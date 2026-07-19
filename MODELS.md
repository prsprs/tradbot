# LLM Model Registry

Single source of truth: [`modelregistry.py`](modelregistry.py). Every LLM call
site in the codebase (the `*util.py` traders, the `llm_utils/*_client.py`
clients used by `llm_compare.py`, and the five inline Gemini calls in
`crypto_trading_bot.py`) resolves its model ID through
`modelregistry.get_model(provider)` — there are no hardcoded model-ID
literals anywhere else in the repo. See [`llmpreflight.py`](llmpreflight.py)
for the startup probe that verifies these IDs are actually alive before the
bot spends a full analysis cycle on a panel member that's about to fail
every call.

## Current registry

| Provider | Default model ID | Env override | Verified |
|---|---|---|---|
| `gemini` | `gemini-3.1-pro-preview` | `GEMINI_MODEL` | 2026-07-18 (real API call, this session) |
| `claude` | `claude-opus-4-8` | `CLAUDE_MODEL` | 2026-07-18 (real API call, this session) |
| `openai` | `gpt-5.5` | `OPENAI_MODEL` | 2026-07-18 (real API call, this session) |
| `grok` | `grok-4.5` | `GROK_MODEL` | 2026-07-18 (real API call, this session — `grok-4` confirmed retired the same day) |
| `perplexity` | `sonar-pro` | `PERPLEXITY_MODEL` | 2026-07-18 (real API call, this session — previously unverified, no free model-list endpoint) |

All five were confirmed live via `llmpreflight.preflight([...])` and direct
SDK calls against the real APIs (see the Appendix below for exact request
params and response shapes captured during that verification). No provider
required a successor swap this session — every configured default was still
valid at verification time.

To override a model without a code change (e.g. while a retirement is being
triaged), set the corresponding env var in `.env`:

```bash
CLAUDE_MODEL=claude-opus-4-7   # pin an older/known-good Claude model
```

`get_model()` reads the env var at call time, strips whitespace, and falls
back to the registry default if the override is unset or blank — so a
commented-out or empty `CLAUDE_MODEL=` line in `.env` is a no-op, not an
error.

## Migration history

Chronicled in more detail in `EVALUATION_LESSONS_LEARNED_2026-07-18.md`
S1.5 and S6.3. Summary, oldest to newest:

1. **`claude-sonnet-4-20250514` retired -> 404.** The bot had been silently
   degrading to Gemini-only "consensus" in compare mode because the Claude
   branch was swallowing the error. Root cause of the "model/API churn" audit
   finding — model IDs were duplicated in `claudeutil.py` *and*
   `llm_utils/claude_client.py`, so a fix in one place didn't fix the other.
   Replaced with `claude-opus-4-8`.
2. **Thinking-block `.text` crash.** Claude Sonnet 5 / Opus 4.8 return
   `ThinkingBlock` content blocks that have no `.text` attribute;
   `message.content[0].text` crashed whenever thinking was present. Fixed by
   selecting the first `text`-type block instead of indexing `content[0]`
   blindly (`next((b.text for b in message.content if b.type == "text"), "")`
   — see `claudeutil.py` / `llm_utils/claude_client.py`).
3. **`gemini-3-pro-preview` shut down by Google -> `gemini-3.1-pro-preview`.**
   The direct successor to Gemini 2.5 Pro had already been retired by the
   time this was investigated; `gemini-3.1-pro-preview` is the current live
   ID (reverified this session, see table above).
4. **GPT-5.x API compatibility break.** `gpt-5.x` models reject the legacy
   `max_tokens` parameter (must be `max_completion_tokens`) and reject
   `temperature`. Additionally, `gpt-5.6` is gated behind identity
   verification (401) while `gpt-5.5` is not — `gpt-5.5` is the current
   default for that reason, not because it's newer.
5. **`grok-4` retired, discovered 2026-07-18 -> `grok-4.5`.** Verified via
   the provider's model-list endpoint earlier the same session this registry
   was built; `grok-4.5` was already live and was swapped in same-day.

## Appendix: verified minimal request/response shapes (2026-07-18)

Captured live against each provider with the exact SDK client construction
`llmpreflight.py` uses, at (or near) the probe's `PROBE_MAX_TOKENS = 16`
budget. Intended as a reference for the next task (structured-output
migration) — this is what each provider's response envelope actually looks
like today, not what the SDK docs claim.

### Claude (`claude-opus-4-8`, `anthropic` SDK)

```python
client.messages.create(
    model="claude-opus-4-8",
    max_tokens=16,
    messages=[{"role": "user", "content": "Reply with the single word OK."}],
)
```

- Response type: `anthropic.types.message.Message`.
- Text lives at: `response.content` is a list of content blocks; the text
  block is `TextBlock(type="text", text="OK", citations=None)`. No thinking
  block is present because `thinking` was not set on the request (Opus 4.8
  defaults to thinking **off** when the param is omitted — this is
  provider-correct behavior per the current Claude API skill, not a bug).
  Extraction pattern already in use: `next((b.text for b in response.content
  if b.type == "text"), "")`.
- `response.stop_reason`: `"end_turn"` on a normal completion.
- `response.usage.output_tokens_details.thinking_tokens`: `0` (thinking off).
- At `max_tokens=16` this model comfortably returns real content — no
  reasoning-token contention observed (unlike GPT-5.5 and Gemini below).

### OpenAI (`gpt-5.5`, `openai` SDK, Chat Completions)

```python
client.chat.completions.create(
    model="gpt-5.5",
    max_completion_tokens=16,
    messages=[{"role": "user", "content": "Reply with the single word OK."}],
)
```

- Response type: `openai.types.chat.chat_completion.ChatCompletion`.
- **At `max_completion_tokens=16`, GPT-5.5 returned `finish_reason="length"`
  with `message.content == ""`** — all 16 tokens were consumed by internal
  reasoning (`usage.completion_tokens_details.reasoning_tokens == 16`), none
  left for visible output. This is expected (gpt-5.x is a reasoning model;
  reasoning tokens are billed against the same `max_completion_tokens`
  budget as the visible completion) and is **not** treated as a preflight
  failure — the request still succeeded (HTTP 200, no exception), which is
  all `llmpreflight` checks. Retested at `max_completion_tokens=64`:
  `finish_reason="stop"`, `message.content == "OK"`,
  `reasoning_tokens: 7`, visible tokens: ~2.
- Text lives at: `response.choices[0].message.content` (may be `""` if the
  token budget is reasoning-dominated — check `finish_reason` before trusting
  empty content as "no answer").
- **Operational implication for real calls:** don't budget
  `max_completion_tokens` tight against expected visible-output length for
  gpt-5.5 — leave headroom for reasoning tokens (the bot's real call sites
  already use 4096, which is safe).
- `response.model` echoes a dated snapshot (`gpt-5.5-2026-04-23`), not the
  bare alias sent in the request — don't assert exact equality against the
  request's `model` string when verifying the response.

### Gemini (`gemini-3.1-pro-preview`, `google-genai` SDK)

```python
client.models.generate_content(
    model="gemini-3.1-pro-preview",
    contents="Reply with the single word OK.",
    config=types.GenerateContentConfig(max_output_tokens=16),
)
```

- Response type: `google.genai.types.GenerateContentResponse`.
- **At `max_output_tokens=16`, `response.text` was `None`** and
  `candidates[0].finish_reason == FinishReason.MAX_TOKENS` —
  `usage_metadata.thoughts_token_count == 13` consumed the entire budget
  before any visible text. Retested at `max_output_tokens=100`:
  `response.text == "OK"`, `finish_reason == FinishReason.STOP`,
  `thoughts_token_count: 94`. Gemini 3.1 Pro Preview reasons heavily even
  for a trivial one-word request; **budget well above 100 output tokens**
  for any real call expecting visible text (the bot's real call sites
  already use the default `GenerateContentConfig` with no `max_output_tokens`
  cap, which is safe).
- Text lives at: `response.text` (a computed property — `None`, not `""`,
  when no visible text was produced).
- `response.usage_metadata` carries token accounting;
  `thoughts_token_count` is the Gemini-side analog of OpenAI's
  `reasoning_tokens`.

### Grok (`grok-4.5`, `openai` SDK pointed at `api.x.ai`, Responses API)

```python
client.responses.create(
    model="grok-4.5",
    input=[{"role": "user", "content": "Reply with the single word OK."}],
    max_output_tokens=16,
)
```

- Response type: `openai.types.responses.response.Response`.
- Text lives at: `response.output_text` (a convenience property — present
  and correct: `"OK"`). `response.output` is a list of typed items: a
  `ResponseReasoningItem` (`type="reasoning"`, carries a `summary` list, no
  directly usable `.content` text) followed by a
  `ResponseOutputMessage` (`type="message"`, `content=[ResponseOutputText(text="OK", ...)]`).
  The existing extraction code
  (`if hasattr(response, "output_text"): return response.output_text`) is
  correct and is the simplest path — prefer it over walking `response.output`.
- `response.status`: `"completed"`.
- `usage.output_tokens_details.reasoning_tokens`: `21`, and
  `usage.output_tokens` (`22`) came in **above** the requested
  `max_output_tokens=16` — reasoning + visible tokens together were allowed
  to exceed the cap slightly on this call. Treat `max_output_tokens` on the
  Grok/xAI Responses API as a soft target, not a hard ceiling, when sizing
  budgets.
- No web-search tool was declared for this probe (the bot's real Grok calls
  add `tools=[{"type": "web_search"}]`); preflight intentionally omits it to
  keep the probe cheap and to isolate auth/model-ID validity from search
  behavior.

### Perplexity (`sonar-pro`, `openai` SDK pointed at `api.perplexity.ai`)

```python
client.chat.completions.create(
    model="sonar-pro",
    max_tokens=16,
    messages=[{"role": "user", "content": "Reply with the single word OK."}],
)
```

- Response type: `openai.types.chat.chat_completion.ChatCompletion` (same
  shape as OpenAI's Chat Completions — Perplexity's API is OpenAI-compatible).
- Text lives at: `response.choices[0].message.content` — returned `"OK"`
  cleanly at `max_tokens=16` (`finish_reason: "stop"`, `completion_tokens: 1`).
  No reasoning-token contention observed for `sonar-pro` at this budget.
- `response.model` echoes back exactly `"sonar-pro"` (no dated-snapshot
  rewrite, unlike OpenAI).
- `response.usage.cost` is a Perplexity-specific extension not present on
  vanilla OpenAI responses: `{"input_tokens_cost", "output_tokens_cost",
  "request_cost", "total_cost"}`. Note the flat `request_cost` component
  (~$0.006 on this call) — Perplexity bills a per-request fee in addition to
  token costs, so cost estimates based on token count alone will
  undercount.
- This resolves the "sonar-pro unverified" flag from the prior session
  (no free model-list endpoint existed to check it against) — the model ID
  is confirmed live via a real completion.

## Appendix 2: structured-output shapes (T8, verified 2026-07-18)

Analysis votes (Round 1, Round 2, solo-mode checks) migrated from
delimiter-tag scraping to schema-enforced JSON
(`{symbol, action, confidence, abstain, reasons}` — canonical schema and
all parsing/validation in [`voteschema.py`](voteschema.py)). Probed live
against every provider; minimal working request + response envelopes are
pinned as fixtures in `tests/fixtures/structured_output/*.json`. Discovery
prompts/parsing (`+++SYM+++`) are untouched.

| Provider | Native structured output | Adopted for votes | Request surface |
|---|---|---|---|
| `gemini` | yes | **yes** | `GenerateContentConfig(response_mime_type="application/json", response_schema=...)` |
| `claude` | yes | **yes** | `messages.create(output_config={"format": {"type": "json_schema", "schema": ...}})` (anthropic >= 0.94, no beta header) |
| `openai` | yes | **yes** | `response_format={"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}` |
| `grok` | yes (probed) | no — delimiter fallback, logged `[FALLBACK PARSER]` | Responses API `text={"format": {"type": "json_schema", ...}}` |
| `perplexity` | yes (probed) | no — delimiter fallback, logged `[FALLBACK PARSER]` | `response_format={"type": "json_schema", "json_schema": {"schema": ...}}` (no name/strict wrapper) |

Per-provider quirks (all verified live, cost: cents):

- **Gemini**: `response_schema` must NOT contain `additionalProperties`
  (400 `Unknown name "additional_properties"`); everything else of the
  canonical schema is accepted. Schema output **coexists with the
  google_search grounding tool** in one request — the bot's analysis calls
  keep grounding. `response.text` can carry trailing whitespace after the
  JSON. Reasoning stays heavy under a schema (855 thought tokens on a tiny
  probe) — analysis calls remain uncapped; empty text at `MAX_TOKENS` maps
  to abstain(parse_failure), never a vote.
- **Claude**: `output_config` json_schema works directly on
  `client.messages.create` with anthropic 0.94.0. The schema must NOT use
  `minimum`/`maximum` on number properties (400) — the confidence range is
  validated client-side in `voteschema.parse_vote` instead;
  `additionalProperties: false` is accepted. The JSON arrives as an
  ordinary single text block.
- **OpenAI (gpt-5.5)**: accepted the full canonical schema in strict mode
  including numeric bounds, first try. Emits properties in alphabetical
  order (parse, don't string-match). All gpt-5.x rules still apply
  (`max_completion_tokens`, no `temperature`, reasoning tokens billed
  against the same budget — 98 on the probe).
- **Grok**: the Responses-API `text.format` json_schema shape works
  (strict, full schema). NOT adopted this phase: schema + the bot's
  `web_search` tool coexistence is unprobed, and T8 scope keeps grok on the
  hardened delimiter fallback. Evidence is in the fixture for a future
  migration.
- **Perplexity**: json_schema mode is honored (note the wrapper has no
  name/strict). **Truncation hazard observed live**: at `max_tokens=800`
  the response came back as *unterminated JSON* cut mid-string — Perplexity
  does not guarantee the schema output fits the budget. Clean at 2000.
  NOT adopted this phase (fallback parser retained).

Failure mapping shared by every provider path (feeds T3's PanelDecision):
API error → abstain(`error`); empty text at cap → abstain(`parse_failure`);
schema-violating JSON → abstain(`parse_failure`); explicit `abstain: true` →
abstain(`refusal`); vote symbol that doesn't bind to the coin under analysis
→ abstain(`symbol_mismatch`). None of these can become a vote or a trade.

## When a model dies

Runbook for the next time a provider retires or renames a model (this has
already happened four times — see Migration history above):

1. **Symptom.** A provider call starts failing — usually a `404` /
   `model_not_found` from the SDK, sometimes a silent quorum shrinkage in
   compare/integrate mode if the failure is being swallowed somewhere (audit
   for that; it's the #1 historical cause of a bad "consensus"). Run
   `python crypto_trading_bot.py --trading-mode=whatif --llm-mode=<provider>
   --coins=BTC` for the affected provider alone to isolate it, or rely on
   the automatic preflight table printed at startup (see below).
2. **Check the registry.** Open [`modelregistry.py`](modelregistry.py) and
   confirm the `DEFAULT_MODELS[provider]` entry is the one that's failing.
   If a newer model ID is known, edit the default there — this is the
   *only* place the literal needs to change; every call site (14 of them
   across `*util.py`, `llm_utils/*_client.py`, and the five Gemini call
   sites in `crypto_trading_bot.py`) reads through `get_model()`.
3. **Or override via env var** for a same-session fix without a code
   change/deploy: set the provider's `*_MODEL` var (e.g. `CLAUDE_MODEL=
   claude-opus-4-7`) in `.env`. This is the faster path when you need to
   keep trading (in whatif mode!) while the permanent registry fix is
   prepared and reviewed.
4. **Verify via preflight** before trusting the fix: run
   `python -c "from dotenv import load_dotenv; load_dotenv(); import
   llmpreflight; print(llmpreflight.preflight(['<provider>']))"`, or just
   start the bot — `crypto_trading_bot.py` runs the full active-panel
   preflight automatically at startup (before any analysis) and prints a
   one-line-per-provider OK/FAIL table. A live-mode run hard-exits on any
   panel failure; whatif prints a WARNING and continues with a degraded
   panel (see `run_llm_preflight()` in `crypto_trading_bot.py`). Use
   `--skip-preflight` only to intentionally bypass the check (e.g. a known
   flaky provider you're deliberately excluding from the panel via
   `--compare-llms`).
5. **Update this file's registry table and migration history** with the
   retirement date, the old/new model IDs, and how it was discovered — the
   next person hunting a 404 should be able to grep this file first.
