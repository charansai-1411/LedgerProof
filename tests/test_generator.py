"""Generator correctness tests — the invariants from docs/GENERATOR_SPEC.md §6.

These guard the load-bearing property: the dataset is honest and internally consistent, so
downstream match-rate / false-match metrics measured against the ground truth mean something.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator, run

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def dataset():
    cfg = GeneratorConfig.load(CONFIG, seed_override=7, run_name_override="test")
    # smaller for speed
    cfg.n_payments = 800
    return Generator(cfg).generate()


def test_money_is_integer_paise(dataset):
    for r in dataset.report_rows:
        for v in (r.gross_amount, r.mdr_fee, r.gst_on_mdr, r.refund_deduction, r.net_amount):
            assert isinstance(v, int) and not isinstance(v, bool)
    for s in dataset.settlements:
        assert isinstance(s.amount, int)


def test_settlement_net_equals_sum_of_report_rows(dataset):
    net = defaultdict(int)
    for r in dataset.report_rows:
        net[r.settlement_id] += r.net_amount
    for s in dataset.settlements:
        assert net[s.settlement_id] == s.amount


def test_clean_and_hero_credits_reconcile_to_settlement_amount(dataset):
    amount = {s.settlement_id: s.amount for s in dataset.settlements}
    for bc in dataset.bank_credits:
        gt = dataset.ground_truth["bank_credits"][bc.bank_txn_id]
        if gt["break_type"] in ("clean", "bank_settlement_match"):
            assert bc.credit_amount == amount[gt["true_settlement_id"]]


def test_upi_zero_fee_trap(dataset):
    method = {p.payment_id: p.method for p in dataset.payments}
    for pid, label in dataset.ground_truth["variance_labels"].items():
        if label in ("FEE_DEDUCTION", "TAX_DEDUCTION"):
            assert method.get(pid) != "upi", f"UPI payment {pid} wrongly carries {label}"


def test_ground_truth_references_existing_ids(dataset):
    settlement_ids = {s.settlement_id for s in dataset.settlements}
    for info in dataset.ground_truth["bank_credits"].values():
        sid = info["true_settlement_id"]
        if sid is not None:
            assert sid in settlement_ids


def test_hero_exceptions_actually_hard(dataset):
    """Every injected bank_settlement_match must carry at least one difficulty tag."""
    hero = [
        info
        for info in dataset.ground_truth["bank_credits"].values()
        if info["break_type"] == "bank_settlement_match"
    ]
    assert hero, "expected some hero exceptions"
    assert all(info["difficulty"] for info in hero)


def test_unexplained_matches_no_settlement(dataset):
    amounts = {s.amount for s in dataset.settlements}
    for bc in dataset.bank_credits:
        gt = dataset.ground_truth["bank_credits"][bc.bank_txn_id]
        if gt["break_type"] == "unexplained":
            assert gt["true_settlement_id"] is None
            assert bc.credit_amount not in amounts


def test_same_seed_is_byte_identical(tmp_path):
    a = run(CONFIG, seed_override=123, run_name_override="rep_a", out_root=tmp_path)
    b = run(CONFIG, seed_override=123, run_name_override="rep_b", out_root=tmp_path)
    for name in ("pg_payments.csv", "settlement_report.csv", "bank_statement.csv", "ground_truth.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), f"{name} not reproducible"
