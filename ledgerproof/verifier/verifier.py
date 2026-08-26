"""The deterministic verifier — the CHECK side of search != check.

It takes the agent's ONE proposed match and re-derives it in pure code. It never searches: it
does not look for a better settlement, it only confirms (or refutes) the one the agent proposed.
Re-deriving a stated match is linear; that it is cheap to check is exactly why it was expensive to
find. A finding only counts once every check passes to the paisa.
"""

from __future__ import annotations

from datetime import date

from ..agent.model import AgentFinding
from ..agent.tools import SeamBToolbox
from ..generator.config import FeeConfig
from ..generator.fees import compute_fee_line
from .models import VerificationResult


class SeamBVerifier:
    def __init__(self, min_drift_days: int = 0, max_drift_days: int = 4,
                 fees: FeeConfig | None = None) -> None:
        self.min_drift_days = min_drift_days
        self.max_drift_days = max_drift_days
        self.fees = fees or FeeConfig.load()

    def _fee_claim_holds(self, claim: dict) -> tuple[bool, str]:
        """Re-derive a fee the agent attributed a gap to, from policy. Anti-hallucination guard:
        if the agent claims (say) an MDR fee on UPI — where policy MDR is 0 — the claim is provably
        false and the finding is refused, never auto-resolved. This is 'search != check' turned on
        the agent's own reasoning: the explanation, not just the match, must survive re-derivation."""
        method = claim.get("method", "")
        component = claim.get("component", "mdr")
        gross = int(claim.get("gross", 0))
        claimed = int(claim.get("amount", 0))
        if method not in self.fees.methods:
            return False, f"unknown instrument '{method}'"
        fl = compute_fee_line(method, gross, self.fees)
        expected = {"mdr": fl.mdr_fee, "gst": fl.gst_on_mdr, "tds": fl.tds, "reserve": fl.reserve}.get(component)
        if expected is None:
            return False, f"unknown fee component '{component}'"
        if claimed == expected:
            return True, f"{component} of ₹{claimed/100:,.2f} for {method} matches policy"
        return False, (f"rule constraint violation: policy {component} for {method} is "
                       f"₹{expected/100:,.2f}, agent claimed ₹{claimed/100:,.2f}")

    def verify(
        self, finding: AgentFinding, tools: SeamBToolbox, claimed_counts: dict[str, int]
    ) -> VerificationResult:
        sid = finding.matched_settlement_id

        # An opened finding (no proposed match) has nothing to verify — it is routed to a human,
        # not auto-resolved. Refusing to force a match is the honest, correct outcome.
        if sid is None:
            return VerificationResult(False, "agent opened the credit; no match to verify", {})

        checks: dict[str, bool] = {}
        # If the agent attributed the residual to a fee, that attribution must survive re-derivation
        # from policy before anything else — a hallucinated fee cannot be allowed to justify a match.
        if finding.fee_claim:
            ok, why = self._fee_claim_holds(finding.fee_claim)
            checks["fee_claim_matches_policy"] = ok
            if not ok:
                return VerificationResult(False, why, checks)
        s = tools.get_settlement(sid)
        checks["settlement_exists"] = s is not None
        if s is None:
            return VerificationResult(False, f"proposed settlement {sid} does not exist", checks)

        bc = tools.get_bank_credit(finding.bank_txn_id)

        # Re-derive the settlement's net INDEPENDENTLY from its exploded per-transaction rows,
        # rather than trusting the header amount — the header could itself be wrong.
        rows = tools.explode_settlement(sid)
        rederived_net = sum(r.net_amount for r in rows)
        checks["header_matches_rows"] = rederived_net == s.amount
        checks["net_reconciles_to_credit"] = rederived_net == bc.credit_amount

        # Date drift must be within the plausible T+2+NEFT window.
        drift = (date.fromisoformat(bc.value_date) - date.fromisoformat(s.created_at)).days
        checks["within_window"] = self.min_drift_days <= drift <= self.max_drift_days

        # No other credit may claim the same settlement (one payout -> one credit).
        checks["no_conflict"] = claimed_counts.get(sid, 0) <= 1

        verified = all(checks.values())
        reason = "all checks passed" if verified else "; ".join(k for k, ok in checks.items() if not ok)
        return VerificationResult(verified, reason, checks, rederived_net)
