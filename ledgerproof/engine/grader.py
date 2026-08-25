"""Grade a Seam-A reconciliation against the generator's hidden ground truth.

Kept separate from the engine on purpose: the engine reads only the sources, the grader reads
only the answer key. The cardinal metric is the FALSE-MATCH RATE — a match the engine asserted
that ground truth says is actually a break. Target: zero.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    CAT_DUPLICATE,
    CAT_LEDGER_BOOKING_MISMATCH,
    CAT_NOT_SETTLED,
    ReconResult,
)

# Ground-truth variance labels that mean "this payment must NOT be matched by Seam A".
# (DUPLICATE is not here: the underlying payment is a valid match; the duplicate ROW is the issue,
#  tracked separately via result.duplicates.)
MUST_NOT_MATCH = {"PARTIAL_PAYMENT", "TIMING_IN_TRANSIT"}

# Which engine exception category is expected for each true break label.
EXPECTED_CATEGORY = {
    "PARTIAL_PAYMENT": CAT_LEDGER_BOOKING_MISMATCH,
    "TIMING_IN_TRANSIT": CAT_NOT_SETTLED,
}


def load_ground_truth(data_dir: str | Path) -> dict:
    return json.loads((Path(data_dir) / "ground_truth.json").read_text(encoding="utf-8"))


def grade(result: ReconResult, ground_truth: dict) -> dict:
    labels: dict[str, str] = ground_truth["variance_labels"]
    true_partial = {pid for pid, l in labels.items() if l == "PARTIAL_PAYMENT"}
    true_timing = {pid for pid, l in labels.items() if l == "TIMING_IN_TRANSIT"}
    true_dupes = {pid for pid, l in labels.items() if l == "DUPLICATE"}
    must_not_match = true_partial | true_timing

    matched_ids = {m.payment_id for m in result.matched}
    exc_by_pid = {e.payment_id: e.category for e in result.exceptions}

    # cardinal metric: matches the engine asserted that are actually breaks
    false_matches = sorted(matched_ids & must_not_match)

    # per-break recall + category correctness
    def recall(true_ids: set[str], expected_cat: str) -> dict:
        flagged = {pid for pid in true_ids if pid in exc_by_pid}
        correct_cat = {pid for pid in flagged if exc_by_pid[pid] == expected_cat}
        return {
            "true": len(true_ids),
            "flagged": len(flagged),
            "correct_category": len(correct_cat),
            "recall": round(len(flagged) / len(true_ids), 4) if true_ids else 1.0,
        }

    matched = len(matched_ids)
    return {
        "match_rate": result.summary()["match_rate"],
        "matched": matched,
        "exceptions": len(result.exceptions),
        "false_match_rate": round(len(false_matches) / matched, 6) if matched else 0.0,
        "false_matches": false_matches,  # target: []
        "partial_payment": recall(true_partial, CAT_LEDGER_BOOKING_MISMATCH),
        "timing_in_transit": recall(true_timing, CAT_NOT_SETTLED),
        "duplicates_detected": {
            "true": len(true_dupes),
            "detected": len(set(result.duplicates) & true_dupes),
        },
    }
