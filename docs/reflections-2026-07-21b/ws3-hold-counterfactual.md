# WS-3 reflection — HOLD counterfactual scoring (cycle 2)

First-person notes from the implementing agent. Surprises, briefing gaps, durable
lessons — not a status report (that's in the final summary).

## What I built

A purely-additive `hold_class` field on `ScoredRecord` that grades the "had we
BOUGHT instead?" counterfactual for every matured HOLD, while leaving
`outcome=NEUTRAL` and every existing aggregation universe untouched. Classes:
`GOOD_AVOID` / `MISSED_WIN` / `CORRECT_NEUTRAL` / `HOLD_UNSCORABLE`, cut on the
same fee-adjusted BUY excess (`excess_return_pct('BUY', ...)`) the analyzer
already uses. Plus a report classification section, per-provider HOLD-quality
tallies, a `STATE_VERSION` 3→4 bump, and RECORD_SCHEMA.md update.

## Surprises

- **The old HOLD branch computed no benchmark at all.** It only fetched the coin's
  own price for an "informational move" — there was no relative return to
  classify against. So this wasn't "add a field to existing math"; the whole
  counterfactual had to be *formed* by routing the HOLD through
  `compute_window_returns` (previously BUY/SELL-only). The nice payoff: that
  function already handles the coin==benchmark case, the maturity→run-time
  degradation, and the benchmark-then/benchmark-end pricing, so reusing it kept
  the HOLD path byte-for-byte consistent with directional grading rather than a
  parallel re-implementation.

- **`grade()` has no band — it's a hard zero cut.** The briefing told me to
  "reuse the existing band/threshold constants FIRST; ... do not invent a second
  constant unless none exists." I fully expected to find a band constant. There
  isn't one: `grade()` is `excess > 0 → WIN else LOSS`, a decisive zero
  boundary. A three-way HOLD split genuinely needs a dead-zone that binary
  grading never had, so I added exactly one new constant
  (`HOLD_COUNTERFACTUAL_BAND_PCT = 2.0`) with a comment explaining why no reuse
  was possible. This is the kind of spec assumption AGENTS.md warns about ("the
  spec tells you where to look; the code tells you what's true").

- **The existing `test_hold_is_scored_neutral` fixture had no benchmark price and
  still had to keep passing.** It asserts `coin_return_pct == 5.0` with a provider
  that knows only the coin. If I'd made the HOLD path bail to EXPIRED when the
  benchmark is missing, that regression pin would have flipped. Preserving the
  legacy best-effort coin-move on the `HOLD_UNSCORABLE` path (still NEUTRAL, still
  SCORED, still carrying the move) is what kept it green — and it's the honest
  behavior anyway: missing a benchmark shouldn't erase the coin move we *do* know.

## Briefing gaps (minor)

- The briefing gave an absolute baseline implicitly (I ran a fresh collect first,
  per AGENTS.md). Good call — the suite grew from **893 → 929** during my session,
  and only 17 of that delta is my file. The rest is the concurrent agents editing
  `executionledger.py` / `marketdata.py` adding their own tests. Had I trusted a
  fixed number I'd have burned time hunting a phantom regression. The file-
  ownership framing ("your delta = your new files") is the only stable invariant
  here.

- The briefing said "extend `test_analyzer_ws4.py` only where new columns/sections
  appear." My new sections (HOLD classification, per-provider HOLD quality) are
  brand-new headers the WS4 tests don't assert on, so no extension was needed —
  the WS4 absence-checks (`AGGREGATION-POLICY COUNTERFACTUALS not in out` etc.)
  still hold. Worth stating explicitly so the next reader doesn't look for a WS4
  diff that isn't there.

## Durable lessons

- **Boundary semantics need pinning at the constant, not just the test.** I chose
  edges inclusive to the *outer* decisive classes (`|excess| == band` is a
  good-avoid / missed-win, not neutral), mirroring `grade()` where the `excess==0`
  tie is a LOSS rather than a draw. Documented in the classifier docstring and
  pinned by two tests (pure classifier + end-to-end through `score_record`). A
  future reader changing the band should see the intent, not reverse-engineer it.

- **Additivity is verifiable by grep, and I did it.** Every consumer of the
  scoring universe outside the module is `crypto_trading_bot.run_startup_summary`
  (which reads none of the scored-record fields) and `historyutil` (only a comment
  reference). The other repo `analyze(`/`print_report`/`.outcome` hits belong to
  unrelated analyzers (fibonacci, correlation_tracker, lp_analyzer, marketdata) —
  different objects entirely. So `hold_class` cannot perturb any existing path;
  the only touch to shared state is the freeze dict (guarded by the version bump).

- **A version bump is a two-line change with a one-line test consequence.** The
  3→4 bump broke exactly one pre-existing test that hard-asserted `== 3`. Updating
  that expectation (and generalizing it to discard both v2 and v3) is the correct
  move, not a workaround — the whole point of the discard-on-mismatch contract is
  that stale derived state is cheap to regenerate.
