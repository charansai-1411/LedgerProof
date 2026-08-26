"""Forward synthetic-data generation: truth first, then injected mess.

Pipeline:
  1. generate clean payments (with partial refunds),
  2. choose exception targets from a seeded budget,
  3. build settlements / report rows / bank credits / ledger for the settling payments,
  4. inject the break types (Seam-B mess, compound variance, timing, duplicate, unexplained),
  5. self-check invariants (fail loudly if construction is inconsistent).

The ground truth is a byproduct of construction, never reverse-engineered. Integer paise only.
See docs/GENERATOR_SPEC.md.
"""

from __future__ import annotations

import random
import string
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .. import __version__
from .config import GeneratorConfig
from .fees import compute_fee_line
from .models import BankCredit, LedgerEntry, Payment, Settlement, SettlementReportRow

_ID_ALPHABET = string.ascii_lowercase + string.digits


@dataclass
class GeneratedDataset:
    payments: list[Payment]
    settlements: list[Settlement]
    report_rows: list[SettlementReportRow]
    bank_credits: list[BankCredit]
    ledger: list[LedgerEntry]
    ground_truth: dict[str, Any]
    manifest: dict[str, Any] = field(default_factory=dict)


class Generator:
    def __init__(self, cfg: GeneratorConfig) -> None:
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self._base = date.fromisoformat(cfg.base_date)
        # ground-truth accumulators
        self._gt_credits: dict[str, Any] = {}
        self._gt_settlements: dict[str, Any] = {}
        self._gt_variance: dict[str, str] = {}
        self._counts: dict[str, int] = defaultdict(int)

    # ---- helpers -------------------------------------------------------------
    def _rid(self, prefix: str, n: int = 10) -> str:
        return prefix + "".join(self.rng.choice(_ID_ALPHABET) for _ in range(n))

    def _utr(self) -> str:
        return "".join(self.rng.choice(string.ascii_uppercase + string.digits) for _ in range(16))

    def _day(self, offset: int) -> str:
        return (self._base + timedelta(days=int(offset))).isoformat()

    def _rupees(self, low: int, high: int) -> int:
        """A whole-rupee amount returned in integer paise."""
        return self.rng.randint(low, high) * 100

    # ---- phase 1: clean payments --------------------------------------------
    def _gen_payments(self) -> list[Payment]:
        methods = list(self.cfg.method_mix.keys())
        weights = [self.cfg.method_mix[m] for m in methods]
        payments: list[Payment] = []
        for _ in range(self.cfg.n_payments):
            method = self.rng.choices(methods, weights=weights, k=1)[0]
            gross = self._rupees(self.cfg.amount_min_rupees, self.cfg.amount_max_rupees)
            capture_day = self.rng.randrange(self.cfg.n_cycles)
            p = Payment(
                payment_id=self._rid("pay_"),
                order_id=self._rid("order_"),
                method=method,
                captured_amount=gross,
                captured_at=self._day(capture_day),
                status="captured",
            )
            # partial refunds only (a full refund would not sit inside a positive settlement)
            if self.rng.random() < self.cfg.refund_rate:
                p.refund_id = self._rid("rfnd_")
                p.refund_amount = (gross * 30 // 100 // 100) * 100  # ~30%, whole rupee
                p.status = "partial_refund"
            payments.append(p)
        return payments

    # ---- exception budget ----------------------------------------------------
    def _budget(self) -> dict[str, int]:
        total = round(self.cfg.n_payments * self.cfg.exception_rate)
        return {bt: round(total * frac) for bt, frac in self.cfg.breaks.items()}

    # ---- phase 3+4: settlements, credits, ledger, breaks ---------------------
    def generate(self, payments: list[Payment] | None = None) -> GeneratedDataset:
        # `payments` lets an adapter inject externally-sourced captures (real public data); the rest
        # of the pipeline — settlements, bank credits, mess, ground truth — is derived as usual.
        cfg = self.cfg
        payments = self._gen_payments() if payments is None else list(payments)
        by_id = {p.payment_id: p for p in payments}
        budget = self._budget()

        # --- pick payment-level break targets (disjoint) ---
        idx = list(range(len(payments)))
        self.rng.shuffle(idx)
        ptr = 0

        def take(k: int) -> list[int]:
            nonlocal ptr
            chosen = idx[ptr:ptr + k]
            ptr += k
            return chosen

        timing_ids = {payments[i].payment_id for i in take(budget.get("timing_in_transit", 0))}
        duplicate_ids = {payments[i].payment_id for i in take(budget.get("duplicate", 0))}
        # compound variance must land on a method that HAS a fee (never UPI — the trap)
        compound_ids: set[str] = set()
        want_compound = budget.get("compound_variance", 0)
        while len(compound_ids) < want_compound and ptr < len(idx):
            p = payments[idx[ptr]]
            ptr += 1
            if p.method != "upi":
                if p.refund_amount is None:  # ensure a refund exists to be un-booked
                    p.refund_id = self._rid("rfnd_")
                    p.refund_amount = (p.captured_amount * 30 // 100 // 100) * 100
                    p.status = "partial_refund"
                compound_ids.add(p.payment_id)
                self._gt_variance[p.payment_id] = "PARTIAL_PAYMENT"

        # --- group settling payments (exclude in-transit) into settlements ---
        settling = [p for p in payments if p.payment_id not in timing_ids]
        by_settle_day: dict[int, list[Payment]] = defaultdict(list)
        for p in settling:
            capture_day = (date.fromisoformat(p.captured_at) - self._base).days
            settle_day = capture_day + cfg.settlement_delay_days
            by_settle_day[settle_day].append(p)

        settlements: list[Settlement] = []
        report_rows: list[SettlementReportRow] = []
        collision_rate = float(cfg.seam_b_mess.get("same_day_collision_rate", 0.0))

        for settle_day in sorted(by_settle_day):
            group = by_settle_day[settle_day]
            batch_id = self._rid("batch_", 8)  # one NEFT batch per settlement cycle (day)
            # split a day's payments into two same-day settlements to create real collisions
            if len(group) >= 2 and self.rng.random() < collision_rate:
                mid = len(group) // 2
                batches = [group[:mid], group[mid:]]
            else:
                batches = [group]
            for batch in batches:
                settlements.append(
                    self._build_settlement(batch, settle_day, report_rows, compound_ids, batch_id))

        # --- bank credits (one clean credit per settlement) ---
        bank_credits: list[BankCredit] = []
        credit_of_settlement: dict[str, BankCredit] = {}
        for s in settlements:
            bc = BankCredit(
                bank_txn_id=self._rid("bank_", 8),
                utr=s.utr,
                value_date=s.created_at,
                credit_amount=s.amount,
                narration=f"NEFT CR: HDFC {s.utr} RAZORPAY SETTLEMENT",
            )
            bank_credits.append(bc)
            credit_of_settlement[s.settlement_id] = bc
            self._gt_credits[bc.bank_txn_id] = {
                "true_settlement_id": s.settlement_id,
                "break_type": "clean",
                "difficulty": [],
            }

        # --- inject Seam-B mess on the hero exception credits ---
        # Hero exceptions are per-settlement (few payouts), NOT a fraction of payments.
        hero_k = round(cfg.seam_b_match_rate * len(settlements))
        self._inject_bank_settlement_mess(settlements, credit_of_settlement, hero_k)
        # tag same-day collisions (post-hoc: >1 credit sharing a value_date)
        self._tag_collisions(bank_credits)

        # --- unexplained: credits that reconcile to no settlement ---
        self._inject_unexplained(bank_credits, budget.get("unexplained", 0))

        # --- ledger (gross-of-fees; net-of-refund except compound = books gross) ---
        ledger = self._build_ledger(payments, compound_ids)

        # --- duplicates: an exact repeat row in the PG source ---
        for pid in duplicate_ids:
            payments.append(_copy_payment(by_id[pid]))
            self._gt_variance[pid] = "DUPLICATE"
        self._counts["duplicate"] = len(duplicate_ids)
        self._counts["timing_in_transit"] = len(timing_ids)
        self._counts["compound_variance"] = len(compound_ids)

        # record timing truth
        for pid in timing_ids:
            self._gt_variance[pid] = "TIMING_IN_TRANSIT"

        dataset = GeneratedDataset(
            payments=payments,
            settlements=settlements,
            report_rows=report_rows,
            bank_credits=bank_credits,
            ledger=ledger,
            ground_truth={
                "generator_version": __version__,
                "seed": cfg.seed,
                "merchant_id": cfg.merchant_id,
                "bank_credits": self._gt_credits,
                "settlements": self._gt_settlements,
                "variance_labels": self._gt_variance,
            },
            manifest={
                "generator_version": __version__,
                "seed": cfg.seed,
                "run_name": cfg.run_name,
                "n_payments": cfg.n_payments,
                "counts": {
                    "payments_rows": len(payments),
                    "settlements": len(settlements),
                    "report_rows": len(report_rows),
                    "bank_credits": len(bank_credits),
                    "ledger": len(ledger),
                },
                "exception_counts": dict(self._counts),
            },
        )
        self._check_invariants(dataset)
        return dataset

    def _build_settlement(
        self,
        batch: list[Payment],
        settle_day: int,
        report_rows: list[SettlementReportRow],
        compound_ids: set[str],
        batch_id: str = "",
    ) -> Settlement:
        setl_id = self._rid("setl_", 8)
        total_net = total_fees = total_tax = total_reserve = total_gross = total_refund = total_tds = 0
        for p in batch:
            fl = compute_fee_line(p.method, p.captured_amount, self.cfg.fees)
            refund_ded = p.refund_amount or 0
            net = (p.captured_amount - fl.mdr_fee - fl.gst_on_mdr - refund_ded - fl.reserve - fl.tds)
            report_rows.append(
                SettlementReportRow(
                    settlement_id=setl_id,
                    payment_id=p.payment_id,
                    order_id=p.order_id,
                    gross_amount=p.captured_amount,
                    mdr_fee=fl.mdr_fee,
                    gst_on_mdr=fl.gst_on_mdr,
                    refund_deduction=refund_ded,
                    net_amount=net,
                    tds=fl.tds,
                    reserve=fl.reserve,
                )
            )
            total_net += net
            total_fees += fl.mdr_fee
            total_tax += fl.gst_on_mdr
            total_reserve += fl.reserve
            total_tds += fl.tds
            total_gross += p.captured_amount
            total_refund += refund_ded
            # engine-resolvable variance labels (informational)
            if fl.mdr_fee and p.payment_id not in compound_ids:
                self._gt_variance.setdefault(p.payment_id, "FEE_DEDUCTION")

        s = Settlement(
            settlement_id=setl_id,
            utr=self._utr(),
            amount=total_net,
            fees=total_fees,
            tax=total_tax,
            reserve_held=total_reserve,
            reserve_release=None,  # hold-only hook
            status="processed",
            created_at=self._day(settle_day),
            tds=total_tds,
            utr_batch_id=batch_id,
        )
        self._gt_settlements[setl_id] = {
            "expected_net": total_net,
            "gross": total_gross,
            "mdr": total_fees,
            "gst": total_tax,
            "refunds": total_refund,
            "reserve": total_reserve,
            "tds": total_tds,
        }
        return s

    def _inject_bank_settlement_mess(
        self, settlements: list[Settlement], credit_of: dict[str, BankCredit], k: int
    ) -> None:
        mess = self.cfg.seam_b_mess
        drift_days = list(mess.get("date_drift_days", [0]))
        targets = self.rng.sample(settlements, min(k, len(settlements)))
        for s in targets:
            bc = credit_of[s.settlement_id]
            diff: list[str] = []
            # date drift
            drift = self.rng.choice(drift_days)
            if drift:
                bc.value_date = (date.fromisoformat(s.created_at) + timedelta(days=drift)).isoformat()
                diff.append("date_drift")
            # UTR garble or missing
            r = self.rng.random()
            if r < float(mess.get("utr_missing_rate", 0.0)):
                bc.utr = ""
                bc.narration = "NEFT CR: HDFC RAZORPAY SETTLEMENT"
                diff.append("utr_missing")
            elif r < float(mess.get("utr_missing_rate", 0.0)) + float(mess.get("utr_garbled_rate", 0.0)):
                garbled = s.utr[:-4] + "".join(self.rng.choice("*#?0") for _ in range(4))
                bc.utr = garbled
                bc.narration = f"NEFT CR: HDFC {garbled} RAZORPAY SETTLEMENT"
                diff.append("utr_garbled")
            # a hero exception must be genuinely hard — guarantee at least one difficulty
            if not diff:
                bc.value_date = (date.fromisoformat(s.created_at) + timedelta(days=1)).isoformat()
                diff.append("date_drift")
            self._gt_credits[bc.bank_txn_id] = {
                "true_settlement_id": s.settlement_id,
                "break_type": "bank_settlement_match",
                "difficulty": diff,
            }
        self._counts["bank_settlement_match"] = len(targets)

    def _tag_collisions(self, bank_credits: list[BankCredit]) -> None:
        by_date: dict[str, list[BankCredit]] = defaultdict(list)
        for bc in bank_credits:
            by_date[bc.value_date].append(bc)
        for same_day in by_date.values():
            if len(same_day) > 1:
                for bc in same_day:
                    gt = self._gt_credits.get(bc.bank_txn_id)
                    if gt and gt["break_type"] == "bank_settlement_match":
                        if "same_day_collision" not in gt["difficulty"]:
                            gt["difficulty"].append("same_day_collision")

    def _inject_unexplained(self, bank_credits: list[BankCredit], k: int) -> None:
        for _ in range(k):
            bc = BankCredit(
                bank_txn_id=self._rid("bank_", 8),
                utr=self._utr(),
                value_date=self._day(self.rng.randrange(self.cfg.n_cycles)),
                credit_amount=self._rupees(500, 40000),  # matches no settlement
                narration="NEFT CR: HDFC RAZORPAY SETTLEMENT",
            )
            bank_credits.append(bc)
            self._gt_credits[bc.bank_txn_id] = {
                "true_settlement_id": None,
                "break_type": "unexplained",
                "difficulty": [],
            }
        self._counts["unexplained"] = k

    def _build_ledger(self, payments: list[Payment], compound_ids: set[str]) -> list[LedgerEntry]:
        ledger: list[LedgerEntry] = []
        for p in payments:
            refund = p.refund_amount or 0
            # normal: merchant books net of refund; compound break: books gross (refund un-booked)
            booked = p.captured_amount if p.payment_id in compound_ids else p.captured_amount - refund
            ledger.append(
                LedgerEntry(
                    ledger_entry_id=self._rid("ldg_", 8),
                    order_id=p.order_id,
                    payment_id=p.payment_id,
                    booked_amount=booked,
                    booked_at=p.captured_at,
                )
            )
        return ledger

    # ---- invariants ----------------------------------------------------------
    def _check_invariants(self, ds: GeneratedDataset) -> None:
        # 2. every settlement: sum(report row net) == settlement.amount
        net_by_settlement: dict[str, int] = defaultdict(int)
        for r in ds.report_rows:
            net_by_settlement[r.settlement_id] += r.net_amount
        for s in ds.settlements:
            if net_by_settlement[s.settlement_id] != s.amount:
                raise AssertionError(
                    f"settlement {s.settlement_id} net {net_by_settlement[s.settlement_id]} != amount {s.amount}"
                )
        # 3. clean bank credit amount == matched settlement amount
        amount_by_settlement = {s.settlement_id: s.amount for s in ds.settlements}
        for bc in ds.bank_credits:
            gt = ds.ground_truth["bank_credits"][bc.bank_txn_id]
            if gt["break_type"] in ("clean", "bank_settlement_match"):
                sid = gt["true_settlement_id"]
                if bc.credit_amount != amount_by_settlement[sid]:
                    raise AssertionError(f"credit {bc.bank_txn_id} amount != settlement {sid} amount")
        # 4. UPI-zero-fee trap: no UPI payment carries a FEE/TAX variance label
        method_by_id = {p.payment_id: p.method for p in ds.payments}
        for pid, label in ds.ground_truth["variance_labels"].items():
            if label in ("FEE_DEDUCTION", "TAX_DEDUCTION") and method_by_id.get(pid) == "upi":
                raise AssertionError(f"UPI-zero-fee trap: UPI payment {pid} labeled {label}")
        # 1. money is integer paise everywhere; and each row nets exactly to its deduction waterfall
        for r in ds.report_rows:
            for v in (r.gross_amount, r.mdr_fee, r.gst_on_mdr, r.refund_deduction,
                      r.tds, r.reserve, r.net_amount):
                if not isinstance(v, int):
                    raise AssertionError(f"non-int money value in report row {r.settlement_id}")
            waterfall = (r.gross_amount - r.mdr_fee - r.gst_on_mdr - r.refund_deduction
                         - r.reserve - r.tds)
            if waterfall != r.net_amount:
                raise AssertionError(
                    f"row {r.payment_id}: gross-mdr-gst-refund-reserve-tds {waterfall} != net {r.net_amount}")


def _copy_payment(p: Payment) -> Payment:
    return Payment(
        payment_id=p.payment_id,
        order_id=p.order_id,
        method=p.method,
        captured_amount=p.captured_amount,
        captured_at=p.captured_at,
        status=p.status,
        refund_id=p.refund_id,
        refund_amount=p.refund_amount,
    )


def run(
    config_path: str | Path,
    seed_override: int | None = None,
    run_name_override: str | None = None,
    out_root: str | Path | None = None,
) -> Path:
    """Load config, generate, and write all outputs. Returns the run's output directory."""
    from .writers import write_dataset  # local import to avoid a cycle

    cfg = GeneratorConfig.load(config_path, seed_override, run_name_override)
    dataset = Generator(cfg).generate()
    return write_dataset(dataset, cfg, out_root=out_root)
