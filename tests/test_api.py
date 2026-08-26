"""Dashboard API tests. Skipped if the optional [api] deps aren't installed."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from ledgerproof.api.app import create_app  # noqa: E402
from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig  # noqa: E402
from ledgerproof.generator.generate import Generator  # noqa: E402
from ledgerproof.generator.writers import write_dataset  # noqa: E402

CONFIG = REPO_ROOT / "configs" / "generator.yaml"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    cfg = GeneratorConfig.load(CONFIG, seed_override=21, run_name_override="api_test")
    cfg.n_payments = 900
    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))
    return TestClient(create_app(out))


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and "LedgerProof" in r.text


def test_report_has_zero_cardinal(client):
    r = client.get("/api/report").json()
    assert r["cardinal"]["combined_false_match_rate"] == 0.0


def test_exceptions_shape(client):
    rows = client.get("/api/exceptions").json()
    assert rows
    for key in ("scope", "id", "kind", "severity", "amount", "status"):
        assert key in rows[0]
    scopes = {r["scope"] for r in rows}
    assert "payment" in scopes and "credit" in scopes  # both flows surfaced with domain names
    kinds = {r["kind"] for r in rows}
    assert kinds & {"Compound variance", "Timing mismatch", "Ambiguous settlement", "Unexplained credit"}


def test_policy_toggle_changes_auto_resolve(client):
    off = client.get("/api/report").json()["governance"]["auto_resolved"]
    assert off == 0  # governor.yaml default is off
    client.post("/api/policy", json={"enabled": True, "min_confidence": 0.9,
                                     "allowlist": ["bank_settlement_match"]})
    on = client.get("/api/report").json()["governance"]["auto_resolved"]
    assert on > 0
    # restore
    client.post("/api/policy", json={"enabled": False, "min_confidence": 0.95, "allowlist": []})


def test_transaction_returns_three_views(client):
    pid = client.get("/api/samples").json()["payment_ids"][0]
    t = client.get(f"/api/transaction/{pid}").json()
    assert t["pg_capture"] and t["settlement_report"] and t["internal_ledger"]
    assert client.get("/api/transaction/pay_does_not_exist").status_code == 404


def test_dataset_endpoint(client):
    d = client.get("/api/dataset").json()
    assert "current" in d and "available" in d
    assert d["current"]["has_ground_truth"] is True


def test_routing_endpoint(client):
    r = client.get("/api/routing").json()
    assert r["llm_in_matching"] == 0  # the whole thesis: no LLM in deterministic matching
    assert r["deterministic"] > r["ai_investigated"]
    assert r["why_ai"] and r["why_not_ai"]


def test_evaluation_benchmark(client):
    e = client.get("/api/evaluation").json()
    assert e["graded"] is True
    assert e["false_matches"] == 0
    cr = e["credit_reconciliation"]
    assert cr["with_agent"] >= cr["deterministic"]  # the agent lifts hard-credit reconciliation
    assert len(e["per_break"]) == 4


def test_memory_endpoint(client):
    m = client.get("/api/memory").json()
    assert m["known_pattern_hits"] > 0
    assert m["novel_investigations"] < m["total"]
    assert m["avg_time_with_cache_s"] < m["avg_time_without_cache_s"]
    assert m["patterns"]


def test_cycles_endpoint(client):
    c = client.get("/api/cycles").json()
    assert c["cycles"] and c["settlement_volume"] > 0
    first = c["cycles"][0]
    for k in ("cycle_id", "date", "gross", "net", "match_rate", "issues"):
        assert k in first


def test_exception_workspace_payload(client):
    creds = client.get("/api/credits").json()
    bid = next((x["bank_txn_id"] for x in creds if x["kind"] != "clean UTR"), creds[0]["bank_txn_id"])
    d = client.get(f"/api/exception/{bid}").json()
    assert d["id"] == bid and d["scope"] == "credit"
    assert len(d["records"]) == 3 and d["records"][0]["amount"] > 0
    assert d["timeline"][0]["node"] == "BANK CREDIT" and d["timeline"][-1]["node"] == "AUDIT"
    assert "verified" in d["verification"] and "decision" in d["governor"]
    assert d["audit"] and d["trace"]
    assert client.get("/api/exception/bank_nope").status_code == 404


def test_payment_exception_detail(client):
    rows = client.get("/api/exceptions").json()
    pay = next(r for r in rows if r["scope"] == "payment")
    d = client.get(f"/api/exception/{pay['id']}").json()
    assert d["scope"] == "payment" and d["reason"]
    assert d["timeline"][0]["node"] == "PAYMENT"
    assert d["governor"]["decision"] == "human_review"


def test_transaction_has_fee_breakdown(client):
    pid = client.get("/api/samples").json()["payment_ids"][0]
    b = client.get(f"/api/transaction/{pid}").json()["breakdown"]
    assert b and b["gross"] - b["net"] == b["difference"]


def test_live_agent_trace_streams(client):
    creds = client.get("/api/credits").json()
    assert creds
    bid = next((c["bank_txn_id"] for c in creds if c["kind"] != "clean UTR"), creds[0]["bank_txn_id"])
    body = client.get(f"/api/investigate?bank_txn_id={bid}&model=heuristic").text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "observe" and kinds[-1] == "done"
    for expected in ("finding", "verify", "govern"):
        assert expected in kinds


def test_template_endpoint(client):
    t = client.get("/api/template/pg_payments").text
    assert "payment_id" in t and "captured_amount" in t


def test_import_ungraded_report(tmp_path_factory):
    """Importing raw source CSVs (no ground truth) yields an ungraded but working report."""
    from ledgerproof.api.importer import import_dataset

    gcfg = GeneratorConfig.load(CONFIG, seed_override=22, run_name_override="imp_src")
    gcfg.n_payments = 800
    ds = Generator(gcfg).generate()
    src = write_dataset(ds, gcfg, out_root=tmp_path_factory.mktemp("src"))

    files = {t: (src / f"{t}.csv").read_bytes()
             for t in ["pg_payments", "settlements", "settlement_report",
                       "bank_statement", "internal_ledger"]}
    out = tmp_path_factory.mktemp("imp") / "uploaded"
    summary = import_dataset(files, out)
    assert summary["has_ground_truth"] is False
    assert not (out / "ground_truth.json").exists()

    c = TestClient(create_app(out))
    rep = c.get("/api/report").json()
    assert rep["graded"] is False
    assert rep["seam_a_payments"]["match_rate"] > 0.9
    assert rep["cardinal"]["combined_false_match_rate"] is None
    assert c.get("/api/dataset").json()["current"]["has_ground_truth"] is False
