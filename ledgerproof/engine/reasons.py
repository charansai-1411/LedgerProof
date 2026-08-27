"""The reason-code taxonomy (PRD §8): status ≠ reason.

`match_status` says what happened; `resolution_type` says how a match was proven; `exception_reason`
says why an item could not be proven. Keeping these three orthogonal is what lets the dashboard show
a precise, auditable reason for every unresolved item — never a vague "unmatched".
"""

from __future__ import annotations

from .models import (
    CAT_DUPLICATE,
    CAT_FEE_CONFIG_MISMATCH,
    CAT_GROSS_MISMATCH,
    CAT_LEDGER_BOOKING_MISMATCH,
    CAT_NOT_SETTLED,
    CAT_REPORT_INCONSISTENT,
)

# match_status
MATCHED = "MATCHED"
EXCEPTION = "EXCEPTION"
HUMAN_REVIEW = "HUMAN_REVIEW"

# resolution_type — how a proven/proposed match was reached
EXACT = "EXACT"
TOLERANCE = "TOLERANCE"
SPLIT = "SPLIT"
RULE_BASED = "RULE_BASED"
AGENT_VERIFIED = "AGENT_VERIFIED"

# exception_reason — why an item could not be proven
NO_CANDIDATE = "NO_CANDIDATE"
AMBIGUOUS_CANDIDATE = "AMBIGUOUS_CANDIDATE"
TOLERANCE_EXCEEDED = "TOLERANCE_EXCEEDED"
SPLIT_UNRESOLVED = "SPLIT_UNRESOLVED"
TIMING_WINDOW_MISS = "TIMING_WINDOW_MISS"
DUPLICATE_REFERENCE = "DUPLICATE_REFERENCE"
REFUND_UNRESOLVED = "REFUND_UNRESOLVED"
COMPOUND_UNRESOLVED = "COMPOUND_UNRESOLVED"
MISSING_SOURCE = "MISSING_SOURCE"
UNEXPLAINED = "UNEXPLAINED"

# engine (Seam-A) category -> exception_reason
CAT_TO_REASON = {
    CAT_NOT_SETTLED: TIMING_WINDOW_MISS,
    CAT_LEDGER_BOOKING_MISMATCH: COMPOUND_UNRESOLVED,
    CAT_DUPLICATE: DUPLICATE_REFERENCE,
    CAT_GROSS_MISMATCH: MISSING_SOURCE,
    CAT_FEE_CONFIG_MISMATCH: UNEXPLAINED,
    CAT_REPORT_INCONSISTENT: UNEXPLAINED,
}

_ACTIONS = {
    NO_CANDIDATE: "Escalate — no settlement explains this credit within the valid window.",
    AMBIGUOUS_CANDIDATE: "Human review — more than one settlement is a plausible match; do not force one.",
    TOLERANCE_EXCEEDED: "Review — the amount gap is outside the configured tolerance band.",
    SPLIT_UNRESOLVED: "Human review — no constrained combination of captures reconciles to this credit.",
    TIMING_WINDOW_MISS: "Await the next settlement cycle, or investigate if it never settles.",
    DUPLICATE_REFERENCE: "Data-quality review — the same reference appears more than once.",
    REFUND_UNRESOLVED: "Locate the offsetting refund, then re-verify the net.",
    COMPOUND_UNRESOLVED: "Book the fee / GST / refund adjustment (see the journal entry), then approve.",
    MISSING_SOURCE: "Source record is missing — obtain it before reconciling.",
    UNEXPLAINED: "Human review — no rule and no defensible hypothesis; never force a match.",
}


def suggest_action(reason: str) -> str:
    return _ACTIONS.get(reason, "Human review.")


def delta_percent(delta_paise: int, base_paise: int) -> float:
    """Signed percentage of the gap against a base amount (0.0 if base is 0)."""
    return round(delta_paise * 100 / base_paise, 3) if base_paise else 0.0
