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


def test_reason_code_taxonomy(client):
    """Every exception carries the §8 taxonomy: status ≠ reason, plus delta and a suggested action."""
    from ledgerproof.engine import reasons as R
    rows = client.get("/api/exceptions").json()
    assert rows
    valid_reasons = {R.NO_CANDIDATE, R.AMBIGUOUS_CANDIDATE, R.TOLERANCE_EXCEEDED, R.SPLIT_UNRESOLVED,
                     R.TIMING_WINDOW_MISS, R.DUPLICATE_REFERENCE, R.REFUND_UNRESOLVED,
                     R.COMPOUND_UNRESOLVED, R.MISSING_SOURCE, R.UNEXPLAINED}
    for r in rows:
        for k in ("match_status", "exception_reason", "delta_paise", "delta_percent",
                  "nearest_candidate_id", "suggested_action"):
            assert k in r
        assert r["match_status"] in {R.MATCHED, R.EXCEPTION, R.HUMAN_REVIEW}
        if r["exception_reason"] is not None:
            assert r["exception_reason"] in valid_reasons
            assert r["suggested_action"]
    # a payment compound break maps to COMPOUND_UNRESOLVED with a real dela
    comp = next((r for r in rows if r["kind"] == "Compound variance"), None)
    if comp:
        assert comp["exception_reason"] == R.COMPOUND_UNRESOLVED
        assert comp["delta_paise"] is not None


def test_what_if_simulator(client):
    """The simulator shows before/after and, on graded data, the safety cost of loosening."""
    # loosen the confidence bar from the default and see the effect
    r = client.post("/api/whatif", json={"enabled": True, "min_confidence": 0.5,
                                         "allowlist": ["bank_settlement_match"]}).json()
    assert "before" in r and "after" in r and r["graded"] is True
    assert r["after"]["auto_resolved"] >= r["before"]["auto_resolved"]  # looser → at least as many
    # the safety number is measured, not assumed
    assert r["after"]["wrong_auto_resolutions"] is not None
    assert r["verdict"]


def test_policy_version_stamped(client):
    """Policy carries a version, and it lands in the audit record (§34)."""
    assert client.get("/api/policy").json()["version"]
    from ledgerproof.agent.model import AgentFinding
    from ledgerproof.verifier.governor import Governor
    from ledgerproof.verifier.config import GovernorConfig
    from ledgerproof.verifier.models import DecisionRecord, VerificationResult
    cfg = GovernorConfig(enabled=True, min_confidence=0.9, allowlist=["bank_settlement_match"],
                         min_drift_days=0, max_drift_days=4, version="v2")
    f = AgentFinding(bank_txn_id="b", matched_settlement_id="s", confidence=0.99,
                     match_basis=["exact_utr"])
    v = VerificationResult(True, "ok", {"amount": True})
    rec = DecisionRecord(f, v, Governor(cfg).decide(f, v))
    assert rec.to_audit()["policy_version"] == "v2"


def test_necessity_benchmark(client):
    """The honest self-attack: deterministic search does the work; the verifier catches an
    aggressive proposer's wrong matches (with population n on every number)."""
    r = client.get("/api/necessity").json()
    assert r["graded"] is True
    # deterministic candidate search already recovers the matchable credits, with zero wrong
    assert r["decomposition"]["final_matchable_recall"] >= 0.9
    assert r["decomposition"]["final_false_match_rate"] == 0.0
    assert r["decomposition"]["n_matchable"] > 0  # never a percentage without a population
    # the verifier's value is demonstrated against the aggressive 'greedy' proposer
    g = r["verifier_work"]["greedy"]
    assert g["wrong_proposed"] > 0                       # greedy really does propose wrong matches
    assert g["wrong_rejected_by_verifier"] == g["wrong_proposed"]  # the verifier catches every one
    assert g["final_false_matches"] == 0
    assert g["proposal_accuracy"] < 1.0                 # and it is genuinely less accurate than final
    assert r["candidate_reachability"]["recall"] <= 1.0 and r["conclusion"]
    # the honest "does the agent earn its existence" number, decomposed and self-consistent
    e = r["escalation"]
    assert (e["of_which_genuinely_ambiguous"] + e["of_which_softer_evidence_might_recover"]
            == e["agent_marginal_opportunity"])
    # on a realistic fixture deterministic search resolves the matchable set → tiny opportunity
    assert e["det_search_resolved_matchable"] + e["agent_marginal_opportunity"] >= r["population"]["matchable"] - 1


def test_human_investigation_benchmark(client):
    """The agent's honest value: effort reduction at accuracy parity, measured proxies separated
    from the modeled time estimate."""
    r = client.get("/api/human-benchmark").json()
    assert r["graded"] is True and r["investigated"] > 0
    m = r["measured"]
    # a human inspects strictly fewer records assisted than unassisted, and it is a real reduction
    assert m["records_inspected_per_case"]["assisted"] < m["records_inspected_per_case"]["unassisted"]
    assert m["record_reduction_factor"] > 1.0
    assert m["false_matches"] == 0                       # accuracy parity: the cardinal metric holds
    # the time estimate is explicitly modeled with stated, tunable assumptions
    assert r["modeled_time"]["assumptions"]["seconds_per_record_inspected"] > 0
    assert r["modeled_time"]["speedup"] > 1.0 and "not a human-subjects study" in r["modeled_time"]["disclaimer"]


def test_dataset_card(client):
    c = client.get("/api/dataset-card").json()
    assert c["available"] is True and c["ground_truth_isolated"] is True
    assert c["injected_breaks"] and all("rate_pct" in b for b in c["injected_breaks"])


def test_handcrafted_adversarial_no_false_match():
    """Anti-circularity: cases authored BY HAND, outside the generator's sampling — a same-amount
    same-day collision, a truncated-UTR searchable credit, and a true orphan. The system must match
    the resolvable ones, OPEN the ambiguous/orphan ones, and never assert a wrong match."""
    from ledgerproof.agent.grader import grade
    from ledgerproof.agent.heuristic import HeuristicAgentModel
    from ledgerproof.agent.loader import SeamBSources
    from ledgerproof.agent.tools import SeamBToolbox
    from ledgerproof.generator.models import BankCredit, Settlement, SettlementReportRow

    def setl(sid, utr, amt):
        return Settlement(sid, utr, amt, 0, 0, 0, None, "processed", "2026-01-10")

    def row(sid, amt):
        return SettlementReportRow(sid, "pay_" + sid, "ord_" + sid, amt, 0, 0, 0, amt)

    settlements = [setl("S1", "AAAAAAAA11111111", 600000), setl("S2", "BBBBBBBB22222222", 450000),
                   setl("S3", "CCCCCCCC33333333", 450000), setl("S4", "DDDDDDDD44444444", 275000)]
    rows = [row("S1", 600000), row("S2", 450000), row("S3", 450000), row("S4", 275000)]
    credits = [
        BankCredit("B_clean", "AAAAAAAA11111111", "2026-01-10", 600000, "clean"),          # → S1
        BankCredit("B_collide", "XYZ?9999????????", "2026-01-10", 450000, "ambiguous"),    # S2==S3 → open
        BankCredit("B_orphan", "", "2026-01-10", 999999, "orphan"),                        # → open
        BankCredit("B_search", "", "2026-01-11", 275000, "missing UTR, drift"),            # → S4 by search
    ]
    tools = SeamBToolbox(SeamBSources(settlements, credits, rows))
    m = HeuristicAgentModel()
    findings = {c.bank_txn_id: m.investigate(c.bank_txn_id, tools) for c in credits}

    assert findings["B_clean"].matched_settlement_id == "S1"
    assert findings["B_search"].matched_settlement_id == "S4"     # searched under a missing UTR
    assert findings["B_collide"].matched_settlement_id is None    # ambiguous → opened, never forced
    assert findings["B_orphan"].matched_settlement_id is None     # orphan → opened

    gt = {"bank_credits": {
        "B_clean": {"break_type": "clean", "true_settlement_id": "S1", "difficulty": []},
        "B_collide": {"break_type": "bank_settlement_match", "true_settlement_id": "S2",
                      "difficulty": ["same_day_collision"]},
        "B_orphan": {"break_type": "unexplained", "true_settlement_id": None, "difficulty": []},
        "B_search": {"break_type": "bank_settlement_match", "true_settlement_id": "S4",
                     "difficulty": ["utr_missing", "date_drift"]},
    }}
    b = grade(list(findings.values()), gt)
    assert b["false_matches"] == 0          # the cardinal guarantee, on hand-built adversarial data
    assert b["correct_matches"] == 2


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
