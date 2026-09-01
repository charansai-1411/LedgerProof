"""Idempotent resolution writes (critique 16).

Submitting the same reconciliation run twice must NOT create duplicate resolutions or duplicate
ledger adjustments. Each decision gets a deterministic `decision_id` derived from
(run_id, bank_txn_id, matched_settlement_id, decision); the store keys on that as the
`idempotency_key`, so a re-applied decision is a no-op, not a second write.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def run_id_for(seed, dataset: str) -> str:
    """A stable id for one reconciliation run — same seed+dataset → same run_id."""
    return hashlib.sha256(f"{dataset}:{seed}".encode()).hexdigest()[:16]


def decision_id_for(run_id: str, bank_txn_id: str, settlement_id, decision: str) -> str:
    key = f"{run_id}|{bank_txn_id}|{settlement_id}|{decision}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


@dataclass
class ResolutionStore:
    """In-memory idempotent store. `apply` returns True on first write, False on a duplicate."""

    _applied: dict[str, dict] = field(default_factory=dict)
    duplicates_suppressed: int = 0

    def apply(self, idempotency_key: str, resolution: dict) -> bool:
        if idempotency_key in self._applied:
            self.duplicates_suppressed += 1
            return False
        self._applied[idempotency_key] = resolution
        return True

    def __len__(self) -> int:
        return len(self._applied)
