# Commit Proposal — 2026-07-21 (Cascade-audit follow-up implementation)

All work from docs/IMPROVEMENT_PLAN_2026-07-20.md executed 2026-07-20/21 by agent teams
(WS1-WS5, WS8-WS9 implemented; WS6/WS7/WS10 delivered as owner-gated design docs).
Suite: 798 → 891 passing (+93 tests). Import purity verified. Nothing committed — Josh commits.

Note: `crypto_trading_bot.py` and `tests/test_run_summary.py` carry changes from multiple
workstreams, so a strict per-workstream split needs `git add -p`. Two options:

## Option A — consolidated (recommended, matches commit-cadence preference)

1. **Fix Polymarket filter bypass in hybrid discovery; truthful run-summary exclusions**
   - `apply_polymarket_filter_to_candidates` + hybrid-mode wiring (fail-closed, provenance-labeled)
   - excluded coins tracked in `coinsExcluded`, distinct summary line
   - tests: test_polymarket_santiment_interaction.py (7), test_trade_gate.py/test_run_summary.py edits
   - files: crypto_trading_bot.py (partial), tests/* — if splitting is not worth it, fold into commit 2

2. **Evidence loop: schema v2 decision records, analyzer research extensions, corpus promotion**
   - historyutil: `vote_details` (per-model action+confidence, ALL records), `schema_version`,
     `prompt_hash`, `models`, `market_block_ref/present`; per-run market_blocks/<run_id>.json
   - tradeanalyzer: per-provider attribution (+legacy fallback), RESEARCH-ONLY aggregation-policy
     counterfactuals, confidence calibration + Brier, `--horizons` sweep (compute-only, state-safe)
   - scripts/promote_research_run.py (whatif-only corpus, live-row refusal, gitignored research_corpus/)
   - tests: test_schema_v2.py (15), test_analyzer_ws4.py (23), test_promote_research_run.py (21)
   - files: historyutil.py, tradeanalyzer.py, crypto_trading_bot.py (partial), scripts/, .gitignore,
     docs/RUNBOOK_whatif_cadence.md

3. **UX/config: --quiet, --json-summary, configurable EXCLUDE_COINS, httpx log fix**
   - `--exclude-coins`/`EXCLUDE_COINS` (default TRUMP unchanged; empty-override live notice; banner provenance)
   - `--json-summary [PATH]` (atomic, best-effort, HISTORY_DIR-aware run_summaries/)
   - `--quiet` (product-JSON dumps + progress banners only; safety lines never suppressed)
   - root cause of HTTP [INFO] noise: fibonacci_analyzer's module-level logging.basicConfig via
     marketdata import; targeted `logging.getLogger('httpx').setLevel(WARNING)` in main()
   - tests: test_exclude_coins.py (16), test_run_summary.py additions (23)
   - files: crypto_trading_bot.py (partial), README.md, OPERATIONS_MANUAL.md, tests/*

4. **Docs: Cascade-audit verdict, improvement plan, P2 design decision docs**
   - docs/IMPROVEMENT_PLAN_2026-07-20.md (verdict + plan + model policy)
   - docs/design/{SELL_EXIT_LIFECYCLE,PORTFOLIO_AWARENESS,PROMPT_CONTRACT_V2}_FEATURE.md
     (each ends in an owner decision checklist; WS6 doc flags the `intended_spend_on_date`
     no-side-filter landmine that must land with any first SELL writer)
   - EVALUATION_LESSONS_LEARNED_2026-07-18.md (pre-session edits, review separately)

## Option B — two commits
1. Implementation (everything code+tests, WS1-WS5+WS8-WS9 in one commit, bulleted body)
2. Docs (commit 4 above)

## Not part of this session (pre-existing on tree — commit separately or with 2026-07-19 work)
- scripts/backfill_trading_mode.py + scripts/backfill_trading_mode_mapping.md
- EVALUATION_LESSONS_LEARNED_2026-07-18.md modifications

## Review flags for Josh (judgment calls made by agents, all noted in their sections)
- prompt_hash canonicalizes on the primary Round-1 template (grok/perplexity preamble variants
  share the hash) — reproducibility key, not byte-identity.
- WS3 `models` map includes client_init_failure panelists (records "what was configured").
- Horizon sweep never persists judged state (recompute-only) — deliberate, state_key isn't horizon-aware.
- Quiet mode gates exactly: 2 product dumps, their headers, per-coin progress banners. Nothing else.

## Addendum (2026-07-21, reflection session) — additional commit

**5. Reflections, process lessons, logging hygiene, reference docs** (suite now 893 passing)
   - docs/reflections-2026-07-21/ (4 agent reflections + ORCHESTRATOR + SYNTHESIS with owner
     follow-up queue)
   - AGENTS.md: five new lessons (module-level basicConfig side effect, effect-honesty,
     implicit-universe aggregations, symbol-anchor briefing, verified-vs-inherited claims) +
     reference-doc pointers
   - Logging hygiene: fibonacci_analyzer.py, correlation_tracker.py, leading_indicator_tester.py
     (third offender found — imported by tests, so suite collection was mutating root logging)
     basicConfig moved behind CLI entry; 2 new import-purity tests (tests/test_import_purity.py)
   - docs/RECORD_SCHEMA.md + docs/INVARIANTS.md (verified field inventory incl. never-read fields;
     exhaustive executionledger aggregation table; both stacks' prompt_hash distinction)
   - Fits Option A as commit 5, or folds into Option B commit 2 (docs) + a small code commit for
     the logging fixes (money-path untouched).

## Owner-gated next steps (need your decisions before any implementation)
- WS6 sell/exit, WS7 portfolio awareness, WS10 prompt contract v2 — decision checklists at the
  end of each docs/design/ file. WS10 is additionally sequenced behind accumulating v2-schema
  whatif data (≥200 matured decisions proposed) measured via the new WS4 analyzer sections.
