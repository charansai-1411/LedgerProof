"""CLI: end-to-end reconciliation report card.

    python -m ledgerproof.metrics --data data/heldout --enable-auto --allow bank_settlement_match
    python -m ledgerproof.metrics --data data/heldout --json report.json

Default model is the deterministic heuristic (fast, so throughput reflects the deterministic
system); pass --model gemini for the LLM path. Run this on a DIFFERENT-seed held-out set so the
numbers are not fit to the data the system was tuned on.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..generator.config import REPO_ROOT
from ..verifier.config import GovernorConfig
from .report import build_report, format_card


def _make_model(name: str):
    if name == "heuristic":
        from ..agent.heuristic import HeuristicAgentModel
        return HeuristicAgentModel()
    from ..agent.gemini import GeminiVertexAgentModel
    return GeminiVertexAgentModel()


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgerproof.metrics", description=__doc__)
    p.add_argument("--data", default=str(REPO_ROOT / "data" / "heldout"))
    p.add_argument("--model", default="heuristic", choices=["heuristic", "gemini"])
    p.add_argument("--enable-auto", action="store_true")
    p.add_argument("--allow", action="append", default=None)
    p.add_argument("--min-confidence", type=float, default=None)
    p.add_argument("--json", default=None, help="also write the full card to this JSON path")
    args = p.parse_args()

    cfg = GovernorConfig.load()
    if args.enable_auto:
        cfg.enabled = True
    if args.allow:
        cfg.allowlist = list(set(cfg.allowlist) | set(args.allow))
    if args.min_confidence is not None:
        cfg.min_confidence = args.min_confidence

    card = build_report(args.data, _make_model(args.model), cfg)
    print(format_card(card))
    if args.json:
        Path(args.json).write_text(json.dumps(card, indent=2), encoding="utf-8")
        print(f"\n[wrote full card -> {args.json}]")


if __name__ == "__main__":
    main()
