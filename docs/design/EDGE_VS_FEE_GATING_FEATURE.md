# Expected-Edge-vs-Fee Gating Feature

## Status

Design spec — **not implemented**. Money-path work (it changes whether a BUY is
dispatched), so per repo convention this gets spec + review before any code.
This document describes a **tightening** gate: it can only ever *block* a BUY
the panel already approved, never create or loosen one. That direction is
called out explicitly because the fail-open hunt in this repo always starts at
anything touching the buy path (AGENTS.md: "when a money-path change loosens
anything, call that direction out"). This one loosens nothing.

## Overview

Before the bot dispatches a BUY, require that the panel's **expected
short-term edge** (the move it thinks it is buying into) plausibly exceeds the
**round-trip cost** of taking the position — roughly `2 × fee_per_side +
slippage`. At the measured Coinbase small-notional rate (~1.2%/side, ~2.4%
round trip; `executionledger` records fills at exactly this rate), a BUY whose
best-case expected move is a fraction of a percent is a structural loser the
moment it fills, regardless of how confident the panel is. Today nothing in the
gate chain knows what fees cost; a unanimous BUY on a coin the panel expects to
drift +0.3% is dispatched exactly like one expecting +8%.

This is philosophically aligned with the branch-analysis verdict in
`docs/reflections-2026-07-19/SYNTHESIS-showcase-session.md`: main's extra
trades were mostly bugs (phantom-BUY parses, quorum shrink, tiebreaker=primary),
and josh's HOLD-proneness is *safety gates plus genuine caution*. The stated
posture is **never loosen gates**. An edge-vs-fee gate is one more principled
reason to *not* trade, grounded in unit economics rather than model sentiment.

### Non-negotiable framing

The current safety invariant is **fail closed on the money path** (AGENTS.md).
This feature extends it: **missing or unusable edge data blocks the BUY**, it
never waves it through. An abstaining panelist already blocks consensus; an
edge signal the bot cannot read must block the trade the same way, with an
explicit reason code — not default to "probably fine".

---

## (a) Where the gate sits in the existing gate order

Today's chain (verified in `crypto_trading_bot.py`):

```
process_coin_with_comparison  -> PanelDecision (action, consensus_state, votes,
                                  abstains, majority_action, block_reason)
   |
record_recommendation         -> history record (T2/T3 fields)
   |
gate_and_maybe_buy(decision, final_action, coin_symbol)
   |   1. decision_allows_trade(decision, LLM_MODE, REQUIRE_CONSENSUS)   [CONSENSUS]
   |   2. reject SELL (no SELL path); require 'BUY' in final_action
   |   +--> maybe_execute_buy(coin_symbol)
   |          0. exclusion list                                          [both modes]
   |          1. daily LIVE spend cap (ledger-backed, fail-closed)       [CAP]
   |          2. per-run SpendTracker cap                                [CAP]
   |          3. buy_something -> ledger rows (+ live order placement)
```

**Placement: a new check inside `gate_and_maybe_buy`, AFTER
`decision_allows_trade` returns True and the action is confirmed BUY, but
BEFORE the call to `maybe_execute_buy`.**

Rationale:

- **After consensus, before caps.** Consensus is *whether the panel agrees to
  buy*; edge-vs-fee is *whether that agreed BUY is worth the friction*. The
  caps are about *how much* money may move. Edge is logically a decision-quality
  gate that belongs adjacent to consensus, upstream of the spend accounting —
  a BUY that fails the edge gate should never touch cap headroom or the ledger
  lock, exactly as the exclusion-list check was moved ahead of the budget
  commit (MP-6/MP-9).
- **`gate_and_maybe_buy` is the single shared gate→execute wiring** for both
  the coin-choice loop and the discovery loop (TS-2). Placing the check here
  means it cannot silently diverge between the two loops — the same reason that
  function exists.
- **Do not put it inside `maybe_execute_buy`.** That function is specifically
  the *spend-cap* stage and holds the reentrant ledger lock across its whole
  span. The edge check needs no ledger and no lock; nesting it there would only
  widen the lock hold and blur the "caps live here" contract.

The edge gate reads data off the `PanelDecision` (see (b)); `gate_and_maybe_buy`
already receives `decision`, so no new parameter threads through the money path
(AGENTS.md: "inject at seams, not through the money path"). The gate returns
`False` (buy not dispatched) with an `edge_blocked` tally analogous to
`daily_cap_blocked`.

---

## (b) What signal to use for expected edge

Three candidates. This is the load-bearing design decision, so all three are
argued honestly.

### Candidate 1 — a new structured-vote field (RECOMMENDED)

Add two fields to the canonical vote schema in `voteschema.py`:

```
expected_move_pct: number   # signed % price move the panelist expects
horizon_hours:     number    # over what horizon (hours)
```

Panelists already return `confidence` (0–1) and `reasons`; asking for a signed
expected move + horizon is the *direct* measurement the gate needs. The edge is
then a **panel aggregate** of `expected_move_pct` over the non-abstaining
voters (see aggregation below), compared against the round-trip fee threshold.

Why this is the right answer:

- It measures the actual quantity the gate reasons about (a % move vs a % cost).
  Every other candidate is a proxy for this.
- It is schema-enforced and fail-closed by construction on the same machinery
  that already hardened votes: a missing/malformed field → `parse_vote` returns
  `(None, err)` → `abstain('parse_failure')`. No new trust surface.
- The horizon lets the gate reject "yes it'll go up 5%... over 3 months" —
  a 5% move over a quarter does not beat a 2.4% round trip taken *now*.

Costs / risks (stated plainly):

- **Schema change touches all 5 providers.** This is the significant cost.
  Per the provider quirks already cataloged in `voteschema.py`: Gemini rejects
  `additionalProperties` (stripped by `schema_for_gemini`), Claude rejects
  `minimum`/`maximum` on numbers (stripped by `schema_for_claude`, bounds
  enforced client-side in `parse_vote`). New numeric fields inherit exactly
  these constraints — `expected_move_pct` and `horizon_hours` must **not** rely
  on schema-level bounds for Claude; range-sanity (e.g. clamp/`abstain` on an
  absurd ±900% or negative horizon) is enforced client-side in `parse_vote`
  like `confidence` already is.
- Requires regenerating the golden fixtures. The vote schema is exercised by
  `tests/test_voteschema.py` and `tests/fixtures/structured_output/`; the
  analysis prompt tail is `schema_instruction()` (and prompt text lives in
  `panelprompts.py`, pinned byte-for-byte by `tests/test_panel_prompts.py` with
  a golden fixture). Adding a field is a **prompt change** and a **schema
  change** in one reviewed commit, golden fixtures regenerated per the AGENTS.md
  procedure — never hand-edited.
- **Adoption is gradual-safe.** Make the fields **required** in the schema
  (fail-closed: a panelist that omits them abstains). A softer alternative —
  optional fields, treat "absent" as "no edge claim → block" — is also
  fail-closed and lowers provider-rejection risk; see Open Questions.

`resolve_structured_vote` today returns only `vote.action` (a bare string), so
`PanelDecision.votes` is `{llm: action}` and confidence/edge are **discarded
before they reach the decision**. Consuming edge therefore requires plumbing
the `Vote` object's `expected_move_pct`/`horizon_hours` (and, if pursued,
`confidence`) through to `PanelDecision` — a new field such as
`edge_estimates: Dict[str, tuple[float, float]]` (llm → (move_pct, horizon_hrs)).
This is a real but contained change at the `resolve_structured_vote` /
`process_coin_with_comparison` seam; it does **not** alter the consensus math.

### Candidate 2 — derive edge from `confidence` (REJECTED as primary; weak proxy)

`confidence` is already present, so it is tempting to map, say, `confidence >
0.8 ⇒ enough edge`. Argued honestly: **this is a bad proxy and should not be
the edge signal.**

- Confidence answers "how sure am I of my call?", not "how big is the move?".
  A panelist can be 0.95-confident that a coin will drift +0.2% (high certainty,
  no edge) or 0.55-confident of a +30% move (low certainty, huge edge). The two
  axes are independent; collapsing them discards exactly the information the fee
  gate needs.
- The live evidence undercuts it directly: today's live runs showed
  confidence **0.60–0.79 on HOLDs**. Confidence simply does not live on a scale
  that maps cleanly to "beats a 2.4% round trip", and any threshold picked over
  it would be a guess dressed as economics.

Confidence *may* still serve as a **secondary weight** in the aggregation (e.g.
confidence-weighting the mean expected move), and as a **degraded fallback only
if** the schema-field rollout is staged provider-by-provider — but never as the
primary edge measurement. If used at all, the mapping must be documented as the
judgment call it is (AGENTS.md: "report judgment calls explicitly").

### Candidate 3 — parse volunteered support/resistance levels (REJECTED as primary; useful later)

Panelists already volunteer exact price levels in free-text `reasons` ("support
at $X, resistance at $Y") — the same observation motivating the planned
limit-order-at-support feature. In principle `(resistance − price) / price`
gives an expected upside the gate could use.

Rejected as the primary signal because:

- `reasons` is **display-only text, never traded on** (AGENTS.md, hard-won:
  reasons carry self-correction debris; `parse_vote` content-filters them and
  they never reach history). Building a money gate on regex-scraping free text
  is precisely the *phantom-BUY parse* bug class this repo spent real money on
  ("a refusal regex-scraped into a real BUY"). Structured fields exist to avoid
  exactly this.
- Levels are volunteered inconsistently (not every panelist, not every coin),
  so a gate depending on them would abstain constantly or, worse, fall open.

These levels are genuinely valuable — but their home is the **structured**
route (Candidate 1's fields, and the separate limit-order-at-support feature),
not a text scrape feeding the trade gate.

**Decision: Candidate 1 (structured `expected_move_pct` + `horizon_hours`),
with confidence available only as an optional secondary weight, and
support/resistance explicitly out of scope for this gate.**

### Panel aggregation of expected edge

The gate needs one number per coin from N non-abstaining voters. Proposed
default (a judgment call, flagged for review):

- Use the **minimum** `expected_move_pct` among the deciding voters (the same
  voters whose votes produced the BUY), normalized to a common horizon — i.e.
  the gate passes only if *even the least optimistic* deciding panelist expects
  a move beating the round-trip threshold. This is the most conservative choice
  and matches the fail-closed / never-loosen posture.
- Alternatives (mean, confidence-weighted mean, median) are less strict; see
  Open Questions. Horizon normalization: compare `expected_move_pct` scaled to,
  or capped at, a configurable `EDGE_MAX_HORIZON_HOURS` so a large move over an
  implausibly long horizon does not pass.

---

## (c) Fee model

```
FEE_RATE_PER_SIDE      env / flag, default 0.012   # measured Coinbase small-notional rate
EDGE_SLIPPAGE_MARGIN   env / flag, default 0.003   # slippage + safety buffer (judgment call)
```

Round-trip threshold:

```
round_trip_cost = 2 * FEE_RATE_PER_SIDE            # entry + eventual exit
edge_threshold  = round_trip_cost + EDGE_SLIPPAGE_MARGIN
                = 2*0.012 + 0.003 = 0.027  (2.7%) with defaults
```

A BUY passes the edge gate iff:

```
aggregate_expected_move_pct / 100  >=  edge_threshold      # (both as fractions)
```

Notes:

- `FEE_RATE_PER_SIDE` mirrors the rate `executionledger` already uses for
  simulated-fill fee estimates (1.2%/side, `fees_estimated=True`). Keeping a
  single documented default in sync avoids two truths; the constant should be
  referenced/justified from the same measured figure, and the round-trip
  estimate stays "2× the entry side" consistent with the ledger's stated model
  ("round-trip fee estimates are 2× the entry fill's fee").
- These are `main()`-time config values. Per the env-snapshot convention, if a
  module in the bot's import graph snapshots them at import, it must be added to
  `_refresh_env_snapshots()` with the refresh test updated in the same change;
  the simpler path is to read them inside `main()` and pass them to the gate, or
  read via `globals().get(...)` (they are assigned in `main()` like `RUN_ID`).
- Config source resolution should reuse `get_config_source(...)` so the
  startup banner can show the active fee rate (see (d) / operator visibility).

---

## (d) Fail-closed semantics and reason codes

The gate blocks the BUY (returns not-dispatched) in **all** of these cases, each
with a distinct reason code surfaced in the run summary and the history record:

| Reason code            | Condition                                                        |
|------------------------|------------------------------------------------------------------|
| `edge_below_fee`       | aggregate expected move < `edge_threshold` (the normal block)    |
| `edge_missing`         | a deciding voter produced no edge field (should already be an abstain upstream if fields are required; belt-and-suspenders) |
| `edge_abstain`         | edge data present but unusable (NaN, out-of-range after client clamp, no deciding voters after edge parsing) |
| `edge_horizon_too_long`| best move only clears the bar over a horizon beyond `EDGE_MAX_HORIZON_HOURS` |

Semantics:

- **Missing/abstain edge data blocks the BUY** — never a default-pass. This is
  the core requirement and the whole point of the feature.
- The block is **loud**: a `[EDGE GATE]` console line naming the coin, the
  aggregate expected move, the threshold, and the reason code — analogous to the
  `[DAILY CAP]` / `[SPEND CAP]` refusal lines.
- The block is **counted**: an `edge_blocked` run tally, printed in the run
  summary next to `Blocked by spend cap` / `Blocked by daily cap`, and reflected
  in the per-coin vote-outcome table (`vote_outcome_label` gains an
  edge-blocked outcome).
- The block is **recorded**: `record_recommendation` already carries
  `block_reason`; an edge block sets `block_reason='edge_below_fee: ...'` (etc.)
  on the recorded rec so the analyzer can separate edge-blocked BUYs from cap
  refusals and from HOLDs. Because a rec is recorded whenever `final_action` is
  truthy, an edge-blocked BUY is a **recorded, attributable** non-trade, never a
  silent no-op. (Confirm the exact `block_reason` string vocabulary against
  `tests/test_consensus.py` — that test file is the sole spec for block-reason
  strings; add the new codes there.)
- **Operator visibility before the loop.** A HOLD/SELL vote short-circuits every
  downstream gate, so — per the daily-cap-banner lesson — the active fee rate
  and edge threshold belong in the **startup banner** (printed unconditionally),
  not only in the buy path an all-HOLD run never reaches.

Fail-closed also against the *type domain*, not just exceptions: a present-but-
`null` edge field, an `expected_move_pct` of the wrong type, or a `[]` deciding-
voter set after edge filtering are all corruption → block, mirroring the ledger
shape-validation discipline (MP-2 / review MAJOR 1).

---

## (e) Interaction with other planned features (flag overlaps; do NOT design them here)

From the SYNTHESIS open items, two adjacent money-path features are planned.
This spec only **flags** the overlaps.

- **Majority-vote consensus mode (e.g. 4-of-5).** `PanelDecision.majority_action`
  is already computed but unconsumed; a majority mode would change *which*
  BUYs reach `gate_and_maybe_buy`. The edge gate sits **downstream** of the
  consensus gate regardless of whether consensus is unanimity- or majority-based,
  so the two compose cleanly — BUT: the edge aggregation's "deciding voters" set
  must be defined against whatever `decision.deciding_llms` ends up meaning under
  majority mode (the minimum-over-deciding-voters rule must not silently include
  a dissenting HOLD voter's edge, or exclude a majority voter's). Coordinate the
  "deciding voters" definition when majority mode lands; do not pre-build it here.
- **Limit-order-at-support.** Panelists volunteer exact trigger levels the
  market-order-only bot cannot use today. That feature will likely want the
  **same** structured levels this spec deliberately left to it (Candidate 3).
  Overlap: if the limit-order feature adds structured `support`/`resistance`
  fields to the vote schema, the edge gate could *optionally* cross-check its
  `expected_move_pct` against `(resistance − price)/price` for sanity — but that
  is a future enhancement, not part of this gate. Keep the schema changes
  coordinated so the two features don't add conflicting fields in separate
  commits.

---

## (f) Test plan

Write the spec as failing tests first (xfail), then implement until they flip
(the house method). All new tests live under `tests/`.

Pure / unit (no network, no files):

1. **Threshold arithmetic** — `edge_threshold = 2*fee + slippage`; boundary
   behavior (exact-equal passes, matching the caps' "exact boundary allowed"
   convention). Parametrized over fee/slippage config values.
2. **Aggregation** — minimum-over-deciding-voters with horizon normalization;
   ties, single voter, differing horizons.
3. **Schema round-trip** (`tests/test_voteschema.py`) — `parse_vote` accepts
   valid `expected_move_pct`/`horizon_hours`; **fails closed** on missing,
   wrong-type, `null`, NaN, and out-of-client-range values → the right reason.
4. **Per-provider schema variants** — `schema_for_gemini` still strips
   `additionalProperties`; `schema_for_claude` still strips `minimum`/`maximum`
   and the new numeric bounds are enforced client-side (add fixtures under
   `tests/fixtures/structured_output/` if a live re-probe is done — probe before
   migrate; keep it to cents).
5. **Gate decision** — given a `PanelDecision` carrying edge estimates,
   `gate_and_maybe_buy` dispatches when edge ≥ threshold and blocks (with each
   reason code) otherwise; asserts `maybe_execute_buy` is **not** called on a
   block (the cap/ledger stage is never reached).
6. **Reason-code vocabulary** — assert the new `block_reason` strings in
   `tests/test_consensus.py` (its assertions are the only spec for these).
7. **Run-summary / history** — an edge-blocked BUY records a rec with the edge
   `block_reason`, increments `edge_blocked`, and shows in the vote-outcome
   table; assert against a redirected `HISTORY_DIR` (never the real `history/`).
8. **Prompt golden** (`tests/test_panel_prompts.py`) — regenerate and pin the
   golden prompt with the new schema-instruction tail; assert byte-for-byte.

Integration-ish (guarded by the conftest network block; stub
`marketdata.build_market_block` per the file-local autouse fixture):

9. A whatif end-to-end coin pass where the panel votes BUY with sub-threshold
   edge → no buy, `[EDGE GATE]` line printed, rec recorded with reason code.

---

## (g) Non-goals (explicit)

- **No SELL / exit-side edge logic.** There is no SELL path today; the gate
  guards BUY dispatch only. (The round-trip cost still *assumes* an eventual
  exit fee — that is the fee model, not an exit implementation.)
- **No dynamic/volume-tiered fee discovery.** `FEE_RATE_PER_SIDE` is a config
  constant seeded from the measured rate; querying Coinbase's live fee tier is
  out of scope.
- **No realized-P&L or backtest engine.** The gate uses the panel's *expected*
  move, not historical outcome data; scoring whether the edge estimates were
  accurate is the analyzer's job, later.
- **No support/resistance parsing** for this gate (Candidate 3 belongs to the
  limit-order feature).
- **No majority-vote mode** and **no limit-order-at-support** design — only the
  interaction flags in (e).
- **No change to consensus math**, tiebreaker logic, or the spend caps. The
  edge gate is strictly additive and strictly tightening.
- **No prompt-framing / decision-quality experiments** — separate lever.

---

## Open questions for Josh

1. **Schema fields required or optional?** Required = strictest fail-closed (a
   panelist that omits edge abstains, shrinking quorum → likely blocks) but
   raises provider-rejection risk across all 5. Optional + "absent ⇒ block" is
   also fail-closed and lower-risk. Which?
2. **Default `edge_threshold` components** — `FEE_RATE_PER_SIDE=0.012` is
   measured, but `EDGE_SLIPPAGE_MARGIN=0.003` is a guess. Comfortable with a
   ~2.7% effective bar, or want it tighter/looser? (A higher bar = fewer, better
   trades — consistent with the never-loosen posture, but fewer live fills to
   learn from.)
3. **Aggregation rule** — minimum-over-deciding-voters (most conservative) vs
   mean vs confidence-weighted mean vs median? Minimum is my default.
4. **Horizon handling** — hard `EDGE_MAX_HORIZON_HOURS` cutoff, or normalize the
   move to a per-hour rate and compare? And what default horizon cap fits your
   intended holding period?
5. **Confidence as secondary weight** — use it to weight the edge aggregate at
   all, or keep the two axes fully separate (my lean: keep separate for v1)?
6. **Whatif enforcement** — enforce the edge gate in whatif too (so the learning
   stream mirrors what live would refuse, like the daily cap does), or let
   whatif record the would-block and continue for measurement? I lean "enforce,
   record the reason" for stream fidelity.
7. **Rollout ordering vs majority-vote mode** — land this before or after the
   4-of-5 majority mode, given both touch `deciding_llms` semantics?
