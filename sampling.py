"""WS5 (improvement cycle 2): per-provider analysis-request sampling policy.

Single source of truth for what sampling parameters each panelist sends on its
ANALYSIS requests (coin-check / trend-check, round 1 and round 2) and the honest
record of same. Motivation: models flipped BUY/HOLD on the same coin within
minutes; prompt_hash + models already pin "same template, same model", but
without recording the sampling params we can't tell provider instability
(same inputs, different vote) from an undocumented sampling change.

Contract (the whole point):
  * Flag OFF (default): NO sampling params are added by ANY provider, so every
    analysis request is BYTE-IDENTICAL to the pre-WS5 request, and each provider
    records the string "provider-default".
  * Flag ON (--deterministic-sampling / DETERMINISTIC_SAMPLING): providers whose
    CURRENT API/SDK analysis path accepts a determinism knob send temperature=0
    (plus a fixed seed where the API accepts one); their record is the dict of
    exactly what was sent. Providers with no supported knob on the current path
    are left UNTOUCHED and still record "provider-default" -- we never contort a
    provider's request shape to force a knob in.

honesty over invention: request_params() and record() are derived from the SAME
per-provider table, so the recorded value is exactly what the request carried --
never a value the code did not explicitly send.

Per-provider knobs under the flag (verified against the code / MODELS.md, not
assumed):
  * gemini     -- temperature + seed: types.GenerateContentConfig accepts both
                  fields (verified in-SDK); folded into gemini_structured_config.
  * claude     -- temperature only: anthropic messages.create accepts temperature
                  (no seed param on the API); thinking is off for Opus 4.8 when
                  unset (MODELS.md), so temperature=0 is valid.
  * perplexity -- temperature only: OpenAI-compatible chat.completions; sonar-pro
                  is not a heavy reasoning model, so temperature=0 is honored.
  * openai     -- provider-default: gpt-5.x REJECTS temperature (AGENTS.md gotcha,
                  verified live) and its seed behavior on the reasoning path is
                  unverified -- left UNTOUCHED rather than risk a 400.
  * grok       -- provider-default: grok-4.5 on the xAI Responses API is a
                  reasoning model; temperature acceptance alongside the adopted
                  json_schema + web_search request shape is unverified live, so
                  the request is left UNTOUCHED (no contortion). A cents-scale
                  probe can promote grok/openai later without a schema change --
                  only this table moves.
"""

import os

# Fixed seed used wherever a provider's API accepts one under the flag.
DETERMINISTIC_SEED = 42

# provider -> the sampling kwargs to send on an ANALYSIS request WHEN the
# deterministic flag is on. An empty dict means "no supported knob on the
# current request path" -> the provider is left untouched and records
# "provider-default". Keep these keys API-neutral names (temperature/seed); the
# call sites splat them where their SDK expects (top-level create kwargs for
# chat/messages/responses, into GenerateContentConfig for gemini).
_DETERMINISTIC_KNOBS = {
    'gemini': {'temperature': 0.0, 'seed': DETERMINISTIC_SEED},
    'claude': {'temperature': 0.0},
    'perplexity': {'temperature': 0.0},
    'openai': {},
    'grok': {},
}

# The sentinel recorded when the code sets nothing on the request.
PROVIDER_DEFAULT = 'provider-default'


def is_enabled(env=None):
    """True iff deterministic sampling is requested via DETERMINISTIC_SAMPLING.

    Read at CALL time (never a module-level env snapshot -- import stays
    side-effect-free), so the bot can set os.environ in main() and every trader
    constructed afterward agrees. Accepts an explicit mapping for tests.
    """
    src = env if env is not None else os.environ
    return str(src.get('DETERMINISTIC_SAMPLING', '')).strip().lower() in (
        '1', 'true', 'yes', 'on')


def request_params(provider, deterministic):
    """Sampling kwargs to actually send on an ANALYSIS request for `provider`.

    Returns {} when the flag is off OR the provider has no supported knob on its
    current request path -- in both cases the request stays byte-identical to
    today. Returns a fresh dict so a caller mutating it can't corrupt the table.
    """
    if not deterministic:
        return {}
    return dict(_DETERMINISTIC_KNOBS.get(provider, {}))


def record(provider, deterministic):
    """Honest record of what the analysis request carried for `provider`:
    the sampling-params dict actually sent, or the string "provider-default"
    when the code set nothing (flag off, or provider with no supported knob).
    """
    params = request_params(provider, deterministic)
    return params if params else PROVIDER_DEFAULT
