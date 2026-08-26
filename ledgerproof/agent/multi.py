"""Alternative Seam-B architectures, for a fair single-vs-multi-agent experiment.

All plug into the SAME pipeline (same tools, verifier, governor, ground truth); only the
investigation architecture changes:

  - DeterministicOnlyModel — no investigation: match only on an exact, unique key; open the rest.
  - HeuristicAgentModel     — one tool-using investigator (heuristic.py).
  - MultiAgentModel         — router/triage -> a GENUINELY distinct specialist -> fallback chain,
                              then the same deterministic verifier (in the pipeline).

The three specialists have DIFFERENT search logic:
  * SettlementSpecialist — exact-UTR, else narrow T+2 window on the net-amount envelope.
  * TimingSpecialist     — a wider T+3 (+1) window, for credits that drifted / are in transit.
  * RefundSpecialist     — refund add-back: a settlement whose net + its refunded amount equals
                           the credit (i.e. the credit posted before a refund was netted).

Fairness: the union of the settlement + timing specialists' windows equals the single agent's
own coverage, so the experiment isolates ARCHITECTURE (routing hops), not raw search capability.
The model records its route and resolver distribution so it can be shown to actually be
multi-agent (each specialist fires), not a router over one core.
"""

from __future__ import annotations

from collections import Counter

from .heuristic import HeuristicAgentModel, _rs
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


# ---- genuine specialists (each returns a finding, or None to defer) ----------
class SettlementSpecialist:
    name = "settlement"

    def investigate(self, bid, tools):
        bc = tools.get_bank_credit(bid)
        s = tools.find_settlement_by_utr(bc.utr)
        if s is not None and s.amount == bc.credit_amount:
            return AgentFinding(bid, s.settlement_id, 0.99, ["exact_utr", "net_amount"],
                                [f"UTR uniquely identifies {s.settlement_id}; net matches to the paisa"],
                                f"Settlement specialist: clean UTR -> {s.settlement_id}.")
        cands = tools.get_settlements_in_window(bc.value_date, 2, 0)
        exact = [c for c in cands if c.amount == bc.credit_amount]
        if len(exact) == 1:
            cand = exact[0]
            conf = HeuristicAgentModel._confidence(bc, cand, [c for c in cands if c is not cand], widened=False)
            return AgentFinding(bid, cand.settlement_id, conf, ["date_window", "net_amount"],
                                [f"{len(cands)} settlements in the T+2 window; only {cand.settlement_id} nets to "
                                 f"{_rs(cand.amount)} == credit to the paisa"],
                                f"Settlement specialist: matched {cand.settlement_id} in the T+2 window.")
        return None


class TimingSpecialist:
    name = "timing"

    def investigate(self, bid, tools):
        bc = tools.get_bank_credit(bid)
        cands = tools.get_settlements_in_window(bc.value_date, 3, 1)  # wider horizon (drift / in-transit)
        exact = [c for c in cands if c.amount == bc.credit_amount]
        if len(exact) == 1:
            cand = exact[0]
            conf = HeuristicAgentModel._confidence(bc, cand, [c for c in cands if c is not cand], widened=True)
            return AgentFinding(bid, cand.settlement_id, conf, ["timing_window", "net_amount"],
                                [f"credit drifted; widening to T+3 found {cand.settlement_id} netting to "
                                 f"{_rs(cand.amount)} == credit"],
                                f"Timing specialist: matched {cand.settlement_id} in the widened window.")
        return None


class RefundSpecialist:
    name = "refund"

    def investigate(self, bid, tools):
        bc = tools.get_bank_credit(bid)
        for c in tools.get_settlements_in_window(bc.value_date, 3, 1):
            refunds = sum(r.refund_deduction for r in tools.explode_settlement(c.settlement_id))
            if refunds > 0 and c.amount + refunds == bc.credit_amount:
                return AgentFinding(bid, c.settlement_id, 0.9, ["refund_addback", "net_amount"],
                                    [f"credit equals {c.settlement_id} net {_rs(c.amount)} + refunded "
                                     f"{_rs(refunds)} — the credit posted before the refund was netted"],
                                    f"Refund specialist: refund add-back matched {c.settlement_id}.")
        return None


class MultiAgentModel(AgentModel):
    """Architecture C: router/triage -> a real specialist -> fallback chain. Verifier stays in the pipeline."""

    name = "multi"

    def __init__(self) -> None:
        self.settlement = SettlementSpecialist()
        self.timing = TimingSpecialist()
        self.refund = RefundSpecialist()
        self.total_hops = 0
        self.cases = 0
        self.routes: Counter = Counter()
        self.resolved_by: Counter = Counter()

    def investigate(self, bank_txn_id: str, tools: SeamBToolbox) -> AgentFinding:
        self.cases += 1
        bc = tools.get_bank_credit(bank_txn_id)

        self.total_hops += 1  # hop 1 — router / triage
        route = self._route(bank_txn_id, tools, bc)
        self.routes[route] += 1

        # dispatch to the chosen specialist first, then fall back to the others (each hop counts)
        order = {
            "settlement": [self.settlement, self.timing, self.refund],
            "timing": [self.timing, self.settlement, self.refund],
            "refund": [self.refund, self.timing, self.settlement],
        }[route]
        for spec in order:
            self.total_hops += 1
            finding = spec.investigate(bank_txn_id, tools)
            if finding is not None:
                self.resolved_by[spec.name] += 1
                return finding

        return AgentFinding(bank_txn_id, None, 0.0, [],
                            [f"no specialist reconciled the credit {_rs(bc.credit_amount)}"],
                            "No specialist could reconcile it — opened for review, not forced.")

    def _route(self, bid, tools, bc) -> str:
        if bc.utr and tools.find_settlement_by_utr(bc.utr) is not None:
            return "settlement"
        if any(c.amount == bc.credit_amount for c in tools.get_settlements_in_window(bc.value_date, 2, 0)):
            return "settlement"
        if any(c.amount == bc.credit_amount for c in tools.get_settlements_in_window(bc.value_date, 3, 1)):
            return "timing"
        return "refund"

    def avg_hops(self) -> float:
        return round(self.total_hops / self.cases, 2) if self.cases else 0.0
