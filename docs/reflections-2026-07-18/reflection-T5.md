# T5 session reflection — fill confirmation + execution ledger (2026-07-18)

Written from session memory only, per coordinator instruction (no repo re-reads).

## 1. Friction (what slowed me down / near-misses)

- **SDK claim in the spec was wrong:** the task said "list_orders supports filtering
  [by client_order_id]; verify in SDK". Verified: the installed SDK's `list_orders`
  has NO client_order_id parameter. Duplicate recovery became
  `_lookup_order_by_client_order_id`: list the product's recent orders (limit=100)
  and match client-side. Cost ~30 min of signature/type spelunking.
- **`fee` vs `total_fees`:** the one real read-only `get_order` I captured had
  `fee=''` (empty string) with the real value in `total_fees`. If I'd coded the
  obvious `order['fee']` first, tests-from-doc-prose would have passed and live
  would have logged empty fees. `_apply_order` prefers `total_fees`, falls back.
- **No `ask` on the Product type:** the spec's what-if synthetic fill wants
  "avg_fill_price: current ask", but the SDK Product models only `price` /
  `mid_market_price`. Wrote `_current_ask` with an ask→best_ask→mid→price fallback
  chain (works because BaseResponse sets arbitrary keys if the API sends them).
- **The ONE what-if run returned SELL,** so the bot run alone never exercised the
  ledger write. Had to call `buy_something('BTC')` directly with ~6 module globals
  hand-wired (trader, RUN_ID, TRADING_MODE, WHATIF_MODE, DEX_MODE, NOTIONAL_USD).
  That global-coupling is the single riskiest part of verifying this path.
- **Scratch-path typo in the task** (`…fba42a2…` vs real `…fba42da2…`) — caught by
  checking existence before the run; a blind `mkdir -p` of the typo'd path would
  have "worked" and scattered artifacts.
- **Mid-session `.gitignore` change I didn't make** (parallel agent/orchestrator).
  Burned time ruling out hooks/reflog/bot code before proceeding. Parallel-editing
  sessions need a "who owns which files" note.

## 2. Guidance quality

- **Gold:** the §5.5 measured numbers verbatim in the prompt (0.06562167 / 75.28 /
  0.0593) — fixtures wrote themselves and the 1.2% fee check was concrete.
  Also gold: the explicit never-place-an-order rule + "at most ONE bot run".
- **Wrong:** the list_orders-filter claim (above); the scratch path typo.
- **Missing (next execution-path agent shouldn't rediscover):**
  - What a real duplicate-client_order_id rejection LOOKS like. I invented
    plausible `error_response` strings; `_looks_like_duplicate` is a heuristic
    never validated against the real API (can't trigger one without placing
    orders). The human live test should deliberately re-run once to capture it.
  - Real `get_order` carries ~40 keys the SDK Order doesn't model, all numerics
    as strings, `fee=''` — a captured-fixtures file would have said all this.
  - Product has no discrete ask.

## 3. Design doubts (plainly)

- **Worst edge:** if a create times out ambiguously and my duplicate heuristic
  fails to match Coinbase's actual wording on retry, the retry returns
  `success=False` → ledger `failed` — while the ORIGINAL order may have filled.
  Money spent, ledger says failed. Reconciliation drift catches it, but only if
  someone runs it. Mitigation worth doing: on ANY create failure, also try the
  client_order_id lookup, not just on duplicate-looking errors.
- **Crash window intent→fill:** the stub is reconcilable but nothing repairs it.
  A `reconcile --repair` that finds intent rows without fills and back-fills via
  the client_order_id lookup is the natural next step (out of scope for T5).
- **Daily cap counts intent rows,** so a day of FAILED creates exhausts the $15
  cap without spending a cent. Chosen deliberately (fail-safe direction) but the
  owner should know refusals don't consume cap while failures do.
- **client_order_id has no sequence:** `run_id-coin-buy` collides if one run ever
  buys the same coin twice (impossible today; breaks under future DCA/repeat
  analysis). Fine now; add an ordinal before that feature.
- **Ledger concurrency:** load-all + append + atomic replace prevents corruption
  but is last-writer-wins if two bot processes run at once — a row can be lost.
  No file locking. Single-user cron cadence makes this acceptable, barely.
- **DEX fill-row mapping is guesswork:** I mapped `tx_signature/base_amount/
  out_amount/price/fee_usd` from reading dex/trader.py, never validated against a
  real DEX result dict. Treat that branch as unverified.
- Simulated fills carry `filled_size=None`; if the analyzer wants a synthetic
  size it must derive notional/ask itself.

## 4. Repo improvements that would have materially helped

1. **`tests/fixtures/` of captured real API responses** (create success, create
   failure, get_order FILLED/OPEN, get_accounts) checked in redacted. I rebuilt
   shapes from doc prose + one live capture; every future execution agent will
   repeat that unless it's persisted.
2. **A context object instead of module globals for the trade path** —
   `buy_something` reading six globals made both testing and my manual what-if
   exercise fragile. Even a dataclass passed down from main() would do. (Shared
   `conftest.py` for the sys.path/tmp-ledger boilerplate is a small third.)

## 5. Tradbot itself — for the owner

- **`unconfirmed` is a real live state:** if get_order errors 3× (network blip),
  the buy is recorded unconfirmed though money moved. Nothing re-polls later.
  Until a repair pass exists, treat any `unconfirmed` row as "check Coinbase UI
  now" — the runbook says so, but only for the supervised test, not for future
  scheduled live runs.
- **Audit other code for reading `fee`:** it's empty on real orders; the value
  lives in `total_fees`. Anything summing `fee` silently reports zero fees.
- **`get_accounts` pagination:** `list_account_balances` does one limit=250 call
  and does not follow `has_next`; an account with more currencies under-reports,
  and reconciliation would mislabel the missing ones. Low risk, easy fix.
- **Reconciliation skips USD/USDC/USDT as cash** — correct today, but if
  stablecoin positions ever become a strategy, they're invisible in the report.
- **Fees confirmed again:** the captured SELL leg showed 0.1186 on ~$9.88 ≈ 1.2%
  — the 2.4% round-trip floor is real; the ledger now records it per trade, so
  the analyzer can finally score net-of-fees instead of direction-only.
