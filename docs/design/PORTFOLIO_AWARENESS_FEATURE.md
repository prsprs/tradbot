# Portfolio Awareness Feature (WS7)

## Status

Design spec — **not implemented**. Produced per
`docs/IMPROVEMENT_PLAN_2026-07-20.md` WS7 (owner-gated P2: design before
code). **Design only; implementation starts only after Josh signs the
decision checklist at the end.**

Direction call-out (AGENTS.md fail-open hunt): this feature is **strictly
tightening** — it adds new reasons to refuse a BUY the panel already approved
and can never create, enlarge, or unblock one. Missing or contradictory
portfolio data blocks the live buy; it never waves it through.

## Overview

The buy path today checks exclusion + caps and nothing else
(`maybe_execute_buy`, crypto_trading_bot.py:1878-1986). Confirmed in the
2026-07-20 audit: `executionledger.positions()` (executionledger.py:607) and
`trader.list_account_balances()` (coinbaseutil2.py:167) are **never consulted
by the bot** — only by `scripts/reconcile_positions.py`. Consequences:

- The same coin can be re-bought every run while a position is open
  (duplicate exposure): at the current $25 notional, five runs of unanimous
  DOGE-BUY = $125 of DOGE with no gate ever noticing it is the *same bet*.
- The spend caps limit **flow** (dollars committed per run / per UTC day) but
  nothing limits **stock** (dollars concentrated in one coin, or in one
  correlated cluster). With no sell path yet (WS6), stock only grows.

This spec adds portfolio-state gates in front of the buy: a per-coin exposure
cap and a duplicate-exposure guard, behind a feature flag, whatif-validated
first. **Caps and exposure limits are complementary and both stay**: caps
bound how fast money moves; exposure bounds where it accumulates. Neither is
redundant with the other and neither replaces the other.

---

## (a) Which data source is authoritative

Two candidate sources, with different truths:

| Source | What it knows | What it cannot know |
|---|---|---|
| `executionledger.positions()` (executionledger.py:468-514, mode-filtered, duplicate-order_id-deduped) | The bot's own attributed book: what THIS bot bought, netted, per mode — deterministic, offline, lock-protected, whatif-capable | Manual buys/sells, deposits, other tools, other users' activity on the same account |
| `trader.list_account_balances()` (coinbaseutil2.py:167-193) | Account truth right now | *Whose* holdings they are — the multi-user norm means accounts legitimately hold assets the bot must not reason about; returns `{}` on any error (:176-179), indistinguishable from an empty account |

**Decision: the ledger's attributed positions are authoritative for every
exposure decision.** Rationale:

- The feature's question is "how much has *the bot* already bet on X" — an
  attributed-book question by definition. Counting a user's long-held
  personal ETH against the bot's ETH exposure cap would block trades on
  holdings the bot doesn't manage (and, per the multi-user norm, must not
  manage).
- The ledger works identically in whatif (mode filter, executionledger.py:502)
  — which is what makes the whatif-first validation meaningful. Balances
  cannot simulate.
- Deterministic and testable with zero network; the balances call degrades to
  `{}` on error, which as an *authority* would read "no exposure anywhere" —
  a fail-open by construction.

**Balances are the cross-check, not the authority.** Their one legitimate
role: detecting that the attributed book has *desynced from reality* (someone
manually sold what the bot bought). Rule, per coin being bought live:

```
attributed = positions(trading_mode)[coin]     # 0.0 if absent
balance    = list_account_balances().get(coin) # live mode only
if attributed > 0 and balance < attributed * 0.98:
    -> [PORTFOLIO: LEDGER/BALANCE MISMATCH] refuse this coin's LIVE buy (fail closed)
```

The 2% tolerance absorbs exchange rounding and fee-in-kind dust; the exact
threshold is a judgment call flagged for review, shared with WS6's identical
sell-side check (one constant, one definition — coordinate the commits). The
refusal names both numbers and points at `scripts/reconcile_positions.py`;
after the owner reconciles (manual-sale adjustment rows are that script's
concern, not this feature's), the buy path unblocks naturally.

Failure semantics of the cross-check:

- **Live buy + balance fetch fails (`{}` or exception): fail closed** for
  coins with an attributed open position — "could not verify" is not "fine"
  (same doctrine as the MP-2 corrupt-ledger refusal,
  crypto_trading_bot.py:1922-1947). Coins with **zero** attributed position
  skip the cross-check entirely (there is nothing to desync), so a Coinbase
  accounts outage does not brick fresh buys — it only pauses *adding to
  existing positions*, which is exactly the conservative direction.
- **Whatif: no balances call at all.** There is no real account state behind
  a whatif book; the cross-check would be noise. The whatif stream exercises
  the exposure math (the part that matters for validation), mirroring how the
  whatif daily-cap branch mirrors live shape without live consequences
  (:1948-1973).
- **One `get_accounts` call per run**, fetched lazily on the first live buy
  attempt and cached for the run (module-global reset per run like other
  run-scoped state) — not per coin (50-coin discovery runs must not make 50
  accounts calls), and not at startup (an all-HOLD run pays nothing).
  Staleness within a run is acceptable: the ledger lock already serializes
  the bot's own writes, and a *manual* sale mid-run landing after the cached
  fetch is the same race that exists between any check and any fill.

### Ledger corruption

`positions()` reads via `load_executions()`, which raises `LedgerError` on
corruption. Follow the established MP-2 split (crypto_trading_bot.py:
1925-1973): **live → fail closed** (refuse the buy; the existing
quarantine/restore machinery at :1988-2021 already runs for the daily-cap
read, which happens under the same lock hold — the exposure check simply
inherits whatever ledger state that recovery produced); **whatif →
soft-fail** (log, skip the exposure check, continue — the learning loop never
crashes on its own bookkeeping).

---

## (b) The two guards

### Guard 1 — duplicate-exposure guard (across runs)

> A BUY for coin X is refused when the bot already holds an attributed open
> position in X (in the current trading mode), unless adding the new notional
> keeps X within the per-coin exposure cap (Guard 2).

With the recommended default below (cap = 1 × notional), Guard 1 is simply
Guard 2's special case: any open position ⇒ refuse re-buy. They are stated
separately because the owner may later set the cap to N× notional, at which
point Guard 1 dissolves into Guard 2's arithmetic ("scaling in" up to the
cap) rather than needing its own flag. **One mechanism, one reason code.**

### Guard 2 — per-coin exposure cap

```
MAX_COIN_EXPOSURE_USD   env / --max-coin-exposure-usd, default = NOTIONAL_USD
```

A BUY passes iff `current_exposure_usd(X) + NOTIONAL_USD <=
MAX_COIN_EXPOSURE_USD` (exact boundary ALLOWED, matching the caps'
convention, executionledger.py:633-639).

**Exposure is measured at cost basis, not mark-to-market.** RECOMMENDED and
load-bearing:

- Cost basis = for each open attributed entry of X, the fill's
  `avg_fill_price × filled_size` (fallback: the intent's
  `intended_notional_usd` when fill price is missing — an *over*statement,
  which errs toward blocking: fail-closed direction).
- Mark-to-market would need a price fetch inside the gate, would make the
  same portfolio pass or block depending on the minute, and — the killer —
  would *unblock re-buys of a falling coin* as its value drops (a
  drawdown-averaging behavior nobody chose). Cost basis is deterministic,
  offline, and stable across a run.
- Consequence to state honestly: a coin that has *appreciated* past the cap
  still shows its (lower) cost basis — the cap bounds what the bot *put in*,
  not what the position is *worth*. That is the intended semantics: this is
  a bet-sizing limit, not a portfolio-valuation limit.

Default `= NOTIONAL_USD` ($25 at Josh's current setting) means: **one open
position per coin, no scaling in** — the most conservative useful value, and
the correct default while no sell path exists to ever reduce exposure. Raising
it is a one-env-var owner decision later.

Requires a small pure extension: `exposure_from_rows(rows, trading_mode)`
returning coin → open cost basis USD (sibling of `positions_from_rows`,
reusing its intent-join / mode-filter / duplicate_of / seen-order_id
discipline, executionledger.py:490-514, so the two derivations cannot
disagree about *which rows count*). Once WS6 lands, entries closed by a SELL's
`closes` list drop out of open cost basis — the seam is designed now so WS6
plugs in without rework.

### Correlated-exposure note (NOT implemented — recorded so it isn't forgotten)

Ten different $25 meme-coin positions are approximately one $250 bet on
"meme-coin beta". The per-coin cap cannot see this. A category-level cap
(e.g. `MAX_CATEGORY_EXPOSURE_USD` keyed on the LunarCrush category data
already cached in `coin_cache.json` for `--categories` filtering) is the
natural future shape — but category data is a third-party label with partial
coverage, and a cap keyed on missing labels either fails open (uncapped
unlabeled coins) or blocks everything unlabeled. That design tension is real
and unresolved; **out of scope for v1**. Until then the real correlated-
exposure bounds remain the run/daily caps and the unanimity gate. The run
summary SHOULD print the open-exposure table per coin (from
`exposure_from_rows`) so the owner can *see* concentration even before any
category math exists — visibility first, policy later.

---

## (c) Where the guards sit

```
gate_and_maybe_buy                      (unchanged)
   +--> maybe_execute_buy(coin_symbol)  (crypto_trading_bot.py:1878)
          0. exclusion list                                  [unchanged, :1914]
          with executionledger.ledger_lock():                [unchanged, :1920]
              0.5  PORTFOLIO GUARDS  (NEW: mismatch cross-check -> exposure cap)
              1.   daily cap                                 [unchanged, :1925]
              2.   per-run SpendTracker cap                  [unchanged, :1976]
              3.   buy_something                             [unchanged, :1983]
```

Why **inside `maybe_execute_buy`, under the ledger lock** — deliberately
*different* from the edge gate's placement in `gate_and_maybe_buy`
(docs/design/EDGE_VS_FEE_GATING_FEATURE.md §a), and for the same reason that
doc gave: the edge check "needs no ledger and no lock". The exposure check is
the opposite — it is a **ledger read followed by a ledger write** (the intent
row), i.e. exactly the check-then-write TOCTOU shape MP-3 closed for the
daily cap (:1901-1908). Two overlapping runs must not both read "no DOGE
position" and both buy DOGE. `maybe_execute_buy`'s docstring says "spend caps
live here"; the honest generalization after this feature is "*ledger-backed
refusals* live here", and the docstring is updated to say so in the same
commit. Ordering within the lock: portfolio guards **before** the daily cap,
so a refused re-buy never consumes cap headroom or triggers the cap's
recovery machinery — mirroring why the exclusion check runs first (MP-6/MP-9
rationale, :1895-1899). The lock hold gains one cached balances call on the
first live buy of a run (network inside the lock span already happens for
live order placement itself, :1907 — accepted for the same serialize-buys
reason).

Reason codes (added to `tests/test_consensus.py`, the sole vocabulary spec):

| Console line | Condition | Tally |
|---|---|---|
| `[PORTFOLIO: EXPOSURE CAP]` | cost basis + notional > MAX_COIN_EXPOSURE_USD (covers the duplicate-exposure case at the default cap) | `exposure_blocked` |
| `[PORTFOLIO: LEDGER/BALANCE MISMATCH]` | live; balance < 0.98 × attributed | `exposure_blocked` |
| `[PORTFOLIO: BALANCE UNVERIFIABLE]` | live; attributed > 0 and balances fetch failed | `exposure_blocked` |

All three refuse the buy, print loudly (coin, attributed cost basis, cap,
balance where relevant), count in a run-summary line next to
`Blocked by daily cap`, and are recorded: the recommendation record's
`block_reason` (historyutil.py:221-222) carries the code so the analyzer can
separate "panel said BUY, portfolio said no" from cap blocks and HOLDs —
these refusals are exactly the counterfactual rows WS4's analyzer extensions
want.

Startup banner (operator-visibility rule, AGENTS.md): print the feature
state, the cap value + config source (`get_config_source`), and the current
open-exposure table unconditionally — an all-HOLD run must still show the
book. Banner honesty rule: the line prints "enabled" only when the flag
actually gates buys this run.

---

## (d) Feature flag and rollout

```
PORTFOLIO_GUARD   env / --portfolio-guard, default OFF for v1
```

- **Off** = today's behavior byte-for-byte (guards not evaluated, no
  balances call, banner says disabled).
- **Whatif-first validation**: enable in the scheduled whatif cadence
  (docs/RUNBOOK_whatif_cadence.md) against scratch `HISTORY_DIR`. Because
  whatif enforces its own daily cap from whatif intent rows already (MP-6b),
  the whatif book accumulates realistically and will exercise real
  `[PORTFOLIO: EXPOSURE CAP]` refusals within a few cadence days at default
  settings. Validation questions WS4 measures: how many buys would the guard
  have refused, on which coins, and were the refused re-buys better or worse
  than the originals (the counterfactual the block_reason rows enable)?
- **Live enablement is an owner decision** after reviewing the whatif
  refusals; flag default flips (if ever) as its own commit.
- Interaction with WS6: independent — this feature only ever *refuses* buys,
  so it is safe to enable before any sell path exists (indeed most valuable
  then, since without sells exposure is monotone). When WS6 lands, sells
  reduce open cost basis through the `closes` linkage and re-buys become
  possible again after an exit — no code change here.
- Interaction with the edge gate (if built): edge gate runs in
  `gate_and_maybe_buy` (decision quality), portfolio guards in
  `maybe_execute_buy` (ledger state). No shared state, no ordering coupling
  beyond "edge first by virtue of call order", which is correct: a
  no-edge BUY should not consume a balances fetch.

## (e) Test plan

Failing tests first (xfail), then implement. No network (conftest guard); the
balances boundary is stubbed; ledger paths redirected, never real `history/`.

1. **Pure exposure math** (`tests/test_execution_ledger.py`):
   `exposure_from_rows` over synthetic rows — open cost basis per coin;
   intent-notional fallback when fill price missing; duplicate_of and
   repeated-order_id rows excluded exactly as `positions_from_rows` excludes
   them (shared-discipline test comparing the two derivations on the same
   rows); mode isolation; (xfail until WS6) entries closed by a SELL drop out.
2. **Guard decisions** (new `tests/test_portfolio_guard.py`): boundary
   arithmetic (exact cap ALLOWED); refusal when position open at default cap;
   pass when no position; mismatch refusal at the 0.98 boundary; unverifiable
   refusal on `{}` balances (live) vs no balances call at all (whatif —
   assert the stub was never invoked); zero-attributed coins skip the
   cross-check even when balances are down.
3. **Placement / ordering** (extend `tests/test_run_summary.py`, reusing its
   `buy_calls` fixture — the canonical no-LLM way to force a BUY through
   `maybe_execute_buy`, per AGENTS.md): a portfolio-refused buy consumes no
   SpendTracker headroom, no daily-cap sum, writes no intent row; flag off →
   guards never evaluated; one balances call per run across multiple live
   buy attempts.
4. **Reason codes** (`tests/test_consensus.py`): the three strings, spec'd
   where all block reasons are spec'd.
5. **Records + summary**: refusal writes a rec with the right `block_reason`;
   `exposure_blocked` tally and banner/summary lines appear only when the
   flag is on (banner-honesty test, same pattern as the filter-precedence
   tests).
6. **Ledger corruption**: live → refuse (after the existing recovery
   machinery), whatif → soft-skip and continue.

## (f) Non-goals (explicit)

- **No sell/rebalance actions.** This feature only refuses buys; reducing
  exposure is WS6's job.
- **No category/correlation cap** (design tension recorded in (b); revisit
  after category-coverage data exists). No portfolio-total exposure cap
  either — the daily cap × days is that bound for now.
- **No mark-to-market valuation, no P&L, no price fetches in the gate.**
- **No changes to consensus math, spend caps, exclusion list, or prompts.**
  (Telling the *panel* about held positions is WS10/prompt territory.)
- **No multi-account or cross-user awareness** — the mode-filtered attributed
  book of this `HISTORY_DIR` only, consistent with the multi-user norm.
- **No automatic reconciliation.** Mismatch = refuse + point at
  `scripts/reconcile_positions.py`; writing adjustment rows stays a
  deliberate owner action.

---

## Decision checklist for owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | Ledger attributed positions **authoritative**; live balances only a desync cross-check? | **Yes** — attributed-book question; balances-as-authority fails open on `{}` and drags non-bot holdings into scope. |
| 2 | On ledger/balance mismatch (>2% short) or unverifiable balances: **fail closed** for that coin's live buys? | **Yes** — could-not-verify ≠ fine; fresh coins (zero attributed) stay buyable so an accounts outage never bricks the bot. |
| 3 | Exposure measured at **cost basis** (not mark-to-market)? | **Yes** — deterministic, offline, and never unblocks averaging-down on a falling coin. |
| 4 | `MAX_COIN_EXPOSURE_USD` default **= NOTIONAL_USD** (one position per coin, no scaling in)? | **Yes** while WS6 is unbuilt — exposure is monotone until sells exist. Revisit after WS6. |
| 5 | Duplicate-exposure guard expressed as the cap's special case (one mechanism, one reason code)? | **Yes** — no second flag to drift. |
| 6 | Guards placed **inside `maybe_execute_buy` under the ledger lock**, before the daily cap? | **Yes** — TOCTOU shape matches MP-3; refusals must not burn cap headroom. |
| 7 | Keep spend caps AND exposure cap (flow vs stock), neither replacing the other? | **Yes.** |
| 8 | Flag `PORTFOLIO_GUARD` default **off**; whatif-cadence validation with WS4 measuring refusals before any live enablement? | **Yes.** |
| 9 | Correlated exposure: **visibility only** for v1 (open-exposure table in banner/summary), category cap deferred? | **Yes** — a cap keyed on partial third-party labels fails open or over-blocks; see the tension recorded in (b). |
| 10 | Mismatch tolerance constant (2%) shared with WS6's sell-side check? | **Yes** — one constant, one definition, coordinated commits. |
