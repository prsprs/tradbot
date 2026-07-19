# AGENTS.md — Working on tradbot with an AI coding agent

Canonical guidance for ANY AI coding agent (Devin, Windsurf, Codex, Grok, Claude, …) and useful for humans too. CLAUDE.md is just a pointer here. Keep this file tool-agnostic.

## What this repo is

A multi-LLM consensus crypto trading bot that places **real-money orders on Coinbase** (plus DEX experiments). Several people run it against their **own** Coinbase accounts and API keys. Treat every change to order placement, consensus/vote logic, parsing of LLM output, or spend limits as a **money-path change**: it needs tests, and it needs to be called out plainly in reports and commit messages.

## Hard rules

1. **Never place a trade or run live mode.** Live runs are for the repo owner only (they require `--live` AND `LIVE_TRADING_CONFIRMED=1` — an anti-accident interlock, not a suggestion). Read-only exchange calls (`get_accounts`, `list_orders`, `get_fills`, product/candle data) are fine.
2. **Any bot run you make must be `--trading-mode=whatif` AND redirect history**: set `HISTORY_DIR=<scratch dir outside the repo>` so `history/` (real per-user data) is never touched. Verify with an md5/mtime check if you ran anything.
3. **Never commit per-user data**: everything under `history/` (recommendations, executions ledger, backups), `live_trades/`, `.env`, `cdp_api_key.json`. The `.gitignore` enforces this — don't fight it, and don't "fix" it by force-adding.
4. **Don't commit unless the owner asked.** House style: make verified progress, leave changes uncommitted, propose a small set of consolidated commits at review checkpoints. Money-path changes stay separable from infrastructure when commits happen.
5. **Model IDs live only in `modelregistry.py`** (env overrides: `GEMINI_MODEL`, `CLAUDE_MODEL`, `OPENAI_MODEL`, `GROK_MODEL`, `PERPLEXITY_MODEL`). Never hardcode a model string elsewhere. Provider IDs rot fast (grok-4 died within weeks of being current); when in doubt run the preflight (below) or check `MODELS.md`.
6. **Small paid LLM probes are pre-authorized** by the owner for verifying model validity and call/response shapes (keep it to cents). Exchange **writes** are never authorized.

## Environment

- Use `./venv/bin/python` (3.11). The system `python3` (3.9) lacks every dependency and will fail at `from google import genai`.
- Keys come from `.env` (loaded via python-dotenv). Coinbase needs `cdp_api_key.json` at repo root — required even for what-if runs (client is constructed either way).
- `import crypto_trading_bot` is **side-effect-free** (no argv parsing, no network, no client construction — all of that happens in `main()`). Keep it that way; tests depend on it. If you add module-level code that touches network/env/argv, you've broken the repo's testability.
- **Timestamp contract (load-bearing):** history records, ledger rows, and LP files store naive-UTC timestamps with a literal `'Z'` suffix (`isoformat()` without offset + `'Z'`); `tradeanalyzer.parse_timestamp` and the LP parsers depend on this exact shape, and regression tests pin it. Do not switch any storage site to aware `isoformat()` (which appends `+00:00`) piecemeal — going timezone-aware end-to-end is a planned dedicated migration. Never compute epoch time via `.timestamp()` on a naive datetime (it assumes *local* time — this was a real 4-hour bug in `lp_history.py`); use `datetime.now(timezone.utc)`.
- **`history/` mixes per-user data (gitignored) with code**: `history/recorder.py` is source and `history/test_expected_output.csv` is a documented fixture, both tracked. If a task says "don't touch history/" it means the *data*; if it says "migrate all code" that includes `recorder.py` — ask or flag the conflict rather than guessing.

## Secrets scanning (optional)

This repo relies on `.gitignore` plus code review to keep `.env`, `cdp_api_key.json`, and key material out of commits — there's no automated scanner installed. Nobody should install one on another contributor's behalf, but if you (the repo owner) want a local pre-commit guard, [gitleaks](https://github.com/gitleaks/gitleaks) via [pre-commit](https://pre-commit.com/) is a lightweight option. Add a `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4  # pin to a current release when you install this
    hooks:
      - id: gitleaks
```

Then `pip install pre-commit && pre-commit install` once, locally, to enable it. Nothing here is installed or required by the codebase — this is a snippet for the owner to opt into, not a dependency.

## Verify before and after

```bash
./venv/bin/python -m pytest tests/ -q     # expected: all pass, 0 xfail (the 2 parser-gap xfails were cleared by T8 structured output)
./venv/bin/python -c "import crypto_trading_bot"   # must be silent
```

A single cheap end-to-end check (uses ~1 LLM call):

```bash
HISTORY_DIR=/tmp/tradbot_scratch ./venv/bin/python crypto_trading_bot.py --trading-mode=whatif --llm-mode=gemini --coins=BTC
```

LLM preflight (connectivity + model-ID validity for the whole panel, few cents):

```bash
./venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); import llmpreflight; print(llmpreflight.preflight(['gemini','claude','openai','grok','perplexity']))"
```

(The `load_dotenv()` is required standalone — the bot loads `.env` in `main()`, so `llmpreflight` alone sees no keys and reports every model "not configured".)

## Architecture map (runtime path vs the rest)

- **Live bot runtime path**: `crypto_trading_bot.py` (main loop, consensus via `PanelDecision`, trade gate) → `marketdata.py` (Coinbase OHLCV + Fibonacci block, cached per coin, injected into every analysis prompt as the primary data section; Trends/CMC/SOCIAL are labeled secondaries inside it — CMC via `coinmarketcaputil.py`, SOCIAL via LunarCrush's `coins/v1` + `topic/v1`, both self-fetched by `build_market_block` so the existing per-coin-per-run cache covers them too) → `claudeutil.py` / `openaiutil.py` / `grokutil.py` / `perplexityutil.py` (panel traders; Gemini is called inline) → `voteschema.py` (schema-enforced JSON votes for gemini/claude/openai; grok/perplexity use the hardened delimiter parser as a loudly-logged fallback) → `coinbaseutil2.py` (orders, fill confirmation) → `historyutil.py` (recommendations) + `executionledger.py` (intent/fill rows, positions, daily cap).
- **Parallel stack**: `llm_utils/` + `config.py` + `prompts/` serve `llm_compare.py` only (a standalone tool). It duplicates the provider clients — a known wart; if you change provider behavior, check both stacks (the registry already covers both).
- **Tests**: `tests/` (pytest). Consensus and parser behavior are spec'd by tests — read `tests/test_consensus.py` before touching vote logic.
- **Reference docs**: `MODELS.md` (model registry, migration history, per-provider request/response shape appendix — read before touching provider calls), `docs/RUNBOOK_live_acceptance.md` (owner-executed live test), `docs/RUNBOOK_whatif_cadence.md` (scheduled what-if runs — the analyzer's data engine), `EVALUATION_LESSONS_LEARNED_2026-07-18.md` (the empirical audit this architecture came from), `docs/reflections-2026-07-18/` (first-person implementer reflections + SYNTHESIS.md with the fix-candidate queue F1–F9/R1–R4).

## Known API gotchas (all empirically verified — don't rediscover them)

- Coinbase create-order nests everything under `success_response`; fill details need a follow-up `get_order`. Numeric fields are **strings**. Fees: `total_fees` is populated, `fee` is often `''` (audit anything reading `fee`). Fees are ~1.2%/side at small notional (~2.4% round trip — measured).
- Coinbase `get_candles` takes unix-second **string** bounds and returns candles with string numeric fields, capped at ~300 rows/request — this bounds how far back a benchmark price can be fetched at hourly granularity.
- The execution ledger records only **BUY** fills today; round-trip fee estimates are 2× the entry fill's fee. SELL-side rows don't exist yet.
- **CMC symbol collision**: `/v3/cryptocurrency/quotes/latest` looked up by symbol returns a list; taking `data[0]` can be the **wrong asset** for obscure tickers. ID-based lookup via `coinmarketcaputil.SYMBOL_TO_CMC_ID`/`get_cmc_id` is the planned fix — those helpers are intentionally kept even while uncalled.
- The Coinbase SDK has **no server-side `client_order_id` filter**; duplicate-order recovery lists recent orders and matches client-side.
- **Duplicate `client_order_id` is NOT an error** (validated live 2026-07-19, runbook §7): resubmitting the same `client_order_id` returns `success: true` with the **original** `order_id` — idempotent dedupe, no error text, no second fill. Never string-match error text to detect duplicates (`_looks_like_duplicate` is log-annotation only and cannot fire on the real shape); the duplicate signal is the returned `order_id` matching the ledger's row for that `client_order_id`. Fixture: `tests/fixtures/coinbase/duplicate_rejection.json`.
- **LLM self-correction debris can survive into parsed `reasons`** even when the typed vote fields (action/confidence/abstain/symbol) parse cleanly — observed live from Claude (fragments like `"]}...__ERROR__ retrying:{"` and a stray literal `"abstain"` as reasons). Root cause: `voteschema.parse_vote` validates reasons by *type* only (voteschema.py:226-231), no content checks. Blast radius is stdout/logs only — history records store action strings, never reasons (`resolve_structured_vote` returns just `vote.action`). FIXED 2026-07-19: `parse_vote` now decodes the first complete JSON object only and content-filters reasons (majority-debris fails closed as `reasons content corrupt` → `abstain('parse_failure')`); spec'd by the content-hygiene tests in `tests/test_voteschema.py` and the malformed-stream regression in `tests/test_structured_requests.py`. Reasons remain display-only text — never trade on them.
- GPT-5.5 and Gemini 3.1 are reasoning models: small `max_tokens` budgets get consumed by reasoning and return **empty visible text** with `finish_reason=length`/`MAX_TOKENS`. Give generous output budgets; treat empty-text-at-cap as an abstain/parse-failure, never as consent.
- Grok's `max_output_tokens` is a soft cap (observed exceeding it). GPT-5.x wants `max_completion_tokens` (not `max_tokens`) and rejects `temperature`.
- Google Trends (pytrends) 429s frequently and its series are scaled max=100 per window — an all-zero series with one blip looks like a "spike to 100". Don't treat it as decision-grade data.
- Structured-output quirks (probed live 2026-07-18, fixtures in `tests/fixtures/structured_output/`): Claude's json_schema output_config **rejects `minimum`/`maximum`** on numbers (enforce bounds client-side); Gemini's `response_schema` **rejects `additionalProperties`** but **coexists with google_search grounding**; OpenAI accepts full strict schemas; Perplexity **returns unterminated JSON when it hits max_tokens** — never trust an unparsed tail; Grok's Responses API json_schema works but is unadopted (fallback parser).
- **CoinMarketCap** (`COINMARKETCAP_API_KEY`, Free tier, 15k credits/mo, 50 req/min): `/v3/cryptocurrency/quotes/latest` (1 credit) and `/v1/cryptocurrency/map` (0 credits) verified current. Adds rank/dominance/supply/multi-window % changes that candles don't have. `coinmarketcaputil.py` has its own client-side throttle; `marketdata.py`'s CMC section (T12) reuses it.
- **LunarCrush** (`LUNARCRUSH_API_KEY`, Individual plan since 2026-07-18: 10 req/min, 2,000 req/day): WORKING (the earlier free-tier 402 wall is gone). Two verified endpoints: `/api4/public/coins/:SYMBOL/v1` (galaxy_score, alt_rank, market_cap_rank, price, volatility, percent_change_24h/7d/30d — no sentiment here) and `/api4/public/topic/:topic/v1` (topic slug = lowercased coin *name*, e.g. `bitcoin` not `BTC`; interactions_24h, num_contributors, num_posts, per-network `types_sentiment`). Auth is `Authorization: Bearer <key>` **plus a real `User-Agent` header — Python's default UA gets Cloudflare 403 "error code: 1010"**, which looks like an auth failure but isn't. Individual plan excludes topic time-series and `/coins/list/v2` (Builder+ only). `marketdata.py`'s SOCIAL section (T13) makes both calls per coin per run and derives an aggregate sentiment score as an interaction-weighted mean of `types_sentiment` (a judgment call — see marketdata.py's `_aggregate_sentiment` docstring).

## Process lessons that keep this repo workable

- **Write the spec as failing tests first** (xfail), then implement until they flip. The consensus hardening was delivered this way; it works.
- **Serialize work that touches `crypto_trading_bot.py`** — it's one big file and every behavior change lands there. Parallel edits to it will conflict. (Splitting it into modules is the standing refactor candidate.)
- **Report judgment calls explicitly.** When you make a choice the task didn't specify (a default, a fallback, a classification), list it in your summary — the owner reviews those.
- **Fail closed on the money path.** An error, refusal, missing panelist, or unparseable vote must block a trade, never shrink the quorum or fall back to a single model. This is the repo's core safety invariant — regressions here are the worst class of bug.
- **Label data honestly.** History records carry `trading_mode` (`live`/`whatif`/`unknown`); `unknown` means "could not verify", never guess. Simulated data must never be indistinguishable from real.
- **Probe before you migrate.** For any provider-API change, make tiny live calls first and save the request/response as fixtures — every provider had an undocumented quirk that would have been a runtime bug (see gotchas above). A valid key is not proof of data access (LunarCrush 402s everything); verify the data surface, not just auth.
- **Inject at seams, not through the money path.** New data/features should reach prompts via caches/wrappers around the consensus code, not new parameters threaded through it — `marketdata.py`'s block cache added a whole data pipeline with zero changes to `process_coin_with_comparison` or its tests.
- **Supplied data fixed the HOLD problem.** The eval's "frontier models refuse/HOLD by default" was a data-starvation artifact, demonstrated live: with a real market block, all panelists analyze and disagreements become analytical (that's the disagreement the consensus gate exists for). If models start refusing again, check what data the prompts carry before touching models or prompts.
- **Verify spec claims against the code before destructive action.** Task specs inherit errors (a "delete `--use-fib` flag" instruction actually meant a junk *file*; the live flag was an unrelated documented feature). The spec tells you where to look; the code tells you what's true. Corollary: "zero callers" and "not intended API" are different facts — check both before deleting a helper.
- **In multi-agent work, the invariant is a file-ownership list, not a global test count.** Parallel agents in one tree each saw the suite grow from the other's files and burned time proving the delta wasn't their bug. Give each agent an explicit list of files it owns; "files outside your list unchanged" is checkable, "N tests" is not.
- **Harvest reflections from implementing agents at phase ends.** Final reports systematically omit near-misses and design doubts; asking each agent afterward for a first-person reflection surfaced three money-path risks no report contained (see `docs/reflections-2026-07-18/SYNTHESIS.md`). Completed agents can be resumed from their transcripts for this even after the orchestrator's context is compacted.
- **`block_reason` vocabulary is spec'd by `tests/test_consensus.py`** — there is no separate enum/doc; read the test assertions before emitting or parsing block reasons.
- **Owner-run live acceptance is a distinct test layer** — 2026-07-19's session (results: `docs/ACCEPTANCE_RESULTS_2026-07-19.md`) falsified a documented API expectation (§7 duplicate shape) and surfaced two bugs (reasons junk, cap-tally undercount) that 599 passing tests never touched. When a runbook prediction is cheaply testable against the real API, test it and save the fixture; and read raw LLM output during acceptance, not just parsed verdicts.
- **Test-authoring traps (each cost real debugging time):** never `monkeypatch.setattr` an attribute on a real stdlib module (e.g. `time.time`) — modules are process-global singletons and you'll freeze pytest itself; rebind the *importing module's* name (`monkeypatch.setattr(mymod, 'time', stub)`) instead. Any new test that reaches `marketdata.build_market_block` needs the CMC/SOCIAL fetch stubs (see `tests/test_market_data.py`'s file-local autouse fixture) or it will trip the conftest network guard after slow real retries. `tests/conftest.py` blocks all sockets; `@pytest.mark.allow_network` is the explicit opt-out.
