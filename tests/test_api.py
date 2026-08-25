"""Dashboard API tests. Skipped if the optional [api] deps aren't installed."""

from __future__ import annotations

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
    first = rows[0]
    for key in ("bank_txn_id", "verification", "governor_decision", "narrative"):
        assert key in first


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
