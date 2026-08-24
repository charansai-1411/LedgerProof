"""Deterministic fee / GST / reserve arithmetic. Integer paise only.

Rounding is half-up on the /10000 basis-points division, defined once here and documented,
so the generator and the engine round identically — a fee break must come from real policy,
never from a rounding disagreement between two code paths.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import FeeConfig


def bps(amount: int, rate_bps: int) -> int:
    """amount * rate_bps / 10000, rounded half-up, in integer paise."""
    return (amount * rate_bps + 5000) // 10000


@dataclass
class FeeLine:
    mdr_fee: int
    gst_on_mdr: int
    reserve: int

    @property
    def total_deduction(self) -> int:
        return self.mdr_fee + self.gst_on_mdr + self.reserve


def compute_fee_line(method: str, gross_amount: int, fees: FeeConfig) -> FeeLine:
    """MDR + GST-on-MDR + rolling reserve for one transaction, from policy config.

    UPI carries mdr_bps=0 and flat=0, so its fee line is zero — the UPI-zero-fee trap:
    UPI transactions have no fee gap, so fee-variance exceptions must never land on UPI.
    """
    m = fees.methods[method]
    mdr_fee = bps(gross_amount, m["mdr_bps"]) + m["flat_paise"]
    gst_on_mdr = bps(mdr_fee, fees.gst_rate_bps)
    reserve = bps(gross_amount, fees.reserve_rate_bps) if method in fees.reserve_applies_to else 0
    return FeeLine(mdr_fee=mdr_fee, gst_on_mdr=gst_on_mdr, reserve=reserve)
