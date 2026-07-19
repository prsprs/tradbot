# Tradbot Improvement Plan — from docs/audit-2026-07-19/EVAL.md (lean version)

**Status:** approved by owner 2026-07-19; amended same day after owner review (llm_compare stays in-repo; DEX live warns instead of refusing; LM-5 delete-with-documented-supersession; removal discipline added; branch-context reflection added — the plan now explicitly builds toward an owner-executed josh→main merge). Read this alongside [EVAL.md](EVAL.md) (the findings this plan implements) — finding IDs (MP-1, DI-1, TS-1, …) below refer to it.

**EXECUTED 2026-07-19 (same day), all phases:** suite 616→723 green; money-path diffs Fable-review-gated (2 MAJORs found and fixed); E2E whatif run + real 5/5 panel preflight probe passed; EVAL.md annotated with per-finding outcomes. Work is uncommitted on `josh` — the owner commits per [../COMMIT_PROPOSAL_2026-07-19_improvement_plan.md](../COMMIT_PROPOSAL_2026-07-19_improvement_plan.md); merge prep in [../MERGE_PROPOSAL_josh_to_main.md](../MERGE_PROPOSAL_josh_to_main.md); capability map in [../SUPERSEDED.md](../SUPERSEDED.md); session reflections in [../reflections-2026-07-19/SYNTHESIS.md](../reflections-2026-07-19/SYNTHESIS.md).

**Functionality guarantee (owner-confirmed 2026-07-19):** this plan removes no feature. llm_compare stays; DEX live stays (with a warning); satellite live modes stay (gated behind the same `LIVE_TRADING_CONFIRMED=1` the main bot already requires). Code removal is permitted only under the removal discipline in the ground rules — verified redundant against both branches and recorded in `docs/SUPERSEDED.md`. In this plan that is exactly one item: the legacy 2-LLM consensus helpers (LM-5, Phase 3), whose capability is fully covered by the `PanelDecision` machinery except the fail-open single-model fallback, which is documented as intentionally dropped. Non-code deletions (a pasted chat transcript, an empty IDE file) need owner sign-off at the checkpoint and stay recoverable from git history.

## Context

The 2026-07-19 audit (12-agent team, adversarially cross-checked) confirmed the consensus/trade-gate core is genuinely fail-closed, and found the real problems one layer out: the files that record money (ledger/history) can be silently wiped or double-counted, the analyzer grades trades against wrong-time prices, typing bare `pytest` fires a real authenticated Coinbase call, two dormant tools can place real swaps without the safety interlock, and the README's setup instructions are factually wrong.

**Selection principle (owner guidance):** no coding for coding's sake. An item is in this plan only if it (a) protects money or money records, (b) **deletes/shrinks** code or docs, or (c) fixes something actively wrong that users or agents hit. Pure refactors, renames, and nice-to-haves are explicitly deferred (list at the end). Every item below has a plain-English "why."

## Branch context — why this plan ultimately points at a merge

Verified 2026-07-19 against `origin/main` (github.com/prsprs/tradbot):

- `josh` is **13 commits / 100 files / +18k−4k lines ahead** of `origin/main`.
- **`main` — the branch other users presumably run — defaults to LIVE trading** (`--trading-mode` help text: "default: live") and contains **none** of the safety machinery: zero hits for `LIVE_TRADING_CONFIRMED`, `resolve_trading_mode`, `executionledger`, daily spend cap, `PanelDecision` fail-closed consensus, `voteschema`, `modelregistry`, `llmpreflight`, `marketdata`. Its hardcoded model IDs predate the registry work and are likely partly dead (provider rot is documented in MODELS.md).

Implications, baked into this plan:

1. **Every fix here protects only `josh` until it reaches `main`.** The end-state of this plan is therefore not just a hardened branch — it is a **merge-ready branch plus the documentation main's users need to adopt it** (see the supersession map in Phase 4 and the merge proposal in Phase 5). The merge itself is owner-executed and owner-timed.
2. **`main` is the old application, not cruft.** The removal discipline verifies both branches, and `docs/SUPERSEDED.md` doubles as the merge changelog: what each main-branch capability became in josh (kept / upgraded / replaced / intentionally changed).
3. **Preservation bias** (the consistent owner correction throughout plan review): when in doubt between removing and gating/documenting — gate and document. Every audit-suggested removal reviewed by the owner was downgraded to preservation (history purge → no rewrite; llm_compare extraction → keep; DEX-live refusal → warn; helper deletion → delete only with verified parity + documented supersession).

**Owner decisions locked in:**
1. **Satellites:** guard now (add the safety interlock), archive later — no code removal of correlation/LP tools in this plan.
2. **llm_compare: KEEP in-repo** (owner reversal 2026-07-19 — it is a working feature that exists on main). Hygiene fixes only: untrack its history file, gitignore allowlist, `HISTORY_DIR` override in `history/recorder.py`, and the llmpreflight rewrite so preflight probes the real money-path clients. The documented check-both-stacks rule (AGENTS.md:76) stays.
3. **History: NO PURGE, NO REWRITE.** Verified: every commit that ever added per-user data (`history/recommendations.json`, `live_trades/`, `history/llm_compare_history.json`) is already on `origin/main` — pulled-down shared history, treated as intentionally preserved. The only local-only commit touching those paths (`a2edfc2`) *removes* tracking. Forward protection only.
4. **MP-5:** warn-only (a startup warning when the primary LLM isn't on the voting panel); no change to consensus math.
5. **DEX live (SC-3): warn but allow** (owner choice 2026-07-19) — a loud `[WARNING]` that DEX live fills lack the Coinbase path's fill-confirmation hardening, then proceed. No functionality change.

## Ground rules (in every agent's brief)

- **Agents never commit or push.** Each phase ends with a file-partitioned commit proposal (each file wholly in one commit; money-path commits separate from infra) that Josh reviews and executes per AGENTS.md, running `scripts/check_staged_hygiene.sh` per commit.
- **One writer at a time on `crypto_trading_bot.py`** — a single serialized lane owns it. Every lane gets an explicit file-ownership list; "files outside your list unchanged" is the check.
- **Never weaken fail-closed. Never make whatif data look like live data** (`status='simulated'` and honest `trading_mode` labels stay).
- **Data safety (hard):** no data file under `history/` or `live_trades/` is ever deleted; no git history is ever rewritten. Only rename (`.corrupt-<ts>` quarantine), copy (`.bak-` snapshot), and `git rm --cached` (index-only — verify the file still exists on disk after). The only true deletions are owner-approved tracked docs/code, all recoverable from git history.
- `import crypto_trading_bot` stays side-effect-free; the naive-UTC+`'Z'` timestamp storage contract stays.
- Bracket everything: `./venv/bin/python -m pytest tests/ -q` green (re-baseline ~616 first) + silent bot import, before each phase's first commit and after every commit group.
- Agent bot runs: whatif only, `HISTORY_DIR=<scratch>`. Small paid LLM probes pre-authorized; exchange writes never.
- **Reflection harvest** from implementing agents at each checkpoint, before the commit proposal.
- **Removal discipline (owner rule, 2026-07-19):** never assume code is unused. Before removing anything, (1) read it and state what it does, (2) verify zero call sites *and* zero doc references on **both `origin/main` and `josh`**, (3) confirm the same capability exists in the current version — or name exactly what is being dropped and why — and (4) record the supersession in `docs/SUPERSEDED.md` (created at first use) in the same commit as the removal. A capability intentionally dropped (not just relocated) always needs explicit owner sign-off.

## Agent team

| Lane | Files owned | Model | Why this model |
|---|---|---|---|
| **L1 Money-path** (serialized; spans P0 & P3) | `crypto_trading_bot.py`, `executionledger.py`, `historyutil.py`, `scripts/reconcile_positions.py`, `panelprompts.py` (new), money tests (`tests/test_execution_ledger.py`, `test_history_integrity.py`, `test_duplicate_rejection_shape.py`, `test_trade_gate.py` new) | **Fable 5** | The one lane where a subtle mistake costs money or corrupts real ledgers — fail-closed semantics and locking need the strongest reasoning |
| **L2 Satellites** | `leading_indicator_tester.py`, `lp_arbitrage.py` | **Sonnet 5** | Two ~15-line guards with exact, verified insertion points |
| **L3 Analyzer** | `tradeanalyzer.py`, `tests/test_analyzer.py` | **Opus 4.8** | Subtle timestamp/scoring semantics, fully pre-designed |
| **L4 Infra/hygiene** | `pytest.ini` (new), probe/lab renames, `.gitignore`, `scripts/check_staged_hygiene.sh`, `history/recorder.py`, `AGENTS.md:32`, doc-reference fixes | **Sonnet 5** | Mechanical config/renames from a checklist |
| **L5 Preflight + provider utils** | `claudeutil.py` + 3 sibling utils (two tiny fixes), `llmpreflight.py`, `tests/test_model_registry.py` | **Opus 4.8** | Provider-SDK and test-rework judgment |
| **L6 Docs** | `README.md`, `.env.example`, `requirements*.txt`, `requirements_dev.txt` (new); later: doc moves, diagram | **Sonnet 5** | Doc-accuracy work against a verified fact list |
| **L7 Polish (P4)** | CI workflow, LICENSE, AGENTS.md prose notes, small log tags | **Sonnet 5** (AGENTS.md threat-model/acceptance prose: **Opus 4.8**) | Mostly mechanical; the prose notes need care |
| **Review gates** | read-only | **Fable 5** for money-path diffs (adversarial fail-open hunt); **Opus 4.8** elsewhere | Independent check before anything reaches Josh |

---

## Phase 0 — Safety & money-record integrity

L1, L2, L4 in parallel. Commit landing order: C1.2 (gitignore first — the snapshot files it must cover appear in C0.3) → C0.1 → C0.2 → C0.3 → C0.4.

### L4 — Infra (why: typing `pytest` today fires a real authenticated Coinbase call at collection, and can collect two real-swap functions)
- `pytest.ini`: `testpaths = tests`, `norecursedirs = lab venv scripts dex context .git __pycache__ live_trades history`, `python_files = test_*.py`.
- `git mv`: `test_coinbase.py→probe_coinbase.py`, `test_jupiter_swap.py→probe_jupiter_swap.py`, `test_trustwallet_swap.py→probe_trustwallet_swap.py`, `lab/session_tests_20260718/test_*.py→_*_snippet.py`, `tests/generate_multi_pair_test.py→generate_multi_pair_data.py`. Update the few doc references (`LEADING_INDICATOR_TEST_GUIDE.md:11,29,225`, `DEX_TRADING_FEATURE.md:1557,1668`, provenance comments in `tests/test_consensus.py:3`, `tests/test_extract_recommendation.py:3,27`); AGENTS.md:32 → "`pytest tests/ -q`".
- **ST-1** (why: the current gitignore is a name-by-name list that already let real user data get committed once): switch `history/` to an allowlist — `history/*` + `!__init__.py`, `!recorder.py`, `!test_expected_output.csv`, `!test_recommendation_data.json`. Stage `git rm --cached history/llm_compare_history.json` (index-only; verify file still on disk + now ignored). Align `check_staged_hygiene.sh:25` to the same list. Give `history/recorder.py` the same `HISTORY_DIR` env override its siblings have.

### L2 — Satellite interlocks (why: these two tools can place real Jupiter swaps today with none of the bot's safety machinery)
- `leading_indicator_tester.py` right after `parse_args()` (~:4888): if live mode and `LIVE_TRADING_CONFIRMED != '1'` → loud `[LIVE LOCK]` banner + downgrade to `'paper'`. Fix the stale `:2178` comment.
- `lp_arbitrage.py` after `parse_args()` (~:1396): same guard, downgrade to `'whatif'` (forces the no-wallet branch). Downgrade, not exit — the tools stay usable for research.

### L1 — Money-path stream (Fable 5), in this order:
1. **Trade-gate test first (TS-2)** — why: today an agent can reorder the cap checks or break one of the two duplicated buy-gate call sites and all 616 tests stay green. Extract the duplicated wiring (`crypto_trading_bot.py:2450-2451`, `:2584-2585`) into one `gate_and_maybe_buy()`; new `tests/test_trade_gate.py` (pattern from `tests/test_consensus.py:80-92`, stubbed `buy_something`) asserting: cap refusals refuse, exclusion excludes, approved buy dispatches exactly once, blocked decisions never dispatch. Every later edit in this region lands inside a tested function.
2. **Fail-closed ledger with self-healing recovery (MP-2 + DI-4, one design)** — why: today a corrupt `executions.json` is silently replaced by a fresh file on the next buy, erasing the money record AND resetting the daily spend cap to $0; but per owner, live trading must never be left stuck — recovery must be automatic or one command. Design: this same commit adds the run-start snapshot (`executions.json.bak-<date>`, DI-4), and that snapshot is the recovery source. `executionledger.py`: new `LedgerError`; `load_executions()` raises on corrupt (absent file still `[]`, normal first run); `quarantine_corrupt_ledger()` renames to `.corrupt-<ts>` — **nothing is ever deleted; this file is local per-user runtime data, gitignored, never committed, unrelated to git history or main**. On corrupt in **live**: quarantine → **auto-restore from the newest `.bak-` snapshot → print a loud `[LEDGER ERROR] recovered from snapshot <name>` → continue trading** (the snapshot carries the real cap data, so this is not trading on a wrongly-reset $0 cap). Only when no snapshot exists (essentially only before the feature's first run) refuse the buy — and the error text itself contains the exact recovery command, copy-paste resolvable. Whatif: quarantine-and-continue. `historyutil.py`: atomic tmp+`os.replace` writes + quarantine-and-continue (recommendations don't gate money). `reconcile_positions.py`: refuse to repair from a corrupt ledger. Short "ledger recovery" subsection in OPERATIONS_MANUAL.md. All tagged `[LEDGER ERROR]`/`[HISTORY ERROR]`. Tests cover the auto-restore path (recovered cap equals snapshot's spend, trading proceeds) and the no-snapshot refusal message.
3. **File locking (MP-3)** — why: the runbook schedules cron runs against the real history dir; two overlapping runs currently do read-modify-write on the same file, so the loser's rows vanish — including the rows the daily cap counts. Sibling `.lock` files, one small reentrant lock helper per file; held in `_append_row` / `save_recommendation`, and in `maybe_execute_buy` spanning the daily-cap check through the intent write (closes the check-then-write race). Never nest the two locks (call sites already don't).
4. **Duplicate protection (MP-1, trimmed to the cheap 90%)** — why: `--coins=BTC,ETH,BTC` currently analyzes BTC twice and records two fills for one real order. Dedupe `ANALYZE_COINS` (`dict.fromkeys`, one line); add a short random suffix to `RUN_ID` (one line — kills same-second cross-run collisions); `positions_from_rows` counts each distinct `order_id` once and `record_fill` marks repeats `duplicate_of` (small function change). *Not* doing the intent-sum rework (deferred, MP-10).
5. **Whatif honesty (MP-6 + MP-9)** — why: whatif is the learning loop's data, and today it "buys" things live never could. Apply the exclusion list in both modes and move it above the budget commit; check the daily cap in whatif too (from whatif intent rows, soft-fail); record estimated fees (`notional*1.2%`) on simulated fills — `status='simulated'` unchanged.
6. **Record decisions even when the price fetch fails (DI-3)** — why: today exactly the interesting runs (blocked decisions, discovery tickers not on Coinbase) leave no history at all, and bid/ask are faked as copies of price. Write the record with `price/bid/ask = None` (analyzer already classifies these honestly); never fabricate bid/ask.
7. **Daily ledger snapshot (DI-4)** — why: one file on one machine holds the money record, and the snapshot is item 2's automatic recovery source; ~5 lines copies it to `executions.json.bak-<date>` at run start (idempotent per day, non-fatal on failure).
8. **DEX-live warning (SC-3, warn-but-allow per owner)** — why: the DEX branch never got the fill-confirmation hardening the CEX path has; print a loud `[WARNING] DEX live fills are recorded unverified (no fill-confirmation hardening)` banner when `--dex` + live is armed, then proceed (~5 lines). Functionality unchanged.
9. **Two summary one-liners:** daily-cap refusals get their own counter + summary line (MP-8 — the acceptance run already hit this confusion); `[NO SELL PATH] consensus SELL recorded but not executable` at the gate (MP-7 interim — so dropped SELL signals are visible).

**Checkpoint 0** (Fable review gate → reflections → commit proposal):

| Commit | Files | Class |
|---|---|---|
| C1.2 | `.gitignore`, `check_staged_hygiene.sh`, `history/recorder.py` (+ `git rm --cached`) | hygiene |
| C0.1 | `pytest.ini`, renames, AGENTS.md, 2 feature docs, 2 provenance comments | infra |
| C0.2 | `leading_indicator_tester.py`, `lp_arbitrage.py` | money-path (satellites) |
| C0.3 | `executionledger.py`, `historyutil.py`, `reconcile_positions.py`, `OPERATIONS_MANUAL.md` (ledger-recovery subsection), their tests | money-path (ledger) |
| C0.4 | `crypto_trading_bot.py`, `tests/test_trade_gate.py` | money-path (bot) |

## Phase 1 — Learning-loop correctness (parallel with Phase 2)

### L3 — Analyzer (why: every at-maturity grade is currently computed hours off target — the exact `.timestamp()` bug AGENTS.md documents as a past 4-hour incident — and then frozen permanently)
- **DI-1:** fix `tradeanalyzer.py:383` (`when.replace(tzinfo=timezone.utc).timestamp()`), extracted into a pure testable helper; bump `STATE_VERSION 2→3` so frozen wrong verdicts re-score once (expected fallout: some old grades honestly become unscoreable — flagged in the commit message).
- **DI-2:** candle cache key includes the lookback span; if the nearest candle is >1.5× the granularity from target, return None so the record degrades honestly instead of being graded against a window edge labeled AT_MATURITY.
- Tests: TZ-independence (`TZ=America/New_York` + `tzset()` fixture, reverted in teardown; never `setattr` the `time` module), cache-key isolation, distance-guard degradation.
- **Checkpoint 1:** commit C1.1.

## Phase 2 — Fix what's actively wrong for users

### L6 — Docs & installability (why: a newcomer following the README today gets `command not found`, sets a dead env var, and never learns about the one credential file the bot actually requires — and a fresh `pip install` can't even run the test suite)
- README Quick Start rewrite: venv step, `pip install`, copy `.env.example`, **place `cdp_api_key.json` at repo root (required even for what-if)**, delete the dead `COINBASE_API_KEY` line, `./venv/bin/python` run command, recommend `HISTORY_DIR=/tmp/tradbot_scratch` for first runs. Fix `.env.example:30` ("required even for what-if runs"). Name `HISTORY_DIR` explicitly in the `--help` epilog (no new CLI flag — keep the surface small).
- `requirements.txt` floors raised to what the code actually needs (`anthropic>=0.94`, `openai>=1.66`, `coinbase-advanced-py>=1.8,<2` — today's floors install versions that crash 2 of 5 panelists); new `requirements_dev.txt` (pytest). `.env.example`: optional DEX/correlation block with a loud never-commit warning on wallet secrets; note the `CMC_API_KEY`/`ANTHROPIC_API_KEY` aliases.
- **Checkpoint 2:** one docs commit + one requirements commit.

## Phase 3 — Preflight fix + small fixes on the bot file

*(llm_compare stays in-repo per owner decision #2 — no extraction. Its hygiene fixes — untracking `llm_compare_history.json`, the gitignore allowlist, the `history/recorder.py` `HISTORY_DIR` override — already landed in Phase 0's ST-1.)*

### L5 — Preflight + provider utils (why: today a user who sets only `ANTHROPIC_API_KEY` — the standard variable name — gets a green preflight, then Claude fails at construction and every trade blocks for the whole run; and a hung provider stalls a cron run ~10 min per call)
1. Two tiny provider-util fixes first: `claudeutil.py:27` accepts `ANTHROPIC_API_KEY or CLAUDE_API_KEY` (LM-1a); `timeout=90` on the 4 SDK client constructions (LM-6).
2. Rewrite `llmpreflight.py` to probe the **actual money-path classes** (`claudeutil.ClaudeTrader` etc. + a literal mirror of the bot's `genai.Client()`; Claude schema probe uses `claudeutil._claude_output_config()`) instead of the `llm_utils/` clients — a green preflight then structurally guarantees the panel constructs. Public contract unchanged ⇒ zero `crypto_trading_bot.py` edits. Rework `tests/test_model_registry.py` monkeypatches accordingly (rebind the importing module's names per AGENTS.md); add the parity test (preflight and panel construct the same class). `llm_utils/` itself is untouched and keeps serving `llm_compare.py`.
3. Evidence: suite green (stated count delta from the test_model_registry rework), silent bot import, one real full-panel preflight probe (cents, pre-authorized).

### L1 — Bot stream, part 2 (small, each separately committable)
- **MP-5 warn-only:** startup `[CONFIG WARNING]` when the primary LLM isn't in `--compare-llms` (its analysis is paid for but its vote won't count).
- **LM-5, delete with documented supersession** (owner call 2026-07-19: remove if truly redundant, but record what was superseded). Redundancy verified: zero call sites and zero doc references on both `main` and `josh`, no `__main__` entry point; capability parity confirmed — `compare_recommendations` (2-LLM equality check) and the `require_consensus=True` path of `get_consensus_action` are fully covered by josh's `PanelDecision`/`process_coin_with_comparison` (N-model consensus including the 2-model case, plus abstain handling, symbol binding, block reasons). Delete both from `claudeutil.py` + shrink the `crypto_trading_bot.py:23` import, and in the same commit create **`docs/SUPERSEDED.md`** with the first entry: what the helpers did, where they lived on main (`claudeutil.py:147/:180`), what replaced them, and the one behavior **intentionally not carried forward** — `get_consensus_action(require_consensus=False)` returned Gemini's vote alone (fail-open single-model fallback), deliberately dropped because it violates the fail-closed money-path invariant.
- **Log fixes:** gate the two unconditional full-LLM-text dumps (`:2402`, `:2537`) behind the existing `LOG_INTEGRATION_ROUNDS` flag (why: they bloat the cron log the runbook appends to forever); add `traceback.print_exc()` to the two consensus-path exception handlers (why: an unattended run's only clue today is a one-line `str(e)`), preserving the pinned `block_reason` strings.
- **Import hygiene (TS-3/CQ-4):** subprocess import-purity test, then move `load_dotenv()` into `main()` — makes the documented "import is side-effect-free" invariant actually true and pinned.
- **Prompt centralization (LM-2, builders only)** (why: the analysis prompt exists in ~20 verbatim copies across 5 files, so every prompt tweak — the most frequent change in an LLM bot — is a 5-file edit that can drift into panelists being asked different questions): golden characterization tests capturing today's exact prompt text per call site → `panelprompts.py` with 4 builder functions (+ `preamble`/`vote_instruction` params for the grok/perplexity variants); the 5 call sites keep only SDK plumbing; byte-identical output enforced by the golden tests. **Not** rewriting `get_llm_response`'s dispatch (deferred); dex-discovery prompts out of scope.
- **Checkpoint 3:** Fable gate on L1 diffs, Opus gate on L5; reflections; commit proposal (provider-util fixes, preflight rewrite, and one commit per bot item).

## Phase 4 — Make the repo navigable + minimal guardrails

### L6/L7 (why: 37 root markdown files — including a 407KB pasted chat transcript and a "core design doc" that predates the entire safety model — is the single biggest obstacle to a human or agent understanding this repo)
- Doc reorg: create `docs/design/` (specs for unbuilt features) + `docs/archive/` (historical plans); move per EVAL's disposition table; **delete** `Restore Directional Analysis.md` + empty `.windsurf/workflows/g.md` (owner sign-off at checkpoint); demote `CRYPTO_TRADING_BOT.md` to `docs/design/` with a superseded banner, repointing `README.md:123,228` at AGENTS.md/OPERATIONS_MANUAL. llm_compare docs (DX-5, feature stays): keep `README_LLM_COMPARE.md` + `LLM_COMPARE_OPERATIONS_MANUAL.md` as the two live docs; move `LLMCompareFeature.md` + `GENERAL_PURPOSE_LLM_COMPARE_AND_INTEGRATE_FEATURE.md` to `docs/design/` with superseded banners and replace their retired `claude-sonnet-4-20250514` references with a pointer to `modelregistry.py`/MODELS.md. Fix the README directory tree (`tradbot/`, `live_trades/`, runtime-created annotations) and the stale `.gitignore:64-67` comment. One AGENTS.md line defining the convention. Add a small mermaid diagram of the runtime path to README (restating AGENTS.md:75's existing prose map — no new research).
- Two-line cross-reference docstrings in `historyutil.py` and a "this is the Coinbase trader" docstring on `BlobbyTrader` (the renames themselves: deferred).
- Tag the 5 untagged error prints in `coinbaseutil2.py` with `[ORDER]`/`[COINBASE]` (they currently escape log grep).
- **CI (OPS-4, minimal):** one GitHub Actions workflow running `pytest tests/ -q` + the hygiene script on PRs (why: multiple users share this repo and today nothing runs the suite automatically). Suite is network-blocked, so this is CI-safe.
- `check_staged_hygiene.sh`: add mnemonic/base58/`*_MNEMONIC`/`SOLANA_PRIVATE_KEY` detection (why: a committed wallet mnemonic — directly spendable — passes the current check).
- **AGENTS.md prose (Opus):** GV-4 threat-model paragraph (web-search/discovery steering surface + peer-text channel, with the existing backstops) and the GV-1 acceptance note (pre-cleanup per-user data exists in shared remote history, intentionally preserved, never rewrite; forward protection = allowlist + hygiene script). One help-text line documenting the daily-cap contract (MP-10).
- **Main→josh supersession map (Opus 4.8, verification-heavy):** expand `docs/SUPERSEDED.md` (seeded by LM-5 in Phase 3) into the full capability map of the old application vs the new: for each main-branch capability, its status in josh — kept / upgraded / replaced-by-what / intentionally changed. Must cover at minimum: trading default **live→whatif + double-lock** (main users' launch commands and cron entries will need `--live` + `LIVE_TRADING_CONFIRMED=1` to keep trading live), 2-LLM consensus → `PanelDecision` fail-closed panel, delimiter-only parsing → structured votes with hardened fallback, hardcoded model IDs → `modelregistry` + env overrides, no ledger → intent/fill ledger + caps + reconciliation, plus this plan's own behavior changes (satellite live modes now need the interlock; whatif enforces exclusion/daily cap; corrupt ledger blocks). Every entry verified against both branches per the removal discipline — this document is what a main user reads to understand the upgrade.
- LICENSE file per owner's choice (or an explicit "private, all rights reserved" README line).
- **Checkpoint 4:** reflections + commit proposal (doc moves / polish / CI as separate commits).

## Phase 5 — Acceptance & wrap

- Full suite + silent import + bare `pytest --collect-only` shows only `tests/` nodes.
- Cheap E2E: `HISTORY_DIR=/tmp/tradbot_scratch ./venv/bin/python crypto_trading_bot.py --trading-mode=whatif --llm-mode=gemini --coins=BTC` (1 LLM call).
- Full-panel preflight one-liner (cents) — now exercising the real trader classes.
- Final Fable 5 sweep of the cumulative money-path diff against the EVAL findings (each ID: fixed / deferred / regression-tested).
- Annotate EVAL.md findings with outcomes; final reflection harvest; memory update; data-safety spot-check (`history/llm_compare_history.json` still on disk, ignored; no history rewritten).
- **Merge proposal (prepare only — owner executes and times it):** a short `docs/MERGE_PROPOSAL_josh_to_main.md` for Josh: confirmation the supersession map is complete, the enumerated behavior changes main users must act on (foremost: live-by-default becomes whatif-by-default — existing live workflows need `--live` + `LIVE_TRADING_CONFIRMED=1`; satellite live modes need the same variable), suite status, and open coordination questions (who runs main, when to push, whether main's README workflows need a transition note). Rationale: main users currently run a live-by-default bot with none of the safety machinery — landing this branch on main is the single highest-leverage safety action in the whole plan, and everything before this line exists to make that merge safe and understandable. **No push, no merge by agents — ever.**

## Deliberately NOT doing (and why) — so nobody re-adds these without a reason

- **llm_compare extraction (SC-2):** owner decided 2026-07-19 the feature stays in-repo. Hygiene fixes only; the check-both-stacks rule remains. Revisit only if the double-maintenance tax starts biting.
- **DEX-live hard refusal (SC-3):** owner chose warn-but-allow — full main-branch behavior preserved; the unverified-fill risk is documented in the warning. Revisit when/if the DEX path gets fill-confirmation hardening.
- **BotConfig refactor / consensus.py split (CQ-1):** pure structural change, no behavior fix. Do it only when the bot file next genuinely needs splitting.
- **`get_llm_response` dispatch-registry rewrite:** tidiness churn; the prompt builders capture the real win.
- **Grok/perplexity structured output (LM-4):** current fallback parser fails closed; migration adds probe risk for a modest abstain-rate gain. Revisit if over-abstention shows up in the whatif data.
- **LLM spend tally (LM-3):** real value, but touches every call site; revisit when API bills matter.
- **`logging` module migration (LG-3):** hundreds-of-lines mechanical churn; the runbook's per-run log file suggestion covers the practical need.
- **Renames (`BlobbyTrader`→`CoinbaseTrader`, `historyutil.py`):** docstrings deliver the clarity without 25+ call-site churn.
- **CQ-3/CQ-5/CQ-6, MP-10 sum-rework, MP-11 notice, cron alerting wrapper:** polish; none protects money or removes confusion a docstring/help-line doesn't.
- **Satellite archival, `--dex` removal, SELL path, package regrouping (ST-3):** owner-deferred; revisit after this plan lands.

## Verification (every phase)

1. `./venv/bin/python -m pytest tests/ -q` green before first commit and after every commit group (baseline ~616; expected deltas stated per commit plan).
2. `./venv/bin/python -c "import crypto_trading_bot"` silent.
3. Money-path diffs pass the Fable 5 adversarial review gate (fail-open hunt) before reaching Josh.
4. Post-Phase-0: bare `pytest --collect-only` yields only `tests/` node IDs.
5. Phase 3: real full-panel preflight probe passes against the rewritten llmpreflight.
6. Data safety at every checkpoint: no history rewritten; every data file touched still exists on disk (`ls` + `git check-ignore`).
