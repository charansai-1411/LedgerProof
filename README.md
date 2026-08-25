# LedgerProof — Merchant Settlement Reconciliation Engine

*Razorpay Buildathon · Track 4 (AI Finance Controller)*

Track 4 lists four *example directions* — pick one. LedgerProof goes **deep on Multi-source
reconciliation** (the core), and adds two that reuse the same engine and data: a **Settlement Q&A
agent** and a **Tax-line matcher**. (Forward cash forecasting is deliberately out — it's prediction,
not verification, and the brief's "why now" is that *verification* is the bottleneck.)

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

## Run the exception agent (Seam B — the hero task)

```bash
python -m ledgerproof.agent --data data/dev --model heuristic   # deterministic, no API
python -m ledgerproof.agent --data data/dev --model gemini      # Gemini on Vertex AI
```

Matches each lumped bank credit to the right settlement when the UTR is garbled/missing/shared,
the value date drifts, and same-day settlements collide — searching candidate settlements in the
window and reconciling on the net-amount envelope, opening a credit as *unexplained* rather than
forcing a match. On the default dataset: **9/9 hero credits matched, 45/45 unexplained correctly
opened, false-match rate 0.0.**

The model sits behind a swappable `AgentModel` interface:
- `heuristic` — deterministic baseline / no-API fallback (always runs).
- `gemini` — Gemini on Vertex AI (verified live: matches the hard credits and opens the unexplained
  ones correctly). Needs `pip install -r requirements-agent.txt`, the Vertex AI API enabled, and
  `gcloud auth application-default login` (project `ledgerproof-506605`, `us-central1`).

## Run the verifier + governor (Item #4)

```bash
python -m ledgerproof.verifier --data data/dev                       # conservative default: auto-resolve OFF
python -m ledgerproof.verifier --data data/dev --enable-auto \
    --allow bank_settlement_match --min-confidence 0.95              # controlled autonomy, on
```

The verifier re-derives the agent's *one* proposed match in pure code (settlement net summed from
its own report rows == bank credit to the paisa, within the date window, no conflicting claim) —
the *check* side of search ≠ check; it never searches. The governor then auto-resolves a verified
finding **only** if auto-resolve is enabled, its category is on the allowlist, and confidence ≥ the
threshold — all off by default. Every decision emits an append-only, reversible audit record.

With auto-resolve off, all 35 verified matches are still **held for human review**. Enabling it with
`bank_settlement_match` on the allowlist auto-resolves the 35 and routes the 45 unexplained credits
to human review.

## Report card on the held-out set (Item #5)

```bash
python -m ledgerproof.generator --config configs/generator_heldout.yaml   # different seed + unseen break mix
python -m ledgerproof.metrics --data data/heldout --enable-auto --allow bank_settlement_match --min-confidence 0.95
```

Runs the whole loop end-to-end and grades it against the hidden ground truth. On the held-out set
(seed and break mix the system never saw):

```
CARDINAL  combined false-match rate : 0.0  (0 wrong of 4745 asserted)   PASS
Seam A   4700/5000 payments (94.0%)  0 false   partial/timing recall 100%  dupes 30/30
Seam B   47/47 credits matched (hero 15/15)  0 false   45 unexplained opened
Governance  47 verified · 45 auto-resolved (0 wrong) · 47 human queue (precision 96%)
Throughput  ~66,000 records/s
```

The headline is not a single match rate — it is the full, honest picture, with **false-match rate
as the cardinal number**. (Two verified hero credits with *missing* UTRs scored below the 0.95
confidence threshold, so the governor correctly held them for human review — controlled autonomy at
work, and why human-queue precision is 96% not 100%.)

## Dashboard (Item #7)

```bash
pip install -r requirements-api.txt
python -m ledgerproof.api --data data/heldout        # then open http://127.0.0.1:8000
```

A Python-only single-page SaaS dashboard (no npm/build step), light and minimal, with sidebar
navigation over the live recon pipeline:
- **Overview** — KPI cards led by the cardinal combined false-match rate, plus the governor controls
  (toggle auto-resolve, confidence threshold, allowlist → Apply; KPIs update live).
- **Exceptions** — every bank credit expands to its full story: agent evidence → verifier checks
  (re-derived in code) → governor decision → plain-English narrative → audit. "Why did the system do this?"
- **Q&A agent** — ask about the run in natural language.
- **Tax** — the GST-on-MDR reconciliation, per method.
- **Source of truth** — the three views (PG capture · settlement report · internal ledger) side by side.
- **Import data** — reconcile a bundled sample dataset, or **upload your own source CSVs** (five files,
  column templates provided). Uploaded runs have no ground-truth key, so the UI honestly shows the
  operational reconciliation without accuracy-vs-truth metrics.

## Status

- [x] Synthetic data generator with ground-truth key
- [x] Deterministic matching engine (Seam A) — 94% match rate, **0 false matches**
- [x] Exception agent — bank-credit ↔ settlement matching (Seam B) — 15/15 hero on held-out, **0 false matches** *(heuristic + Gemini/Vertex, verified live)*
- [x] Deterministic verifier + governor — re-derives each match; controlled autonomy off by default; **never confirms a wrong match**
- [x] Honest metrics harness on the held-out set — **combined false-match rate 0.0** across 4,745 asserted reconciliations
- [x] Dashboard — FastAPI-served single page: summary · exception queue · governor controls · source-of-truth
- [x] Resolved-pattern cache — verifier-gated; **97% fewer agent (LLM) calls, 0 false matches**
- [x] Settlement Q&A agent — natural-language questions over the reconciled data *(RuleQA + Gemini, verified live)*
- [x] Tax-line matcher — GST-on-MDR reconciliation, per method; **18.00% effective rate, 0 discrepancies**
- [ ] *Bonus:* Cloud Run deploy

## Settlement Q&A agent + Tax-line matcher (additional Track-4 directions)

```bash
python -m ledgerproof.qa  --data data/heldout "how much GST did we pay? which credits are unexplained?"
python -m ledgerproof.qa  --data data/heldout --model gemini "why was bank_xxxx opened?"   # Gemini agent
python -m ledgerproof.tax --data data/heldout
```

The **Q&A agent** answers natural-language questions over the same reconciled results and audit
trail — match rate, MDR/GST totals, why a credit was opened, what's in the human queue — with a
deterministic keyword router (no API) or a Gemini function-calling agent. The **tax-line matcher**
independently re-derives GST-on-MDR against policy per transaction and aggregates by method (UPI
carries no MDR, so no GST). Both are also surfaced as panels on the dashboard.

## Resolved-pattern cache (Item #6, stretch)

```bash
python -m ledgerproof.cache --data data/heldout
```

A verifier-gated performance layer: when the agent resolves a credit and the verifier confirms it,
the resolution *strategy* is cached against a precise pattern key. A later credit matching that
pattern is resolved by re-applying the cached strategy deterministically — **without another agent
(LLM) investigation** — and is **still re-verified in code**. On the held-out set: 92 credits → **3
agent investigations** (one per novel pattern) + 89 cache hits = **97% fewer agent calls, 0 false
matches**. The cache proposes; the verifier still decides — so a mis-cached pattern is caught at
verify time, and the cache stays out of the metrics path (held-out numbers run cold).

## Requirements

Python 3.11+. Dependencies: `PyYAML` (runtime), `pytest` (dev). `uv`-compatible if you prefer it,
but plain `pip install -r requirements.txt` is the supported path.
