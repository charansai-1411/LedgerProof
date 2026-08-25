"""Import user-uploaded source CSVs into a working dataset (no ground truth).

Validates that each of the five sources has its required columns, writes them into a run directory,
and builds the SQLite working DB the engine/agent read. Empty cells become NULL so the loaders'
integer casts behave. Uploaded runs have no ground-truth key, so accuracy-vs-truth is not measurable
— the operational reconciliation (matches, exceptions, tax, Q&A) still runs.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

# table name -> required columns (order defines the CSV/DB column order)
REQUIRED: dict[str, list[str]] = {
    "pg_payments": ["payment_id", "order_id", "method", "captured_amount", "captured_at",
                    "status", "refund_id", "refund_amount"],
    "settlements": ["settlement_id", "utr", "amount", "fees", "tax", "reserve_held",
                    "reserve_release", "status", "created_at"],
    "settlement_report": ["settlement_id", "payment_id", "order_id", "gross_amount", "mdr_fee",
                          "gst_on_mdr", "refund_deduction", "net_amount"],
    "bank_statement": ["bank_txn_id", "utr", "value_date", "credit_amount", "narration"],
    "internal_ledger": ["ledger_entry_id", "order_id", "payment_id", "booked_amount", "booked_at"],
}


class ImportError_(ValueError):
    pass


def _parse_csv(name: str, data: bytes) -> tuple[list[str], list[dict]]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    required = REQUIRED[name]
    missing = [c for c in required if c not in header]
    if missing:
        raise ImportError_(f"{name}.csv is missing columns: {', '.join(missing)}")
    rows = list(reader)
    if not rows:
        raise ImportError_(f"{name}.csv has no data rows")
    return required, rows


def import_dataset(files: dict[str, bytes], out_dir: Path) -> dict:
    """files: {table_name: csv_bytes} for every table in REQUIRED. Returns a summary dict."""
    missing_files = [t for t in REQUIRED if t not in files]
    if missing_files:
        raise ImportError_(f"missing source files: {', '.join(missing_files)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "ledgerproof.sqlite"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    counts: dict[str, int] = {}
    try:
        for name, cols in REQUIRED.items():
            _, rows = _parse_csv(name, files[name])
            # persist a normalized CSV copy
            with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                w.writeheader()
                for r in rows:
                    w.writerow({c: r.get(c, "") for c in cols})
            # build the sqlite table (empty string -> NULL so int casts work downstream)
            col_sql = ", ".join(f'"{c}"' for c in cols)
            ph = ", ".join("?" for _ in cols)
            conn.execute(f'CREATE TABLE "{name}" ({col_sql})')
            conn.executemany(
                f'INSERT INTO "{name}" ({col_sql}) VALUES ({ph})',
                [tuple((r.get(c, "") or None) for c in cols) for r in rows],
            )
            counts[name] = len(rows)
        conn.commit()
    finally:
        conn.close()

    (out_dir / "manifest.json").write_text(
        '{"source": "uploaded", "ground_truth": false}', encoding="utf-8"
    )
    return {"run_name": out_dir.name, "counts": counts, "has_ground_truth": False}
