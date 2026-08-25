"""Tax-line matcher (Track-4 direction, additive).

Reconciles the GST-on-MDR tax line independently against policy: for every settled transaction it
re-derives the expected GST (18% of the MDR fee) and compares it to what the settlement report
booked, then aggregates by method and cycle. Reuses the same fee/tax policy the engine uses — a tax
discrepancy is a real reconciliation break, not a rounding disagreement.
"""

from .matcher import TaxLine, TaxReport, match_tax

__all__ = ["TaxLine", "TaxReport", "match_tax"]
