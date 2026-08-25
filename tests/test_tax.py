"""Tax-line matcher tests."""

from __future__ import annotations

import pytest

from ledgerproof.engine.loader import load_sources
from ledgerproof.generator.config import REPO_ROOT, FeeConfig, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset
from ledgerproof.tax.matcher import match_tax

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=4, run_name_override="tax_test")
    cfg.n_payments = 1200
    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))
    return load_sources(out)


def test_tax_line_reconciles_on_clean_data(sources):
    rep = match_tax(sources, FeeConfig.load())
    assert rep.discrepancies == []
    assert rep.total_gst_reported == rep.total_gst_expected
    assert rep.effective_rate_bps == 1800  # 18.00%


def test_upi_carries_no_gst(sources):
    rep = match_tax(sources, FeeConfig.load())
    upi = rep.by_method.get("upi")
    assert upi is not None and upi["gst"] == 0


def test_detects_a_tax_discrepancy(sources):
    fees = FeeConfig.load()
    # corrupt the GST on the first taxable row and confirm the matcher flags exactly it
    taxable = next(r for r in sources.report_rows if r.mdr_fee > 0)
    original = taxable.gst_on_mdr
    taxable.gst_on_mdr = original + 500  # wrong by Rs 5
    try:
        rep = match_tax(sources, fees)
        assert len(rep.discrepancies) == 1
        d = rep.discrepancies[0]
        assert d.payment_id == taxable.payment_id
        assert d.reported_gst == original + 500 and d.expected_gst == original
    finally:
        taxable.gst_on_mdr = original
