"""Deterministic verifier + governor (Item #4).

Verifier: the CHECK side of search != check. It takes the agent's ONE proposed match and
re-derives it in pure code — it never searches. Governor: even a verified finding auto-resolves
only inside a boundary the finance team set (allowlist + confidence threshold), off by default.
See docs/PRD.md sections 2, 8.
"""

from .verifier import SeamBVerifier
from .governor import Governor
from .models import DecisionRecord, GovernorDecision, VerificationResult

__all__ = ["SeamBVerifier", "Governor", "VerificationResult", "GovernorDecision", "DecisionRecord"]
