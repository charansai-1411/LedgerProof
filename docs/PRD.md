# LedgerProof — Merchant Settlement Reconciliation Engine
### Product Requirements Document · Production Build

**Context:** Razorpay Buildathon, Track 4 (AI Finance Controller). Built as a deployable product and a hiring artifact — the goal is to demonstrate product thinking, engineering maturity, correct AI judgment, and genuine understanding of Razorpay's settlement domain. Not a hackathon toy.

**One line:** *Deterministic code proves the books; a tool-using AI agent investigates only what the code cannot match, and no resolution is written until the code re-verifies the agent's finding.*

---

## 1. The problem (stated the way Razorpay lives it)

A merchant on Razorpay sees three views of the same money, and they never line up cleanly:

1. **Payment gateway (PG) captures** — what customers paid.
2. **Bank settlement / payout** — what actually landed in the merchant's bank account, net of deductions, on a T+1/T+2 delay.
3. **Merchant internal ledger** — what the merchant's own books expected.

Between capture and payout, Razorpay deducts TDR (transaction fee), GST on that fee, refunds, chargebacks, and holds a rolling reserve. Settlements are batched and time-shifted. So a ₹5,000 capture might arrive as ₹4,891 two days later inside a ₹3.2L batch payout — and the merchant's finance team reconciles this **by hand, in spreadsheets**, every settlement cycle.

The 2026 bottleneck is verification, not generation. Reconciliation is exactly that: high-volume, rules-heavy verification that humans do slowly and inconsistently. Most of it is deterministic and should never touch an LLM. The genuinely hard part — the 5–15% of records that don't match — is investigative reasoning, which is where an AI agent earns its place.

**The shape of the hard part (this is the whole thesis, so state it plainly):** the hard breaks are *hard to find, trivial to check* — the P-vs-NP shape. The hardness is **not** "which captures compose this payout" — Razorpay's settlement report already lists that, keyed by `settlement_id`, so *within Razorpay's world* attribution is a `GROUP BY` and any join like that stays in the deterministic engine. The genuinely hard seam is **bank statement ↔ settlement report**: the merchant's bank shows one lumped NEFT credit ("RAZORPAY SETTLEMENT," a UTR, a date, a total) net of MDR, GST and refunds — no order-level detail — and it must be matched to the *right* settlement batch when the UTR is a strong-but-insufficient signal, settlement date and credit date differ across a T+2-plus-NEFT delay, and several settlements land close together. Finding which settlement a lump credit corresponds to (and confirming its net reconciles) is **search + hypothesis**; re-deriving one proposed match — "does this settlement's net, after its listed MDR/GST/refunds, equal this credit to the paisa, within the plausible date window?" — is a single linear **check**. The agent searches; the code checks. Everything else in the architecture follows from that one asymmetry.

**What "done" looks like:** ingest three sources for a settlement cycle, deterministically match what can be matched, and for every unmatched record produce an investigated, evidence-backed, human-readable explanation — auto-resolving only the high-confidence, re-verified cases and queuing the rest.

---

## 2. Design principles (the hiring signal is here)

1. **Code proves the books. AI investigates the exceptions. Search ≠ check.** This is the core architectural claim, and the answer to the sharpest question a Razorpay engineer will ask — *"if code can verify the agent's finding, why couldn't code match it in the first place?"* Because matching and verifying are different problems. The deterministic engine does clean joins under known keys — settlement report ↔ ledger is keyed per-transaction by `order_id`/`payment_id`, so it matches once fees/GST/refunds are modeled, and an LLM never decides whether ₹4,891 equals ₹5,000 minus fees (arithmetic). The engine *fails* at the **bank statement ↔ settlement** seam, where the correct settlement match must be **discovered**: a lumped bank credit whose UTR is a strong signal but not always sufficient — bank data is noisy or incomplete, settlement and credit dates differ, and multiple same-day settlements collide — so the agent reasons over UTR + date-window + net-amount envelope + settlement metadata to propose the right batch. That discovery is search; the agent does it. The verifier then re-derives the *one* proposed match in pure code — a linear check, not a search. Hard to find, trivial to check. That is not circular; it is the entire point.
2. **A false match is the cardinal sin.** In finance, asserting a wrong match is far worse than leaving an item open. The system is tuned to never claim a match it cannot prove; when unsure, it opens an exception. Every metric reflects this asymmetry.
3. **Controlled autonomy.** Auto-resolution is off by default, gated behind a confidence threshold and a per-category allowlist the finance team controls. The system can act, but only where it has been explicitly trusted, and every action is reversible and audited.
4. **Everything is explainable and auditable.** Every match, every exception, every auto-resolution carries its evidence and its reasoning. A finance person can always answer "why did the system do this?"
5. **Deployable, not demo-ware.** Clean architecture, tests, config, containerized, one-command deploy to GCP. The repo should read like a professional wrote it, because it's the real deliverable.

**Architecture principle:**
> Deterministic engine matches. Agent *searches* the residue to discover scattered linkages. Deterministic verifier *checks* the one proposed linkage. Governor decides auto-resolve vs. human. Everything is audited.
>
> The dividing line is precise: **if a rule explains it, code resolves it and the agent never sees it; the agent only receives breaks that need a hypothesis.** Search is the agent's job; checking is the code's job; the two never blur.

---

## 3. Scope

### In scope
Three-way settlement reconciliation for a single merchant across one or more settlement cycles: PG captures ↔ bank settlement ↔ internal ledger, with the full real deduction stack (TDR, GST, refunds, chargebacks, reserve, timing). Deterministic matching engine, tool-using exception agent, deterministic verifier, governed auto-resolution, audit trail, dashboard, and a synthetic-data generator with ground truth.

### Explicitly out of scope — and why we own the choice
The track is *"run the books **and the cash position**."* We deliberately address **the books half — reconciliation — deeply, rather than the cash-position half shallowly, because verification is the harder and more valuable problem** and the brief's own bar rewards a deep loop over broad coverage. This is a judgment call stated on purpose, not an oversight: forward cash forecasting is a real Track-4 direction, and we are choosing depth on reconciliation over spreading across both.

Also out: forward cash forecasting, tax-line matching as a separate product, settlement Q&A chatbot (other Track-4 directions that would dilute depth) · real Razorpay API integration (synthetic data is the honest, controllable choice — see §5) · fraud detection · multi-merchant/tenant platform · any write-back to a real accounting system.

### Non-goals as trust signals
The system deliberately does **not** auto-resolve anything outside its allowlist, does **not** match outside tolerance, and does **not** hide the items it couldn't resolve. The honest exception list is the product, not a failure of it.

---

## 4. Domain model — the break taxonomy (this is where domain authenticity is proven)

Reconciliation is **three-legged, with two seams of very different difficulty** — this distinction is the domain-authenticity signal, and it decides what routes to the engine vs. the agent:

- **Seam A — settlement report ↔ internal ledger.** Per-transaction, keyed by `order_id`/`payment_id`. The Razorpay settlement report already explodes each `settlement_id` into its component transactions with gross, MDR, GST-on-MDR, refund deductions and net. Deterministic once fees/GST/refunds are modeled → **engine territory**.
- **Seam B — bank statement ↔ settlement report.** A single lumped NEFT credit ("RAZORPAY SETTLEMENT," UTR, date, total) must be matched to the right settlement batch. The UTR is a strong signal but not always sufficient: bank data is noisy/incomplete, settlement date and credit date differ across a T+2-plus-NEFT delay, and multiple settlements land close together. Search + hypothesis → **agent territory**.

**Two-level classification.** *Which seam failed* is the match-level break; *why a per-transaction amount differs* uses Razorpay recon's real **variance vocabulary** — adopt these labels verbatim, they are the actual language of the domain:

`FEE_DEDUCTION` · `TAX_DEDUCTION` · `ROUNDING` · `PARTIAL_PAYMENT` · `UNEXPLAINED`

The first four are rule-resolvable (engine); `UNEXPLAINED` is the honest exception — routed to a human, never forced.

**Routing (the split is the architecture):**

| Break | Seam | Resolver | Why |
|---|---|---|---|
| `FEE_DEDUCTION` (MDR) | A | **Engine** | One fee rule against a per-txn row — arithmetic |
| `TAX_DEDUCTION` (GST-on-MDR) | A | **Engine** | One tax rule against a known fee |
| `ROUNDING` | A | **Engine** | Tolerance band, deterministic |
| Rolling reserve (flat %) | A | **Engine** | One reserve rule per policy |
| Duplicate | any | **Engine** | Dedupe on keys |
| Clean timing / in-transit | A | **Engine** | Deterministic once the later settlement arrives |
| **Bank-credit ↔ settlement match** ⭐ | B | **Agent** | The lump credit must be matched to the right batch under a noisy/insufficient UTR, colliding same-day settlements, and a T+2 date drift — search + hypothesis |
| **Compound variance** (`PARTIAL_PAYMENT` + stacked deductions) | B | **Agent** | A credit short by an amount no single rule explains; decompose into layered deductions, then verify each |
| **Timing vs. genuinely-missing** | B | **Agent** | In-transit across the T+2+NEFT window, or a real break? Reason over cadence + history, not a lookup |
| `UNEXPLAINED` | — | **Human** | No rule and no defensible hypothesis — honest exception, never forced |

⭐ = the agent's **hero task** (see §7). Two rows matter most. **Bank-credit ↔ settlement matching** is the case that proves this is an agent and not a join script — it is real, documented Razorpay behavior (the bank UTR isn't order-level, dates drift, settlements collide), not a contrived subset-sum. And **`UNEXPLAINED`** is the honesty signal: route what it *cannot* explain to a human rather than force a match.

> Design note (correction from earlier drafts): the hero task is **not** "reconstruct which captures compose a payout." Razorpay's settlement report already lists that, so that framing is a `GROUP BY` a judge dismisses instantly — and worse, it signals you don't know the report has per-transaction linkage. The genuinely hard, defensible search lives one seam out, at the bank statement. Everything a rule can close stays in the engine; the agent only ever gets Seam-B search problems.

---

## 5. Data strategy — honest, non-circular measurement

Data is **synthetic and generator-produced**, modeled on Razorpay's real settlement shape. This is a deliberate strength, not a shortcut:

- **The generator holds ground truth.** Every record is generated with a known correct match/break label, so precision, recall, and false-match rate are *objectively measurable* — not self-graded like invented fraud labels would be. Reconciliation is checkable by construction: "does this line reconcile under these rules" has a right answer.
- **The generator is a first-class deliverable.** It produces three source files shaped like their real counterparts (see below) plus a hidden ground-truth key, with a configurable mess level: injectable rates of each break type, timing spread, fee/GST/reserve configs, refund and chargeback density, duplicates, and noise. A clean dataset that matches 100% proves nothing — the mess is the point, and controlling it is how you generate a fair held-out test set. Critically, the mess for Seam B is *structural and authentic*: date drift across the T+2+NEFT window, colliding same-day settlements, noisy bank narrations, and occasionally missing/garbled UTRs — never a manufactured "we deleted the join key" difficulty.
- **Held-out evaluation set** is generated with a different seed and unseen break-rate mix, so reported metrics aren't fit to the data the system was tuned on.

**Generation defaults (all seeded + config-driven — see `docs/GENERATOR_SPEC.md`):**
- **Exception density ~5–7%, not 15%.** A credible deterministic engine clears ~93–95%; the agent earns its place on a *small, genuinely hard* residue. Too many exceptions (a) isn't realistic, (b) burns LLM calls in dev, and (c) undercuts the engine's own credibility ("why does it miss one in seven?"). The rate is a knob — dial *up* for a dense demo run, keep the realistic *headline* metric on the low default.
- **MDR must be plausibly real, method-specific, not arbitrary-but-consistent.** UPI ≈ 0, cards ≈ 2%, netbanking ≈ flat ₹, wallets their own shape, + 18% GST on the fee. Same build effort, free authenticity multiplier — a judge glancing at the fee config decides "knows Indian payments" vs. "made-up numbers" on the *shape and relative ordering*, not the basis points. **Realism trap to catch in the generator, not in debugging:** UPI ≈ 0 MDR means UPI has *no fee gap* — fee-variance exceptions must fall on cards/netbanking, never on UPI.
- **Reserve: hold-only in v1, with a release hook.** Modeling reserve *release* is a cross-cycle temporal dependency (a settlement's net would depend on state from N−2) that complicates ground truth; scoped out of v1. But emit the withheld reserve as a **labeled line** and leave a nullable `reserve_release` field / event stub in the schema, so the release stretch slots in without a refactor. Interview framing: "reserve release is modeled structurally, hold is implemented, release was a scoped stretch" — controlled-scope judgment, not a gap.

**Schema — grounded on the real Razorpay settlement object.** All amounts are **integer paise** (the API returns e.g. `amount: 9973635, fees: 471699, tax: 42070` — this independently confirms the integer-paise decision; never floats). Three sources:

1. **Settlement report** — keyed by `settlement_id` (`setl_…`), carrying `{ id, amount, status, fees, tax, utr, created_at, reserve_held, reserve_release }` (`reserve_release` nullable — the hold-only-with-hook stub), and **exploded to per-transaction rows**: `order_id, payment_id, gross_amount, mdr_fee, gst_on_mdr, refund_deduction, net_amount`.
2. **Bank statement** — lumped credits only: `{ utr, value_date, credit_amount, narration }` (e.g. narration `"NEFT CR: <bank> <UTR> RAZORPAY SETTLEMENT"`). **No order-level detail** — this is the Seam-B search input. The UTR is issued by the correspondent bank; it is a strong reconciliation signal, not a guaranteed clean key.
3. **Internal ledger** — the merchant's own gross bookings: `ledger_entry_id, order_id, payment_id, booked_amount, booked_at` (typically booked gross, no settlement IDs).

The **ground-truth key** records, for every bank credit, exactly which `settlement_id` it corresponds to and the full per-transaction decomposition — so Seam-B matches and variance labels are objectively gradable.

---

## 6. System architecture

```
        ┌─────────────────────────────────────────────────────────┐
        │                    INGESTION                             │
        │  PG captures  ·  Bank settlement  ·  Internal ledger     │
        └───────────────────────────┬─────────────────────────────┘
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │              DETERMINISTIC MATCHING ENGINE               │
        │  exact + rule-based (fee/GST/reserve) + tolerance +      │
        │  many-to-one settlement batching                         │
        │        → MATCHED (proven)      → UNMATCHED (exceptions)   │
        └───────────────┬───────────────────────────┬─────────────┘
              matched    │                           │  unmatched
                         ▼                           ▼
                    ┌─────────┐        ┌──────────────────────────────┐
                    │  BOOKS  │        │   EXCEPTION AGENT (tool-using)│
                    │ PROVEN  │        │  get_transaction()           │
                    └─────────┘        │  get_settlement()            │
                                       │  get_ledger_entry()          │
                                       │  search_similar_transactions()│
                                       │  get_fee_configuration()     │
                                       │  get_merchant_rules()        │
                                       │  get_related_entries()       │
                                       │  Observe→investigate→gather  │
                                       │  evidence→classify→recommend │
                                       └───────────────┬──────────────┘
                                                       ▼
                                       ┌──────────────────────────────┐
                                       │   DETERMINISTIC VERIFIER      │
                                       │  ✓ fee/GST/reserve rule exists│
                                       │  ✓ amount matches expected    │
                                       │  ✓ historical pattern holds   │
                                       │  ✓ no conflicting records     │
                                       └───────────────┬──────────────┘
                                              verified  │  not verified
                                                        ▼
                                       ┌──────────────────────────────┐
                                       │        GOVERNOR               │
                                       │  category on allowlist? AND   │
                                       │  confidence ≥ threshold?      │
                                       └──────┬─────────────────┬──────┘
                                          yes │             no  │
                                              ▼                 ▼
                                       AUTO-RESOLVE       HUMAN REVIEW QUEUE
                                              │                 │
                                              └────────┬────────┘
                                                       ▼
                                        AUDIT TRAIL (append-only)
```

**The division that sells the whole project:** the deterministic engine owns **Seam A** (settlement report ↔ ledger, per-transaction, keyed) and proves everything a rule can close; the agent only ever sees **Seam B** residue (bank credit ↔ settlement, where the match must be searched for); the agent's finding is re-proven by code before it counts; the governor decides whether code-verified findings may act on their own. The LLM never writes to the ledger and never asserts a match.

*(Engine box above: "many-to-one settlement batching" = Seam-A grouping the report already exposes. The genuinely searched batching — matching a lump bank credit to its settlement — is the agent's Seam-B job, not the engine's.)*

---

## 7. The exception agent (where AI judgment is demonstrated)

Not a prompt with context dumped in — a **tool-using agent** that investigates like a finance analyst. Critically, it is **never handed a break a rule could close** (see §4). It receives only search problems.

**Hero task — bank-credit ↔ settlement matching (Seam B).** The single break type that proves this is an agent and not a join script, and the one to build end-to-end first (see §13). A lumped NEFT credit landed in the merchant's bank — a UTR, a value date, a total, a noisy narration, and *no* order-level detail. It must be matched to the right `settlement_id`. Straightforward UTR + date + amount matching resolves the easy majority deterministically; **the agent's value is the exceptions where that isn't sufficient** — the UTR is missing/garbled or shared, the settlement date and credit date straddle the T+2-plus-NEFT window, or several same-day settlements have close totals. There the agent **searches**: pull candidate settlements in the plausible date window, reason over the net-amount envelope (each candidate's net after its listed MDR/GST/refunds) and settlement metadata, propose the single best-matching batch, and hand that one proposed match to the verifier to confirm to the paisa. Hard to find, linear to check. A judge cannot dismiss it as arithmetic, and it is straight from documented Razorpay behavior. **If only one break type ships fully investigated, it is this one.**

> Framing guardrail: pitch the UTR as *"an important reconciliation signal that isn't always sufficient,"* never as *"the wrong key."* Razorpay documents the settlement UTR as a unique reference to track a settlement in the bank account — so the agent's job is exception handling when UTR/date/amount matching falls short, not "discovering the UTR doesn't work." Overclaiming here is a factual error a judge will catch.

**Tools (shaped for Seam B):** `get_bank_credit`, `get_settlement`, `get_settlements_in_window` (candidate batches by date range), `explode_settlement` (per-transaction MDR/GST/refund/net for a settlement), `get_ledger_entry`, `get_fee_configuration`, `get_merchant_rules`, `search_similar_settlements` (historical matching patterns).

**Loop:** Observe the unmatched bank credit → pull candidate settlements in the plausible date window → for each, explode to its net after listed deductions and compare against the credit's amount envelope → weigh UTR/date/metadata signals → propose the single best-matching `settlement_id` with a confidence → hand it to the verifier.

**Output — two artifacts:**
1. **Structured resolution record** (for the system):
```json
{
  "record_id": "bank_txn_44120",
  "break_type": "bank_settlement_match",
  "confidence": 0.93,
  "hypothesis": {
    "matched_settlement_id": "setl_9K2fQx",
    "match_basis": ["date_window", "net_amount_envelope", "utr_partial"]
  },
  "evidence": [
    "bank credit 310927 on value_date 2026-08-24; narration UTR garbled (last 4 'f...40')",
    "3 settlements landed within the T+2 window; only setl_9K2fQx nets to 310927 to the paisa (gross 331402 − MDR/GST 4110 − reserve 16365)",
    "other 2 candidates net to 288140 and 402551 — outside envelope; no collision"
  ],
  "recommended_action": "match_credit_to_settlement",
  "verification": null
}
```
2. **Investigation narrative** (for the human) — a short plain-English account: *"This ₹3,10,927 bank credit on 24 Aug has a partially garbled UTR, so it didn't auto-match. Three settlements landed inside the T+2 window; of those, only settlement `setl_9K2fQx` reconciles to the paisa once its listed MDR, GST and refund deductions are applied to its gross — the other two are ₹22K and ₹92K away, well outside any plausible envelope. Recommend matching this credit to `setl_9K2fQx`."* This is the artifact that proves the agent reached a *defensible* conclusion by search, not lookup — the trait the internship is screening for.

**Guardrail:** the agent proposes; it never resolves. Its confidence and evidence feed the verifier, not the ledger.

---

## 8. Deterministic verifier + governor

**Verifier** (pure code, no LLM): this is the **check** side of search ≠ check. It takes the agent's *one* proposed match and re-derives it deterministically — it never searches, it confirms. For a proposed bank-credit ↔ settlement match: does the claimed `settlement_id` exist and belong to this merchant? Does its net — gross minus its *listed* MDR, GST-on-MDR and refund deductions — equal the bank credit **to the paisa**? Is its `created_at` within the plausible T+2+NEFT window of the credit's value date? Is that settlement already matched to another credit (conflict)? Only if every check passes is the finding "verified." Re-deriving one stated match is linear; that it is cheap to check is exactly why it was expensive to find.

**Governor:** even a verified finding auto-resolves only if (a) its break category is on the finance-team allowlist, and (b) confidence ≥ the configured threshold. Both default conservative — auto-resolve **off** until explicitly enabled per category. Everything else → human review queue. This is the controlled-autonomy signal: the system *can* act, but only inside a boundary a human set.

**Config (finance-team-owned):**
```yaml
auto_resolve:
  enabled: false            # master switch, off by default
  min_confidence: 0.95
  allowlist: []             # agent categories only, e.g. [bank_settlement_match, compound_variance]
```

---

## 8b. Resolved-pattern cache (memory — STRETCH, verifier-gated)

A performance/consistency layer *on top of* the core loop, not a new product surface. When the agent investigates a break, the verifier confirms it, and it resolves, store the **pattern → resolution** mapping. When a structurally identical break reappears, the cache recognizes it and resolves it **without another agent investigation**. This deepens the existing division: the deterministic cache + verifier do the repeat work; the agent is reserved for genuinely novel breaks.

**Why it earns its place (all three are judge-relevant):** throughput (stop paying for an LLM call on the 200th identical break), consistency (the same break always resolves the same way — an audit virtue), and product maturity ("the system learns the merchant's recurring patterns and stops re-investigating them").

**The one rule that keeps it honest — the cache feeds the verifier, it never bypasses it.** Memory *proposes* "this looks like resolved-pattern X"; the deterministic verifier **still re-derives it against this specific record** before anything resolves. Memory is a fast-path hypothesis generator, not an authority — the same *search proposes, code verifies* shape as the agent, with the cache standing in for the agent on repeats. Skipping re-verification because "memory said so" is how one cached wrong resolution silently becomes a *repeated* false match — the cardinal sin, multiplied. Do not build that version.

**Two guardrails:**
1. **Precise pattern key** — same break type, same method, same fee/tax rule applied, amounts matching to the paisa under that rule. A fuzzy "looks similar" key is how you cache a wrong match. Precise key + re-verification means even a mis-cached pattern is caught at verify time on the next record.
2. **Out of the measurement path** — held-out metrics run *cold*. A cache warmed on the tuning set must never inflate held-out accuracy, or circularity is reintroduced. The cache is a runtime feature; evaluation stays clean.

**Sequencing:** build the core loop first (generator → engine → agent → verifier → governor → honest metrics); add the cache once the agent↔verifier path works end-to-end. Impressive *if the core is solid*, a distraction *if it isn't*. Clean cut with zero thesis damage if days get tight.

---

## 9. Audit trail

Append-only record for every decision — match, exception, auto-resolution, human action:
```json
{ "timestamp": "...", "record_id": "bank_txn_44120", "stage": "auto_resolve",
  "break_type": "bank_settlement_match", "matched_settlement_id": "setl_9K2fQx", "confidence": 0.96,
  "evidence": [...], "verifier_result": "passed",
  "governor_decision": "auto_resolved", "policy": {"allowlist": true, "threshold": 0.95},
  "reversible": true }
```
Every auto-resolution is reversible. A finance lead can audit exactly why any record landed where it did. This is table stakes for anything touching money and a direct answer to the track's "honest exception list" bar.

---

## 10. Metrics (honest, false-match-aware)

The headline is **not** a single match rate. Report the full, honest picture on the held-out set:

- **Match rate** — % reconciled deterministically.
- **False-match rate** — the cardinal metric; target ~0. A wrong match counts far more heavily than an open item.
- **Auto-resolve rate** — % of exceptions the system resolved under governance.
- **Exception-classification accuracy** — agent's break-type calls vs. ground truth.
- **Human-queue precision** — of items sent to humans, how many were genuinely ambiguous (not things the system should have caught).
- **Coverage of the honest exception list** — every unresolved item has a reason.
- **Throughput** — records/second, to show it scales past a cherry-picked example.

Framing line for the demo: *"We reconciled 4,873 of 5,000 records with zero false matches; the agent auto-resolved 94 of the 127 exceptions under policy, and here are the 33 it correctly refused to touch — each with why."*

---

## 11. Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Language/API | Python 3.11 + FastAPI | Standard, fast, testable |
| Packaging | **`requirements.txt` + `pyproject.toml`** (metadata) | Frictionless-to-run beats fashionable-to-read for a hiring artifact — the reviewer `git clone`s and runs on *their* machine first try. `pip install -r requirements.txt` is the required path; uv-compatibility is a README mention, not a dependency |
| Matching engine | pandas / SQL, pure deterministic | Correctness over cleverness; no LLM in the match path |
| Exception agent | **Gemini (Vertex AI)** behind a clean `AgentModel` interface | Free test access during the build; strong structured tool-calling; Vertex aligns with GCP credits if we reach deploy. Interface keeps it swappable to Claude — a deliberate engineering-judgment signal in the repo |
| Verifier/governor | Pure Python | Deterministic, auditable |
| DB | Cloud SQL (Postgres) | Sources, matches, exceptions, audit |
| Secrets | Secret Manager | No keys in code |
| Logging | Cloud Logging (basic) | Observability without a DevOps project |
| Container/deploy | Docker → Cloud Run, one-command deploy | Ships to cloud, proves you can deploy |
| Dashboard | React (minimal, polished) | Recon run view + exception queue + audit drawer |
| Tests | pytest | Engine correctness + generator + verifier are all unit-tested |

The agent is behind an interface so the model is swappable and the deterministic path is independently testable — an architecture choice worth stating in the README.

---

## 12. Dashboard (one clear story, not a generic fintech dashboard)

- **Recon summary:** `4,873 / 5,000 reconciled · 0 false matches · 127 exceptions · 94 auto-resolved · 33 in review`.
- **Source-of-truth panel:** the three views side by side for any transaction.
- **Exception queue:** each row expands to Diagnosis → Evidence (tool calls) → Verifier result → Governor decision → Narrative → audit. Clicking a queued item shows the human exactly what the agent found and why it stopped short of resolving.
- **Governor controls:** the allowlist/threshold config, visibly finance-team-owned.
- Every screen answers "why did the system do this?"

---

## 13. Build plan — submission deadline **5 Sep 2026**

Roughly 11 calendar days from the 25 Aug start, so the nominal 10-day plan below holds with ~1 day of slack. The slack does **not** buy more scope — it buffers the hero task (Seam B) and the honest metrics. The ruthless cut list after the table governs if anything slips.

| Days | Deliverable |
|---|---|
| **1–2** | Domain model + synthetic data generator with ground-truth key and configurable break rates. Nail the Razorpay settlement shape (TDR, GST, reserve, timing). This is the foundation — everything measures against it. |
| **3–4** | Deterministic matching engine: exact → rule-based (fee/GST/reserve) → tolerance → many-to-one batching. Unit-tested to zero false matches on the test set. |
| **5–6** | Exception agent + the seven tools. Structured finding + narrative. Get one break type fully investigated end-to-end, then broaden. |
| **7** | Deterministic verifier + governor (allowlist, threshold, off-by-default). Auto-resolve vs. human routing. |
| **8** | Audit trail + metrics harness on the held-out set. Wire false-match rate as the cardinal metric. |
| **9** | Dashboard: recon summary, exception queue with the expansion story, governor controls. |
| **10** | Dockerize, deploy to Cloud Run + Cloud SQL + Secret Manager, one-command deploy. README with per-decision rationale. Buffer + polish. |

**Ruthless priority order (not gentle — this is the cut list).** The internship is decided by the loop, not the URL. A deep loop that visibly reasons beats a shallow one that deploys prettily. Build strictly in this order; if days slip, cut from the bottom:

1. **Generator with ground truth** — non-negotiable foundation.
2. **Deterministic engine** — matches everything a rule can, to zero false matches.
3. **Agent on the ONE hero break type — bank-credit ↔ settlement matching (Seam B)** — the most obviously non-trivial case, the hardest to dismiss as a join, and straight from documented Razorpay behavior. If only one agent break type ships, it is this.
4. **Verifier + governor** — check the agent's proposed linkage; gate auto-resolve.
5. **Honest metrics on the held-out set** — false-match rate as the cardinal number.
6. *Stretch, on top of a solid core:* **Resolved-pattern cache (§8b)** — verifier-gated; clean cut if days slip.
7. *Bonus, first to cut:* **Dashboard.**
8. *Bonus, first to cut:* **Cloud Run / Cloud SQL deploy.**

Items 1–5 are the bar. **3–4 break types total is the floor, not the ceiling** — one deep agent break type beats eleven shallow ones. Items 6–8 are stretch/bonus and the first things to drop if time runs short (cache before dashboard before deploy). Protect the generator and engine (days 1–4) above everything; never cut the engine or the honest metrics to save a break type, a cache, or a deploy.

---

## 14. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Synthetic data too clean → trivial match → "proves nothing" | Configurable, aggressive mess; held-out set with unseen mix; false-match metric |
| Agent hallucinates a resolution | It never resolves — verifier re-proves in code; governor gates; auto-resolve off by default |
| Scope creep (forecasting, Q&A, multi-tenant) | Frozen §3; one loop done deeply |
| Deploy eats build days | Lean GCP footprint; one-command deploy; day 10 only |
| Looks like a join script, not an agent | The agent is pointed *only* at Seam-B search problems (§4 split); the hero task is bank-credit ↔ settlement matching under a noisy/insufficient UTR, colliding same-day settlements and T+2 date drift — documented Razorpay behavior, not a join; rule-resolvable Seam-A breaks never reach it |
| Overclaiming "UTR isn't the key" | Pitch UTR as an important-but-insufficient signal; agent handles the exceptions where UTR/date/amount matching falls short (§7 guardrail). Razorpay documents UTR as a valid settlement tracker — don't contradict it |
| Pattern cache turns one wrong resolution into a *repeated* false match | Cache proposes, verifier still re-derives against each specific record (§8b); precise pattern key; cache never bypasses verification |
| Cache warmed on tuning data inflates held-out metrics | Cache is a runtime feature only; held-out evaluation runs cold (§8b guardrail 2) |
| Over-planning instead of building | This PRD is frozen. Day 1 starts the generator, not another doc. |

---

## 15. Why this wins the internship (not just the track)

It shows the four things the screen is actually testing: **product thinking** (the honest exception list, false-match-as-cardinal-sin, controlled autonomy), **engineering** (deterministic core, tested, deployed, clean repo), **AI judgment** (AI confined to investigation, re-verified by code, never touching the ledger), and **understanding of Razorpay's business** (the settlement break taxonomy is their real world, not a generic one). The one sentence a judge should leave with: *"This person understands exactly where AI belongs in a payments system — and where it doesn't."*

---

*Every architectural choice in this document has a stated rationale so it can be defended in an interview. Build it so it's genuinely yours to explain.*
