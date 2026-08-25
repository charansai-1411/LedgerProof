"""The agent's interface and output artifact.

`AgentModel` is the swap point: a HeuristicAgentModel (deterministic baseline, no API) and a
GeminiVertexAgentModel implement the same method. Keeping this boundary clean is a deliberate
engineering-judgment signal — the deterministic path stays independently testable and the LLM
is never load-bearing for the pipeline to run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .tools import SeamBToolbox


@dataclass
class AgentFinding:
    """The structured resolution record + human narrative (PRD section 7).

    matched_settlement_id is None when the agent opens the credit as unexplained rather than
    forcing a match — a false match is the cardinal sin, so 'no defensible match' is a valid,
    honest outcome.
    """

    bank_txn_id: str
    matched_settlement_id: Optional[str]
    confidence: float
    match_basis: list[str] = field(default_factory=list)  # e.g. ["exact_utr", "net_amount"]
    evidence: list[str] = field(default_factory=list)
    narrative: str = ""

    def as_record(self) -> dict:
        return {
            "bank_txn_id": self.bank_txn_id,
            "matched_settlement_id": self.matched_settlement_id,
            "confidence": round(self.confidence, 3),
            "match_basis": self.match_basis,
            "evidence": self.evidence,
            "narrative": self.narrative,
            "verification": None,  # filled by the deterministic verifier (Item #4)
        }


class AgentModel(ABC):
    name: str = "abstract"

    @abstractmethod
    def investigate(self, bank_txn_id: str, tools: SeamBToolbox) -> AgentFinding:
        """Search for the settlement this bank credit belongs to and return a finding."""
        raise NotImplementedError
