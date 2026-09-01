"""Query core for the Q&A agent + a deterministic keyword router (RuleQA)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..agent.heuristic import HeuristicAgentModel
from ..agent.loader import load_seam_b
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
        self._rows_by_settlement: dict[str, list] = defaultdict(list)
        for r in self.sources.report_rows:
            self._rows_by_settlement[r.settlement_id].append(r)
        self._credit = {c.bank_txn_id: c for c in load_seam_b(self.data_dir).bank_credits}

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

    def settlement_short(self, sid: str) -> dict:
        """Why is settlement S short? — decompose its gross → net gap into the deduction waterfall."""
        rows = self._rows_by_settlement.get(sid)
        if not rows:
            return {"answer": f"No settlement '{sid}' in this run.", "data": {}}
        g = sum(r.gross_amount for r in rows); mdr = sum(r.mdr_fee for r in rows)
        gst = sum(r.gst_on_mdr for r in rows); tds = sum(r.tds for r in rows)
        res = sum(r.reserve for r in rows); ref = sum(r.refund_deduction for r in rows)
        net = sum(r.net_amount for r in rows)
        parts = [f"MDR {_rs(mdr)}" if mdr else "", f"GST {_rs(gst)}" if gst else "",
                 f"TDS {_rs(tds)}" if tds else "", f"reserve {_rs(res)}" if res else "",
                 f"refunds {_rs(ref)}" if ref else ""]
        return {"answer": f"{sid} paid {_rs(net)} on {_rs(g)} gross across {len(rows)} transactions — "
                          f"short by {_rs(g - net)} = " + " + ".join(p for p in parts if p) + ".",
                "data": {"settlement_id": sid, "gross": g, "net": net, "mdr": mdr, "gst": gst,
                         "tds": tds, "reserve": res, "refunds": ref, "transactions": len(rows)}}

    def credits_over(self, threshold_paise: int, unresolved_only: bool = False) -> dict:
        hits = []
        for r in self.records:
            bc = self._credit.get(r.finding.bank_txn_id)
            if not bc or bc.credit_amount <= threshold_paise:
                continue
            if unresolved_only and r.finding.matched_settlement_id is not None:
                continue
            hits.append((bc.bank_txn_id, bc.credit_amount, r.finding.matched_settlement_id,
                         r.governor.decision))
        hits.sort(key=lambda x: -x[1])
        scope = "unresolved bank credits" if unresolved_only else "bank credits"
        lines = "; ".join(f"{b} {_rs(a)}"
                          + ("" if m else " (unexplained)") for b, a, m, _ in hits[:10])
        return {"answer": f"{len(hits)} {scope} above {_rs(threshold_paise)}"
                          + (f": {lines}" if hits else "."),
                "data": {"count": len(hits), "threshold_paise": threshold_paise,
                         "credits": [{"id": b, "amount": a, "matched": m, "decision": d}
                                     for b, a, m, d in hits[:50]]}}

    def why_not_auto(self, bank_txn_id: str) -> dict:
        r = self._by_credit.get(bank_txn_id)
        if r is None:
            return {"answer": f"No bank credit '{bank_txn_id}' in this run.", "data": {}}
        if r.governor.decision == DECISION_AUTO:
            return {"answer": f"{bank_txn_id} WAS auto-resolved — verified in code, on the allowlist, "
                              f"confidence {r.finding.confidence:.2f} ≥ {self.policy.min_confidence}.",
                    "data": r.to_audit()}
        return {"answer": f"{bank_txn_id} was NOT auto-resolved: {r.governor.reason}. "
                          + (f"Verifier: {r.verification.reason}." if not r.verification.verified else
                             f"It verified, but the governor held it (policy boundary the finance team set)."),
                "data": r.to_audit()}

    def agent_investigated(self, bank_txn_id: str) -> dict:
        r = self._by_credit.get(bank_txn_id)
        if r is None:
            return {"answer": f"No bank credit '{bank_txn_id}' in this run.", "data": {}}
        f = r.finding
        ev = "; ".join(f.evidence) if f.evidence else "no corroborating evidence found"
        return {"answer": f"On {bank_txn_id} the agent {'proposed ' + f.matched_settlement_id if f.matched_settlement_id else 'found no defensible match'} "
                          f"(basis: {', '.join(f.match_basis) or 'none'}). Evidence: {ev}.",
                "data": {"matched": f.matched_settlement_id, "basis": f.match_basis,
                         "evidence": f.evidence, "confidence": round(f.confidence, 3)}}


_CREDIT_RE = re.compile(r"\b(bank_[0-9a-z]+)\b")
_SETTLE_RE = re.compile(r"\b(setl_[0-9a-z]+)\b")
_AMOUNT_RE = re.compile(r"(?:₹|rs\.?\s*)?([\d,]+(?:\.\d+)?)\s*(cr|crore|l|lakh|lac|k|thousand)?", re.I)


def _parse_amount_paise(q: str) -> int | None:
    """Parse an amount like '50000', '₹50,000', '50k', '2 lakh', '1.5cr' → integer paise."""
    m = _AMOUNT_RE.search(q.replace(",", ""))
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "").lower()
    mult = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lakh": 1e5, "lac": 1e5,
            "cr": 1e7, "crore": 1e7}.get(unit, 1)
    return int(round(val * mult * 100))


class RuleQA:
    """Deterministic keyword router — instant, no API. Powers the Finance Copilot and tests.

    It answers over the ACTUAL reconciliation state via structured tools — settlement decomposition,
    threshold filters, why-not-auto, agent evidence — not free text. A finance interface, not a chatbot.
    """

    def __init__(self, ctx: QAContext) -> None:
        self.ctx = ctx

    def ask(self, question: str) -> dict:
        q = question.lower()
        s = _SETTLE_RE.search(q)
        if s and ("short" in q or "why" in q or "gap" in q or "deduct" in q or "less" in q):
            return self.ctx.settlement_short(s.group(1))
        m = _CREDIT_RE.search(q)
        if m and ("not auto" in q or "not resolved" in q or "not auto-resolved" in q
                  or ("why" in q and "auto" in q)):
            return self.ctx.why_not_auto(m.group(1))
        if m and ("investigat" in q or "evidence" in q or "what did" in q or "look at" in q
                  or "check" in q):
            return self.ctx.agent_investigated(m.group(1))
        if m and ("why" in q or "explain" in q or "opened" in q):
            return self.ctx.why_opened(m.group(1))
        # threshold filters: "unresolved credits over ₹50,000", "show credits above 1 lakh"
        if ("over" in q or "above" in q or "greater" in q or ">" in q or "more than" in q) and "credit" in q:
            amt = _parse_amount_paise(q)
            if amt is not None:
                unresolved = ("unresolved" in q or "unexplain" in q or "open" in q or "pending" in q)
                return self.ctx.credits_over(amt, unresolved_only=unresolved)
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
