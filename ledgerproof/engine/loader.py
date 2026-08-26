"""Load the source tables from a generated run's SQLite working DB.

The engine reads ONLY the sources (pg_payments, settlement_report, internal_ledger). It never
opens ground_truth.json — that isolation is what keeps the metrics honest.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..generator.models import LedgerEntry, Payment, SettlementReportRow


@dataclass
class Sources:
    payments: list[Payment]
    report_rows: list[SettlementReportRow]
    ledger: list[LedgerEntry]


def _int(v) -> int | None:
    return None if v is None else int(v)


def _col(row, name: str, default=0):
    """Read a column that may be absent in a dataset generated before it was added."""
    return int(row[name]) if name in row.keys() and row[name] is not None else default


def load_sources(data_dir: str | Path) -> Sources:
    db = Path(data_dir) / "ledgerproof.sqlite"
    if not db.exists():
        raise FileNotFoundError(f"no working DB at {db} — run the generator first")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        payments = [
            Payment(
                payment_id=r["payment_id"],
                order_id=r["order_id"],
                method=r["method"],
                captured_amount=int(r["captured_amount"]),
                captured_at=r["captured_at"],
                status=r["status"],
                refund_id=r["refund_id"],
                refund_amount=_int(r["refund_amount"]),
            )
            for r in conn.execute("SELECT * FROM pg_payments")
        ]
        report_rows = [
            SettlementReportRow(
                settlement_id=r["settlement_id"],
                payment_id=r["payment_id"],
                order_id=r["order_id"],
                gross_amount=int(r["gross_amount"]),
                mdr_fee=int(r["mdr_fee"]),
                gst_on_mdr=int(r["gst_on_mdr"]),
                refund_deduction=int(r["refund_deduction"]),
                net_amount=int(r["net_amount"]),
                tds=_col(r, "tds"),
                reserve=_col(r, "reserve"),
            )
            for r in conn.execute("SELECT * FROM settlement_report")
        ]
        ledger = [
            LedgerEntry(
                ledger_entry_id=r["ledger_entry_id"],
                order_id=r["order_id"],
                payment_id=r["payment_id"],
                booked_amount=int(r["booked_amount"]),
                booked_at=r["booked_at"],
            )
            for r in conn.execute("SELECT * FROM internal_ledger")
        ]
        return Sources(payments=payments, report_rows=report_rows, ledger=ledger)
    finally:
        conn.close()
