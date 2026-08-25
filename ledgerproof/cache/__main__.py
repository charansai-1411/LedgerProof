"""CLI: demonstrate the pattern cache — how many agent (LLM) investigations it saves.

    python -m ledgerproof.cache --data data/heldout

Default inner model is the heuristic (so this runs with no API and the invocation counts are the
point). With --model gemini, the cache means the LLM is called only once per novel pattern.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ..generator.config import REPO_ROOT
from ..verifier.config import GovernorConfig
from .pipeline import run_cached_pipeline


def _make_model(name: str):
    if name == "heuristic":
        from ..agent.heuristic import HeuristicAgentModel
        return HeuristicAgentModel()
    from ..agent.gemini import GeminiVertexAgentModel
    return GeminiVertexAgentModel()


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgerproof.cache", description=__doc__)
    p.add_argument("--data", default=str(REPO_ROOT / "data" / "heldout"))
    p.add_argument("--model", default="heuristic", choices=["heuristic", "gemini"])
    p.add_argument("--enable-auto", action="store_true")
    args = p.parse_args()

    cfg = GovernorConfig.load()
    if args.enable_auto:
        cfg.enabled = True
        cfg.allowlist = ["bank_settlement_match"]

    records, resolver = run_cached_pipeline(args.data, _make_model(args.model), cfg)

    total = len(records)
    from_cache = sum(1 for _, src in records if src == "cache")
    # cardinal check: no false match slipped through, cache or agent
    gt = json.loads((Path(args.data) / "ground_truth.json").read_text(encoding="utf-8"))["bank_credits"]
    false_matches = sum(
        1 for rec, _ in records
        if rec.finding.matched_settlement_id is not None
        and rec.finding.matched_settlement_id != gt[rec.finding.bank_txn_id]["true_settlement_id"]
    )
    by_source = Counter(src for _, src in records)

    print(f"[cache] data={args.data}  inner_model={args.model}  credits={total}")
    print(f"  agent (LLM) investigations : {resolver.agent_invocations}   (without cache: {total})")
    print(f"  resolved from cache        : {from_cache}")
    print(f"  reduction in agent calls   : {(1 - resolver.agent_invocations / total) * 100:.0f}%")
    print(f"  false matches (cache+agent): {false_matches}   "
          f"{'PASS (zero) — verifier gates every hit' if false_matches == 0 else 'FAIL'}")
    print(f"  routing: {dict(by_source)}")
    print("  patterns learned:")
    for name, info in resolver.cache.summary()["patterns"].items():
        print(f"    {name}  -> strategy '{info['strategy']}'  (hits {info['hits']}, seed {info['seed']})")


if __name__ == "__main__":
    main()
