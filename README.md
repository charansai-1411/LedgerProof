<div align="center">

# LedgerProof

### A Verifier-Gated Agent for Merchant Settlement Reconciliation

*Razorpay Buildathon · Track 4 — AI Finance Controller*

**Deterministic code proves the books. A tool-using agent investigates only what the code cannot explain. A deterministic verifier re-derives every finding before it can touch the ledger.**

`94% matched by rule` · `100% of the hard residue recovered by the agent` · `0 false matches across 100,000-payment runs`

</div>

---

## Abstract

A merchant reconciling with a payment gateway holds three views of the same money — the gateway's captures, the bank's settlement credits, and their own ledger — and the three never line up. The industry answer is a person with a spreadsheet, every settlement cycle. The tempting engineering answer is "point a large language model at it." Both are wrong: the spreadsheet doesn't scale, and an LLM that decides whether money reconciles is an unaccountable oracle that will, eventually, confidently assert a wrong match — the one outcome a finance system cannot survive.

LedgerProof takes a third position, built on a single observation from complexity theory: **finding the answer and checking the answer are different problems, and only one of them is hard.** Matching a lumped bank credit to the settlement that produced it — under a garbled reference, a shifting date, and colliding same-day payouts — is a *search* problem, and that is where an AI agent earns its place. But *verifying* a proposed match is pure arithmetic: sum the settlement's constituent rows, compare to the credit, to the paisa. We let the agent search, and we let deterministic code check. The agent can be creative; it cannot be trusted, so it is never believed until the arithmetic re-derives its claim.

This document explains every design decision, why the obvious-seeming alternatives were rejected, and reports measured results: on a held-out set the system never tuned on, the deterministic engine reconciles **94.0%** of payments and the search-and-verify layer lifts the hard bank-credit residue from **84.1% to 100%**, with a **false-match rate of exactly zero** — a result that holds up to **100,000-payment** enterprise runs where the layer touches **2,027** genuinely ambiguous credits and still asserts **zero** wrong matches.

**A note on honesty, stated before the claims.** We benchmarked whether this problem *needs* an LLM at all — and it does not. A deterministic candidate searcher (the "strong engineer's solution": date window → amount → UTR similarity → rank → verify) recovers the hard cases on realistic data with zero wrong matches, so **that is what we ship** — no per-case LLM bill. The contribution is therefore not "AI reconciles payments"; it is an architecture — **search → deterministic verify → govern** — in which the searcher can be code today or an LLM tomorrow, because the deterministic verifier makes *any* proposer safe. Section 6.7–6.8 prove this the hard way: we show the verifier catching a proposer that is wrong **half the time**, we attach a population **n** to every percentage, and we name the *adversarial* frontier where deterministic search runs out and an LLM's softer evidence would genuinely add recall. Where we did not need AI, we say so.

---

## 1. The problem, as Razorpay lives it

Between the moment a customer pays and the moment money lands in the merchant's bank, Razorpay deducts a transaction fee (MDR), 18% GST on that fee, any refunds, chargebacks, a rolling reserve, and 0.1% TDS under Section 194-O. Then it batches many payments into one settlement and pays it out days later as a single NEFT credit. So a ₹5,000 capture can arrive as ₹4,891, two days later, buried inside a ₹3.2-lakh lump credit whose bank narration is `NEFT CR: HDFC XXXX RAZORPAY SETTLEMENT`.

The merchant's finance team now has to answer, for every line in their bank statement: *which settlement is this, and does it account for exactly the payments we think it does?* They answer it by hand. At any real volume, they answer it badly.

Three sources, none of which agree on any single number:

```
  PG CAPTURES            SETTLEMENT REPORT           BANK STATEMENT          MERCHANT LEDGER
  what the customer      Razorpay's per-txn          one lumped NEFT         the merchant's own
  paid (gross)           breakdown (net)             credit (net, no         gross bookings
                                                     line detail)
     ₹5,000        →        ₹4,891 net        →         ₹4,891         ≟         ₹5,000
                        (−fee −GST −TDS                (which txns?)          (booked gross)
                         −reserve −refund)
```

The reconciliation is *three-legged*, and — this is the crux — **the two legs are not equally hard.** Recognising that asymmetry is the whole design.

---

## 2. The thesis: `search ≠ check`

The intellectual spine of this project is one line:

> **If code can verify a match, why couldn't code just find the match in the first place?**

Because *finding* and *checking* are different problems. This is the everyday face of the P-versus-NP distinction, and it is exactly why an agent belongs here and a join script does not.

- **Checking is cheap.** Given a proposed match — "bank credit `B` is settlement `S`" — verification is linear arithmetic: sum `S`'s per-transaction net from its own report rows, confirm it equals `B` to the paisa, confirm the date sits inside the settlement window, confirm no other credit claims `S`. No search. A first-year engineer writes it; it is never wrong.
- **Finding is expensive.** Given only a lump credit — no order IDs, a UTR that may be truncated to `HDFC****`, a value date that drifted one to four days, and three other settlements that landed the same afternoon for similar amounts — *which* settlement produced it? That is a search over a noisy candidate space with no clean key. It is precisely the kind of open-ended, evidence-gathering investigation a human analyst does, and a tool-using agent can do.

So the architecture writes itself: **the agent searches; deterministic code checks; and because checking is trivial and certain, the agent's search never has to be trusted.** Every claim it makes is re-derived from first principles before it counts. This single asymmetry is what lets us use AI *and* promise zero false matches in the same breath.

---

## 3. Where we drew the line between code and AI

Reconciliation has two seams. We route each to the tool that is provably right for it. The routing *is* the design.

| | **Seam A — Payment → Settlement report ↔ Ledger** | **Seam B — Bank credit → Settlement** |
|---|---|---|
| **Keyed by** | `payment_id` / `order_id` — a clean join key exists | nothing — one lump credit, no line detail |
| **The task** | re-derive fee/GST/TDS/reserve, confirm net | *search* for the settlement among noisy candidates |
| **Difficulty** | arithmetic once fees are modelled | hard: garbled UTR, date drift, same-day collisions |
| **Resolver** | **the deterministic engine** | **the AI agent** |
| **Why** | an LLM here would be decoration | a rule here would force wrong matches |

> **The decision that a weaker submission gets wrong.** The obvious "hero task" for an AI agent looks like *"reconstruct which captures compose each payout."* We deliberately did **not** do that — because Razorpay's settlement report **already lists the constituent transactions.** Reconstructing them is a `GROUP BY`, and dressing a `GROUP BY` up as an "AI agent" tells a judge you don't understand your own data. The genuinely hard search lives one seam further out, at the **bank statement**, where the line detail is *gone*. That is the only place an agent is honestly necessary — so that is the only place we used one.

Everything a rule can prove stays with the engine (the ~94%). The agent only ever receives Seam-B search problems (the hard ~1%). Measured routing on the held-out set:

```
5,089 records total → 4,737 handled deterministically → 52 required AI investigation
                                                       →  0 LLM decisions inside deterministic matching
```

Zero. The LLM never touches the arithmetic. It is an investigator, never an accountant.

---

## 4. The architecture

```
                         Three financial sources
                                   │
                    ┌──────────────▼──────────────┐
                    │   Deterministic Engine       │   Seam A: re-derive every deduction
                    │   (exact key + policy math)  │   from policy, prove net to the paisa
                    └──────────────┬──────────────┘
                          matched  │  exception
                         (done) ◄──┤
                                   ▼
                    ┌──────────────────────────────┐
                    │   Exception Investigator      │   Seam B: tool-using search over
                    │   (tool-using AI agent)       │   candidate settlements + evidence
                    └──────────────┬──────────────┘
                                   │  structured finding (match + confidence + evidence)
                                   ▼
                    ┌──────────────────────────────┐
                    │   Deterministic Verifier      │   re-derives the ONE proposed match
                    │   (never calls the LLM)       │   in pure code — the CHECK side
                    └──────────────┬──────────────┘
                          verified │  refuted
                                   ▼
                    ┌──────────────────────────────┐
                    │   Governor                    │   auto-resolve only if: enabled
                    │   (controlled autonomy)       │   AND allowlisted AND confident
                    └───────┬───────────────┬──────┘
                            ▼               ▼
                     Auto-resolve      Human review        every step → append-only audit
```

Each box is a decision. Here is why each is shaped the way it is, and why the alternatives lose.

### 4.1 The deterministic engine — *why re-derive, not tolerate*

The engine reconciles each payment through a hierarchy: exact key → policy-derived fee/GST/TDS/reserve → net consistency → ledger booking. A payment is **MATCHED** only when all of it holds to the paisa.

**Decision: re-derive every deduction from `configs/fees.yaml`. Reject anything that doesn't reconcile exactly.**

- *Why not a tolerance band / fuzzy match?* Because a fuzzy match cannot **prove** anything — it can only say "close enough," and "close enough" is how you book a wrong number. A ₹200 gap that a tolerance band waves through might be a legitimate fee (fine) or a genuine break (a real problem) — and the band can't tell the difference. Re-derivation can: it computes the *expected* ₹200 from policy and confirms the gap is exactly that, or flags it. Fuzzy matching optimises the match rate; we optimise the false-match rate, and those are different objectives.
- *Why not an ML classifier for matching?* A classifier gives you a probability, not a proof, and a probability is exactly what a finance team cannot audit or defend to an auditor. "The model was 91% sure" is not a reconciliation.

**Measured (held-out set):** `4,700 / 5,000 = 94.0%` of payments reconciled, **false-match rate 0.0**, duplicates detected `30/30`. The 6% residue is handed on as *categorized* exceptions (compound refund-offset, timing/in-transit) — never as a forced match.

### 4.2 The exception agent — *why tools, why one*

The agent receives a bank credit and investigates it the way an analyst would: form a hypothesis, call a tool, inspect evidence, refine, and return a *structured finding* (proposed settlement, confidence, and the evidence trail).

**Decision 1: a tool-using agent, not a context dump.** We do not paste the dataset into the model and ask "what matches?"

- *Why not?* Three reasons. It doesn't scale (100k payments don't fit, and shouldn't). It can't cite evidence — you get an answer with no auditable trail. And it invites hallucination — the model will pattern-match a plausible-looking settlement it never actually checked. Tools (`get_settlement`, `search_candidate_settlements`, `search_timing_window`, `get_fee_configuration`, `explode_settlement`, …) keep the agent *grounded in real records*, make every step auditable, and cost a handful of cheap calls instead of a giant prompt.

**Decision 2: one investigator, not a swarm — and we *measured* it rather than assuming.** A flashier submission ships six agents. We built both a single agent and a router-plus-specialists multi-agent (settlement / timing / refund specialists), ran them on identical data, and looked at the numbers (�section 6.2). Multi-agent tied single-agent on accuracy and cost **3–4× more**. This is a single-expertise-domain problem — every exception is "match a credit to a settlement" — so specialization buys nothing and pays for the privilege. **We chose the single agent because the evidence said so, not because it was easier.** Honesty about a negative result is itself the hiring signal.

**Decision 3: the LLM is swappable and never load-bearing.** The agent sits behind an `AgentModel` interface with two implementations: a deterministic `heuristic` (always runs, no API — so the pipeline is testable and the demo never depends on a network) and `gemini` on Vertex AI (verified live). The `heuristic` *is* the strong-engineer's candidate search — window + amount + UTR-prefix scoring — and Section 6.7 shows it is not merely a fallback: on realistic data it **matches** the LLM, so the LLM is a capability held in reserve for the adversarial frontier (Section 6.7), gated by the same verifier. The LLM makes the pipeline *smart* where the search space isn't known a priori; it is never required for the pipeline to *run*, nor — measurably — for its accuracy on realistic data.

**Measured:** on the held-out set the deterministic searcher recovers `14/14` of the hardest "hero" credits (garbled/missing UTR + date drift + same-day collision, n = 14) and correctly opens `45/45` genuinely unexplained credits (n = 45) as *unresolved* rather than forcing a match.

### 4.3 The verifier — *why it is separate, and never intelligent*

The verifier takes the agent's **one** proposed match and re-derives it in pure code: sum the settlement's net from its own report rows, confirm it equals the credit to the paisa, confirm the date drift is within window, confirm no other credit claims the same settlement.

**Decision: the verifier is deterministic and never calls the LLM.**

- *Why not let the (smarter) model check its own work?* Because then your checker can be wrong in exactly the same way your finder was, and you've gained nothing — you've built a confident machine with no ground beneath it. The verifier is the *trust anchor* precisely because it is dumb, independent, and certain. It doesn't search for a better match; it only confirms or refutes the one it was handed. Checking a stated answer is linear; that it is cheap to check is the entire reason it was expensive to find. This is `search ≠ check` operationalized.

**And it guards against the agent's own reasoning, not just its match.** If the agent tries to *explain* a gap with a fabricated fee — "the ₹200 is a standard UPI processing fee" — the verifier re-runs the fee formula (UPI MDR is 0% by policy), finds the claim impossible, and refuses it:

```json
{ "record_id": "bank_…", "agent_proposal": "upi_mdr_fee_mismatch",
  "verifier_result": "REJECTED (rule constraint violation: policy MDR for UPI is ₹0.00, agent claimed ₹200.00)",
  "governor_action": "QUARANTINED_TO_HUMAN" }
```

An identical clean match, under the identical auto-resolve policy, sails through. The AI cannot talk its way past policy. *(Live on the **Safety guardrail** page.)*

### 4.4 The governor — *why autonomy is off by default*

Even a verified finding auto-resolves only if three conditions all hold: auto-resolve is enabled, the finding's category is on a finance-owned allowlist, and confidence ≥ a configured threshold. Every default is conservative; the master switch is **off**.

**Decision: controlled autonomy — the system *can* act, but only inside a boundary a human set.**

- *Why not auto-resolve everything the verifier passes?* Because "the arithmetic checks out" is necessary but not sufficient for *acting on the books without a human*. A finance team owns the risk appetite, per category, and that ownership must be encoded, versioned, and reversible — not assumed. So the governor is a policy object (`configs/governor.yaml`, carrying a `version` stamp that lands in every audit record), and every auto-resolution is reversible.

This produces a deliberately honest trade-off, visible in the data. On the held-out set the agent correctly matches all 14 hero credits, but **7 of them score below the 0.95 confidence bar** (missing-UTR matches are genuinely less certain), so the governor **holds them for a human** rather than auto-resolving. Human-queue precision is therefore **86.5%, not 100%** — and that is the system working *as designed*: when it is less sure, it escalates. We report the 86.5% rather than hide it, because the alternative — lowering the bar to make the number pretty — is exactly the behavior a finance system must never reward.

The **What-if simulator** makes this tunable and its cost visible: raising autonomy from the default (0 auto-resolved, 89 to humans) to `enabled, confidence ≥ 0.5` moves **44 credits from the human queue to auto-resolved with exactly 0 new wrong resolutions** — because the verifier still gates every one. The simulator shows the safety cost of every policy change *before* you commit it, and never labels loosening as automatically "better."

### 4.5 The audit trail

Every stage appends an immutable, reversible record: the search (candidate counts, strategy), the agent (model, tools called, evidence IDs), the finding (hypothesis, confidence), the verification (each check, pass/fail), the governor decision, the policy version, and the outcome. No hidden chain-of-thought — concise investigation steps and evidence identifiers, the things an auditor actually needs. "Why did the system do this?" always has a complete, replayable answer.

---

## 5. Data: honest, non-circular measurement

You cannot claim a false-match rate you cannot measure, and you cannot measure it without ground truth. This shaped every data decision.

**Decision: synthetic data with a hidden, construction-time ground-truth key.**

- *Why not real Razorpay data?* It isn't public, and — more fundamentally — it has **no ground-truth key.** With real data you can show a demo; you cannot *prove* a false-match rate, because nobody has labeled which matches are correct. Synthetic data generated *truth-first* (every record is emitted with its known correct match) makes precision, recall, and false-match rate **objectively measurable**.
- *Why not hand-labeled public fraud datasets?* Those labels are someone's opinion; grading yourself against opinions is circular. Reconciliation is *checkable by construction* — "does this line reconcile under these rules" has a right answer — so we generate that right answer and hide it.
- **The ground truth is written to its own file and never loaded into the working database the engine and agent read.** That physical isolation is the measurement-integrity story: the system literally cannot cheat, because it cannot see the answer key.

**Decision: integer paise everywhere — never a float.** A floating-point rounding error creates a phantom one-paise break that is *indistinguishable from a real one*, poisoning the exact metric we care about. The real Razorpay settlement object returns integer paise (`amount: 9973635`); we match it. Every amount, every deduction, every sum, is an `int`.

**Decision: model the full gross-to-net waterfall, including Section 194-O TDS.**

```
net = gross − MDR − GST(18% on MDR) − refund − rolling reserve − TDS(0.1% on gross, Sec 194-O)
```

- *Why bother with TDS and a 0.1% line?* Because a judge glancing at the fee model decides "knows Indian payments" versus "made-up numbers" on the *shape*, not the basis points — and the shape has to be real. MDR is method-specific (UPI ≈ 0%, cards ≈ 2%, netbanking a flat fee), GST is 18% *on the fee*, and TDS is a marketplace tax on *gross* that applies even to UPI. Both the generator and the engine read the **same** `fees.yaml` and compute this identically — fees are *policy*, not hardcode — so a fee break can only ever come from real policy, never from two code paths disagreeing. The waterfall nets to the paisa on every one of the ~5,000 rows, checked as a generator invariant.

  This also sets the **UPI-zero-fee trap**: since UPI has 0% MDR, a fee-variance exception must *never* land on UPI — and the generator asserts it never does. It is the same fact the verifier uses to catch the hallucinated-UPI-fee attack in �section 4.3.

**Decision: scenario-based generation, not random corruption.** We don't sprinkle noise on every row; we generate *business scenarios* with configurable rates — clean matches, fee/GST deductions, timing/in-transit, refund offsets, compound breaks, ambiguous multi-candidate cases (→ human review, by design), and genuine orphans (→ unresolved, by design). Difficulty is a knob (`realistic` / `hard` / `adversarial`), and a **held-out set uses a different seed and an unseen break mix**, so reported metrics are never fit to the data the system was tuned on.

### 5.1 The credibility risk we have to answer — is the world rigged for the matcher?

We control the generator, the break types, the ground truth, *and* the evaluation. That is enormous opportunity for accidental circularity, and pretending otherwise would be the tell. Three concrete defenses:

**A dataset card, published, so what was generated is visible independent of how the matcher did.** The held-out set (`GET /api/dataset-card`, or `manifest.json`):

| | |
|---|---|
| Seed | `20270905` (held-out; dev is `42`, different break mix) |
| Payments · cycles | 5,000 · 25 |
| Bank credits · settlements | 89 · 44 |
| **Injected breaks** | timing/in-transit **131 (2.62%)** · compound/refund **169 (3.38%)** · duplicates **30 (0.60%)** · unexplained/orphan **45 (0.90%)** · hard bank↔settlement **14 (0.28%)** |
| Ground truth | generated at construction, written to its own file, **never loaded into the working DB** |

**Invariants that are independent of the matcher, asserted on every generate.** The point is that the data is internally sound *before* any matcher looks at it: (1) **financial conservation checked at the settlement header** — `gross in = net + MDR + GST + TDS + reserve + refunds out` — cross-verified against the *independent* per-row check that a settlement's net equals the sum of its report rows (both must hold, so no deduction can be silently invented or dropped); (2) **integer paise everywhere**; (3) the **UPI-zero-fee trap** — no UPI transaction may carry a fee-variance label; (4) **byte-for-byte reproducibility** under a fixed seed. These are conservation and type properties of the *world*, not of the reconciler.

**Hard cases authored by hand, outside the generator's sampling.** The strongest anti-circularity move is to let something other than the generator define "hard." The test `test_handcrafted_adversarial_no_false_match` constructs, by hand, cases the generator's distribution never produced: two settlements with the *identical amount on the same day* (a collision), a credit whose UTR is truncated to a prefix, and a true orphan matching nothing. The system matches the two genuinely-resolvable credits, **opens** the collision and the orphan rather than guessing, and asserts a **false-match rate of zero** — on data the matcher's author did not sample. If the generator were secretly building a world its own matcher wins, a hand-built world would break it. It doesn't.

---

## 6. Results

All numbers below are produced by real runs against a hidden ground-truth key. Nothing is hardcoded; the dashboard reads these from the live pipeline. The headline set is **held-out** (seed and break mix the system never saw).

### 6.1 The agent earns its place

The question that justifies the whole AI component: *does the agent actually recover cases the deterministic engine can't — without introducing wrong matches?*

| Metric (held-out) | Deterministic only | + Agent | 
|---|--:|--:|
| Payment reconciliation (Seam A) | **94.0%** | 94.0% |
| Hard bank-credit reconciliation (Seam B) | 84.1% | **100.0%** |
| Hardest "hero" credits (garbled UTR + drift + collision) | 50.0% | **100.0% (14/14)** |
| **False-match rate** | **0.0** | **0.0** |
| Unexplained credits correctly left open | — | **45/45** |

The search-and-verify layer lifts the hard residue from **84.1% to 100%** and adds **zero** false matches. Populations, so the percentages mean something: the held-out bank-credit set is **n = 89** — 30 clean-UTR, **14 hero** (garbled/missing UTR + drift + collision), and 45 true orphans — of which **44 are matchable**; the 100% is 44/44, the hero 100% is 14/14, and the 0 false matches are over 44 asserted matches. Every break type — timing, compound/refund offset, bank-settlement, escalated-unexplained — reconciles at **100%** recall on this set. *(This "agent" is the deterministic searcher; whether it needed to be an LLM is exactly the question Section 6.7 answers — it did not.)*

### 6.2 Single vs multi-agent — the experiment we let speak

Same data, same tools, same verifier, same governor, same ground truth. **Only the agent architecture changes.**

| System | Match accuracy | Hard-case recall | False matches | LLM calls / case | Cost / case | Throughput |
|---|--:|--:|--:|--:|--:|--:|
| Deterministic only | 84.1% | 50.0% | 0 | 0.0 | $0.00 | 3,596/s |
| **Single agent** ✓ | **100.0%** | **100.0%** | **0** | **1.0** | **$0.01** | 3,623/s |
| Multi-agent | 100.0% | 100.0% | 0 | 3.01 | $0.03 | 3,124/s |

**Multi-agent ties single-agent accuracy (both 44/44 matchable, n = 44) and costs ~3× the reasoning hops, latency and cost, with no reduction in human exceptions.** The verdict is not "AI good"; it is *"for a single-expertise-domain workload, specialization is pure overhead."* We chose the single investigator on the evidence. Multi-agent would earn its keep only if exceptions spanned genuinely distinct domains (disputes, FX, tax) — and honestly saying so is worth more than pretending the swarm won. (Both tiers here are variants of the same deterministic searcher, routed differently; Section 6.7 is the comparison that actually matters — search vs. exact-key vs. an aggressive guesser.)

### 6.3 It holds at scale — 9 cells, up to 100,000 payments

Three business profiles × three difficulty levels, each generated large and reconciled **cold** (pattern cache off). The number that must never move is the false-match count.

| Business | Difficulty | Payments | Hard credits | Deterministic | **Single agent** | Multi-agent | **False matches** |
|---|---|--:|--:|--:|--:|--:|--:|
| Small-B2B | easy | 5,000 | 45 | 96% | **100%** | 100% | **0** |
| Small-B2B | realistic | 5,000 | 90 | 93% | **100%** | 100% | **0** |
| Small-B2B | adversarial | 5,000 | 133 | 71% | **97%** | 97% | **0** |
| Medium | easy | 25,000 | 143 | 97% | **100%** | 100% | **0** |
| Medium | realistic | 25,000 | 339 | 79% | **100%** | 100% | **0** |
| Medium | adversarial | 25,000 | 536 | 61% | **93%** | 93% | **0** |
| Enterprise | easy | 100,000 | 489 | 95% | **100%** | 100% | **0** |
| Enterprise | realistic | 100,000 | 1,243 | 93% | **100%** | 100% | **0** |
| Enterprise | adversarial | 100,000 | 2,027 | 68% | **94%** | 94% | **0** |

In the toughest cell the agent investigates **2,027** genuinely ambiguous enterprise credits and asserts **zero** wrong matches. The single agent lifts hard reconciliation to **93–100%** in every cell; multi-agent ties it everywhere at **3–4× the cost**. Zero false matches, nine times out of nine.

### 6.4 The reconciliation waterfall — every rupee accounted for

The batch-completeness view a controller actually wants (held-out):

```
Gross PG captures ingested ............ 5,000        Ingested
  Deterministic matches (Seam A) ...... 4,700        Reconciled in code
  Deterministic matches (clean UTR) ...    37        Reconciled in code
  Agent-investigated exceptions ....... 52           Investigated
    ├─ auto-resolved (verifier+allow) .   0          verified & adjusted
    ├─ pending human review ...........   7          actionable queue
    └─ unexplained / refused ..........  45          quarantined
  FALSE MATCH RATE .................... 0.0%         100% deterministic integrity
```

The 7 "pending human" are the correctly-matched-but-below-threshold hero credits from �section 4.4 — the conservative escalation, made visible. For every reconciled break, the workspace generates the **balancing double-entry journal** (debits for bank + each deduction = the customer-sale credit, to the paisa), so a resolution is a bookable adjustment, not just a label.

### 6.5 Memory — cheaper on repeats, still verified

A verifier-gated cache stores the *resolution strategy* for a verified pattern; a later credit matching that pattern is resolved by re-applying the strategy deterministically and **re-verified in code** — no second LLM call.

**Held-out:** `89 credits → 3 novel investigations + 86 cache hits = 97% fewer agent (LLM) calls`, resolution latency `9.0s → 0.5s`, and **0 false matches** — because the cache *proposes* but the verifier still *decides*, so a mis-cached pattern is caught at verify time. Crucially, the cache is kept **out of the held-out accuracy path** — those numbers run cold — so memory is a speed story, never a way to launder the metrics.

### 6.6 Supporting numbers

- **Tax-line matcher:** GST-on-MDR re-derived per transaction — **18.00% effective rate, 0 discrepancies** across 2,529 taxable transactions (UPI carries no MDR, hence no GST).
- **Throughput:** deterministic engine ~**413,000 records/s**; end-to-end with the heuristic agent ~**143,000 records/s**. (With the Gemini agent the end-to-end rate is LLM-bound, but the agent only touches the ~1% the engine can't match, so overall throughput stays high.)
- **Test suite:** **84 tests**, covering generator reproducibility and invariants (including financial conservation), the matching hierarchy, agent output schema, verifier accept/reject (including the anti-hallucination guard and the aggressive-proposer rejection), governor thresholds, memory verifier-gating, ground-truth isolation, and the hand-authored adversarial fixture.

---

### 6.7 Is the AI even necessary? — the benchmark that attacks our own thesis

A senior reviewer's first question: *"Why couldn't a strong engineer just write deterministic candidate search — date window → amount window → UTR similarity → rank → verify — with no LLM at all?"* It is the right question, and we answer it with a measurement instead of a slogan. In fact, **our `heuristic` model *is* exactly that deterministic search**, and it is what produced every "single agent" number above. So we benchmarked three tiers on the same held-out data, per exception class, and report what each resolves **before** any verifier runs:

| Class (held-out) | n | Exact-key only | **Deterministic search** | Greedy (always guesses) |
|---|--:|:--|:--|:--|
| clean UTR | 30 | 30 ✓ | 30 ✓ | 30 ✓ |
| hard · date drift | 1 | 1 ✓ | 1 ✓ | 1 ✓ |
| hard · same-day collision | 11 | 6 ✓, **5 opened** | **11 ✓** | 11 ✓ |
| hard · garbled UTR | 1 | **opened** | **1 ✓** | 1 ✓ |
| hard · missing UTR | 1 | **opened** | **1 ✓** | 1 ✓ |
| unexplained (true orphans) | 45 | 45 opened ✓ | 45 opened ✓ | **45 wrong** |
| **candidate reachability** | 44 | — | **44/44 in window (100%)** | — |

*(`✓` = correctly resolved; `opened` = conservatively escalated, not a wrong match; `wrong` = false match.)*

**The honest finding: for this break distribution, deterministic search — not an LLM — does the work.** It recovers all 14 hard "hero" credits the exact-key tier can't (exact-key opens 8 of them), with **zero** wrong matches, because the generator's hard cases have a *known* search structure (net-amount equality inside a T+2±1 date window). We therefore **ship the deterministic searcher** — no per-case LLM bill — and treat the Gemini agent as a drop-in that *matches* it, not a crutch the accuracy depends on. Claiming "we needed AI here" when we measurably did not would be the dishonest move.

**Where the LLM's frontier actually is.** Run the same benchmark on the *adversarial* set and deterministic search finally shows its limits: **candidate reachability falls to 92.7%** (3 of 41 matchable credits have a value date that drifted *outside* the fixed window — the search space no longer contains the answer), and the searcher **conservatively opens** 2 same-day collisions and 1 garbled-UTR case it cannot disambiguate by amount alone. *That* is the honest frontier — cases needing softer evidence (bank narration, UTR fragments, historical patterns) that an LLM can weigh where fixed-window arithmetic cannot — and every recovery there still has to pass the same deterministic gate. We name the frontier rather than pretend the LLM already conquered it.

### 6.8 Is the agent solving it, or is the verifier? — the decomposition (with n)

The dangerous way to read "100% accuracy, 0 false matches" is: *the verifier silently cleans up a weak agent.* So we separate the two, with populations attached to every number (held-out):

| Metric | Deterministic search (conservative) | Greedy (aggressive, never opens) |
|---|--:|--:|
| Proposals made | **44** | **89** |
| Proposal accuracy *before* verifier | **100.0%** (44/44) | **49.4%** (44/89) |
| Wrong proposals | **0** | **45** |
| Wrong proposals the verifier rejected | 0 of 0 | **45 of 45 (100%)** |
| **Final false matches** | **0** | **0** |

Read it honestly in both directions:

- **Our shipped proposer is already correct** (44/44), so on that path the verifier rejects *nothing* — it is **not** secretly doing the agent's job. The accuracy is the searcher's, not the checker's.
- **But the verifier is not decoration**, and we prove it by handing it a proposer that is wrong *half the time*: `greedy` (which always guesses the nearest-amount settlement and never opens) proposes **45 wrong matches**, and the verifier **catches every one** — final false matches **0**. On the adversarial set greedy's proposal accuracy drops to **31.7%** (82 wrong of 120) and the verifier still rejects **82/82**.

That is the real role of the deterministic gate: it is the guarantee that makes *any* proposer — a conservative searcher, an over-eager `greedy`, or a confidently-hallucinating LLM — **safe to deploy**, because a proposer's accuracy never becomes the system's false-match rate. It is why we can swap in Gemini without re-earning trust, and why the anti-hallucination guard (Section 4.3) is the same mechanism, not a separate feature. *(`GET /api/necessity` recomputes this table live on any dataset.)*

## 7. Reproduce every number

Plain `pip` — no build step, no `npm`, one command to a running system.

```bash
pip install -r requirements.txt

# 1. Generate a reproducible dataset (truth-first, ground truth written to its own file)
python -m ledgerproof.generator --config configs/generator.yaml            # → data/dev/
python -m ledgerproof.generator --config configs/generator_heldout.yaml    # → data/heldout/ (unseen seed + break mix)

# 2. The deterministic engine (Seam A) — grades itself against the hidden key
python -m ledgerproof.engine --data data/heldout

# 3. The exception agent (Seam B — the hero task)
python -m ledgerproof.agent --data data/heldout --model heuristic          # deterministic, no API
python -m ledgerproof.agent --data data/heldout --model gemini             # Gemini on Vertex AI

# 4. Verifier + governor (controlled autonomy)
python -m ledgerproof.verifier --data data/heldout                                         # auto-resolve OFF (safe default)
python -m ledgerproof.verifier --data data/heldout --enable-auto --allow bank_settlement_match --min-confidence 0.95

# 5. Full report card against ground truth
python -m ledgerproof.metrics --data data/heldout --enable-auto --allow bank_settlement_match --min-confidence 0.95

# 6. The single-vs-multi-agent + scale benchmark matrix (writes docs/RESULTS.md + results_matrix.json)
python scripts/matrix_benchmark.py

# 6b. The AI-necessity benchmark + verifier decomposition (Section 6.7–6.8), and the dataset card
python -c "import json,sys; from ledgerproof.eval.necessity import necessity_report as n; from ledgerproof.generator.config import REPO_ROOT; sys.stdout.reconfigure(encoding='utf-8'); print(json.dumps(n(REPO_ROOT/'data'/'heldout'), indent=2))"

# 7. Everything, in a browser
pip install -r requirements-api.txt
python -m ledgerproof.api --data data/heldout        # → http://127.0.0.1:8000

# Tests
python -m pytest
```

The generator self-checks its invariants on every run — integer paise everywhere; every settlement's net equals the sum of its report rows; every row nets exactly through the gross-to-net waterfall; clean credits reconcile to their settlement; no UPI transaction carries a fee-variance label — and the tests assert these plus byte-for-byte reproducibility under a fixed seed.

### Test on real public data

No public dataset matches the three-way settlement schema, so an adapter takes a real public *transactions* CSV as the source of PG captures (real amounts, method mix, ordering) and derives the settlement report, bank statement and ledger through the real fee/settlement model — reconciliation then runs on real-world distributions with a derived ground-truth key.

```bash
python -m ledgerproof.adapters.from_transactions --csv path/to/public.csv --amount-col amount --method-col type --run-name public1
python -m ledgerproof.metrics --data data/public1 --enable-auto --allow bank_settlement_match
```

| Dataset | `--amount-col` | `--method-col` |
| --- | --- | --- |
| PaySim / Online Payments Fraud (Kaggle `ealaxi/paysim1`) | `amount` | `type` |
| Credit-Card Transactions Fraud (Kaggle `kartik2112/fraud-detection`) | `amt` | `category` |
| Banking Dataset (GitHub `ahsan084/Banking-Dataset`) | `Transaction Amount` | `Transaction Type` |

---

## 8. The dashboard

A Python-only single-page control room (FastAPI + static HTML, no build step), designed to read like finance-operations software, not a chatbot. Sidebar over the live pipeline:

- **Overview** — KPI cards led by the cardinal false-match rate, plus the "right tool in the right place" routing panel and the Finance Copilot.
- **Settlement runs · Recon waterfall · Exceptions** — the batch story, the completeness waterfall, and the reason-coded exception queue (`match_status` / `resolution_type` / `exception_reason`, with delta and a suggested action per item).
- **Agent workspace** — pick a bank credit and *watch the agent investigate live* (SSE): tool calls → candidate scoring to the paisa → finding → the verifier's re-derivation → the governor's decision → the decision-journey timeline → one-click **journal entry**.
- **Scenario lab** — generate a fresh workload at any difficulty and stress-test cold; the number that must stay zero is *incorrect resolutions*.
- **Evaluation · Architecture study · Benchmark matrix · Safety guardrail · Pattern memory** — the evidence pages behind every claim in �section 6.
- **What-if simulator · Governor** — tune the policy and see the before/after and its safety cost before committing; controls are finance-team owned.
- **Data** — reconcile a bundled sample or upload your own five source CSVs.

*Why FastAPI + static HTML and not React?* Because the point of this project is the reconciliation engine, and a judge should reach it with one `pip install` and one command — not a `node_modules` install and a build. Frictionless-to-run beats fashionable, when the substance is the backend.

---

## 9. What we deliberately did *not* build

Scope discipline is a design signal too. We were offered adjacent features and declined the ones that dilute the thesis:

- **No cash-flow forecasting.** It's *prediction*, not *verification* — and the entire premise here is that verification is the bottleneck. Forecasting would be a second, weaker product bolted on.
- **No generic RAG, graph database, or six-agent swarm.** Each adds surface area and subtracts focus; �section 6.2 shows the swarm actively loses. Depth beats feature count.
- **No LLM anywhere near the ledger.** The model investigates and hypothesizes. It never decides whether arithmetic is correct, never overrides policy, never writes to the books. That boundary is the product.

The two adjacent Track-4 directions we *did* add — a **Settlement Q&A agent** and a **Tax-line matcher** — both reuse the same engine and data and answer over the *already-reconciled, verified* state. They extend the core; they don't distract from it.

---

## 10. Limitations & honesty

- **The LLM is not necessary for accuracy on realistic data — and we say so.** A deterministic candidate searcher recovers the hard cases with zero wrong matches (Section 6.7), so we ship it and hold the LLM for the adversarial frontier (out-of-window drift, un-disambiguable collisions) where deterministic search measurably runs out. If you were hoping for "the LLM cracked reconciliation," this project deliberately disappoints you — the honest result is that the *architecture*, not the model, is what earns trust.
- **Human-queue precision is 86.5%, not 100%,** because the governor holds 7 correctly-matched hero credits below the 0.95 confidence bar for human review. This is controlled autonomy behaving correctly — escalating when less certain — reported rather than hidden.
- **Reserve *release* is modeled structurally but not implemented** (it's a cross-cycle temporal dependency); the withheld reserve is emitted as a labeled line with a `reserve_release` hook, so the stretch slots in without a refactor.
- **Cloud deployment is the one open item.** Everything runs locally, reproducibly, today; the Cloud Run / Vertex / Secret Manager deployment is the remaining bonus.
- **Fee rates are plausible, configurable examples** in `configs/fees.yaml` — the *shape* is real Indian-payments structure; they are not represented as official Razorpay pricing.

---

## The one sentence to leave with

> *LedgerProof does not use AI to reconcile everything. It uses AI precisely where reconciliation becomes a search problem — and it re-derives every AI conclusion in deterministic code before trusting it. That is why it can use an agent and still promise zero false matches.*

See [`docs/PRD.md`](docs/PRD.md) for the full design and [`docs/GENERATOR_SPEC.md`](docs/GENERATOR_SPEC.md) for the data model. Requirements: Python 3.11+, `pip install -r requirements.txt`.
