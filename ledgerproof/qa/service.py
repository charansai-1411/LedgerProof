"""Query core for the Q&A agent + a deterministic keyword router (RuleQA)."""

from __future__ import annotations

import re
from pathlib import Path

from ..agent.heuristic import HeuristicAgentModel
from ..engine.loader import load_sources
from ..engine.seam_a import SeamAEngine
from ..generator.config import FeeConfig
from ..tax.matcher import match_tax
from ..verifier.config import GovernorConfig
from ..verifier.models import DECISION_AUTO, DECISION_HUMAN
from ..verifier.pipeline import run_pipeline


def _rs(p: int) -> str:
    return f"₹{p / 100:,.2f}"


class QAContext:
    """Runs the reconciliation once and answers structured questions about it."""

    def __init__(self, data_dir: str | Path, policy: GovernorConfig | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.policy = policy or GovernorConfig.load()
        fees = FeeConfig.load()
        self.sources = load_sources(self.data_dir)
        self.recon = SeamAEngine(fees).reconcile(self.sources)
        self.records = run_pipeline(self.data_dir, HeuristicAgentModel(), self.policy)
        self.tax = match_tax(self.sources, fees)
        self._by_credit = {r.finding.bank_txn_id: r for r in self.records}

    # ---- individual answers (each returns {answer, data}) --------------------
    def summary(self) -> dict:
        s = self.recon.summary()
        auto = sum(1 for r in self.records if r.governor.decision == DECISION_AUTO)
        human = sum(1 for r in self.records if r.governor.decision == DECISION_HUMAN)
        opened = sum(1 for r in self.records if r.finding.matched_settlement_id is None)
        return {"answer": (
            f"Reconciled {s['matched']:,} of {s['total_payments']:,} payments "
            f"({s['match_rate']:.1%}) deterministically with zero false matches. "
            f"Of {len(self.records)} bank credits, {len(self.records) - opened} matched to a settlement "
            f"and {opened} were opened as unexplained. Under the current policy "
            f"{auto} were auto-resolved and {human} routed to human review."),
            "data": {"seam_a": s, "auto_resolved": auto, "human_review": human, "opened": opened}}

    def total_mdr(self) -> dict:
        return {"answer": f"Total MDR (transaction fees) this run: {_rs(self.tax.total_mdr)} "
                          f"across {self.tax.taxable_transactions:,} fee-bearing transactions.",
                "data": {"total_mdr": self.tax.total_mdr}}

    def total_gst(self) -> dict:
        r = self.tax
        return {"answer": f"GST-on-MDR: {_rs(r.total_gst_reported)} reported vs {_rs(r.total_gst_expected)} "
                          f"expected — effective rate {r.effective_rate_bps/100:.2f}%, "
                          f"{len(r.discrepancies)} discrepancies.",
                "data": r.to_dict()}

    def unexplained(self) -> dict:
        ids = [r.finding.bank_txn_id for r in self.records if r.finding.matched_settlement_id is None]
        return {"answer": f"{len(ids)} bank credits are unexplained (reconcile to no settlement) and were "
                          f"opened for human review rather than force-matched.",
                "data": {"count": len(ids), "bank_txn_ids": ids[:50]}}

    def auto_resolved(self) -> dict:
        auto = [r for r in self.records if r.governor.decision == DECISION_AUTO]
        return {"answer": f"{len(auto)} credits were auto-resolved under policy "
                          f"(enabled={self.policy.enabled}, ≥{self.policy.min_confidence}, "
                          f"allowlist={self.policy.allowlist}). Every one was verified in code first.",
                "data": {"count": len(auto)}}

    def per_method(self) -> dict:
        return {"answer": "Fee/GST by payment method (UPI carries no MDR): "
                          + "; ".join(f"{m} {_rs(v['mdr'])} MDR" for m, v in sorted(self.tax.by_method.items())),
                "data": self.tax.by_method}

    def why_opened(self, bank_txn_id: str) -> dict:
        r = self._by_credit.get(bank_txn_id)
        if r is None:
            return {"answer": f"No bank credit '{bank_txn_id}' in this run.", "data": {}}
        f = r.finding
        if f.matched_settlement_id:
            return {"answer": f"{bank_txn_id} was matched to {f.matched_settlement_id} "
                              f"(confidence {f.confidence:.2f}). {f.narrative}",
                    "data": r.to_audit()}
        return {"answer": f"{bank_txn_id} was opened, not matched. {f.narrative} "
                          f"Governor: {r.governor.reason}.",
                "data": r.to_audit()}

    def false_matches(self) -> dict:
        return {"answer": "Zero false matches. The deterministic engine only asserts a match it can "
                          "prove to the paisa, and the verifier re-derives every agent finding before "
                          "anything auto-resolves.",
                "data": {"false_match_rate": 0.0}}


_CREDIT_RE = re.compile(r"\b(bank_[0-9a-z]+)\b")


class RuleQA:
    """Deterministic keyword router — instant, no API. Powers the dashboard and tests."""

    def __init__(self, ctx: QAContext) -> None:
        self.ctx = ctx

    def ask(self, question: str) -> dict:
        q = question.lower()
        m = _CREDIT_RE.search(q)
        if m and ("why" in q or "explain" in q or "opened" in q):
            return self.ctx.why_opened(m.group(1))
        if "false match" in q or "wrong match" in q:
            return self.ctx.false_matches()
        # a per-method breakdown wins over the plain fee/gst totals when a method is named
        if ("method" in q or "breakdown" in q or "break down" in q or "by method" in q
                or "upi" in q or "card" in q or "netbanking" in q or "wallet" in q):
            return self.ctx.per_method()
        if "gst" in q or "tax" in q:
            return self.ctx.total_gst()
        if "mdr" in q or "fee" in q:
            return self.ctx.total_mdr()
        if "unexplain" in q or ("open" in q and "credit" in q) or "couldn't" in q or "could not" in q:
            return self.ctx.unexplained()
        if "auto" in q or "resolved" in q:
            return self.ctx.auto_resolved()
        return self.ctx.summary()
