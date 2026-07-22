# Reflection — Orchestrator (Fable 5), 2026-07-21

First-person reflection on the full session: verifying an external AI's evaluation, planning, and
running the implementation with model-tiered agent teams.

---

**Triage-before-dispatch paid for itself again, and more than last time.** The external (Cascade)
evaluation was strategically sound but factually mediocre: of its concrete capability claims, about
five were refuted or materially overstated (fee-adjusted scoring exists; blocked-vote counterfactuals
are persisted; a frozen per-coin market block exists; a decision table exists; no docs/defaults
divergence found). If I had dispatched implementation teams straight from its recommendations, we
would have rebuilt three things the repo already had. The 2026-07-19 lesson ("triage external reviews
against the current tree") generalizes: the *better-written* an external review is, the more its
refuted claims cost you, because polish reads as accuracy. Per-claim verdicts (CONFIRMED / REFUTED /
PARTIAL) with file:line evidence are the right unit of triage output — the improvement plan wrote
itself from them, including an explicit "rejected from the external report" section that prevented
scope creep.

**The one thing the external review undersold was the one real bug.** Cascade called the
Polymarket/Santiment interaction a "UX ambiguity"; the audit showed the filter is skipped for every
candidate whenever santiment is in --discovery. External reviewers see symptoms (banner says Enabled,
candidates clearly unfiltered); only code reads see gates. The generalized lesson: when an external
observer says "this output confused me," treat it as a defect hypothesis to trace, not a
documentation request — confusion at the boundary is often a control-flow bug on the inside.

**Model tiering worked, with one surprise.** Opus 4.8 on monolith implementation and Fable 5 on
design/review split the work as intended, and doing the money-path reviews myself between phases
(targeted greps confirming "persistence-only", checking the one convention risk per diff) was cheap
and caught nothing the agents got wrong — which is itself signal that detailed briefs with explicit
"do not change decision logic" constraints do most of the review's work up front. The surprise was
Sonnet 5 on WS8/WS9: given one flagged uncertainty ("the audit's no-basicConfig finding might be
wrong"), it root-caused a logging bug that an Opus audit agent had gotten wrong. The load-bearing
element wasn't model capability — it was *permission to distrust a stated fact*. Briefs should mark
which claims are verified and which are inherited, so agents know where skepticism is expected.

**Briefing debt showed up exactly where AGENTS.md predicted.** I briefed with line numbers that were
stale within a day and a test-count baseline that was two workstreams old — both anti-patterns
AGENTS.md already documents for commits, which I failed to apply to briefs. Symbol anchors and
"run a fresh collect; your delta = your files" are now the standing rule.

**Phasing by file ownership held; the residual risk is attribution, not conflict.** Serializing
crypto_trading_bot.py edits across phases produced zero conflicts across seven workstreams. The one
scare (WS8 agent seeing WS4's transient test failures) was attribution, and the agent resolved it
correctly by diffing file ownership — the 2026-07-19 lesson, working as intended.

**Reflection harvest keeps out-earning its cost.** Four reflections produced: a second instance of
the module-level basicConfig pattern (correlation_tracker.py), the "implicit-universe aggregation"
hazard pattern with a systematic search recipe, the RECORD_SCHEMA gap, the effect-honesty test idea,
and four explicit push-back points on design constants that final reports had presented with more
confidence. None of these were in any completion report.

**What I'd do differently:** (1) Run the aggregation grep-audit (implicit-universe sweep) as part of
any audit phase, not just when a design agent trips over one instance. (2) Have audit agents stamp
each claim they emit as VERIFIED-BY-ME vs INHERITED — my briefs then inherit that labeling for free.
(3) The improvement plan should have named symbol anchors from the start; the audit reports had them
and I flattened them to line numbers for brevity. Brevity was the wrong trade.
