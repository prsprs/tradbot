# Tradbot Audit Eval — 2026-07-19

**Purpose:** a full-repo evaluation across programming practices, structure, business logic, LLM/API usage, logging, testing, documentation, readability, simplicity, and devops — written so a later AI session can convert it directly into an actionable improvement plan. This document is the synthesis; the raw per-dimension reports (with fuller evidence) are in [dimensions/](dimensions/) and the adversarial cross-check is in [CRITIQUE.md](CRITIQUE.md).

**Not applied:** this audit changed no code. Nothing here is committed work; every fix is a proposal.

**Follow-up:** [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) is the owner-approved, phased implementation plan derived from this eval (approved 2026-07-19, not yet executed).

**Session outcome (2026-07-19, same day):** the approved plan in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) was executed through Phase 5 in this working tree (uncommitted; suite 723 passed, up from the 616 baseline). Every finding below now ends with an **Outcome (2026-07-19 session)** line: fixed / partially fixed / deferred-by-plan / owner-decision-pending. Removals and intentional behavior changes are recorded in [../SUPERSEDED.md](../SUPERSEDED.md); the owner-facing merge briefing is [../MERGE_PROPOSAL_josh_to_main.md](../MERGE_PROPOSAL_josh_to_main.md).

---

## How this audit was produced

Eleven specialist auditor agents ran in parallel, each on one dimension, followed by a completeness critic that (a) spot-verified the most consequential findings against the code, (b) hunted for dimensions the team missed, and (c) flagged overstated or double-counted findings. Models: Fable 5 for business-logic design, MVP-scope judgment, and the critic; Opus 4.8 for the money-path bug hunt, LLM/API usage, code quality, testing, documentation triage, and devops; Sonnet 5 for structure, logging, and newcomer experience. ~1.55M tokens of audit work, 373 tool uses, all read-only (no live runs, no trades, no paid API calls).

Every finding below carries file:line evidence an auditor personally read. **Status labels:** `verified` = the critic independently re-read the cited code and confirmed; `corroborated` = found independently by 2+ auditors; `single-report` = one auditor, evidence cited but not re-checked; `already-documented` = AGENTS.md or the acceptance results already record it as known. No finding contradicted an AGENTS.md empirically-verified gotcha — the critic called the finding set "unusually well-grounded."

## Baseline facts (as of 2026-07-19, branch `josh`)

- ~180 tracked files; ~40k lines of tracked Python; ~38k lines of markdown (1.5 MB of it at repo root).
- Test suite: **616 passed in ~2.85s** via `./venv/bin/python -m pytest tests/ -q` (run by the testing auditor during this audit). Re-run to re-baseline before any fix lands.
- Core money path (~10.9k lines incl. tests) is dwarfed by satellites: ~20.6k of 31.5k non-test Python lines belong to experiments dormant since May–June 2026.
- Working tree at audit time: modified `EVALUATION_LESSONS_LEARNED_2026-07-18.md`; untracked `scripts/backfill_trading_mode.py` + mapping doc (critic reviewed the backfill script: careful — idempotent, `--dry-run`, timestamped backup, unknowns honestly labeled; no defect found).

## Scorecard

| Dimension | Grade | One-line verdict |
|---|---|---|
| Consensus / trade-gate logic | **A−** | Genuinely fail-closed on every probed path; spec'd by ~60-case test file; adversarial bug hunt found no fail-open. |
| Ledger & persistence ring | **C** | The weak layer: fail-open corrupt-JSON load, no cross-process locking, no duplicate-order dedup, no backup story. |
| Learning loop (analyzer/history) | **C+** | Honest scoring design undermined by a naive-timestamp bug that skews and freezes at-maturity grades. |
| LLM/API usage | **B** | Model-ID discipline is exemplary; prompt text duplicated ~20×, no spend observability, preflight probes the wrong Claude client. |
| Testing | **B** | Fast, deterministic, well-fixtured suite — but bare `pytest` is a live-API landmine and the end-to-end buy path has zero coverage. |
| Logging | **B−** | Excellent greppable tag vocabulary on the decision path; zero `logging` module use, no timestamps, no rotation, no tracebacks. |
| Documentation (agent-facing) | **A−** | AGENTS.md / MODELS.md / OPERATIONS_MANUAL are accurate, dense, empirically grounded. |
| Documentation (human-facing) | **D** | README Quick Start literally fails on a clean shell; dead env var; the "core design doc" predates the entire safety model. |
| Repo structure & hygiene | **C+** | 37 root .md files, name-collision between `historyutil.py` and `history/`, gitignore denylist already leaked per-user data. |
| Scope / simplicity | **C** | MVP core is admirably small; 65% more satellite code than core, two satellites carry unguarded live-trading paths. |
| DevOps / reproducibility | **C+** | Integration code is disciplined; requirements floors are below what the code needs, no lockfile, no CI, no cadence alerting. |

## Headline conclusions

1. **The consensus core is sound and the satellites are not.** Nobody — including a dedicated adversarial bug hunt — found a fail-open in the vote/quorum/gate path. But `leading_indicator_tester.py` and `lp_arbitrage.py` accept `--trading-mode live` and can place real Jupiter swaps with **no** `LIVE_TRADING_CONFIRMED` interlock, no ledger, and no caps (MP-4). The repo's signature safety posture exists only in `crypto_trading_bot.py`.
2. **The persistence ring around the consensus core is the weak layer.** Three auditors independently converged on it: corrupt-JSON loads fail open and silently wipe the ledger + reset the daily cap (MP-2); concurrent runs do lock-free read-modify-write on the files the daily cap depends on, plus a check-then-write TOCTOU on the cap itself (MP-3); and the empirically-documented Coinbase duplicate-order signal is implemented nowhere, so duplicates double-count positions (MP-1).
3. **The learning loop is being fed corrupted grades.** `tradeanalyzer.py` commits the exact naive-`.timestamp()` sin AGENTS.md documents as a past 4-hour bug: every at-maturity grade is offset by the machine's UTC offset over mismatched windows, then frozen by sidecar state (DI-1). Whatif is also a systematically optimistic predictor of live (MP-6). For a live-day-one posture with whatif as the data engine, this tier matters nearly as much as Tier 0.
4. **Bare `pytest` is a landmine — the most replicated finding (4 of 11 auditors).** No pytest config exists; bare `pytest` collects root probe scripts, one of which makes an authenticated Coinbase call *at import time*, and two of which are collectible real-swap functions sitting outside the network guard. One `pytest.ini` plus three renames fixes it.
5. **Documentation is split-brain.** Agent-facing docs are excellent; the human-facing entry path (README Quick Start, .env.example header, CRYPTO_TRADING_BOT.md) is factually wrong on the money credential, the venv, and the safety model.
6. **Per-user data has already leaked into git history** (critic finding, missed by all 11 auditors): `history/recommendations.json` and `live_trades/` files were tracked for months and only untracked recently — `git rm --cached` removed them from the tree, not from history. `history/llm_compare_history.json` is *still tracked* and re-accumulates real prompts/responses. This needs an owner decision before the repo is ever pushed or shared (GV-1, ST-1).

---

## Consolidated findings

Duplicate write-ups across auditors are merged here (the critic identified the overlaps); the per-dimension reports keep the originals. Severity: **critical** = could lose money or corrupt real data; **high** = materially wrong behavior or major maintenance hazard; **medium** = real friction; **low/info** = polish. Effort: S < 1 day, M = 1–3 days, L = larger/staged.

### A. Money path & ledger integrity (MP)

**MP-1 · HIGH · M · verified, corroborated** — The live-validated Coinbase duplicate shape (`success:true` + original `order_id`) is detected nowhere on the write path; duplicate buys double-count positions and cap tallies.
`coinbaseutil2.py:222-243` recovery runs only on exception/failure; the duplicate takes the normal success path and `buy_something` (`crypto_trading_bot.py:1596-1606`) appends a fresh fill row unconditionally — `OrderResult.idempotent_reuse` is consumed only by a log line (`coinbaseutil2.py:530`). `positions_from_rows` (`executionledger.py:250-262`) sums per fill row with no order_id dedup. Concrete triggers: `--coins=BTC,ETH,BTC` is not deduplicated (`crypto_trading_bot.py:2077` — discovery mode *does* dedup); RUN_ID has 1-second granularity (`:2028`). Calibration (critic): Coinbase's own idempotency prevents double-*spend*; the damage is corrupted real per-user ledgers and a poisoned base for any future SELL sizing. **Fix:** dedupe `ANALYZE_COINS` via `dict.fromkeys`; add a short random RUN_ID suffix; before `record_fill`, check the ledger for the returned order_id and record duplicates with a `duplicate_of` field; make `positions_from_rows` and the daily-cap sum count each distinct order_id once.
**Outcome (2026-07-19 session):** **Fixed** (trimmed per plan): coins deduped (`parse_analyze_coins`), random `RUN_ID` suffix (`new_run_id`), `record_fill` marks repeat order_ids `duplicate_of` under one lock hold, `positions_from_rows` and the cap sum count each real order_id once; pinned by `tests/test_execution_ledger.py`. Intent-sum rework deferred (see MP-10).

**MP-2 · HIGH · S · verified, corroborated (3 auditors)** — Corrupt ledger/history JSON fails open: load returns `[]` on `JSONDecodeError`, the next append silently rewrites the file (wiping all rows), and the daily cap reads through the same path so it resets to $0.
`executionledger.py:79-89` (load) + `:109-114` (append) + `:353-367` (cap); identical pattern in `historyutil.py:45-72`, which also lacks the atomic tmp+`os.replace` write. The warning line is untagged (`"Warning: ..."`), invisible to anyone grepping the repo's own `[TAG]` vocabulary. This is the fail-open class the repo's core invariant forbids, on the one cap that spans runs. **Fix:** fail closed — raise on unreadable ledger and treat it as a refused buy; rename the bad file to `executions.json.corrupt-<ts>` instead of overwriting; make `daily_cap_would_exceed` fail closed; give historyutil the atomic-write pattern; tag the error `[LEDGER ERROR]`.
**Outcome (2026-07-19 session):** **Fixed**: `load_executions` raises `LedgerError` on corrupt/wrong-shape files, `.corrupt-<ts>` quarantine (never deleted), live auto-restore from the newest `.bak-` snapshot else the buy is refused with a copy-paste recovery command; historyutil got atomic tmp+`os.replace` writes + quarantine; tagged `[LEDGER ERROR]`/`[HISTORY ERROR]`; OPERATIONS_MANUAL.md 'Ledger recovery'; pinned by `tests/test_execution_ledger.py`.

**MP-3 · HIGH · M · verified (critic-extended)** — No cross-process locking on `executions.json`/`recommendations.json`, and the daily cap has a check-then-write TOCTOU even with zero lost rows.
`_append_row` is load→append→replace with no lock (`executionledger.py:109-114`); `save_recommendation` likewise (`historyutil.py:62-72`). The whatif-cadence runbook points cron runs at the **real** history dir (`docs/RUNBOOK_whatif_cadence.md:30-36,133`) and runs take minutes, so overlap is realistic: last writer wins and rows the daily cap depends on vanish silently. Critic extension: `daily_cap_would_exceed` (read, `crypto_trading_bot.py:1639`) and `append_intent` (write, `:1561`) are separate unlocked steps — two overlapping live runs can both read under-cap and both order. **Fix:** `fcntl.flock` on a sibling lock file — held from load through `os.replace` in both writers, **and** spanning check-through-append at the `maybe_execute_buy` level for the live daily cap.
**Outcome (2026-07-19 session):** **Fixed**: reentrant cross-process `fcntl.flock` sibling-lock (`executionledger._FileLock`/`file_lock`) inside `_append_row` and `save_recommendation`, and held in `maybe_execute_buy` from the daily-cap read through the intent write (TOCTOU closed); deadlock rule (never nest the two locks) documented at both sites.

**MP-4 · HIGH · S · verified, single-report (under-replicated per critic)** — Two satellite tools are independent live-money entry points without the double-lock interlock.
`leading_indicator_tester.py:4827-4830` accepts `--trading-mode live (real swaps)` gated only by its own pair-viability preflight (`:5397-5426`); `lp_arbitrage.py:1283-1328` executes live with only a wallet-key check. Zero `LIVE_TRADING_CONFIRMED` occurrences in either (grep-verified by critic). Neither writes to the execution ledger nor respects any spend cap. The only finding class where real money can move without the repo's signature interlock. **Fix (stopgap, ~15 lines each):** refuse `live` unless `LIVE_TRADING_CONFIRMED=1`, mirroring `resolve_trading_mode`'s downgrade notice — or archive the tools (SC-1, owner decision).
**Outcome (2026-07-19 session):** **Fixed**: both satellites now require `LIVE_TRADING_CONFIRMED=1` for live mode, downgrading to paper (`leading_indicator_tester.py`) / whatif (`lp_arbitrage.py`) with a loud `[LIVE LOCK]` banner.

**MP-5 · MEDIUM · S · verified** — The voting panel is `COMPARE_LLMS` only: a `PRIMARY_LLM` outside it is preflighted, paid for, and silently discarded from the tally, while `get_active_llm_panel` (used by preflight, `crypto_trading_bot.py:1872-1877`) *does* include the primary — so live mode can hard-exit over a model whose vote can never count. **Fix:** build the panel as `dedupe([PRIMARY_LLM] + COMPARE_LLMS)` or refuse/warn loudly at startup; update `tests/test_consensus.py`.
**Outcome (2026-07-19 session):** **Fixed as warn-only** (owner decision): `warn_if_primary_off_panel` prints a startup `[CONFIG WARNING]`; consensus math unchanged; pinned by `tests/test_primary_panel_warning.py`.

**MP-6 · MEDIUM · M · verified** — Whatif diverges from live in three optimistic directions: simulated fills price at mid/last with `fees_usd=None` (no spread; `crypto_trading_bot.py:1513-1527,1572-1575`), the daily cap is checked only when `not WHATIF_MODE` (`:1639`), and the exclusion list is live-only (`:1654`). The whatif stream — explicitly the analyzer's data engine — overstates achievable live performance and contains trades live could not have made. **Fix:** simulate the daily cap from whatif intent rows; apply `coinsToExclude` in both modes; record estimated fees (or an analyzer-side spread haircut) on simulated fills.
**Outcome (2026-07-19 session):** **Fixed**: exclusion list applies in BOTH modes before any budget commit; whatif enforces the daily cap from whatif intent rows (soft-fail); simulated fills record estimated fees (`fees_usd` + `fees_estimated=True`) while `status='simulated'` stays the honest label.

**MP-7 · MEDIUM · L · already-documented** — BUY-only execution: consensus SELL writes a history record and nothing else (`market_order_sell` has zero callers, `coinbaseutil2.py:485-491`; gate fires only on `'BUY'`, `crypto_trading_bot.py:2450/2584`). Exposure grows without bound (~$450/month at default caps); manual exits desync attributed positions until `scripts/reconcile_positions.py` runs. **Interim fix:** print a loud `[NO SELL PATH]` line when a SELL consensus is dropped; the real SELL path is a separate, owner-scoped feature that must ride the same fail-closed machinery.
**Outcome (2026-07-19 session):** **Interim fix landed**: `gate_and_maybe_buy` prints `[NO SELL PATH]` when a gate-passing SELL is dropped; the real SELL path remains owner-scoped future work.

**MP-8 · LOW · S · already-documented (acceptance issue #2, still open)** — Daily-cap refusals are absent from the run-summary tally: the `[DAILY CAP]` branch returns before `spend_tracker.blocked` is touched (`crypto_trading_bot.py:1639-1644` vs `:2618`). **Fix:** distinct counter + its own summary line.
**Outcome (2026-07-19 session):** **Fixed**: `daily_cap_blocked` counter + its own run-summary line ('Blocked by daily cap: N', whatif-annotated).

**MP-9 · LOW · S · verified (reframed by critic)** — Run-cap budget is committed before the exclusion check (`crypto_trading_bot.py:1647-1658`), so an excluded coin burns notional headroom with no order. (The coin appearing in `coinsToBuy` is documented intent per the inline comment — the ordering of the budget commit is the real issue.) **Fix:** move the exclusion check above `try_spend`.
**Outcome (2026-07-19 session):** **Fixed**: the exclusion check is now step 0 of `maybe_execute_buy`, before the daily-cap read and `try_spend`.

**MP-10 · LOW · M · single-report** — Daily-cap contract ambiguity: every live intent row counts (even clean-failed orders) and fees are excluded, so the cap both over-blocks after failures and under-bounds actual account debits. **Fix:** decide and document the contract; recommended: skip intents whose latest fill is a clean `failed`, note fees are excluded in `--daily-spend-cap-usd` help.
**Outcome (2026-07-19 session):** **Partially fixed**: the contract is now documented in the `--daily-spend-cap-usd` help text (failed intents count, `duplicate_of` attempts excluded, fees excluded); the skip-clean-failed-intents sum rework is deferred by plan.

**MP-11 · INFO · S · spec'd policy** — Quorum floor is an absolute 2 regardless of panel size; with `REQUIRE_CONSENSUS=false`, an N-panel can trade on exactly 2 surviving voters — which can be grok+perplexity, the two fallback-parser providers. Within stated policy (`REQUIRE_CONSENSUS` defaults true) and pinned by tests, but the AGENTS.md invariant phrasing overpromises. **Fix:** startup notice when consensus is disabled; align AGENTS.md wording.
**Outcome (2026-07-19 session):** **Deferred-by-plan** ('polish; none protects money') — no startup notice, AGENTS.md wording unchanged.

### B. Learning-loop data integrity (DI)

**DI-1 · HIGH · S · verified** — `tradeanalyzer.py:383` computes `when.timestamp()` on a naive-UTC datetime — the exact trap AGENTS.md:23 documents as a past real 4-hour bug (fixed in `lp_history.py`, not here). On a non-UTC machine every at-maturity candle lookup is hours off, the coin-return and benchmark-return windows are mismatched, and wrong verdicts are frozen permanently by sidecar state (`tradeanalyzer.py:654-665`). **Fix:** `when.replace(tzinfo=timezone.utc).timestamp()`; regression test with a non-UTC TZ; bump `STATE_VERSION` to re-score frozen verdicts.
**Outcome (2026-07-19 session):** **Fixed**: `tradeanalyzer.utc_epoch` (named, tested helper), `STATE_VERSION` 2→3 so frozen wrong verdicts re-score once, TZ-independence regression tests in `tests/test_analyzer.py`; AGENTS.md timestamp contract updated to mandate the helper.

**DI-2 · MEDIUM · S · single-report** — Analyzer candle cache is keyed `(coin, granularity)` ignoring the lookback span, and the nearest-candle lookup has no max-distance guard (`tradeanalyzer.py:371-385`) — out-of-window records silently grade against the window edge while stamped `AT_MATURITY`. **Fix:** include the span in the cache key; return None when the nearest candle is > ~1.5× granularity from target so scoring degrades honestly.
**Outcome (2026-07-19 session):** **Fixed**: candle cache key now `(coin, granularity, days)`; nearest-candle lookups >1.5× granularity from target return None so records degrade honestly.

**DI-3 · MEDIUM · S · verified** — `record_recommendation` returns None when the price fetch fails (`historyutil.py:284-289`), silently dropping decisions — including blocked ones — despite call-site comments promising "ALWAYS recorded"; discovery-produced unlisted tickers hit this every time. Stored bid/ask are fabricated copies of last price (`historyutil.py:236-240`). **Fix:** record with `price/bid/ask = None` on fetch failure (analyzer already maps missing rec_price to `EXPIRED_UNSCORABLE`); never copy price into bid/ask.
**Outcome (2026-07-19 session):** **Fixed**: `record_recommendation` writes the record with `price/bid/ask = None` on fetch failure; bid/ask are never fabricated from last price; candidate export failures can no longer lose a saved record.

**DI-4 · MEDIUM · S · critique gap** — No backup/durability story for `history/`: each user's money records are one JSON file, on one machine, never versioned (correctly gitignored), with a demonstrated silent-wipe path (MP-2). **Fix:** run-start snapshot (`executions.json.bak-<date>`, ~5 lines — the `.bak-*` gitignore pattern already exists) plus the `.corrupt-<ts>` rename from MP-2.
**Outcome (2026-07-19 session):** **Fixed**: run-start `snapshot_ledger()` writes `executions.json.bak-<date>` (idempotent per UTC day, non-fatal, skipped for corrupt ledgers) and doubles as MP-2's auto-recovery source.

### C. Testing infrastructure (TS)

**TS-1 · HIGH · S · verified, corroborated (4 auditors)** — Bare `pytest` is unsafe and broken: with no pytest config anywhere, root collection (a) imports `test_coinbase.py`, which runs an **authenticated `client.get_accounts()` Coinbase call at module top level** during collection; (b) collects `test_with_private_key`/`test_sell_with_private_key` (`test_trustwallet_swap.py:267,593`) — real-swap flows guarded only incidentally by pytest's stdin capture; (c) crashes on `lab/session_tests_20260718/` snippet files; (d) none of this is covered by `tests/conftest.py`'s network guard, which is scoped to `tests/`. Also `tests/generate_multi_pair_test.py` matches the `*_test.py` glob. Critic note: AGENTS.md:32's "full `pytest`" most plausibly means "the full suite," so drop the self-contradiction framing — but the empirical hazard is triple-confirmed. **Fix (one commit):** `pytest.ini` with `testpaths = tests` and `norecursedirs = lab venv scripts`; rename the three root probes to `probe_*.py` (zero importers, grep-verified) and the two lab snippet files off the `test_` prefix; rename `generate_multi_pair_test.py`; clarify AGENTS.md:32 to `pytest tests/ -q`.
**Outcome (2026-07-19 session):** **Fixed**: `pytest.ini` (`testpaths = tests`, norecursedirs), the three root probes renamed `probe_*.py`, lab snippets renamed `_*_snippet.py`, `generate_multi_pair_data.py`, AGENTS.md:32 now says `pytest tests/ -q`; bare `pytest --collect-only -q` verified to yield only tests/ nodes (723).

**TS-2 · HIGH · M · single-report** — The end-to-end buy path has zero coverage: `maybe_execute_buy` (daily cap → run cap → exclusion → dispatch) is referenced by no test, and the gate→execute wiring is duplicated verbatim at `crypto_trading_bot.py:2450-2451` and `:2584-2585` inside the untested `main()`. Every leaf is tested; the assembly is not — an agent can reorder the cap checks or change one of the two call sites and keep all 616 tests green. This is the highest-consequence silent-regression class in the repo. **Fix:** extract one `gate_and_maybe_buy()` helper used by both loops; add a focused test (monkeypatched globals, stubbed `buy_something`) asserting cap refusals, exclusion behavior, and exactly-once dispatch.
**Outcome (2026-07-19 session):** **Fixed**: single `gate_and_maybe_buy()` wiring used by both loops; `tests/test_trade_gate.py` pins cap refusals, exclusion, SELL drop, and exactly-once dispatch.

**TS-3 · MEDIUM · S · single-report** — The load-bearing "import crypto_trading_bot is side-effect-free" invariant is unpinned by any test, and the function-scoped network guard is structurally blind at collection/import time. Relatedly, `load_dotenv()` runs at module scope (`crypto_trading_bot.py:16-17`), already mildly violating the invariant (CQ-4). **Fix:** subprocess-based import-purity test (no stdout, no sockets); move `load_dotenv()` into `main()`.
**Outcome (2026-07-19 session):** **Fixed**: subprocess import-purity test (`tests/test_import_purity.py`); `load_dotenv()` moved into `main()` with `_refresh_env_snapshots()` re-resolving every import-time env snapshot in the bot's import graph.

**TS-4 · INFO · S · already-documented** — `block_reason` vocabulary exists only as scattered string assertions in `tests/test_consensus.py` (intentional per AGENTS.md:109). Optional: a module-level frozenset referenced by emit sites and tests, keeping composed text free-form.
**Outcome (2026-07-19 session):** **Deferred** (optional per the finding; scattered-assertion vocabulary intentional per AGENTS.md).

### D. LLM / AI API usage (LM)

**LM-1 · MEDIUM · S · verified (critic downgraded from HIGH: fails closed)** — Preflight probes a different Claude client than the money path: `llmpreflight.py:112-113` probes `llm_utils.ClaudeClient` (accepts `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY`) while `claudeutil.ClaudeTrader` requires `CLAUDE_API_KEY` only (`claudeutil.py:27-29`) — so a green preflight can precede a full run of standing abstains. Inverse divergence exists for Gemini. The preflight docstring's "real signal that the production code path works" is false for Claude. **Fix:** accept both env vars in `claudeutil`; longer-term, preflight the actual money-path classes; add a regression test that preflight and trader agree on env vars per provider.
**Outcome (2026-07-19 session):** **Fixed**: `claudeutil` accepts `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY`; `llmpreflight.py` rewritten to probe the actual money-path trader classes (plus a literal `genai.Client()` mirror; the Claude schema probe uses `claudeutil._claude_output_config()` directly); `tests/test_model_registry.py` reworked accordingly.

**LM-2 · HIGH · M · corroborated (3 auditors)** — The core analysis prompt exists in ~20 verbatim copies across 5 files (`claudeutil.py`, `openaiutil.py`, `grokutil.py`, `perplexityutil.py`, inline Gemini in `crypto_trading_bot.py:510-643`), the discovery prompt in 8; `get_llm_response` adds five near-identical dispatch branches (~110 lines). Prompt edits — the highest-frequency change class in an LLM trading bot — are 5-file, up-to-20-site edits, and drift means panelists get asked subtly different questions (a consensus-correctness hazard; the dex-mode discovery prompts have already diverged). Adding a 6th provider touches ~10 sites. AGENTS.md documents the llm_utils stack split but **not** this in-money-path duplication. **Fix:** `panelprompts.py` with 4 builder functions (coin_check, trend_check, integrated variants) taking `(coin_symbol, coin_type, market_block, trends_data, peer_analysis)`; all 5 call sites keep only SDK plumbing; then collapse the dispatch to a `{provider: trader}` registry. Do **not** couple this to full two-stack unification.
**Outcome (2026-07-19 session):** **Fixed (builders only, per plan)**: new `panelprompts.py` with the 4 builder functions; all 5 call sites keep only SDK plumbing; inter-provider drift preserved via parameters, byte-identity pinned by golden tests (`tests/test_panel_prompts.py` + fixtures). Dispatch-registry rewrite deferred.

**LM-3 · MEDIUM · M · single-report** — No LLM-spend observability or ceiling anywhere on the money path: up to 5 providers × 2 rounds per coin, output-uncapped on Gemini/Grok (deliberately, per the reasoning-model gotcha), no call site reads `response.usage`, and the only cost code (`config.estimate_cost`) serves llm_compare with stale flat rates. **Fix:** capture per-provider usage fields (documented in MODELS.md appendix) into a per-coin/per-run tally line; optional per-run LLM-spend cap mirroring the trade caps.
**Outcome (2026-07-19 session):** **Deferred-by-plan** ('revisit when API bills matter').

**LM-4 · MEDIUM · M · partially already-documented** — Grok/perplexity remain on the delimiter fallback whose concluding-tag rule abstains if *any* letter follows the final tag (`crypto_trading_bot.py:794-797`) — yet these are the two web-search providers most likely to trail citations, and the rule was validated on only 8 responses. Structured output is probe-verified working for both (fixtures exist). Fails closed but silently degrades the configured panel. **Fix:** adopt native structured output for both (fixtures already in `tests/fixtures/structured_output/`), or tolerate a trailing citations block; add trailing-prose fixtures either way.
**Outcome (2026-07-19 session):** **Deferred-by-plan** (fallback fails closed; migration adds probe risk for modest gain).

**LM-5 · MEDIUM · S · single-report** — Fail-open legacy consensus helpers are imported into the money-path module: `crypto_trading_bot.py:23` imports `compare_recommendations`/`get_consensus_action` (zero call sites); the latter returns the Gemini vote as a single-model fallback — exactly the behavior the core invariant forbids, one grep away from being rewired by a future agent. **Fix:** delete both from `claudeutil.py` and the import (confirm no test dependency first).
**Outcome (2026-07-19 session):** **Fixed**: both helpers deleted from `claudeutil.py` and the bot import shrunk; supersession recorded in `docs/SUPERSEDED.md` (the fail-open single-model fallback is the one capability intentionally dropped, owner-approved).

**LM-6 · LOW · S · corroborated (2 auditors)** — No explicit timeouts on any LLM call (SDK defaults ~600s); every HTTP data integration sets one explicitly. A hung provider stalls scheduled runs ~10 min/call. **Fix:** `timeout=60–120s` at client construction for all four SDK clients + the genai call.
**Outcome (2026-07-19 session):** **Partially fixed**: `timeout=90` on the 4 SDK trader clients; the bot's inline Gemini `genai.Client()` still has no explicit timeout (plan scoped LM-6 to the four).

**LM-7 · INFO · — · single-report (ties to GV-4)** — Round-2 peer analysis embeds raw peer-LLM text (which may carry web-search content) into other models' prompts. Bounded: the vote is schema-constrained and symbol-bound, so injected text can influence reasoning but never forge a vote. **Fix:** document as an accepted bounded surface next to the marketdata injection note; optionally cap peer-text length.
**Outcome (2026-07-19 session):** **Fixed as documentation**: covered by the AGENTS.md accepted-bounded-surface paragraph (see GV-4), including the peer-text channel; no length cap added.

### E. Code quality (CQ)

**CQ-1 · HIGH · L · single-report** — `crypto_trading_bot.py` couples ~52 module-level globals to a 653-line `main()` (cyclomatic ~100); money-path functions read config from hidden module state set 700 lines away. This is the root cause of the "serialize all work on this file" rule and the blocker on the standing split refactor. **Fix (staged, in order):** (1) frozen `BotConfig` dataclass (mirror `config.py`'s existing pattern) threaded explicitly into `process_coin_with_comparison`/`get_llm_response`/the gate — behavior-preserving, guarded by `tests/test_consensus.py`; (2) only then extract the consensus core into `consensus.py` (best-tested unit moves first) and provider dispatch into a panel module; (3) discovery/wiring last; traders live in a passed registry dict. **Do not split files first.**
**Outcome (2026-07-19 session):** **Deferred-by-plan** (pure structural change; revisit when the file genuinely needs splitting).

**CQ-2 · MEDIUM · L · single-report** — Research-tool monoliths have ~900-line, CX>100 `main()`s (`leading_indicator_tester.py:4728`, `correlation_tracker.py:2413`) — effectively untestable. Lower priority than CQ-1 (off the money path); carve one command handler at a time only when next touched. (Superseded by SC-1 if the archive decision goes through.)
**Outcome (2026-07-19 session):** **Deferred-by-plan** (off the money path).

**CQ-3 · LOW · S · single-report** — The provider roster `['gemini','claude','openai','grok','perplexity']` is hardcoded in ~7 places across `crypto_trading_bot.py` and `config.py` while `modelregistry.MODEL_IDS` already holds the canonical set. **Fix:** export `PROVIDERS` from `modelregistry` and derive; keep `STRUCTURED_VOTE_PROVIDERS` explicit (genuinely different fact).
**Outcome (2026-07-19 session):** **Deferred-by-plan** (polish).

**CQ-4 · LOW · S · single-report** — Module-level `load_dotenv()` (`crypto_trading_bot.py:16-17`) contradicts the documented side-effect-free-import invariant; movable into `main()` with no behavior change. (Pairs with TS-3.)
**Outcome (2026-07-19 session):** **Fixed** (with TS-3): `load_dotenv()` now runs in `main()`; the side-effect-free-import invariant is true and pinned by `tests/test_import_purity.py`.

**CQ-5 · LOW · S · single-report** — `get_config_source` uses prefix matching over `sys.argv` (`crypto_trading_bot.py:301-308`) so the provenance banner can mislabel prefix-colliding flags. **Fix:** exact-token or `flag=`-prefix match.
**Outcome (2026-07-19 session):** **Deferred-by-plan** (polish).

**CQ-6 · LOW · S · single-report** — Bare `except:` clauses in `fibonacci_analyzer.py:1105` and `dex/jupiterutil.py:541-544` swallow `KeyboardInterrupt` and hide malformed oracle data silently. **Fix:** narrow to `except Exception` and log the swallowed error.
**Outcome (2026-07-19 session):** **Deferred-by-plan** (polish).

### F. Logging & observability (LG)

The tag vocabulary (`[BLOCKED]`, `[ABSTAIN]`, `[STRUCTURED VOTE]`, `[LEDGER]`, `[ORDER]`, `[DAILY CAP]`, `[LIVE LOCK]`, …) with per-panelist vote breakdowns is a genuine strength — a human can reconstruct any decision from stdout. The gaps:

**LG-1 · MEDIUM · S · single-report** — Full raw primary-LLM text is dumped unconditionally at two call sites (`crypto_trading_bot.py:2402,:2537`), bypassing the `LOG_INTEGRATION_ROUNDS` gate that the equivalent panelist dump already respects — bloating the unrotated cadence log. **Fix:** gate both sites behind the existing flag.
**Outcome (2026-07-19 session):** **Fixed**: both primary-text dumps gated behind `LOG_INTEGRATION_ROUNDS` (pinned by `tests/test_log_fixes.py`).

**LG-2 · MEDIUM · S · single-report** — 18 `except Exception as e: print(...)` blocks and zero `traceback` usage anywhere on the runtime path: an unattended run's only diagnostic for a real bug is `str(e)`. **Fix:** `traceback.print_exc()` (or `logging.exception`) at minimum on the two consensus-path handlers (`crypto_trading_bot.py:951-953,1396-1402`).
**Outcome (2026-07-19 session):** **Fixed at the two consensus-path handlers**: `traceback.print_exc()` added in `get_llm_response` and `process_coin_with_comparison` (block_reason strings unchanged); the remaining handlers were out of plan scope.

**LG-3 · MEDIUM · M · single-report** — Zero `logging`-module use on the runtime path: no per-line timestamps, no rotation story, while the runbook's cron examples append forever to one file — and `correlation_tracker.py:36-43` already demonstrates the `logging.basicConfig('%(asctime)s [%(levelname)s] …')` pattern in-repo. **Fix:** mechanical adoption preserving the bracket tags, plus per-run log files or rotation guidance in the runbook.
**Outcome (2026-07-19 session):** **Deferred-by-plan** (mechanical churn; the runbook's per-run log file suggestion covers the practical need).

**LG-4 · LOW · S · single-report** — Five untagged error prints in `coinbaseutil2.py` (`:229,:501,:147,:175,:565`) escape `[ORDER]`-grep monitoring. **Fix:** tag them `[ORDER]`/`[COINBASE]`.
**Outcome (2026-07-19 session):** **Fixed**: all five prints tagged `[ORDER]`/`[COINBASE]`.

**LG-5 · LOW · S · single-report** — `[FALLBACK PARSER]` fires on 100% of grok/perplexity calls (routing info, not anomaly signal), diluting the tag. **Fix:** one-time-per-run routing note; reserve the tag for outcome lines.
**Outcome (2026-07-19 session):** **Deferred** (not selected by the plan).

### G. Documentation (DX)

**DX-1 · HIGH · S · verified, corroborated (4 auditors)** — README Quick Start fails literally on a clean shell and is wrong about the money credential: no venv step (system python3 is 3.9 and lacks every dep), `export COINBASE_API_KEY=...` is read **nowhere** in the code, `cdp_api_key.json` (required even for whatif — `BlobbyTrader()` constructs unconditionally, `crypto_trading_bot.py:2264`) is never mentioned, and `.env.example:30`'s "required for live trading only" header says the opposite of the truth. **Fix:** rewrite the Quick Start (venv → `pip install` → copy `.env.example` → place `cdp_api_key.json` with the download URL → whatif run command with `./venv/bin/python`); fix the `.env.example` header.
**Outcome (2026-07-19 session):** **Fixed**: Quick Start rewritten (venv, pip install incl. `requirements_dev.txt`, `.env` copy, `cdp_api_key.json` requirement, `./venv/bin/python` run with `HISTORY_DIR` scratch); dead `COINBASE_API_KEY` line gone; `.env.example` header now says 'required even for what-if runs'.

**DX-2 · HIGH · M · single-report** — `CRYPTO_TRADING_BOT.md` — README-linked as the core design doc and the "start here" for new traders — predates the entire safety model (no double lock, whatif default, caps, fail-closed consensus, marketdata block; says GPT-4o and "Python 3.9+", opens with a `pl#` typo). **Fix:** rewrite the stale sections, or demote to `docs/design/` with a superseded banner and repoint README at AGENTS.md + OPERATIONS_MANUAL.md.
**Outcome (2026-07-19 session):** **Fixed**: demoted to `docs/design/CRYPTO_TRADING_BOT.md` with a superseded banner; README repointed at AGENTS.md + OPERATIONS_MANUAL.

**DX-3 · MEDIUM · M · corroborated (3 auditors)** — Root sprawl: 37 .md files / 1.5 MB with no tree-level signal separating current-reference from design-only (6 docs, 233 KB, zero backing code) from historical plans. Target layout (pure `git mv`; only cross-links need fixing — README already curates status tables): keep at root only `README`, `AGENTS`, `CLAUDE`, `MODELS`, `OPERATIONS_MANUAL`; `docs/features/` or `docs/design/` for feature specs; `docs/archive/` for historical plans; add one AGENTS.md line defining the convention.
**Outcome (2026-07-19 session):** **Fixed** (first pass): `docs/design/` + `docs/archive/` created, 11 root docs moved via `git mv`, README link tables updated, AGENTS.md docs-layout convention line added.

**DX-4 · MEDIUM · S · corroborated** — `Restore Directional Analysis.md` is a 407 KB / 10,197-line raw Windsurf chat transcript, referenced nowhere, leaking a prior owner's absolute paths. **Fix:** delete (git history preserves it) — owner sign-off since agents don't delete unasked.
**Outcome (2026-07-19 session):** **Fixed**: deleted (owner-approved at checkpoint; recoverable from git history).

**DX-5 · MEDIUM · M · single-report** — llm_compare is documented four times over; `LLMCompareFeature.md` hardcodes the retired `claude-sonnet-4-20250514` and an obsolete 2-LLM design. **Fix:** keep quick-start + ops manual as the live pair; move the two design docs to `docs/design/` with superseded banners; kill the dead model IDs. (Superseded by SC-2 if llm_compare is extracted.)
**Outcome (2026-07-19 session):** **Fixed**: both design docs moved to `docs/design/` with superseded banners; retired `claude-sonnet-4-20250514` references replaced with `modelregistry.py`/MODELS.md pointers; quick-start + ops manual remain the live pair.

**DX-6 · LOW · S · single-report** — README directory tree lists `paper_trades/` (doesn't exist), root name `tradingbot/` (old project name), and runtime-created dirs without marking them. **Fix:** update the tree; annotate runtime-created dirs.
**Outcome (2026-07-19 session):** **Fixed**: tree corrected (`tradbot/`, `live_trades/` added, `paper_trades/` note fixed, runtime-created dirs annotated).

**DX-7 · INFO · — · single-report** — AGENTS.md (19 KB) is at the healthy upper bound of one dense page; the two bullet-lists (API gotchas, process lessons) are the growth risk and partially restate MODELS.md. **Fix:** none now; when either list next grows, split gotchas into a linked doc and keep MODELS.md canonical for provider quirks.
**Outcome (2026-07-19 session):** **No action, by the finding's own recommendation** ('Fix: none now').

### H. Onboarding & readability (OB)

**OB-1 · MEDIUM · S · single-report** — A first-time user's first successful run silently writes into the shared `history/` directory: `HISTORY_DIR` is absent from `--help` (only an "etc." in the epilog) and from README, while AGENTS.md treats redirecting it as a hard rule for agents. **Fix:** add a `--history-dir` flag (or name `HISTORY_DIR` explicitly in the epilog) + one Quick Start line recommending a scratch dir for experimentation.
**Outcome (2026-07-19 session):** **Fixed**: `HISTORY_DIR` named explicitly in the `--help` epilog and recommended in the README Quick Start (no new CLI flag, per plan).

**OB-2 · MEDIUM · S · single-report** — `crypto_trading_bot.py` has no module docstring and no doc pointers; `main()` starts at line 1973 of 2629 after ~40 helpers — physical order is the reverse of reading order. **Fix (cheap, distinct from the CQ-1 refactor):** module docstring pointing at AGENTS.md's architecture map + section-boundary comments for searchability.
**Outcome (2026-07-19 session):** **Deferred** (not selected by the plan; the module still opens with imports, no docstring).

**OB-3 · LOW · S · single-report** — No architecture diagram anywhere; the only map is prose in an agent-framed doc. **Fix:** mermaid restatement of AGENTS.md:75's existing map in README.
**Outcome (2026-07-19 session):** **Fixed**: mermaid runtime-path diagram added to README, explicitly restating AGENTS.md's prose map.

**OB-4 · LOW · S · single-report** — `BlobbyTrader` is an opaque name for the class that places real-money Coinbase orders (and the `2` in `coinbaseutil2.py` is a dangling rename artifact). **Fix:** rename to `CoinbaseTrader` with a back-compat alias, or at least a docstring explaining the name.
**Outcome (2026-07-19 session):** **Fixed via docstring** ('This is the Coinbase trader; the name is historical'); the rename itself deferred-by-plan.

### I. Repo structure & hygiene (ST)

**ST-1 · HIGH · S · verified, corroborated (2 auditors + critic)** — `history/` gitignore is a drifting denylist: `history/llm_compare_history.json` is **tracked** and contains real accumulated prompt/response records (committed 2026-04-24, re-accumulates on every `llm_compare.py` run — `git add -A` republishes a user's query history); `check_staged_hygiene.sh`'s exception list disagrees with the gitignore (false alarms on `history/__init__.py`, blind to the real gap). Directly contradicts AGENTS.md hard rule #3's "the .gitignore enforces this." **Fix:** convert to allowlist (`history/*` + `!` entries for the tracked code/fixtures); `git rm --cached history/llm_compare_history.json`; derive the hygiene script's exceptions from the same list; give `history/recorder.py` the HISTORY_DIR-style env override its siblings already have.
**Outcome (2026-07-19 session):** **Fixed**: `history/*` gitignore allowlist; `llm_compare_history.json` untracked index-only (verified still on disk and now ignored); `check_staged_hygiene.sh` exception list aligned; `history/recorder.py` gained the `HISTORY_DIR` env override.

**ST-2 · HIGH · S · single-report** — Naming collision: `historyutil.py` (the live bot's history writer) vs the `history/` package (the unrelated llm_compare recorder) — an agent asked to fix "history recording" plausibly patches the wrong subsystem, and AGENTS.md documents the data/code mix but not this. **Fix now:** cross-reference docstrings in both. **Later:** rename one side (`historyutil.py` has exactly 3 importers — a bounded single-commit rename).
**Outcome (2026-07-19 session):** **Fixed (docstring half)**: cross-reference docstrings added to both `historyutil.py` and `history/recorder.py`; the rename deferred-by-plan.

**ST-3 · MEDIUM · L · single-report** — No package story for ~29 flat top-level modules; the 4 non-dex packages all belong to the llm_compare stack by accident. Proposed (explicitly phase-2, one module at a time with back-compat shims, starting from 0–1-importer modules): `bot/`, `providers/`, `analytics/`. Do not attempt during money-path work.
**Outcome (2026-07-19 session):** **Deferred-by-plan** (owner-deferred; revisit after this plan lands).

**ST-4 · MEDIUM · S · corroborated** — pytest (and all dev tooling) is absent from every requirements file — a fresh clone following the documented install cannot run the prescribed verify step. **Fix:** `requirements_dev.txt` with a pytest pin; reference it in AGENTS.md's Environment section.
**Outcome (2026-07-19 session):** **Fixed**: `requirements_dev.txt` (pytest pin) added and referenced in the README Quick Start (AGENTS.md Environment section not updated — minor residue).

**ST-5 · LOW · S · single-report** — Tracked zero-byte IDE artifact `.windsurf/workflows/g.md`; stale `.gitignore:64-67` comment describing a cleanup that already happened. **Fix:** delete the file (owner sign-off), rewrite the comment as resolved fact.
**Outcome (2026-07-19 session):** **Fixed**: `.windsurf/workflows/g.md` deleted (owner-approved); the stale `.gitignore` comment rewritten as resolved fact.

### J. DevOps & reproducibility (OPS)

**OPS-1 · HIGH · S · single-report** — Requirements floors are below what the money path actually calls: `anthropic>=0.18` (needs ≥0.94 for `output_config` — claudeutil's own comment says so) and `openai>=1.0` (needs ≥1.66 for the Responses API grok uses); no upper bounds, no lockfile. A second user's honest resolve can silently break 2 of 5 panelists (fails closed, but defeats the panel), and a future breaking major lands unnoticed. **Fix:** raise floors (`anthropic>=0.94`, `openai>=1.66`), cap the Coinbase SDK to the tested line, commit a `requirements.lock` (pip freeze) as the canonical install path.
**Outcome (2026-07-19 session):** **Partially fixed**: floors raised (`anthropic>=0.94`, `openai>=1.66`) and `coinbase-advanced-py>=1.8,<2` capped; no `requirements.lock` (not selected by the plan).

**OPS-2 · LOW · S · single-report** — `check_staged_hygiene.sh`'s secret regexes can't catch the DEX wallet secrets the repo actually reads (raw base58 Solana keys, 12/24-word mnemonics, unprefixed provider keys). **Fix:** add mnemonic/base58 heuristics + `*_MNEMONIC`/`SOLANA_PRIVATE_KEY`/`*_SEED` name matches; keep advisory.
**Outcome (2026-07-19 session):** **Fixed**: mnemonic-phrase, base58-length, and `*_MNEMONIC`/`*_SEED`/`SOLANA_PRIVATE_KEY` name heuristics added to the hygiene script (advisory, as recommended).

**OPS-3 · LOW · S · single-report** — `.env.example` omits the entire optional/experimental env surface (`COINGECKO_API_KEY`, `JUPITER_API_KEY`, `SOLANA_RPC_URL`, and the spendable `SOLANA_PRIVATE_KEY`/`WALLET_MNEMONIC`) and the accepted aliases (`CMC_API_KEY`, `ANTHROPIC_API_KEY`). **Fix:** commented optional block with a pointed never-commit warning on wallet material.
**Outcome (2026-07-19 session):** **Fixed**: optional DEX/data-provider block added with a loud never-commit wallet-secret warning; `CMC_API_KEY`/`ANTHROPIC_API_KEY` aliases documented.

**OPS-4 · INFO · M · single-report** — No CI and no cadence alerting: regressions reach other users only via manual discipline, and a crashing cron run silently stops feeding the analyzer. **Fix:** minimal GitHub Actions (or documented `make check`) running the suite + hygiene script; wrap the cron command to alert on non-zero exit or stale log. Keep consistent with the "don't install tooling on others' behalf" norm — propose, don't impose.
**Outcome (2026-07-19 session):** **Fixed (CI half)**: `.github/workflows/tests.yml` runs the suite on PRs and main pushes (hygiene script deliberately excluded — it inspects the staging index, vacuous in CI, reasoning documented in the workflow); cadence alerting deferred-by-plan.

### K. Scope & simplicity (SC)

**SC-1 · HIGH · M · single-report (owner decision)** — The correlation/leading-indicator universe (~10.6k lines, ~34% of non-test Python) is dormant since May–June, has zero pytest coverage except one class, is invoked by no documented workflow — and carries an unguarded live path (MP-4). Concrete archive plan: extract `FibTradeFilter`+`FibFilterResult` into `fibonacci_analyzer.py` (its only live dependency; update `tests/test_fibonacci_analyzer.py:37`), then `git rm` the tester, tracker, `preflight.py`, the two root swap probes, config yaml, its requirements file, and the orphaned fixture trees (SC-5) — optionally tagging `archive/correlation-universe` first. README advertises these as implemented, so owner sign-off is required.
**Outcome (2026-07-19 session):** **Owner decision executed as guard-now-archive-later**: the MP-4 interlock landed in both tools; archival (and SC-5's fixture cleanup) explicitly deferred.

**SC-2 · MEDIUM · M · already-documented wart (owner decision)** — The llm_compare parallel stack (2,066 lines across `llm_compare.py`, `llm_utils/`, `config.py`, `prompts/`, `context/`; zero tests; dormant since April; the 2026-07-18 registry retrofit proved the double-maintenance tax). Extraction to its own repo (with its 4 docs and the tracked history file) removes the "check both stacks" rule, half the provider-duplication problem, and the ST-1 tracked-data gap in one move. `modelregistry.py` stays.
**Outcome (2026-07-19 session):** **Resolved by owner reversal (KEEP in-repo)**: hygiene fixes landed via ST-1 (untrack, allowlist, `HISTORY_DIR` override) and LM-1 (preflight probes money-path classes); extraction is on the deliberately-not-doing list.

**SC-3 · MEDIUM · M · single-report (owner decision)** — `--dex` is a second, less-hardened exchange backend inside the money path: live DEX fills map straight to ledger rows with no fill-confirmation equivalent of the CEX path, `dex_mode` threads through every panelist's discovery surface, and no runbook ever passes it. **Fix:** remove the DEX branch from the bot (leaving `dex/` importable), or hard-refuse `--dex` + live until it gets the CEX hardening.
**Outcome (2026-07-19 session):** **Fixed as warn-but-allow** (owner choice): loud `[WARNING]` banner when `--dex` + armed live mode combine (DEX fills recorded unverified); functionality unchanged.

**SC-4 · LOW · S · single-report** — Satellite hooks in money-path modules: 4 of `record_recommendation`'s 20 parameters exist solely for the correlation satellite's CSV export; `coinbaseutil2.py:592` imports a data-provider filter into the exchange client. **Fix:** rides with SC-1; independently move the category filter up into `apply_coin_filters`.
**Outcome (2026-07-19 session):** **Deferred** (rides with the deferred SC-1 archival).

**SC-5 · LOW · S · single-report** — Orphaned fixture trees in `tests/` (`test_correlation_data/`, `test_multi_pair_data/`, two generators, ~900 lines + 16 data files) referenced by no pytest test. Rides with SC-1.
**Outcome (2026-07-19 session):** **Deferred** (rides with the deferred SC-1 archival).

**SC-6 · INFO · — · single-report (owner decision)** — The LP cluster (lp_arbitrage/lp_analyzer/lp_history + labs + 2.5k doc lines) is half-alive: dormant since May, no tests, but the owner fixed a real lp_history bug on 2026-07-19 and AGENTS.md documents its timestamp contract. Ambiguity is itself a cost — classify it: active (add the MP-4 stopgap + one UTC-bucketing smoke test) or attic.
**Outcome (2026-07-19 session):** **Partially resolved**: `lp_arbitrage.py` got the MP-4 live interlock; the active-vs-attic classification remains owner-decision-pending.

### L. Gaps found only in critique (GV)

**GV-1 · HIGH · decision · critic-verified** — Per-user money data is recoverable from git history in every clone: `history/recommendations.json` and `live_trades/` files were tracked for months before being untracked (`git log --all -- history/recommendations.json live_trades/` shows the commits). `git rm --cached` cleaned the tree, not history. **Owner decision required before any push/share:** purge with `git-filter-repo`/BFG, or record a documented acceptance.
**Outcome (2026-07-19 session):** **Resolved by owner decision: NO purge, NO rewrite** — every commit that added the data is already on `origin/main` (shared history, intentionally preserved); the acceptance is documented in AGENTS.md hard rule #3, with forward protection via the ST-1 allowlist + hygiene script.

**GV-2** — Daily-cap TOCTOU: merged into MP-3.
**Outcome (2026-07-19 session):** **Fixed under MP-3** (the merged finding).

**GV-3 · LOW · S** — No LICENSE file; with multiple people running and copying the code it is all-rights-reserved by default. One file once the owner picks (or an explicit "private, all rights reserved" README note).
**Outcome (2026-07-19 session):** **Fixed**: README now carries 'License: private, all rights reserved.'

**GV-4 · MEDIUM · doc-only** — The adversarial-data threat model is handled in fragments but never end-to-end: marketdata deliberately passes only extracted numeric/enum fields (real credit), but grok/perplexity run live web search inside the panel and discovery proposes tickers from public content — a coordinated pump/astroturf campaign can steer votes toward a listed meme coin by design. Backstops: independent-model consensus, Coinbase listing validation, $5/$15 caps. Probably accepted-by-design — **make it an explicit documented acceptance** (threat-model paragraph in AGENTS.md next to the injection note), covering LM-7's peer-text channel too.
**Outcome (2026-07-19 session):** **Fixed as documentation**: accepted-bounded-surface threat-model paragraph added to AGENTS.md (web-search panelists + discovery steering + LM-7's peer-text channel, with the consensus/listing/caps backstops).

**GV-5 · INFO** — The untracked `scripts/backfill_trading_mode.py` (the one pending change that rewrites the money-history file) was reviewed: idempotent, `--dry-run`, timestamped backup, evidence-backed mapping, unknowns default to `'unknown'`. No defect. Owner should run/track/discard it deliberately rather than leaving it in limbo.
**Outcome (2026-07-19 session):** **Owner-decision-pending**: `scripts/backfill_trading_mode.py` (+ mapping doc) is still untracked in the working tree — run/track/discard remains with the owner.

**GV-6 · process** — Re-baseline `./venv/bin/python -m pytest tests/ -q` immediately before the first fix lands, and after every tier.
**Outcome (2026-07-19 session):** **Done**: suite re-baselined at every phase (616 → 723); this sweep's evidence: 723 passed, silent import, tests/-only collection.

---

## Strengths to preserve (do not regress these while fixing)

1. **Fail-closed consensus is real** — every abstain/error/sub-quorum/unknown-mode path returns BLOCKED (`crypto_trading_bot.py:1299-1342,1396-1402`), pinned by ~60 cases in `tests/test_consensus.py`, including the standing-abstain design that keeps dead clients *in* quorum. The adversarial bug hunt found no fail-open in the decision path.
2. **The live double-lock** is a pure, testable truth table resolved before trader construction, disarming the DEX path too.
3. **Order execution is written for the real API** — intent-before-order, atomic fsync'd ledger writes, recovery lookup on ambiguous failures, `unverified_failure` + append-only reconcile.
4. **`voteschema.parse_vote`** is strict per-field, symbol-bound, and fails closed on reasons debris — the bug class that spent real money in the 2026-07-18 eval is structurally closed.
5. **Model-ID centralization** — zero hardcoded model IDs outside `modelregistry.py`, repo-wide (grep-verified).
6. **Prompt-injection discipline in marketdata** — only extracted numeric/enum fields reach prompts; free text never does.
7. **The test suite's engineering** — 616 tests in ~2.85s, socket-level network guard that names the offender, provenance-stamped real-API fixtures, injected clocks.
8. **The tag vocabulary + durable history records** — decisions are reconstructable from stdout and survive in JSON even when stdout is lost.
9. **AGENTS.md / MODELS.md / OPERATIONS_MANUAL / docs/ hygiene** — accurate, empirically-verified, honestly self-critical; `docs/` (stamped historical records, runbooks, reflections) is the pattern the root should follow.
10. **Recent hygiene is active** — the 2026-07-19 cleanup deleted 2,699 dead lines and untracked user data; `lab/` is a correctly-used quarantine.

## Owner decisions required (blocking items an improvement plan can't decide alone)

| # | Decision | Findings |
|---|---|---|
| 1 | Purge per-user data from git history (filter-repo/BFG) or document acceptance — **before any push** | GV-1, ST-1 |
| 2 | Archive vs. stopgap-guard the correlation universe (and its live path) | SC-1, MP-4 |
| 3 | Keep LP cluster active (guard + smoke test) or archive | SC-6, MP-4 |
| 4 | Remove `--dex` from the bot vs. hard-refuse dex+live until hardened | SC-3 |
| 5 | Extract llm_compare stack to its own repo | SC-2, DX-5 |
| 6 | Delete the 407 KB transcript + relocate design-only docs | DX-3, DX-4 |
| 7 | Pick a license (or explicit private notice) | GV-3 |
| 8 | Daily-cap contract semantics (failed intents, fees) | MP-10 |
| 9 | Run/track/discard `scripts/backfill_trading_mode.py` | GV-5 |

## Recommended sequencing (from the critique, adjusted)

**Tier 0 — stop the bleeding (each < 1 day):**
1. TS-1: `pytest.ini` + probe renames (kills the live-call-at-collection landmine; 4 auditors demanded it).
2. MP-4: `LIVE_TRADING_CONFIRMED` stopgap in both satellites (or the owner's archive decision) — the only place real money moves uninterlocked.
3. MP-2 (+DI-4's rename half): ledger fail-closed + `.corrupt-<ts>` + fail-closed cap check.
4. MP-1: coins dedup, RUN_ID suffix, order_id-deduped positions/cap sums.
5. MP-3: flock spanning cap-check→append (not just `_append_row`).

**Tier 1 — learning-loop integrity (the data engine the live posture depends on):** DI-1 (timestamp fix + STATE_VERSION bump), DI-3, DI-2, MP-6 (whatif parity), ST-1 (gitignore allowlist + untrack), DI-4 (snapshot), GV-1 (owner decision teed up).

**Tier 2 — onboarding safety (trivially cheap, high embarrassment-value):** DX-1, OB-1, OPS-1, ST-4, DX-6.

**Tier 3 — maintenance debt (serialize everything touching `crypto_trading_bot.py` in one agent stream with a file-ownership list, per AGENTS.md):** TS-2 (gate helper + test) → MP-5 → LM-1 → LM-6 → LM-5 → LM-2 (panelprompts.py) → MP-8/MP-9 → LG-1/LG-2 → TS-3/CQ-4 → then CQ-1's staged BotConfig threading. LM-4 and LM-3 can ride alongside (different files).

**Tier 4 — repo shape (highest-conflict, lowest-money-risk; do last, one at a time):** DX-2/DX-3/DX-4/DX-5 doc reorg, SC-1/SC-2/SC-3/SC-5 archival/extraction, ST-2 rename, OB-2/OB-3/OB-4, ST-3 packages (explicitly optional), LG-3, OPS-4, GV-3, GV-4 threat-model paragraph.

## Constraints the improvement plan must respect

- **House rules stand:** agents never commit unprompted; commits are file-partitioned, owner-approved, bracket-tested, no attribution lines; never push. Money-path changes stay separable from infrastructure.
- **One writer at a time on `crypto_trading_bot.py`**; multi-agent work uses explicit file-ownership lists, not global test counts.
- **Never make whatif and live *look* alike in data** — parity fixes (MP-6) must keep `trading_mode` labeling honest; simulated data must never be indistinguishable from real.
- **The learning loop is core, not satellite** — nothing in the archive plans touches `tradeanalyzer.py`, `historyutil.py`, the whatif cadence, or history integrity tests.
- **Fixes to fail-open paths must themselves fail closed** (e.g., an unreadable ledger refuses buys; it does not warn and proceed).
- Several fixes above carry their own regression-test requirement in the finding text; treat those as part of the fix, not optional extras.
- The two double-counted findings the critique flagged are already merged here (MP-1, MP-2) — do not schedule them twice.

## Source reports

- [dimensions/business-logic.md](dimensions/business-logic.md) — Fable 5 · money-path design (12 findings)
- [dimensions/money-path-bugs.md](dimensions/money-path-bugs.md) — Opus 4.8 · adversarial line-level hunt (4)
- [dimensions/ai-api-usage.md](dimensions/ai-api-usage.md) — Opus 4.8 · LLM/API usage (7)
- [dimensions/code-quality.md](dimensions/code-quality.md) — Opus 4.8 · best practices (8)
- [dimensions/repo-structure.md](dimensions/repo-structure.md) — Sonnet 5 · structure (8)
- [dimensions/logging.md](dimensions/logging.md) — Sonnet 5 · logging (6)
- [dimensions/testing.md](dimensions/testing.md) — Opus 4.8 · testing (4)
- [dimensions/documentation.md](dimensions/documentation.md) — Opus 4.8 · docs (7)
- [dimensions/devops.md](dimensions/devops.md) — Opus 4.8 · devops/integrations (8)
- [dimensions/simplicity.md](dimensions/simplicity.md) — Fable 5 · MVP scope (10)
- [dimensions/readability-onboarding.md](dimensions/readability-onboarding.md) — Sonnet 5 · newcomer experience (7)
- [CRITIQUE.md](CRITIQUE.md) — Fable 5 · gaps, verification spot-checks, disputed findings, sequencing
