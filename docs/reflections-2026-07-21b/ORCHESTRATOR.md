# Orchestrator reflection — improvement cycle 2 (2026-07-21, evening)

First-person reflection from the Fable 5 orchestrator that vetted the Cascade live-session
transcript and ran cycle 2.

## What the cycle was

Input: a 20-recommendation external-AI (Cascade) review of the 2026-07-21 live showcase
session. Output: 9 implemented workstreams + 2 audit-driven follow-ups, suite 893 → 1091,
all uncommitted per house rules.

## What worked

- **Vet before planning, again.** Cycle 1's triage-before-dispatch lesson repeated its
  payoff: four Cascade recommendations were already implemented (shadow policies, Brier,
  prompt_hash/models, confidence-out-of-gating) and three were already designed and
  owner-gated. Two parallel Explore agents with a claim-by-claim verification brief
  (file:line evidence, verdict enum) settled all 16 spot-checked claims in one pass.
  Without that, cycle 2 would have rebuilt three existing features — the exact failure
  mode the external review itself fell into by reviewing stale code.
- **Serialize the monolith, parallelize the rest.** crypto_trading_bot.py slots ran
  strictly one-at-a-time (WS-2 → WS-6 → WS-4 → WS-5 → WS-9 → WS-9b) with a green suite
  between slots; isolated files (executionledger, tradeanalyzer, marketdata, scripts/)
  ran in parallel. Zero merge conflicts, zero stepped-on edits across 11 agents.
- **Introspection round-trips found real bugs.** Resuming completed agents with a
  four-question introspection prompt (what helped / what hurt / one durable change /
  out-of-scope flags) surfaced two genuine follow-ups that became code: the lock-free
  recovery paths (WS-1b, from WS-1's flag) and the provider-util discovery-prompt
  duplication (WS-9b, from WS-9's flag). The reflection files alone would not have
  triggered these — the direct question "what did you notice out of scope?" did.
- **Fresh-count discipline held.** Every agent reported its delta as "my new test files"
  rather than an absolute count, so the moving baseline (893→929→940→959→978→1005→1026
  →1052→1091) never produced a phantom-regression hunt.
- **REQUIRED vs SUGGESTED briefing (adopted mid-cycle).** WS-2 deviated from a
  mechanism-worded brief ("reuse _FileLock") for good reasons and spent effort justifying
  it. Later briefs (WS-5c, WS-9) were written as REQUIRED properties + SUGGESTED
  mechanisms, and those agents deviated cheaply and correctly (sampling as sibling field;
  call-site phrase substitution).

## What went wrong or nearly wrong

- **A parallel agent used `git stash` on the shared tree** (WS-7, to bisect pre-existing
  failures while WS-3 was mid-flight). No damage — but only because nothing wrote during
  the stashed window. AGENTS.md already bans stashing; the agent knew the rule existed
  but reached for stash anyway under time pressure to verify "not my failure." The
  correct tool (git worktree / `git show <rev>:<file>`) is now written down as the
  positive alternative; bans without alternatives get violated.
- **Cross-agent test flakiness attribution burned a round-trip.** WS-1b observed
  intermittent full-suite failures in WS-6's in-flight test file; WS-6 could not
  reproduce after hardening and suspected WS-1b's own thread-timing tests instead. The
  most likely truth: running the full suite while another agent actively edits shared
  modules is inherently noisy. Lesson: mid-cycle full-suite runs by parallel agents are
  advisory; only phase-boundary runs on a quiescent tree are evidence.
- **The brief's own assumptions leaked.** WS-3's brief implied a band constant existed in
  `grade()` (it doesn't); WS-5's brief implied the product payload carries bid/ask (it
  doesn't — `get_best_bid_ask` is a separate endpoint). Both agents caught the drift by
  reading code before trusting the brief — the verified-vs-inherited discipline working
  as designed — but briefs should mark unverified claims as such.

## Model-tier observations

Opus 4.8 on the monolith slots and analyzer produced the two most intricate diffs
(WS-5's three-subsystem change with a corrected spec assumption; WS-3's three-site
freeze/thaw lockstep) with no rework. Sonnet 5 on isolated, well-specified files was
fast and thorough (WS-8's 39 tests; WS-9b's cross-provider trace). The one place tiering
mattered most: WS-9 (Sonnet) correctly stopped at its ownership boundary and flagged the
provider-util duplication rather than expanding scope — the flag-then-follow-up pattern
beats scope creep even when the extra work is obvious.
