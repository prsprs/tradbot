# Runbook — Phase 1 live acceptance test (ONE supervised $5 BTC buy)

> **EXECUTED 2026-07-19** by the owner — all sections including §7, with a real
> $5 **ETH** fill (substituted for BTC on the day). Results and findings:
> `docs/ACCEPTANCE_RESULTS_2026-07-19.md`. The procedure below remains the
> reusable runbook for future acceptance passes (e.g. after money-path changes).

**Status: reserved for a human. The agent-side work for T5 is complete.**
Fill confirmation, the execution ledger, the daily spend cap, position
reconciliation, and their tests all landed and pass in what-if. The one thing
an agent must never do is place a real order, so the single live acceptance
trade is deliberately left here for a human operator to execute under
supervision.

This runbook is the acceptance gate for Phase 1 (plan: *Phase 1 — Execution
integrity*, T5). It exercises the full money path exactly once: gate → caps →
order → `success_response` unwrap → `get_order` fill confirmation → ledger fill
row → history join → reconciliation.

---

## 0. Preconditions (verify BEFORE arming live)

- [ ] `./venv/bin/python -m pytest tests/ -q` is green (all pass, 0 xfail).
- [ ] `./venv/bin/python -c "import crypto_trading_bot, executionledger"` is clean.
- [ ] `cdp_api_key.json` is present and valid (real trading credentials).
- [ ] You are watching this run live and can intervene.
- [ ] You accept that this spends **real money** (~$5 plus ~1.2%/side fee) and
      that at $5 notional a directionally-correct trade still nets **≈ −2.4%**
      round-trip (EVALUATION_LESSONS_LEARNED 5.5). This is an execution-path
      acceptance test, **not** an alpha bet.
- [ ] Note today's UTC date. The daily cap sums LIVE intent rows for *today* in
      `history/executions.json`; a prior live buy today counts against it.

## 1. The command (copy exactly)

Run against the REAL history dir (do NOT set `HISTORY_DIR` — the ledger and
history must be the production files for this acceptance test):

```bash
LIVE_TRADING_CONFIRMED=1 ./venv/bin/python crypto_trading_bot.py \
  --live \
  --trading-mode=live \
  --llm-mode=gemini \
  --coins=BTC \
  --notional-usd=5.00 \
  --run-spend-cap-usd=5.00 \
  --daily-spend-cap-usd=5.00
```

Why these values:
- `--live` **and** `LIVE_TRADING_CONFIRMED=1` are the T1 double lock. Missing
  either downgrades to what-if with a `[LIVE LOCK]` notice — if you see that
  notice, live did **not** arm; stop and fix before retrying.
- `--llm-mode=gemini` is a single-LLM probe (one decision, no panel/consensus).
  It may well return HOLD — see the abort criteria; that is a valid outcome.
- `--coins=BTC` — one liquid, cheap-to-reason-about pair.
- `--run-spend-cap-usd=5.00` and `--daily-spend-cap-usd=5.00` cap the blast
  radius at exactly one $5 buy. A second buy this run or day is refused.

## 2. What to watch (in order)

1. **Banner** — `Trading Mode: LIVE (trades will execute) [--live +
   LIVE_TRADING_CONFIRMED=1]`, `Run ID: run_...`, `Notional per buy: $5.00`.
   If it says WHAT-IF, live did not arm — abort.
2. **Decision** — Gemini returns BUY / SELL / HOLD for BTC. Only a BUY proceeds
   to an order (this bot has no SELL path yet; a SELL is recorded and dropped).
3. **Intent row** — `[LEDGER] intent led_...: BUY BTC $5.00 (live,
   client_order_id=run_...-BTC-buy)`. This is written to
   `history/executions.json` **before** the order — a crash after this leaves a
   reconcilable stub.
4. **Order result unwrap** — `[ORDER] ID: <real order id> | Status: FILLED |
   Success: True` and `[ORDER] Filled size: <n> | Filled value: <n> | Avg
   price: <n> | Fees: <n>`. These are REAL values (the pre-T5 bug printed all
   `N/A` because it read top-level keys instead of unwrapping
   `success_response` + `get_order`). If Status is OPEN, the fill did not
   confirm within the poll window — see step 6.
5. **Fill row** — `[LEDGER] fill led_...: filled (order_id=..., size=...,
   avg=..., fees=...)`. Confirm **fees ≈ 1.2%** of $5 (≈ $0.06). A wildly
   different fee is a red flag — investigate before doing anything else.
6. **History record** — `[HISTORY] Recorded: BTC BUY @ $... ` — the
   recommendation row (note it stores the pre-trade quote, by design; the
   ledger holds the actual fill). Both carry the same `run_id`, which joins
   them.

## 3. Post-run verification

```bash
# The execution ledger now has an intent + fill row for this run:
./venv/bin/python -c "import json;print(json.dumps(json.load(open('history/executions.json'))['executions'][-2:], indent=2))"

# Reconcile bot-attributed positions vs. account truth (READ-ONLY):
./venv/bin/python scripts/reconcile_positions.py
```

- [ ] The ledger's last two rows are the intent (`status:'intent'`) and fill
      (`status:'filled'`) for this run, sharing one `ledger_id`.
- [ ] `reconcile_positions.py` lists BTC under **Bot (ledger)** with your new
      size, and shows the account balance alongside. Expect **legacy holdings**
      (SOL, etc. from prior manual/live activity) flagged `bot-unknown balance`
      — that is correct: the report explicitly states bot positions are an
      attribution, **not** account truth.

> **Recommendation (doc note only, no code change):** the reconciliation on
> the current account shows 17 legacy holdings plus ETH drift unrelated to
> the bot. The ledger-attribution design already handles this correctly (it
> never claims account truth, only bot-attributed positions), but a
> **dedicated/clean Coinbase portfolio used only for bot trading** would make
> "drift" mean something — right now the diff between bot ledger and account
> balance is dominated by pre-existing manual holdings, not anything the bot
> did. Consider it before scaling past single acceptance trades.
- [ ] The `run_id` in the ledger intent row matches the `run_id` in the new
      `history/recommendations.json` record (the join key).

## 3a. What today's evidence does / does not show

Today's acceptance run (2026-07-19) validated the **execution path**: gate,
caps, order placement, fill confirmation, ledger, and the daily-cap
accounting all behaved correctly (the startup banner correctly showed "$5.00
spent today" against the acceptance fill). It says nothing about **strategy
performance** — do not conflate the two. Only 6 mature directional records
exist so far, which is not enough to draw any conclusion about whether the
panel's BUY/SELL calls are any good. Before drawing conclusions about
strategy, run `python tradeanalyzer.py` for benchmark-relative scoring (a BUY
that rose but trailed BTC, or didn't clear fees, is scored a LOSS, not a
win). Also remember the fee floor: round-trip fees are ≈1.2% of notional per
side (≈$0.059 observed on the $5 acceptance fill), so at small notional a
trade needs **more than ≈2.4% edge round-trip** just to clear fees before it
can be a real win.

## 3b. Observing a cap refusal without spending money

The daily-cap REFUSAL (`[DAILY CAP] ... refused`) is only reached when a
**BUY** is attempted — it is not consulted on HOLD or SELL votes, and there
is no CLI flag to force a BUY vote (the panel decides). If every vote you've
seen so far has been HOLD, you have never actually seen this refusal path
fire, only inferred it exists from the code. `scripts/demo_cap_refusal.py`
lets you observe it directly, with **no LLM call, no network call, no order,
and no money spent**: it seeds a scratch execution ledger with a whatif
intent that already consumes the daily cap, then calls the exact same
production function (`maybe_execute_buy`) that a real BUY vote reaches, with
a forced decision instead of a panel call. It refuses to run if
`TRADING_MODE=live` or `LIVE_TRADING_CONFIRMED=1` is set.

```bash
mkdir -p /tmp/tradbot-cap-demo
HISTORY_DIR=/tmp/tradbot-cap-demo TRADING_MODE=whatif \
  ./venv/bin/python scripts/demo_cap_refusal.py
```

Observed output (captured 2026-07-19, whatif, scratch `HISTORY_DIR`, no
network, no order):

```
======================================================================
DEMO: daily-cap refusal path (WHATIF, no money, no network)
======================================================================
Scratch ledger: /tmp/tradbot-cap-demo/executions.json
Daily spend cap: $5.00   Notional per buy: $5.00

[SEEDED] whatif intent: SOL $5.00 -> $5.00 already committed today (whatif)

[FORCED] Attempting a BUY for BTC (forced decision -- no LLM call)
----------------------------------------------------------------------
[DAILY CAP] (whatif-simulated) BUY for BTC refused: $5.00 would push today's WHATIF spend past the $5.00 daily cap ($5.00 simulated today across all runs). No real cap was consumed -- this mirrors what live would refuse.
----------------------------------------------------------------------

Blocked by daily cap: 1

[OK] The [DAILY CAP] refusal fired. No order was placed, buy_something() was never called, nothing was spent.
```

This exercises the whatif branch of the cap check (the code path is
identical in shape to the live branch, just against `trading_mode='whatif'`
intents and the `spend_today(trading_mode='whatif')` tally instead of
`live_spend_today()`) — it is a demonstration of the refusal mechanics and
the operator-visible message shape, not a substitute for eventually seeing
the real live `[DAILY CAP]` line fire on an actual BUY vote.

## 4. Abort / no-trade criteria (all normal, not failures)

- **`[LIVE LOCK]` downgrade notice** → live never armed; nothing was spent. Fix
  the flag/env and rerun only if you still intend to.
- **Gemini returns HOLD or SELL** → no order is placed; `Coins to buy: []`.
  This is a valid acceptance outcome (the path was gated correctly). You may
  rerun to seek a BUY, or accept the HOLD and validate the path in what-if
  instead.
- **`[SPEND CAP]` / `[DAILY CAP]`** → a cap refused the buy. Expected if you
  already did a live buy today; the caps work. Nothing spent. Note the caps are
  consulted **only when a BUY is attempted**, so a HOLD/SELL vote never triggers
  either cap line — to demo a cap you need an actual BUY. (The startup banner's
  `Daily spend cap: $X ($Y spent today [UTC])` line shows today's committed
  spend regardless of the vote, so cap visibility no longer depends on a BUY.)
- **`[ORDER] ... Status: OPEN` / fill unconfirmed** → the order was placed but
  did not confirm FILLED within the poll window. The ledger records it
  `unconfirmed`. Do **not** rerun blindly (idempotency will dedupe the same
  `client_order_id`, but confirm first): check the order on the Coinbase UI or
  via `scripts/reconcile_positions.py`.
- **Fee is not ≈1.2%/side, or size/price look wrong** → stop and investigate
  before any further action.

## 5. Rollback

There is **no automated sell path** (deferred per the plan). To unwind the test
position:

1. Open the Coinbase app / web UI.
2. Manually market-sell the BTC amount shown in the fill row / reconciliation
   (expect to net ≈ −2.4% after both fees — this is the measured cost of the
   round trip, not a bug).
3. Re-run `scripts/reconcile_positions.py` to confirm the bot-attributed BTC
   position and the account balance both reflect the exit.

Do **not** hand-edit `history/executions.json`. The ledger is append-only; the
manual sell simply won't be bot-attributed (it will show as drift on
reconciliation, which is the honest record).

## 6. Sign-off

- [ ] Full money path exercised once: gate → cap → order → unwrap → get_order →
      ledger fill row → history join → reconciliation.
- [ ] Real fees observed ≈ 1.2%/side.
- [ ] Position reconciled; legacy holdings correctly flagged `bot-unknown
      balance`.
- [ ] Test position unwound (or consciously retained).

Record the run_id, order_id, filled size, avg price, and fees here for the
Phase 1 acceptance log.

---

## 7. OPTIONAL (owner-only): capture the REAL duplicate-rejection shape (F2)

> **EXECUTED 2026-07-19 — RESULT CAPTURED.** The prediction below ("Coinbase
> should reject the duplicate") was wrong in *shape* but right in *effect*:
> resubmitting the same `client_order_id` returns **`success: true` with the
> ORIGINAL `order_id`** — idempotent server-side dedupe, **no error text at
> all**, no second order, no funds moved. Consequences: `_looks_like_duplicate`
> can never fire on the real duplicate shape (nothing to string-match); the
> reliable duplicate signal is the returned `order_id` equaling the ledger's
> existing `order_id` for that `client_order_id`. F2 recovery (unconditional
> lookup) already handles this correctly. Fixture:
> `tests/fixtures/coinbase/duplicate_rejection.json`; pinned by
> `tests/test_duplicate_rejection_shape.py`. Re-running this section is only
> needed if Coinbase's API behavior is suspected to have changed.

**Why:** `coinbaseutil2._looks_like_duplicate` is a string heuristic that was
**never validated against a real Coinbase duplicate rejection** (an agent can't
place an order to trigger one). F2 no longer *gates* recovery on that heuristic
— every create failure now attempts the client_order_id lookup regardless — but
the heuristic is still used to annotate logs, and the exact rejection shape
(status code, `error_response.error`, message text, whether it throws vs returns
`success:false`) is worth pinning down as a fixture. This step captures it.

**This DOES place a real order** (the same $5 BTC buy as §1), then deliberately
re-submits the **same `client_order_id`** so Coinbase rejects the second create
as a duplicate. Only do it if you accept the §0 spend and are supervising.

1. Complete a normal §1 buy (or run one now). Note the `client_order_id` printed
   in the `[LEDGER] intent` line, e.g. `run_<ts>-BTC-buy`.
2. Immediately re-submit **the exact same** `client_order_id` for the same
   product. From a Python shell against the real client (read the raw
   response/exception — do **not** rely on the wrapper swallowing it):

   ```bash
   ./venv/bin/python - <<'PY'
   from coinbaseutil2 import BlobbyTrader
   t = BlobbyTrader()
   cid = "run_<ts>-BTC-buy"   # <-- paste the client_order_id from step 1
   try:
       resp = t.client.market_order_buy(client_order_id=cid,
                                         product_id="BTC-USD", quote_size="5.00")
       print("RETURNED (no throw):")
       print(resp.to_dict() if hasattr(resp, "to_dict") else resp)
   except Exception as e:
       print(f"THREW {type(e).__name__}: {e}")
   PY
   ```

   Expect **no second fill** — Coinbase should reject the duplicate. If a second
   order *does* fill, stop: idempotency is not working and that is a money bug.
3. **Save the captured shape as a fixture.** Redact nothing structural; drop
   only account identifiers. Suggested home:
   `tests/fixtures/coinbase/duplicate_rejection.json` (create the dir). Record
   whether it threw or returned `success:false`, the `error` code, and the
   message.
4. **Validate `_looks_like_duplicate` against it** and tighten if needed:

   ```bash
   ./venv/bin/python -c "from coinbaseutil2 import BlobbyTrader as B; \
     print(B._looks_like_duplicate('<paste the real error/message text>'))"
   ```

   It should return `True`. If it returns `False`, update the heuristic (and add
   a unit test built from the fixture) so duplicate rejections are correctly
   annotated. Recovery itself is unaffected either way (F2 recovers on any
   failure), but the logs and the heuristic should reflect reality.
5. Reconcile and, if you retained the §1 position, unwind it per §5.

Record here: threw-vs-returned, `error` code, message text, and the fixture
path.
