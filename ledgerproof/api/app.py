"""FastAPI app: dashboard + JSON API, with dataset switching and CSV upload."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from ..generator.config import REPO_ROOT
from ..verifier.config import GovernorConfig
from .importer import REQUIRED, ImportError_, import_dataset
from .service import ReconService

STATIC = Path(__file__).parent / "static"
DATA_ROOT = REPO_ROOT / "data"


class PolicyUpdate(BaseModel):
    enabled: bool
    min_confidence: float
    allowlist: list[str]


class SampleSelect(BaseModel):
    name: str


def _available_datasets() -> list[dict]:
    out = []
    if DATA_ROOT.exists():
        for d in sorted(DATA_ROOT.iterdir()):
            if (d / "ledgerproof.sqlite").exists():
                out.append({"name": d.name, "has_ground_truth": (d / "ground_truth.json").exists()})
    return out


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    data_dir = Path(data_dir) if data_dir else DATA_ROOT / "heldout"
    if not (Path(data_dir) / "ledgerproof.sqlite").exists():
        alt = DATA_ROOT / "dev"
        if (alt / "ledgerproof.sqlite").exists():
            data_dir = alt

    state: dict = {"svc": ReconService(data_dir, GovernorConfig.load())}

    def svc() -> ReconService:
        return state["svc"]

    app = FastAPI(title="LedgerProof — Settlement Reconciliation")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    # ---- reconciliation reads ----
    @app.get("/api/report")
    def report() -> dict:
        return svc().report()

    @app.get("/api/exceptions")
    def exceptions() -> list[dict]:
        return svc().exceptions()

    @app.get("/api/policy")
    def get_policy() -> dict:
        return svc().policy_dict()

    @app.post("/api/policy")
    def set_policy(update: PolicyUpdate) -> dict:
        return svc().set_policy(update.enabled, update.min_confidence, update.allowlist)

    @app.get("/api/transaction/{payment_id}")
    def transaction(payment_id: str) -> dict:
        t = svc().transaction(payment_id)
        if t is None:
            raise HTTPException(status_code=404, detail=f"no payment '{payment_id}'")
        return t

    @app.get("/api/samples")
    def samples() -> dict:
        return {"payment_ids": svc().sample_payment_ids()}

    @app.get("/api/tax")
    def tax() -> dict:
        return svc().tax_report()

    @app.get("/api/cycles")
    def cycles() -> dict:
        return svc().cycles()

    @app.get("/api/routing")
    def routing() -> dict:
        return svc().routing()

    @app.get("/api/evaluation")
    def evaluation() -> dict:
        return svc().evaluation()

    @app.get("/api/memory")
    def memory() -> dict:
        return svc().memory()

    @app.get("/api/architectures")
    def architectures() -> dict:
        return svc().architectures()

    @app.get("/api/exception/{bank_txn_id}")
    def exception_detail(bank_txn_id: str) -> dict:
        d = svc().exception_detail(bank_txn_id)
        if d is None:
            raise HTTPException(status_code=404, detail=f"no bank credit '{bank_txn_id}'")
        return d

    @app.get("/api/qa")
    def qa(q: str) -> dict:
        return svc().ask(q)

    # ---- live agent trace (Server-Sent Events) ----
    @app.get("/api/credits")
    def credits() -> list[dict]:
        return svc().investigation_targets()

    @app.get("/api/investigate")
    async def investigate(bank_txn_id: str, model: str = "heuristic") -> StreamingResponse:
        gen = svc().stream_investigation(bank_txn_id, model)
        pace = 0.28 if model == "heuristic" else 0.06

        async def sse():
            try:
                for ev in gen:
                    yield "data: " + json.dumps(ev) + "\n\n"
                    await asyncio.sleep(pace)
            except Exception as e:  # surface an agent/creds error into the live console
                yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- dataset management ----
    @app.get("/api/dataset")
    def dataset() -> dict:
        return {"current": svc().dataset_info(), "available": _available_datasets()}

    @app.post("/api/dataset/sample")
    def select_sample(sel: SampleSelect) -> dict:
        d = DATA_ROOT / sel.name
        if not (d / "ledgerproof.sqlite").exists():
            raise HTTPException(status_code=404, detail=f"no dataset '{sel.name}'")
        state["svc"] = ReconService(d, svc().policy)
        return svc().dataset_info()

    @app.get("/api/template/{table}", response_class=PlainTextResponse)
    def template(table: str) -> str:
        if table not in REQUIRED:
            raise HTTPException(status_code=404, detail=f"unknown table '{table}'")
        return ",".join(REQUIRED[table]) + "\n"

    @app.post("/api/dataset/upload")
    async def upload(
        pg_payments: UploadFile = File(...),
        settlements: UploadFile = File(...),
        settlement_report: UploadFile = File(...),
        bank_statement: UploadFile = File(...),
        internal_ledger: UploadFile = File(...),
    ) -> dict:
        uploads = {
            "pg_payments": pg_payments, "settlements": settlements,
            "settlement_report": settlement_report, "bank_statement": bank_statement,
            "internal_ledger": internal_ledger,
        }
        files = {name: await f.read() for name, f in uploads.items()}
        out_dir = DATA_ROOT / "uploads" / f"upload_{int(time.time())}"
        try:
            summary = import_dataset(files, out_dir)
        except ImportError_ as e:
            raise HTTPException(status_code=400, detail=str(e))
        state["svc"] = ReconService(out_dir, svc().policy)
        return {**summary, **svc().dataset_info()}

    return app
