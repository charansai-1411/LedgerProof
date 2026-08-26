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


def test_architecture_experiment(client):
    a = client.get("/api/architectures").json()
    assert a["graded"] is True
    names = [s["system"] for s in a["systems"]]
    assert names == ["Deterministic", "Single agent", "Multi-agent"]
    det, single, multi = a["systems"]
    # the agent recovers what deterministic-only leaves unresolved
    assert single["match_accuracy"] > det["match_accuracy"]
    # fair experiment: no false matches under any architecture (verifier gates all three)
    assert all(s["false_match_rate"] == 0.0 for s in a["systems"])
    # multi-agent costs more reasoning hops without beating single-agent accuracy
    assert multi["llm_calls_per_case"] > single["llm_calls_per_case"]
    assert multi["match_accuracy"] == single["match_accuracy"]
    assert a["conclusion"]


def test_scenario_stress_test(client):
    r = client.post("/api/scenario", json={"difficulty": "adversarial", "records": 1000}).json()
    assert r["incorrect_resolutions"] == 0  # the number that must stay zero, even adversarial
    assert r["false_match_rate"] == 0.0
    assert r["correctly_resolved"] + r["missed"] == r["matchable"]
    assert client.post("/api/scenario", json={"difficulty": "nope", "records": 1000}).status_code == 400


def test_multi_agent_is_genuinely_multi(tmp_path_factory):
    """Guard against regressing to a router-over-one-core: distinct specialists must resolve cases."""
    from ledgerproof.agent.loader import load_seam_b
    from ledgerproof.agent.multi import MultiAgentModel
    from ledgerproof.agent.tools import SeamBToolbox
    from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
    from ledgerproof.generator.generate import Generator
    from ledgerproof.generator.writers import write_dataset

    # a harsh set so the timing specialist (wider window) fires alongside the settlement one
    cfg = GeneratorConfig.load(REPO_ROOT / "configs" / "generator.yaml",
                               seed_override=77, run_name_override="multi_test")
    cfg.n_payments = 2500
    cfg.seam_b_match_rate = 0.45
    cfg.seam_b_mess = {"utr_garbled_rate": 0.55, "utr_missing_rate": 0.20,
                       "same_day_collision_rate": 0.65, "date_drift_days": [0, 1, 2, 3, 4]}
    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=tmp_path_factory.mktemp("data"))

    tools = SeamBToolbox(load_seam_b(out))
    m = MultiAgentModel()
    for bid in tools.all_bank_txn_ids():
        m.investigate(bid, tools)
    # more than one specialist actually resolved cases, and hops > 1 (a router + specialist chain)
    assert len([k for k, v in m.resolved_by.items() if v > 0]) >= 2
    assert m.avg_hops() > 1.0


def test_waterfall_matrix(client):
    w = client.get("/api/waterfall").json()
    stages = {s["stage"]: s for s in w["stages"]}
    assert "Gross PG captures ingested" in stages
    ingested = stages["Gross PG captures ingested"]
    assert ingested["volume"] > 0 and ingested["value"] > 0
    # the three agent sub-rows sum to the investigated total (nothing lost)
    investigated = next(s for s in w["stages"] if s["stage"].startswith("Agent-investigated"))
    subs = [s for s in w["stages"] if s["depth"] == 1]
    assert sum(s["volume"] for s in subs) == investigated["volume"]
    assert w["false_match_rate"] == 0.0  # graded set: zero false matches across the waterfall


def test_guardrail_blocks_hallucinated_fee(client):
    g = client.get("/api/guardrail").json()
    assert g["available"] is True
    # identical match + policy; the clean one auto-resolves, the poisoned one is quarantined
    assert g["control"]["governor_action"] == "AUTO_RESOLVED"
    assert g["control"]["verified"] is True
    assert g["poisoned"]["governor_action"] == "QUARANTINED_TO_HUMAN"
    assert g["poisoned"]["verified"] is False
    assert g["poisoned"]["verifier_checks"]["fee_claim_matches_policy"] is False
    assert "UPI" in g["poisoned"]["verifier_result"] or "upi" in g["poisoned"]["verifier_result"]


def test_journal_entry_balances(client):
    """Every reconciled credit posts a double-entry that balances to the paise."""
    creds = client.get("/api/credits").json()
    bid = next((x["bank_txn_id"] for x in creds if x["kind"] == "clean UTR"), creds[0]["bank_txn_id"])
    j = client.get(f"/api/journal/{bid}").json()
    assert j["available"] is True
    assert j["balanced"] is True
    assert j["total_debit"] == j["total_credit"]
    # the customer sale is the single credit; deductions + bank are the debits
    credit_lines = [l for l in j["lines"] if l["side"] == "credit"]
    assert credit_lines and credit_lines[0]["account"].startswith("Accounts receivable")
    assert any(l["account"].startswith("Bank account") for l in j["lines"])


def test_fee_configuration_tool_upi_has_no_mdr():
    """The get_fee_configuration tool reports UPI's zero MDR — the fact the guardrail rests on."""
    from ledgerproof.agent.loader import load_seam_b
    from ledgerproof.agent.tools import SeamBToolbox
    from ledgerproof.generator.config import FeeConfig, GeneratorConfig
    from ledgerproof.generator.generate import Generator
    from ledgerproof.generator.writers import write_dataset
    import tempfile
    from pathlib import Path

    fees = FeeConfig.load()
    upi = fees.describe("upi")
    assert upi["mdr_bps"] == 0 and upi["has_mdr"] is False
    assert upi["tds_rate_bps"] > 0  # TDS (194-O) still applies to UPI
    assert fees.describe("card")["has_mdr"] is True

    # the tool surfaces the same policy to the agent
    cfg = GeneratorConfig.load(CONFIG, seed_override=31, run_name_override="feetool")
    cfg.n_payments = 300
    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=Path(tempfile.mkdtemp()))
    tools = SeamBToolbox(load_seam_b(out))
    assert tools.get_fee_configuration("upi")["has_mdr"] is False


def test_tds_applied_and_itemized(client):
    """TDS (194-O) is on gross for every instrument, and settlements carry a NEFT batch id."""
    pid = client.get("/api/samples").json()["payment_ids"][0]
    t = client.get(f"/api/transaction/{pid}").json()
    assert "tds" in t["breakdown"]
    assert t["settlement"]["tds"] >= 0 and t["settlement"]["utr_batch_id"]
    # at least one payment across the sample actually had TDS withheld
    tds_seen = any(client.get(f"/api/transaction/{p}").json()["breakdown"].get("tds", 0) > 0
                   for p in client.get("/api/samples").json()["payment_ids"])
    assert tds_seen


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
