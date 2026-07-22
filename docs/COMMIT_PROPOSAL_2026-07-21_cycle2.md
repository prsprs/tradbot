# Commit proposal — improvement cycle 2 (2026-07-21, evening)

Status: implemented and verified, **uncommitted** (Josh commits per house rules).
Suite: **893 → 1093 passing** (+200), green at every phase boundary, import purity
intact, `git stash list` empty. Adversarial money-path review (Fable 5): **no
blockers, SAFE TO PROPOSE FOR COMMIT**; its one SHOULD-FIX (env universe validation)
is already fixed and tested. Independent verification pass: 10/10 checks PASS,
including a real end-to-end whatif run with hash recomputation and zero repo-history
writes.

This proposal covers ONLY cycle-2 files; cycle-1 work is mapped in
`docs/COMMIT_PROPOSAL_2026-07-21_cascade_followup.md` and should be committed first
(cycle 2 builds on it — e.g. new record fields follow cycle 1's schema-v2 pattern).

## What this cycle is

The Cascade live-session review (20 recommendations) was vetted claim-by-claim:
4 already implemented in cycle 1, 3 already designed and owner-gated, 2 rejected
(armed-observe mode; immediate role-specialized panels), the rest genuinely open and
implemented here as 9 workstreams + 2 audit-driven follow-ups.

## Proposed commits (file-partitioned; each file wholly in one commit)

### Commit 1 — P0 ledger/process correctness
> Take ledger lock in snapshot/restore/quarantine; add instance lock

- `executionledger.py` — `snapshot_ledger`, `restore_from_snapshot`,
  `quarantine_corrupt_ledger` now under `ledger_lock()` (reads-that-persist rule);
  new `bot_instance_lock`/`InstanceLock`/`bot_instance_lock_path` (non-blocking
  flock, per-mode, PID informational only).
- `tests/test_snapshot_lock.py` (8), `tests/test_instance_lock.py` (11).

### Commit 2 — learning loop: HOLD counterfactual scoring
> Classify matured HOLDs as counterfactual grades

- `tradeanalyzer.py` — `hold_class` (`GOOD_AVOID`/`MISSED_WIN`/`CORRECT_NEUTRAL`/
  `HOLD_UNSCORABLE`) via `classify_hold_counterfactual`; `outcome` stays NEUTRAL
  (all aggregation universes preserved); `HOLD_COUNTERFACTUAL_BAND_PCT = 2.0` (new
  constant — **owner judgment call**, `grade()` has no band to reuse);
  `print_hold_classification`; per-provider HOLD-quality tallies; STATE_VERSION 3→4.
- `tests/test_hold_counterfactual.py` (17), `tests/test_analyzer.py` (v4 update).

### Commit 3 — ops: cross-process rate limiting
> Add cross-process LunarCrush throttle, retry, TTL cache

- `ratelimit.py` (new) — flock interval gate, `cached_call` TTL cache,
  `request_with_retry` (Retry-After + bounded backoff), state dir
  `~/.cache/tradbot` / `TRADBOT_STATE_DIR` (never HISTORY_DIR).
- `marketdata.py` — LunarCrush fetches use them; degradation unchanged.
- `tests/test_rate_limit.py` (15), `tests/conftest.py` (state-dir isolation fixture).

### Commit 4 — observability: monolith + records
> Add print-config/plan, data quality, fingerprint, universe honesty

- `crypto_trading_bot.py` — instance-lock guard in `main()`
  (`acquire_instance_lock_or_exit`, `--allow-concurrent` whatif-only);
  `--print-config`/`--plan` (zero-network early exit, secrets presence-only);
  `derive_data_quality` + per-coin `data_quality` into summary/records;
  `market_block_hash` wiring; `_honest_bid_ask`/`_spread_pct` (uses
  `get_best_bid_ask` — product payload has no discrete bid/ask);
  `--deterministic-sampling`; `--discovery-universe` + `build_discovery_prompt`
  (default byte-identical, ast-pinned) + fail-closed env validation + banner/summry
  honesty + phrase pass-through to all five providers.
- `historyutil.py` — `market_block_hash()`; optional record fields `data_quality`,
  `market_block_hash`, `spread_pct`, `sampling`, bid/ask overrides (v1
  byte-identity pinned).
- `sampling.py` (new); `claudeutil.py`, `openaiutil.py`, `grokutil.py`,
  `perplexityutil.py` (phrase kwarg; sampling knobs — openai/grok stay
  provider-default pending a paid probe).
- Tests: `test_print_config.py` (15), `test_data_quality.py` (19),
  `test_ws5_bid_ask_sampling.py` + `test_schema_v2.py` extensions (27),
  `test_discovery_universe.py` (49), `test_structured_requests.py` (1 update).

### Commit 5 — experiment runner
> Add sequential whatif experiment runner with drift detection

- `scripts/run_experiment.py` (new) — spec-driven sequential whatif variants,
  live refusal (regex + forced whatif + `LIVE_TRADING_CONFIRMED` stripped),
  per-variant HISTORY_DIR, manifest + per-coin comparability via
  `market_block_hash` equality (drift reported, never papered over).
- `tests/test_experiment_runner.py` (39).

### Commit 6 — docs, design stubs, reflections
> Record cycle-2 docs, gated designs, and reflections

- `AGENTS.md` (6 new/extended process lessons), `docs/INVARIANTS.md` (gate-placement
  canonical rule; instance-lock + snapshot notes), `docs/RECORD_SCHEMA.md` (new
  field rows; STATE_VERSION 4; frozen-field three-site rule),
  `docs/design/SPREAD_GATE_FEATURE.md` (new, gated),
  `docs/design/PROMPT_CONTRACT_V2_FEATURE.md` (role-panels addendum, same gate),
  `docs/reflections-2026-07-21b/` (9 files incl. ORCHESTRATOR + SYNTHESIS),
  this file.

## Rejected / gated (recorded, not implemented)

- **Armed-observe trading mode**: rejected — redundant with whatif + owner-only live;
  a third mode multiplies the gate-test matrix for no new safety.
- **Spread/liquidity gate**: gated on matured whatif records with populated
  `spread_pct` (capture ships in commit 4); design stub in commit 6.
- **Role-specialized panels**: gated behind the PROMPT_CONTRACT_V2 evidence bar
  (≥200 matured v2 decisions); testable via the experiment runner when the time comes.
- **Vote-schema enrichment** (expected_return/horizon/invalidation): folded into the
  gated WS10 prompt-contract-v2 track, not built separately.

## Review flags for Josh (judgment calls to eyeball)

1. `HOLD_COUNTERFACTUAL_BAND_PCT = 2.0` — new constant, no existing band to reuse.
2. Per-mode instance locks let a live and a whatif run coexist (intended; benign
   because cap tallies are mode-filtered) — confirm you want that.
3. openai/grok deterministic-sampling left provider-default (reasoning models may
   reject temperature); one-line promotion after a paid probe.
4. `sampling` is a sibling record field, not nested under `models` (models values
   are pinned as bare strings).
5. Hardening follow-ups from review (NOTE-level): OPERATIONS_MANUAL line about not
   deleting lock files mid-run; sanitize LunarCrush topic slugs in cache keys.

## Verification (re-runnable)

```bash
./venv/bin/python -m pytest tests/ -q          # expect 1093 passed
./venv/bin/python -c "import crypto_trading_bot"   # silent
HISTORY_DIR=/tmp/scratch ./venv/bin/python crypto_trading_bot.py --trading-mode=whatif --print-config
```
