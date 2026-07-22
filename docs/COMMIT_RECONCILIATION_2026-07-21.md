# Commit reconciliation — cycles 1+2 combined (2026-07-21, session close)

**Why this file exists:** the working tree carries TWO uncommitted improvement
cycles whose changes are interleaved in shared files. The per-cycle commit maps
(`docs/COMMIT_PROPOSAL_2026-07-21_cascade_followup.md` and
`docs/COMMIT_PROPOSAL_2026-07-21_cycle2.md`) describe each cycle's *content*
accurately, but they CANNOT be executed independently as written: house rules
require whole-file staging (no hunk staging), and e.g. `crypto_trading_bot.py`
now contains cycle 1's Polymarket fix AND cycle 2's instance lock in one file.
Staging that file for a "cycle 1" commit would silently carry cycle 2 along.

This file is the executable partition: **every dirty path assigned to exactly
one commit**, reconciled against `git status --porcelain -uall` at session
close (70 paths; suite **1093 passed**; `git stash list` empty; import purity
verified). Read the two cycle proposals for per-change rationale and review
flags; use THIS file for staging.

## Recommended consolidated sequence (6 commits)

Per-commit procedure (AGENTS.md): stage listed files only → run
`./scripts/check_staged_hygiene.sh` → read the staged diff → fresh full suite →
owner yes → commit (imperative subject ≤50 chars, no attribution lines).
Money-path commits (1, 3) first so they stay reviewable.

### Commit 1 — ledger correctness + instance lock (money-path adjacent)
> Lock ledger reads-that-persist; add instance lock

- `executionledger.py`
- `tests/test_snapshot_lock.py`
- `tests/test_instance_lock.py`

Note: the `main()`-side guard (`acquire_instance_lock_or_exit`) lives in
`crypto_trading_bot.py` → commit 3. Tests in this commit exercise the
executionledger half plus the guard function; if the suite-at-this-commit
discipline matters to you, run the suite only after commit 3, or reorder 3
before 1 — both files are internally consistent in the working tree.

### Commit 2 — analyzer evidence loop + HOLD counterfactuals
> Add analyzer attribution, calibration, HOLD counterfactuals

- `tradeanalyzer.py`  (cycle 1 WS4: per-provider attribution, policy
  counterfactuals, calibration + cycle 2 WS-3: `hold_class`, STATE_VERSION 4)
- `tests/test_analyzer_ws4.py`
- `tests/test_hold_counterfactual.py`
- `tests/test_analyzer.py`

### Commit 3 — core bot: fixes, schema v2, observability, config (the big one)
> Fix polymarket bypass; add schema v2, observability, config

Carries BOTH cycles for these files (enumerate in the body): cycle 1 —
Polymarket/santiment bypass fix, excluded-coins append fix, schema-v2 records
(vote_details/prompt_hash/models/market_block sidecars), `--quiet`,
`--json-summary`, `EXCLUDE_COINS`; cycle 2 — instance-lock guard +
`--allow-concurrent`, `--print-config`/`--plan`, `data_quality`,
`market_block_hash`, bid/ask/`spread_pct`, `--deterministic-sampling`,
`--discovery-universe` (+ fail-closed env validation, all-provider phrase
pass-through).

- `crypto_trading_bot.py`
- `historyutil.py`
- `sampling.py`
- `claudeutil.py`, `openaiutil.py`, `grokutil.py`, `perplexityutil.py`
- `tests/test_polymarket_santiment_interaction.py`
- `tests/test_schema_v2.py`
- `tests/test_exclude_coins.py`
- `tests/test_run_summary.py`
- `tests/test_trade_gate.py`
- `tests/test_print_config.py`
- `tests/test_data_quality.py`
- `tests/test_discovery_universe.py`
- `tests/test_ws5_bid_ask_sampling.py`
- `tests/test_structured_requests.py`

### Commit 4 — cross-process rate limiting
> Add cross-process rate limiting and TTL cache

- `ratelimit.py`
- `marketdata.py`
- `tests/test_rate_limit.py`
- `tests/conftest.py`  (state-dir isolation fixture)

### Commit 5 — scripts + logging hygiene
> Add research scripts; fix module-level logging config

- `scripts/promote_research_run.py` + `tests/test_promote_research_run.py`
- `scripts/run_experiment.py` + `tests/test_experiment_runner.py`
- `fibonacci_analyzer.py`, `correlation_tracker.py`,
  `leading_indicator_tester.py`  (basicConfig import-purity fixes)
- `tests/test_import_purity.py`

### Commit 6 — docs, design specs, reflections, config
> Record cycle 1+2 docs, designs, reflections

- `AGENTS.md`, `README.md`, `OPERATIONS_MANUAL.md`, `.gitignore`,
  `docs/RUNBOOK_whatif_cadence.md`, `docs/MERGE_PROPOSAL_josh_to_main.md`
- `docs/INVARIANTS.md`, `docs/RECORD_SCHEMA.md`
- `docs/IMPROVEMENT_PLAN_2026-07-20.md`,
  `docs/COMMIT_PROPOSAL_2026-07-21_cascade_followup.md`,
  `docs/COMMIT_PROPOSAL_2026-07-21_cycle2.md`, this file
- `docs/design/` (all four: PORTFOLIO_AWARENESS, PROMPT_CONTRACT_V2,
  SELL_EXIT_LIFECYCLE, SPREAD_GATE)
- `docs/reflections-2026-07-21/` and `docs/reflections-2026-07-21b/` (all)

## Deliberately EXCLUDED from all commits (owner decisions pending)

1. `EVALUATION_LESSONS_LEARNED_2026-07-18.md` — the modification includes the
   **owner's own edit** predating cycle 1 (flagged in the cycle-1 proposal).
   Confirm contents before staging; it can ride in commit 6 if approved.
2. `scripts/backfill_trading_mode.py` + `scripts/backfill_trading_mode_mapping.md`
   — GV-5 run/track/discard decision still pending (see merge proposal §6.4).

## Verification at commit time (fresh, don't trust this doc's numbers)

```bash
git status --porcelain -uall        # must match this file's universe (+ nothing new)
./venv/bin/python -m pytest tests/ -q   # expect 1093 passed at session close
./venv/bin/python -c "import crypto_trading_bot"   # silent
```

After all commits: `git status` clean except the two excluded items above;
then the merge proposal (`docs/MERGE_PROPOSAL_josh_to_main.md`, incl. the
2026-07-21 addendum) governs the josh→main merge.
