# WS-9: discovery-universe honesty -- implementer reflection

## What shipped

- `--discovery-universe` / `DISCOVERY_UNIVERSE` (CLI > env > default, same
  precedence pattern as `--exclude-coins`). Choices: `meme` (default),
  `major`, `defi`, `any`.
- `DISCOVERY_UNIVERSE_PHRASES` maps each choice to its universe phrase
  (`meme coins`, `large-cap cryptocurrencies`, `DeFi tokens`,
  `cryptocurrencies (any category)`).
- `build_discovery_prompt(dex_mode, universe)`: a new pure function
  factored out of `sendRecommendationRequest`. It keeps the ORIGINAL
  hardcoded DEX/CEX prompt strings verbatim and does one
  `.replace('meme coins', phrase, 1)` over them. With `universe='meme'` the
  replace is a no-op, so the returned string is byte-identical to the
  pre-WS9 prompts -- pinned in `tests/test_discovery_universe.py` against
  strings extracted via `ast.parse` from the original function (not
  hand-retyped, to eliminate transcription risk from the pin itself).
- Banner honesty: `Discovery Methods: llm (universe: meme) [source]` --
  only appended when `USE_LLM_DISCOVERY` is true, reading the exact same
  `DISCOVERY_UNIVERSE` module global `build_discovery_prompt` consumes.
- `build_run_summary` gained an optional `discovery_universe=None` kwarg
  (mirrors the WS4 `data_quality_by_coin` pattern). The `universe` key is
  written into `summary['discovery']` only when `use_coin_discovery` AND
  `'llm' in discovery_methods` AND the arg was supplied -- inert paths
  (santiment-only discovery, explicit coins) never get the key, and old
  callers that omit the kwarg get the exact prior dict shape.
- `build_config_report` gained a `discovery_universe` settings entry with
  standard provenance (`cli`/`env`/`default`) via the existing
  `_config_source_label`/`get_config_source` machinery -- no parallel
  provenance logic.

## Symbol anchors

- `crypto_trading_bot.py`: `DISCOVERY_UNIVERSE_PHRASES`,
  `build_discovery_prompt`, `sendRecommendationRequest` (now a 2-line
  wrapper), `--discovery-universe` arg block (near `--discovery`),
  `DISCOVERY_UNIVERSE` global assignment in `main()` (next to
  `USE_SANTIMENT_DISCOVERY`), the `Discovery Methods:` banner line, the
  `build_run_summary` discovery-entry block, `build_config_report`'s
  `settings['discovery_universe']` line.
- Tests: `tests/test_discovery_universe.py` (new, 21 tests) covering the
  byte-identical pin, per-universe phrase substitution in both prompt
  variants, CLI>env>default precedence, banner-line construction, run
  summary optionality, and print-config provenance.

## Test delta

1005 (baseline) -> 1026 passed. All new tests in one file; two existing
test files touched for hermeticity/compatibility, not behavior:
- `tests/test_print_config.py`: added `DISCOVERY_UNIVERSE` to the env-scrub
  list (same reason every other config var is scrubbed there) and to the
  settings spot-check key list.
- `tests/test_structured_requests.py`:
  `TestGeminiRequests.test_discovery_request_is_untouched` now also
  monkeypatches `bot.DISCOVERY_UNIVERSE = 'meme'` since
  `sendRecommendationRequest` gained that dependency and the test never runs
  `main()` (which is what normally sets the global).

## Judgment calls

1. **Scope confined to `crypto_trading_bot.py`.** The identical hardcoded
   "meme coins" DEX/CEX prompt pair also lives, byte-for-byte duplicated, in
   `claudeutil.py`, `openaiutil.py`, `grokutil.py`, and `perplexityutil.py`
   (each provider's own `send_recommendation_request`). The task's
   motivation, grep pointer, and "exclusive access to crypto_trading_bot.py"
   framing all scope this to the Gemini path in the monolith. I left the
   other four files untouched -- they still hardcode "meme coins"
   regardless of `--discovery-universe`. This means in `--llm-mode=compare`
   with multiple panelists, only Gemini's discovery call (the one
   `sendRecommendationRequest`/`USE_LLM_DISCOVERY` path actually drives) is
   honesty-fixed; if any other provider's discovery path is independently
   invoked it still asks for meme coins. I did not flag this as a spawned
   follow-up task since it's an obvious, low-effort mechanical extension
   (same phrase-substitution pattern, four files) that the owner may want
   bundled with this WS rather than split off -- surfacing it here instead.
2. **`build_discovery_prompt` keeps the exact original literal strings
   in-line** rather than defining phrase-templated f-strings, specifically
   so the default-path text can never silently drift from the original by a
   typo during refactor -- the substitution is applied at the end via
   `.replace()`, and the byte-identical test pins the untouched literal
   against an independently `ast`-extracted copy.
3. **`discovery_universe` in `build_run_summary`gates on
   `'llm' in discovery_methods` (not `USE_LLM_DISCOVERY` directly)** since
   the function is pure and doesn't receive that global -- `discovery_methods`
   is the same list `USE_LLM_DISCOVERY = 'llm' in DISCOVERY_METHODS` was
   derived from, so this can't drift.
4. **No change to `build_plan_lines`** (the `--plan` human-readable output).
   The task's required property #4 only asked for `--print-config`/`--plan`
   to "enumerate operational settings" via `build_config_report`, which both
   flags consume; `discovery_universe` is now in that settings dict and
   therefore in `--print-config`'s JSON. `build_plan_lines`' prose doesn't
   individually narrate every settings key today (e.g. it doesn't call out
   `exclude_coins` by name in prose either, despite `exclude_coins` being a
   settings entry), so I did not add a `--plan` prose line for it to stay
   consistent with that existing convention.

## Full suite

`./venv/bin/python -m pytest -q` -> 1026 passed, 0 failed. No commits made
(implementer scope; commits are owner-gated per repo convention).

## WS-9b follow-up

### Trace: is claudeutil/openaiutil/grokutil/perplexityutil discovery reachable?

Yes -- confirmed by reading the call graph, not assumed. `run_llm_discovery()`
(crypto_trading_bot.py) calls `get_primary_recommendation()`, which dispatches
on the module-level `PRIMARY_LLM` global:

```
if PRIMARY_LLM == 'gemini': ... sendRecommendationRequest()
elif PRIMARY_LLM == 'claude' and claude_trader: claude_trader.send_recommendation_request(...)
elif PRIMARY_LLM == 'openai' and openai_trader: openai_trader.send_recommendation_request(...)
elif PRIMARY_LLM == 'grok' and grok_trader: grok_trader.send_recommendation_request(...)
elif PRIMARY_LLM == 'perplexity' and perplexity_trader: perplexity_trader.send_recommendation_request(...)
```

`--primary-llm` (`PRIMARY_LLM` env/CLI) accepts all five providers, and
`run_llm_discovery()` is reached whenever `'llm' in discovery_methods` (i.e.
`--discovery`/`DISCOVERY` includes `llm`, the default) with no coins
specified. So a real operator running e.g. `--primary-llm=claude
--discovery-universe=defi` would have silently gotten a "meme coins" prompt
out of Claude while the banner honestly said "universe: defi" -- exactly the
dishonesty class WS-9 fixed for the gemini-only path. Confirmed CONFIRMED
(not inherited): traced the exact call chain above, not taken on the WS-9
agent's flag alone.

A second finding while tracing: the four provider prompts are **not** all
byte-identical duplicates of each other or of the gemini-path text.
`claudeutil.py` and `openaiutil.py` are exact duplicates of the gemini CEX/DEX
prompt (same words, same "...you are aware of." ending). `grokutil.py` and
`perplexityutil.py` carry their own wording: grok prepends "Using real-time
web search for current market data and sentiment, " and both end "...you
find." instead of "...you are aware of." This matters for the fix shape --
importing/reusing `build_discovery_prompt` wholesale for grok/perplexity
would have silently overwritten their provider-specific phrasing, not just
parameterized the universe.

### Import-cycle check

`claudeutil.py`/`openaiutil.py`/`grokutil.py`/`perplexityutil.py` import only
`anthropic`/`openai`, `os`, `modelregistry`, `panelprompts`, `sampling`,
`voteschema` -- none import `crypto_trading_bot`. `crypto_trading_bot.py`
constructs `ClaudeTrader()`/`OpenAITrader()`/`GrokTrader()`/
`PerplexityTrader()` directly, i.e. the four provider utils are imported BY
crypto_trading_bot. Importing `crypto_trading_bot` from any of them (to reuse
`build_discovery_prompt`/`DISCOVERY_UNIVERSE_PHRASES` directly) would be a
cycle. Per the task's own fallback instruction, moved the phrase
substitution to the call site instead.

### Fix shape

`get_primary_recommendation()` now resolves the phrase once --
`bot.DISCOVERY_UNIVERSE_PHRASES.get(bot.DISCOVERY_UNIVERSE,
bot.DISCOVERY_UNIVERSE_PHRASES['meme'])` -- and passes it down as a plain
string via a new `phrase: str = 'meme coins'` kwarg on each provider's
`send_recommendation_request`. Each provider still owns and builds its own
prompt template (preserving grok/perplexity's distinct wording); only the
final line changed, from returning the hardcoded prompt directly to
`prompt = prompt.replace('meme coins', phrase, 1)` before use -- the same
`.replace()`-based no-op-by-default pattern `build_discovery_prompt` already
uses for the gemini path. Default `phrase='meme coins'` keeps every existing
caller (including `tests/test_structured_requests.py`'s
`send_recommendation_request()` no-arg calls) byte-identical.

No shared constants module was introduced -- the four-line
`DISCOVERY_UNIVERSE_PHRASES` map stays owned solely by
`crypto_trading_bot.py`; the provider utils never see universe *names*, only
the already-resolved phrase *string*, so there is nothing to keep in sync
across five files beyond the one map.

### Symbol-anchored changes

- `crypto_trading_bot.py`: `get_primary_recommendation()` -- resolves
  `phrase` from `DISCOVERY_UNIVERSE_PHRASES`/`DISCOVERY_UNIVERSE` and passes
  `phrase=phrase` to each non-gemini branch's `send_recommendation_request`
  call.
- `claudeutil.py`: `ClaudeTrader.send_recommendation_request` -- new
  `phrase: str = 'meme coins'` param, `.replace('meme coins', phrase, 1)`
  applied to the built prompt before the API call.
- `openaiutil.py`: `OpenAITrader.send_recommendation_request` -- same shape.
- `grokutil.py`: `GrokTrader.send_recommendation_request` -- same shape
  (grok's distinct wording/ending untouched apart from the phrase swap).
- `perplexityutil.py`: `PerplexityTrader.send_recommendation_request` --
  same shape (perplexity's distinct ending untouched apart from the phrase
  swap).

No dead code found -- all four prompts are live on the discovery path
whenever their provider is `PRIMARY_LLM`, so no superseded-code comments
were needed (the "if genuinely dead" branch of the task did not apply).

### Tests

Extended `tests/test_discovery_universe.py` (same file WS-9 created) rather
than a new file, per the task's own instruction. Added, using the
`ClaudeTrader.__new__`/`OpenAITrader.__new__`/`GrokTrader.__new__`/
`PerplexityTrader.__new__` construction pattern from
`tests/test_structured_requests.py` (skips `__init__`, no network, no API
keys needed):

- Per-provider default-universe byte-identical pins (`test_claude_discovery_
  default_phrase_byte_identical`, `..._openai_...`, `..._grok_...`,
  `..._perplexity_...`) -- captured request kwargs checked against literal
  strings extracted straight from each provider's pre-change source (grok/
  perplexity pinned to their own distinct wording, not the gemini text).
- Per-provider, per-universe parametrized tests (`test_claude_discovery_
  honors_universe` etc., over all four `_EXPECTED_PHRASES` entries) proving
  the universe phrase actually lands in the built prompt for every choice,
  plus that grok's web-search preamble and perplexity's ending survive
  untouched.
- `test_dex_mode_honors_universe_across_providers` -- the DEX-mode variant
  parameterizes correctly too (claude + grok sampled as representative of
  the two duplicate-vs-distinct-wording groups).
- Call-site trace tests: `test_get_primary_recommendation_passes_universe_
  phrase_to_claude` and `..._default_universe_matches_gemini_builder` --
  monkeypatch `bot.PRIMARY_LLM`/`bot.claude_trader` (or `openai_trader`)/
  `bot.DEX_MODE`/`bot.DISCOVERY_UNIVERSE` (all `raising=False`, since they're
  only real module attributes after `main()` runs) and call
  `bot.get_primary_recommendation()` directly, asserting the captured prompt
  equals `bot.build_discovery_prompt(dex_mode=..., universe=...)` for the
  same universe -- i.e. a non-gemini primary now produces the same universe
  honesty as the gemini path, not just a phrase that happens to look right
  in isolation.

26 new tests added to `tests/test_discovery_universe.py` (21 -> 47).

### Full suite

Fresh collect + run (not the WS-9 baseline number, per AGENTS.md's own
warning about stale baselines): `./venv/bin/python -m pytest tests/ -q` ->
**1052 passed, 0 failed** (this session's fresh baseline before any edit was
1026; delta is exactly the 26 tests added here).
`./venv/bin/python -c "import crypto_trading_bot"` -- silent, as required.
`tests/test_experiment_runner.py` / `scripts/run_experiment.py` (owned by a
concurrent agent) did not exist in the tree at any point during this
session -- nothing was excluded from the suite run above.

### Judgment calls

1. **Passed the resolved phrase string, not the universe key.** An
   alternative was giving each provider its own copy of
   `DISCOVERY_UNIVERSE_PHRASES` and a `universe: str = 'meme'` param,
   resolving the phrase locally. Rejected: that would recreate exactly the
   duplication problem this task exists to fix, five copies of the same
   four-entry map instead of one. Passing the already-resolved string keeps
   exactly one copy of the map, in `crypto_trading_bot.py`.
2. **Did not touch `claude_trader`/`openai_trader`/`grok_trader`/
   `perplexity_trader`'s `__init__`** (e.g. to snapshot the universe at
   construction time). `send_recommendation_request` is only ever called
   from `get_primary_recommendation()` for these four providers (grepped;
   no other call site), so resolving `phrase` fresh at call time is
   equivalent and avoids adding another `_refresh_env_snapshots()` obligation
   for a value that already lives in a `main()`-set global, not an env
   snapshot.
3. **Did not rename `phrase` to `universe`.** `send_recommendation_request`
   receives the finished phrase, not a universe key, to keep the boundary
   clean (providers do substitution, never lookup) -- named the param for
   what it actually is.
