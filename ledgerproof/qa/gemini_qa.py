"""Gemini function-calling front for the Q&A agent.

Same SDK discipline as ledgerproof/agent/gemini.py: module-level plain tool functions with REAL
type annotations (NO `from __future__ import annotations`), reading the active QAContext from a
ContextVar. Bound methods / nested closures and stringized annotations break the SDK's automatic
function calling.
"""

import json
import os
from contextvars import ContextVar

from .service import QAContext

_CURRENT_QA: ContextVar[QAContext] = ContextVar("qa_ctx")

_SYSTEM = """You are a settlement reconciliation assistant. Answer the user's question about ONE
reconciliation run using the tools provided. Always call a tool to get real numbers — never guess.
Amounts from the tools are in paise; present them as rupees (₹, divide by 100). Be concise and
concrete, and cite the figures you used."""


def recon_summary():
    """Overall reconciliation: payments matched/total, match rate, credits matched vs opened,
    auto-resolved and human-review counts."""
    return _CURRENT_QA.get().summary()["data"]


def tax_totals():
    """MDR and GST-on-MDR totals (paise), effective GST rate (bps), and any discrepancies."""
    return _CURRENT_QA.get().total_gst()["data"]


def unexplained_credits():
    """Count and ids of bank credits that reconcile to no settlement and were opened for review."""
    return _CURRENT_QA.get().unexplained()["data"]


def fees_by_method():
    """MDR/GST totals broken down by payment method (UPI carries no MDR)."""
    return _CURRENT_QA.get().per_method()["data"]


def explain_credit(bank_txn_id: str):
    """The full audit record for one bank credit: match/opened, verifier checks, governor decision,
    narrative."""
    return _CURRENT_QA.get().why_opened(bank_txn_id)["data"]


_TOOLS = [recon_summary, tax_totals, unexplained_credits, fees_by_method, explain_credit]


class GeminiQA:
    name = "gemini-qa"

    def __init__(self, ctx: QAContext, project: str | None = None,
                 location: str | None = None, model: str | None = None) -> None:
        self.ctx = ctx
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT", "ledgerproof-506605")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model = model or os.getenv("LEDGERPROOF_GEMINI_MODEL", "gemini-2.5-flash")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(vertexai=True, project=self.project, location=self.location)
        return self._client

    def ask(self, question: str) -> dict:
        from google.genai import types

        config = types.GenerateContentConfig(system_instruction=_SYSTEM, tools=_TOOLS, temperature=0)
        token = _CURRENT_QA.set(self.ctx)
        try:
            resp = self._get_client().models.generate_content(
                model=self.model, contents=question, config=config)
        finally:
            _CURRENT_QA.reset(token)
        return {"answer": (resp.text or "").strip(), "data": {}}
