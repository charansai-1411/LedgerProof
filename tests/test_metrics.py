"""End-to-end report-card tests, run on a freshly generated (isolated) dataset.

The headline assertion is the cardinal one: across everything the system asserted — deterministic
matches plus governed auto-resolutions — the combined false-match rate is zero.
"""

from __future__ import annotations

import pytest

from ledgerproof.agent.heuristic import HeuristicAgentModel
from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset
from ledgerproof.metrics.report import build_report, format_card
from ledgerproof.verifier.config import GovernorConfig

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def card(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=99, run_name_override="metrics_test")
    cfg.n_payments = 1500
    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))
    gov = GovernorConfig(enabled=True, min_confidence=0.90, allowlist=["bank_settlement_match"],
                         min_drift_days=0, max_drift_days=4)
    return build_report(out, HeuristicAgentModel(), gov)


def test_combined_false_match_rate_is_zero(card):
    assert card["cardinal"]["combined_false_match_rate"] == 0.0


def test_no_wrong_auto_resolutions(card):
    assert card["governance"]["wrong_auto_resolutions"] == 0


def test_both_seams_zero_false(card):
    assert card["seam_a_payments"]["false_match_rate"] == 0.0
    assert card["seam_b_credits"]["false_match_rate"] == 0.0


def test_auto_resolve_actually_happens_when_enabled(card):
    assert card["governance"]["auto_resolved"] > 0
    assert 0.0 < card["governance"]["auto_resolve_rate"] <= 1.0


def test_coverage_complete(card):
    assert card["coverage"]["every_unresolved_item_has_a_reason"] is True


def test_throughput_positive(card):
    assert card["throughput"]["records_per_second"] > 0


def test_card_formats(card):
    text = format_card(card)
    assert "combined false-match rate" in text
    assert "Throughput" in text
