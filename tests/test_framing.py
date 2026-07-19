"""Tests for T7 (prompt framing fixes, plan Phase 2).

EVALUATION_LESSONS_LEARNED_2026-07-18.md 1.4 / 5.3.1 / 5.7 #11: three
framing bugs, closed here.

  1. claudeutil.py's Round-2 methods (send_integrated_coin_check,
     send_integrated_trend_check) hardcoded the literal string "meme coin"
     instead of using self.coin_type like every other method (Round-1 on
     Claude, and both rounds on openai/grok/perplexity already did this
     correctly). Verified live: with ANALYZE_COINS=ETH set, Claude's Round-2
     response still objected to "the meme coin" framing -- unfixable by the
     env var for Claude specifically. Fixed by swapping the literal for
     self.coin_type.

  2. `--coins` never set the ANALYZE_COINS env var that all four panel
     trader __init__ methods read to choose "cryptocurrency" vs "meme coin"
     framing, so an explicit `--coins=BTC` run still called BTC a "meme
     coin" for claude/openai/grok/perplexity (Gemini reads USE_COIN_DISCOVERY
     directly in crypto_trading_bot.py and was already correct). Fixed via a
     new pure helper, resolve_analyze_coins_env(use_coin_discovery,
     analyze_coins), called from main() before trader construction.

  3. Wherever Google Trends data is injected into a prompt, the block now
     carries one factual sentence disclosing the max=100 window
     normalization (doc 5.7 #11) -- only when trends data IS present;
     absence disclosure is T9's job, not implemented here.

No real network calls anywhere in this file. Round-2 prompt-builder tests
use the same client-mocking pattern as tests/test_structured_requests.py
(a Capture callable standing in for the SDK's create() method). Trader
constructor tests call the real __init__ with fake API keys monkeypatched
in -- constructing anthropic.Anthropic / openai.OpenAI clients does not
touch the network (verified empirically: sub-second, no outbound call).
Gemini-side tests reuse test_structured_requests.py's pattern of
monkeypatching crypto_trading_bot.client / .USE_COIN_DISCOVERY; bot.main()
is never invoked (it does far more than framing resolution -- parses argv,
constructs the Coinbase client, etc. -- consistent with
tests/test_model_registry.py's documented no-main() convention).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import voteschema
from claudeutil import ClaudeTrader
from openaiutil import OpenAITrader
from grokutil import GrokTrader
from perplexityutil import PerplexityTrader

NORMALIZATION_PHRASE = "window maximum = 100"


def vote_json(symbol='BTC', action='BUY'):
    return json.dumps({"symbol": symbol, "action": action, "confidence": 0.8,
                       "abstain": False, "reasons": ["r1"]})


class Capture:
    """Callable that records kwargs and returns a canned result (mirrors
    tests/test_structured_requests.py -- no network, just records the
    request the code built)."""
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.result


# ============================================================================
# 1. Round-2 "meme coin" hardcode (claudeutil.py, and a panel-wide regression
#    guard so no provider silently reintroduces the bug).
# ============================================================================

def make_claude(capture, coin_type='cryptocurrency'):
    trader = ClaudeTrader.__new__(ClaudeTrader)
    trader.client = SimpleNamespace(messages=SimpleNamespace(create=capture))
    trader.model = 'claude-test'
    trader.coin_type = coin_type
    return trader


def claude_message(text):
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)])


def make_openai(capture, coin_type='cryptocurrency'):
    trader = OpenAITrader.__new__(OpenAITrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'gpt-test'
    trader.coin_type = coin_type
    return trader


def openai_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason='stop')])


def make_grok(capture, coin_type='cryptocurrency'):
    trader = GrokTrader.__new__(GrokTrader)
    trader.client = SimpleNamespace(responses=SimpleNamespace(create=capture))
    trader.model = 'grok-test'
    trader.tools = [{"type": "web_search"}]
    trader.coin_type = coin_type
    return trader


def grok_response(text):
    return SimpleNamespace(output_text=text)


def make_perplexity(capture, coin_type='cryptocurrency'):
    trader = PerplexityTrader.__new__(PerplexityTrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'sonar-test'
    trader.coin_type = coin_type
    return trader


def perplexity_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content))])


class TestClaudeRoundTwoFraming:
    """claudeutil.py:118/:158 (pre-fix) hardcoded "meme coin"; this pins the
    fix to self.coin_type, matching Round-1 and every other provider."""

    def test_integrated_coin_check_uses_coin_type_not_hardcode(self):
        cap = Capture(claude_message(vote_json()))
        make_claude(cap, coin_type='cryptocurrency').send_integrated_coin_check('BTC', 'peer says HOLD')
        prompt = cap.kwargs['messages'][0]['content']
        assert 'cryptocurrency' in prompt
        assert 'meme coin' not in prompt

    def test_integrated_trend_check_uses_coin_type_not_hardcode(self):
        cap = Capture(claude_message(vote_json()))
        make_claude(cap, coin_type='cryptocurrency').send_integrated_trend_check(
            'BTC', 'peer says HOLD', 'trend data')
        prompt = cap.kwargs['messages'][0]['content']
        assert 'cryptocurrency' in prompt
        assert 'meme coin' not in prompt

    def test_discovery_coin_type_still_reaches_round_two(self):
        # Regression guard: discovery mode's "meme coin" framing must still
        # flow through when that IS the correct coin_type (this is not the
        # bug -- the bug was ignoring coin_type entirely).
        cap = Capture(claude_message(vote_json()))
        make_claude(cap, coin_type='meme coin').send_integrated_coin_check('PEPE', 'peer says BUY')
        prompt = cap.kwargs['messages'][0]['content']
        assert 'meme coin' in prompt


@pytest.mark.parametrize("make,response,method,args", [
    (make_claude, claude_message(vote_json()), 'send_integrated_coin_check', ('BTC', 'peer')),
    (make_claude, claude_message(vote_json()), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
    (make_openai, openai_response(vote_json()), 'send_integrated_coin_check', ('BTC', 'peer')),
    (make_openai, openai_response(vote_json()), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
    (make_grok, grok_response('<**BTC-PRS-BUY**>'), 'send_integrated_coin_check', ('BTC', 'peer')),
    (make_grok, grok_response('<**BTC-PRS-BUY**>'), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
    (make_perplexity, perplexity_response('<**BTC-PRS-BUY**>'), 'send_integrated_coin_check', ('BTC', 'peer')),
    (make_perplexity, perplexity_response('<**BTC-PRS-BUY**>'), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
])
def test_round_two_framing_is_coin_type_panel_wide(make, response, method, args):
    """Panel-wide regression guard (doc 5.3.1's fix note: "the --coins fix
    must also de-hardcode the Round-2 Claude prompts" -- generalized to
    cover every provider's Round-2 builder, not just the one that broke)."""
    cap = Capture(response)
    trader = make(cap, coin_type='cryptocurrency')
    getattr(trader, method)(*args)
    prompt = cap.kwargs['messages'][0]['content'] if 'messages' in cap.kwargs else cap.kwargs['input'][0]['content']
    assert 'cryptocurrency' in prompt
    assert 'meme coin' not in prompt


# ============================================================================
# 2. `--coins` framing propagation: resolve_analyze_coins_env (pure) +
#    trader __init__ actually picking up the resulting env var.
# ============================================================================

class TestResolveAnalyzeCoinsEnv:
    """Pure function -- no os.environ, no trader construction."""

    def test_discovery_mode_returns_none(self):
        assert bot.resolve_analyze_coins_env(True, []) is None
        # Even if ANALYZE_COINS somehow carried a stale list, discovery mode
        # (USE_COIN_DISCOVERY=True) means --coins was NOT used; don't touch
        # the env var.
        assert bot.resolve_analyze_coins_env(True, ['BTC']) is None

    def test_coins_mode_returns_joined_list(self):
        assert bot.resolve_analyze_coins_env(False, ['BTC', 'ETH']) == 'BTC,ETH'

    def test_coins_mode_single_coin(self):
        assert bot.resolve_analyze_coins_env(False, ['BTC']) == 'BTC'


class TestTraderConstructionFraming:
    """Deliverable #2's acceptance criterion: a trader constructed under
    ANALYZE_COINS (what main() now sets for --coins runs, via
    resolve_analyze_coins_env) frames coins as "cryptocurrency"."""

    @pytest.mark.parametrize("trader_cls,env_var", [
        (ClaudeTrader, 'CLAUDE_API_KEY'),
        (OpenAITrader, 'OPENAI_API_KEY'),
        (GrokTrader, 'XAI_API_KEY'),
        (PerplexityTrader, 'PERPLEXITY_API_KEY'),
    ])
    def test_analyze_coins_env_set_gives_cryptocurrency_framing(self, monkeypatch, trader_cls, env_var):
        monkeypatch.setenv(env_var, 'fake-key-for-test')
        monkeypatch.setenv('ANALYZE_COINS', 'BTC,ETH')
        trader = trader_cls()
        assert trader.coin_type == 'cryptocurrency'

    @pytest.mark.parametrize("trader_cls,env_var", [
        (ClaudeTrader, 'CLAUDE_API_KEY'),
        (OpenAITrader, 'OPENAI_API_KEY'),
        (GrokTrader, 'XAI_API_KEY'),
        (PerplexityTrader, 'PERPLEXITY_API_KEY'),
    ])
    def test_analyze_coins_env_unset_keeps_discovery_framing(self, monkeypatch, trader_cls, env_var):
        # Regression guard: discovery mode (no --coins) must keep its "meme
        # coin" framing -- that's its actual domain, not a bug.
        monkeypatch.setenv(env_var, 'fake-key-for-test')
        monkeypatch.delenv('ANALYZE_COINS', raising=False)
        trader = trader_cls()
        assert trader.coin_type == 'meme coin'

    def test_main_style_flow_end_to_end(self, monkeypatch):
        """Simulates exactly what main() does: parse-derived USE_COIN_DISCOVERY
        / ANALYZE_COINS -> resolve_analyze_coins_env -> os.environ -> trader
        construction. Ties the pure resolver to the actually-observed trader
        behavior without invoking bot.main()."""
        monkeypatch.setenv('CLAUDE_API_KEY', 'fake-key-for-test')
        monkeypatch.delenv('ANALYZE_COINS', raising=False)

        use_coin_discovery = False
        analyze_coins = ['BTC']
        env_value = bot.resolve_analyze_coins_env(use_coin_discovery, analyze_coins)
        assert env_value is not None
        monkeypatch.setenv('ANALYZE_COINS', env_value)

        trader = ClaudeTrader()
        assert trader.coin_type == 'cryptocurrency'


# ============================================================================
# 3. Trends normalization disclosure -- present only when trends_data IS
#    supplied, across every trend-prompt builder in the bot + trader utils.
# ============================================================================

class TestClaudeTrendsDisclosure:

    def test_trend_check_includes_note_when_data_present(self):
        cap = Capture(claude_message(vote_json()))
        make_claude(cap).send_trend_check_request('BTC', 'raw trend series')
        assert NORMALIZATION_PHRASE in cap.kwargs['messages'][0]['content']

    def test_trend_check_omits_note_when_no_data(self):
        cap = Capture(claude_message(vote_json()))
        make_claude(cap).send_trend_check_request('BTC', None)
        assert NORMALIZATION_PHRASE not in cap.kwargs['messages'][0]['content']

    def test_integrated_trend_check_includes_note_when_data_present(self):
        cap = Capture(claude_message(vote_json()))
        make_claude(cap).send_integrated_trend_check('BTC', 'peer', 'raw trend series')
        assert NORMALIZATION_PHRASE in cap.kwargs['messages'][0]['content']

    def test_integrated_trend_check_omits_note_when_no_data(self):
        cap = Capture(claude_message(vote_json()))
        make_claude(cap).send_integrated_trend_check('BTC', 'peer', None)
        assert NORMALIZATION_PHRASE not in cap.kwargs['messages'][0]['content']


@pytest.mark.parametrize("make,response,method,args", [
    (make_claude, claude_message(vote_json()), 'send_trend_check_request', ('BTC', 'trend data')),
    (make_claude, claude_message(vote_json()), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
    (make_openai, openai_response(vote_json()), 'send_trend_check_request', ('BTC', 'trend data')),
    (make_openai, openai_response(vote_json()), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
    (make_grok, grok_response('<**BTC-PRS-BUY**>'), 'send_trend_check_request', ('BTC', 'trend data')),
    (make_grok, grok_response('<**BTC-PRS-BUY**>'), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
    (make_perplexity, perplexity_response('<**BTC-PRS-BUY**>'), 'send_trend_check_request', ('BTC', 'trend data')),
    (make_perplexity, perplexity_response('<**BTC-PRS-BUY**>'), 'send_integrated_trend_check', ('BTC', 'peer', 'trend data')),
])
def test_trends_disclosure_present_panel_wide(make, response, method, args):
    cap = Capture(response)
    trader = make(cap)
    getattr(trader, method)(*args)
    prompt = cap.kwargs['messages'][0]['content'] if 'messages' in cap.kwargs else cap.kwargs['input'][0]['content']
    assert NORMALIZATION_PHRASE in prompt


@pytest.mark.parametrize("make,response,method,args", [
    (make_claude, claude_message(vote_json()), 'send_trend_check_request', ('BTC', None)),
    (make_openai, openai_response(vote_json()), 'send_trend_check_request', ('BTC', None)),
    (make_grok, grok_response('<**BTC-PRS-BUY**>'), 'send_trend_check_request', ('BTC', None)),
    (make_perplexity, perplexity_response('<**BTC-PRS-BUY**>'), 'send_trend_check_request', ('BTC', None)),
])
def test_trends_disclosure_absent_panel_wide_when_no_data(make, response, method, args):
    # T9 owns the "trends fetch failed" disclosure; absence must stay silent
    # here, not gain a note this task wasn't asked to add.
    cap = Capture(response)
    trader = make(cap)
    getattr(trader, method)(*args)
    prompt = cap.kwargs['messages'][0]['content'] if 'messages' in cap.kwargs else cap.kwargs['input'][0]['content']
    assert NORMALIZATION_PHRASE not in prompt


# ============================================================================
# Gemini side (crypto_trading_bot.py's own sendTrendCheckRequest /
# sendIntegratedTrendCheckRequest) -- same pattern as
# tests/test_structured_requests.py's TestGeminiRequests.
# ============================================================================

def gemini_response(text):
    return SimpleNamespace(text=text)


class Capture3:
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def __call__(self, *, model, contents, config):
        self.kwargs = {'model': model, 'contents': contents, 'config': config}
        return self.result


def patch_gemini(monkeypatch, capture, use_coin_discovery=False):
    monkeypatch.setattr(bot, 'client',
                        SimpleNamespace(models=SimpleNamespace(generate_content=capture)),
                        raising=False)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', use_coin_discovery, raising=False)


class TestGeminiTrendsDisclosure:

    def test_trend_check_includes_note_when_data_present(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap)
        bot.sendTrendCheckRequest('BTC', 'trend data')
        assert NORMALIZATION_PHRASE in cap.kwargs['contents']

    def test_trend_check_omits_note_when_no_data(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap)
        bot.sendTrendCheckRequest('BTC', None)
        assert NORMALIZATION_PHRASE not in cap.kwargs['contents']

    def test_integrated_trend_check_includes_note_when_data_present(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap)
        bot.sendIntegratedTrendCheckRequest('BTC', 'peer', 'trend data')
        assert NORMALIZATION_PHRASE in cap.kwargs['contents']

    def test_integrated_trend_check_omits_note_when_no_data(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap)
        bot.sendIntegratedTrendCheckRequest('BTC', 'peer', None)
        assert NORMALIZATION_PHRASE not in cap.kwargs['contents']

    def test_gemini_coin_type_unaffected_by_analyze_coins_env(self, monkeypatch):
        # Gemini deliberately reads USE_COIN_DISCOVERY directly, not the
        # ANALYZE_COINS env var -- confirm the T7 fix left that alone.
        monkeypatch.delenv('ANALYZE_COINS', raising=False)
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap, use_coin_discovery=False)
        bot.sendCoinCheckRequest('BTC')
        assert 'cryptocurrency' in cap.kwargs['contents']


# ============================================================================
# F7b: get_llm_response must not double-inject trends when a market block is
# already cached for the coin. T9 folded a demoted GOOGLE TRENDS SECONDARY
# section into the market block; the provider utils' send_trend_check_request
# / send_integrated_trend_check still accept a separate trends_data param
# (kept -- see the "Trends normalization disclosure" tests above, which
# exercise it directly and are genuine, independent coverage, not vestigial).
# get_llm_response is the one place both a real market block AND a real
# trends_data value could be supplied together, so it is the fix's choke
# point: forward trends_data only when no market block is cached.
#
# use_trend_check=True is not reachable from either live call site in
# main() today (both call process_coin_with_comparison with the default
# use_trend_check=False -- T9 moved trends fully inside the block), so this
# guards a currently-latent path, not an observed live bug.
# ============================================================================

MARKET_BLOCK_TRENDS_MARKER = "GOOGLE TRENDS SECONDARY: present (cached in block)"
RAW_TRENDS_DATA_MARKER = "RAW_TREND_SERIES_FROM_CALLER"


def _cached_block_with_trends():
    return (f"MARKET DATA (Coinbase BTC-USD, verifiable by all panelists): "
            f"last_price=100\n{MARKET_BLOCK_TRENDS_MARKER}\nRULE: verify before citing.")


def _prep_llm_response_provider(monkeypatch, llm_name, cap):
    """Cache a market block for BTC and wire `cap` in as the given
    provider's request-capturing client, mirroring
    tests/test_market_data.py's TestGetLlmResponseReadsCache pattern."""
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {'BTC': _cached_block_with_trends()},
                        raising=False)
    monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {}, raising=False)
    if llm_name == 'gemini':
        monkeypatch.setattr(bot, 'client',
                            SimpleNamespace(models=SimpleNamespace(generate_content=cap)),
                            raising=False)
        monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)
        return
    builders = {'claude': make_claude, 'openai': make_openai,
                'grok': make_grok, 'perplexity': make_perplexity}
    attrs = {'claude': 'claude_trader', 'openai': 'openai_trader',
             'grok': 'grok_trader', 'perplexity': 'perplexity_trader'}
    trader = builders[llm_name](cap)
    monkeypatch.setattr(bot, attrs[llm_name], trader, raising=False)


def _prompt_from(llm_name, cap):
    if llm_name == 'gemini':
        return cap.kwargs['contents']
    return cap.kwargs['messages'][0]['content'] if 'messages' in cap.kwargs else cap.kwargs['input'][0]['content']


class TestTrendsNotDoubleInjected:

    def test_claude_trend_check_with_cached_block_suppresses_trends_data(self, monkeypatch):
        cap = Capture(claude_message(vote_json()))
        _prep_llm_response_provider(monkeypatch, 'claude', cap)

        bot.get_llm_response('claude', 'BTC', use_trend_check=True,
                             trends_data=RAW_TRENDS_DATA_MARKER)

        prompt = _prompt_from('claude', cap)
        # the block's own trends section made it through...
        assert prompt.count('GOOGLE TRENDS') == 1
        # ...but the separately-supplied trends_data did not get a second,
        # independent injection.
        assert RAW_TRENDS_DATA_MARKER not in prompt
        assert 'BEGIN GOOGLE TRENDS DATA' not in prompt

    @pytest.mark.parametrize("llm_name,response", [
        ('claude', claude_message(vote_json())),
        ('openai', openai_response(vote_json())),
        ('grok', grok_response('<**BTC-PRS-BUY**>')),
        ('perplexity', perplexity_response('<**BTC-PRS-BUY**>')),
        ('gemini', gemini_response(vote_json())),
    ])
    def test_trend_check_panel_wide_no_double_injection(self, monkeypatch, llm_name, response):
        cap = Capture(response) if llm_name != 'gemini' else Capture3(response)
        _prep_llm_response_provider(monkeypatch, llm_name, cap)

        bot.get_llm_response(llm_name, 'BTC', use_trend_check=True,
                             trends_data=RAW_TRENDS_DATA_MARKER)

        prompt = _prompt_from(llm_name, cap)
        assert prompt.count('GOOGLE TRENDS') == 1
        assert RAW_TRENDS_DATA_MARKER not in prompt

    def test_trend_check_without_cached_block_still_uses_trends_data(self, monkeypatch):
        """Regression guard on the guard: when NO market block is cached,
        trends_data must still reach the prompt exactly as before -- the
        fix only suppresses it when a block is present, it must not
        silently drop trends_data in the direct/no-block case (that's the
        documented, tested T7 API surface)."""
        cap = Capture(claude_message(vote_json()))
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {}, raising=False)
        monkeypatch.setattr(bot, 'claude_trader', make_claude(cap), raising=False)

        bot.get_llm_response('claude', 'BTC', use_trend_check=True,
                             trends_data=RAW_TRENDS_DATA_MARKER)

        prompt = _prompt_from('claude', cap)
        assert RAW_TRENDS_DATA_MARKER in prompt
        assert MARKET_BLOCK_TRENDS_MARKER not in prompt  # no block was cached at all
