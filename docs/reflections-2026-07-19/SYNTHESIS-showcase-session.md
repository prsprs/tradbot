# Reflection synthesis — showcase & UX-review session, 2026-07-19 (second session this date)

A different session from the IMPROVEMENT_PLAN execution covered by `SYNTHESIS.md`.
Shape: the owner ran a full-functionality showcase sequence (setup checks →
what-if modes → analyzers → supervised live arming) prepared by the
orchestrator, shared the terminal logs, and the log review drove three fixes —
one done by the orchestrator (correlation verbose-report crash), two by
dispatched agents (llm_compare `.env`/fail-fast, Sonnet 5; daily-cap banner,
Opus 4.8). Suite 723 → 739 over the session. Agent first-person reflections:
[reflection-showcase-daily-cap-banner.md](reflection-showcase-daily-cap-banner.md),
[reflection-showcase-llm-compare-env.md](reflection-showcase-llm-compare-env.md).

## Lessons applied to the living docs this session

All of these were written into AGENTS.md / OPERATIONS_MANUAL.md / README.md /
.env.example in the same change set — listed here for provenance:

1. **Feature-extras requirements files are invisible failure modes** (AGENTS.md
   Environment; README setup; OPERATIONS_MANUAL Step 2). `statsmodels` lives
   only in `requirements_correlation_tracker.txt`; without it the Granger test
   degrades gracefully — and the graceful-degradation branch itself carried the
   crash, because skip paths are the least-tested code in a feature.
2. **`load_dotenv()` walks from the calling file's path** (AGENTS.md
   Environment) — `env -i` does not simulate "no keys" for repo-root scripts;
   an agent's first attempt to test the no-key path made two real paid calls.
   Move `.env` aside (verified restore) or monkeypatch.
3. **macOS has no `timeout`** (AGENTS.md Environment) — background + poll +
   kill is the house pattern for bounding CLI runs.
4. **Operator visibility must print before the analysis loop** (AGENTS.md
   process lessons) — a HOLD vote short-circuits every gate, so a supervised
   live run showed zero cap state. The daily-cap banner line is the fix; the
   general rule is that pre-decision state belongs in the banner.
5. **Never `git stash` in this repo** (AGENTS.md test traps) — pending
   tracked+untracked pairs make a stash manufacture fake ImportErrors.
6. **`Test*`-named production classes need import aliases in tests**
   (AGENTS.md test traps).
7. **Grep for duplicated format strings before fixing print bugs** (AGENTS.md
   process lessons) — the tracker had two identical 30-line inline printers.
8. **Doc/code drift: `--coins` max is 5, not 6** (OPERATIONS_MANUAL fixed; the
   6 applies only to internal discovery's 3-LLM + 3-Santiment cap).
9. **Spend-cap env vars added to `.env.example`** — they were documented in
   README but absent from the template users actually copy.

## Process lessons (orchestrator's own reflection)

- **A showcase-and-log-review loop is a cheap, high-yield audit.** One
  operator pass over a prepared command sequence surfaced two real bugs, a
  cascade failure, and a visibility gap that 723 passing tests and a prior
  full audit did not. The terminal log — with its mangled pastes, empty
  sections, and silent no-ops — is evidence the test suite structurally cannot
  produce. Recommend repeating after any UX-facing change batch.
- **Predict what each log line should show before the run.** The pre-stated
  watchlist ("does `[DAILY CAP]` show consumption?", "does `--duration 10m`
  parse?") is what made the review fast; findings fell out by diffing
  prediction against log rather than reading cold.
- **Silent no-op demos are a UX finding in themselves.** Both planned cap
  demos no-opped because the vote was HOLD — correct behavior, invisible to
  the operator. When a safety mechanism can be exercised only on a specific
  vote, the docs must say so (now in the runbook) and the banner must carry
  the state unconditionally.
- **Cascades hide the real bug count.** One crash (verbose printer) read as
  three failures in the log (analyze crash, missing discovery report, tester
  refusing to start). Attribute downstream failures before counting bugs.
- **Model-tiering the dispatch worked.** Pattern-following fix with an
  existing in-repo template (dotenv/TS-3) → Sonnet 5; money-path-adjacent
  change requiring restraint about locks and reuse → Opus 4.8. Both returned
  clean; the Opus brief's "reuse the gate's own function, add no lock" was the
  load-bearing sentence, and the agent confirmed reading `maybe_execute_buy`
  first was the single most useful move.
- **Concurrent agents in one tree need a stated baseline AND per-file
  isolation.** Telling both agents "baseline is 726" let each detect the
  other's landings (726→733→739) without panic; the file-fence lists held.
  This matches the prior session's file-ownership lesson; the addition is
  that a *moving* test count should be expected and stated as such.
- **Agents self-filing reflections works** — both wrote their own
  `reflection-*.md` unprompted when asked for reflection text, and resuming
  completed agents from transcripts for the harvest cost nothing. Keep the
  harvest question specific: "what slowed you down, what did you wish you
  knew, mistakes are the valuable part" got candid material (an unintended
  paid call, a self-inflicted stash incident) that final reports omitted.

## Close-out additions (same session, later phases)

After the first synthesis above, the session continued: live-lock hardening
(.env can no longer arm `LIVE_TRADING_CONFIRMED` — stripped and loudly
ignored), run-summary daily-cap + `Votes:` lines, panel-response logging to
`<HISTORY_DIR>/panel_responses/<run_id>.log`, structured output adopted for
grok+perplexity (all five panelists now vote via json_schema; delimiter tag
is schema-rejection fallback only), a Fable-run main→josh branch analysis
(verdict: main's extra trades were mostly bugs — phantom-BUY parses, quorum
shrink, tiebreaker=primary; josh's HOLD-proneness is safety gates plus
genuine panel caution), the owner's caps rescaled to $25/$50/$100 (mirrored
in .env.example), and a docs-consistency sweep. Suite 739 → **790**.
Additional first-person reflections: reflection-closeout-run-summary.md,
reflection-closeout-panel-log.md, reflection-closeout-structured-votes.md,
reflection-closeout-branch-analysis.md. Commit mapping for everything:
[COMMIT_PROPOSAL_2026-07-19_showcase_addendum.md](../COMMIT_PROPOSAL_2026-07-19_showcase_addendum.md).

Converged lessons from the close-out reflections (candidates already folded
into AGENTS.md where durable):

- **Carry the output path on the response object; never infer it from
  content bytes** — the structured/fallback routing worked only because the
  path was tagged explicitly at request time. Inferring "looks like JSON"
  vs "looks like a tag" from content is the exact bug class (phantom-BUY
  parse) this repo spent real money on.
- **Re-probe a fixture's stated open questions before treating them as
  constraints.** Grok structured output was "unadopted" solely because
  schema+web_search coexistence was unverified in 2026-07-18's probes; one
  cents-scale re-probe flipped it. Trust fixtures for shape, not for
  staleness.
- **Investigate the existing flag before inventing one** — `--log-rounds`
  already gated exactly the four offending dumps; the fix was re-aiming its
  destination, not a new switch. Related trap: TWO `--log-rounds`
  definitions exist (crypto_trading_bot.py default true; config.py default
  false — different entrypoints).
- **Read the nearest gate function's return value before adding tracking
  state** — `gate_and_maybe_buy` already returned the dispatched/blocked
  signal the vote table needed; and don't widen a core execution function's
  contract just to feed a print statement — document the honesty gap
  (`BUY->ordered` = dispatched, not confirmed-filled) instead.
- **Branch archaeology recipe:** read EVALUATION_LESSONS_LEARNED +
  ACCEPTANCE_RESULTS first (they are the design rationale), then verify
  every claim with `git show main:<file>` — diff-grep mechanism keywords,
  never whole-diff-read a 2600-line file. Sorting changes into SAFETY vs
  DECISION-QUALITY made the "is the bot too HOLD-prone?" question
  answerable.
- **Serialize-by-ordering works under concurrency:** the structured-votes
  agent front-loaded util/schema/tests and touched the moving
  crypto_trading_bot.py once, last, after re-grepping (the target block had
  drifted +17 lines). Same pattern as the banner agent's re-grep habit.
- **Tests must never assert on real user-data state.** The panel-log
  import-purity test asserted the repo's real `history/panel_responses`
  didn't exist — it went red the same evening, the moment the owner
  legitimately used the feature, and briefly masqueraded as data pollution
  during close-out. Purity checks run from an empty tmp cwd. (Also folded
  into AGENTS.md test traps; the owner's evening live runs at the new $25
  scale all voted HOLD — ledger unchanged.)

## Recon round (same session, after an external AI review of new live runs)

The owner ran three more live runs (all HOLD; controls behaved) and shared an
external AI's review. Triage verdict: agree on "controls validated, strategy
not"; the filter-precedence finding was real and BIGGER than reported
(`--discovery=santiment` was also silently defeated by env `ANALYZE_COINS`,
with the banner printing the inert filters as active); three of its five
"missing controls" already existed. Suite 790 → **798**. What landed:

- **Filter/discovery precedence fix** (Opus 4.8):
  `resolve_coin_selection_conflict` — env coins + CLI filters → loud override
  into discovery mode; CLI coins + CLI filters → hard error; banner/summary
  filter lines gated on actual applicability. 8 new tests
  (`tests/test_filter_precedence.py`). Residual accepted path: env+env — coins
  win, banner stays honest. Reflection: reflection-recon-filter-precedence.md.
- **Cap-refusal demo + evidence framing** (Sonnet 5): `scripts/demo_cap_refusal.py`
  (whatif-only, live-refusing interlocks, verified output in the runbook),
  "what today's evidence does/does not show" notes, clean-portfolio
  recommendation. Reflection: reflection-recon-cap-demo.md.
- **Edge-vs-fee gating spec** (Opus 4.8, spec-only per money-path convention):
  `docs/design/EDGE_VS_FEE_GATING_FEATURE.md` — structured `expected_move_pct`
  signal, ~2.7% round-trip threshold from measured 1.2%/side fees, fail-closed
  reason codes, sits before caps. Reflection: reflection-recon-edge-spec.md.

New durable lessons folded into AGENTS.md this round: PanelDecision is
action-only (plumbing precedes any per-panelist gate); gate-boundary rationale
(gate_and_maybe_buy vs maybe_execute_buy, live vs whatif cap branches differ);
coin-selection precedence table; banner honesty; test-suite-as-recipe-book
(`buy_calls` fixture); triage external reviews before dispatching; reject
silent-reinterpretation options on money paths; modification-spec vs
greenfield-spec shapes.

## Open items after this session

- The live order path has not re-fired since the acceptance fill (all
  showcase-day votes were HOLD); caps and banner spend display are verified
  by tests + a seeded-ledger demo, not by a second real fill.
- `llm_compare`'s junk empty record `rec_20260719_211510` remains in
  `history/recommendations.json` (append-only; owner's call — it is counted
  as `non_trading` by the analyzer and is harmless).
- `leading_indicator_tester.py` prints an empty "Available pairs:" list when
  the discovery report has no significant pairs — accurate but unhelpful;
  candidate polish item.
- Showcase phases 0–6 logs were never fully reviewed (a later 5-model live
  panel run WAS reviewed — it drove the verbosity and structured-output
  fixes); the integrate/discovery/DEX phases still have had no UX pass.
- The live order path has not fired at the new $25 scale (all panel votes
  to date are HOLD); first $25 fill deserves acceptance-level supervision
  (fees should be ≈ $0.30/side).
- Recommended next feature (from the branch analysis): a majority-vote
  consensus mode (e.g. 4-of-5) — `PanelDecision.majority_action` is already
  computed but unconsumed; and a limit-order-at-support capability, since
  panelists volunteer exact trigger levels the market-order-only bot cannot
  use. Both are money-path design work: spec + review first.
- A prompt-framing experiment ("would a sophisticated bot..." wording) is
  the remaining decision-quality lever — run it what-if-only, A/B via the
  analyzer, now cheap because panelprompts.py is single-source and
  golden-tested.
