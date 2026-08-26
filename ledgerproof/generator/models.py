"""Data models for the generator. Every monetary field is INTEGER PAISE — never a float.

These dataclasses map one-to-one to the CSV sources described in docs/GENERATOR_SPEC.md.
Field order is the CSV column order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Payment:
    """A PG capture — what the customer paid (source: pg_payments.csv)."""

    payment_id: str
    order_id: str
    method: str  # upi | card | netbanking | wallet
    captured_amount: int  # paise
    captured_at: str  # ISO date
    status: str  # captured | refunded | partial_refund
    refund_id: Optional[str] = None
    refund_amount: Optional[int] = None  # paise


@dataclass
class Settlement:
    """A settlement batch header, keyed by settlement_id (source: settlements.csv)."""

    settlement_id: str
    utr: str
    amount: int  # net paid out, paise
    fees: int  # total MDR, paise
    tax: int  # total GST-on-MDR, paise
    reserve_held: int  # paise
    reserve_release: Optional[int]  # nullable — hold-only hook (always None in v1)
    status: str
    created_at: str  # ISO date
    tds: int = 0  # total Sec 194-O TDS withheld, paise
    utr_batch_id: str = ""  # NEFT batch this payout rode in (settlements paid same cycle share one)


@dataclass
class SettlementReportRow:
    """A settlement exploded to one row per transaction (source: settlement_report.csv)."""

    settlement_id: str
    payment_id: str
    order_id: str
    gross_amount: int  # paise
    mdr_fee: int  # paise
    gst_on_mdr: int  # paise
    refund_deduction: int  # paise
    net_amount: int  # paise
    tds: int = 0  # Sec 194-O TDS on gross, paise
    reserve: int = 0  # rolling reserve held, paise (0 for instruments outside the reserve policy)


@dataclass
class BankCredit:
    """A lumped bank credit — the Seam-B search input (source: bank_statement.csv).

    No order-level detail. The UTR is a strong-but-not-guaranteed key.
    """

    bank_txn_id: str
    utr: str  # may be garbled/empty after mess injection
    value_date: str  # ISO date — may drift from the settlement's created_at
    credit_amount: int  # paise
    narration: str


@dataclass
class LedgerEntry:
    """A merchant internal-ledger booking, typically gross (source: internal_ledger.csv)."""

    ledger_entry_id: str
    order_id: str
    payment_id: str
    booked_amount: int  # paise
    booked_at: str  # ISO date
