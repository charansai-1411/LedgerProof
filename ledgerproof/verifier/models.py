"""Result types for the verifier + governor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..agent.model import AgentFinding

DECISION_AUTO = "auto_resolved"
DECISION_HUMAN = "human_review"


@dataclass
class VerificationResult:
    verified: bool
    reason: str
    checks: dict = field(default_factory=dict)  # name -> bool
    rederived_net: Optional[int] = None


@dataclass
class GovernorDecision:
    decision: str  # DECISION_AUTO | DECISION_HUMAN
    reason: str
    policy: dict = field(default_factory=dict)


@dataclass
class DecisionRecord:
    """A single credit's full journey: finding -> verification -> governor decision.

    This is the audit-trail unit (Item #9 will persist it append-only).
    """

    finding: AgentFinding
    verification: VerificationResult
    governor: GovernorDecision

    def to_audit(self) -> dict:
        rec = self.finding.as_record()
        rec["verification"] = {
            "verified": self.verification.verified,
            "reason": self.verification.reason,
            "checks": self.verification.checks,
            "rederived_net": self.verification.rederived_net,
        }
        rec["governor_decision"] = self.governor.decision
        rec["governor_reason"] = self.governor.reason
        rec["policy"] = self.governor.policy
        rec["reversible"] = True
        return rec
