# INVARIANTS.md — money-path invariants (load first)

The cross-cutting invariants of the live buy path, distilled from docstrings,
tests, and AGENTS.md into one page a design agent can load before touching the
money path. Symbol anchors, not line numbers (this tree's line numbers rot).
AGENTS.md is canonical for doctrine — this page names the authoritative functions.

## (a) Spend-cap contract (MP-10)

Two caps, both checked **before any order is placed**, in `maybe_execute_buy`:

- **Daily cap** (live only, spans runs): `executionledger.daily_cap_would_exceed` →
  `spend_today` → `intended_spend_on_date`, summed from the ledger for the UTC day.
  Exact-cap boundary is **allowed** (`> cap`, not `>=`). What-if does **not** consume
  the live cap; whatif enforces the *same* cap against its own `trading_mode='whatif'`
  intents (soft-fail, separate tally — the modes never share).
- **Per-run cap** (T1): `spend_tracker.try_spend` (what-if spend counts too, so the
  cap is exercised without real money).

**What counts toward the daily cap** (authoritative: `intended_spend_on_date`):
- Every **INTENT** row of the mode on that UTC date — **including intents whose order
  later failed** (intended notional is committed at intent time).
- **Excluded:** attempts whose fill was marked `duplicate_of` (Coinbase idempotent
  dedupe returned the original order — no second fill, so only the first intent
  counts). This is a cap-*loosening* dedupe → treat with the fail-open suspicion
  AGENTS.md demands.
- **`whatif` exclusion:** filtered by `trading_mode`, so whatif intents never touch
  the live tally and vice versa.
- **Fees are excluded** — the cap sums `intended_notional_usd` only, never fees.
- **Caveat (notional vs fees):** the cap is *intended* notional at intent time, not
  filled notional and not fee-inclusive; actual fills + fees can differ. Fee accounting
  lives in the analyzer's `actual_roundtrip_fee_pct`, not the cap.

## (b) Lock ordering

- **Instance lock** (`executionledger.bot_instance_lock`, non-blocking flock on
  `bot_instance.<mode>.lock`, WS-2) is the **OUTERMOST** lock: acquired **once**
  at startup by `crypto_trading_bot.acquire_instance_lock_or_exit` — after
  arg/config resolution, before any network/LLM/ledger work — and held for the
  whole process lifetime, **never interleaved** with the ledger or
  recommendations locks. Per-mode files mean a `live` and a `whatif` run can
  each hold their own (intended: whatif is read-only research). The PID written
  into the file is informational only; flock (freed by the OS on process death)
  is the liveness gate, so a stale PID never blocks. Live contention fails
  closed with no override; whatif refuses unless `--allow-concurrent`.
- **Ledger lock** (`executionledger.ledger_lock`, flock on `executions.json.lock`,
  reentrant per-thread): `maybe_execute_buy` holds it from the **daily-cap READ**
  through `buy_something`'s **intent WRITE**, and in **live mode that span includes
  the actual order placement** — overlapping runs serialize their buys, closing the
  check-then-write TOCTOU. Reentrancy lets `append_intent`/`record_fill` re-acquire it
  inside the span.
- **Recommendations lock** (`historyutil.save_recommendation`, sibling
  `recommendations.json.lock`, shared `file_lock` helper): guards the history
  load→append→replace.
- **Never nested:** the two locks are **never held together**. A call path nesting
  `record_recommendation` inside the `maybe_execute_buy` span is a deadlock bug.
  Current sites are safe because `record_recommendation` runs *before*
  `gate_and_maybe_buy`, never inside it.
- **`snapshot_ledger` now takes the ledger lock too** (MP-11, 2026-07-21): its
  read (`load_executions`) and copy (`shutil.copyfile`) run under
  `with ledger_lock():`, closing a gap where a run-start snapshot could read
  mid-replace against a concurrent writer. Its only caller (`main()`'s
  run-start snapshot) runs before any lock span begins, so this doesn't nest
  today; the lock is reentrant per-thread regardless, so nesting would stay
  deadlock-free if a future caller did. Spec'd by `tests/test_snapshot_lock.py`.

## (c) Gate placement (and why)

- **Decision-quality gate** → `gate_and_maybe_buy` (`decision_allows_trade`, the SELL
  no-op, the BUY dispatch). It is the **shared, lock-free** wiring used by *both*
  analysis loops (coin-choice and discovery), extracted so the gate→execute assembly
  cannot silently diverge between loops. No ledger lock here.
- **Spend caps** → `maybe_execute_buy`, which **holds the ledger lock** from cap-check
  through order placement. Caps belong with the lock; decision quality does not.
- **Placement decision rule (canonical statement — design docs cite this, not each
  other):** does the new check need to *read-then-write ledger state* (TOCTOU risk,
  e.g. exposure caps, spend caps)? → `maybe_execute_buy`, under the ledger lock.
  Is it *decision-quality only* (consensus, spread, edge-vs-fee, data quality)? →
  `gate_and_maybe_buy`, lock-free. This rule was previously restated per feature doc
  (portfolio-awareness, spread-gate, edge-gate) and is promoted here as the single
  source (2026-07-21).
- Read each function's docstring *rationale* before inserting a check. Live and whatif
  daily-cap branches are **structurally different** (live fails closed + quarantines +
  snapshot-restores; whatif soft-fails + continues) — an agent can only ever exercise
  the whatif branch, so a cap-refusal demo proves the same *shape*, not the same live
  *code path*.

## (d) Aggregation-universe table

Every aggregation over ledger/history rows, the row-universe it implicitly assumes,
and the roadmap dimension (side / mode / status / schema_version) that would
invalidate it. **Exhaustive over `executionledger.py`.**

| function | aggregates | implicit universe | dimension that breaks it |
|---|---|---|---|
| **`intended_spend_on_date`** ⭐ | sum `intended_notional_usd` | INTENT rows, filtered by `trading_mode` + date, minus `duplicate_of`; **no `side` filter** | **side** — canonical landmine (`docs/design/SELL_EXIT_LIFECYCLE_FEATURE.md`): assumes only BUY intents exist, so the first SELL-intent writer MUST add the side filter in the same change or sells silently consume the daily *buy* cap. |
| `spend_today` / `live_spend_today` / `daily_cap_would_exceed` | wrappers over `intended_spend_on_date` | inherit its universe | **side** (inherited) — fixing the base function fixes all three. |
| `positions_from_rows` | net size per coin | `FILLED` fills only (`_POSITION_STATUSES`), joined to intent by `ledger_id`, per `trading_mode`, order_id-deduped; **already side-aware** (BUY +, SELL −) | **status** — only `FILLED` moves a position; a new "held" status must be added here. Mode filter present; side already handled. |
| `_intents_by_id` | index INTENT rows by `ledger_id` | assumes `ledger_id` unique among intents | (structural) `ledger_id` collision. |
| `latest_fill_by_ledger_id` | last fill per `ledger_id` | append-only ⇒ file order = chronological; last fill wins | (structural) ordering assumption; underpins repair idempotence. |
| `find_repair_targets` | live rows needing repair | `trading_mode == 'live'` only; latest fill `unconfirmed`/`unverified_failure`/orphan-intent | **mode** (live-only by design); **status** vocabulary. |
| `duplicate_lids` set (inside `intended_spend_on_date` and `record_fill`) | ledger_ids whose fill is `duplicate_of` | truthy `order_id` on both rows; `''`/None never an identity | (structural) falsy order_id must never dedupe (cap-loosening guard, review MAJOR 2). |

Analyzer / historyutil aggregations (not in executionledger, listed for completeness):

| function | row-universe assumption | dimension |
|---|---|---|
| `tradeanalyzer.actual_roundtrip_fee_pct` | join by `(run_id, coin, side)`; **×2 doubling assumes symmetric exit** and BUY-only fills | side / status (SELL fills change the round-trip model). |
| `tradeanalyzer.scoring_universe` | `trading_mode ∈ {live, whatif}` ∧ lifecycle category | mode. |
| `tradeanalyzer.panel_stats` | only `recommendation == 'NONE'` (blocked) rows | status/recommendation. |
| `tradeanalyzer.provider_attribution` / `shadow_score` / `confidence_calibration` / `aggregation_counterfactuals` | only records carrying `vote_details`; legacy v1 falls back to `llm_source` (attribution) or is skipped (shadow) | schema_version (v1 vs v2). |
| `tradeanalyzer.category_counts` / `timing_preview` | all records; branch on `recommendation`=='NONE', `trading_mode`, action | status / mode. |
| `historyutil.load_recommendations` / `tradeanalyzer.load_records` | reads `recommendations*.json`, skips `.bak-*` backups | (file-selection, not a row filter). |

**The rule** (AGENTS.md): any sum/count/dedupe written when only one kind of row can
exist is correct *by accident*. When adding a value to any dimension, grep every
aggregation over those rows and ask what it implicitly assumed.

## (e) Record-evolution rules

See **RECORD_SCHEMA.md** — all new fields optional, v1 byte-identity when omitted
(pinned by `tests/test_schema_v2.py`), `trading_mode` validated at write, the
`market_blocks/<run_id>.json` sidecar, and `analyzer_state.json` (derived, versioned,
discard-on-mismatch). The two history stacks (live bot vs llm_compare) are documented
there and must not be conflated.

## (f) Fail-closed doctrine (pointers — AGENTS.md is canonical)

- **Fail closed on the money path** — an error, refusal, missing panelist, or
  unparseable vote **blocks** a trade, never shrinks the quorum. Fail-closed is against
  the input's whole *type domain*: wrong-shape money files (`{}` ledger, list-where-dict)
  and falsy-but-non-None values (`''` order_ids) are corruption too — validate shape,
  not just parseability. `executionledger.load_executions` **raises `LedgerError`**
  (fails closed) because it backs the cap; `historyutil.load_recommendations`
  **fails open with quarantine** because recommendations gate no money.
- **When a change loosens anything** (frees budget, unblocks a path, dedupes a sum),
  call that direction out explicitly — the fail-open hunt starts there.
- **`PanelDecision` is action-only** — confidence/reasons never reach it; any feature
  reasoning over a per-panelist signal must first plumb the `Vote` object
  (`docs/design/EDGE_VS_FEE_GATING_FEATURE.md`).

See AGENTS.md ("Fail closed on the money path", "Ledger locking contract",
"Implicit-universe aggregations", "Gate boundaries") for the full doctrine.
