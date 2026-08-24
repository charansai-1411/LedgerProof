# Synthetic Data Generator — Spec

> Item #1 of the build (§13). Produces three source files shaped like their real Razorpay
> counterparts + a hidden ground-truth key, all seeded and config-driven. Everything downstream
> measures against this, so it is the load-bearing deliverable. See [PRD §5](PRD.md).

## 0. Non-negotiables

- **Integer paise everywhere.** No floats touch money. `₹5,000.00` is `500000`. Confirmed by the
  real settlement object (`amount:9973635, fees:471699, tax:42070`).
- **Forward generation, then mess.** Generate the *truth* first (payments → settlements → bank
  credits with known composition), then inject breaks/mess while recording labels. The ground
  truth is a byproduct of construction, never reverse-engineered.
- **Ground truth is isolated.** Written to a separate file the engine/agent never read during
  matching. This separation *is* the measurement-integrity story.
- **Seeded + reproducible.** One seed reproduces a dataset exactly. Held-out set uses a *different*
  seed and an unseen break-rate mix.

## 1. Output layout

```
data/<run_name>/
  pg_payments.csv          # source 1 — PG captures (what customers paid)
  settlement_report.csv    # source 2 — Razorpay settlement report (per-txn rows)
  settlements.csv          #            settlement batch headers (keyed by settlement_id)
  bank_statement.csv       # source 3 — lumped bank credits (Seam-B search input)
  internal_ledger.csv      # source 3b — merchant gross bookings
  ground_truth.json        # HIDDEN key — engine/agent must never read this
  ledgerproof.sqlite       # all sources loaded (working DB); ground truth NOT loaded here
  manifest.json            # seed, config snapshot, counts, generator version
```

## 2. Entity fields (all `*_amount`/fee/tax/reserve fields are integer paise)

**PG payment** (`pg_payments.csv`)
`payment_id (pay_…), order_id, method {upi|card|netbanking|wallet}, captured_amount, captured_at, status {captured|refunded|partial_refund}, refund_id (nullable), refund_amount (nullable)`

**Settlement header** (`settlements.csv`)
`settlement_id (setl_…), utr, amount (net paid out), fees (total MDR), tax (total GST-on-MDR), reserve_held, reserve_release (nullable — hold-only hook), status {processed}, created_at`

**Settlement report row** (`settlement_report.csv`) — the batch exploded per transaction
`settlement_id, payment_id, order_id, gross_amount, mdr_fee, gst_on_mdr, refund_deduction, net_amount`
Invariant: `sum(net_amount) over a settlement_id == settlements.amount` for that id.

**Bank statement credit** (`bank_statement.csv`) — lump only, no order detail
`bank_txn_id, utr, value_date, credit_amount, narration`
Narration shape: `"NEFT CR: <BANK> <UTR> RAZORPAY SETTLEMENT"`. `credit_amount` equals the matched
settlement's `amount` in the clean case; UTR is a strong-but-not-guaranteed key (see mess).

**Internal ledger entry** (`internal_ledger.csv`) — merchant's own books, typically gross
`ledger_entry_id, order_id, payment_id, booked_amount, booked_at`

## 3. Fee / tax / reserve model (config-driven — `configs/fees.yaml`)

Plausibly-real, method-specific MDR + 18% GST on the fee. Shape and relative ordering matter, not
basis points. Engine reads the *same* config to reconcile — this is the finance-team-owned config.

```yaml
gst_rate_bps: 1800            # 18% GST applied to the MDR
methods:
  upi:        { mdr_bps: 0,   flat_paise: 0 }      # ≈ 0 — NO fee gap (see trap)
  card:       { mdr_bps: 200, flat_paise: 0 }      # ≈ 2%
  netbanking: { mdr_bps: 0,   flat_paise: 1000 }   # flat ₹10
  wallet:     { mdr_bps: 150, flat_paise: 0 }      # ≈ 1.5%
reserve:
  rate_bps: 500                # 5% rolling reserve, hold-only in v1
  applies_to: [card]           # per-merchant policy; keep narrow
```

Per-transaction: `mdr_fee = round(gross * mdr_bps / 10000) + flat_paise`;
`gst_on_mdr = round(mdr_fee * gst_rate_bps / 10000)`;
`net = gross − mdr_fee − gst_on_mdr − refund_deduction − reserve_slice`. All integer paise, banker-safe rounding fixed and documented.

**⚠️ UPI-zero-fee trap:** UPI MDR ≈ 0, so UPI has no fee gap. The generator must route
`FEE_DEDUCTION` / `TAX_DEDUCTION` exceptions to cards/netbanking/wallet only — never UPI. Asserted in tests.

## 4. Break-injection config (`configs/generator.yaml`)

```yaml
seed: 42
run_name: dev
merchant_id: mrc_demo
n_payments: 5000
n_cycles: 25                   # daily settlement cycles
method_mix: { upi: 0.55, card: 0.30, netbanking: 0.10, wallet: 0.05 }

exception_rate: 0.06           # ~6% agent-worthy residue (NOT 15%); knob per PRD §5

# Break mix — fractions of the exception residue. Engine-resolvable variances (FEE/TAX/
# ROUNDING) are modeled as clean by default and matched deterministically; these are the
# genuinely-hard Seam-B cases plus honest unexplained.
breaks:
  bank_settlement_match: 0.45  # ⭐ hero — Seam B: lump credit ↔ right settlement
  compound_variance:     0.20  # PARTIAL_PAYMENT + stacked deductions
  timing_in_transit:     0.20  # captured cycle N, not yet settled (agent: in-transit vs missing)
  duplicate:             0.05  # same txn twice in a source
  unexplained:           0.10  # honest human-only residue

# Seam-B structural mess (authentic, NOT "we deleted the join key")
seam_b_mess:
  utr_garbled_rate: 0.35       # last-N chars corrupted / partial
  utr_missing_rate: 0.10       # narration lacks a clean UTR
  same_day_collision_rate: 0.40 # multiple settlements land same value_date
  date_drift_days: [0, 1, 2]   # credit value_date vs settlement created_at (T+2 + NEFT)
```

## 5. Ground-truth schema (`ground_truth.json`)

The gradable key. For every bank credit and every injected break:

```json
{
  "generator_version": "0.1.0",
  "seed": 42,
  "bank_credits": {
    "bank_txn_44120": {
      "true_settlement_id": "setl_9K2fQx",
      "break_type": "bank_settlement_match",
      "difficulty": ["utr_garbled", "same_day_collision"],
      "composing_payment_ids": ["pay_A1", "..."]
    }
  },
  "settlements": {
    "setl_9K2fQx": {
      "expected_net": 310927,
      "gross": 331402, "mdr": 3480, "gst": 627, "refunds": 4110, "reserve": 12258
    }
  },
  "variance_labels": {
    "pay_77han": "FEE_DEDUCTION",
    "pay_31kdz": "UNEXPLAINED"
  }
}
```

Grader compares system output against this to compute match rate, **false-match rate (cardinal)**,
exception-classification accuracy, human-queue precision, and coverage.

## 6. Invariants the generator self-checks (fail the run if violated)

1. Money is integer paise — no float anywhere in the pipeline.
2. Every settlement: `sum(report row net) == settlement.amount`.
3. Every clean bank credit: `credit_amount == matched settlement.amount`.
4. No UPI payment carries a `FEE_DEDUCTION`/`TAX_DEDUCTION` exception (UPI-zero-fee trap).
5. Ground truth references only IDs that exist in the sources.
6. Re-running with the same seed produces byte-identical CSVs.

## 7. CLI

```
python -m ledgerproof.generator --config configs/generator.yaml
python -m ledgerproof.generator --config configs/generator.yaml --seed 99 --run-name heldout
```
Reproducible, config-first, seed-overridable. Held-out = different seed + unseen break mix.
