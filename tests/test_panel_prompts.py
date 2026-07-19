"""LM-2 golden characterization tests (audit 2026-07-19, prompt builders).

The core analysis prompt existed in ~20 verbatim copies across claudeutil /
openaiutil / grokutil / perplexityutil and the inline Gemini senders in
crypto_trading_bot.py. These tests snapshot the EXACT prompt text every one
of those call sites produces for fixed inputs, into
tests/fixtures/panel_prompts/golden_prompts.json.

The fixture was generated FROM THE PRE-CENTRALIZATION CODE (the duplicated
f-strings), so it is the byte truth of what each provider was asked before
panelprompts.py existed. The test rebuilds every prompt through the live
call paths (stubbed SDK clients, mirroring tests/test_framing.py /
test_structured_requests.py patterns -- zero network) and requires equality
byte-for-byte. Any refactor of the prompt plumbing must keep every one of
these strings identical; any INTENTIONAL prompt change must regenerate the
fixture in the same commit and say so.

Known inter-provider drift deliberately preserved (parameterized, not
unified -- see panelprompts.py):
  - grok prefixes a real-time-web-search preamble and its trend-check
    trends block ends "analysis." (no trailing space) with a " " before the
    vote instruction; every other provider ends "analysis. " and joins with
    no separator;
  - perplexity appends "Use current market data and recent news." /
    "Use current market data." / "Use live data." sentences after the core
    question, and its trend-check joins the vote instruction with NO space
    (so with no trends data the prompt reads "Use live data.Conclude ...");
  - perplexity's two trend variants use two DIFFERENT preambles ("recent
    social media trends and Google Trends data" vs "recent social media and
    search trends");
  - ALL FIVE providers now end with voteschema.schema_instruction: grok and
    perplexity were migrated to native structured output (T8 phase 2,
    2026-07-19), so the golden fixture was regenerated for their 14 entries
    (delimiter-tag sentence -> schema instruction) in that same change. The
    delimiter instruction survives only on their schema-rejection FALLBACK
    request, which this golden (a successful stubbed call) does not exercise;
    the preamble/suffix/spacing drift above is unchanged on both paths.

Regenerating (only for an intentional prompt change):
    ./venv/bin/python -c "import sys; sys.path[:0] = ['.', 'tests']; \
        import test_panel_prompts as t; t.write_fixture()"
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
from claudeutil import ClaudeTrader
from openaiutil import OpenAITrader
from grokutil import GrokTrader
from perplexityutil import PerplexityTrader

FIXTURE = Path(__file__).parent / 'fixtures' / 'panel_prompts' / 'golden_prompts.json'

# Fixed inputs. Chosen to be visibly synthetic and safely greppable in a
# failure diff; the goldens only pin the TEMPLATE bytes around them.
COIN = 'BTC'
MB = 'MARKET DATA (golden fixture block)\nprice=1.00'
TD = 'Golden fixture Google Trends series for BTC'
PA = '[GEMINI]: golden fixture peer analysis'


class _Capture:
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.result


def _make_claude(capture):
    trader = ClaudeTrader.__new__(ClaudeTrader)
    trader.client = SimpleNamespace(messages=SimpleNamespace(create=capture))
    trader.model = 'claude-test'
    trader.coin_type = 'cryptocurrency'
    return trader, lambda: capture.kwargs['messages'][0]['content']


def _make_openai(capture):
    trader = OpenAITrader.__new__(OpenAITrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'gpt-test'
    trader.coin_type = 'cryptocurrency'
    return trader, lambda: capture.kwargs['messages'][0]['content']


def _make_grok(capture):
    trader = GrokTrader.__new__(GrokTrader)
    trader.client = SimpleNamespace(responses=SimpleNamespace(create=capture))
    trader.model = 'grok-test'
    trader.tools = [{"type": "web_search"}]
    trader.coin_type = 'cryptocurrency'
    return trader, lambda: capture.kwargs['input'][0]['content']


def _make_perplexity(capture):
    trader = PerplexityTrader.__new__(PerplexityTrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'sonar-test'
    trader.coin_type = 'cryptocurrency'
    return trader, lambda: capture.kwargs['messages'][0]['content']


_TRADER_RESULTS = {
    'claude': lambda: SimpleNamespace(content=[]),
    'openai': lambda: SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='x'), finish_reason='stop')]),
    'grok': lambda: SimpleNamespace(output_text='x'),
    'perplexity': lambda: SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='x'), finish_reason='stop')]),
}

_TRADER_MAKERS = {
    'claude': _make_claude,
    'openai': _make_openai,
    'grok': _make_grok,
    'perplexity': _make_perplexity,
}

# Each analysis call site x input variant. (method, args builder). The four
# methods per provider are the whole LM-2 scope; discovery prompts are out.
_CASES = [
    ('coin_check/mb',
     'send_coin_check_request', lambda: ((COIN,), {'market_block': MB})),
    ('coin_check/no_mb',
     'send_coin_check_request', lambda: ((COIN,), {'market_block': None})),
    ('trend_check/mb_td',
     'send_trend_check_request', lambda: ((COIN, TD), {'market_block': MB})),
    ('trend_check/mb_no_td',
     'send_trend_check_request', lambda: ((COIN, None), {'market_block': MB})),
    ('integrated_coin/mb_pa',
     'send_integrated_coin_check', lambda: ((COIN, PA), {'market_block': MB})),
    ('integrated_trend/mb_td_pa',
     'send_integrated_trend_check', lambda: ((COIN, PA, TD), {'market_block': MB})),
    ('integrated_trend/mb_no_td_pa',
     'send_integrated_trend_check', lambda: ((COIN, PA, None), {'market_block': MB})),
]

_GEMINI_CASES = [
    ('coin_check/mb', bot.sendCoinCheckRequest, lambda: ((COIN,), {'market_block': MB})),
    ('coin_check/no_mb', bot.sendCoinCheckRequest, lambda: ((COIN,), {'market_block': None})),
    ('trend_check/mb_td', bot.sendTrendCheckRequest, lambda: ((COIN, TD), {'market_block': MB})),
    ('trend_check/mb_no_td', bot.sendTrendCheckRequest, lambda: ((COIN, None), {'market_block': MB})),
    ('integrated_coin/mb_pa', bot.sendIntegratedCoinCheckRequest,
     lambda: ((COIN, PA), {'market_block': MB})),
    ('integrated_trend/mb_td_pa', bot.sendIntegratedTrendCheckRequest,
     lambda: ((COIN, PA, TD), {'market_block': MB})),
    ('integrated_trend/mb_no_td_pa', bot.sendIntegratedTrendCheckRequest,
     lambda: ((COIN, PA, None), {'market_block': MB})),
]

_MISSING = object()


def build_all_prompts():
    """Build every analysis prompt through the LIVE call paths (stubbed SDK
    clients) with the fixed inputs above. Returns {case_id: prompt_text}."""
    prompts = {}

    for provider, maker in _TRADER_MAKERS.items():
        for case_id, method_name, args_fn in _CASES:
            capture = _Capture(_TRADER_RESULTS[provider]())
            trader, get_prompt = maker(capture)
            args, kwargs = args_fn()
            getattr(trader, method_name)(*args, **kwargs)
            prompts[f'{provider}/{case_id}'] = get_prompt()

    # Gemini: module-level senders read bot.client / bot.USE_COIN_DISCOVERY
    # (neither exists until main() runs). Set and fully restore.
    old_client = getattr(bot, 'client', _MISSING)
    old_discovery = getattr(bot, 'USE_COIN_DISCOVERY', _MISSING)
    try:
        bot.USE_COIN_DISCOVERY = False  # 'cryptocurrency', like the traders above
        for case_id, fn, args_fn in _GEMINI_CASES:
            capture = _Capture(SimpleNamespace(text='x'))
            bot.client = SimpleNamespace(
                models=SimpleNamespace(generate_content=capture))
            args, kwargs = args_fn()
            fn(*args, **kwargs)
            prompts[f'gemini/{case_id}'] = capture.kwargs['contents']
    finally:
        for name, old in (('client', old_client), ('USE_COIN_DISCOVERY', old_discovery)):
            if old is _MISSING:
                if hasattr(bot, name):
                    delattr(bot, name)
            else:
                setattr(bot, name, old)

    return prompts


def write_fixture():
    """Regenerate the golden fixture from the CURRENT code paths. Use only
    for an intentional prompt change, in the same commit, called out."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(build_all_prompts(), indent=2, sort_keys=True))
    print(f'wrote {FIXTURE}')


def test_every_call_site_matches_golden_bytes():
    golden = json.loads(FIXTURE.read_text())
    built = build_all_prompts()
    assert sorted(built) == sorted(golden), (
        'case set changed -- prompt call sites added/removed?')
    for case_id in sorted(golden):
        assert built[case_id] == golden[case_id], (
            f'prompt text drifted from golden at {case_id!r}')


def test_golden_fixture_covers_all_five_providers():
    golden = json.loads(FIXTURE.read_text())
    providers = {c.split('/', 1)[0] for c in golden}
    assert providers == {'gemini', 'claude', 'openai', 'grok', 'perplexity'}
    # 7 input variants across the 4 analysis methods, per provider.
    for provider in providers:
        assert sum(c.startswith(provider + '/') for c in golden) == 7, provider


def test_known_drift_is_still_present():
    """Pin the drift we chose to PRESERVE (not silently unify). If one of
    these fails after an intentional unification, update fixture + this test
    + the drift notes in panelprompts.py together."""
    golden = json.loads(FIXTURE.read_text())
    # grok: web-search preamble, lowercase 'would'
    assert 'Using real-time web search for current market data and sentiment, would' \
        in golden['grok/coin_check/mb']
    # grok trend block joins the vote instruction with a single space (vote_sep
    # drift); the vote instruction itself is now the schema one (T8 phase 2)
    assert 'Use this data in your analysis. Provide your conclusion as a JSON object' \
        in golden['grok/trend_check/mb_td']
    # perplexity: no-space join when trends data absent (drift preserved) — the
    # vote instruction is the schema one, so the join reads "data.Provide"
    assert 'Use live data.Provide your conclusion as a JSON object' \
        in golden['perplexity/trend_check/mb_no_td']
    # perplexity: two different trend preambles
    assert 'recent social media trends and Google Trends data' \
        in golden['perplexity/trend_check/mb_td']
    assert 'recent social media and search trends' \
        in golden['perplexity/integrated_trend/mb_td_pa']
    # gemini/claude/openai share identical bytes at every case
    for case_id, _, _ in _CASES:
        assert golden[f'claude/{case_id}'] == golden[f'openai/{case_id}'] \
            == golden[f'gemini/{case_id}'], case_id
