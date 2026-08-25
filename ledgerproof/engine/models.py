"""Result types for the matching engine. All amounts are integer paise."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Exception categories the deterministic engine can assign (Seam A).
# These route to the exception agent or the human queue; the engine never resolves them.
CAT_NOT_SETTLED = "LEDGER_ENTRY_NOT_SETTLED"  # in ledger, no settlement report row -> timing candidate
CAT_GROSS_MISMATCH = "GROSS_MISMATCH"  # report gross != PG capture
CAT_FEE_CONFIG_MISMATCH = "FEE_CONFIG_MISMATCH"  # report's stated MDR/GST != policy
CAT_REPORT_INCONSISTENT = "REPORT_INCONSISTENT"  # report net != recomputed net
CAT_LEDGER_BOOKING_MISMATCH = "LEDGER_BOOKING_MISMATCH"  # booked != gross-of-refund -> compound/partial
CAT_DUPLICATE = "DUPLICATE"  # same payment_id appears more than once in a source


@dataclass
class MatchRecord:
    """A proven Seam-A reconciliation. Carries its evidence so it is auditable."""

    payment_id: str
    settlement_id: str
    method: str
    gross_amount: int
    net_amount: int
    evidence: dict = field(default_factory=dict)


@dataclass
class ExceptionRecord:
    """A record the engine could not prove. Never a forced match."""

    payment_id: str
    category: str
    detail: str
    expected: Optional[int] = None
    actual: Optional[int] = None
    settlement_id: Optional[str] = None


@dataclass
class ReconResult:
    matched: list[MatchRecord] = field(default_factory=list)
    exceptions: list[ExceptionRecord] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)  # payment_ids seen more than once
    total_payments: int = 0

    def summary(self) -> dict:
        by_cat: dict[str, int] = {}
        for e in self.exceptions:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
        matched = len(self.matched)
        rate = matched / self.total_payments if self.total_payments else 0.0
        return {
            "total_payments": self.total_payments,
            "matched": matched,
            "match_rate": round(rate, 4),
            "exceptions": len(self.exceptions),
            "exceptions_by_category": by_cat,
            "duplicates": len(self.duplicates),
        }
