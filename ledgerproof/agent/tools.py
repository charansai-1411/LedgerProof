"""The Seam-B toolbox — the read-only data access the agent investigates through.

Every tool is deterministic and side-effect-free: the agent (heuristic or Gemini) reasons over
what these return. The toolbox never resolves anything and never sees the ground truth.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from ..generator.config import FeeConfig
from ..generator.models import BankCredit, Settlement, SettlementReportRow
from .loader import SeamBSources


class SeamBToolbox:
    def __init__(self, sources: SeamBSources, fees: FeeConfig | None = None) -> None:
        self._fees = fees or FeeConfig.load()
        self._settlements = {s.settlement_id: s for s in sources.settlements}
        self._credits = {c.bank_txn_id: c for c in sources.bank_credits}
        self._by_utr: dict[str, list[Settlement]] = defaultdict(list)
        for s in sources.settlements:
            self._by_utr[s.utr].append(s)
        self._rows_by_settlement: dict[str, list[SettlementReportRow]] = defaultdict(list)
        for r in sources.report_rows:
            self._rows_by_settlement[r.settlement_id].append(r)
        self._settlement_list = list(sources.settlements)

    # ---- lookups -------------------------------------------------------------
    def get_bank_credit(self, bank_txn_id: str) -> BankCredit:
        return self._credits[bank_txn_id]

    def get_settlement(self, settlement_id: str) -> Optional[Settlement]:
        return self._settlements.get(settlement_id)

    def find_settlement_by_utr(self, utr: str) -> Optional[Settlement]:
        if not utr:
            return None
        hits = self._by_utr.get(utr, [])
        return hits[0] if len(hits) == 1 else None

    def get_settlements_in_window(
        self, value_date: str, days_before: int = 2, days_after: int = 0
    ) -> list[Settlement]:
        """Candidate settlements whose created_at falls in the plausible T+2+NEFT window.

        A bank credit's value_date is on or after its settlement's created_at (drift >= 0), so
        the window looks mostly backwards from the value_date.
        """
        vd = date.fromisoformat(value_date)
        lo = vd - timedelta(days=days_before)
        hi = vd + timedelta(days=days_after)
        return [
            s for s in self._settlement_list
            if lo <= date.fromisoformat(s.created_at) <= hi
        ]

    def explode_settlement(self, settlement_id: str) -> list[SettlementReportRow]:
        """Per-transaction rows for a settlement — evidence for a proposed match."""
        return list(self._rows_by_settlement.get(settlement_id, []))

    def get_fee_configuration(self, method: str) -> dict:
        """The fee policy for one instrument (MDR, GST rate, TDS, reserve).

        Lets the agent reason about instrument-level rules — e.g. that UPI carries no MDR, so a
        UPI gap can never be a TDR fee. The deterministic verifier re-derives against this same
        policy, so any fee the agent attributes is independently checkable.
        """
        return self._fees.describe(method)

    def all_bank_txn_ids(self) -> list[str]:
        return list(self._credits.keys())
