"""Deterministic Seam-B search — the baseline / no-API fallback behind the AgentModel interface.

This encodes the same investigation a Gemini agent should perform, as explicit code: use the UTR
when it is clean, otherwise search settlements in the plausible date window and reconcile on the
net-amount envelope, and *open* the credit as unexplained when nothing reconciles. It never forces
a match. It is also the honest baseline the Gemini model must beat or match.
"""

from __future__ import annotations

from .model import AgentFinding, AgentModel
from .tools import SeamBToolbox

# money formatting for narratives
def _rs(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


class HeuristicAgentModel(AgentModel):
    name = "heuristic"

    def investigate(self, bank_txn_id: str, tools: SeamBToolbox) -> AgentFinding:
        bc = tools.get_bank_credit(bank_txn_id)

        # 1. Clean path: an exact, unique UTR whose settlement amount also reconciles.
        s = tools.find_settlement_by_utr(bc.utr)
        if s is not None and s.amount == bc.credit_amount:
            return AgentFinding(
                bank_txn_id=bank_txn_id,
                matched_settlement_id=s.settlement_id,
                confidence=0.99,
                match_basis=["exact_utr", "net_amount"],
                evidence=[
                    f"UTR {bc.utr} uniquely identifies settlement {s.settlement_id}",
                    f"settlement net {_rs(s.amount)} == bank credit {_rs(bc.credit_amount)} to the paisa",
                ],
                narrative=(
                    f"This {_rs(bc.credit_amount)} credit carries a clean UTR that maps to a single "
                    f"settlement whose net matches to the paisa. Match {s.settlement_id}."
                ),
            )

        # 2. Search path: candidate settlements in the plausible window, reconcile on amount.
        for before, after, base_conf in ((2, 0, 0.93), (3, 1, 0.82)):
            candidates = tools.get_settlements_in_window(bc.value_date, before, after)
            exact = [c for c in candidates if c.amount == bc.credit_amount]
            if len(exact) == 1:
                cand = exact[0]
                basis = ["date_window", "net_amount"]
                conf = base_conf
                # a matching UTR prefix is a corroborating (not decisive) signal
                if bc.utr and cand.utr[:8] == bc.utr[:8]:
                    basis.append("utr_prefix")
                    conf = min(0.97, conf + 0.03)
                others = [c for c in candidates if c is not cand]
                return AgentFinding(
                    bank_txn_id=bank_txn_id,
                    matched_settlement_id=cand.settlement_id,
                    confidence=conf,
                    match_basis=basis,
                    evidence=[
                        f"UTR unusable/insufficient ('{bc.utr}') — searched by date window + amount",
                        f"{len(candidates)} settlement(s) in window; only {cand.settlement_id} nets to "
                        f"{_rs(cand.amount)} == credit {_rs(bc.credit_amount)} to the paisa",
                        f"other candidates differ from the credit amount"
                        + (f" (e.g. {_rs(others[0].amount)})" if others else ""),
                    ],
                    narrative=(
                        f"This {_rs(bc.credit_amount)} credit on {bc.value_date} did not auto-match on UTR. "
                        f"Of {len(candidates)} settlements in the T+{before} window, only {cand.settlement_id} "
                        f"reconciles to the paisa once its listed MDR, GST and refunds are applied. Match it."
                    ),
                )
            if len(exact) > 1:
                # genuine ambiguity — do not force; open for human review
                break

        # 3. Nothing reconciles -> open honestly (unexplained), never force a match.
        return AgentFinding(
            bank_txn_id=bank_txn_id,
            matched_settlement_id=None,
            confidence=0.0,
            match_basis=[],
            evidence=[
                f"no settlement amount equals the credit {_rs(bc.credit_amount)} within the plausible window",
            ],
            narrative=(
                f"This {_rs(bc.credit_amount)} credit on {bc.value_date} reconciles to no settlement "
                f"under UTR, date-window or amount matching. Opened for review rather than forced."
            ),
        )
