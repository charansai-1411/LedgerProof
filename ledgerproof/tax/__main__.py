"""CLI:  python -m ledgerproof.tax --data data/heldout"""

from __future__ import annotations

import argparse

from ..engine.loader import load_sources
from ..generator.config import DEFAULT_FEES, REPO_ROOT, FeeConfig
from .matcher import match_tax


def _rs(p: int) -> str:
    return f"Rs {p / 100:,.2f}"


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgerproof.tax", description=__doc__)
    p.add_argument("--data", default=str(REPO_ROOT / "data" / "heldout"))
    args = p.parse_args()

    fees = FeeConfig.load(DEFAULT_FEES)
    rep = match_tax(load_sources(args.data), fees)

    print(f"[tax] GST-on-MDR reconciliation — {args.data}")
    print(f"  transactions        : {rep.transactions}  ({rep.taxable_transactions} with MDR)")
    print(f"  total MDR           : {_rs(rep.total_mdr)}")
    print(f"  total GST reported  : {_rs(rep.total_gst_reported)}")
    print(f"  total GST expected  : {_rs(rep.total_gst_expected)}")
    print(f"  effective GST rate  : {rep.effective_rate_bps / 100:.2f}%")
    print(f"  discrepancies       : {len(rep.discrepancies)}  "
          f"{'-> tax line reconciles to policy' if not rep.discrepancies else '-> REVIEW'}")
    print("  by method:")
    for m, v in sorted(rep.by_method.items()):
        print(f"    {m:11} MDR {_rs(v['mdr']):>16}  GST {_rs(v['gst']):>14}  "
              f"rate {v['effective_rate_bps']/100:.2f}%  (n={v['count']})")


if __name__ == "__main__":
    main()
