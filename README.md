# LedgerProof — Merchant Settlement Reconciliation Engine

*Razorpay Buildathon · Track 4 (AI Finance Controller)*

> **Deterministic code proves the books; a tool-using AI agent investigates only what the code
> cannot match, and no resolution is written until the code re-verifies the agent's finding.**

A merchant sees three views of the same money that never line up: PG captures, the bank
settlement, and their own ledger. LedgerProof reconciles them — matching everything a rule can
deterministically (the ~94%), and pointing a tool-using agent at the genuinely hard residue: the
**bank statement ↔ settlement** seam, where a lumped NEFT credit must be matched to the right
settlement batch under a noisy/insufficient UTR, T+2 date drift, and colliding same-day payouts.

See [`docs/PRD.md`](docs/PRD.md) for the full design and [`docs/GENERATOR_SPEC.md`](docs/GENERATOR_SPEC.md)
for the data model.

## Quick start (no friction — plain pip)

```bash
pip install -r requirements.txt
python -m ledgerproof.generator --config configs/generator.yaml
```

That writes a reproducible dataset to `data/dev/`:

| File | What it is |
| --- | --- |
| `pg_payments.csv` | PG captures — what customers paid |
| `settlement_report.csv` | Razorpay settlement report, exploded per transaction |
| `settlements.csv` | Settlement batch headers (keyed by `settlement_id`) |
| `bank_statement.csv` | Lumped bank credits — the Seam-B search input |
| `internal_ledger.csv` | Merchant gross bookings |
| `ground_truth.json` | Hidden answer key — the engine/agent never read this |
| `ledgerproof.sqlite` | All sources loaded (working DB); ground truth **not** loaded here |
| `manifest.json` | Seed, config snapshot, counts |

Produce a held-out evaluation set with a different seed and (optionally) a different config:

```bash
python -m ledgerproof.generator --config configs/generator.yaml --seed 99 --run-name heldout
```

## Tests

```bash
python -m pytest
```

The generator self-checks its invariants on every run (integer paise everywhere; every
settlement's net equals the sum of its report rows; clean credits reconcile to their settlement;
no UPI transaction carries a fee-variance label). The tests assert these plus byte-for-byte
reproducibility under a fixed seed.

## Design integrity notes

- **All money is integer paise — never a float.** Matches the real Razorpay settlement object.
- **The ground truth is isolated** in its own file and never loaded into the working DB — that
  separation is the measurement-integrity story (metrics can't be self-graded).
- **Fees are policy, not hardcode:** [`configs/fees.yaml`](configs/fees.yaml) is read by both the
  generator and (soon) the deterministic engine.

## Run the deterministic engine (Seam A)

```bash
python -m ledgerproof.engine --data data/dev
```

Reconciles settlement report ↔ ledger per transaction, re-deriving every deduction from
`configs/fees.yaml`, and grades itself against the hidden ground truth. On the default dataset it
clears **95.2%** with a **false-match rate of 0.0** — the cardinal metric — and hands the residue
(compound partial-payments and timing/in-transit) onward as categorized exceptions.

## Status

- [x] Synthetic data generator with ground-truth key
- [x] Deterministic matching engine (Seam A) — 95.2% match rate, **0 false matches**
- [ ] Tool-using exception agent — bank-credit ↔ settlement matching (Seam B, the hero task)
- [ ] Deterministic verifier + governor
- [ ] Honest metrics harness on the held-out set
- [ ] *Stretch:* resolved-pattern cache · dashboard · Cloud Run deploy

## Requirements

Python 3.11+. Dependencies: `PyYAML` (runtime), `pytest` (dev). `uv`-compatible if you prefer it,
but plain `pip install -r requirements.txt` is the supported path.
