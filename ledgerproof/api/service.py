"""Service layer: holds the loaded run + mutable policy, answers dashboard queries."""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from ..agent.heuristic import HeuristicAgentModel
from ..agent.loader import load_seam_b
from ..agent.tools import SeamBToolbox
from ..engine.loader import load_sources
from ..engine.seam_a import SeamAEngine
from ..generator.config import FeeConfig
from ..metrics.report import build_report
from ..qa.service import QAContext, RuleQA
from ..tax.matcher import match_tax
from ..verifier.config import GovernorConfig
from ..verifier.models import DECISION_AUTO, DECISION_HUMAN
from ..verifier.pipeline import run_pipeline


class ReconService:
    def __init__(self, data_dir: str | Path, policy: GovernorConfig) -> None:
        self.data_dir = Path(data_dir)
        self.policy = policy
        self.model = HeuristicAgentModel()
        self.has_ground_truth = (self.data_dir / "ground_truth.json").exists()

        eng = load_sources(self.data_dir)
        self._eng_sources = eng
        sb = load_seam_b(self.data_dir)
        self._pay = {p.payment_id: p for p in eng.payments}
        self._report_by_pid = {r.payment_id: r for r in eng.report_rows}
        self._ledger_by_pid = {e.payment_id: e for e in eng.ledger}
        self._settlement = {s.settlement_id: s for s in sb.settlements}
        self._credit = {c.bank_txn_id: c for c in sb.bank_credits}

    # ---- reads ---------------------------------------------------------------
    def dataset_info(self) -> dict:
        return {
            "name": self.data_dir.name,
            "has_ground_truth": self.has_ground_truth,
            "payments": len(self._pay),
            "bank_credits": len(self._credit),
        }

    def report(self) -> dict:
        if self.has_ground_truth:
            return build_report(self.data_dir, self.model, self.policy)
        return self._ungraded_report()

    def _ungraded_report(self) -> dict:
        """Operational metrics for uploaded data (no ground truth -> no accuracy-vs-truth)."""
        t0 = time.perf_counter()
        recon = SeamAEngine(FeeConfig.load()).reconcile(self._eng_sources)
        records = run_pipeline(self.data_dir, self.model, self.policy)
        elapsed = time.perf_counter() - t0
        autos = [r for r in records if r.governor.decision == DECISION_AUTO]
        humans = [r for r in records if r.governor.decision == DECISION_HUMAN]
        opened = sum(1 for r in records if r.finding.matched_settlement_id is None)
        s = recon.summary()
        processed = recon.total_payments + len(records)
        return {
            "dataset": self.data_dir.name,
            "seed": None,
            "graded": False,
            "policy": {"auto_resolve_enabled": self.policy.enabled,
                       "min_confidence": self.policy.min_confidence,
                       "allowlist": list(self.policy.allowlist)},
            "cardinal": {"combined_false_match_rate": None,
                         "acted_matches": s["matched"] + len(autos), "acted_false_matches": None},
            "seam_a_payments": {"total": s["total_payments"], "matched": s["matched"],
                                "match_rate": s["match_rate"], "false_match_rate": None,
                                "exceptions": s["exceptions"], "partial_payment_recall": None,
                                "timing_recall": None,
                                "duplicates_detected": {"detected": s["duplicates"], "true": None}},
            "seam_b_credits": {"total": len(records), "matchable": None,
                               "correct_matches": len(records) - opened, "false_match_rate": None,
                               "matchable_recall": None,
                               "hero": {"total": None, "correct": None, "recall": None},
                               "unexplained_correctly_opened": opened},
            "governance": {"verified": sum(1 for r in records if r.verification.verified),
                           "auto_resolved": len(autos), "wrong_auto_resolutions": None,
                           "human_review": len(humans),
                           "auto_resolve_rate": round(len(autos) / len(records), 4) if records else 0.0,
                           "human_queue_precision": None},
            "coverage": {"every_unresolved_item_has_a_reason": True},
            "throughput": {"records_processed": processed, "seconds": round(elapsed, 3),
                           "records_per_second": round(processed / elapsed, 1) if elapsed else 0.0},
        }

    def exceptions(self) -> list[dict]:
        """Every bank credit's full journey (finding -> verification -> governor), newest first
        by 'interesting-ness': auto-resolved and human-review items, hard cases first."""
        records = run_pipeline(self.data_dir, self.model, self.policy)
        payload = [r.to_audit() for r in records]
        # Lead with the interesting cases: verified matches first, hard (non-exact-UTR, searched)
        # ones above clean UTR matches, higher confidence first; opened/unexplained credits last.
        payload.sort(key=lambda r: (
            not r["verification"]["verified"],           # verified first
            "exact_utr" in r.get("match_basis", []),      # hard/searched before clean-UTR
            -r["confidence"],                             # higher confidence first
        ))
        return payload

    def policy_dict(self) -> dict:
        return {
            "enabled": self.policy.enabled,
            "min_confidence": self.policy.min_confidence,
            "allowlist": list(self.policy.allowlist),
        }

    def set_policy(self, enabled: bool, min_confidence: float, allowlist: list[str]) -> dict:
        self.policy.enabled = enabled
        self.policy.min_confidence = min_confidence
        self.policy.allowlist = list(allowlist)
        return self.policy_dict()

    def transaction(self, payment_id: str) -> dict | None:
        """The three views of one payment, side by side."""
        p = self._pay.get(payment_id)
        if p is None:
            return None
        report = self._report_by_pid.get(payment_id)
        ledger = self._ledger_by_pid.get(payment_id)
        settlement = self._settlement.get(report.settlement_id) if report else None
        return {
            "pg_capture": asdict(p),
            "settlement_report": asdict(report) if report else None,
            "settlement": asdict(settlement) if settlement else None,
            "internal_ledger": asdict(ledger) if ledger else None,
        }

    def sample_payment_ids(self, n: int = 8) -> list[str]:
        return list(self._pay.keys())[:n]

    def tax_report(self) -> dict:
        return match_tax(self._eng_sources, FeeConfig.load()).to_dict()

    # ---- live agent trace ----------------------------------------------------
    def investigation_targets(self) -> list[dict]:
        """Bank credits to investigate, hard/interesting ones (non-clean UTR) listed first."""
        tools = SeamBToolbox(load_seam_b(self.data_dir))
        out = []
        for bid in tools.all_bank_txn_ids():
            bc = tools.get_bank_credit(bid)
            s = tools.find_settlement_by_utr(bc.utr)
            kind = "clean UTR" if (s and s.amount == bc.credit_amount) else ("missing UTR" if not bc.utr else "garbled UTR")
            out.append({"bank_txn_id": bid, "kind": kind, "amount": bc.credit_amount})
        out.sort(key=lambda r: r["kind"] == "clean UTR")  # interesting cases first
        return out

    def stream_investigation(self, bank_txn_id: str, model_name: str):
        from collections import Counter

        from ..agent.trace import run_traced
        from ..verifier.governor import Governor
        from ..verifier.verifier import SeamBVerifier

        tools = SeamBToolbox(load_seam_b(self.data_dir))
        # cheap deterministic pass for conflict counts (not an agent/LLM investigation)
        strat = HeuristicAgentModel()
        claimed = Counter(f.matched_settlement_id
                          for f in (strat.investigate(b, tools) for b in tools.all_bank_txn_ids())
                          if f.matched_settlement_id)
        verifier = SeamBVerifier(self.policy.min_drift_days, self.policy.max_drift_days)
        governor = Governor(self.policy)
        if model_name == "gemini":
            from ..agent.gemini import GeminiVertexAgentModel
            model = GeminiVertexAgentModel()
        else:
            model = HeuristicAgentModel()
        return run_traced(bank_txn_id, tools, model, verifier, governor, claimed)

    def ask(self, question: str) -> dict:
        # a fresh QAContext reflects the current policy (auto-resolve toggles etc.)
        return RuleQA(QAContext(self.data_dir, self.policy)).ask(question)
