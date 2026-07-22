# Prompt Contract v2 Feature (WS10)

## Status

Design spec — **not implemented**. Produced per
`docs/IMPROVEMENT_PLAN_2026-07-20.md` WS10 (owner-gated P2). **Design only;
implementation after Josh signs the decision checklist. Whatif-only until WS4
can measure it — no live use of the v2 contract before the validation gate
in (e) is passed.**

Direction call-out (AGENTS.md): a prompt/taxonomy change is the one lever in
this repo that can change trade frequency **in either direction** without
touching a single gate. That is the point of the feature — today's HOLD-heavy
distribution may be an artifact of asking an underspecified question — but it
means v2 must be treated as a money-path change of the first order: its
effect on decision distribution is **measured under whatif, never assumed**,
and the live panel stays on v1 until the owner promotes v2 on evidence.

## Overview

The panel is asked: *"Would a sophisticated trading bot designed for
short-term appreciation recommend buying, selling, or holding the
{coin_type} with symbol {coin_symbol} right now?"*
(`_core_question`, panelprompts.py:94-103), answered in the schema
`action ∈ {BUY, SELL, HOLD}` + `confidence` + `abstain`
(voteschema.py:49-85). Confirmed problems (IMPROVEMENT_PLAN Part 1):

- **HOLD is semantically overloaded.** It conflates at least four states:
  "direction is up but not enough to beat fees", "genuinely no signal",
  "wait — a setup may form", and "I hold a position and keep it" (this last
  is vacuous today: the panel is never told about positions, and there is no
  sell path — WS6/WS7).
- **No horizon.** "Right now" names an entry moment but no holding period.
  The analyzer grades at a **24h maturity window**
  (`DEFAULT_MATURITY_HOURS = 24`, tradeanalyzer.py:53); a panelist reasoning
  over a 7-day thesis is scored against a question it was never asked.
- **No cost floor.** The analyzer scores fee-adjusted, benchmark-relative:
  `excess = (coin − benchmark) − fee_floor` with
  `DEFAULT_FEE_FLOOR_PCT = 2.4` (~1.2%/side round trip, measured;
  tradeanalyzer.py:54, 156-173). The panel is never told that a +1% call is a
  structural loss. Live evidence: confidence 0.60-0.79 HOLDs — models hedging
  an underspecified question.
- **Direction and entry quality are fused.** BUY means both "it will go up"
  and "enter now at market"; there is no way to say "up, but not worth the
  friction."

v2 fixes the *question* and the *answer vocabulary* together, versioned, with
a conservative mapping onto today's actions so history, consensus math, and
the analyzer remain comparable across the boundary.

---

## (a) The v2 action taxonomy

```
ENTER_LONG  — direction up AND entry quality sufficient: expected to beat the
              benchmark by more than the fee floor within the stated horizon.
              The only action that can produce a BUY.
WATCH       — constructive but not actionable now (setup forming, catalyst
              pending, entry quality poor). Direction ≥ neutral, no trade.
NO_EDGE     — analyzed and concluded: no expected move clearing the fee floor
              in either direction within the horizon. The honest default.
EXIT        — direction down / thesis against holding: expected to
              UNDERperform the benchmark beyond the fee floor within the
              horizon. Maps to SELL (executable only once WS6 lands).
ABSTAIN     — unchanged first-class outcome via the existing `abstain: true`
              boolean (voteschema.py:72-75), NOT a new enum member. Declining
              to analyze is orthogonal to the verdict vocabulary, and reusing
              the boolean keeps the entire T8 abstain machinery
              (parse-failure, refusal, symbol-binding) byte-identical.
```

Why five-way (four enum values + the abstain boolean) and not more: each
value is distinguishable by a *scoring consequence* (see (c)); anything finer
(e.g. ENTER_LONG_STRONG) re-encodes confidence, which already exists as its
own axis. Why no SHORT/ENTER_SHORT: the bot cannot short, and asking for
unexecutable actions invites vocabulary drift; EXIT covers the bearish
verdict.

### Conservative backward-compatible mapping (load-bearing)

```
v2 native      -> v1 action   (used for consensus + legacy record field)
ENTER_LONG     -> BUY
WATCH          -> HOLD
NO_EDGE        -> HOLD
EXIT           -> SELL
abstain=true   -> abstain     (unchanged machinery)
```

Properties that make this mapping safe:

- **Total and unambiguous** — every v2 value maps to exactly one v1 action;
  no runtime judgment, no content sniffing (the vote_path lesson).
- **Conservative** — exactly one v2 value can produce a BUY. The split of
  HOLD into WATCH/NO_EDGE can only *reduce or hold constant* the set of
  states that read as BUY; the mapping itself can never add trades. (The
  *taxonomy* may still change model behavior — that is the measured risk,
  see (e) — but the mapping layer is provably non-loosening.)
- **Consensus math untouched.** `PanelDecision`, `decision_allows_trade`,
  tiebreakers, and `tests/test_consensus.py` all keep operating on
  BUY/SELL/HOLD: the mapping is applied at the vote-resolution seam
  (`resolve_structured_vote`, voteschema.py:378, which already returns only
  `vote.action` — AGENTS.md: "PanelDecision is action-only"). Unanimity
  under v2 means "all mapped actions agree" — e.g. three WATCH + two NO_EDGE
  is a unanimous HOLD. This is deliberate: v2 changes what we *ask and
  record*, not (in v2.0) what mix of native values may trade. A stricter
  native-level consensus (all ENTER_LONG, not merely all-mapping-to-BUY —
  vacuously identical for BUY since only ENTER_LONG maps there, but
  meaningful if the taxonomy ever grows) is a *later, separately-reviewed
  tightening*, listed in the checklist as an explicit non-decision.

## (b) Schema and versioning in voteschema.py

- `VOTE_SCHEMA_V2`: same shape as `VOTE_SCHEMA` (voteschema.py:54-85) with
  `action.enum = ['ENTER_LONG','WATCH','NO_EDGE','EXIT']`. Everything else —
  symbol, confidence 0-1, abstain, reasons — unchanged. **No new fields in
  v2.0**: the edge-gate fields (`expected_move_pct`, `horizon_hours`;
  docs/design/EDGE_VS_FEE_GATING_FEATURE.md §b Candidate 1) are the obvious
  passengers for this migration, and if the owner approves both features in
  the same window they SHOULD ride one schema bump (one provider probe, one
  fixture regeneration) — but this doc does not require them. Decide in the
  checklist.
- `ACTIONS_V2` tuple + `map_v2_action(native) -> v1 action` (pure, total,
  raises on unknown input — an unmapped value is a parse failure upstream,
  never a default).
- Contract version selector: `PROMPT_CONTRACT` env / `--prompt-contract`
  flag, values `v1` (default) | `v2`, resolved in `main()` per the
  env-snapshot convention (AGENTS.md — if any module snapshots it at import,
  `_refresh_env_snapshots()` + its test update in the same change).
- Per-provider variants inherit mechanically: `schema_for_gemini` /
  `schema_for_claude` / `openai_response_format` / `grok_text_format` /
  `perplexity_response_format` (voteschema.py:101-154) are parameterized by
  which base schema they copy. Enum-only changes should be low-risk across
  providers, **but probe anyway** (probe-before-migrate, AGENTS.md): five
  cents-scale live calls with the v2 schema, request/response saved under
  `tests/fixtures/structured_output/` as `*_v2.json`. Every provider quirk in
  this repo was found by a probe, not a changelog. Perplexity's
  truncation hazard (unterminated JSON at token cap) is unchanged: fail
  closed to `abstain('parse_failure')`.
- `parse_vote` (voteschema.py:248) becomes contract-aware: validates the
  action against the active contract's enum, applies the same client-side
  confidence bounds, reasons hygiene, and symbol binding, and returns a
  `Vote` carrying **both** `native_action` (v2 string) and `action` (mapped
  v1 string). v1 contract: `native_action == action`. Downstream consensus
  code keeps reading `.action` and does not change.

### Prompt text (panelprompts.py)

The core question is rewritten to state the horizon and the cost floor. v2
draft (final wording is an owner review item — it IS the feature):

> "You are advising a bot that enters long positions at market and is graded
> {MATURITY_HOURS} hours later on the coin's return relative to
> {BENCHMARK} minus round-trip trading costs of about {FEE_FLOOR_PCT}%.
> Recommend ENTER_LONG only if you expect the {coin_type} with symbol
> {coin_symbol} to beat that bar within the horizon. If it will likely move
> up but not enough to clear costs, answer NO_EDGE. If a better entry may
> set up soon, answer WATCH. If you expect it to underperform beyond costs,
> answer EXIT."

- The three numbers are **interpolated from the same constants the analyzer
  uses** (`DEFAULT_MATURITY_HOURS`, `DEFAULT_FEE_FLOOR_PCT`, benchmark
  'BTC'; tradeanalyzer.py:51-58) — one source of truth, so the panel is
  graded on exactly the question it was asked. If the owner runs the
  analyzer at a non-default horizon, the prompt follows automatically.
- `schema_instruction` (voteschema.py:157) gets a v2 twin naming the four
  actions and their meanings; per-provider preamble/spacing drift in
  panelprompts.py is **preserved untouched** (the module docstring's hard
  line: unifying drift is its own reviewed commit — v2 must not smuggle
  whitespace normalization).
- Both v1 and v2 builders coexist; the golden fixture
  (`tests/fixtures/panel_prompts/golden_prompts.json`) is **regenerated to
  cover both contracts** in the same commit, per the AGENTS.md procedure —
  never hand-edited. v1 golden bytes must be byte-identical before/after
  (the characterization guarantee that v1 is untouched).

## (c) History records, prompt_version, and analyzer comparability

- **`prompt_version` stamping**: WS3 (P1, sequenced before this feature)
  adds prompt hash + schema-version fields to every history record. This
  feature **references, not re-implements** that field: v2 records carry
  `prompt_version` (e.g. `v2.0`) + the WS3 prompt hash; v1 records after WS3
  carry `v1`; the 109 pre-WS3 records carry nothing and are treated as v1
  (the only contract that ever existed before the field). **Hard sequencing
  dependency: WS10 does not begin implementation until WS3's fields exist**
  — running v2 whatif without version stamps would poison the corpus for
  exactly the comparison this feature needs.
- **Record shape**: `recommendation` keeps holding the mapped v1 action
  (BUY/SELL/HOLD/NONE) — every consumer (`tradeanalyzer.score_record`,
  vote-outcome tables, per-LLM win/loss) reads on unchanged. New optional
  field `native_votes` ({llm: v2-action}) alongside the existing `votes`
  ({llm: mapped action, abstains as `ABSTAIN(<reason>)` markers —
  historyutil.py:169/219-220}). Optional-when-supplied, exactly the T3
  pattern (historyutil.py:214-224), so legacy records remain loadable
  unchanged.
- **Analyzer comparability**: the analyzer scores mapped actions, so v1 and
  v2 records grade on the same scale; `prompt_version` becomes a partition
  key for WS4's extensions (segment grades, action distribution, calibration
  by contract version). WATCH vs NO_EDGE — both mapped HOLD — become
  *measurable* for the first time via `native_votes`: does WATCH precede
  wins more than NO_EDGE does? That question is the taxonomy's empirical
  test.
- EXIT maps to SELL: today that path records and prints `[NO SELL PATH]`
  (crypto_trading_bot.py:2042-2045) — correct and unchanged; once WS6 lands,
  EXIT votes become executable with zero changes here. (Interaction flagged;
  WS6 is not designed here.)

## (d) Test plan

Failing tests first (xfail), then flip. No network except the five owner-
authorized cents-scale probes (fixtures committed).

1. **Mapping** (`tests/test_voteschema.py`): `map_v2_action` total over
   `ACTIONS_V2`, raises on anything else; property test: only ENTER_LONG
   maps to BUY.
2. **Contract-aware parse_vote**: v2 accepts the four actions, rejects
   BUY/SELL/HOLD strings under v2 (and vice versa) as parse failures →
   abstain; confidence bounds, reasons hygiene, symbol binding, Perplexity
   truncation — all unchanged assertions re-run under v2.
3. **Per-provider schema variants**: gemini strip of `additionalProperties`
   and claude strip of `minimum`/`maximum` hold for `VOTE_SCHEMA_V2`;
   fixtures `*_v2.json` round-trip through the parser.
4. **Prompt goldens** (`tests/test_panel_prompts.py`): v1 goldens
   byte-identical (characterization); v2 goldens added for all four builders
   × five providers; v2 prompt interpolates the analyzer's constants (assert
   the numbers match `tradeanalyzer.DEFAULT_*` so the two can never drift
   apart silently).
5. **Consensus unchanged** (`tests/test_consensus.py`): a panel of mapped v2
   votes produces identical `PanelDecision`s to the equivalent v1 votes
   (unanimity, tiebreaker, blocked, abstain paths); mixed WATCH/NO_EDGE is
   unanimous HOLD; EXIT panel hits the `[NO SELL PATH]` branch.
6. **Record shape**: v2 record carries `native_votes` + `prompt_version`;
   v1 and legacy records load unchanged; analyzer scores a mixed-version
   corpus without error and partitions by `prompt_version`.
7. **Flag plumbing**: default is v1 byte-for-byte (banner line included —
   banner-honesty rule: print the active contract version unconditionally at
   startup); `--prompt-contract=v2` switches schema + prompt + instruction
   together (never mixed — a v2 prompt with a v1 schema is a bug class of
   its own; one selector controls all three).

## (e) Whatif-only validation, measured by WS4 — the promotion gate

The taxonomy is *expected* to change decision distribution; the risk is
promoting it on vibes. Protocol:

1. **Baseline freeze**: before v2 runs, WS4's report over the existing v1
   corpus (action distribution, grade rates, calibration) is stamped as the
   comparison baseline.
2. **v2 whatif cadence**: run v2 in the scheduled whatif cadence
   (scratch/dedicated `HISTORY_DIR`, promoted via WS5's
   `promote_research_run.py` into the research corpus). **Interleave v1 and
   v2 runs across the cadence** (alternating runs over the same coin
   universe) rather than paired same-minute duplicate panels — paired runs
   double API cost for a comparison WS4 can make across interleaved samples;
   accept the noise, state it in the report.
3. **Minimum evidence before any promotion discussion**: every decision at
   the 24h horizon needs 24h+ to mature, and per-provider calibration needs
   volume. Proposed floor (owner may raise): ≥ 200 matured v2 decisions
   spanning ≥ 10 distinct coins and ≥ 14 calendar days, zero v2-attributable
   parse-failure regressions (structured-path abstain rates per provider not
   materially above v1's).
4. **What WS4 must report, v2 vs v1**: action distribution (incl. the
   WATCH/NO_EDGE split inside mapped-HOLD); would-trade frequency
   (mapped-BUY unanimity rate); matured fee-adjusted excess-return grades of
   mapped-BUYs; confidence calibration by contract; per-provider
   native-action tendencies. **Trade frequency moving is success only if
   grades don't degrade** — more trades with worse excess return is the
   failure mode this gate exists to catch.
5. **Promotion** = owner flips the default to v2 for live, as its own
   commit, citing the WS4 report. Until then live runs stay v1. Rollback is
   the same flag; v1 builders/schema are not deleted in any v2.0-adjacent
   commit (they are the rollback path AND the analyzer's baseline
   definition).

## (f) Non-goals (explicit)

- **No consensus-math change** — unanimity over mapped actions; native-level
  consensus is a listed future tightening, not part of v2.0.
- **No new numeric vote fields required** — edge fields
  (`expected_move_pct`/`horizon_hours`) are a coordinated-but-separate
  decision (checklist #4); this doc stands without them.
- **No sell execution** (WS6) and **no position-aware prompting** ("you
  currently hold X at $Y") — the latter needs WS6+WS7 and is v3 territory;
  flagged so the taxonomy leaves room (WATCH/EXIT already read naturally in
  a position-aware world).
- **No multi-horizon voting** (one stated horizon per contract version;
  WS4's multi-horizon *scoring* sweep is analysis, not prompting).
- **No prompt-wording experiments beyond the contract change** — framing
  A/B tests are a separate lever with their own measurement burden.
- **No changes to discovery prompts** (out of panelprompts.py scope by
  design, panelprompts.py:14-16) and **no llm_compare stack changes** (the
  parallel stack keeps v1 until this contract is proven; the registry note
  in AGENTS.md about checking both stacks applies at implementation time).
- **No deletion of v1** anywhere in the v2 rollout.

---

## Decision checklist for owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | Adopt the four-value native taxonomy (ENTER_LONG/WATCH/NO_EDGE/EXIT) with abstain staying the existing boolean? | **Yes** — each value has a distinct scoring consequence; abstain-as-boolean keeps T8 machinery untouched. |
| 2 | Conservative mapping (only ENTER_LONG → BUY; WATCH & NO_EDGE → HOLD; EXIT → SELL), consensus computed over mapped actions? | **Yes** — provably non-loosening at the mapping layer; behavior change is then purely empirical and measurable. |
| 3 | Prompt states the 24h horizon, BTC benchmark, and ~2.4% fee floor, interpolated from `tradeanalyzer` constants (one source of truth)? | **Yes** — grade the panel on the question it was asked; a drift test pins the constants together. |
| 4 | Bundle the edge-gate fields (`expected_move_pct`, `horizon_hours`) into the same v2 schema bump? | **Yes, if** EDGE_VS_FEE is approved in the same window — one probe cycle, one fixture regen, one migration. Otherwise ship v2 enum-only. |
| 5 | Hard-sequence behind WS3 (`prompt_version` + prompt-hash stamping exists before any v2 run)? | **Yes** — unstamped v2 records would poison the exact comparison the validation gate needs. |
| 6 | Whatif-only with the promotion gate in (e): interleaved cadence, ≥200 matured decisions / ≥10 coins / ≥14 days, WS4 report required, promotion as its own commit? | **Yes** — trade-frequency change must be measured against grade quality, never assumed good. |
| 7 | Native-level consensus (stricter than mapped-level) deferred as a future, separately-reviewed tightening? | **Yes** — vacuously identical for BUY in v2.0; deciding it now buys nothing. |
| 8 | Keep v1 fully intact (builders, schema, goldens) as rollback + baseline until v2 is promoted AND a full analyzer cycle has run on v2 live data? | **Yes.** |
| 9 | Final v2 prompt wording review by you before the probe cycle (the draft in (b) is a draft)? | **Yes** — the wording IS the feature; five-provider probes are run once, after wording freeze. |
| 10 | llm_compare stack stays v1 until promotion (drift accepted, documented)? | **Yes** — it is a standalone tool; migrating it rides the promotion commit, not the experiment. |

---

## Addendum (2026-07-21): role-specialized panels (Cascade item K)

Not part of v2.0 scope above; recorded here because it is the same class of
change (a prompt/taxonomy change to the panel) and rides the same gate.

The Cascade review proposed giving each of the five panelists a
role-specialized prompt — technical analyst, risk manager,
catalyst-verifier, skeptic, portfolio-manager — instead of every panelist
receiving an identical core question (`_core_question`,
panelprompts.py:94-103, shared byte-for-byte across all five providers
today). The stated goal: reduce correlated votes, since five models
answering the exact same question tend to reason the same way and move
together.

**The correlated-vote concern is real, not speculative.** Session evidence
observed directly: a 5-model panel's votes clustered rather than spreading
across the action space, and separately, near-simultaneous Gemini vote
flips were observed within the same session — both consistent with
panelists converging on shared framing rather than independent analysis.
This is a legitimate signal, not dismissed by this addendum.

**But prompt changes affect decision quality**, and this repo's standing
rule (AGENTS.md, this doc's own Status section) is that any change to what
the panel is asked is measured under whatif before it touches live,
never assumed good from priors — however plausible. Role-specialization is
no exception, and arguably a larger one than the v2 taxonomy change above:
it changes *five* prompts' framing simultaneously, multiplying the surface
for an untested regression (a role prompt that inadvertently biases one
panelist toward permanent HOLD or permanent BUY would look like "more
diverse votes" while actually being a broken panelist).

**Disposition: rides the same evidence gate as prompt contract v2** —
whatif-only, ≥200 matured v2 decisions (the floor in §(e) above), and
promotion as its own commit, separate from whatever commit lands v2's
taxonomy change. Role-specialization is not bundled into the v2.0 schema
bump in (b); it is a candidate for a later, separately-reviewed prompt
experiment once v2 itself has evidence behind it.

One practical note: this becomes cheaply testable once the cycle-2
experiment runner (`scripts/run_experiment.py`) exists — role-specialized
panels are exactly the kind of A/B (correlated-vote rate, action
distribution spread, per-panelist calibration) that runner is meant to
make routine, rather than a bespoke one-off measurement each time someone
proposes a prompt variant.
