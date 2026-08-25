"""Gemini-on-Vertex implementation of the AgentModel interface.

Uses the google-genai SDK with automatic function calling: Gemini investigates a bank credit by
calling the Seam-B tools, then returns a structured finding. Same contract as the heuristic model
(never forces a match; opens as unexplained when nothing reconciles).

Requires the Vertex AI API enabled on the project and Application Default Credentials:
    gcloud services enable aiplatform.googleapis.com
    gcloud auth application-default login
    gcloud config set project ledgerproof-506605

Config via env (with sensible defaults):
    GOOGLE_CLOUD_PROJECT   (default: ledgerproof-506605)
    GOOGLE_CLOUD_LOCATION  (default: us-central1)
    LEDGERPROOF_GEMINI_MODEL (default: gemini-2.5-flash)

google-genai is an optional dependency:  pip install -r requirements-agent.txt
"""

from __future__ import annotations

import json
import os

from .model import AgentFinding, AgentModel
from .tools import SeamBToolbox

_SYSTEM = """You are a settlement reconciliation analyst. You match a single lumped bank credit
to the Razorpay settlement it represents.

Rules:
- All amounts are INTEGER PAISE. Reconcile to the exact paisa, never approximately.
- The bank UTR is a strong signal but NOT guaranteed: it may be garbled, missing, or shared, and
  the credit's value_date can drift 0-2 days after the settlement's created_at (T+2 + NEFT).
- Investigate with the tools: read the credit, list candidate settlements in the date window, and
  compare each candidate's net amount to the credit amount. The correct settlement is the one whose
  amount equals the credit to the paisa within the plausible window.
- If exactly one candidate reconciles, propose it. If none reconciles, DO NOT force a match — a
  wrong match is worse than an open item. Return matched_settlement_id = null.

Return ONLY a JSON object, no prose around it:
{"matched_settlement_id": <string|null>, "confidence": <0..1>, "match_basis": [<string>...],
 "evidence": [<string>...], "narrative": <string>}"""


class GeminiVertexAgentModel(AgentModel):
    name = "gemini"

    def __init__(self, project: str | None = None, location: str | None = None, model: str | None = None):
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT", "ledgerproof-506605")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model = model or os.getenv("LEDGERPROOF_GEMINI_MODEL", "gemini-2.5-flash")
        self._client = None  # lazy — importing google-genai should not be required to load this module

    def _get_client(self):
        if self._client is None:
            from google import genai  # lazy import; optional dependency

            self._client = genai.Client(vertexai=True, project=self.project, location=self.location)
        return self._client

    def investigate(self, bank_txn_id: str, tools: SeamBToolbox) -> AgentFinding:
        from google.genai import types

        # --- tool wrappers exposed to Gemini (JSON-serializable returns) ---
        def get_bank_credit(bank_txn_id: str) -> dict:
            """Return the bank credit's utr, value_date, credit_amount (paise) and narration."""
            c = tools.get_bank_credit(bank_txn_id)
            return {"utr": c.utr, "value_date": c.value_date, "credit_amount": c.credit_amount,
                    "narration": c.narration}

        def list_candidate_settlements(value_date: str, days_before: int = 2, days_after: int = 0) -> list:
            """List settlements whose created_at is within [value_date-days_before, value_date+days_after].
            Each item: settlement_id, created_at, utr, amount (net paid, paise)."""
            return [
                {"settlement_id": s.settlement_id, "created_at": s.created_at, "utr": s.utr, "amount": s.amount}
                for s in tools.get_settlements_in_window(value_date, days_before, days_after)
            ]

        def get_settlement_detail(settlement_id: str) -> dict:
            """Return a settlement's created_at, utr, amount, fees, tax, reserve_held (paise) and txn count."""
            s = tools.get_settlement(settlement_id)
            if s is None:
                return {"error": "not found"}
            n = len(tools.explode_settlement(settlement_id))
            return {"settlement_id": s.settlement_id, "created_at": s.created_at, "utr": s.utr,
                    "amount": s.amount, "fees": s.fees, "tax": s.tax, "reserve_held": s.reserve_held,
                    "n_transactions": n}

        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            tools=[get_bank_credit, list_candidate_settlements, get_settlement_detail],
            temperature=0,
        )
        prompt = f"Match bank credit '{bank_txn_id}' to its settlement. Begin by reading the credit."
        resp = client.models.generate_content(model=self.model, contents=prompt, config=config)
        return self._parse(bank_txn_id, resp.text or "")

    @staticmethod
    def _parse(bank_txn_id: str, text: str) -> AgentFinding:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):]
        try:
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except (ValueError, json.JSONDecodeError):
            return AgentFinding(bank_txn_id, None, 0.0, [], [f"unparseable model output: {text[:200]}"],
                                "Model output could not be parsed; opened for review.")
        return AgentFinding(
            bank_txn_id=bank_txn_id,
            matched_settlement_id=data.get("matched_settlement_id"),
            confidence=float(data.get("confidence", 0.0)),
            match_basis=list(data.get("match_basis", [])),
            evidence=list(data.get("evidence", [])),
            narrative=str(data.get("narrative", "")),
        )
