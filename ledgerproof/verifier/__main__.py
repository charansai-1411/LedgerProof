"""CLI: run agent -> verifier -> governor and summarize decisions.

    python -m ledgerproof.verifier --data data/dev
    python -m ledgerproof.verifier --data data/dev --enable-auto --allow bank_settlement_match --min-confidence 0.95

Default model is the deterministic heuristic (no API); pass --model gemini for Gemini on Vertex.
With auto-resolve off (the default), every verified match still routes to human review — that is
the conservative controlled-autonomy default.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ..generator.config import REPO_ROOT
from .config import GovernorConfig
from .models import DECISION_AUTO, DECISION_HUMAN
from .pipeline import run_pipeline


def _make_model(name: str):
    if name == "heuristic":
        from ..agent.heuristic import HeuristicAgentModel
        return HeuristicAgentModel()
    from ..agent.gemini import GeminiVertexAgentModel
    return GeminiVertexAgentModel()


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgerproof.verifier", description=__doc__)
    p.add_argument("--data", default=str(REPO_ROOT / "data" / "dev"))
    p.add_argument("--model", default="heuristic", choices=["heuristic", "gemini"])
    p.add_argument("--enable-auto", action="store_true", help="turn the auto-resolve master switch on")
    p.add_argument("--allow", action="append", default=None, help="add a break category to the allowlist")
    p.add_argument("--min-confidence", type=float, default=None)
    p.add_argument("--show", type=int, default=1, help="print N example audit records")
    args = p.parse_args()

    cfg = GovernorConfig.load()
    if args.enable_auto:
        cfg.enabled = True
    if args.allow:
        cfg.allowlist = list(set(cfg.allowlist) | set(args.allow))
    if args.min_confidence is not None:
        cfg.min_confidence = args.min_confidence

    records = run_pipeline(args.data, _make_model(args.model), cfg)

    verified = sum(1 for r in records if r.verification.verified)
    decisions = Counter(r.governor.decision for r in records)
    print(f"[verify+govern] data={args.data}  model={args.model}")
    print(f"  policy: enabled={cfg.enabled} min_confidence={cfg.min_confidence} allowlist={cfg.allowlist}")
    print(f"  credits={len(records)}  verified={verified}  "
          f"auto_resolved={decisions[DECISION_AUTO]}  human_review={decisions[DECISION_HUMAN]}")

    autos = [r for r in records if r.governor.decision == DECISION_AUTO]
    for r in autos[: args.show]:
        print("\n  --- example auto-resolved (audit record) ---")
        print("  " + json.dumps(r.to_audit(), indent=2).replace("\n", "\n  "))
    if not autos:
        # show a verified-but-held example to make the controlled-autonomy default visible
        held = [r for r in records if r.verification.verified][: args.show]
        for r in held:
            print("\n  --- example verified but HELD for human (auto-resolve off) ---")
            print("  " + json.dumps(r.to_audit(), indent=2).replace("\n", "\n  "))


if __name__ == "__main__":
    main()
