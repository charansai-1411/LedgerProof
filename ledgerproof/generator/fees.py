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
    tds: int = 0  # Sec 194-O, 0.1% of gross — applies to every instrument, UPI included

    @property
    def total_deduction(self) -> int:
        return self.mdr_fee + self.gst_on_mdr + self.reserve + self.tds


def compute_fee_line(method: str, gross_amount: int, fees: FeeConfig) -> FeeLine:
    """The full gross-to-net deduction waterfall for one transaction, from policy config:

        net = gross - MDR - GST(18% on MDR) - rolling reserve - TDS(0.1% on gross, Sec 194-O)

    UPI carries mdr_bps=0 and flat=0, so its MDR/GST are zero — the UPI-zero-fee trap: fee-variance
    exceptions must never land on UPI. TDS is a flat 0.1% on gross and DOES apply to UPI (it is a
    marketplace tax on order value, not a payment fee), so it is the one deduction UPI still carries.
    """
    m = fees.methods[method]
    mdr_fee = bps(gross_amount, m["mdr_bps"]) + m["flat_paise"]
    gst_on_mdr = bps(mdr_fee, fees.gst_rate_bps)
    reserve = bps(gross_amount, fees.reserve_rate_bps) if method in fees.reserve_applies_to else 0
    tds = bps(gross_amount, fees.tds_rate_bps)
    return FeeLine(mdr_fee=mdr_fee, gst_on_mdr=gst_on_mdr, reserve=reserve, tds=tds)
