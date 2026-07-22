# Sell / Exit Lifecycle Feature (WS6)

## Status

Design spec — **not implemented**. This is the owner-deferred MP-7 work
(`docs/audit-2026-07-19/EVAL.md` MP-7: "the real SELL path is a separate,
owner-scoped feature that must ride the same fail-closed machinery"), produced
per `docs/IMPROVEMENT_PLAN_2026-07-20.md` WS6. **Design only; implementation
starts only after Josh signs the decision checklist at the end.**

Direction call-out (AGENTS.md fail-open hunt): a SELL path is the first
feature in this repo that **moves assets out** of a position. It cannot loosen
the BUY path (it touches none of the buy gates), but it introduces a new class
of money-moving action with its own fail-open surface: *selling more than the
bot owns, selling what the user bought manually, or selling on a signal the
panel never fail-closed on.* Every recommendation below is chosen to keep the
sell side exactly as fail-closed as the buy side.

## Overview

Today the bot's lifecycle is entry-only:

- `gate_and_maybe_buy` short-circuits SELL with a loud
  `[NO SELL PATH]` line and returns False (crypto_trading_bot.py:2042-2045).
- `market_order_sell` exists with **zero callers** (coinbaseutil2.py:488-512).
  It places the order and unwraps the create response but does **no fill
  polling** and **no create-failure recovery** — deliberately minimal because
  nothing calls it.
- The ledger already *anticipates* sells: `append_intent` takes
  `side='BUY'|'SELL'` (executionledger.py:344), and `positions_from_rows` nets
  SELL fills as negative size (executionledger.py:508-512, "SELLs are
  supported for the day a SELL/exit path exists").

Consequence (MP-7): exposure grows without bound (~$450/month at the old
default caps; proportionally more at Josh's current $25/$50/$100 settings),
consensus SELL signals are recorded and dropped, and any manual exit desyncs
the attributed positions until `scripts/reconcile_positions.py` runs.

This spec defines the full entry-to-exit lifecycle for the **CEX path only**
(DEX explicitly out of scope, see Non-goals): what triggers an exit, how the
sell executes and confirms, how the ledger records it, how P&L links back to
the entry, and how the existing safety machinery extends to the sell side.

---

## (a) What triggers an exit

Two fundamentally different trigger classes exist. They must not be conflated,
because one is a *panel judgment* and the other is a *mechanical owner rule*.

### Trigger class 1 — consensus SELL on a held asset (RECOMMENDED for v1)

The panel already produces SELL votes under the same fail-closed unanimity as
BUY (`decision_allows_trade`, crypto_trading_bot.py:1193; vote schema
voteschema.py:49). The only missing piece is execution. Rule:

> A gate-approved SELL for coin X dispatches a sell **iff** the bot holds an
> attributed position in X (`executionledger.positions()` > 0 for X). A SELL
> on a coin with no attributed position prints `[SELL: NO POSITION]` and does
> nothing — it is a directional opinion, not an executable exit.

Why this is the right v1:

- It reuses every existing safety layer unchanged: schema-enforced votes,
  fail-closed unanimity, abstain machinery, symbol binding. Zero new
  decision-making surface.
- The panel is *already asked* "buy, sell, or hold ... right now"
  (panelprompts.py:94-103) — SELL votes exist today and are wasted.
- It is naturally rare (unanimous SELL on a specifically-held coin), which is
  the correct rollout posture for the first asset-outbound path.

Known weakness, stated honestly: the panel does not know the bot holds the
coin, so its SELL is a market opinion, not a position-management judgment.
Fixing that is a **prompt change** (tell the panel the entry price/date when a
position exists) and belongs to WS10/prompt-contract territory — flagged as an
interaction, not designed here. v1 executes on market-opinion SELLs; that is
strictly better than dropping them.

### Trigger class 2 — owner-defined mechanical rules (RECOMMENDED for v2, design fixed now)

Stop-loss %, take-profit %, max holding period, thesis invalidation. Critical
structural fact: **the bot is episodic** — it runs on a cadence
(docs/RUNBOOK_whatif_cadence.md), it is not a resident process. Therefore:

- Mechanical rules are **checked at run start, per run** — never continuously.
  A 10% stop-loss means "if, when a run happens, the position is ≥10% under
  its cost basis, exit" — not a resting stop order. This must be documented
  loudly; an owner who believes they have a real-time stop has a false sense
  of protection. (A resting exchange-side stop order is a different feature —
  out of scope, see Non-goals.)
- Proposed rule set (all optional, all off by default, all env/flag config
  following the `get_config_source` pattern so the startup banner shows them):
  - `EXIT_STOP_LOSS_PCT` — exit if mark price ≤ cost basis × (1 − pct/100).
  - `EXIT_TAKE_PROFIT_PCT` — exit if mark price ≥ cost basis × (1 + pct/100).
  - `EXIT_MAX_HOLD_HOURS` — exit any position older than this (age from the
    entry intent row's timestamp; naive-UTC + 'Z' contract, parsed only via
    `tradeanalyzer.parse_timestamp`/`utc_epoch` per AGENTS.md).
- Cost basis and age come from the **ledger** (entry fill's
  `avg_fill_price`/`filled_size` joined by ledger_id; executionledger.py:
  468-514) — never from account history.
- Mechanical exits run **before** the analysis loop (they need no LLM calls
  and must not be skippable by an all-HOLD run — same lesson as the
  operator-visibility rule in AGENTS.md), each printing a loud
  `[EXIT RULE]` line naming the rule, the position, cost basis, mark, and age.
- Rule ordering when several fire: stop-loss > max-hold > take-profit
  (loss containment first). One sell per coin per run regardless.
- "Thesis invalidation" (the panel's original reason no longer holds) is NOT
  mechanically checkable today — reasons are display-only text, never traded
  on (AGENTS.md hard rule; the phantom-BUY bug class). It becomes possible
  only after WS3 persists structured decision context and WS10 gives votes a
  stated horizon. **Deferred**; do not fake it with text matching.

Recommendation: **ship class 1 first, alone.** Class 2 rides the same
execution machinery later; its config surface and semantics are fixed by this
doc so it does not get redesigned.

### Precedence between the classes

When both could apply in one run: mechanical rules run first (pre-loop). A
coin exited by rule is still analyzed by the panel afterwards (its votes are
recorded), but a second sell for the same coin in the same run is refused by
the position check (position is now ~0).

---

## (b) Sell execution and fill confirmation

`market_order_sell` (coinbaseutil2.py:488) is deliberately behind the buy path.
Bringing it to parity means mirroring the buy contract
(coinbaseutil2.py:195-255) exactly:

1. **Deterministic client_order_id**: `build_client_order_id(run_id, coin,
   'sell')` — already wired (coinbaseutil2.py:496). The `'sell'` intent
   suffix keeps it distinct from the same run's buy id, so retries dedupe
   idempotently the same way (duplicate resubmit returns the ORIGINAL
   order_id, success:true — validated live 2026-07-19, never string-match
   error text; `tests/fixtures/coinbase/duplicate_rejection.json`).
2. **Create-failure recovery (F2)**: on any create exception or
   success=false, run `_resolve_create_failure` (coinbaseutil2.py:257-287)
   exactly as the buy does — an ambiguous timeout may have actually placed the
   sell; it must never be ledgered as a clean failure. `_recover_order` and
   `_find_order_by_client_order_id` are side-agnostic already
   (side comes from the found order, coinbaseutil2.py:419/482).
3. **Fill polling**: `_poll_fill` (coinbaseutil2.py:323-338) after a
   successful create, same tries/delay, capturing status / filled_size /
   average_filled_price / total_fees. Never-confirmed → `unconfirmed` ledger
   status → picked up by `reconcile --repair` (its repair-target logic is
   already side-carrying, executionledger.py:568).
4. **base_size, not quote_size**: sells are sized in the base asset
   (coinbaseutil2.py:501). Size determination is a money-path rule of its own
   — see (d) "how much to sell".

Implementation shape: refactor `market_order_buy`'s post-create sequence into
a shared `_execute_market_order(side, ...)` used by both, OR duplicate the
~40 lines into `market_order_sell`. **Recommend the shared helper** — the F2
recovery ladder is exactly the code you do not want to fork (the repo's
duplicate-format-string lesson, AGENTS.md), but the refactor must be
characterization-tested against the existing buy tests first so the buy path
provably does not change.

### The bot-side wiring

Mirror the buy chain one-for-one:

```
gate_and_maybe_buy                      (SELL branch, replacing [NO SELL PATH])
   +--> maybe_execute_sell(coin_symbol)          [NEW — sell twin of :1878]
          0. feature flag off -> [NO SELL PATH] (unchanged behavior)
          1. exclusion list (yes, sells too — see (f))
          2. position check: attributed position > 0, else [SELL: NO POSITION]
          3. balance cross-check (fail closed, see (d))
          4. sell_something(coin) -> SELL intent row -> order -> fill row
```

`maybe_execute_sell` holds `executionledger.ledger_lock()` from the position
READ through the intent WRITE and live order placement, exactly like
`maybe_execute_buy` does for the cap read (MP-3 TOCTOU closure,
crypto_trading_bot.py:1920; docstring rationale :1901-1908). Two overlapping
runs must not both read "position open" and both sell it. The history lock is
never taken inside this span (deadlock contract, AGENTS.md).

Write-order is crash-safe by construction, same as `buy_something`
(crypto_trading_bot.py:1780-1793): SELL **intent row first**, then the order,
then the fill row. A crash mid-sell leaves a reconcilable stub.

---

## (c) Ledger semantics

### SELL intent rows

`append_intent(..., side='SELL')` — already supported (executionledger.py:344).
Two additions:

- `intended_base_size` (new field): sells are sized in base units;
  `intended_notional_usd` is recorded too (base_size × current bid) for
  human-readable auditing, but the base size is the execution truth.
- `closes` (new field): the list of entry `ledger_id`s this sell is exiting,
  computed at intent time by FIFO over the coin's open attributed entries.
  This is the **realized-P&L linkage** — explicit at write time, never
  re-inferred later. (FIFO because it is deterministic and matches standard
  cost-basis accounting; with the duplicate-exposure guard of WS7 there will
  usually be exactly one open entry anyway.)

Fill rows are unchanged in shape (`record_fill`, executionledger.py:371) —
side lives on the intent and is recovered by the ledger_id join, exactly as
documented at :385-388.

### Realized P&L

A new pure derivation `realized_pnl_from_rows(rows)` (sibling of
`positions_from_rows`): for each SELL fill, join to its intent's `closes`
entries, P&L = (sell proceeds − sell fees) − (allocated entry cost + allocated
entry fees). Pure function over rows, unit-testable without I/O, consumed by
the analyzer and the run summary. This is the first **realized** (not
benchmark-relative-expected) performance number the repo will have; it must be
labeled distinctly from the analyzer's fee-adjusted excess-return grades —
they answer different questions.

### Interaction with the daily-cap contract (MP-10) — **load-bearing**

`intended_spend_on_date` sums `intended_notional_usd` over **all** intent rows
of the mode with no side filter (executionledger.py:574-600) — written when
only BUYs existed. If SELL intents carry a notional, **they would silently
count against the daily spend cap**, blocking buys. Two decisions:

1. **SELL intents must not consume the daily cap.** Add
   `if (r.get('side') or 'BUY').upper() != 'BUY': continue` to the cap sum.
   Direction call-out per AGENTS.md: on the day sells exist this is
   cap-neutral-to-tightening relative to the naive alternative (which would
   over-block); relative to today it changes nothing (no SELL rows exist).
   It must land **in the same commit** as the first SELL-intent writer, with a
   test pinning "a SELL intent does not move `spend_today`".
2. **Does selling free up buy cap? RECOMMENDED: NO.** The daily cap is a
   *flow* limit on money the bot commits per UTC day — a blast-radius bound,
   not a portfolio-size bound (that is WS7's exposure cap). Refunding cap on
   sells converts it into a churn allowance: buy $100, sell, buy $100 again —
   $200 of order flow and ~$4.80 of fees in a day under a "$100 cap". That is
   a **loosening** and is rejected. Sells neither consume nor free the daily
   cap; the same rule applies to the per-run `SpendTracker` cap.

This decision also resolves half of MP-10's ambiguity going forward: the cap
contract is explicitly "sum of BUY-side intended notional, fees excluded" —
document it in the `--daily-spend-cap-usd` help text in the same change.

### What-if simulation of sells

Symmetric with the buy's whatif branch (crypto_trading_bot.py:1822-1833):
SELL intent row + `record_fill(status='simulated', avg_fill_price=<bid>,
fees_usd=round(proceeds*0.012,4), fees_estimated=True)`. Fill at the **bid**
(a market sell crosses the spread the other way; the buy simulates at the
ask, :1803/:1829). `positions_from_rows` then nets the simulated position
down with no further changes (executionledger.py:509-510 — mode isolation
already guarantees whatif sells never move a live position, :502). This gives
the whatif stream full lifecycle P&L, which is what makes WS4's realized-P&L
measurement possible without live risk.

---

## (d) Safety locks and sizing

### Live interlock — RECOMMENDED: identical double interlock, no additions

A live sell moves real assets; it requires exactly what a live buy requires:
`--live` AND shell-provided `LIVE_TRADING_CONFIRMED=1`, with the .env-proof
scrub (`crypto_trading_bot.py:1607-1678` — the lock deletes a
`LIVE_TRADING_CONFIRMED` smuggled via `.env`). No *additional* sell-specific
interlock: the asymmetric risk ("bot dumps my holdings") is controlled by the
never-touch-non-bot-holdings rule below plus the feature flag, not by a third
env var that would train the owner to type two confirmations reflexively.
Agents remain forbidden from live runs entirely (AGENTS.md hard rule 1 —
unchanged, and it automatically covers sells).

Feature flag: `ENABLE_SELL_PATH` env / `--enable-sell` flag, **default off**.
Off = today's behavior byte-for-byte (`[NO SELL PATH]` line). Banner prints
the sell-path state unconditionally at startup (operator-visibility rule:
an all-HOLD run must still show whether sells are armed).

### How much to sell — the sizing rule

**RECOMMENDED: full exit of the bot-attributed position, capped by live
balance.**

```
attributed = executionledger.positions()[coin]          # bot's book
balance    = trader.list_account_balances()[coin]        # account truth (coinbaseutil2.py:167)
sell_size  = min(attributed, balance)
```

- Partial/scaled exits are a strategy refinement with no evidence basis yet —
  v1 exits are all-or-nothing per coin.
- The `min()` is the **never-touch-non-bot-holdings guarantee**: the bot can
  never sell more than it bought, and never sells at all when its book says
  it holds nothing — assets acquired outside the bot are structurally
  unreachable (they exist only in `balance`, never in `attributed`).
- **Mismatch fail-closed**: if `balance < attributed × 0.98` (someone sold
  part of the bot's position manually; 2% tolerance for exchange rounding
  and fee-in-kind dust), the live sell is REFUSED with
  `[SELL: LEDGER/BALANCE MISMATCH]` naming both numbers and pointing at
  `scripts/reconcile_positions.py`. A book that disagrees with the exchange
  is corruption on the money path; we do not guess (same doctrine as the
  MP-2 corrupt-ledger refusal, crypto_trading_bot.py:1922-1947).
- **Balance fetch failure fails closed for live sells** —
  `list_account_balances` returns `{}` on error (coinbaseutil2.py:176-179),
  which must read as "could not verify", not "zero balance is fine to skip":
  refuse with `[SELL: BALANCE UNVERIFIABLE]`. Whatif sells skip the balance
  cross-check (no real account is involved; soft behavior mirrors the whatif
  daily-cap branch's soft-fail philosophy, :1948-1973).

### Failure modes

| Failure | Handling |
|---|---|
| **Partial fill** | Market orders on liquid pairs fill fully, but `_poll_fill` may capture a partial `filled_size` before timeout, or an order can complete partially in edge cases. The fill row records the actual `filled_size`; `positions_from_rows` nets only what filled, so a residual position remains attributed and the next run's exit logic (or rule) sees it. No retry-in-run: one sell attempt per coin per run (retries reuse the deterministic client_order_id across runs, so they are idempotent). |
| **Dust below Coinbase minimums** | Before placing, check the product's `base_min_size` (via `get_product_details`, probe the exact field name first — probe-before-migrate, AGENTS.md). If `sell_size < base_min_size`: print `[SELL: DUST]`, write **no** intent row (nothing was attempted), and mark nothing — the position stays attributed. Dust positions are a reporting concern (surface them in the run summary), not a trading concern. Never round *up* to the minimum (that would sell non-bot holdings). |
| **Sell of a coin acquired outside the bot** | Structurally impossible (sizing rule above): no attributed position → `[SELL: NO POSITION]`, regardless of balance. |
| **Unconfirmed sell** | `status='unconfirmed'` fill row; position is NOT netted down until a confirmed fill row lands (a repair row via `reconcile --repair`, whose targeting logic already carries side, executionledger.py:562-570). Conservative direction: the bot thinks it still holds the coin and may re-attempt next run — the deterministic client_order_id makes the re-attempt collapse onto the original order rather than double-sell. |
| **Sell create cleanly failed** | `status='failed'`; position unchanged; next run may retry (new run_id → new client_order_id → genuinely new attempt — intended). |

### How `[NO SELL PATH]` retires

The `final_action and 'SELL' in final_action` branch of `gate_and_maybe_buy`
(crypto_trading_bot.py:2042-2045) becomes:

```
if final_action and 'SELL' in final_action:
    if not SELL_PATH_ENABLED:
        print("[NO SELL PATH] ...")        # today's exact line
        return False
    return maybe_execute_sell(coin_symbol) # may itself refuse (flag order: position, balance, dust)
```

The interim guard is thus never deleted — it becomes the flag-off branch, so
the rollout can be reverted by unsetting one flag. `gate_and_maybe_buy`
remains the single gate→execute wiring for both loops (TS-2 rationale,
:2025-2032); the sell dispatch must NOT be added anywhere else.

---

## (e) Test plan

House method: write the spec as failing tests first (xfail), flip by
implementing. All under `tests/`, no network (conftest socket block), never
the real `history/` (redirected `HISTORY_DIR` / monkeypatched
`EXECUTIONS_FILE` — and never `monkeypatch.undo()`, per AGENTS.md).

1. **Ledger pure functions** (`tests/test_execution_ledger.py`): SELL intent
   row shape (`side`, `intended_base_size`, `closes`); cap sum ignores SELL
   intents (the load-bearing MP-10 test); `positions_from_rows` nets a
   confirmed SELL; duplicate-order_id dedupe works across sides; realized-P&L
   derivation over synthetic buy+sell row sets (fees, FIFO allocation,
   partial-fill residue).
2. **Sizing / guards** (new `tests/test_sell_path.py`): min(attributed,
   balance); mismatch refusal at the 0.98 boundary; balance-fetch-failure
   refusal (live) vs skip (whatif); dust refusal writes no intent; no-position
   refusal; exclusion-list refusal.
3. **Gate wiring** (`tests/test_consensus.py` + run-summary tests): flag off
   → byte-identical `[NO SELL PATH]` (characterization test BEFORE the
   refactor); flag on + no position → `[SELL: NO POSITION]`, `maybe_execute_sell`
   never reaches order placement; flag on + position → dispatch. New
   block/refusal strings added to `tests/test_consensus.py` — that file is the
   sole spec for the reason vocabulary (AGENTS.md).
4. **Order-layer parity** (`tests/test_coinbase_orders.py` or equivalent):
   shared `_execute_market_order` characterization — buy behavior unchanged
   byte-for-byte; sell path polls fills, runs F2 recovery on create failure,
   maps unconfirmed/unverified/failed to the right ledger statuses. Reuse the
   existing buy-path fixtures; sell create-response fixture captured by a
   cents-scale live probe **only by the owner** (a real sell is a trade —
   agents may never place it; the probe-before-migrate rule meets hard rule 1
   here and hard rule 1 wins).
5. **Whatif end-to-end** (integration-ish, stubbed market block): panel SELL
   on a coin with a simulated open position → simulated SELL fill at bid,
   estimated fees, position netted to ~0, run summary counts the exit.
6. **Locking**: `maybe_execute_sell` holds the ledger lock across
   read-position→write-intent (assert via the reentrant-lock test pattern);
   no history-lock nesting inside the span.
7. **Mechanical rules (v2, when built)**: per-rule boundary tests at exact
   thresholds; rule precedence; pre-loop execution (fires even when every
   vote is HOLD).

## (f) Migration / rollout

1. Land ledger side-awareness (cap-sum side filter + new intent fields +
   tests) — inert while nothing writes SELL rows, but reviewed as money-path.
2. Land the order-layer parity refactor (characterization-tested; buy
   unchanged).
3. Land `maybe_execute_sell` + gate wiring behind `ENABLE_SELL_PATH`
   (default off). Suite green; whatif validation runs with the flag on
   against scratch `HISTORY_DIR` per the runbook cadence.
4. Owner reviews whatif sell records + realized-P&L output; then a single
   supervised live acceptance run mirroring
   `docs/RUNBOOK_live_acceptance.md` (small position bought and exited,
   fixture captured, results doc stamped).
5. Only then does the flag default flip — as its own owner-decided commit.

Sells stay on the exclusion list's jurisdiction: an excluded coin is refused
for sells too in v1 (simplest honest rule: the bot does not touch that coin
in any direction; can be revisited if an excluded coin ever ends up held).

## (g) Non-goals (explicit)

- **No DEX sell path.** DEX buys already lack exchange-side fill confirmation
  (audit finding #2, crypto_trading_bot.py:2660-2669); building sells on that
  foundation is refused until the buy side confirms fills. CEX only.
- **No resting exchange-side stop/limit orders.** Mechanical rules are
  run-time checks; the limit-order-at-support feature is separate.
- **No partial/scaled exits, no position sizing strategy.** Full exit only.
- **No short selling, no EXIT-vs-SELL taxonomy change** (that is WS10's
  contract; this feature consumes whatever action string the gate approves).
- **No thesis-invalidation automation** (blocked on WS3/WS10 structured
  context; never via reasons-text matching).
- **No change to buy gates, consensus math, caps, or the exclusion default.**
- **No portfolio-level exit policy** (drawdown-triggered liquidation etc.) —
  WS7 territory at most, and not even designed there.

---

## Decision checklist for owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | Ship v1 with **consensus-SELL-on-held-asset only** (mechanical rules as fixed-design v2)? | **Yes** — smallest new surface, reuses all fail-closed machinery. |
| 2 | Sells **never consume and never free** the daily cap or run cap (cap = BUY-flow only)? | **Yes** — refunding cap on sells is a churn-enabling loosening; WS7's exposure cap is the stock-side control. |
| 3 | Sizing = **full exit of min(attributed position, live balance)**; never touch non-bot holdings? | **Yes** — structural guarantee, not a check. |
| 4 | **Fail closed** on ledger/balance mismatch (>2% short) and on balance-fetch failure, for live sells? | **Yes** — book-vs-exchange disagreement is money-path corruption; point at reconcile_positions.py. |
| 5 | Live sells require the **same double interlock** (`--live` + shell `LIVE_TRADING_CONFIRMED=1`), no third knob? | **Yes** — same, not more; the flag + no-position rule carry the sell-specific risk. |
| 6 | Feature flag `ENABLE_SELL_PATH` default **off**, `[NO SELL PATH]` retained as the flag-off branch? | **Yes** — one-flag revert. |
| 7 | Realized P&L linkage via explicit `closes` (FIFO) on the SELL intent row? | **Yes** — write-time attribution, never re-inferred. |
| 8 | Dust below exchange minimum: **skip, keep attributed, report** (never round up)? | **Yes.** |
| 9 | Excluded coins refused for sells too in v1? | **Yes** (revisit only if an excluded coin is ever actually held). |
| 10 | Owner-run live acceptance (buy + exit round trip, fixture captured) gates the flag-default flip? | **Yes** — the sell create-response shape is unprobed; MP-7's "same fail-closed machinery" needs the same acceptance layer that caught §7. |
