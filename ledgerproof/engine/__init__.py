"""Deterministic matching engine.

Seam A: settlement report <-> internal ledger, per transaction, keyed by payment_id.
Pure code, no LLM. Asserts a match only when every check passes to the paisa; anything
it cannot prove becomes an exception (never a forced match). See docs/PRD.md sections 4, 6.
"""

from .seam_a import SeamAEngine
from .models import ExceptionRecord, MatchRecord, ReconResult

__all__ = ["SeamAEngine", "MatchRecord", "ExceptionRecord", "ReconResult"]
