"""Seam-A engine tests — the guarantees that matter for a finance product.

The load-bearing one is test_zero_false_matches: the engine must never assert a match that
ground truth says is a break. Everything else is coverage of the residue it hands onward.
"""

from __future__ import annotations

import pytest

from ledgerproof.engine.grader import grade, load_ground_truth
from ledgerproof.engine.loader import load_sources
from ledgerproof.engine.models import CAT_LEDGER_BOOKING_MISMATCH, CAT_NOT_SETTLED
from ledgerproof.engine.seam_a import SeamAEngine
from ledgerproof.generator.config import REPO_ROOT, FeeConfig, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=11, run_name_override="engine_test")
    cfg.n_payments = 1200
    ds = Generator(cfg).generate()
    return write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="module")
def graded(run_dir):
    fees = FeeConfig.load()
    result = SeamAEngine(fees).reconcile(load_sources(run_dir))
    report = grade(result, load_ground_truth(run_dir))
    return result, report


def test_zero_false_matches(graded):
    _, report = graded
    assert report["false_match_rate"] == 0.0
    assert report["false_matches"] == []


def test_match_rate_is_high(graded):
    result, _ = graded
    assert result.summary()["match_rate"] > 0.9


def test_every_payment_is_matched_or_excepted(graded):
    result, _ = graded
    unique_excepted = {e.payment_id for e in result.exceptions}
    assert len(result.matched) + len(unique_excepted) == result.total_payments


def test_partial_payments_flagged_with_right_category(graded):
    _, report = graded
    pp = report["partial_payment"]
    assert pp["recall"] == 1.0
    assert pp["correct_category"] == pp["true"]


def test_timing_breaks_flagged_with_right_category(graded):
    _, report = graded
    t = report["timing_in_transit"]
    assert t["recall"] == 1.0
    assert t["correct_category"] == t["true"]


def test_all_duplicates_detected(graded):
    _, report = graded
    d = report["duplicates_detected"]
    assert d["detected"] == d["true"]


def test_matched_records_reconcile_to_the_paise(graded):
    """Every asserted match must actually balance under its own evidence."""
    result, _ = graded
    for m in result.matched:
        ev = m.evidence
        recomputed = m.gross_amount - ev["mdr_fee"] - ev["gst_on_mdr"] - ev["refund_deduction"] - ev["reserve"]
        assert recomputed == m.net_amount, f"{m.payment_id} does not balance"


def test_reconciliation_is_deterministic(run_dir):
    fees = FeeConfig.load()
    a = SeamAEngine(fees).reconcile(load_sources(run_dir)).summary()
    b = SeamAEngine(fees).reconcile(load_sources(run_dir)).summary()
    assert a == b
