"""Seam-A deterministic matching engine.

Reconciles each PG capture <-> settlement report row <-> internal ledger entry, per payment_id,
re-deriving every deduction from policy (configs/fees.yaml). A payment is MATCHED only when all
of the following hold to the paisa:

  1. the report's gross equals the PG capture,
  2. the report's stated MDR and GST equal what policy computes (fees are policy, not assertion),
  3. the report's net equals gross - MDR - GST - refund - reserve (report is internally consistent),
  4. the ledger booked amount equals gross-of-refund (the merchant booked the right principal).

Anything that fails becomes an exception with a category — never a forced match. This is the
"a false match is the cardinal sin" principle in code: the engine opens an item when it cannot
prove a match, and routes it onward (agent or human).
"""

from __future__ import annotations

from collections import Counter

from ..generator.config import FeeConfig
from ..generator.fees import compute_fee_line
from ..generator.models import LedgerEntry, Payment, SettlementReportRow
from .loader import Sources
from .models import (
    CAT_DUPLICATE,
    CAT_FEE_CONFIG_MISMATCH,
    CAT_GROSS_MISMATCH,
    CAT_LEDGER_BOOKING_MISMATCH,
    CAT_NOT_SETTLED,
    CAT_REPORT_INCONSISTENT,
    ExceptionRecord,
    MatchRecord,
    ReconResult,
)


class SeamAEngine:
    def __init__(self, fees: FeeConfig) -> None:
        self.fees = fees

    def reconcile(self, sources: Sources) -> ReconResult:
        report_by_pid: dict[str, SettlementReportRow] = {r.payment_id: r for r in sources.report_rows}
        ledger_by_pid: dict[str, LedgerEntry] = {e.payment_id: e for e in sources.ledger}

        # duplicate detection: a payment_id appearing more than once in the PG source
        pid_counts = Counter(p.payment_id for p in sources.payments)
        duplicates = sorted(pid for pid, n in pid_counts.items() if n > 1)

        result = ReconResult(duplicates=duplicates)
        seen: set[str] = set()
        for p in sources.payments:
            if p.payment_id in seen:
                continue  # reconcile each unique payment once; the repeat is tracked as a duplicate
            seen.add(p.payment_id)
            self._reconcile_one(p, report_by_pid.get(p.payment_id), ledger_by_pid.get(p.payment_id), result)

        result.total_payments = len(seen)
        return result

    def _reconcile_one(
        self,
        p: Payment,
        report: SettlementReportRow | None,
        ledger: LedgerEntry | None,
        result: ReconResult,
    ) -> None:
        # 0. not yet settled -> timing candidate (agent disambiguates in-transit vs missing)
        if report is None:
            result.exceptions.append(
                ExceptionRecord(
                    payment_id=p.payment_id,
                    category=CAT_NOT_SETTLED,
                    detail="ledger/PG entry has no settlement report row",
                )
            )
            return

        refund = report.refund_deduction
        exp = compute_fee_line(p.method, p.captured_amount, self.fees)

        # 1. report gross must equal the capture
        if report.gross_amount != p.captured_amount:
            return self._exc(result, p, report, CAT_GROSS_MISMATCH, "report gross != PG capture",
                             expected=p.captured_amount, actual=report.gross_amount)

        # 2. stated fees must equal policy (a fee that disagrees with config is not a proven match)
        if report.mdr_fee != exp.mdr_fee:
            return self._exc(result, p, report, CAT_FEE_CONFIG_MISMATCH, "MDR != policy",
                             expected=exp.mdr_fee, actual=report.mdr_fee)
        if report.gst_on_mdr != exp.gst_on_mdr:
            return self._exc(result, p, report, CAT_FEE_CONFIG_MISMATCH, "GST-on-MDR != policy",
                             expected=exp.gst_on_mdr, actual=report.gst_on_mdr)

        # 3. report internal consistency: net == gross - mdr - gst - refund - reserve
        expected_net = p.captured_amount - report.mdr_fee - report.gst_on_mdr - refund - exp.reserve
        if expected_net != report.net_amount:
            return self._exc(result, p, report, CAT_REPORT_INCONSISTENT, "net != gross-mdr-gst-refund-reserve",
                             expected=expected_net, actual=report.net_amount)

        # 4. ledger must have booked the right principal (gross-of-refund)
        expected_booked = p.captured_amount - refund
        if ledger is None:
            return self._exc(result, p, report, CAT_LEDGER_BOOKING_MISMATCH, "no ledger entry",
                             expected=expected_booked, actual=None)
        if ledger.booked_amount != expected_booked:
            return self._exc(result, p, report, CAT_LEDGER_BOOKING_MISMATCH,
                             "ledger booked != gross-of-refund (unbooked refund / partial)",
                             expected=expected_booked, actual=ledger.booked_amount)

        # all proven -> MATCHED
        result.matched.append(
            MatchRecord(
                payment_id=p.payment_id,
                settlement_id=report.settlement_id,
                method=p.method,
                gross_amount=p.captured_amount,
                net_amount=report.net_amount,
                evidence={
                    "mdr_fee": report.mdr_fee,
                    "gst_on_mdr": report.gst_on_mdr,
                    "reserve": exp.reserve,
                    "refund_deduction": refund,
                    "booked_amount": ledger.booked_amount,
                },
            )
        )

    @staticmethod
    def _exc(result, p, report, category, detail, expected=None, actual=None):
        result.exceptions.append(
            ExceptionRecord(
                payment_id=p.payment_id,
                category=category,
                detail=detail,
                expected=expected,
                actual=actual,
                settlement_id=report.settlement_id if report else None,
            )
        )
