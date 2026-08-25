"""Adapt a generic public transactions CSV into a full LedgerProof dataset."""

from __future__ import annotations

import argparse
import csv
import random
import string
from datetime import date, timedelta
from pathlib import Path

from ..generator.config import REPO_ROOT, GeneratorConfig
from ..generator.generate import Generator
from ..generator.models import Payment
from ..generator.writers import write_dataset

_ALNUM = string.ascii_lowercase + string.digits

# map free-text method values from public data onto LedgerProof's four methods
_METHOD_KEYWORDS = {
    "upi": "upi",
    "credit": "card", "debit": "card", "card": "card", "visa": "card", "mastercard": "card",
    "netbank": "netbanking", "net bank": "netbanking", "imps": "netbanking", "neft": "netbanking",
    "wallet": "wallet", "paytm": "wallet", "phonepe": "wallet",
    "payment": "card", "transfer": "netbanking", "cash_out": "wallet", "cash_in": "upi",
}


def _to_paise(raw: str, amount_in: str) -> int:
    s = str(raw).strip().replace(",", "").replace("₹", "").replace("Rs", "").replace("$", "").strip()
    val = float(s)
    return int(round(val * 100)) if amount_in == "rupees" else int(round(val))


def _map_method(raw, rng, methods, weights) -> str:
    if raw:
        r = str(raw).lower()
        for kw, m in _METHOD_KEYWORDS.items():
            if kw in r:
                return m
    return rng.choices(methods, weights=weights, k=1)[0]


def build_payments(rows, cfg: GeneratorConfig, amount_col: str, date_col: str | None,
                   method_col: str | None, amount_in: str, seed: int) -> list[Payment]:
    rng = random.Random(seed)
    base = date.fromisoformat(cfg.base_date)
    methods = list(cfg.method_mix.keys())
    weights = [cfg.method_mix[m] for m in methods]

    clean = []
    for r in rows:
        try:
            amt = _to_paise(r[amount_col], amount_in)
        except (KeyError, ValueError, TypeError):
            continue
        if amt <= 0:
            continue
        clean.append((amt, _map_method(r.get(method_col) if method_col else None, rng, methods, weights)))

    n = len(clean)
    payments: list[Payment] = []
    for i, (amt, method) in enumerate(clean):
        # spread rows across the settlement cycles preserving input order (time-ordered exports batch)
        day = min(cfg.n_cycles - 1, int(i * cfg.n_cycles / max(n, 1)))
        p = Payment(
            payment_id="pay_" + "".join(rng.choice(_ALNUM) for _ in range(10)),
            order_id="order_" + "".join(rng.choice(_ALNUM) for _ in range(10)),
            method=method,
            captured_amount=amt,
            captured_at=(base + timedelta(days=day)).isoformat(),
            status="captured",
        )
        if rng.random() < cfg.refund_rate:
            p.refund_id = "rfnd_" + "".join(rng.choice(_ALNUM) for _ in range(8))
            p.refund_amount = (amt * 30 // 100 // 100) * 100
            p.status = "partial_refund"
        payments.append(p)
    return payments


def adapt_csv(csv_path, amount_col, date_col=None, method_col=None, amount_in="rupees",
              run_name="public", seed=7, limit=5000, config=None, out_root=None) -> Path:
    cfg = GeneratorConfig.load(config or (REPO_ROOT / "configs" / "generator.yaml"),
                               seed_override=seed, run_name_override=run_name)
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if limit:
        rows = rows[:limit]
    payments = build_payments(rows, cfg, amount_col, date_col, method_col, amount_in, seed)
    if not payments:
        raise SystemExit(f"no usable rows (check --amount-col '{amount_col}')")
    cfg.n_payments = len(payments)  # scale the exception budget to the real row count
    dataset = Generator(cfg).generate(payments=payments)
    return write_dataset(dataset, cfg, out_root=out_root)


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgerproof.adapters.from_transactions", description=__doc__)
    p.add_argument("--csv", required=True, help="path to a public transactions CSV")
    p.add_argument("--amount-col", required=True, help="column holding the transaction amount")
    p.add_argument("--date-col", default=None)
    p.add_argument("--method-col", default=None, help="column with a payment method / type (optional)")
    p.add_argument("--amount-in", default="rupees", choices=["rupees", "paise"])
    p.add_argument("--run-name", default="public")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--limit", type=int, default=5000, help="cap rows (public sets can be huge)")
    args = p.parse_args()

    out = adapt_csv(args.csv, args.amount_col, args.date_col, args.method_col,
                    args.amount_in, args.run_name, args.seed, args.limit)
    print(f"[adapter] built dataset from {args.csv} -> {out}")
    print("  load it in the dashboard:  python -m ledgerproof.api --data " + str(out))
    print("  or score it:               python -m ledgerproof.metrics --data " + str(out))


if __name__ == "__main__":
    main()
