"""Load the Seam-B sources (settlements, bank credits, settlement report) from the working DB."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..generator.models import BankCredit, Settlement, SettlementReportRow


def _int(v):
    return None if v is None else int(v)


def _col(row, name: str, default=0):
    """Read a column that may be absent in a dataset generated before it was added."""
    if name not in row.keys() or row[name] is None:
        return default
    return int(row[name]) if isinstance(default, int) else row[name]


@dataclass
class SeamBSources:
    settlements: list[Settlement]
    bank_credits: list[BankCredit]
    report_rows: list[SettlementReportRow]


def load_seam_b(data_dir: str | Path) -> SeamBSources:
    db = Path(data_dir) / "ledgerproof.sqlite"
    if not db.exists():
        raise FileNotFoundError(f"no working DB at {db} — run the generator first")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        settlements = [
            Settlement(
                settlement_id=r["settlement_id"],
                utr=r["utr"],
                amount=int(r["amount"]),
                fees=int(r["fees"]),
                tax=int(r["tax"]),
                reserve_held=int(r["reserve_held"]),
                reserve_release=_int(r["reserve_release"]),
                status=r["status"],
                created_at=r["created_at"],
                tds=_col(r, "tds"),
                utr_batch_id=_col(r, "utr_batch_id", ""),
            )
            for r in conn.execute("SELECT * FROM settlements")
        ]
        bank_credits = [
            BankCredit(
                bank_txn_id=r["bank_txn_id"],
                utr=r["utr"],
                value_date=r["value_date"],
                credit_amount=int(r["credit_amount"]),
                narration=r["narration"],
            )
            for r in conn.execute("SELECT * FROM bank_statement")
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
        return SeamBSources(settlements=settlements, bank_credits=bank_credits, report_rows=report_rows)
    finally:
        conn.close()
