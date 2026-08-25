"""Verifier + governor tests.

The cardinal guarantee: the verifier never confirms a WRONG match (cross-checked against ground
truth). Plus controlled-autonomy behavior: off by default holds everything; enabling it releases
only verified, allowlisted, high-confidence findings.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from ledgerproof.agent.heuristic import HeuristicAgentModel
from ledgerproof.agent.loader import load_seam_b
from ledgerproof.agent.model import AgentFinding
from ledgerproof.agent.tools import SeamBToolbox
from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset
from ledgerproof.verifier.config import GovernorConfig
from ledgerproof.verifier.governor import Governor
from ledgerproof.verifier.models import DECISION_AUTO, DECISION_HUMAN
from ledgerproof.verifier.pipeline import run_pipeline
from ledgerproof.verifier.verifier import SeamBVerifier

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=3, run_name_override="verify_test")
    cfg.n_payments = 1500
    ds = Generator(cfg).generate()
    return write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))


def _off():
    return GovernorConfig(enabled=False, min_confidence=0.95, allowlist=[], min_drift_days=0, max_drift_days=4)


def _on():
    return GovernorConfig(enabled=True, min_confidence=0.90, allowlist=["bank_settlement_match"],
                          min_drift_days=0, max_drift_days=4)


def test_verifier_never_confirms_a_wrong_match(run_dir):
    """Cardinal: any finding the verifier marks verified must point at the TRUE settlement."""
    records = run_pipeline(run_dir, HeuristicAgentModel(), _off())
    gt = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))["bank_credits"]
    for r in records:
        if r.verification.verified:
            true = gt[r.finding.bank_txn_id]["true_settlement_id"]
            assert r.finding.matched_settlement_id == true, "verifier confirmed a WRONG match"


def test_opened_findings_are_not_verified(run_dir):
    records = run_pipeline(run_dir, HeuristicAgentModel(), _off())
    for r in records:
        if r.finding.matched_settlement_id is None:
            assert not r.verification.verified


def test_verified_findings_pass_every_check(run_dir):
    records = run_pipeline(run_dir, HeuristicAgentModel(), _off())
    for r in records:
        if r.verification.verified:
            assert all(r.verification.checks.values())
            assert r.verification.rederived_net is not None


def test_off_by_default_holds_everything(run_dir):
    records = run_pipeline(run_dir, HeuristicAgentModel(), _off())
    decisions = Counter(r.governor.decision for r in records)
    assert decisions[DECISION_AUTO] == 0
    assert decisions[DECISION_HUMAN] == len(records)


def test_enabling_auto_resolves_only_verified_allowlisted(run_dir):
    records = run_pipeline(run_dir, HeuristicAgentModel(), _on())
    autos = [r for r in records if r.governor.decision == DECISION_AUTO]
    assert autos, "expected some auto-resolutions when enabled"
    for r in autos:
        assert r.verification.verified
        assert r.finding.break_type in _on().allowlist
        assert r.finding.confidence >= _on().min_confidence


def test_empty_allowlist_blocks_auto_even_when_enabled(run_dir):
    cfg = GovernorConfig(enabled=True, min_confidence=0.0, allowlist=[], min_drift_days=0, max_drift_days=4)
    records = run_pipeline(run_dir, HeuristicAgentModel(), cfg)
    assert all(r.governor.decision == DECISION_HUMAN for r in records)


def test_conflict_check_rejects_shared_settlement(run_dir):
    """A real, otherwise-valid match becomes unverified when another credit claims the same
    settlement (no_conflict fails while every other check passes)."""
    tools = SeamBToolbox(load_seam_b(run_dir))
    gt = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))["bank_credits"]
    # a clean credit and its true settlement -> exists/reconcile/window all pass
    bid, info = next((b, v) for b, v in gt.items() if v["break_type"] == "clean")
    sid = info["true_settlement_id"]
    f = AgentFinding(bank_txn_id=bid, matched_settlement_id=sid, confidence=0.99)

    solo = SeamBVerifier().verify(f, tools, claimed_counts={sid: 1})
    assert solo.verified is True  # otherwise valid

    conflicted = SeamBVerifier().verify(f, tools, claimed_counts={sid: 2})
    assert conflicted.verified is False
    assert conflicted.checks["no_conflict"] is False


def test_audit_record_shape(run_dir):
    records = run_pipeline(run_dir, HeuristicAgentModel(), _off())
    audit = records[0].to_audit()
    for key in ("verification", "governor_decision", "policy", "reversible"):
        assert key in audit
