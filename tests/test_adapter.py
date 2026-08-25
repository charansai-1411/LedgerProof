"""Adapter tests: a generic external CSV becomes a valid, reconcilable dataset."""

from __future__ import annotations

import csv
import random

import pytest

from ledgerproof.adapters.from_transactions import adapt_csv
from ledgerproof.engine.grader import grade, load_ground_truth
from ledgerproof.engine.loader import load_sources
from ledgerproof.engine.seam_a import SeamAEngine
from ledgerproof.generator.config import FeeConfig


@pytest.fixture(scope="module")
def external_csv(tmp_path_factory):
    path = tmp_path_factory.mktemp("ext") / "txns.csv"
    rng = random.Random(2)
    types = ["UPI", "Credit Card", "Net Banking", "Wallet", "PAYMENT"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "amt", "kind"])
        for i in range(500):
            w.writerow([i, round(rng.uniform(100, 60000), 2), rng.choice(types)])
    return path


def test_adapter_builds_reconcilable_dataset(external_csv, tmp_path_factory):
    out = adapt_csv(external_csv, amount_col="amt", method_col="kind",
                    run_name="adapter_test", out_root=tmp_path_factory.mktemp("data"))
    assert (out / "ledgerproof.sqlite").exists()
    assert (out / "ground_truth.json").exists()  # derived, so measurable

    sources = load_sources(out)
    assert len(sources.payments) > 400
    result = SeamAEngine(FeeConfig.load()).reconcile(sources)
    report = grade(result, load_ground_truth(out))
    assert report["false_match_rate"] == 0.0
    assert result.summary()["match_rate"] > 0.85


def test_upi_stays_fee_free_from_real_methods(external_csv, tmp_path_factory):
    """Rows mapped to UPI must not carry fee/tax variance labels (the trap holds on real data)."""
    out = adapt_csv(external_csv, amount_col="amt", method_col="kind",
                    run_name="adapter_trap", out_root=tmp_path_factory.mktemp("data"))
    gt = load_ground_truth(out)["variance_labels"]
    sources = load_sources(out)
    method = {p.payment_id: p.method for p in sources.payments}
    for pid, label in gt.items():
        if label in ("FEE_DEDUCTION", "TAX_DEDUCTION"):
            assert method.get(pid) != "upi"
