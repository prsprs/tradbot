# WS-6 reflection: `--print-config` / `--plan`

First-person implementer notes, harvested at phase end (per the reflection-harvest
pattern). Verified-by-me unless marked INHERITED.

## What shipped

Two zero-network introspection flags in `crypto_trading_bot.py`:

- `--print-config`: emits fully-resolved operational config as JSON
  (`{"settings": {key: {value, source}}, "credentials": {provider: present|absent}}`)
  and exits 0.
- `--plan`: everything print-config does, plus a human-readable RUN PLAN block.

Both exit 0 **after** full config resolution but **before** the instance lock,
the analyzer summary, `.env`-key-dependent client construction, and any network.
The hook is a single `if` immediately after `args = parse_args()` in `main()`,
which is itself after `load_dotenv()` + `_refresh_env_snapshots()` — so resolved
`.env` defaults are visible, exactly the owner's original need.

New symbol anchors (not line numbers — this tree churns):
- `build_config_report(args, environ)` — the resolver/reporter.
- `build_plan_lines(report, environ)` — human-readable plan from a report.
- `emit_config_report_and_exit(args, environ, include_plan)` — print + `sys.exit(0)`.
- `_config_source_label`, `_credentials_presence`, `_resolve_effective_coins`,
  `_instance_lock_held` — helpers.

## Judgment calls (owner should review these)

1. **Keys included.** trading_mode (effective, via `resolve_trading_mode`),
   llm_mode, primary_llm, compare_llms, coins, discovery, exclude_coins, chains,
   categories, polymarket_filter, require_consensus, tiebreaker, notional_usd,
   run_spend_cap_usd, daily_spend_cap_usd, dex, slippage, and the five resolved
   `model_<provider>` IDs (from `modelregistry`). "universe" from the spec has no
   corresponding flag/env in this codebase, so it's omitted (spec said "if present").

2. **Keys excluded.** Pure-operational/no-money flags that aren't decision-shaping
   were left out to keep the report focused: `--log-rounds`, `--show-responses`,
   `--quiet`, `--json-summary`, `--export-*`, `--candidate-*`,
   `--relax-discovery-failure`, `--skip-preflight`, `--skip-analyzer`,
   `--test-wallet`, `--allow-concurrent`. Easy to add if the owner wants them.

3. **`use_discovery` is derived, not a `{value,source}` setting.** It has no flag
   of its own (it's `len(coins)==0`), so surfacing it with a fake "source" would
   have broke the uniform shape contract. It's recomputed inside the plan builder.

4. **Provenance reuse, not reimplementation.** Every source label goes through the
   existing `get_config_source` (the same machinery the startup banner uses);
   `_config_source_label` only normalizes its `--flag`/`ENV env`/`default` answer to
   the WS-6 `cli`/`env`/`default` vocabulary. Coin-selection honesty reuses
   `parse_analyze_coins` + `resolve_coin_selection_conflict` (so an override that
   flips env-coins into discovery mode is reflected). The transforms for
   chains/categories/discovery-methods are byte-identical to `main()`'s — a real
   drift risk if `main()` changes, called out below.

5. **Credentials = presence only, from env-var names + the coinbase file's
   existence.** Never reads a key value (redaction by construction, so the
   redaction tests pass trivially). Derived directly from `os.environ`
   (`_CREDENTIAL_ENV_VARS`, mirroring the names claudeutil/openaiutil/grokutil/
   perplexityutil/llmpreflight require) — no client construction, no network.

6. **Instance-lock check is a read-only probe that never creates the lock file.**
   `_instance_lock_held` uses `executionledger.bot_instance_lock_path` and, only if
   the file already exists, opens it `'r'` and does a momentary non-blocking
   `flock` + immediate unlock to distinguish HELD vs FREE. If the file is absent →
   FREE, and we do **not** create it (`open('a+')`, which the real acquire path
   uses, would). The run is never started under the probe. This is the one spot
   that momentarily touches the lock; I judged that acceptable for "read-only", and
   the tests assert no lock file is left behind.

7. **Approx LLM call count is explicitly approximate:** `panel*2 + tiebreaker` per
   coin (round-1 + up-to round-2 peer + at most one tiebreaker). Discovery mode
   can't know the coin count pre-discovery, so it's reported per-discovered-coin.

## How exit-before-network is guaranteed

Placement, not interception. The flags are handled before `pytrends`
construction, before `acquire_instance_lock_or_exit`, before
`tradeanalyzer.run_startup_summary`, before the DI-4 ledger snapshot, and before
any client init. The subprocess tests prove it under poisoned sockets (grenades
on `socket.socket.connect`/`create_connection`/`getaddrinfo`, mirroring
`tests/conftest.py` + `tests/test_import_purity.py`) with `dotenv` faked to a
no-op so no real `.env` keys load.

## Near-misses / risks

- **Banner/report drift.** `_resolve_effective_coins` and the chains/categories
  string-splits duplicate `main()`'s inline transforms. They call the same *helper*
  functions, but the trivial `.split(',')` normalization is copied. If someone
  changes how `main()` parses `--chains`, the report could silently disagree.
  A future cleanup would extract one shared resolver that both `main()` and the
  report read — I did not attempt that refactor here because rewiring `main()`'s
  ~30 config globals is high-risk on the money-path file for a read-only feature.
- **INHERITED (unrelated to WS-6):** `tests/test_snapshot_lock.py` shows
  intermittent failures (2 of its thread/`flock`-timing tests) depending on
  collection set — reproduced with the WS-6 file *excluded*, then vanished on
  re-run of the same command. It uses `threading.Thread`/`Event` and real locks;
  the flakiness is pre-existing. The full real suite runs green at **959**.

## Test-pollution hardening (orchestrator flagged intermittent failures in my file)

The orchestrator reported a different subset of `test_print_config.py` failing on
different full-suite runs. I could not reproduce it in 7+ full runs (all 959
green, deterministic collection order, no `pytest-randomly`/`xdist`). Rather than
rely on non-reproduction, I hardened against every plausible shared-state vector,
since the builders read process-global state:

1. **`os.environ`** — `parse_args`' argparse defaults and `get_config_source`
   both read `os.environ`; `build_config_report` also reads `*_API_KEY` and
   `*_MODEL`. An autouse fixture now scrubs the FULL set of config-relevant env
   vars (`_CONFIG_ENV_VARS` + the `*_API_KEY`/`*_MODEL` patterns) before every
   test, so a leaked var from any other test / the shell / `.env` cannot shift a
   resolved value or source label. Verified: injecting `ANALYZE_COINS`,
   `LLM_MODE`, `OPENAI_API_KEY`, `CLAUDE_MODEL`, `POLYMARKET_FILTER` into the
   process env still yields 15/15.
2. **`executionledger.EXECUTIONS_FILE` module global** — `build_plan_lines` /
   `_instance_lock_held` derive the lock path + history dir from it. The autouse
   fixture redirects it to a per-test `tmp_path`, so no in-process test touches
   shared ledger/lock state or the owner's real `./history/` (the lock probe
   would otherwise read `./history/bot_instance.*.lock`).
3. **cwd** — my tests never `chdir`; subprocess tests pass `cwd=REPO_ROOT`
   explicitly and isolate all writes under `HISTORY_DIR=tmp_path`.
4. **Outbound** — every mutation is via `monkeypatch` (auto-restored); the
   builders assign no `bot` module globals, so this file cannot pollute others.

`monkeypatch` restoration + the autouse scrub make each test hermetic in both
directions. Confirmed green in targeted adversarial orderings (my file placed
right after `test_trade_gate`/`test_run_summary`/`test_snapshot_lock`, which
mutate `bot` globals and ledger paths, and placed before `test_snapshot_lock`).
Most likely the orchestrator's observation was either the pre-existing
`test_snapshot_lock` thread-timing flakiness mis-attributed, or another agent
concurrently mutating shared modules in the same working tree during its run.

## Test delta

`tests/test_print_config.py`: +15 tests (10 in-process builder tests, 5
subprocess end-to-end). Suite: 940 → **959**, all green. Import stays silent /
side-effect-free (`test_import_purity.py` still passes).
