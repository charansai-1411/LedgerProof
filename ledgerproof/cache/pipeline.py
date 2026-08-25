"""Cached Seam-B pipeline: agent-on-novel-patterns, cache-on-repeats, verify EVERYTHING."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..agent.heuristic import HeuristicAgentModel
from ..agent.loader import load_seam_b
from ..agent.model import AgentModel
from ..agent.tools import SeamBToolbox
from ..verifier.config import GovernorConfig
from ..verifier.governor import Governor
from ..verifier.models import DecisionRecord
from ..verifier.verifier import SeamBVerifier
from .pattern_cache import CachedResolver, PatternCache


def run_cached_pipeline(
    data_dir: str | Path, inner_model: AgentModel, cfg: GovernorConfig
) -> tuple[list[tuple[DecisionRecord, str]], CachedResolver]:
    tools = SeamBToolbox(load_seam_b(data_dir))
    resolver = CachedResolver(inner_model, PatternCache())
    verifier = SeamBVerifier(cfg.min_drift_days, cfg.max_drift_days)
    governor = Governor(cfg)
    ids = tools.all_bank_txn_ids()

    # Conflict detection needs to know which settlements are multiply-claimed. Compute claims cheaply
    # up front with the deterministic strategy (no agent/LLM calls, not counted as investigations).
    strategy = HeuristicAgentModel()
    claimed = Counter(
        f.matched_settlement_id
        for f in (strategy.investigate(b, tools) for b in ids)
        if f.matched_settlement_id
    )

    # Online pass: consult the cache as it fills, verify every finding, learn only from verified
    # agent-sourced matches.
    out: list[tuple[DecisionRecord, str]] = []
    for bid in ids:
        finding, source = resolver.resolve(bid, tools)
        verification = verifier.verify(finding, tools, claimed)
        if source == "agent":
            resolver.learn(finding, tools, verification.verified)
        decision = governor.decide(finding, verification)
        out.append((DecisionRecord(finding, verification, decision), source))
    return out, resolver
