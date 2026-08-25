"""Service layer: holds the loaded run + mutable policy, answers dashboard queries."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ..agent.heuristic import HeuristicAgentModel
from ..agent.loader import load_seam_b
from ..engine.loader import load_sources
from ..metrics.report import build_report
from ..verifier.config import GovernorConfig
from ..verifier.pipeline import run_pipeline


class ReconService:
    def __init__(self, data_dir: str | Path, policy: GovernorConfig) -> None:
        self.data_dir = Path(data_dir)
        self.policy = policy
        self.model = HeuristicAgentModel()

        eng = load_sources(self.data_dir)
        sb = load_seam_b(self.data_dir)
        self._pay = {p.payment_id: p for p in eng.payments}
        self._report_by_pid = {r.payment_id: r for r in eng.report_rows}
        self._ledger_by_pid = {e.payment_id: e for e in eng.ledger}
        self._settlement = {s.settlement_id: s for s in sb.settlements}
        self._credit = {c.bank_txn_id: c for c in sb.bank_credits}

    # ---- reads ---------------------------------------------------------------
    def report(self) -> dict:
        return build_report(self.data_dir, self.model, self.policy)

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
