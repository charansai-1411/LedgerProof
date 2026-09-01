"""Q&A agent tests (deterministic RuleQA — no API)."""

from __future__ import annotations

import pytest

from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset
from ledgerproof.qa.service import QAContext, RuleQA

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def qa(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=6, run_name_override="qa_test")
    cfg.n_payments = 1200
    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))
    return RuleQA(QAContext(out))


def test_summary(qa):
    a = qa.ask("give me an overview")["answer"]
    assert "Reconciled" in a and "false matches" in a


def test_gst_question(qa):
    a = qa.ask("what is our total GST and does it reconcile?")["answer"]
    assert "GST" in a and "18.00%" in a


def test_mdr_question(qa):
    a = qa.ask("how much did we pay in MDR fees?")["answer"]
    assert "MDR" in a


def test_method_breakdown_beats_totals(qa):
    a = qa.ask("break down fees by method")["answer"]
    assert "upi" in a.lower()


def test_unexplained_question(qa):
    r = qa.ask("which credits could not be reconciled?")
    assert "unexplained" in r["answer"].lower()
    assert "count" in r["data"]


def test_false_match_question(qa):
    assert "Zero false matches" in qa.ask("do we have any false matches?")["answer"]


def test_why_opened_specific_credit(qa):
    unexplained = qa.ask("unexplained credits")["data"]["bank_txn_ids"]
    if unexplained:
        r = qa.ask(f"why was {unexplained[0]} opened?")
        assert unexplained[0] in r["answer"]
        assert "opened" in r["answer"].lower()


def test_settlement_short_decomposes_the_gap(qa):
    """'Why is settlement X short?' returns the deduction waterfall, not a canned line."""
    sid = next(iter(qa.ctx._rows_by_settlement))
    r = qa.ask(f"why is settlement {sid} short?")
    assert sid in r["answer"] and "short by" in r["answer"]
    d = r["data"]
    assert d["gross"] - d["net"] == d["mdr"] + d["gst"] + d["tds"] + d["reserve"] + d["refunds"]


def test_credits_over_threshold_filter(qa):
    """A threshold query runs a real filter over the reconciliation state."""
    r = qa.ask("show credits over ₹10,000")
    assert "above" in r["answer"] and "threshold_paise" in r["data"]
    assert r["data"]["threshold_paise"] == 1_000_000  # ₹10,000 in paise
    # unresolved-only narrows the set
    ru = qa.ask("show unresolved credits over ₹5,000")["data"]
    assert ru["count"] <= r["data"]["count"]


def test_why_not_auto_and_agent_investigated(qa):
    bid = qa.ctx.records[0].finding.bank_txn_id
    a = qa.ask(f"why was {bid} not auto-resolved?")["answer"]
    assert bid in a and ("auto-resolved" in a.lower())
    inv = qa.ask(f"what did the agent investigate for {bid}?")
    assert bid in inv["answer"] and "basis" in inv["data"]
