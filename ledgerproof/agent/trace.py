"""Emit a live investigation trace for one bank credit: observe → agent steps → verify → govern.

Computed on demand against the current dataset (not pre-recorded), so it reflects uploaded data.
Yields plain dicts that the API streams as Server-Sent Events.
"""

from __future__ import annotations

from typing import Iterator

from .heuristic import _rs
from .tools import SeamBToolbox


def run_traced(bank_txn_id: str, tools: SeamBToolbox, model, verifier, governor,
               claimed: dict) -> Iterator[dict]:
    bc = tools.get_bank_credit(bank_txn_id)
    yield {"type": "observe",
           "text": f"Investigating {bank_txn_id} — {_rs(bc.credit_amount)} on {bc.value_date}, "
                   f"UTR '{bc.utr or '(missing)'}'"}
    yield {"type": "status", "text": f"Running {getattr(model, 'name', 'agent')} investigation…"}

    finding, steps = model.investigate_with_trace(bank_txn_id, tools)
    for st in steps:
        yield st

    verification = verifier.verify(finding, tools, claimed)
    yield {"type": "verify", "verified": verification.verified, "checks": verification.checks,
           "rederived_net": verification.rederived_net, "reason": verification.reason}

    decision = governor.decide(finding, verification)
    yield {"type": "govern", "decision": decision.decision, "reason": decision.reason}

    yield {"type": "done", "matched": finding.matched_settlement_id,
           "confidence": round(finding.confidence, 3)}
