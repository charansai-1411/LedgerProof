# LedgerProof — 5-minute pitch (Track 4 · AI Finance Controller)

Voiceover over a screen recording of the live app. First person. ~5:00.
Live: https://ledgerproof-1020004477951.asia-south1.run.app

---

## ElevenLabs script (copy-paste — spoken words only)

Every merchant on a payment gateway lives with three versions of the same money. What the customer paid. What the bank actually deposited. And what their own books say they're owed. And the three never agree.

Between them sits a stack of deductions — fees, GST, a marketplace TDS, refunds, a rolling reserve. So a five-thousand-rupee sale arrives as four thousand eight hundred and ninety-one, two days late, buried inside a single bank credit worth lakhs. And that bank line doesn't even tell you which payments it's paying for. It's just one number. Today, a human untangles that by hand, every settlement cycle. That's the problem I picked. Not glamorous. Just real, and everywhere.

The whole design rests on one idea. Finding an answer and checking an answer are not the same problem. Matching a garbled bank credit to the right settlement is a search — genuinely hard. But verifying a proposed match is only arithmetic. You sum the parts, to the paisa. So I let code do the checking, and I never trust the searching until the arithmetic agrees.

Here's what that becomes. A deterministic engine clears the clean ninety-four percent by rule — no AI anywhere near the money. Whatever's left — a garbled reference, a drifted date, two payouts that collide on the same day — goes to an AI exception investigator. It searches, it scores candidates, and it proposes one match, with its evidence.

And that's where, one night, it almost fell apart.

Because I ran the experiment that could embarrass me. I asked, honestly — does this problem even need an LLM? I put a plain deterministic searcher next to my AI agent, on the same data. And the searcher won. It reconciled everything the agent did, with zero wrong matches. My agent's marginal accuracy was exactly zero.

The code didn't break that night. My thesis did. I was sitting there with an AI-track submission whose headline finding was — the AI adds nothing.

I had two choices. Bury the number, or believe it.

I believed it. And the moment I stopped asking the agent to be more accurate, I finally saw what it was actually for. Not matching — code already wins at matching. What the agent buys you is speed, and safety, on the cases a rule can't close.

So I proved that instead. A human working one exception alone opens about seven candidate settlements to find the match. With the agent, they audit just one — already searched, already verified. That's six-point-seven times fewer records to inspect. Two-thirds less investigation time. Same accuracy. Zero false matches.

And I didn't stop at one agent. I asked the obvious next question — would a whole team of specialists do better? A router, a settlement expert, a timing expert, a refund expert. I ran it five times over, fresh data each time. The team tied the single agent exactly — same accuracy — at nearly three times the cost. So I shipped the one. Another place I chose less AI, because the evidence told me to.

And accuracy is the one place I refused to compromise. Every match the agent proposes, a deterministic verifier re-derives in pure code. It never calls the model. If the arithmetic disagrees, even by a single paisa, the finding dies right there.

I even tried to make my own agent lie. I handed it a match that blamed a two-hundred-rupee UPI processing fee — a fee that, by policy, cannot exist. The verifier re-ran the formula, saw the impossible number, and refused it. The model can be wrong. It can even be confidently wrong. It still cannot talk its way past the arithmetic.

Only then does a governor decide whether it's safe to auto-resolve — and it stays off by default. When it does resolve, it doesn't just say "matched"; it posts the balanced journal entry, to the paisa. And every step lands in a tamper-evident audit chain you cannot quietly rewrite.

The AI investigates. Code decides. That is the line I do not cross — and I can prove every word of it.

Across nine workloads, up to a hundred thousand payments, in the hardest case the agent touches more than two thousand genuinely ambiguous credits and asserts zero wrong matches. In finance, that zero is the only number that matters. And it never travels alone — a hundred percent auto-resolution precision, eighty-four percent coverage. This isn't a system that refuses everything hard. It acts, and it never acts wrongly.

Then I tried to break it. Corrupt data. A lying model. A dead tool. A duplicated payout. Eight different failures, injected on purpose. Eight out of eight — detected, contained, and routed to a human. Zero wrong financial actions. Every single time.

Everything else is here too. A reconciliation waterfall. A scenario lab. A verifier-gated pattern cache. A decision-ready review queue. A what-if policy simulator. And a finance copilot that answers off the real, reconciled data. Ninety-five tests. Live on Google Cloud right now.

You said you read the work, not the resume. So here's the work — a repo that runs, and the night it almost fell apart.

I built an AI Finance Controller. And then I proved, in my own repo, exactly where the AI should not touch the money. That's the judgment. Thank you.

---

## Screen recording cues (map each beat)

1. Three-views diagram — "three versions of the same money…"
2. `search ≠ check` line — "finding and checking are not the same…"
3. Investigation Workspace, cursor down the decision journey — "a deterministic engine clears the clean 94%…"
4. Architecture study → AI-necessity table (agent opportunity: 0) — "and that's where, one night, it almost fell apart…" (SLOW DOWN)
5. Manual-work-avoided card — "six-point-seven times fewer records…"
6. Architecture study → single-vs-multi table (tie at ~3× cost) — "would a whole team of specialists do better?"
7. Safety guardrail page, poisoned-vs-control cards — "I even tried to make my own agent lie…" (the REJECTED card is the beat)
8. Verifier column: green 5/5 checks, re-derived net, journal entry, audit-chain badge — "a deterministic verifier re-derives in pure code…"
9. Benchmark matrix, then Overview quartet — "a hundred thousand payments… zero wrong matches…"
10. Fault injection — PRESS "Break the system" LIVE — "eight out of eight… zero wrong financial actions."
11. Slow sidebar pan, rest on the live URL + "0 false matches" hero — "here's the work… the night it almost fell apart."

## ElevenLabs settings

Voice: a calm, warm narrator (Adam / Daniel / Brian). Stability ~45–50, Similarity ~75, Style 0–10, Speaker Boost on.
Dramatic pauses — insert `<break time="0.7s" />` before "I believed it." and after "the AI adds nothing."

## Recording checklist

- Warm the live URL a minute before recording (avoid cold-start lag).
- Pre-run "Break the system" once so the result is instant on camera.
- If it runs long, trim the "Everything else is here too" montage first; never cut the 2 AM beat.
