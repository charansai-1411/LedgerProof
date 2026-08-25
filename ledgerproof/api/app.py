"""FastAPI app wiring the dashboard to the recon service."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..generator.config import REPO_ROOT
from ..verifier.config import GovernorConfig
from .service import ReconService

STATIC = Path(__file__).parent / "static"


class PolicyUpdate(BaseModel):
    enabled: bool
    min_confidence: float
    allowlist: list[str]


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    data_dir = Path(data_dir) if data_dir else REPO_ROOT / "data" / "heldout"
    if not (Path(data_dir) / "ledgerproof.sqlite").exists():
        # fall back to the dev run if the requested one is not generated
        alt = REPO_ROOT / "data" / "dev"
        if (alt / "ledgerproof.sqlite").exists():
            data_dir = alt
    svc = ReconService(data_dir, GovernorConfig.load())

    app = FastAPI(title="LedgerProof — Settlement Reconciliation")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/report")
    def report() -> dict:
        return svc.report()

    @app.get("/api/exceptions")
    def exceptions() -> list[dict]:
        return svc.exceptions()

    @app.get("/api/policy")
    def get_policy() -> dict:
        return svc.policy_dict()

    @app.post("/api/policy")
    def set_policy(update: PolicyUpdate) -> dict:
        return svc.set_policy(update.enabled, update.min_confidence, update.allowlist)

    @app.get("/api/transaction/{payment_id}")
    def transaction(payment_id: str) -> dict:
        t = svc.transaction(payment_id)
        if t is None:
            raise HTTPException(status_code=404, detail=f"no payment '{payment_id}'")
        return t

    @app.get("/api/samples")
    def samples() -> dict:
        return {"payment_ids": svc.sample_payment_ids()}

    return app
