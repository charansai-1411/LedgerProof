"""Seam-B agent tests (heuristic model — no API needed).

The hero-task guarantees: the agent matches the hard credits, never asserts a wrong match, and
opens the unexplained ones honestly instead of forcing them.
"""

from __future__ import annotations

import json

import pytest

from ledgerproof.agent.grader import grade
from ledgerproof.agent.heuristic import HeuristicAgentModel
from ledgerproof.agent.pipeline import investigate_all
from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=5, run_name_override="agent_test")
    cfg.n_payments = 1500
    ds = Generator(cfg).generate()
    return write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="module")
def graded(run_dir):
    findings = investigate_all(run_dir, HeuristicAgentModel())
    report = grade(findings, json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8")))
    return findings, report


def test_zero_false_matches(graded):
    _, report = graded
    assert report["false_match_rate"] == 0.0
    assert report["false_matches"] == 0


def test_hero_credits_all_matched(graded):
    _, report = graded
    assert report["hero"]["total"] >= 1
    assert report["hero"]["recall"] == 1.0


def test_all_matchable_recalled(graded):
    _, report = graded
    assert report["matchable_recall"] == 1.0


def test_unexplained_opened_not_forced(graded):
    _, report = graded
    u = report["unexplained"]
    assert u["correctly_opened"] == u["total"]


def test_searched_matches_carry_evidence_and_narrative(graded):
    findings, _ = graded
    searched = [f for f in findings if f.matched_settlement_id and "exact_utr" not in f.match_basis]
    assert searched, "expected at least one credit matched by search, not clean UTR"
    for f in searched:
        assert f.evidence and f.narrative
        assert "net_amount" in f.match_basis


def test_deterministic(run_dir):
    a = [f.matched_settlement_id for f in investigate_all(run_dir, HeuristicAgentModel())]
    b = [f.matched_settlement_id for f in investigate_all(run_dir, HeuristicAgentModel())]
    assert a == b
