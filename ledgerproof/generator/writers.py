"""Output writers: CSV sources + SQLite working DB + isolated ground-truth key + manifest.

The ground truth is written to its own file and is NEVER loaded into the SQLite working DB —
the engine and agent read the sources, never the answer key. That isolation is the
measurement-integrity story.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Sequence

from .config import REPO_ROOT, GeneratorConfig
from .generate import GeneratedDataset

# CSV filename ↔ dataset attribute
_SOURCES = [
    ("pg_payments.csv", "payments"),
    ("settlements.csv", "settlements"),
    ("settlement_report.csv", "report_rows"),
    ("bank_statement.csv", "bank_credits"),
    ("internal_ledger.csv", "ledger"),
]


def _write_csv(path: Path, rows: Sequence[Any]) -> list[str]:
    if not rows:
        path.write_text("", encoding="utf-8")
        return []
    header = [f.name for f in fields(rows[0])]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))
    return header


def _load_sqlite(db_path: Path, tables: dict[str, tuple[list[str], Sequence[Any]]]) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        for table, (header, rows) in tables.items():
            if not header:
                continue
            cols = ", ".join(f'"{c}"' for c in header)
            placeholders = ", ".join("?" for _ in header)
            conn.execute(f'CREATE TABLE "{table}" ({cols})')
            conn.executemany(
                f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})',
                [tuple(asdict(r)[c] for c in header) for r in rows],
            )
        conn.commit()
    finally:
        conn.close()


def write_dataset(
    ds: GeneratedDataset, cfg: GeneratorConfig, out_root: str | Path | None = None
) -> Path:
    root = Path(out_root) if out_root else REPO_ROOT / "data"
    out_dir = root / cfg.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    tables: dict[str, tuple[list[str], Sequence[Any]]] = {}
    for filename, attr in _SOURCES:
        rows = getattr(ds, attr)
        header = _write_csv(out_dir / filename, rows)
        tables[Path(filename).stem] = (header, rows)

    # SQLite working DB — sources only, NEVER the ground truth
    _load_sqlite(out_dir / "ledgerproof.sqlite", tables)

    # isolated answer key + manifest (sorted keys → reproducible bytes)
    (out_dir / "ground_truth.json").write_text(
        json.dumps(ds.ground_truth, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(ds.manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return out_dir
