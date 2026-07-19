"""Single source of truth for LLM model IDs used across the trading bot.

Model IDs used to be hardcoded in two parallel stacks -- the `*util.py`
traders (claudeutil.py, openaiutil.py, grokutil.py, perplexityutil.py) and
the `llm_utils/*_client.py` clients used by llm_compare.py -- plus five
inline literals in crypto_trading_bot.py's Gemini call functions. A model
retirement (this repo has already hit two: claude-sonnet-4-20250514 and
gemini-3-pro-preview, see EVALUATION_LESSONS_LEARNED_2026-07-18.md S1.5)
meant hunting down every copy by hand.

Call get_model(provider) instead of hardcoding a model string. Every call
site now reads its model ID through this module, so a retired/renamed
model is a one-place fix (or a same-session env var override while a fix
is prepared -- see the per-provider *_MODEL vars below).
"""

import os

# Provider -> default model ID. Keep these in sync with MODELS.md, which
# also carries the migration history and the "when a model dies" runbook.
DEFAULT_MODELS = {
    'gemini': 'gemini-3.1-pro-preview',
    'claude': 'claude-opus-4-8',
    'openai': 'gpt-5.5',
    'grok': 'grok-4.5',
    'perplexity': 'sonar-pro',
}

# Provider -> env var that overrides the default, e.g. to pin a working
# model within minutes of a retirement without touching code.
ENV_OVERRIDE_VARS = {
    'gemini': 'GEMINI_MODEL',
    'claude': 'CLAUDE_MODEL',
    'openai': 'OPENAI_MODEL',
    'grok': 'GROK_MODEL',
    'perplexity': 'PERPLEXITY_MODEL',
}


def get_model(provider: str) -> str:
    """Return the model ID to use for `provider`.

    Resolution order: the provider's env override (e.g. CLAUDE_MODEL) if
    set to a non-empty value, else the registry default. Env vars are read
    at call time (not import time) so tests and runtime overrides both
    work without reloading this module.

    Raises ValueError for a provider not in DEFAULT_MODELS -- an unknown
    provider is almost always a typo and should fail loudly rather than
    silently resolve to None.
    """
    key = provider.lower().strip()
    if key not in DEFAULT_MODELS:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. Valid providers: "
            f"{', '.join(sorted(DEFAULT_MODELS))}"
        )
    override = os.environ.get(ENV_OVERRIDE_VARS[key], '').strip()
    return override or DEFAULT_MODELS[key]
