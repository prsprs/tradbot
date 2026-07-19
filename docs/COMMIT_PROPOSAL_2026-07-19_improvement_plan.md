# Commit proposal — IMPROVEMENT_PLAN.md execution, 2026-07-19

**For:** Josh (owner executes; agents never commit — per AGENTS.md).
**State:** all Phases 0–5 of [docs/audit-2026-07-19/IMPROVEMENT_PLAN.md](audit-2026-07-19/IMPROVEMENT_PLAN.md) are implemented in the uncommitted working tree. Suite: **723 passed** (baseline 616, +107 new tests). Silent import verified. Bare `pytest --collect-only` yields only `tests/` nodes. Every money-path diff passed a Fable 5 adversarial review gate (2 MAJORs found and fixed with pinning tests); non-money diffs passed an Opus gate. E2E whatif run (1 Gemini call) and a real 5/5 full-panel preflight probe (schema probes included) both green.

Because all phases landed in one tree, the plan's per-phase commit tables are consolidated here so **each file appears in exactly one commit** (file-partitioned, money-path separate from infra). The order below keeps the tree green and the hygiene rules intact at every step. Run `scripts/check_staged_hygiene.sh` before each commit.

## Commit sequence

| # | Theme | Files | Notes |
|---|---|---|---|
| 1 | **Hygiene + test infra** (plan C1.2+C0.1) | `.gitignore`, `scripts/check_staged_hygiene.sh`, `history/recorder.py`, the staged `git rm --cached history/llm_compare_history.json`, `pytest.ini` (new), renames: `probe_coinbase.py`, `probe_jupiter_swap.py`, `probe_trustwallet_swap.py`, `lab/session_tests_20260718/_consensus_snippet.py`, `_extract_rec_snippet.py`, `tests/generate_multi_pair_data.py`, `LEADING_INDICATOR_TEST_GUIDE.md`, `DEX_TRADING_FEATURE.md`, provenance comments in `tests/test_consensus.py` + `tests/test_extract_recommendation.py`, `AGENTS.md` | AGENTS.md lands once here (line-32 fix + Phase 4 threat-model/GV-1/docs-convention prose). `llm_compare_history.json` stays on disk, now ignored. |
| 2 | **Satellite live interlocks** (C0.2, money) | `leading_indicator_tester.py`, `lp_arbitrage.py` | `[LIVE LOCK]` downgrade guards; MP-4 closed. |
| 3 | **Ledger/history fail-closed + locking** (C0.3, money) | `executionledger.py`, `historyutil.py`, `scripts/reconcile_positions.py`, `OPERATIONS_MANUAL.md`, `tests/test_execution_ledger.py`, `tests/test_history_integrity.py`, `tests/test_duplicate_rejection_shape.py` | MP-1/2/3, DI-3/4 + the review gate's shape-validation and truthy-order_id tightens. |
| 4 | **Bot money-path + hygiene** (C0.4 + Phase 3 bot items, money) | `crypto_trading_bot.py`, `tests/test_trade_gate.py`, `tests/test_import_purity.py`, `tests/test_log_fixes.py`, `tests/test_primary_panel_warning.py` | Gate extraction, whatif honesty, recovery wiring, DEX warning, summary counters, MP-5 warning, LG-1/LG-2, `load_dotenv`→`main()` + `_refresh_env_snapshots()`, MP-10 help line, HISTORY_DIR epilog. Import already shrunk; commit 5 deletes the helpers. |
| 5 | **Provider utils + preflight + prompts + LM-5** (money-adjacent) | `claudeutil.py`, `openaiutil.py`, `grokutil.py`, `perplexityutil.py`, `llmpreflight.py`, `panelprompts.py` (new), `docs/SUPERSEDED.md` (new), `tests/test_model_registry.py`, `tests/test_panel_prompts.py` (new), `tests/fixtures/panel_prompts/golden_prompts.json` (new) | LM-1a alias, LM-6 timeouts, preflight→money-path classes + parity tests, LM-2 builders (35 byte-identical goldens), LM-5 deletion **in the same commit as** its SUPERSEDED.md record (removal-discipline rule). SUPERSEDED.md also carries the full main→josh map. |
| 6 | **Analyzer correctness** (C1.1) | `tradeanalyzer.py`, `tests/test_analyzer.py` | DI-1 `utc_epoch` + STATE_VERSION 3 (expected one-time fallout: frozen wrong verdicts re-score; some old grades honestly become unscoreable), DI-2 cache key + distance guard, TZ tests. |
| 7 | **Docs & installability** (Phase 2) | `README.md`, `.env.example`, `requirements.txt`, `requirements_dev.txt` (new) | Quick Start now true on a clean shell; floors `anthropic>=0.94`, `openai>=1.66`, `coinbase-advanced-py>=1.8,<2`. The `.env.example` ANTHROPIC_API_KEY alias note depends on commit 5 — keep this after it. Also includes the README tree fix + mermaid diagram + license line + doc-reorg link repoints (README lands once). |
| 8 | **Doc reorg + polish** (Phase 4) | `git mv` moves into `docs/design/` (9 files incl. `CRYPTO_TRADING_BOT.md`, `LLMCompareFeature.md`, `GENERAL_PURPOSE_LLM_COMPARE_AND_INTEGRATE_FEATURE.md` with superseded banners) and `docs/archive/` (2), `LLM_COMPARE_OPERATIONS_MANUAL.md` (model-ID pointer), `CORRELATION_HISTORY_TRACKER.md` (link fixes), `coinbaseutil2.py` (5 log tags + BlobbyTrader docstring only), `historyutil.py`… **note:** historyutil's docstring edit is in commit 3's file — verify it carries both changes there; `history/recorder.py` docstring rides commit 1. **Deletions: owner signed off 2026-07-19** (in-session): `Restore Directional Analysis.md` (407KB transcript), `.windsurf/workflows/g.md` (empty) — staged, recoverable from git history. |
| 9 | **CI** (OPS-4) | `.github/workflows/tests.yml` (new) | pytest only; hygiene script deliberately not in CI (inspects local index — rationale in workflow comment). CI gives **no** secret backstop; local hygiene discipline remains the guard. |
| 10 | **Audit records + proposals** | `docs/audit-2026-07-19/` (EVAL, plan, dimensions, outcome annotations), `docs/MERGE_PROPOSAL_josh_to_main.md`, `docs/COMMIT_PROPOSAL_2026-07-19_improvement_plan.md` (this file), session reflections doc | Point-in-time records. |

## Not included — pre-existing, owner-pending

- `EVALUATION_LESSONS_LEARNED_2026-07-18.md` (your uncommitted edit — untouched by agents).
- `scripts/backfill_trading_mode.py` + mapping doc (GV-5: run/track/discard deliberately).
- Two stamped historical docs still reference old probe filenames by design (`docs/SESSION_HANDOFF_2026-07-18.md`, `EVALUATION_LESSONS_LEARNED_2026-07-18.md`) — frozen records, not updated.

## Behavior changes to be aware of (all reviewed and gated)

Tightenings: corrupt/wrong-shape ledger now refuses in live (with snapshot auto-restore); whatif enforces exclusion list + daily cap (labeled whatif-simulated); duplicate `--coins` analyze once; satellites downgrade unarmored live. Loosenings (deliberate, reviewed): excluded coins no longer burn run-cap headroom; duplicate-marked attempts' intents don't count against the daily cap. The ledger flock is held across live order placement (overlapping cron runs serialize). STATE_VERSION 3 causes a one-time analyzer re-score.

## Open items for you

1. ~~Sign off the two doc deletions~~ — **done 2026-07-19** (owner approved in-session; they're staged).
2. LICENSE: README now says "private, all rights reserved" — replace with a LICENSE file if preferred (GV-3).
3. The merge itself: see `docs/MERGE_PROPOSAL_josh_to_main.md` (owner-executed, owner-timed; re-verify suite count at merge time).
4. GV-5 backfill script decision.
5. Post-merge follow-up queue: `docs/reflections-2026-07-19/SYNTHESIS.md` §"Recommended follow-ups" (14 items, leverage-ordered).
