# Tradbot Evaluation — Lessons Learned (2026-07-18)

**Origin:** A full-day hands-on evaluation session: syncing 50 commits from upstream, upgrading all three LLMs to frontier models (Gemini 3.1 Pro, Claude Opus 4.8, GPT-5.5), running the bot in what-if and live modes (~10 runs, 3 real $5 trades), scoring the historical recommendation record, and fixing three real bugs found along the way. This document records the empirical findings and two independent code audits, as the starting point for an improvement plan.

**Evaluators:** Claude (Fable 5) with session evidence; independent codebase audit by a Claude Opus 4.8 agent; data-integrity/methodology audit by a Claude Sonnet 5 agent.

**Status (end of 2026-07-18):** evidence phase COMPLETE. Parts 1–3 are the original audits; Part 4 the original priorities; Part 5 the follow-up empirical verification (every reachable claim tested — confirmations, corrections, and ~15 new findings); **Part 6 is the implementation handoff for the next session — start there.**

---

## Part 1 — Empirical findings from live operation

These are things that *actually happened* during the evaluation, not code-reading speculation. Each is a lesson with direct evidence.

### 1.1 A refusal was parsed as a BUY and real money was spent (severity: critical, now fixed)

Claude Opus 4.8 refused to recommend on ETH ("I can't provide a real-time buy/sell/hold recommendation…") but quoted the required output format as an example: `` `<**ETH-PRS-BUY**>` ``. The parser (`get_text_between_strings(text, "-PRS-", "**>")` — first match anywhere in the text) read the quoted example as a genuine BUY vote. Simultaneously, the third LLM (OpenAI) errored with a 401 and was **silently dropped from the consensus set**. Result: "unanimous consensus" = Gemini BUY + a phantom Claude BUY → a real $5 ETH market order.

**Lessons:**
- Free-text parsing of LLM output is a *money-path* component and must be engineered like one. Fixed in this session with `extract_recommendation()` (strips backtick-quoted spans, exact-keyword match, last occurrence wins), but the deeper fix is **structured output**: every provider now supports schema-enforced JSON (`output_config.format` on Claude, structured outputs on OpenAI/Gemini). A trading decision should never be regex-scraped from prose.
- **An errored LLM must not silently shrink the quorum.** "All LLMs agree" degraded to "all LLMs that didn't crash agree" — under `require_consensus=true`, an API error or refusal should block the trade (fail-closed), not be excused from voting (fail-open).
- Frontier models increasingly refuse to roleplay confident recommendations without data. Refusals are now a *normal* response class and the pipeline must have an explicit representation for them (abstain ≠ HOLD ≠ parse failure).

### 1.2 The integrate-mode tiebreaker overrides the majority — and the tiebreaker is the bull (severity: high, unfixed)

In integrate mode, ETH finished **Gemini: BUY, Claude: HOLD, OpenAI: HOLD**. Instead of taking the 2-of-3 majority (HOLD), the disagreement was resolved by the tiebreaker — which defaults to Gemini, the same model that voted BUY and is also the primary. A real $5 ETH buy executed against the majority. Structurally: with `tiebreaker == primary`, any split where the primary is on one side resolves the primary's way. `Require Consensus: True` is decorative in integrate mode.

The aggravating detail: Claude's round-2 analysis *specifically flagged* that Gemini's cited figures might be confabulated and sided with OpenAI's caution — the multi-LLM debate surfaced exactly the right epistemic concern, and the vote structure then discarded it.

**Lessons:**
- Consensus semantics must be uniform across modes and honestly named. Options, most conservative first: (a) disagreement = no trade in all modes; (b) majority vote, tiebreaker only for genuine ties; (c) at minimum forbid `tiebreaker == primary`.
- The value of multi-LLM comparison is adversarial error-checking. Any aggregation rule that lets one model unilaterally override the panel destroys the purpose of paying for the panel.

### 1.3 The historical record shows no investing skill — and the feedback loop that would reveal this is broken

Manual scoring of all 27 pre-July recommendations against current prices:

| Rec type | Count | Correct | Avg price change since rec |
|---|---|---|---|
| BUY | 9 | **0** | **−28.1%** |
| SELL | 1 | 1 | −51.3% (BONK) |
| HOLD | 17 | n/a | −24.8% |

Caveats: the whole meme-coin market fell ~20–30% in that window, and the bot targets short-term moves while this scoring spans 3 months. But the BUYs (−28.1%) did *worse* than the same period's HOLDs (−24.8%) — no evidence of selection alpha even relative to its own inaction.

Worse, `tradeanalyzer.py` itself reported **nothing** — its scoring windows (24–48h, 2–7d, 7–8d ago) had zero recommendations in them, because nobody ran it on the required cadence. All 31 historical records aged out unjudged. A performance feedback loop that only works if a human remembers to run it daily is not a feedback loop.

**Lessons:**
- Run the analyzer automatically (cron/launchd, or at the start of every bot run) and widen/parameterize the windows so records can't silently age out.
- Score against a benchmark (vs. holding BTC, vs. the coin's sector) — raw up/down correctness rewards bull markets, not skill.
- Track actual positions and PnL including fees, not just recommendation correctness. A $5 Coinbase market order pays roughly 1–3% in fees/spread round-trip; at that size the strategy must clear a high bar before "correct direction" means "made money."

### 1.4 What the LLMs receive vs. what the prompts imply (information quality)

Observed across ~10 runs with frontier models:

- **The only hard data provided is Google Trends minute-level search interest** (plus spot price recorded separately for history). The prompt then asks what a "sophisticated trading bot" would do. Gemini (with live search grounding) responds with detailed RSI values, EMA levels, ETF flow figures, and dated news; these matched Coinbase spot prices when checkable, but Claude repeatedly (and correctly) flagged them as unverifiable-by-the-panel. OpenAI mostly declines specifics. The result: three models reasoning from **three different effective information sets** while the code treats their votes as comparable.
- **Trends data is only meaningful for majors.** BONK and SHIB returned all-zero minute-level series (search volume below Google's granularity floor); the pipeline fed zeros to the LLMs anyway. ETH's fetch hit a 429 (pytrends is unauthenticated and rate-limits under repeated use) and the coin was silently analyzed with no trends at all — no run-level flag that the primary signal was missing.
- **"Meme coin" framing misfires:** the prompts call every coin a meme coin unless the `ANALYZE_COINS` *env var* is set — but the `--coins` CLI flag doesn't set the env var, so BTC/ETH/SOL runs via the flag still ask about "the meme coin BTC," which frontier Claude models push back on (wasted tokens, occasional refusal, format breakage).
- **Frontier models converge on HOLD when under-informed.** With better models, the pipeline became dramatically more trade-shy: near-universal HOLD verdicts explicitly justified by "insufficient data." This is epistemically correct behavior colliding with a pipeline that under-supplies data. The fix is not weaker models; it is feeding real market data (OHLCV, volume, order-book summary, computed indicators) so the models have something to analyze.

**Lesson:** the binding constraint on analysis quality is the *input data pipeline*, not model intelligence. Upgrading models made decisions safer but not better-informed.

### 1.5 Model/API churn is a standing operational risk

Found and fixed during this one session:
- Claude model ID was retired (`claude-sonnet-4-20250514` → 404) — the bot had been silently degrading to Gemini-only "consensus" in compare mode.
- Sonnet 5/Opus 4.8 return thinking blocks; `message.content[0].text` crashed (`ThinkingBlock` has no `.text`). Fixed by selecting the first text block.
- Gemini 2.5 Pro's successor (`gemini-3-pro-preview`) was already *shut down* by the provider; the current ID is `gemini-3.1-pro-preview`.
- GPT-5.x rejects `max_tokens` (now `max_completion_tokens`) and `temperature`; also `gpt-5.6` is gated behind identity verification (401) while `gpt-5.5` works.

**Lessons:**
- Model IDs belong in config (env/`.env`/config.py), not hardcoded in two parallel client stacks (`claudeutil.py` *and* `llm_utils/claude_client.py` each carry their own copy).
- A startup **preflight probe** (1-token call per configured LLM) would turn silent quorum shrinkage into a loud pre-trade failure. The repo already has `preflight.py` for live trading checks — LLM health belongs in it.
- An LLM-call failure in live mode deserves a hard decision: abort the run or explicitly proceed with a reduced, logged panel — never a one-line print that scrolls past.

### 1.6 Order execution is fire-and-forget

The live SOL and ETH buys printed `[ORDER] ID: N/A | Status: N/A | Success: True | Filled: N/A`. The Coinbase create-order response nests the order ID under `success_response`, and fill details require a follow-up `get_order` call — so the bot never actually confirms what it bought, at what price, or whether the order filled. There is also no position record: history stores *recommendations*, not *executions*, so the system cannot know what it holds, and there is no exit logic (no stop-loss, no take-profit, no sell path for CEX positions).

**Lesson:** a trading system's ledger of record must be its own executions (order ID, fill price, size, fees, timestamp), reconciled against the exchange. Recommendations-only history cannot support PnL, risk management, or even "what do I own?"

### 1.7 Session-level safety observations

- **Live-by-default is a footgun.** `--trading-mode` defaults to `live`; a bare `python crypto_trading_bot.py` with valid keys places real orders. Every one of today's simulated tests had to remember `whatif`. Default should be the safe mode, with live requiring an explicit flag (and ideally a confirmation or `LIVE_TRADING_CONFIRMED=1`).
- **Fixed $5/$25 notional is hardcoded** at the two `market_order_buy` call sites — position sizing is a code edit, not a parameter.
- The evaluation stayed within a 5-trade/$5 cap only because a human enforced it; the bot has no run-level or daily spend limit.

### 1.8 What genuinely works well

Credit where due — the architecture's core bets were validated today:

- **Consensus gating works.** In compare mode, every disagreement correctly blocked action across ~8 live/simulated runs. The single legitimate live trade of the day (SOL BUY on a real search-interest surge) had genuine 2-model agreement.
- **Multi-LLM adversarial review is real, not theater.** Claude caught Gemini's unverifiable specifics; OpenAI independently refused false confidence; Gemini's BONK analysis surfaced a specific, dated treasury-exploit narrative via search grounding and produced the day's best single piece of analysis (a well-reasoned SELL on an asset down 51% since April).
- **The what-if mode faithfully mirrors the live path** (same LLM calls, same parsing, same history records) — an excellent testing affordance.
- **History recording is consistent and append-only**, with source/mode/consensus metadata that made this retrospective evaluation possible at all.
- The upstream feature direction (correlation tracker, Fibonacci analysis, preflight validation, leading-indicator tester) points correctly at the biggest weakness identified here: grounding decisions in real market data.

---

## Part 2 — Codebase & programming practices audit (independent, Opus 4.8)

*Independent code audit; scope: `crypto_trading_bot.py` (~1570 lines), `coinbaseutil2.py`, `claudeutil.py`, `openaiutil.py`, `llm_utils/*.py`, `historyutil.py`, `config.py`, `tradeanalyzer.py`.*

### 2.1 Architecture & organization

**Two parallel, non-interoperable LLM client stacks.** `claudeutil.py`/`openaiutil.py`/`grokutil.py`/`perplexityutil.py` (bespoke `*Trader` classes — what the live bot actually uses) vs. `llm_utils/` (a cleaner `LLMClient` ABC with per-provider clients — used only by `llm_compare.py`). The better-designed stack is not the one touching money. Both stacks hardcode duplicate model IDs (`claudeutil.py:11` and `llm_utils/claude_client.py:20`) — textbook parallel-path drift.

**The main script is a procedural script, not a program.** No `main()`, no `if __name__ == "__main__"` guard; argument parsing, client construction, and the entire trade loop execute at module top level (`args = parse_args()` at :217, `client = genai.Client()` at :964, buy loop at :1362–1536). The file cannot be imported for testing without triggering live API calls; global mutable state is threaded through functions via `global`.

**Massive prompt duplication.** The discovery prompt and the `<**COIN-PRS-BUY**>` delimiter instruction are copy-pasted across ~10 methods in 5 files; any wording change requires ~10 synchronized edits. `llm_compare.py` already demonstrates the right pattern (`prompts/templates.py`), unused by the bot.

**Dead/vestigial code.** `coinsToSell`/`coinsToHold` declared (:258–260) and never used; `coinbaseutil2nokey.py` near-duplicates `coinbaseutil2.py`; a stray 15 KB file literally named `--use-fib` (captured stdout of a mis-redirected command) is committed at the repo root. ~40 feature `.md` docs (some 90–110 KB) dwarf the code with no index of implemented-vs-aspirational.

### 2.2 Robustness & error handling

- **Silent exception swallowing on the money path.** `market_order_buy` catches everything, prints, returns `None` (`coinbaseutil2.py:60–62`) — and the CEX caller **discards the return value** (`crypto_trading_bot.py:952`): a failed buy is indistinguishable from success; the run summary still lists the coin as bought. The DEX branch checks `result.get('executed')`; the CEX branch doesn't — inconsistent success semantics.
- **No fill confirmation.** `_log_order_result` prints but nothing programmatically inspects `success`/`failure_reason`; an order response with `success: false` is treated as a completed buy.
- **LLM failure mid-consensus degrades silently.** If fewer than 2 LLMs respond, the code falls back to whichever single LLM answered (:858–860) — consensus protection dropped without the `REQUIRE_CONSENSUS` gate applying. Two `None`/empty recommendations can count as "agreement" on `''` (:868, :913) — a false-consensus-on-empty-string bug. The outer `try` (:801–932) swallows any Round-2 exception and silently reverts to the primary's Round-1 call.
- **Brittle delimiter parsing** (`<**NAME-PRS-BUY**>` scraped from prose) — hardened this session after being burned, but the whole scheme should be replaced with structured output. Coin discovery parsing is a cascade of guesses (`+++SYM+++` → `**SYM**` → `(SYM)` → first word after `1.`).
- **Pervasive hardcoding:** buy size `'5.00'` as a string literal (twice); model IDs pasted 5× in the main script; `coinsToExclude = {'TRUMP'}` buried mid-file; inline magic values throughout.

### 2.3 Configuration

Three competing mechanisms: `config.py` (clean dataclass — serves only `llm_compare.py`), the bot's own `parse_args` + ~40 module-level globals, and env-var defaults. Two arg parsers duplicate flags with different semantics. `get_config_source` reconstructs provenance by scanning `sys.argv` with prefix matching (fragile). **Live trading is the default** (`--trading-mode` default `'live'`, :58) — running with no arguments spends real money, with no confirmation, no spend ceiling. Secrets are correctly gitignored, but `test_coinbase.py:14–15` prints the first 40 chars of API keys to stdout, and tracked `live_trades/*.json` files deserve a sensitivity review.

### 2.4 Testing

Effectively no coverage of money-touching paths. The only real pytest suite covers the Fibonacci analyzer (pure math). `test_coinbase.py` etc. are manual smoke scripts hitting live APIs. Untested: `extract_recommendation` (pure function, decides what to buy), `process_coin_with_comparison` (consensus/tiebreaker gate), `market_order_buy`/`_log_order_result`, `buy_something`, and `calculate_outcome` (defines "correctness" for the whole system). The top-level-script structure makes testing hard — a self-reinforcing gap.

### 2.5 Safety engineering for a real-money program

- **No idempotency:** fresh `uuid4` client_order_id per call — a timed-out-but-filled order can double-buy on retry. Should be deterministic per (coin, run, intent).
- **History records intent, not execution, at the wrong price:** `record_recommendation` is called *before* `buy_something` and stores the quote price, never the actual fill; the audit trail measures against prices the bot never transacted at, with no link to whether a trade occurred.
- **No position tracking.** The bot doesn't know what it holds.
- **No exits.** `market_order_sell` is defined and **never called** — the main loop only handles `'BUY'` (:1409–1418, :1529–1536). A SELL consensus is recorded to history and silently ignored. The bot can enter positions but has no code path to ever leave one — the single most serious safety gap.
- **No aggregate spend guard:** discovery can buy up to 6 coins × $5 with no per-run cap or circuit breaker.
- **Print-based auditability:** no structured logging, no run correlation IDs, no log files. Also: deprecated `datetime.utcnow()` throughout the audit-timestamp code.

### 2.6 Auditor's top 10 (verbatim priorities)

1. Flip the default to dry-run; require explicit `--live` + per-run dollar caps.
2. Check order results on the CEX path; treat `success != true` as failure; poll for fill.
3. Implement (or explicitly disable) the SELL/exit path — today every SELL is silently dropped.
4. Record actual fills after execution with deterministic client_order_id for idempotency.
5. Delete one LLM stack; standardize the bot on `llm_utils/`'s ABC.
6. Centralize prompts and model IDs (one templates module, one model registry).
7. Replace sigil parsing with structured output for decisions *and* discovery.
8. Make the script importable (`main()` + config object), then unit-test the parsers, consensus logic (incl. the empty-string false-consensus bug), and `calculate_outcome`.
9. Structured logging + machine-readable trade ledger + spend circuit breaker.
10. Repo hygiene: remove `--use-fib`, `coinbaseutil2nokey.py`, dead globals; stop printing key prefixes; review tracked `live_trades/*.json`; migrate off `datetime.utcnow()`.

**Auditor's overall verdict:** the newer subsystems (`llm_utils/`, `config.py`, `tradeanalyzer.py`) show competent design instincts, but the live bot bypasses all of them and runs as a 1570-line top-level script that defaults to spending real money, can only buy, doesn't confirm fills, has no exits, and is untested on every path that moves funds.

---

## Part 3 — Data integrity & methodology audit (independent, Sonnet 5)

*Independent methodology audit. One editorial correction from session evidence: this auditor states the Gemini calls have no search grounding — in fact the discovery/analysis path configures `GoogleSearch` grounding (`crypto_trading_bot.py:1002–1012`), and Gemini's cited prices matched Coinbase spot in live runs. The deeper point stands: the* panel *shares no common grounded dataset, and the other models cannot verify Gemini's citations.*

### 3.1 Signal quality: the Google Trends pipeline

- **Wrong instrument for the stated purpose.** `googleTrendsRequest` (`crypto_trading_bot.py:229–254`) pulls 4 hours of minute-level *search interest* — a popularity proxy, lagging/coincident at best — and it is the only quantitative signal supplied, yet prompts present it as decision-grade market data.
- **Noise treated as precision.** avg/max/min and "recent 10 values" are computed over a scaled 0–100 index that is mostly zeros for small-cap tickers (BONK, SHIB); `avg_interest: 0.0` is passed to LLMs as "actual data."
- **Failure is indistinguishable from absence.** A bare `except Exception` returns `None` for both a Google 429 and genuinely-no-data; the prompt silently omits the trends section without disclosing that collection failed.
- **Inconsistent application within a run:** in the coin-choice loop (:1368–1379), only the *first* coin's primary prompt gets trends injected (`use_trend = (i == 0)`); coins 2–5 are analyzed without it, while the comparison rounds still receive it — an inconsistent evidentiary basis for the same decision.

### 3.2 Prompt design and hallucination risk

- No prompt variant supplies price, volume, order book, or OHLC — yet all ask what a "sophisticated trading bot" would do "based on analysis of recent data," structurally inviting fabricated RSI/EMA/support-resistance specifics. Nothing instructs models to cite only supplied data or to disclose missing data.
- Discovery prompts demand "most positive social media sentiment in the last 4 hours" from models that (Gemini's grounding aside) cannot observe it — a hallucination invitation baked into the requirements.
- Parse failure is conflated with legitimate outcomes: format drift yields `None`, which downstream is indistinguishable from a genuine abstention or split.
- The "meme coin"/"cryptocurrency" framing switch primes different risk registers for identical instruments depending on mode — an unintentional framing effect (and, per Part 1, a trigger for frontier-model pushback).
- **Integrate mode can propagate hallucinations rather than correct them:** Round 2 feeds each model every peer's freeform Round-1 prose, so one fabricated statistic can be echoed as corroborating evidence across the panel. (Session evidence cuts both ways: Claude used Round 2 to *challenge* Gemini's figures — but the mechanism that then resolved the dispute was the tiebreaker, per finding 1.2.)

### 3.3 Decision methodology

- **Tiebreaker defaults to the primary** (`gemini` for both, :74 and :126): on any split, the architecture reverts to a single LLM's view — undermining the purpose of the panel (confirmed empirically in Part 1.2 with a real trade).
- Consensus is unanimous-or-nothing; there is no majority-vote option between "all agree" and "one model decides."
- `None` recommendations (refusals, parse failures, API errors) participate in agreement checks as `''` and are not logged as a distinct failure class; sub-quorum runs silently fall back to single-LLM mode.

### 3.4 History & evaluation loop

- Records capture recommendation context but **no trade size, fees, PnL, or position linkage**; the JSON list is rewritten in full on every append (O(n) writes, unbounded growth).
- The analyzer's windows (24–48h, 2–7d, 7–8d) mean records older than 192h are **permanently unjudged** with no "expired unscored" marker — the report implies completeness while silently dropping history (empirically confirmed: all 31 records fell through).
- No judged-flag is written back, so re-runs re-score and re-export duplicate CSVs.
- **Correctness is directionally naive:** any move in the recommended direction counts, regardless of magnitude, benchmark, or costs. HOLD is entirely unaccountable — and HOLD is what frontier models overwhelmingly emit (Part 1.4), so the majority of the system's output is never evaluated at all.
- No benchmark-relative scoring exists anywhere in the live loop (the separate `leading_indicator_tester.py` has PnL/cost-basis logic but is not wired in).

### 3.5 Missing trading fundamentals

- Position sizing: hardcoded flat notional, independent of conviction, volatility, or portfolio.
- Exits: no stop-loss/take-profit/time-based exit; a position closes only if a future run happens to SELL-recommend the same symbol (and per Part 2, the SELL path isn't even wired).
- Fees/slippage: a $5 Coinbase market order pays ~0.4–1.2%+ taker fee plus spread each way — the accuracy metric can call a trade "CORRECT" that lost money net of costs.
- Portfolio: no cross-coin exposure, concentration limits, or aggregate capital-at-risk view.

### 3.6 Auditor's top 10 (verbatim priorities)

1. Decouple tiebreaker from primary (or require majority among the others).
2. Track parse-failure/refusal as a distinct state excluded from agreement math.
3. Benchmark-relative correctness in the analyzer (vs. BTC/market over the same window).
4. Close the >192h evaluation gap; persist judged-flags; add an expired-unscored bucket.
5. Stop presenting Trends as decision-grade data; disclose fetch failures in the prompt.
6. Remove "sophisticated trading bot"/live-sentiment framing where no such data is supplied.
7. Fix the first-coin-only trends injection inconsistency.
8. Fee- and spread-aware PnL; link BUYs to closing SELLs in the record schema.
9. Real position sizing and exit triggers.
10. Structured output instead of delimiter parsing across all five providers.

---

## Part 4 — Consolidated priorities for the improvement plan

*(Synthesized from Parts 1–3; ordered by risk-adjusted value.)*

1. **Fail-closed consensus.** Errors, refusals, and parse failures block trades under `require_consensus`; integrate-mode disagreement uses majority (or blocks); forbid `tiebreaker == primary`.
2. **Structured outputs for all LLM votes.** Schema-enforced JSON ({action, confidence, abstain, reasons}) replaces delimiter scraping everywhere.
3. **Execution ledger.** Parse `success_response`, follow up with `get_order`, record executions (not just recommendations) with fills and fees; add a position table and a sell/exit path.
4. **Safe defaults.** `whatif` by default; live requires explicit opt-in; configurable position size; per-run and daily spend caps.
5. **Feed real market data to the panel.** OHLCV/volume/indicators from Coinbase (already available via the correlation-tracker work) in every prompt; flag missing/zero trends data instead of silently proceeding; treat Gemini's search grounding as one source among several, labeled as such.
6. **Automated evaluation loop.** Analyzer on a schedule or at bot startup; configurable windows; benchmark-relative scoring; fee-aware PnL.
7. **Config consolidation.** Model IDs, notional size, prompts out of code; one LLM client stack instead of two (`*util.py` vs `llm_utils/`); `--coins` flag sets the wording context (the `ANALYZE_COINS` env/flag split caused real misbehavior).
8. **LLM preflight probe** in `preflight.py`; hard-fail live runs on panel degradation.
9. **Tests for the money paths** — the parser regression discovered today (quoted-example-as-BUY) is exactly the class of bug a 20-line unit test would have caught; what-if mode makes integration tests cheap.
10. **Documentation hygiene** — record model-ID/API migrations (this session: Sonnet 5 thinking blocks, GPT-5.x parameter renames, Gemini 3.x deprecation cycle) in a MODELS.md so the next AI or human doesn't rediscover them.

---

## Part 5 — Second-session empirical verification (2026-07-18, follow-up session)

*A targeted test session run before implementing Part 4: offline unit tests of the parser and consensus math (scripted votes, no API calls), three what-if runs with the live 3-LLM panel (compare on BTC/ETH, integrate on ETH, compare on BONK/SHIB), and a re-run of the analyzer. No live trades were placed. Results below either **confirm**, **refine**, or **add to** Parts 1–3.*

### 5.1 Confirmed as written

- **Consensus math (offline, scripted votes).** With `require_consensus=true` in compare mode: an API-errored LLM is silently dropped and the remaining two can form a "unanimous" BUY (the exact 1.1 mechanism); a sub-quorum run (only 1 responder) returns that lone vote with `consensus=None` and the buy loop trades it. In integrate mode, the 1.2 split (primary BUY vs 2× HOLD, tiebreaker=primary) reproduces the BUY exactly. `REQUIRE_CONSENSUS` is **never consulted in integrate mode** — structurally, not just behaviorally (only the compare branch at `crypto_trading_bot.py:874` reads it).
- **The 1.2 vote pattern reproduced live** in a what-if integrate run on ETH: Round 2 ended Gemini BUY, Claude HOLD, OpenAI HOLD. With `--tiebreaker=claude` the outcome was correctly HOLD — empirically validating priority #1's "forbid tiebreaker == primary." `--tiebreaker=none` (already a supported CLI value) also blocks the trade in offline tests; both mitigations are available *today* without code changes.
- **Meme-coin framing misfire (live).** With `--coins=BTC,ETH`, Claude corrected the premise ("BTC is not a meme coin") and refused both coins. Refined below in 5.2/5.3.
- **First-coin-only trends injection (live).** In the BTC/ETH compare run, only BTC's prompts carried trends; every ETH prompt (all three LLMs) went out with no quantitative data at all.
- **Gemini's grounded-but-unverifiable specifics (live, twice).** ETH analyses cited RSI 47–56, $1,840–$1,950 levels, $105M ETF inflows, a pending CLARITY Act vote, and "$1.2B taker buy volume after the July 15 CPI print." In Round 2, Claude explicitly called these "fabricated-sounding specifics ... may be invented to justify a predetermined conclusion" and sided with OpenAI — the adversarial-review value of 1.8, again resolved only by whoever the tiebreaker happens to be.
- **Frontier panel is trade-shy (live).** 3 what-if runs, 5 coin-analyses, 0 trades: every single one blocked on disagreement (typically Gemini directional vs OpenAI HOLD-by-default vs Claude refusal-or-HOLD).
- **Analyzer scores nothing (live re-run).** With 43 records on file (16 less than a day old), all three windows again matched zero.

### 5.2 Refinements and corrections to Parts 1–3

- **The "false consensus on empty string" bug (2.2) is real but currently harmless to the money path.** If *all* parseable votes are None they collapse to agreement-on-`''`, but the returned action is `None`, so no trade fires and (because recording is gated on a truthy action) no history record is written. The consensus *flag* is polluted, money is not. A genuine vote + an empty vote counts as disagreement (safe).
- **Refusals currently act as a hard veto in compare mode, not a fail-open.** Because a refusal parses to `None` ≠ any real vote, a refusing panelist blocks every trade. So today's failure directions are asymmetric: *refusals* fail closed (over-blocking), while *API errors* fail open (quorum shrinkage). The report's fail-closed recommendation stands, but the immediate practical effect of adding Claude to the panel is a near-total trade freeze, not phantom trades.
- **The full-name tag issue is cosmetic — with a caveat.** Both Gemini and OpenAI emitted `<**Ethereum-PRS-HOLD**>` (name, not symbol). The parsed coin name is display-only (`followUp_coin` is printed, never traded), but it exposes the real gap: `extract_recommendation` is **coin-agnostic** — it accepts any `-PRS-X**>` tag regardless of which coin it names, so a peer's tag for a *different* coin quoted unbackticked in a Round-2 response would count as a vote for the current coin.
- **`llm_source` in history is always the primary LLM**, even when the recorded action came from a tiebreaker or a fallback — the 41-of-43 "gemini" records overstate Gemini's authorship and make per-LLM accuracy attribution in the analyzer unreliable for compare/integrate records.
- **Editorial note on 3.4:** the analyzer gap is wider than ">192h": records aged **0–24h are also invisible** (no window covers them), so a record is scorable only if the analyzer happens to run while it is 24–192h old.
- **Correction to 1.5:** `preflight.py` is *not* a general live-trading preflight — it validates a specific leader/follower pair for the DEX correlation strategy (profitability analysis + Jupiter tradeability; requires `--leader`/`--follower`, verified live). The LLM-panel bot currently has **no preflight of any kind**; the proposed LLM health probe (#8) is a new capability, not an addition to an existing check.

### 5.3 New findings from this session

1. **Round-2 prompts hardcode "meme coin" for Claude** (`claudeutil.py:91` and `:130` use a literal string; Round-1 methods and all of `openaiutil.py` correctly use `self.coin_type`). Observed live: with `ANALYZE_COINS=ETH` set, Claude's Round-1 response engaged normally but its Round-2 response objected to "the meme coin" framing. So in integrate mode the framing bug is unfixable by the env var for Claude specifically.
2. **If the tiebreaker LLM itself errored out of the panel, integrate mode silently falls back to the first LLM in insertion order — the primary** (offline test; `crypto_trading_bot.py:926–927`). Configuring a non-primary tiebreaker therefore does *not* fully forbid tiebreaker==primary outcomes.
3. **Residual parser gaps (offline, 14-case suite — see `tests` candidates below).** `extract_recommendation` correctly rejects the exact 1.1 refusal, but still parses (a) a format example cited *without* backticks and (b) a tag inside a triple-backtick fenced block (only inline single-backtick spans are stripped). Both are plausible frontier-refusal shapes.
4. **The outer `try` fallback is easy to trigger and fully silent in effect** (2.2's last bullet, now demonstrated): any exception anywhere in the compare/integrate block — including a plain `NameError` — prints one line and returns the primary's Round-1 vote with `consensus=None`, which the buy loop will trade. Single-model trading by accident, wearing a multi-LLM configuration banner.
5. **History records carry no trading-mode field.** What-if and live runs write indistinguishable records into the same `recommendations.json` the analyzer scores (this session's what-if ETH HOLD is now in the file, identical in shape to a live-run record). Simulated experiments silently contaminate the performance record.
6. **All three models misread Google Trends normalization (live, BONK).** The series is scaled so the window max = 100, so on a near-dead ticker one stray minute reads as "a spike to 100." All three LLMs narrated this artifact as a real pump-and-fade ("the hype cycle has completely died") and two derived SELL votes from what is effectively an empty series. Zero-filled data isn't just uninformative — it *actively generates* confident wrong narratives.
7. **`tradeanalyzer.py` has no argument parsing at all** — `--help` (or any flag) is ignored and triggers a full run with live Coinbase price fetches. Harmless today, but it means the windows genuinely cannot be widened without a code edit, confirming 1.3's cadence trap.
8. **The consensus flag is never consulted at trade time** (`crypto_trading_bot.py:1409–1418`: the gate is `'BUY' in final_action` only). Consensus semantics live entirely inside `process_coin_with_comparison`; anything that leaks an action out of it (tiebreaker, sub-quorum fallback, exception fallback) trades unconditionally.
9. **Trends 429s are frequent under light use** (2 of 3 fetch batches this session hit one; the ETH integrate run proceeded with no trends and Gemini nonetheless opened with "Based on ... Google Trends" — asserting the missing signal). Failure-disclosure in prompts (3.1) is not hypothetical polish; the models actively paper over the gap.

### 5.4 Five-LLM panel session (Grok + Perplexity added)

With `XAI_API_KEY`/`PERPLEXITY_API_KEY` configured, `grok-4` and `sonar-pro` both work (finding 1.5's model-churn risk did not bite here). Solo what-if probes plus a 5-LLM compare run (BTC, ETH) and a 5-LLM integrate run (ETH, `--tiebreaker=none`) produced:

- **Grok is the noisiest panelist.** Solo run: bare `<**BTC-PRS-SELL**>` with *zero* reasoning text. Fifteen minutes later in the panel: BTC **BUY** (again reasonless). It was the lone dissenter blocking a 4-model HOLD in both panel runs.
- **New format-drift case:** Grok emitted `<**Ethereum - PRS - HOLD**>` (spaces around dashes, full name). The parser rejects it → Grok's HOLD silently became a non-vote. Structured output (#2) or a whitespace-tolerant pattern is needed.
- **Integration self-corrected the primary — and then propagated the abandoned thesis.** In Round 2 Gemini flipped BUY→HOLD, explicitly conceding to Claude/Perplexity's caution. But Grok flipped None→BUY *by adopting Gemini's Round-1 contrarian thesis* ("low trends = accumulation zone") — a thesis its author had just abandoned, invisible to Grok because Round 2 only cross-feeds Round-1 texts. This is 3.2's echo-propagation mechanism observed live: Round-1 prose outlives its author's own retraction.
- **`--tiebreaker=none` worked live:** final vote 4× HOLD vs Grok BUY → `[TIEBREAKER] No tiebreaker set, no action taken`. Note the flip side: a 4-of-5 majority (HOLD) was discarded entirely — not even recorded to history — because agreement is defined as unanimity. Majority-vote (#1 option b) would have captured it.
- **Perplexity is a useful second grounded voice** (live-search citations like Gemini, but voted HOLD both times with explicit "post-spike consolidation" reasoning); Grok also cites live sources in Round 2. The panel now has three different effective information sets *with* grounding asymmetry — the 1.4 comparability concern applies more, not less.
- Trends 429'd again on the integrate run (3rd of 5 batches today) — the panel analyzed ETH with no quantitative data and Gemini's Round-1 still asserted trends-based conclusions.
- The two solo probes each wrote a history record: BTC SELL and BTC HOLD, 29 seconds apart at the same price, from what-if runs — compounding the missing trading-mode-field problem (5.3.5).

**Discovery-mode what-if run (the bot's default flow, previously untested this session):** mechanically sound end-to-end — Gemini discovered DOGE/PEPE/SHIB via grounded search narratives, `+++SYM+++` parsing worked, all three coins were panel-analyzed and all three blocked on disagreement. The striking result: Gemini's *discovery* phase picked PEPE as the strongest bullish-sentiment coin ("800B whale withdrawal ... primes the token for a quick rally"), and twenty minutes later Gemini's own *analysis* phase voted **SELL on all three of its own discoveries** — including PEPE. The discovery prompt (social-sentiment framing, search-grounded) and the analysis prompt (trends-data framing) produce opposite conclusions from the same model about the same coin at the same time. Discovery narratives and analysis verdicts are not currently the same signal, and only the disagreement gate kept the contradiction from mattering. Also: the correlation/leading-indicator stack was probed live — the CLIs are extensive and Jupiter connectivity works, but `correlation_data/` does not exist; **the collection phase has never been run**, so preflight/analyzer/tester are all blocked on it (relevant to priority #5's assumption that this data source is "already available").

### 5.5 Live execution test (one deliberate $5 SOL buy + read-only reconciliation)

A single live `--llm-mode=gemini --coins=SOL` run bought $5 of SOL; follow-up read-only `get_fills`/`list_orders`/`get_accounts` calls produced the first ground-truth execution data:

- **Finding 1.6 confirmed post-fix:** the run still printed `[ORDER] ID: N/A | Status: N/A | Success: True` — the order ID and fill details are definitively nested (`success_response`), and only the follow-up `list_orders` call revealed the truth: `status=FILLED, filled_size=0.06562167, avg_price=75.28, fees=0.0593`. Everything priority #3 needs is one API call away.
- **Fees measured, not estimated:** commission on a $5 market buy = $0.0593 on a $4.94 net fill ≈ **1.2% per side**, so ≥ **2.4% round-trip before spread** — the strategy must clear ~2.5% per trade to break even at this notional, at the high end of 3.5's 1–3% estimate.
- **History vs execution:** history recorded `SOL BUY @ $75.2800` (quote price, pre-trade); actual avg fill also 75.28 this time, but the record contains no size, fee, order ID, or any link to the execution — reconciliation was only possible manually.
- **Position blindness illustrated:** the account now holds 0.1314 SOL from *two* separate $5 test buys (this session and the earlier one), plus several unrelated legacy positions; the bot's history knows about neither.
- **Missing SELL path confirmed live:** a live BONK run produced a SELL consensus — `[HISTORY] Recorded: BONK SELL ...` followed by `Coins to buy: []` and no order attempt. A live-mode SELL is recorded and silently dropped, exactly as 2.5 predicted from code reading.
- **Full round trip measured** (manual sell of the 0.1314 SOL position): $10.00 in → $9.76 out. Buys at 75.13/75.28, sell at 75.23 — the price was essentially flat (slightly *up* vs. average entry), yet the round trip lost **2.35%**, all fees ($0.0593 + $0.0593 + $0.1186 = $0.237 on $10). Empirical confirmation of 3.5: at $5–10 notional, a directionally *correct* recommendation still loses ~2.4% net; the analyzer's direction-only "CORRECT" metric is measuring the wrong thing.

### 5.6 Fibonacci subsystem test (in-session, real data)

- **The pytest suite passes 40/40** — this remains the only well-tested module in the repo.
- **The collector dependency is bypassable:** 7 days of Coinbase hourly candles (public `get_candles` API, fetched in seconds) fed to `fibonacci_analyzer.py --csv` produced coherent real-coin analyses (SOL downtrend: 65.9% overall bounce rate, 23.6% level most respected at 80%; BTC uptrend: 58.3%, 38.2% level flagged weak). This is a practical template for priority #5: the bot's LLM prompts could carry exactly this kind of computed, verifiable structure instead of raw trends noise.
- **The full integration chain works:** `--save-report` → cache → `leading_indicator_tester --bypass-leader --use-fib` loads the cached levels, applies a trend-direction trade constraint (DOWN → SELL-only), and monitors live Jupiter prices against the levels (observed live: SOL sitting 0.19% from its 78.6% retracement, correctly flagged "AT LEVEL").
- **Bug/doc gap:** `--dry-run` claims "show configuration without executing" but in bypass-leader mode it starts an *indefinite* monitoring loop (no trades, but never exits without `--duration`). Looked like a hang under buffered output.
- **Bug: `--duration` is not honored in bypass-leader mode** — a `--duration 3min` paper run went 9 cycles (4.5+ min) and only stopped on Ctrl+C. An unattended "bounded" run isn't bounded.
- **Live monitor behaved correctly on signals:** across 9 cycles SOL sat 0.16–0.22% from the 78.6% level (within touch tolerance) without bouncing or breaking; the monitor correctly emitted zero signals and held the SELL-only constraint. No false positives from a flat price on a level.
- **UX:** `--verbose` sets DEBUG on the root logger, flooding httpcore TLS/header logs that bury the one signal line per cycle.

### 5.7 Adjustments to Part 4 priorities

The Part 4 list survives contact with testing intact; adjust as follows:

- **#1 (fail-closed consensus)** — add: gate the *trade*, not just the vote function, on consensus (finding 5.3.8); when the configured tiebreaker is unavailable, block instead of falling back to the first LLM (5.3.2); and remove the outer catch-all fallback to primary (5.3.4). Interim, zero-code mitigation available today: run integrate mode with `--tiebreaker=claude` or `--tiebreaker=none` (both verified).
- **#2 (structured output)** — add: the schema must bind the vote to a coin (`{symbol, action, ...}`) since delimiter parsing is coin-agnostic (5.2); until then, note the two residual parser gaps (5.3.3).
- **#4 (safe defaults)** — add a `trading_mode` field to history records so what-if experiments stop contaminating the scored record (5.3.5).
- **#6 (automated evaluation loop)** — the window fix must cover 0–24h as well as >192h (5.2); give the analyzer argparse (5.3.7); record the actual deciding LLM(s), not `llm_source=primary` (5.2).
- **#7 (config consolidation)** — the `--coins` fix must also de-hardcode the Round-2 Claude prompts (5.3.1).
- **#9 (tests)** — the offline harnesses from this session (a 14-case `extract_recommendation` suite; a scripted-vote consensus matrix covering error/refusal/sub-quorum/tiebreaker-error cases) are ready to be turned into pytest files and already found two new bugs; this is the cheapest high-yield item on the list.
- **New #11: fix the trends signal or stop sending it.** Disclose fetch failures in the prompt, drop all-zero series for small caps (or state "search volume below Google's floor"), and explain the max=100 normalization to the models — or better, replace the signal per #5 (real OHLCV). The BONK run shows garbage-in produces *confident directional votes*, not noise, out.

*Session artifacts: what-if run logs (BTC/ETH compare, ETH integrate, BONK/SHIB compare) and offline test scripts in the session scratchpad; one what-if ETH HOLD record was appended to `history/recommendations.json` by the integrate run.*

---

## Part 6 — Implementation handoff (for the next session)

### 6.1 State of the working tree (uncommitted as of 2026-07-18 evening)

Modified, not yet committed: `crypto_trading_bot.py` (model IDs → `gemini-3.1-pro-preview`; `extract_recommendation()`; dotenv), `claudeutil.py` / `llm_utils/claude_client.py` (`claude-opus-4-8`; thinking-block-safe text extraction), `openaiutil.py` / `llm_utils/openai_client.py` (`gpt-5.5`; `max_completion_tokens`), `coinbaseutil2.py` (`_log_order_result`, $25→$5 notional), `tradeanalyzer.py` (dotenv). **Committing this working tree is a sensible first act of the next session** (with `lab/session_tests_20260718/` and this document).

### 6.2 Implementation queue — validated, ordered, with anchors

Each item is evidence-backed (Part 5 refs) and scoped small enough to verify with the harnesses in `lab/session_tests_20260718/`:

1. **History `trading_mode` field** — `historyutil.py:98–116` (`create_recommendation_record`) + pass mode from the two `record_recommendation` call sites (`crypto_trading_bot.py:1393`, `:1513`). Evidence: 5.3.5, 5.4 (what-if and solo probes wrote 6+ fake records today). Unblocks any scheduled evaluation cadence.
2. **Fill confirmation** — in `buy_something` (`crypto_trading_bot.py:936`) check the create-order return, then `client.get_order(order_id)` (or `list_orders`) and record fill price/size/fees; deterministic `client_order_id` per (coin, run). Evidence: 5.5 — everything needed is present in the follow-up call (`status=FILLED, filled_size, avg_price, fees`); `_log_order_result` (`coinbaseutil2.py:79`) must unwrap `success_response`.
3. **Consensus hardening** — three point fixes in `crypto_trading_bot.py`: (a) gate trades on `consensus` at `:1409`/`:1529`, not just the action string; (b) tiebreaker missing from `r2_recs` → block, don't fall through to first-LLM (`:926–927`); (c) delete the catch-all `except` → primary fallback (`:929–932`), let errors block. Evidence: 5.1, 5.3.2, 5.3.4, offline matrix B1–B5. Interim mitigation already available: `--tiebreaker=none` (verified live, 5.4).
4. **Pytest conversion** — port `lab/session_tests_20260718/test_extract_rec.py` (14 cases) and `test_consensus.py` (11 scripted-vote cases) into `tests/`; add regression cases: spaced tags (`<**Ethereum - PRS - HOLD**>`, 5.4), fenced code blocks (5.3.3), coin-binding (5.2). Requires making the parser/consensus importable (a `main()` guard — auditor #8) or keep the source-extraction trick the harnesses use.
5. **Prompt fixes** — de-hardcode "meme coin" in `claudeutil.py:91` and `:130` (5.3.1); make `--coins` set the framing for all providers, not just Gemini (5.1); disclose trends-fetch failure in the prompt instead of silently omitting (5.3.9); consider the fib-report template (5.6) as the first "real data" injection for priority #5.
6. **Analyzer overhaul** — argparse, window coverage 0h→∞ with an expired-unscored bucket, judged-flags, benchmark-relative + fee-aware scoring (fee floor now measured: **~2.4% round trip at $5 notional**, 5.5). Evidence: 5.1, 5.2, 5.3.7.
7. **Small bugs** — `--duration` ignored in bypass-leader mode; `--dry-run` starts an infinite monitor; `--verbose` roots-DEBUG flooding (all 5.6).

Deliberately deferred: SELL/exit path design (needs position tracking from #2 first), structured output migration (#2-of-Part-4; do after tests exist), stack unification and repo hygiene (auditor #5/#10).

### 6.3 Environment and cost facts (verified this session)

- Working model IDs: `gemini-3.1-pro-preview`, `claude-opus-4-8`, `gpt-5.5`, `grok-4`, `sonar-pro`. Keys in `.env`: `GOOGLE_API_KEY`, `CLAUDE_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `PERPLEXITY_API_KEY`. Coinbase: `cdp_api_key.json` (required even for CEX what-if runs — constructed unconditionally at `crypto_trading_bot.py:1136`).
- **Live is still the default trading mode** — every test command must carry `--trading-mode=whatif` until Part 4 #4 lands.
- Coinbase fees: ~1.2%/side measured at $5 notional; break-even ≈ 2.4% + spread.
- pytrends 429s frequently under repeated use (3 of 5 batches); Google Trends is scaled max=100 per window (all-zero + one blip ⇒ misleading "spike to 100").
- Panel behavior with frontier models: Gemini directional (grounded, unverifiable specifics), Perplexity HOLD-leaning (grounded), OpenAI HOLD-by-default, Claude refuses under bad framing/absent data, Grok erratic + reasonless. Compare mode with Claude in the panel ≈ trade-frozen.
- `correlation_data/` still does not exist; the correlation stack has never collected. The Coinbase-candles→CSV route (5.6, script pattern in `lab/session_tests_20260718/`) works without it.

### 6.4 Evaluation-methodology lessons (for whoever tests next)

- **Offline scripted-vote harnesses were the highest-yield tool of the session** — the full consensus matrix (errors, refusals, sub-quorum, tiebreaker-error) cost zero API calls and found two new bugs. Extend them before touching the consensus code.
- **What-if mode faithfully mirrors the live path** (same LLM calls, parsing, recording) — use it as the default integration test; but remember its records currently pollute history (fix #1).
- **The two $5 live trades bought answers code-reading couldn't:** the response-nesting confirmation and the measured fee floor. Budget the occasional deliberate micro-trade when a question is execution-shaped.
- **Multi-model disagreement is itself a diagnostic:** Claude's refusals located the framing bug; Grok's format drift located the parser gap; Gemini's discovery-vs-analysis self-contradiction (5.4) located the prompt-inconsistency problem. Read the dissents, not just the verdicts.
- Session artifacts: run logs + harnesses in `lab/session_tests_20260718/`; history contamination from today: ~9 what-if/probe records in `history/recommendations.json` (identifiable by timestamp 2026-07-18 17:50–18:15 UTC).

---

*Prepared 2026-07-18 during a live evaluation session. Trades referenced: SOL $5 BUY (legitimate consensus), ETH $5 BUY (parser bug — fixed), ETH $5 BUY (tiebreaker override — design issue open); follow-up session added one deliberate $5 SOL BUY + full-position SELL for execution/fee measurement (net cost ≈ $0.24). All bug fixes exist as uncommitted working-tree changes as of this writing. Parts 5–6 added later the same day.*
