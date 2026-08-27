"""The governor — controlled autonomy.

Even a verified finding auto-resolves only if (a) auto-resolve is enabled, (b) its break category
is on the finance-team allowlist, and (c) confidence >= the configured threshold. Every default is
conservative: auto-resolve is off until explicitly enabled per category. Everything else goes to
the human review queue. The system *can* act, but only inside a boundary a human set.
"""

from __future__ import annotations

from ..agent.model import AgentFinding
from .config import GovernorConfig
from .models import DECISION_AUTO, DECISION_HUMAN, GovernorDecision, VerificationResult


class Governor:
    def __init__(self, cfg: GovernorConfig) -> None:
        self.cfg = cfg

    def _policy(self) -> dict:
        return {
            "enabled": self.cfg.enabled,
            "min_confidence": self.cfg.min_confidence,
            "allowlist": list(self.cfg.allowlist),
            "version": self.cfg.version,
        }

    def decide(self, finding: AgentFinding, verification: VerificationResult) -> GovernorDecision:
        policy = self._policy()

        if not verification.verified:
            return GovernorDecision(DECISION_HUMAN, f"not verified ({verification.reason})", policy)
        if not self.cfg.enabled:
            return GovernorDecision(DECISION_HUMAN, "auto-resolve disabled (master switch off)", policy)
        if finding.break_type not in self.cfg.allowlist:
            return GovernorDecision(DECISION_HUMAN, f"category '{finding.break_type}' not on allowlist", policy)
        if finding.confidence < self.cfg.min_confidence:
            return GovernorDecision(
                DECISION_HUMAN,
                f"confidence {finding.confidence:.2f} < threshold {self.cfg.min_confidence:.2f}",
                policy,
            )
        return GovernorDecision(DECISION_AUTO, "verified, on allowlist, confidence above threshold", policy)
