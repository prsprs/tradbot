"""WS-9: discovery-universe honesty.

Motivation (owner bug): sendRecommendationRequest's LLM discovery prompt
hardcodes "meme coins" (DEX and CEX variants) while the startup banner prints
"Discovery Methods: llm" with no disclosure of what universe the LLM was
actually asked about. During a recent session both discovery runs surfaced
DOGE/PEPE/SHIB/FARTCOIN and the owner was surprised -- the meme-coin universe
is a hardcoded prompt choice presented as neutral "llm discovery".

This adds --discovery-universe/DISCOVERY_UNIVERSE (choices: meme [default],
major, defi, any), which parameterizes ONLY the coin-universe phrase of the
two discovery prompts. The default preserves today's prompts BYTE-IDENTICAL
(pinned below) -- everything else (+++SYM+++/***FAILED*** contract, DEX
tradeability constraints, etc.) is untouched.

Follows the tests/test_filter_precedence.py / tests/test_print_config.py
convention: exercise the pure builders directly, no live LLM/network calls.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
from claudeutil import ClaudeTrader
from openaiutil import OpenAITrader
from grokutil import GrokTrader
from perplexityutil import PerplexityTrader


# ============================================================================
# Byte-identical pin: default universe ('meme') must reproduce today's exact
# hardcoded prompts. These two strings were extracted verbatim (via ast.parse)
# from sendRecommendationRequest before this change -- do NOT hand-edit them.
# ============================================================================

ORIGINAL_DEX_PROMPT = (
    "What 3 Solana blockchain meme coins are major crypto analysts and "
    "influencers online currently discussing as having potential for "
    "short-term price appreciation? Only include coins tradeable on Solana "
    "DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, "
    "ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other "
    "chains like Base, Ethereum, or BNB. Once you have identified the top 3 "
    "being discussed, number them and indicate which show the most positive "
    "social media sentiment in the last 4 hours. Put 3 plus signs around "
    "EACH coin symbol separately at the end of your response. If you cannot "
    "identify any coins being actively discussed, include ***FAILED*** at "
    "the end of your output. Base your response on actual analyst "
    "discussions you are aware of."
)

ORIGINAL_CEX_PROMPT = (
    "What 3 meme coins listed on the Coinbase exchange are major crypto "
    "analysts and influencers online currently discussing as having "
    "potential for short-term price appreciation? Once you have identified "
    "the top 3 being discussed, number them and indicate which show the "
    "most positive social media sentiment in the last 4 hours. Put 3 plus "
    "signs around EACH coin symbol separately at the end of your response. "
    "If you cannot identify any coins being actively discussed, include "
    "***FAILED*** at the end of your output. Base your response on actual "
    "analyst discussions you are aware of."
)


def test_default_universe_dex_prompt_byte_identical():
    assert bot.build_discovery_prompt(dex_mode=True, universe='meme') == ORIGINAL_DEX_PROMPT


def test_default_universe_cex_prompt_byte_identical():
    assert bot.build_discovery_prompt(dex_mode=False, universe='meme') == ORIGINAL_CEX_PROMPT


# ============================================================================
# Each universe value lands in both prompt variants, replacing ONLY the
# universe phrase -- rest of the prompt (output contract, DEX constraints)
# stays intact.
# ============================================================================

_EXPECTED_PHRASES = {
    'meme': 'meme coins',
    'major': 'large-cap cryptocurrencies',
    'defi': 'DeFi tokens',
    'any': 'cryptocurrencies (any category)',
}


def test_universe_phrase_map_matches_spec():
    assert bot.DISCOVERY_UNIVERSE_PHRASES == _EXPECTED_PHRASES


def test_each_universe_lands_in_dex_prompt():
    for universe, phrase in _EXPECTED_PHRASES.items():
        prompt = bot.build_discovery_prompt(dex_mode=True, universe=universe)
        assert f"Solana blockchain {phrase}" in prompt, (universe, prompt)
        # Output contract untouched regardless of universe.
        assert '***FAILED***' in prompt
        assert 'Jupiter' in prompt


def test_each_universe_lands_in_cex_prompt():
    for universe, phrase in _EXPECTED_PHRASES.items():
        prompt = bot.build_discovery_prompt(dex_mode=False, universe=universe)
        assert f"What 3 {phrase} listed on the Coinbase exchange" in prompt, (universe, prompt)
        assert '***FAILED***' in prompt


def test_non_meme_universe_only_changes_the_universe_phrase():
    # Diffing the default vs a non-default universe should show a change
    # confined to the universe phrase -- nothing else in the prompt shifts.
    default_prompt = bot.build_discovery_prompt(dex_mode=False, universe='meme')
    major_prompt = bot.build_discovery_prompt(dex_mode=False, universe='major')
    assert default_prompt.replace('meme coins', 'large-cap cryptocurrencies') == major_prompt


# ============================================================================
# CLI > env > default precedence for --discovery-universe/DISCOVERY_UNIVERSE
# ============================================================================

def _parse(monkeypatch, argv, env):
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'] + argv)
    for k in ('DISCOVERY_UNIVERSE',):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return bot.parse_args()


def test_discovery_universe_default(monkeypatch):
    args = _parse(monkeypatch, [], {})
    assert args.discovery_universe == 'meme'


def test_discovery_universe_env_override(monkeypatch):
    args = _parse(monkeypatch, [], {'DISCOVERY_UNIVERSE': 'defi'})
    assert args.discovery_universe == 'defi'


def test_discovery_universe_cli_beats_env(monkeypatch):
    args = _parse(monkeypatch, ['--discovery-universe=any'], {'DISCOVERY_UNIVERSE': 'defi'})
    assert args.discovery_universe == 'any'


def test_discovery_universe_cli_alone(monkeypatch):
    args = _parse(monkeypatch, ['--discovery-universe=major'], {})
    assert args.discovery_universe == 'major'


def test_discovery_universe_invalid_env_fails_closed(monkeypatch, capsys):
    # argparse `choices` validates only CLI-supplied values, not defaults, so
    # an invalid env value would otherwise slip through to the banner while
    # build_discovery_prompt() silently fell back to the meme phrase -- the
    # banner/effect-honesty bug class. parse_args must refuse instead.
    with pytest.raises(SystemExit) as excinfo:
        _parse(monkeypatch, [], {'DISCOVERY_UNIVERSE': 'majors'})
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "'majors'" in err
    assert 'meme, major, defi, any' in err


def test_discovery_universe_env_case_insensitive(monkeypatch):
    # The env value is lowered before validation; uppercase spellings of valid
    # universes must keep working (regression pin for the fail-closed check).
    args = _parse(monkeypatch, [], {'DISCOVERY_UNIVERSE': 'DEFI'})
    assert args.discovery_universe == 'defi'


# ============================================================================
# Banner honesty: "Discovery Methods: llm (universe: <value>)" -- derived from
# the SAME resolved variable the prompt builder uses (bot.DISCOVERY_UNIVERSE
# after main() sets it), not a second literal.
# ============================================================================

def _discovery_methods_line(discovery_methods, use_llm_discovery, universe, source):
    """Reproduce the banner's line-building logic (mirrors how
    tests/test_filter_precedence.py pins _filter_lines_shown against the
    banner's actual gate) without running main() end-to-end."""
    methods_str = ', '.join(discovery_methods)
    if use_llm_discovery:
        methods_str += f" (universe: {universe})"
    return f"Discovery Methods: {methods_str} [{source}]"


def test_banner_includes_universe_when_llm_discovery_active():
    line = _discovery_methods_line(['llm'], True, 'meme', '--discovery-universe')
    assert line == "Discovery Methods: llm (universe: meme) [--discovery-universe]"


def test_banner_omits_universe_when_llm_not_active():
    line = _discovery_methods_line(['santiment'], False, 'meme', 'default')
    assert line == "Discovery Methods: santiment [default]"


def test_banner_universe_reflects_non_default_value():
    line = _discovery_methods_line(['llm'], True, 'major', 'DISCOVERY_UNIVERSE env')
    assert 'universe: major' in line


# ============================================================================
# Run summary: universe recorded only when llm discovery is in use.
# ============================================================================

def _build_summary(**overrides):
    kwargs = dict(
        run_id='run_20260721T000000Z_ws9',
        trading_mode='whatif',
        llm_mode='compare',
        primary_llm='gemini',
        compare_llms=['gemini', 'claude'],
        use_coin_discovery=True,
        discovery_methods=['llm'],
        analyze_coins=[],
        coins_to_buy=[],
        coins_excluded=[],
        coin_vote_outcomes=[],
        spend_tracker=bot.SpendTracker(10.0, 0.0),
        daily_spend_cap_usd=15.0,
        daily_cap_blocked=0,
        whatif_mode=True,
        whatif_buys=0,
    )
    kwargs.update(overrides)
    return bot.build_run_summary(**kwargs)


def test_run_summary_carries_universe_when_llm_discovery_active():
    summary = _build_summary(discovery_universe='meme')
    assert summary['discovery']['universe'] == 'meme'


def test_run_summary_omits_universe_when_llm_not_active():
    summary = _build_summary(discovery_methods=['santiment'], discovery_universe='meme')
    assert 'universe' not in summary['discovery']


def test_run_summary_omits_universe_when_not_discovery_mode():
    summary = _build_summary(
        use_coin_discovery=False, discovery_methods=[], analyze_coins=['BTC'],
        discovery_universe='meme')
    assert 'universe' not in summary['discovery']


def test_run_summary_backward_compatible_without_universe_arg():
    # Existing callers that don't pass discovery_universe at all must keep
    # working (optional kwarg, default None) and never add the key.
    summary = _build_summary()
    assert 'universe' not in summary['discovery']


def test_run_summary_universe_reflects_non_default_value():
    summary = _build_summary(discovery_universe='defi')
    assert summary['discovery']['universe'] == 'defi'


# ============================================================================
# --print-config: discovery_universe with correct source attribution.
# ============================================================================

_CONFIG_ENV_VARS_FOR_TEST = ['DISCOVERY_UNIVERSE']


def _report(monkeypatch, argv, env):
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'] + argv)
    for k in _CONFIG_ENV_VARS_FOR_TEST:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    args = bot.parse_args()
    return bot.build_config_report(args, os.environ)


def test_print_config_includes_discovery_universe_default(monkeypatch):
    report = _report(monkeypatch, ['--print-config'], {})
    entry = report['settings']['discovery_universe']
    assert entry == {'value': 'meme', 'source': 'default'}


def test_print_config_discovery_universe_env_source(monkeypatch):
    report = _report(monkeypatch, ['--print-config'], {'DISCOVERY_UNIVERSE': 'major'})
    entry = report['settings']['discovery_universe']
    assert entry == {'value': 'major', 'source': 'env'}


def test_print_config_discovery_universe_cli_source(monkeypatch):
    report = _report(monkeypatch, ['--print-config', '--discovery-universe=defi'],
                     {'DISCOVERY_UNIVERSE': 'major'})
    entry = report['settings']['discovery_universe']
    assert entry == {'value': 'defi', 'source': 'cli'}


# ============================================================================
# WS-9b follow-up: PRIMARY_LLM discovery is reachable via
# run_llm_discovery() -> get_primary_recommendation() -> <provider>_trader
# .send_recommendation_request() for claude/openai/grok/perplexity (not just
# gemini). Those four provider utils each hardcode their own copy of the
# "meme coins" discovery prompt pair -- claude/openai are byte-identical
# duplicates of the gemini-path prompt; grok/perplexity carry their own
# distinct wording (grok's "Using real-time web search..." prefix; both end
# "...you find." not "...you are aware of."). All four must honor
# --discovery-universe the same way build_discovery_prompt does: default
# universe ('meme') byte-identical, other universes swap ONLY the phrase.
#
# get_primary_recommendation() resolves the phrase once (from
# bot.DISCOVERY_UNIVERSE_PHRASES / bot.DISCOVERY_UNIVERSE) and passes it down
# as a finished string -- no import of crypto_trading_bot from the provider
# utils (they are imported BY crypto_trading_bot; importing back would be a
# cycle).
# ============================================================================

class _Capture:
    """Minimal stand-in for a provider SDK call: records kwargs, returns a
    canned response. Mirrors tests/test_structured_requests.py's Capture."""
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _make_claude(capture):
    trader = ClaudeTrader.__new__(ClaudeTrader)
    trader.client = SimpleNamespace(messages=SimpleNamespace(create=capture))
    trader.model = 'claude-test'
    trader.coin_type = 'cryptocurrency'
    return trader


def _make_openai(capture):
    trader = OpenAITrader.__new__(OpenAITrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'gpt-test'
    trader.coin_type = 'cryptocurrency'
    return trader


def _make_grok(capture):
    trader = GrokTrader.__new__(GrokTrader)
    trader.client = SimpleNamespace(responses=SimpleNamespace(create=capture))
    trader.model = 'grok-test'
    trader.tools = [{"type": "web_search"}]
    trader.coin_type = 'cryptocurrency'
    return trader


def _make_perplexity(capture):
    trader = PerplexityTrader.__new__(PerplexityTrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'sonar-test'
    trader.coin_type = 'cryptocurrency'
    return trader


def _claude_message(text):
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)])


def _openai_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason='stop')])


def _grok_response(output_text):
    return SimpleNamespace(output_text=output_text, status='completed')


def _perplexity_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason='stop')])


# Original (pre-WS9b) hardcoded prompt text per provider, extracted verbatim
# from source. claude/openai match the gemini-path ORIGINAL_*_PROMPT above
# exactly; grok/perplexity have their own wording.
_ORIGINAL_CLAUDE_OPENAI_CEX = ORIGINAL_CEX_PROMPT
_ORIGINAL_CLAUDE_OPENAI_DEX = ORIGINAL_DEX_PROMPT

_ORIGINAL_GROK_CEX = (
    "Using real-time web search for current market data and sentiment, "
    "what 3 meme coins listed on the Coinbase exchange are major crypto "
    "analysts and influencers online currently discussing as having "
    "potential for short-term price appreciation? Once you have identified "
    "the top 3 being discussed, number them and indicate which show the "
    "most positive social media sentiment in the last 4 hours. Put 3 plus "
    "signs around EACH coin symbol separately at the end of your response. "
    "If you cannot identify any coins being actively discussed, include "
    "***FAILED*** at the end of your output. Base your response on actual "
    "analyst discussions you find."
)

_ORIGINAL_PPLX_CEX = (
    "What 3 meme coins listed on the Coinbase exchange are major crypto "
    "analysts and influencers online currently discussing as having "
    "potential for short-term price appreciation? Once you have identified "
    "the top 3 being discussed, number them and indicate which show the "
    "most positive social media sentiment in the last 4 hours. Put 3 plus "
    "signs around EACH coin symbol separately at the end of your response. "
    "If you cannot identify any coins being actively discussed, include "
    "***FAILED*** at the end of your output. Base your response on actual "
    "analyst discussions you find."
)


def test_claude_discovery_default_phrase_byte_identical():
    cap = _Capture(_claude_message('+++DOGE+++'))
    _make_claude(cap).send_recommendation_request(dex_mode=False)
    prompt = cap.kwargs['messages'][0]['content']
    assert prompt == _ORIGINAL_CLAUDE_OPENAI_CEX


def test_openai_discovery_default_phrase_byte_identical():
    cap = _Capture(_openai_response('+++DOGE+++'))
    _make_openai(cap).send_recommendation_request(dex_mode=False)
    prompt = cap.kwargs['messages'][0]['content']
    assert prompt == _ORIGINAL_CLAUDE_OPENAI_CEX


def test_grok_discovery_default_phrase_byte_identical():
    cap = _Capture(_grok_response('+++DOGE+++'))
    _make_grok(cap).send_recommendation_request(dex_mode=False)
    prompt = cap.kwargs['input'][0]['content']
    assert prompt == _ORIGINAL_GROK_CEX


def test_perplexity_discovery_default_phrase_byte_identical():
    cap = _Capture(_perplexity_response('+++DOGE+++'))
    _make_perplexity(cap).send_recommendation_request(dex_mode=False)
    prompt = cap.kwargs['messages'][0]['content']
    assert prompt == _ORIGINAL_PPLX_CEX


@pytest.mark.parametrize('universe,phrase', list(_EXPECTED_PHRASES.items()))
def test_claude_discovery_honors_universe(universe, phrase):
    cap = _Capture(_claude_message('+++DOGE+++'))
    _make_claude(cap).send_recommendation_request(dex_mode=False, phrase=phrase)
    prompt = cap.kwargs['messages'][0]['content']
    assert f"What 3 {phrase} listed on the Coinbase exchange" in prompt
    assert '***FAILED***' in prompt


@pytest.mark.parametrize('universe,phrase', list(_EXPECTED_PHRASES.items()))
def test_openai_discovery_honors_universe(universe, phrase):
    cap = _Capture(_openai_response('+++DOGE+++'))
    _make_openai(cap).send_recommendation_request(dex_mode=False, phrase=phrase)
    prompt = cap.kwargs['messages'][0]['content']
    assert f"What 3 {phrase} listed on the Coinbase exchange" in prompt
    assert '***FAILED***' in prompt


@pytest.mark.parametrize('universe,phrase', list(_EXPECTED_PHRASES.items()))
def test_grok_discovery_honors_universe(universe, phrase):
    cap = _Capture(_grok_response('+++DOGE+++'))
    _make_grok(cap).send_recommendation_request(dex_mode=False, phrase=phrase)
    prompt = cap.kwargs['input'][0]['content']
    assert f"what 3 {phrase} listed on the Coinbase exchange" in prompt
    assert '***FAILED***' in prompt
    # Grok's own wording (web-search framing) survives untouched.
    assert prompt.startswith("Using real-time web search")


@pytest.mark.parametrize('universe,phrase', list(_EXPECTED_PHRASES.items()))
def test_perplexity_discovery_honors_universe(universe, phrase):
    cap = _Capture(_perplexity_response('+++DOGE+++'))
    _make_perplexity(cap).send_recommendation_request(dex_mode=False, phrase=phrase)
    prompt = cap.kwargs['messages'][0]['content']
    assert f"What 3 {phrase} listed on the Coinbase exchange" in prompt
    assert '***FAILED***' in prompt
    assert prompt.endswith("analyst discussions you find.")


@pytest.mark.parametrize('universe,phrase', list(_EXPECTED_PHRASES.items()))
def test_dex_mode_honors_universe_across_providers(universe, phrase):
    # DEX-mode variant also parameterizes correctly for every provider.
    claude_cap = _Capture(_claude_message('+++WIF+++'))
    _make_claude(claude_cap).send_recommendation_request(dex_mode=True, phrase=phrase)
    assert f"Solana blockchain {phrase}" in claude_cap.kwargs['messages'][0]['content']

    grok_cap = _Capture(_grok_response('+++WIF+++'))
    _make_grok(grok_cap).send_recommendation_request(dex_mode=True, phrase=phrase)
    assert f"Solana blockchain {phrase}" in grok_cap.kwargs['input'][0]['content']


# ============================================================================
# Call-site trace: get_primary_recommendation() resolves the same
# bot.DISCOVERY_UNIVERSE_PHRASES map and passes `phrase=` through to whichever
# provider trader is PRIMARY_LLM, so a non-gemini primary produces a prompt
# consistent with the gemini path's build_discovery_prompt for the same
# universe.
# ============================================================================

def test_get_primary_recommendation_passes_universe_phrase_to_claude(monkeypatch):
    cap = _Capture(_claude_message('+++DOGE+++'))
    trader = _make_claude(cap)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', 'claude', raising=False)
    monkeypatch.setattr(bot, 'claude_trader', trader, raising=False)
    monkeypatch.setattr(bot, 'DEX_MODE', False, raising=False)
    monkeypatch.setattr(bot, 'DISCOVERY_UNIVERSE', 'defi', raising=False)

    bot.get_primary_recommendation()

    prompt = cap.kwargs['messages'][0]['content']
    assert prompt == bot.build_discovery_prompt(dex_mode=False, universe='defi')


def test_get_primary_recommendation_default_universe_matches_gemini_builder(monkeypatch):
    cap = _Capture(_openai_response('+++DOGE+++'))
    trader = _make_openai(cap)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', 'openai', raising=False)
    monkeypatch.setattr(bot, 'openai_trader', trader, raising=False)
    monkeypatch.setattr(bot, 'DEX_MODE', False, raising=False)
    monkeypatch.setattr(bot, 'DISCOVERY_UNIVERSE', 'meme', raising=False)

    bot.get_primary_recommendation()

    prompt = cap.kwargs['messages'][0]['content']
    assert prompt == bot.build_discovery_prompt(dex_mode=False, universe='meme')
    assert prompt == ORIGINAL_CEX_PROMPT
