# SUPERSEDED — capability supersession record

This file records every capability that was **removed or intentionally
changed** on the `josh` branch relative to what existed before (including on
`origin/main`). It exists for two audiences:

1. **Anyone about to delete code** — the removal discipline (AGENTS.md /
   IMPROVEMENT_PLAN ground rules) requires that before anything is removed,
   its behavior is stated, zero call sites and zero doc references are
   verified on **both** `origin/main` and `josh`, capability parity in the
   current code is confirmed (or the dropped behavior is named explicitly),
   and the supersession is recorded **here, in the same commit as the
   removal**. A capability intentionally dropped (not just relocated) always
   needs explicit owner sign-off.
2. **Users of `main`** — several people run this bot against their own
   Coinbase accounts from `main`. When `josh` is merged, this file doubles as
   the merge changelog: for each old capability, what replaced it and what
   (if anything) was deliberately not carried forward.

Format: one entry per removal/supersession, newest first.

---

## 2026-07-19 — legacy 2-LLM consensus helpers (`compare_recommendations`, `get_consensus_action`)

**Removed from:** `claudeutil.py` (on `origin/main`: `claudeutil.py:147` and
`claudeutil.py:180`; on `josh` immediately before removal: `:200` and `:233`),
plus their names in the import at `crypto_trading_bot.py` (main `:15`,
josh `:24`). Finding LM-5, audit `docs/audit-2026-07-19/EVAL.md`; owner
decision 2026-07-19: delete with documented supersession.

**What they did:**

- `compare_recommendations(gemini_rec, claude_rec)` — compared exactly two
  recommendation strings (hardcoded Gemini-vs-Claude), returning a dict with
  `agree`, both normalized votes, a HIGH/LOW `confidence` label, and
  `consensus` (the shared vote, or `None` on disagreement / any missing
  vote).
- `get_consensus_action(comparison_result, require_consensus=True)` — turned
  that dict into an action. With `require_consensus=True`: the consensus
  action, or `None` (with a `[DISAGREE]` print) when the two disagreed. With
  `require_consensus=False`: **returned the Gemini vote alone**, ignoring
  disagreement entirely.

**Verification before removal (both branches, 2026-07-19):** zero call sites
beyond the `from claudeutil import ...` line in `crypto_trading_bot.py`
itself; zero test references; zero doc references; no `__main__` entry point.
Both functions were dead weight on both branches — imported, never called.

**What replaced them:** the `PanelDecision` machinery in
`crypto_trading_bot.py` (`process_coin_with_comparison` + `decide` +
`decision_allows_trade`), which covers everything the helpers did and more:
N-model fail-closed consensus (including the 2-model case the helpers
hardcoded), explicit abstain handling with per-LLM reasons (`error`,
`parse_failure`, `refusal`, `symbol_mismatch`, `client_init_failure`),
symbol binding of every vote to the coin under analysis, structured
`block_reason` strings on every blocked decision, quorum enforcement, and
tiebreaker validation. Consensus/parser behavior is spec'd by
`tests/test_consensus.py`.

**Intentionally NOT carried forward (owner-approved):** the
`require_consensus=False` single-model fallback — the path where a
disagreement (or missing Claude vote) resolved to **Gemini's vote alone**.
This is fail-open: an error or disagreement shrank the effective panel to one
model and could still trade. It directly violates the repo's core money-path
invariant ("an error, refusal, missing panelist, or unparseable vote must
block a trade, never shrink the quorum or fall back to a single model" —
AGENTS.md). In the current machinery the nearest configuration is
`REQUIRE_CONSENSUS=false` **with an explicit tiebreaker**, which still
requires quorum (≥2 real votes), still blocks on abstains-with-errors under
consensus, and never silently substitutes a lone model's vote. Anyone who
wants single-model behavior must ask for it explicitly with
`--llm-mode=<provider>` (a solo mode, honestly labeled as such in history
records), not get it as a silent degradation of a 2-model panel.

---

# Full capability map — `origin/main` (old application) → `josh` (new)

This is the complete adoption changelog for anyone running the bot from
`origin/main`. `josh` is **13 commits / 100 files / +18k−4k lines** ahead of
`origin/main` (`github.com/prsprs/tradbot`). Each row below states, for a
main-branch capability, its status in `josh`: **kept** (unchanged),
**upgraded** (same purpose, stronger implementation), **replaced**
(different mechanism), **intentionally changed** (behavior differs on
purpose), or **removed** (with parity note). Nothing a main user relies on
was dropped without a replacement or an explicit note here — that is the
removal discipline (AGENTS.md hard rule #4 / IMPROVEMENT_PLAN ground rules).

**Verification method (applied to every row):** each claim was checked
against **both** sides — `git show origin/main:<file>` and `git grep` /
counts on `origin/main` for the old side, and the **working tree** (not just
`josh` HEAD — this branch's Phase 0–4 changes are uncommitted) for the new
side. The per-row "verified" line records the specific commands' outcomes.
Suite at time of writing: **723 passed** (`./venv/bin/python -m pytest
tests/ -q`).

| # | Capability on `main` | Status in `josh` | What a `main` user must know |
|---|---|---|---|
| 1 | **Trading default = LIVE** (`--trading-mode` help: "default: live"; a bare run traded real money) | **Intentionally changed** — default is now **whatif**, live requires a **double lock** | **Action required:** launch commands / cron entries that relied on the live default now run in **what-if**. To keep trading live you must pass **`--live` AND set `LIVE_TRADING_CONFIRMED=1`**. `--trading-mode=live` alone no longer enables live (it is downgraded to whatif with a loud notice). |
| 2 | **2-LLM consensus** via `process_coin_with_comparison` (delimiter parse + tiebreaker) and dead helpers `compare_recommendations` / `get_consensus_action` | **Upgraded / replaced** — `PanelDecision` fail-closed N-model panel (same entry-point name, new internals); helpers deleted (see the LM-5 entry above) | Consensus is now fail-closed: any error / refusal / unparseable vote / missing panelist **blocks** the trade instead of shrinking the quorum. |
| 3 | **Single-model modes** (`LLM_MODE=gemini/claude/...` returned one model's rec directly; `require_consensus=False` fell back to Gemini alone) | **Intentionally changed** — solo modes still exist but are **honestly labeled** (`trading_mode`/history records say so); the silent fail-open fallback is gone | See the LM-5 entry above. Ask for single-model behavior explicitly with `--llm-mode=<provider>`; you no longer get it as a silent degradation of a panel. |
| 4 | **Delimiter-only LLM parsing** (`get_text_between_strings`, `-PRS-` … `**>`) | **Upgraded** — schema-enforced structured votes (`voteschema.py`) for gemini/claude/openai; the hardened delimiter parser survives only as a **loudly-logged fallback** for grok/perplexity | More robust vote extraction; malformed/partial LLM output fails closed to `abstain('parse_failure')` rather than mis-parsing. |
| 5 | **Hardcoded model IDs** (e.g. `models/gemini-2.5-pro` inline) | **Replaced** — all IDs live in `modelregistry.py` with env overrides (`GEMINI_MODEL`, `CLAUDE_MODEL`, `OPENAI_MODEL`, `GROK_MODEL`, `PERPLEXITY_MODEL`) | Provider IDs rot fast; override per-provider via env or edit one file. `main`'s inline IDs predate the registry and are partly dead. |
| 6 | **No execution ledger** (positions tracked ad-hoc via `live_trades/*.json`; no spend caps) | **Replaced (new capability)** — `executionledger.py`: intent/fill rows, `positions_from_rows`, per-order + per-run + per-UTC-day **spend caps**, plus `scripts/reconcile_positions.py` | Real orders now recorded as intent→fill with duplicate protection; caps (defaults $5 / $10 / $15) gate spend. |
| 6a | *(this session)* corrupt-ledger handling | **New behavior** — a corrupt `executions.json` is **quarantined** (`.corrupt-<ts>`, never deleted) and, in live, **auto-restored** from the newest `.bak-<date>` snapshot; only with no snapshot does it refuse the buy (error text carries the recovery command). Run-start snapshots + sibling `.lock` files close the wipe/reset and concurrent-write races. | A corrupt money record can no longer be silently replaced by an empty file (which would also reset the daily cap to $0). |
| 7 | **LLM live-mode preflight**: none | **New capability** — `llmpreflight.py` probes the actual money-path panel classes so a green preflight structurally guarantees the panel constructs | `main`'s `preflight.py` (trading-pair **profitability** validation, a different thing) is **kept unchanged**; `llmpreflight.py` is additive. |
| 8 | **Market-data assembly** (candles fetched inline) | **Upgraded** — `marketdata.py` centralizes Coinbase OHLCV + Fibonacci + CMC + LunarCrush SOCIAL into one per-coin cached block injected into every prompt | Panelists now analyze on real supplied data (this is what fixed the "models refuse/HOLD by default" artifact). |
| 9 | **Satellite live trading** (`leading_indicator_tester.py`, `lp_arbitrage.py` could place real Jupiter swaps with no safety interlock) | *(this session)* **Intentionally changed** — both now require `LIVE_TRADING_CONFIRMED=1`; without it a live request prints a `[LIVE LOCK]` banner and **downgrades** to paper/whatif (tools stay usable for research) | **Action required:** to run these two tools live, export `LIVE_TRADING_CONFIRMED=1` (same interlock as the main bot). |
| 10 | **whatif simulation** (`status='simulated'`) | **Upgraded** — whatif now enforces the **exclusion list** and the **daily cap** too, and records estimated fees; `status='simulated'` and honest `trading_mode` labels unchanged | whatif data is the learning loop's input; it no longer "buys" things live never could. |
| 11 | **Bare `pytest`** collected real modules — firing an authenticated Coinbase call and collecting two real-swap functions | *(this session)* **Intentionally changed** — `pytest.ini` scopes collection to `tests/`; the three real-swap scripts renamed `test_*` → `probe_*` (`probe_coinbase.py`, `probe_jupiter_swap.py`, `probe_trustwallet_swap.py`) | Bare `pytest` / `pytest --collect-only` is now safe; it no longer touches the exchange. Old `test_coinbase.py` etc. are the `probe_*` files. |
| 12 | **`history/` .gitignore** — name-by-name denylist (let real user data get committed once) | *(this session)* **Replaced** — allowlist (`history/*` + `!__init__.py`/`!recorder.py`/`!test_expected_output.csv`/`!test_recommendation_data.json`); `check_staged_hygiene.sh` aligned + mnemonic/base58 detection added | Per-user data under `history/` can no longer be accidentally committed. |
| 13 | **`coinbaseutil2nokey.py`** (248-line dead duplicate of `coinbaseutil2.BlobbyTrader`, header `#foo`, keys-as-args variant) | **Removed** (already committed on `josh`, commit `a2edfc2`) | **Parity:** zero `.py` references on `main` or `josh`; identical trader capability lives in `coinbaseutil2.py`. Recoverable from git history. No user-facing loss. |
| 14 | **No top-level `requirements.txt`** (only `requirements_{correlation_tracker,dex,llm_compare}.txt`) | **New** — top-level `requirements.txt` with real floors (`coinbase-advanced-py>=1.8,<2`, `anthropic>=0.94.0`, `openai>=1.66.0` — old floors crashed 2 of 5 panelists) + new `requirements_dev.txt` (pytest) | **Action required:** run `pip install -r requirements.txt` (and `requirements_dev.txt` to run the suite) after adopting `josh`. |
| 15 | **Root doc sprawl** (37 root markdown files incl. a 407 KB pasted transcript) + junk files (`--use-fib`, `output6,tmp`) | **Reorganized** — specs moved to `docs/design/`, historical plans to `docs/archive/`; junk files removed; `CRYPTO_TRADING_BOT.md` demoted with a superseded banner | Feature/spec docs are preserved, just relocated. Nothing describing a live feature was deleted. |
| 16 | **Pre-cleanup per-user data** in shared remote history (`history/recommendations.json`, `live_trades/*`, `history/llm_compare_history.json`) | **Kept, intentionally preserved** — untracked (`git rm --cached`) but **still on disk**; git history is **never rewritten** | See AGENTS.md hard rule #3 (GV-1): pulled-down shared history is treated as intentionally preserved. Forward protection is the allowlist + hygiene script, not a purge. |

| 17 | **Two non-spec files** — `Restore Directional Analysis.md` (407 KB pasted Windsurf/Cascade chat transcript) and `.windsurf/workflows/g.md` (0 bytes, empty) | **Removed, no replacement** (owner-approved in-session 2026-07-19) | Neither described a live capability: one was a raw chat log, the other empty. Both recoverable from git history. |

**Sweep for anything a `main` user would miss (not in the plan's minimum list):**
`git ls-tree -r --name-only origin/main` was diffed against the working
tree. Every main-branch `.py`, `.txt`, `.yaml`, `.ts`, and `.json` code /
config file is still present on disk **except**: `coinbaseutil2nokey.py`
(row 13, dead duplicate) and the four `test_*`→`probe_*`/`generate_*` renames
(rows 11, and `tests/generate_multi_pair_test.py`→`tests/generate_multi_pair_data.py`).
All feature modules `main` shipped — `correlation_tracker.py`,
`lp_arbitrage.py`, `lp_analyzer.py`, `lp_history.py`, `leading_indicator_tester.py`,
`llm_compare.py` (+ `llm_utils/`, `prompts/`, `config.py`),
`fibonacci_analyzer.py`, `candidate_util.py`, `polymarketutil.py`,
`coingeckoutil.py`, `coinmarketcaputil.py`, `lunarcrushutil.py`,
`santimentutil.py`, `refresh_coin_cache.py`, `dex/*`, `context/*`,
`preflight.py` — are **kept**. No live feature was removed. The only
capability intentionally dropped in the whole diff is the fail-open
single-model consensus fallback (rows 2–3, LM-5 entry above), owner-approved.
