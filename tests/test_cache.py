"""Pattern-cache tests.

Two guarantees matter most: the cache is TRANSPARENT to correctness (results identical to the
un-cached pipeline), and it never introduces a false match (the verifier re-checks every hit).
"""

from __future__ import annotations

import json

import pytest

from ledgerproof.agent.heuristic import HeuristicAgentModel
from ledgerproof.cache.pipeline import run_cached_pipeline
from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset
from ledgerproof.verifier.config import GovernorConfig
from ledgerproof.verifier.pipeline import run_pipeline

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


def _cfg():
    return GovernorConfig(enabled=True, min_confidence=0.90, allowlist=["bank_settlement_match"],
                          min_drift_days=0, max_drift_days=4)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=8, run_name_override="cache_test")
    cfg.n_payments = 1500
    ds = Generator(cfg).generate()
    return write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="module")
def cached(run_dir):
    return run_cached_pipeline(run_dir, HeuristicAgentModel(), _cfg())


def test_cache_reduces_agent_invocations(cached):
    records, resolver = cached
    assert resolver.cache_hits > 0
    assert resolver.agent_invocations < len(records)
    # one investigation per distinct learned pattern (plus at most a few before a match is verified)
    assert resolver.agent_invocations <= resolver.cache.summary()["patterns_learned"] + 3


def test_no_false_match_through_cache(cached, run_dir):
    records, _ = cached
    gt = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))["bank_credits"]
    for rec, _src in records:
        mid = rec.finding.matched_settlement_id
        if mid is not None:
            assert mid == gt[rec.finding.bank_txn_id]["true_settlement_id"]


def test_cache_is_transparent_to_results(cached, run_dir):
    """Cached and un-cached pipelines must agree on every credit's outcome."""
    records, _ = cached
    cached_map = {rec.finding.bank_txn_id: rec.finding.matched_settlement_id for rec, _ in records}
    plain = run_pipeline(run_dir, HeuristicAgentModel(), _cfg())
    plain_map = {r.finding.bank_txn_id: r.finding.matched_settlement_id for r in plain}
    assert cached_map == plain_map


def test_every_finding_is_verified(cached):
    """Guardrail: the verifier runs on every finding, cache hit or miss."""
    records, _ = cached
    for rec, _src in records:
        assert isinstance(rec.verification.verified, bool)
        assert rec.verification.reason


def test_cache_hits_are_actually_used(cached):
    records, _ = cached
    assert any(src == "cache" for _, src in records)
