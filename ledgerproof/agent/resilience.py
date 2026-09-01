"""Agent infrastructure resilience (critique 15).

Two failure modes a payments company actually cares about, handled so neither can cause a wrong
financial action:

  tool timeout / exception  → bounded retry → still failing → investigation INCOMPLETE → human review
  invalid model output      → schema validation → reject → no match proposed → human review

The rule is uniform: any infrastructure failure degrades to 'open, route to human', never to an
unverified auto-resolution. Validation runs BEFORE the verifier, so a malformed finding never even
reaches the money path.
"""

from __future__ import annotations

from .model import AgentFinding, AgentModel
from .tools import SeamBToolbox


class ToolTimeout(Exception):
    """Raised by a tool that exceeded its time budget."""


class FindingSchemaError(Exception):
    """The model returned something that is not a valid, self-consistent finding."""


def validate_finding(finding, tools: SeamBToolbox) -> AgentFinding:
    """Reject anything that isn't a schema-valid, internally-consistent finding. On any violation we
    do NOT guess — we return an opened finding (→ human), so bad output can never auto-resolve."""
    try:
        if not isinstance(finding, AgentFinding):
            raise FindingSchemaError("not an AgentFinding")
        if not isinstance(finding.confidence, (int, float)) or not (0.0 <= finding.confidence <= 1.0):
            raise FindingSchemaError(f"confidence out of range: {finding.confidence!r}")
        if not isinstance(finding.match_basis, list):
            raise FindingSchemaError("match_basis is not a list")
        sid = finding.matched_settlement_id
        if sid is not None:
            if not isinstance(sid, str) or tools.get_settlement(sid) is None:
                raise FindingSchemaError(f"proposed settlement {sid!r} does not exist")
    except FindingSchemaError as e:
        bid = getattr(finding, "bank_txn_id", "unknown")
        return AgentFinding(bank_txn_id=bid, matched_settlement_id=None, confidence=0.0,
                            match_basis=[], evidence=[f"schema validation rejected the finding: {e}"],
                            narrative="Model output failed schema validation — opened for human review, "
                                      "no financial action taken.")
    return finding


def resilient_investigate(model: AgentModel, bank_txn_id: str, tools: SeamBToolbox,
                          attempts: int = 2) -> tuple[AgentFinding, dict]:
    """Run the agent with bounded retries; on exhaustion, open the credit (→ human). Then validate the
    surviving finding. Returns (finding, telemetry) so the fault harness can show what happened."""
    tries = 0
    last_err = None
    for tries in range(1, attempts + 1):
        try:
            raw = model.investigate(bank_txn_id, tools)
            finding = validate_finding(raw, tools)
            rejected = finding is not raw
            return finding, {"attempts": tries, "outcome": "validated" if not rejected else "schema_rejected",
                             "error": None}
        except (ToolTimeout, Exception) as e:  # noqa: BLE001 — any infra failure degrades safely
            last_err = f"{type(e).__name__}: {e}"
            continue
    incomplete = AgentFinding(bank_txn_id=bank_txn_id, matched_settlement_id=None, confidence=0.0,
                              match_basis=[], evidence=[f"investigation incomplete after {attempts} attempts: {last_err}"],
                              narrative="Tool/agent failure exhausted the retry budget — opened for human "
                                        "review, no match forced.")
    return incomplete, {"attempts": attempts, "outcome": "investigation_incomplete", "error": last_err}
