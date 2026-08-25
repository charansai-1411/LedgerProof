"""CLI: run the Seam-B exception agent over a generated run and grade it.

    python -m ledgerproof.agent --data data/dev --model heuristic
    python -m ledgerproof.agent --data data/dev --model gemini      # needs Vertex AI creds

Default model is the deterministic heuristic (no API), so the pipeline always runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..generator.config import REPO_ROOT
from .grader import grade
from .pipeline import investigate_all


def _make_model(name: str):
    if name == "heuristic":
        from .heuristic import HeuristicAgentModel
        return HeuristicAgentModel()
    if name == "gemini":
        from .gemini import GeminiVertexAgentModel
        return GeminiVertexAgentModel()
    raise SystemExit(f"unknown model '{name}' (choices: heuristic, gemini)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledgerproof.agent", description=__doc__)
    parser.add_argument("--data", default=str(REPO_ROOT / "data" / "dev"))
    parser.add_argument("--model", default="heuristic", choices=["heuristic", "gemini"])
    parser.add_argument("--show", type=int, default=2, help="print N example findings")
    args = parser.parse_args()

    model = _make_model(args.model)
    findings = investigate_all(args.data, model)
    print(f"[seam-b] model={model.name}  investigated {len(findings)} bank credits")

    gt_path = Path(args.data) / "ground_truth.json"
    if gt_path.exists():
        report = grade(findings, json.loads(gt_path.read_text(encoding="utf-8")))
        print("  " + json.dumps(report, indent=2).replace("\n", "\n  "))
        fm = report["false_match_rate"]
        print(f"\n  FALSE-MATCH RATE (cardinal): {fm}  ->  {'PASS (zero)' if fm == 0.0 else 'FAIL'}")

    hard = [f for f in findings if f.match_basis and "exact_utr" not in f.match_basis and f.matched_settlement_id]
    for f in hard[: args.show]:
        print("\n  --- example (searched, not UTR-matched) ---")
        print("  " + json.dumps(f.as_record(), indent=2).replace("\n", "\n  "))


if __name__ == "__main__":
    main()
