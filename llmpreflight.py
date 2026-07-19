"""LLM preflight checks.

Before the bot burns a full analysis cycle (Google Trends fetch, coin
discovery, multi-round consensus) on a panel where one provider is about
to fail every call -- a retired model ID, an expired key, an unset env
var -- run one minimal-cost probe request per configured provider and
surface the result up front.

Each probe reuses the exact client construction the bot uses in production
(llm_utils.<Provider>Client), so a preflight pass is a real signal that the
production code path works, not just that the network is reachable. A
provider with no API key configured is reported as
PreflightResult(ok=False, error='not configured') WITHOUT making a network
call -- the llm_utils client constructors already raise ValueError in that
case before touching the network, and preflight() treats that as the
"not configured" signal rather than a probe failure.

F9 -- OPTIONAL schema-probe mode (`preflight(providers, schema_probe=True)`):
the plain probe above only proves "the model ID + auth + endpoint work" --
it says nothing about the structured-output CONTRACT the bot actually
depends on in production (voteschema.py's per-provider json_schema/
output_config/response_schema variants). That contract has already drifted
server-side once for a young surface (Claude's output_config -- see
MODELS.md), and the T8 implementer's reflection flagged that this class of
drift currently only surfaces mid-panel, during a real analysis run, not at
startup. When `schema_probe=True`, each of the THREE structured-output-
adopting providers (gemini/claude/openai -- grok/perplexity stay on the
delimiter-tag fallback parser per voteschema.py and are UNCHANGED by this
flag) gets a second, still-minimal-but-real probe: one request carrying
that provider's actual voteschema schema variant, validated with
voteschema.parse_vote against the real response text. A schema violation
(the API rejects the schema, or returns something that doesn't parse as a
Vote) reports PreflightResult(ok=False, ...), the same failure shape the
plain probe uses -- so it flows through the SAME "hard-fail live, warn
whatif" semantics callers already apply to any other preflight failure; no
change to that logic was needed here. The schema probe intentionally does
NOT cap Gemini's output tokens (mirrors the production call: gemini-3.1 is
a reasoning model that can burn a small budget on reasoning alone and
return empty visible text -- AGENTS.md gotcha) and gives Claude/OpenAI a
larger-than-the-plain-probe budget for the same reason; costs stay "a few
cents total" for all three (pre-authorized, AGENTS.md).

The default preflight() call (schema_probe=False, the existing default) is
completely unchanged in behavior and cost -- schema_probe is opt-in. Wiring
a bot-level CLI flag for this is left to a later change (out of scope
here; crypto_trading_bot.py is off-limits to this module).

See MODELS.md for the "when a model dies" runbook this module feeds.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import llm_utils
import voteschema

# Deliberately small: enough headroom that a reasoning-capable model
# returning finish_reason="length" doesn't masquerade as an error, small
# enough that the probe's cost is negligible next to a real analysis call.
PROBE_MAX_TOKENS = 16
PROBE_PROMPT = "Reply with the single word OK."

NOT_CONFIGURED_ERROR = "not configured"

# F9: schema-probe mode. A real, minimal one-vote analysis request using
# each provider's ACTUAL voteschema variant -- bigger than PROBE_PROMPT
# above because the response has to be schema-valid JSON, not just one
# word, but still a single tiny request (a few cents total across all
# three providers). Claude/OpenAI get a larger-than-plain-probe token
# budget (reasoning models can consume a small budget on reasoning alone
# and return empty visible text -- AGENTS.md gotcha); Gemini's schema
# probe deliberately leaves the budget uncapped, mirroring the production
# call in crypto_trading_bot.gemini_structured_config.
SCHEMA_PROBE_MAX_TOKENS = 1024
SCHEMA_PROBE_COIN = "BTC"
SCHEMA_PROBE_PROMPT = (
    "This is a startup preflight schema probe, not a real trading "
    "decision -- verifying only that structured output works. Would a "
    f"sophisticated trading bot recommend buying, selling, or holding "
    f"{SCHEMA_PROBE_COIN} right now? "
    + voteschema.schema_instruction(SCHEMA_PROBE_COIN)
)


@dataclass
class PreflightResult:
    """Outcome of one provider's preflight probe."""
    ok: bool
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None


def _probe_gemini() -> PreflightResult:
    from google.genai import types

    wrapper = llm_utils.GeminiClient()  # raises ValueError if GOOGLE_API_KEY unset
    model = wrapper.model
    start = time.monotonic()
    try:
        wrapper.client.models.generate_content(
            model=model,
            contents=PROBE_PROMPT,
            config=types.GenerateContentConfig(max_output_tokens=PROBE_MAX_TOKENS),
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    return PreflightResult(ok=True, model=model, latency_ms=(time.monotonic() - start) * 1000)


def _probe_claude() -> PreflightResult:
    wrapper = llm_utils.ClaudeClient()  # raises ValueError if no API key
    model = wrapper.model
    start = time.monotonic()
    try:
        wrapper.client.messages.create(
            model=model,
            max_tokens=PROBE_MAX_TOKENS,
            messages=[{"role": "user", "content": PROBE_PROMPT}],
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    return PreflightResult(ok=True, model=model, latency_ms=(time.monotonic() - start) * 1000)


def _probe_openai() -> PreflightResult:
    wrapper = llm_utils.OpenAIClient()  # raises ValueError if OPENAI_API_KEY unset
    model = wrapper.model
    start = time.monotonic()
    try:
        wrapper.client.chat.completions.create(
            model=model,
            max_completion_tokens=PROBE_MAX_TOKENS,
            messages=[{"role": "user", "content": PROBE_PROMPT}],
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    return PreflightResult(ok=True, model=model, latency_ms=(time.monotonic() - start) * 1000)


def _probe_grok() -> PreflightResult:
    wrapper = llm_utils.GrokClient()  # raises ValueError if XAI_API_KEY unset
    model = wrapper.model
    start = time.monotonic()
    try:
        # No web_search tool here -- preflight only needs to prove the
        # model ID + auth + endpoint are valid, not exercise search.
        wrapper.client.responses.create(
            model=model,
            input=[{"role": "user", "content": PROBE_PROMPT}],
            max_output_tokens=PROBE_MAX_TOKENS,
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    return PreflightResult(ok=True, model=model, latency_ms=(time.monotonic() - start) * 1000)


def _probe_perplexity() -> PreflightResult:
    wrapper = llm_utils.PerplexityClient()  # raises ValueError if PERPLEXITY_API_KEY unset
    model = wrapper.model
    start = time.monotonic()
    try:
        wrapper.client.chat.completions.create(
            model=model,
            max_tokens=PROBE_MAX_TOKENS,
            messages=[{"role": "user", "content": PROBE_PROMPT}],
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    return PreflightResult(ok=True, model=model, latency_ms=(time.monotonic() - start) * 1000)


def _validate_schema_probe_text(model, text):
    """Shared F9 tail for the three schema probes below: validate that
    `text` parses as a schema-valid vote via voteschema.parse_vote (the
    SAME validator the production consensus path uses). Any parse failure
    -- schema violation, empty text, non-JSON -- reports ok=False with the
    detail; a valid vote (BUY/SELL/HOLD OR an explicit abstain -- abstain
    is a first-class parse SUCCESS per voteschema.py, not a failure) is
    ok=True. Never raises."""
    vote, err = voteschema.parse_vote(text)
    if vote is None:
        return PreflightResult(
            ok=False, model=model,
            error=f'schema probe: response did not parse as a vote ({err})')
    return PreflightResult(ok=True, model=model)


def _probe_gemini_schema() -> PreflightResult:
    """F9: real request carrying Gemini's actual voteschema variant
    (response_mime_type + response_schema, same shape as
    crypto_trading_bot.gemini_structured_config minus the google_search
    grounding tool -- the schema contract is what's under test, not
    grounding). Output is deliberately left uncapped: gemini-3.1 is a
    reasoning model that can consume a small budget on reasoning alone and
    return empty visible text at finish_reason=MAX_TOKENS (AGENTS.md
    gotcha) -- capping this probe would risk mistaking that for a schema
    failure."""
    from google.genai import types

    wrapper = llm_utils.GeminiClient()  # raises ValueError if GOOGLE_API_KEY unset
    model = wrapper.model
    start = time.monotonic()
    try:
        response = wrapper.client.models.generate_content(
            model=model,
            contents=SCHEMA_PROBE_PROMPT,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=voteschema.schema_for_gemini(),
            ),
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    result = _validate_schema_probe_text(model, getattr(response, 'text', None))
    if result.ok:
        result.latency_ms = (time.monotonic() - start) * 1000
    return result


def _probe_claude_schema() -> PreflightResult:
    """F9: real request carrying Claude's actual voteschema variant
    (output_config json_schema, same shape as claudeutil._claude_output_config).
    This is exactly the surface the T8 implementer's reflection flagged as
    young and prone to server-side drift."""
    wrapper = llm_utils.ClaudeClient()  # raises ValueError if no API key
    model = wrapper.model
    start = time.monotonic()
    try:
        message = wrapper.client.messages.create(
            model=model,
            max_tokens=SCHEMA_PROBE_MAX_TOKENS,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": voteschema.schema_for_claude(),
                }
            },
            messages=[{"role": "user", "content": SCHEMA_PROBE_PROMPT}],
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    text = next((b.text for b in message.content if getattr(b, 'type', None) == "text"), "")
    result = _validate_schema_probe_text(model, text)
    if result.ok:
        result.latency_ms = (time.monotonic() - start) * 1000
    return result


def _probe_openai_schema() -> PreflightResult:
    """F9: real request carrying OpenAI's actual voteschema variant
    (response_format json_schema strict, same shape as
    openaiutil.OpenAITrader.send_coin_check_request)."""
    wrapper = llm_utils.OpenAIClient()  # raises ValueError if OPENAI_API_KEY unset
    model = wrapper.model
    start = time.monotonic()
    try:
        response = wrapper.client.chat.completions.create(
            model=model,
            max_completion_tokens=SCHEMA_PROBE_MAX_TOKENS,
            response_format=voteschema.openai_response_format(),
            messages=[{"role": "user", "content": SCHEMA_PROBE_PROMPT}],
        )
    except Exception as e:
        return PreflightResult(ok=False, model=model, error=str(e))
    text = response.choices[0].message.content or ""
    result = _validate_schema_probe_text(model, text)
    if result.ok:
        result.latency_ms = (time.monotonic() - start) * 1000
    return result


_PROBES = {
    'gemini': _probe_gemini,
    'claude': _probe_claude,
    'openai': _probe_openai,
    'grok': _probe_grok,
    'perplexity': _probe_perplexity,
}

# F9: only the three structured-output-ADOPTING providers get a schema
# probe (voteschema.py: grok/perplexity stay on the delimiter-tag fallback
# parser, so there's no schema contract of theirs to probe). A provider
# not in this dict falls back to its plain probe even when
# schema_probe=True -- schema_probe changes cost/behavior for gemini/
# claude/openai ONLY.
_SCHEMA_PROBES = {
    'gemini': _probe_gemini_schema,
    'claude': _probe_claude_schema,
    'openai': _probe_openai_schema,
}


def _run_one(provider: str, schema_probe: bool = False) -> PreflightResult:
    probe = _PROBES.get(provider)
    if probe is None:
        return PreflightResult(ok=False, error=f"unknown provider '{provider}'")
    if schema_probe:
        probe = _SCHEMA_PROBES.get(provider, probe)
    try:
        return probe()
    except ValueError:
        # llm_utils.<Provider>Client.__init__ raises ValueError only when
        # the provider's required API key env var is unset -- no network
        # call has been attempted at this point.
        try:
            from modelregistry import get_model
            model = get_model(provider)
        except Exception:
            model = None
        return PreflightResult(ok=False, model=model, error=NOT_CONFIGURED_ERROR)


def preflight(providers: List[str], schema_probe: bool = False) -> Dict[str, "PreflightResult"]:
    """Run one minimal-cost probe per provider in `providers`.

    schema_probe=False (default): unchanged behavior/cost -- one tiny
    plain-text probe per provider, exactly as before F9.

    schema_probe=True: gemini/claude/openai (the structured-output-
    adopting providers) additionally get their probe SWAPPED for a
    schema-carrying variant that validates the response parses as a
    voteschema.Vote (see module docstring). grok/perplexity are
    unaffected by this flag -- they keep the plain probe either way, since
    they have no structured-output contract of their own to validate.
    Same PreflightResult shape and semantics either way (ok/model/
    latency_ms/error) -- callers (e.g. crypto_trading_bot.run_llm_preflight)
    need no changes to consume a schema-probed result: a schema violation
    is just another ok=False, flowing through the existing hard-fail-live/
    warn-whatif handling unchanged.

    Returns a dict keyed by lowercased provider name. Order of the input
    list is not preserved in the return value (dict is unordered by
    provider identity, not call order) -- callers that want ordered
    output should iterate their own panel list and look up each key.
    """
    results: Dict[str, PreflightResult] = {}
    for provider in providers:
        key = provider.lower().strip()
        if key in results:
            continue  # skip duplicate probes for a provider listed twice
        results[key] = _run_one(key, schema_probe=schema_probe)
    return results
