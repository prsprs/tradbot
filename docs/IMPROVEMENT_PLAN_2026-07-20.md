# Improvement Plan — 2026-07-20

> **EXECUTED 2026-07-21** — implemented across the cascade_followup and cycle2 sessions; see `docs/COMMIT_PROPOSAL_2026-07-21_cascade_followup.md`, `docs/COMMIT_PROPOSAL_2026-07-21_cycle2.md`, and `docs/COMMIT_RECONCILIATION_2026-07-21.md`. Retained as the audit-trail source of the plan.

Source: independent verification of an external AI's (Cascade) live-trading-day session log and its two
reflection reports, audited against the actual codebase by three agents (2× Opus 4.8 code audits,
1× Sonnet 5 docs/tests audit), synthesized by Fable 5. No code was changed and no trades were placed
during the audit. No new API-spending what-if runs were needed: every contested claim was a
control-flow question answerable deterministically from code.

## Part 1 — Verdict on the external evaluation

### Confirmed (external AI was right)
- **No executable CEX sell path.** `market_order_sell` exists (coinbaseutil2.py:488) with zero callers;
  `gate_and_maybe_buy` short-circuits SELL with `[NO SELL PATH]` (crypto_trading_bot.py:2042-2045).
  Already known internally (MP-7, docs/audit-2026-07-19/EVAL.md) and deliberately owner-deferred.
- **TRUMP exclusion is hardcoded, unconfigurable, and undocumented in user-facing docs**
  (`coinsToExclude = {'TRUMP'}`, crypto_trading_bot.py:2808; no env/CLI hook; absent from README and
  OPERATIONS_MANUAL).
- **No portfolio awareness.** Buy path checks only exclusion + caps; `executionledger.positions()` and
  `list_account_balances()` are never consulted by the bot; same coin can be re-bought across runs.
- **HOLD is semantically overloaded.** Prompt asks only "buy, sell, or hold … right now"; no holding
  period, no fee-adjusted minimum move, no entry-quality-vs-direction distinction (panelprompts.py,
  voteschema.py:157-177).
- **Monolith with global state.** 3,250 lines, ~797-line `main()`, 24 `global` statements over ~40
  module-level names. (Nuance: typed records `Vote`/`PanelDecision`/`OrderResult` do exist.)
- **No confidence calibration, no aggregation-policy counterfactual tooling, no walk-forward /
  multi-horizon evaluation.** Confidence is validated at decision time (voteschema.py:183) then dropped
  before persistence — zero records on disk carry a confidence value.
- **No promotion path from scratch (`/tmp` HISTORY_DIR) what-if runs into a durable research corpus.**

### Confirmed and WORSE than claimed (the one genuinely new defect)
- **Polymarket filter is silently bypassed whenever `santiment` is in `--discovery`** — for ALL
  candidates, not just a fallback path. The only route to `filter_coins_by_polymarket` is gated
  `if USE_COIN_FILTERING and USE_COIN_DISCOVERY and not USE_SANTIMENT_DISCOVERY:`
  (crypto_trading_bot.py:2947); hybrid discovery (:3048-3130) never calls it, while the banner prints
  "Polymarket Filter: Enabled" regardless (:2915-2917). No test covers the interaction
  (test_filter_precedence.py only tests banner lines). The external AI called this a "UX ambiguity";
  it is a real control-flow defect.

### Refuted or materially overstated (external AI was wrong)
- **"Fee-adjusted returns unsupported"** — REFUTED. Fee adjustment is the analyzer's core metric:
  `excess = (coin − benchmark) − fee_floor`, with actual round-trip fees joined from the execution
  ledger when a fill matches (tradeanalyzer.py:155-173, 262-312).
- **"Blocked decisions recorded as NONE lose the counterfactual"** — MOSTLY REFUTED. Blocked records
  persist `votes` (per-LLM action map), `deciding_llms`, `majority_action`, `consensus_state`,
  `block_reason` (historyutil.py:215-224). What's actually lost: per-model **confidence** (everywhere)
  and `votes` on **non-blocked** directional records.
- **"No per-provider performance ranking"** — PARTIAL. A per-LLM win/loss table exists
  (tradeanalyzer.py:841-855) but keys on the comma-joined `llm_source` string, so multi-LLM runs
  aren't decomposed per individual provider.
- **"Panelists see different data within a coin"** — PARTIAL. `MARKET_BLOCK_CACHE` (F7a,
  crypto_trading_bot.py:422-440) freezes one market block per coin per run shared by all panelists.
  Real gaps: the block is never persisted to disk, and grok/perplexity prompts invite live web search
  outside it.
- **"No final decision table"** — REFUTED (vote-outcomes line + RUN SUMMARY exist). What's true: no
  `--quiet`/`--json` flag and no machine-readable summary artifact; product JSON dumps unconditionally
  on every buy (:1799, :1873).
- **"Docs and runtime defaults diverge"** — not supported in a 9-item spot check; all matched.
- **Novelty overstated.** Of its headline proposals, research-only majority scoring
  (`majority_action` "for MEASUREMENT only"), vote persistence, compact-output gating (LG-1), the
  sell-path interim guard, and per-coin snapshot freezing were already implemented or explicitly
  pre-identified in this repo's own 2026-07-18/19 docs.

### New findings from this audit (not in the external report)
1. Excluded coins are appended to `coinsToBuy` before the exclusion return (:1915), so the run
   summary's "Coins to buy" overstates intent.
2. DEX live fills are recorded to the ledger without exchange-side fill confirmation (:2660-2669) —
   pre-existing warning, still open.
3. Daily-cap concurrency safety depends on file-lock semantics of the ledger's filesystem.
4. Discrepancy to check: provider HTTP `[INFO]` lines appeared in Josh's terminal runs, but no code in
   the import chain raises logging verbosity — likely google-genai SDK-side logging config; small
   repro needed before "fixing" log noise.

### Bottom-line judgment
The external evaluation's strategic conclusions are sound and match this repo's own prior audits:
safety posture is real, trade frequency is policy-calibrated abstention, and the biggest gaps are
lifecycle (sell/exit/portfolio) and measurement (calibration, counterfactuals, reproducibility) — not
panel size. But its factual accuracy on what the code already does was mediocre (~5 of its concrete
capability claims refuted or materially overstated), and it missed the one real bug it brushed past.
Treat it as directionally useful, not as a source of truth about the codebase.

## Part 2 — Improvement plan

Ground rules (per AGENTS.md and standing conventions): agents never run live mode, never touch real
`history/`, never commit; what-if validation uses scratch `HISTORY_DIR`; money-path changes require
tests and review; Josh commits consolidated, verified progress.

### Model-selection policy for implementation
- **Fable 5** — decision-policy design, money-path adversarial review, prompt-contract changes,
  anything where a wrong judgment costs money. Used as reviewer/designer, sparingly.
- **Opus 4.8** — complex implementation inside the monolith (discovery control flow, historyutil
  schema, analyzer extensions): needs deep multi-file reasoning but follows an approved design.
- **Sonnet 5** — well-scoped mechanical work: tests, small gated fixes, doc updates, CLI flags,
  scripts. Fast and cheap; escalate to Opus if a task turns out to touch decision logic.

### P0 — Correctness (do first)
- **WS1: Fix the Polymarket/Santiment filter bypass.** Apply `filter_coins_by_polymarket` to the
  unioned hybrid-discovery candidate set (or hard-error on the flag combination — design choice for
  review); make the banner report per-source filter provenance; add interaction tests.
  *Impl: Opus 4.8. Review: Fable 5 (money-path adjacent). Tests: included, not delegated separately.*
- **WS2: Stop appending excluded coins to `coinsToBuy`;** correct the summary semantics
  (BUY vs BUY-excluded vs BUY-blocked vs BUY-simulated). *Impl: Sonnet 5.*

### P1 — Evidence & learning loop (highest leverage)
- **WS3: Persist the full decision record.** Per-model confidence + votes on ALL records (not just
  blocked), prompt hash, resolved model IDs/params, and a reference to the frozen per-coin market
  block (persist `MARKET_BLOCK_CACHE` entries per run). Schema-versioned, backward-compatible with
  the 109 existing records. *Impl: Opus 4.8. Review: Fable 5 (historyutil is analyzer input = money-adjacent).*
- **WS4: Analyzer extensions** (unblocked by WS3 data going forward): decompose comma-joined
  `llm_source` into per-provider attribution; aggregation-policy counterfactuals (unanimous vs 3-of-N
  vs 2-of-N vs single-provider shadow policies); confidence calibration (reliability + Brier);
  multi-horizon maturation sweep (e.g. 6h/24h/72h/7d). Read-only over history — safe to iterate.
  *Impl: Opus 4.8; calibration/report plumbing subtasks: Sonnet 5.*
- **WS5: Scratch-run promotion.** A sanitized `scripts/promote_research_run.py` that copies a scratch
  HISTORY_DIR run into a durable owner-data-free research corpus (separate from personal `history/`,
  respecting the multi-user never-commit norm), plus runbook update. *Impl: Sonnet 5.*

### P2 — Strategy lifecycle (owner-gated; design before code)
- **WS6: Sell/exit path design doc.** Entry-to-exit lifecycle: exit conditions, invalidation,
  max holding period, sell execution + fill confirmation, ledger semantics. Already owner-deferred
  (MP-7) — produce the decision document, implement only after Josh approves.
  *Design: Fable 5. Later impl: Opus 4.8 + Fable review.*
- **WS7: Portfolio awareness.** Consult ledger positions/balances before buys; per-coin exposure cap;
  duplicate-exposure guard across runs. Behind a flag, whatif-validated first.
  *Design: Fable 5. Impl: Opus 4.8. Review: Fable 5.*
- **WS10: Prompt contract v2.** Replace overloaded HOLD with an explicit taxonomy
  (e.g. ENTER_LONG / WATCH / NO_EDGE / EXIT / ABSTAIN mapped conservatively to today's actions),
  and state horizon + fee-adjusted minimum expected move in the prompt. This changes decision
  distribution → whatif-only until WS4 can measure it against the old contract.
  *Design: Fable 5. Impl: Opus 4.8. Validation runs: whatif, scratch HISTORY_DIR.*

### P3 — UX & configuration
- **WS8: `--json` run-summary artifact + `--quiet` mode;** gate the unconditional product-JSON dumps;
  first reproduce where the HTTP `[INFO]` lines actually come from (finding #4) before suppressing.
  *Impl: Sonnet 5.*
- **WS9: Configurable exclusion list** (`EXCLUDE_COINS` env / `--exclude-coins`, with per-symbol
  reason strings surfaced in banner and summary; TRUMP becomes the documented default). *Impl: Sonnet 5.*

### Sequencing
1. WS1 + WS2 (bugfixes, tests) → Josh reviews/commits.
2. WS3 → WS4 in that order (schema before analytics); WS5 in parallel.
3. WS6/WS7/WS10 designs go to Josh as decision docs; implementation only on approval.
4. WS8/WS9 anytime; cheap, independent.

### Explicitly rejected from the external report
- Loosening live consensus now (its own data can't justify it — and neither can ours until WS3/WS4
  accumulate counterfactual outcomes).
- Building "frozen snapshots" from scratch (exists — extend/persist F7a instead).
- Rebuilding fee-adjusted scoring (exists — extend it).
- Online RL / adaptive live policy (premature; agreed with the report's own caution here).
