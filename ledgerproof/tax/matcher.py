"""Deterministic GST-on-MDR reconciliation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..engine.loader import Sources
from ..generator.config import FeeConfig
from ..generator.fees import bps


@dataclass
class TaxLine:
    payment_id: str
    method: str
    mdr_fee: int          # paise
    reported_gst: int     # paise — what the settlement report booked
    expected_gst: int     # paise — 18% of MDR per policy
    ok: bool


@dataclass
class TaxReport:
    total_mdr: int = 0
    total_gst_reported: int = 0
    total_gst_expected: int = 0
    transactions: int = 0
    taxable_transactions: int = 0            # those with a non-zero MDR (UPI has none)
    discrepancies: list[TaxLine] = field(default_factory=list)
    by_method: dict = field(default_factory=dict)

    @property
    def effective_rate_bps(self) -> int:
        return round(self.total_gst_reported * 10000 / self.total_mdr) if self.total_mdr else 0

    def to_dict(self) -> dict:
        return {
            "total_mdr": self.total_mdr,
            "total_gst_reported": self.total_gst_reported,
            "total_gst_expected": self.total_gst_expected,
            "effective_rate_bps": self.effective_rate_bps,
            "transactions": self.transactions,
            "taxable_transactions": self.taxable_transactions,
            "discrepancy_count": len(self.discrepancies),
            "gst_reconciles": len(self.discrepancies) == 0
            and self.total_gst_reported == self.total_gst_expected,
            "by_method": self.by_method,
            "discrepancies": [
                {"payment_id": d.payment_id, "method": d.method, "mdr_fee": d.mdr_fee,
                 "reported_gst": d.reported_gst, "expected_gst": d.expected_gst}
                for d in self.discrepancies[:50]
            ],
        }


def match_tax(sources: Sources, fees: FeeConfig) -> TaxReport:
    method_by_pid = {p.payment_id: p.method for p in sources.payments}
    report = TaxReport()
    by_method: dict[str, dict] = defaultdict(lambda: {"mdr": 0, "gst": 0, "count": 0})

    for r in sources.report_rows:
        method = method_by_pid.get(r.payment_id, "unknown")
        expected = bps(r.mdr_fee, fees.gst_rate_bps)  # 18% of MDR, same rounding as the engine
        ok = r.gst_on_mdr == expected
        line = TaxLine(r.payment_id, method, r.mdr_fee, r.gst_on_mdr, expected, ok)

        report.transactions += 1
        report.total_mdr += r.mdr_fee
        report.total_gst_reported += r.gst_on_mdr
        report.total_gst_expected += expected
        if r.mdr_fee > 0:
            report.taxable_transactions += 1
        if not ok:
            report.discrepancies.append(line)

        m = by_method[method]
        m["mdr"] += r.mdr_fee
        m["gst"] += r.gst_on_mdr
        m["count"] += 1

    report.by_method = {
        k: {**v, "effective_rate_bps": round(v["gst"] * 10000 / v["mdr"]) if v["mdr"] else 0}
        for k, v in by_method.items()
    }
    return report
