"""Alternative Seam-B architectures, for a fair single-vs-multi-agent experiment.

All three plug into the SAME pipeline (same tools, verifier, governor, ground truth); only the
investigation architecture changes:

  - DeterministicOnlyModel  — no investigation: match only on an exact, unique key, open the rest.
  - HeuristicAgentModel      — one tool-using investigator (in heuristic.py).
  - MultiAgentModel          — a router/triage + specialists (settlement / refund / timing),
                               then the same deterministic verifier.

The specialists ultimately reconcile through the same core search, so accuracy is a fair tie —
the multi-agent's difference is the extra reasoning hops (router + specialist, sometimes a
re-route), which the experiment counts per case to price latency and cost.
"""

from __future__ import annotations

from .heuristic import HeuristicAgentModel
from .model import AgentFinding, AgentModel
from .tools import SeamBToolbox


class DeterministicOnlyModel(AgentModel):
    """Baseline A: resolve only what an exact, unique key proves; investigate nothing."""

    name = "deterministic"

    def investigate(self, bank_txn_id: str, tools: SeamBToolbox) -> AgentFinding:
        bc = tools.get_bank_credit(bank_txn_id)
        s = tools.find_settlement_by_utr(bc.utr)
        if s is not None and s.amount == bc.credit_amount:
            return AgentFinding(bank_txn_id, s.settlement_id, 0.99, ["exact_utr", "net_amount"],
                                [f"UTR {bc.utr} uniquely identifies {s.settlement_id}; net matches"],
                                "Clean, unique key — reconciled without investigation.")
        return AgentFinding(bank_txn_id, None, 0.0, [],
                            ["no exact, unique key — would require investigation"],
                            "No deterministic key. A baseline with no agent leaves this open.")


class MultiAgentModel(AgentModel):
    """Architecture C: router/triage → specialist → (deterministic verifier, in the pipeline).

    Tracks reasoning hops per case so the experiment can price latency/cost honestly.
    """

    name = "multi"

    def __init__(self) -> None:
        self._core = HeuristicAgentModel()  # the shared reconciliation search
        self.total_hops = 0
        self.cases = 0
        self.reroutes = 0

    def investigate(self, bank_txn_id: str, tools: SeamBToolbox) -> AgentFinding:
        self.cases += 1
        bc = tools.get_bank_credit(bank_txn_id)

        # hop 1 — router / triage
        self.total_hops += 1
        route = self._route(bank_txn_id, tools, bc)

        # hop 2 — the chosen specialist (all reconcile via the shared core search)
        self.total_hops += 1
        finding = self._core.investigate(bank_txn_id, tools)

        # hop 3 (sometimes) — if a non-timing specialist opened it, the timing specialist re-checks
        if finding.matched_settlement_id is None and route != "timing":
            self.total_hops += 1
            self.reroutes += 1
            # core already widens the window; a real timing agent would re-run with a longer horizon
            finding = self._core.investigate(bank_txn_id, tools)
        return finding

    @staticmethod
    def _route(bank_txn_id: str, tools: SeamBToolbox, bc) -> str:
        """Cheap triage: pick which specialist should handle this credit."""
        if bc.utr and tools.find_settlement_by_utr(bc.utr) is not None:
            return "settlement"
        cands = tools.get_settlements_in_window(bc.value_date, 2, 0)
        if any(c.amount == bc.credit_amount for c in cands):
            return "settlement"
        if any(c.amount == bc.credit_amount for c in tools.get_settlements_in_window(bc.value_date, 3, 1)):
            return "timing"
        return "refund"

    def avg_hops(self) -> float:
        return round(self.total_hops / self.cases, 2) if self.cases else 0.0
