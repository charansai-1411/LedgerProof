"""CLI: run the Seam-A engine on a generated run and print honest metrics.

    python -m ledgerproof.engine --data data/dev
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..generator.config import DEFAULT_FEES, REPO_ROOT, FeeConfig
from .grader import grade, load_ground_truth
from .loader import load_sources
from .seam_a import SeamAEngine


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledgerproof.engine", description=__doc__)
    parser.add_argument("--data", default=str(REPO_ROOT / "data" / "dev"), help="generated run directory")
    parser.add_argument("--fees", default=str(DEFAULT_FEES), help="fee policy config")
    parser.add_argument("--no-grade", action="store_true", help="skip grading against ground truth")
    args = parser.parse_args()

    fees = FeeConfig.load(args.fees)
    sources = load_sources(args.data)
    result = SeamAEngine(fees).reconcile(sources)

    print(f"[seam-a] reconciled {args.data}")
    print("  " + json.dumps(result.summary(), indent=2).replace("\n", "\n  "))

    if not args.no_grade and (Path(args.data) / "ground_truth.json").exists():
        report = grade(result, load_ground_truth(args.data))
        print("\n[grade] against ground truth")
        print("  " + json.dumps(report, indent=2).replace("\n", "\n  "))
        fm = report["false_match_rate"]
        print(f"\n  FALSE-MATCH RATE (cardinal): {fm}  ->  {'PASS (zero)' if fm == 0.0 else 'FAIL'}")


if __name__ == "__main__":
    main()
