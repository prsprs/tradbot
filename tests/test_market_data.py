"""T9: real Coinbase market-data injection (plan Phase 2).
T12/T13: CoinMarketCap CMC section + LunarCrush SOCIAL section.

Covers marketdata.py (fetch/summarize/fib/block assembly + failure-path
disclosures) and its injection into every provider's analysis prompt via
crypto_trading_bot. No network anywhere:

  - fetch_candles is exercised against a fake RESTClient returning
    string-field candles (the shape captured live 2026-07-18).
  - summarize/fib/block use the real lab candle fixture
    (lab/session_tests_20260718/btc_7d_1h.csv, the §5.6 data that produced
    coherent analyses).
  - prompt-injection tests reuse the Capture/patch mocking from
    tests/test_structured_requests.py and tests/test_framing.py.
  - get_trends_status classification uses a fake pytrends (real pandas frames).
  - marketdata.build_market_block fetches CMC/SOCIAL itself (see its
    docstring: it's the only seam available without touching the off-limits
    crypto_trading_bot.py), so an autouse fixture below
    (`_stub_cmc_social_fetches`) monkeypatches
    marketdata.fetch_cmc_status/fetch_social_status to deterministic
    'unavailable' stand-ins for EVERY test in this file by default -- no
    test hits CoinMarketCap or LunarCrush over the network. Tests that
    specifically exercise CMC/SOCIAL behavior override those two names
    locally with fakes built from the tests/fixtures/coinmarketcap_*.json
    and tests/fixtures/lunarcrush_*.json response fixtures (captured live
    2026-07-18).
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import marketdata
from claudeutil import ClaudeTrader
from openaiutil import OpenAITrader
from grokutil import GrokTrader
from perplexityutil import PerplexityTrader

# Captured before the autouse fixture below ever monkeypatches these names,
# so tests that target fetch_cmc_status/fetch_social_status THEMSELVES can
# restore the real implementation (while still mocking the network one
# layer down, at _fetch_cmc_quote_raw / _fetch_lunarcrush_*_raw).
_REAL_FETCH_CMC_STATUS = marketdata.fetch_cmc_status
_REAL_FETCH_SOCIAL_STATUS = marketdata.fetch_social_status

LAB_CSV = Path(__file__).parent.parent / "lab" / "session_tests_20260718" / "btc_7d_1h.csv"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

STUB_CMC_UNAVAILABLE = {'status': 'unavailable', 'data': None, 'reason': 'test stub: not fetched'}
STUB_SOCIAL_UNAVAILABLE = {'status': 'unavailable', 'data': None, 'reason': 'test stub: not fetched'}


@pytest.fixture(autouse=True)
def _stub_cmc_social_fetches(monkeypatch):
    """No test in this file may reach CoinMarketCap or LunarCrush over the
    network. build_market_block calls marketdata.fetch_cmc_status /
    fetch_social_status by name (module-global lookup at call time), so
    patching them here on the `marketdata` module neutralizes every call
    path -- direct build_market_block() calls AND the
    bot.build_market_block_for_coin -> marketdata.build_market_block chain.
    Individual tests override one or both with monkeypatch.setattr(...) to
    exercise the present/failure/cache-sharing paths explicitly.
    """
    monkeypatch.setattr(marketdata, 'fetch_cmc_status',
                        lambda coin: dict(STUB_CMC_UNAVAILABLE), raising=False)
    monkeypatch.setattr(marketdata, 'fetch_social_status',
                        lambda coin: dict(STUB_SOCIAL_UNAVAILABLE), raising=False)


def load_lab_rows():
    """Normalized rows from the §5.6 lab BTC candle CSV (the proven data)."""
    rows = []
    with open(LAB_CSV) as f:
        for r in csv.DictReader(f):
            ts = datetime.fromisoformat(r['timestamp'])
            rows.append({
                'time': int(ts.timestamp()),
                'timestamp': ts,
                'open': float(r['Open']), 'high': float(r['High']),
                'low': float(r['Low']), 'close': float(r['Close']),
                'volume': float(r['Volume']),
            })
    return rows


def synth_rows(closes, start_ts=1_784_000_000, step=3600, volume=100.0):
    """Synthesize normalized hourly rows from a list of close prices."""
    rows = []
    for i, c in enumerate(closes):
        t = start_ts + i * step
        rows.append({
            'time': t,
            'timestamp': datetime.fromtimestamp(t, tz=timezone.utc),
            'open': c, 'high': c * 1.01, 'low': c * 0.99, 'close': c,
            'volume': volume,
        })
    return rows


# ============================ fetch_candles =================================

class FakeCandleClient:
    """Stand-in RESTClient: records the get_candles call and returns
    dict-like Candle rows with STRING fields (the real Coinbase shape),
    deliberately newest-first to prove fetch_candles sorts ascending."""
    def __init__(self, candles, as_attr=False):
        self._candles = candles
        self.as_attr = as_attr
        self.calls = []

    def get_candles(self, **kwargs):
        self.calls.append(kwargs)
        if self.as_attr:
            return SimpleNamespace(candles=self._candles)
        return {'candles': self._candles}


def _candle(t, o, h, l, c, v):
    # strings, mirroring the live API
    return {'start': str(t), 'open': str(o), 'high': str(h),
            'low': str(l), 'close': str(c), 'volume': str(v)}


class TestFetchCandles:

    def test_coerces_strings_and_sorts_ascending(self):
        newest_first = [
            _candle(1000 + 7200, 3, 3.5, 2.9, 3.2, 12),
            _candle(1000 + 3600, 2, 2.5, 1.9, 2.2, 11),
            _candle(1000, 1, 1.5, 0.9, 1.2, 10),
        ]
        client = FakeCandleClient(newest_first)
        rows = marketdata.fetch_candles(client, 'BTC-USD', days=7)
        assert [r['time'] for r in rows] == [1000, 4600, 8200]  # ascending
        assert all(isinstance(r['close'], float) for r in rows)
        assert rows[0]['close'] == 1.2 and rows[-1]['close'] == 3.2
        assert isinstance(rows[0]['timestamp'], datetime)

    def test_passes_unix_second_string_bounds_and_granularity(self):
        client = FakeCandleClient([_candle(1000, 1, 1, 1, 1, 1)])
        marketdata.fetch_candles(client, 'ETH-USD', days=7, granularity='ONE_HOUR')
        call = client.calls[0]
        assert call['product_id'] == 'ETH-USD'
        assert call['granularity'] == 'ONE_HOUR'
        assert call['start'].isdigit() and call['end'].isdigit()
        assert int(call['end']) - int(call['start']) == 7 * 86400

    def test_response_as_attribute_also_supported(self):
        client = FakeCandleClient([_candle(1000, 1, 1, 1, 1, 1)], as_attr=True)
        rows = marketdata.fetch_candles(client, 'BTC-USD')
        assert len(rows) == 1

    def test_empty_response_returns_empty_list(self):
        assert marketdata.fetch_candles(FakeCandleClient([]), 'BTC-USD') == []


# ========================= summarize_market_data ===========================

class TestSummarize:

    def test_lab_data_summary_is_plausible(self):
        s = marketdata.summarize_market_data(load_lab_rows())
        assert s['n_candles'] == 168
        assert 6.5 < s['window_days'] < 7.1
        # BTC hovered ~64k in the fixture window.
        assert 60000 < s['last_price'] < 66000
        assert s['low'] < s['last_price'] < s['high']
        assert 0 <= s['range_position_pct'] <= 100
        assert s['volume_trend'] in ('rising', 'falling', 'steady')
        assert s['volatility_pct'] >= 0
        # as_of is a compact UTC stamp
        assert s['as_of'].endswith('Z')

    def test_empty_rows_returns_none(self):
        assert marketdata.summarize_market_data([]) is None

    def test_changes_reflect_direction(self):
        rows = synth_rows([100.0] * 24 + [110.0])  # up ~10% over last step
        s = marketdata.summarize_market_data(rows)
        assert s['change_24h'] is not None and s['change_24h'] > 0
        assert s['last_price'] == 110.0

    def test_short_window_leaves_long_lookbacks_none(self):
        # only 3 hourly candles: no 24h/72h history to look back to.
        s = marketdata.summarize_market_data(synth_rows([10.0, 11.0, 12.0]))
        assert s['change_24h'] is None
        assert s['change_72h'] is None
        # 7d change falls back to the oldest available candle
        assert s['change_7d'] is not None

    def test_rising_volume_trend(self):
        rows = synth_rows([100.0] * 10)
        for r in rows[5:]:
            r['volume'] = 1000.0  # second half much heavier
        assert marketdata.summarize_market_data(rows)['volume_trend'] == 'rising'


# ============================== fib_summary ================================

class TestFibSummary:

    def test_lab_data_matches_known_report(self):
        fib = marketdata.fib_summary(load_lab_rows(), 'BTC')
        assert fib is not None
        assert fib['trend_direction'] in ('up', 'down')
        assert fib['most_respected_level'] is not None
        assert 1 <= len(fib['nearest']) <= 3
        # nearest levels are sorted by absolute distance from price
        dists = [abs(l['distance_pct']) for l in fib['nearest']]
        assert dists == sorted(dists)

    def test_too_few_points_degrades_to_none(self):
        assert marketdata.fib_summary(synth_rows([1.0, 2.0]), 'BTC') is None

    def test_empty_rows_degrades_to_none(self):
        assert marketdata.fib_summary([], 'BTC') is None


# ============================ build_market_block ===========================

TRENDS_PRESENT = {'status': 'present', 'data': 'Google Trends: avg 42, max 100'}
TRENDS_FLOOR = {'status': 'below_floor', 'data': None}
TRENDS_FAILED = {'status': 'failed', 'data': None}
TRENDS_NONE = {'status': 'unavailable', 'data': None}


def normal_block():
    rows = load_lab_rows()
    s = marketdata.summarize_market_data(rows)
    fib = marketdata.fib_summary(rows, 'BTC')
    return marketdata.build_market_block('BTC', s, fib, TRENDS_PRESENT)


class TestBuildMarketBlock:

    def test_normal_block_has_all_labeled_sections(self):
        block = normal_block()
        assert 'MARKET DATA (Coinbase BTC-USD, verifiable by all panelists' in block
        assert 'FIBONACCI' in block
        assert 'GOOGLE TRENDS (secondary signal' in block
        assert block.strip().splitlines()[-1].startswith('RULE:')
        assert 'Do not invent indicator values' in block
        # trends is positioned AFTER market data (secondary)
        assert block.index('MARKET DATA') < block.index('GOOGLE TRENDS')

    def test_token_budget_under_500_for_normal_case(self):
        block = normal_block()
        approx_tokens = len(block) / 4.0  # ~4 chars/token
        assert approx_tokens < 500, f"block too large: ~{approx_tokens:.0f} tokens"
        assert len(block.split()) < 500

    def test_market_data_unavailable_is_explicit_never_silent(self):
        block = marketdata.build_market_block(
            'BTC', None, None, TRENDS_NONE,
            unavailable_reason='429 from Coinbase')
        assert 'MARKET DATA UNAVAILABLE (BTC-USD): 429 from Coinbase' in block
        # trends section is still rendered (independent)
        assert 'GOOGLE TRENDS' in block
        assert 'RULE:' in block

    def test_unavailable_without_reason_still_discloses(self):
        block = marketdata.build_market_block('BTC', None, None, TRENDS_NONE)
        assert 'MARKET DATA UNAVAILABLE' in block

    def test_fib_failure_degrades_to_summary_note(self):
        s = marketdata.summarize_market_data(load_lab_rows())
        block = marketdata.build_market_block('BTC', s, None, TRENDS_PRESENT)
        assert 'MARKET DATA (Coinbase' in block
        assert 'retracement levels unavailable' in block

    def test_trends_below_floor_disclosed(self):
        block = normal_block_with_trends(TRENDS_FLOOR)
        assert 'search volume below measurement floor' in block

    def test_trends_fetch_failure_disclosed(self):
        block = normal_block_with_trends(TRENDS_FAILED)
        assert 'data collection failed (rate limit)' in block
        assert 'unsupported' in block

    def test_trends_present_carries_normalization_note(self):
        block = normal_block_with_trends(TRENDS_PRESENT)
        assert 'window maximum = 100' in block

    def test_trends_absence_never_silent(self):
        # every trends state produces a labeled line (doc 5.3.9)
        for status in (TRENDS_FLOOR, TRENDS_FAILED, TRENDS_NONE):
            block = normal_block_with_trends(status)
            assert 'GOOGLE TRENDS (secondary signal)' in block


def normal_block_with_trends(trends_status):
    rows = load_lab_rows()
    s = marketdata.summarize_market_data(rows)
    fib = marketdata.fib_summary(rows, 'BTC')
    return marketdata.build_market_block('BTC', s, fib, trends_status)


# ============================ grounding labels =============================

class TestGroundingLabel:

    @pytest.mark.parametrize("llm", ['gemini', 'grok', 'perplexity'])
    def test_grounded_providers_get_search_disclosure(self, llm):
        label = marketdata.grounding_label(llm)
        assert 'live search access' in label
        assert 'separate' in label.lower()

    @pytest.mark.parametrize("llm", ['claude', 'openai'])
    def test_ungrounded_providers_get_primary_evidence_line(self, llm):
        label = marketdata.grounding_label(llm)
        assert 'MARKET DATA section is your primary evidence' in label


# ===================== get_trends_status classification ====================

class FakePytrends:
    def __init__(self, df=None, raise_on_build=False):
        self._df = df
        self.raise_on_build = raise_on_build

    def build_payload(self, *a, **k):
        if self.raise_on_build:
            raise RuntimeError("429 Too Many Requests")

    def interest_over_time(self):
        return self._df


class TestGetTrendsStatus:

    def test_present_series(self, monkeypatch):
        df = pd.DataFrame({'BTC': [10, 20, 30, 40]})
        monkeypatch.setattr(bot, 'pytrends', FakePytrends(df), raising=False)
        st = bot.get_trends_status('BTC')
        assert st['status'] == 'present'
        assert 'Google Trends data for BTC' in st['data']

    def test_all_zero_is_below_floor(self, monkeypatch):
        df = pd.DataFrame({'BTC': [0, 0, 0, 0]})
        monkeypatch.setattr(bot, 'pytrends', FakePytrends(df), raising=False)
        assert bot.get_trends_status('BTC')['status'] == 'below_floor'

    def test_fetch_exception_is_failed(self, monkeypatch):
        monkeypatch.setattr(bot, 'pytrends', FakePytrends(raise_on_build=True), raising=False)
        assert bot.get_trends_status('BTC')['status'] == 'failed'

    def test_empty_frame_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(bot, 'pytrends', FakePytrends(pd.DataFrame()), raising=False)
        assert bot.get_trends_status('BTC')['status'] == 'unavailable'


# =========== build_market_block_for_coin (cache + failure path) ============

class TestBuildMarketBlockForCoin:

    def test_dex_mode_no_client_discloses_unavailable(self, monkeypatch):
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
        monkeypatch.setattr(bot, 'get_trends_status',
                            lambda c: TRENDS_NONE, raising=False)
        block = bot.build_market_block_for_coin('BTC', candle_client=None)
        assert 'MARKET DATA UNAVAILABLE' in block
        assert 'DEX mode' in block

    def test_success_path_builds_full_block_and_caches(self, monkeypatch):
        cache = {}
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', cache, raising=False)
        monkeypatch.setattr(bot, 'get_trends_status',
                            lambda c: TRENDS_PRESENT, raising=False)
        client = FakeCandleClient([
            _candle(1000 + i * 3600, 100 + i, 101 + i, 99 + i, 100 + i, 50)
            for i in range(10)
        ])
        block = bot.build_market_block_for_coin('BTC', candle_client=client)
        assert 'MARKET DATA (Coinbase BTC-USD' in block
        assert cache['BTC'] == block  # cached
        # second call is served from cache (no second fetch)
        bot.build_market_block_for_coin('BTC', candle_client=client)
        assert len(client.calls) == 1

    def test_fetch_exception_disclosed_not_raised(self, monkeypatch):
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
        monkeypatch.setattr(bot, 'get_trends_status',
                            lambda c: TRENDS_FAILED, raising=False)

        class Boom:
            def get_candles(self, **k):
                raise RuntimeError("network down")

        block = bot.build_market_block_for_coin('BTC', candle_client=Boom())
        assert 'MARKET DATA UNAVAILABLE' in block
        assert 'RuntimeError' in block
        # trends failure is independently disclosed
        assert 'data collection failed' in block


# =============== injection into every provider analysis prompt =============

MB = "MARKET DATA (Coinbase BTC-USD, verifiable by all panelists): SENTINEL"


class Capture:
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.result


def make_claude(cap):
    t = ClaudeTrader.__new__(ClaudeTrader)
    t.client = SimpleNamespace(messages=SimpleNamespace(create=cap))
    t.model, t.coin_type = 'claude-test', 'cryptocurrency'
    return t


def claude_message(text):
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)])


def make_openai(cap):
    t = OpenAITrader.__new__(OpenAITrader)
    t.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=cap)))
    t.model, t.coin_type = 'gpt-test', 'cryptocurrency'
    return t


def openai_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason='stop')])


def make_grok(cap):
    t = GrokTrader.__new__(GrokTrader)
    t.client = SimpleNamespace(responses=SimpleNamespace(create=cap))
    t.model, t.tools, t.coin_type = 'grok-test', [{"type": "web_search"}], 'cryptocurrency'
    return t


def grok_response(text):
    return SimpleNamespace(output_text=text)


def make_perplexity(cap):
    t = PerplexityTrader.__new__(PerplexityTrader)
    t.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=cap)))
    t.model, t.coin_type = 'sonar-test', 'cryptocurrency'
    return t


def perplexity_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def prompt_of(cap):
    if 'messages' in cap.kwargs:
        return cap.kwargs['messages'][0]['content']
    return cap.kwargs['input'][0]['content']


ANALYSIS_METHODS = [
    ('send_coin_check_request', ('BTC',)),
    ('send_trend_check_request', ('BTC', 'trend data')),
    ('send_integrated_coin_check', ('BTC', 'peer says HOLD')),
    ('send_integrated_trend_check', ('BTC', 'peer says HOLD', 'trend data')),
]

PROVIDER_BUILDERS = [
    (make_claude, claude_message(json.dumps({"symbol": "BTC", "action": "BUY",
        "confidence": 0.8, "abstain": False, "reasons": ["r"]}))),
    (make_openai, openai_response(json.dumps({"symbol": "BTC", "action": "BUY",
        "confidence": 0.8, "abstain": False, "reasons": ["r"]}))),
    (make_grok, grok_response('<**BTC-PRS-BUY**>')),
    (make_perplexity, perplexity_response('<**BTC-PRS-BUY**>')),
]


class TestPromptInjectionEveryProvider:
    """The market block reaches the prompt of EVERY provider's every analysis
    builder (deliverable #2: Round 1 + Round 2, trend + coin checks)."""

    @pytest.mark.parametrize("make,response", PROVIDER_BUILDERS)
    @pytest.mark.parametrize("method,args", ANALYSIS_METHODS)
    def test_market_block_prepended(self, make, response, method, args):
        cap = Capture(response)
        trader = make(cap)
        getattr(trader, method)(*args, market_block=MB)
        assert MB in prompt_of(cap)

    @pytest.mark.parametrize("make,response", PROVIDER_BUILDERS)
    @pytest.mark.parametrize("method,args", ANALYSIS_METHODS)
    def test_no_block_leaves_prompt_clean(self, make, response, method, args):
        cap = Capture(response)
        trader = make(cap)
        getattr(trader, method)(*args)  # market_block defaults None
        assert 'MARKET DATA' not in prompt_of(cap)


# --- Gemini inline builders ---

def gemini_response(text):
    return SimpleNamespace(text=text)


class Capture3:
    def __init__(self, result):
        self.kwargs, self.result = None, result

    def __call__(self, *, model, contents, config):
        self.kwargs = {'model': model, 'contents': contents, 'config': config}
        return self.result


def patch_gemini(monkeypatch, cap):
    monkeypatch.setattr(bot, 'client',
                        SimpleNamespace(models=SimpleNamespace(generate_content=cap)),
                        raising=False)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)


class TestGeminiInlineInjection:

    @pytest.mark.parametrize("call", [
        lambda: bot.sendCoinCheckRequest('BTC', market_block=MB),
        lambda: bot.sendTrendCheckRequest('BTC', 'trend data', market_block=MB),
        lambda: bot.sendIntegratedCoinCheckRequest('BTC', 'peer', market_block=MB),
        lambda: bot.sendIntegratedTrendCheckRequest('BTC', 'peer', 'trend data', market_block=MB),
    ])
    def test_market_block_prepended(self, monkeypatch, call):
        cap = Capture3(gemini_response('{}'))
        patch_gemini(monkeypatch, cap)
        call()
        assert MB in cap.kwargs['contents']

    def test_no_block_leaves_prompt_clean(self, monkeypatch):
        cap = Capture3(gemini_response('{}'))
        patch_gemini(monkeypatch, cap)
        bot.sendCoinCheckRequest('BTC')
        assert 'MARKET DATA' not in cap.kwargs['contents']


# ============ get_llm_response reads the cache and attaches grounding =======

class TestGetLlmResponseReadsCache:

    def _prep(self, monkeypatch, llm, trader_attr, trader, block='CACHED_MARKET_BLOCK'):
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {'BTC': block}, raising=False)
        monkeypatch.setattr(bot, trader_attr, trader, raising=False)

    def test_claude_gets_cached_block_and_ungrounded_label(self, monkeypatch):
        cap = Capture(claude_message(json.dumps({"symbol": "BTC", "action": "HOLD",
            "confidence": 0.6, "abstain": False, "reasons": ["r"]})))
        self._prep(monkeypatch, 'claude', 'claude_trader', make_claude(cap))
        bot.get_llm_response('claude', 'BTC', use_trend_check=False)
        prompt = prompt_of(cap)
        assert 'CACHED_MARKET_BLOCK' in prompt
        assert 'primary evidence' in prompt  # ungrounded label

    def test_grok_gets_grounded_label(self, monkeypatch):
        cap = Capture(grok_response('<**BTC-PRS-HOLD**>'))
        self._prep(monkeypatch, 'grok', 'grok_trader', make_grok(cap))
        bot.get_llm_response('grok', 'BTC', use_trend_check=False)
        prompt = prompt_of(cap)
        assert 'CACHED_MARKET_BLOCK' in prompt
        assert 'live search access' in prompt  # grounded label

    def test_empty_cache_injects_nothing(self, monkeypatch):
        cap = Capture(claude_message(json.dumps({"symbol": "BTC", "action": "HOLD",
            "confidence": 0.6, "abstain": False, "reasons": ["r"]})))
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
        monkeypatch.setattr(bot, 'claude_trader', make_claude(cap), raising=False)
        bot.get_llm_response('claude', 'BTC', use_trend_check=False)
        assert 'MARKET DATA' not in prompt_of(cap)


# ============ per-coin trends fix: first-coin-only injection is gone ========

class TestFirstCoinOnlyTrendsRemoved:

    def test_source_no_longer_has_first_coin_only_trends(self):
        src = (Path(__file__).parent.parent / 'crypto_trading_bot.py').read_text()
        # the doc-5.3.x bug: use_trend = (i == 0). It must be gone as code.
        assert 'use_trend = (i == 0)' not in src

    def test_loops_build_market_block_per_coin(self):
        src = (Path(__file__).parent.parent / 'crypto_trading_bot.py').read_text()
        # both the coin-choice and discovery loops now build a per-coin block
        # (the candle-client line appears once per loop, not in the def).
        assert src.count("candle_client = None if DEX_MODE else getattr(trader, 'client', None)") == 2
        # 2 loop call sites + 1 function definition
        assert src.count('build_market_block_for_coin(coin_symbol') == 3


# =========================== T12: CoinMarketCap CMC ==========================

def load_fixture(name):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


CMC_QUOTE_FIXTURE = load_fixture('coinmarketcap_quotes_latest_btc_v3.json')
# F3: captured live 2026-07-19 querying quotes/latest BY ID (params={'id':
# '1', ...}) instead of by symbol -- proves `data` is the same LIST shape
# either way, so no separate response-parsing branch is needed.
CMC_QUOTE_BY_ID_FIXTURE = load_fixture('coinmarketcap_quotes_latest_btc_v3_by_id.json')
# F3: captured live 2026-07-19 from /v1/cryptocurrency/map?symbol=ONDO --
# the auto_resolve_symbol path for a symbol not in the static
# SYMBOL_TO_CMC_ID cache (0 credits per AGENTS.md, confirmed by
# status.credit_count == 0 in the fixture).
CMC_MAP_ONDO_FIXTURE = load_fixture('coinmarketcap_map_ondo_v1.json')


@pytest.fixture
def isolated_symbol_cache(monkeypatch):
    """F3: auto_resolve_symbol mutates coinmarketcaputil.SYMBOL_TO_CMC_ID in
    place (its caching behavior, by design). Swap in a shallow copy for the
    duration of the test so a resolution discovered here never leaks into
    other tests via the shared module-level dict -- monkeypatch restores
    the original dict object on teardown."""
    monkeypatch.setattr(
        marketdata.coinmarketcaputil, 'SYMBOL_TO_CMC_ID',
        dict(marketdata.coinmarketcaputil.SYMBOL_TO_CMC_ID), raising=False)
    return marketdata.coinmarketcaputil.SYMBOL_TO_CMC_ID


def _fake_get_by_url(monkeypatch, by_url, captured=None):
    """Install a fake requests.get that dispatches on a substring of the
    URL (quotes/latest vs. cryptocurrency/map need different canned
    bodies in the auto-resolve tests)."""
    class FakeResp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def fake_get(url, headers=None, params=None, timeout=None):
        if captured is not None:
            captured.setdefault('calls', []).append(
                {'url': url, 'headers': headers, 'params': params})
        for marker, body in by_url.items():
            if marker in url:
                return FakeResp(body)
        raise AssertionError(f"unexpected URL in test: {url}")

    import requests as real_requests
    monkeypatch.setattr(real_requests, 'get', fake_get)


class TestResolveCmcId:
    """F3: symbol -> CMC id resolution, cheapest path first."""

    def test_known_symbol_resolves_from_static_cache_no_network(self, monkeypatch):
        import requests as real_requests

        def fail(*a, **k):
            raise AssertionError("known symbol must not touch the network")
        monkeypatch.setattr(real_requests, 'get', fail)

        assert marketdata._resolve_cmc_id('BTC') == 1  # SYMBOL_TO_CMC_ID['BTC']

    def test_unmapped_symbol_falls_through_to_auto_resolve(self, monkeypatch, isolated_symbol_cache):
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: True, raising=False)
        assert 'ONDO' not in isolated_symbol_cache
        _fake_get_by_url(monkeypatch, {'cryptocurrency/map': CMC_MAP_ONDO_FIXTURE})

        cmc_id = marketdata._resolve_cmc_id('ONDO')
        assert cmc_id == 21159  # from the live-captured fixture
        # auto_resolve_symbol caches the discovery back into SYMBOL_TO_CMC_ID
        assert isolated_symbol_cache['ONDO'] == 21159

    def test_truly_unmappable_symbol_returns_none(self, monkeypatch, isolated_symbol_cache):
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: True, raising=False)
        _fake_get_by_url(monkeypatch, {'cryptocurrency/map': {'data': []}})

        assert marketdata._resolve_cmc_id('NOTACOIN') is None
        assert 'NOTACOIN' not in isolated_symbol_cache


class TestFetchCmcQuoteRaw:
    """_fetch_cmc_quote_raw parses the authentic v3 response shape (`quote`
    is a LIST, unlike v1/v2's `quote: {USD: {...}}` dict) via a mocked
    `requests.get` -- no network."""

    def test_parses_authentic_v3_fixture(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return CMC_QUOTE_FIXTURE

        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: True, raising=False)
        captured = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            captured['url'] = url
            captured['headers'] = headers
            captured['params'] = params
            return FakeResp()

        import requests as real_requests
        monkeypatch.setattr(real_requests, 'get', fake_get)

        data = marketdata._fetch_cmc_quote_raw('BTC')
        assert data['cmc_rank'] == 1
        assert data['market_cap_dominance'] == pytest.approx(58.724)
        assert data['circulating_supply'] == 20058175
        assert data['max_supply'] == 21000000
        assert data['supply_ratio_pct'] == pytest.approx(20058175 / 21000000 * 100.0)
        assert data['percent_change_1h'] == pytest.approx(-0.13380481)
        assert data['percent_change_24h'] == pytest.approx(1.30321139)
        assert data['percent_change_7d'] == pytest.approx(0.91843665)
        assert data['percent_change_30d'] == pytest.approx(3.15638094)
        # X-CMC_PRO_API_KEY header carries the key, never printed/logged elsewhere
        assert captured['headers']['X-CMC_PRO_API_KEY'] == 'fake-key'
        assert 'quotes/latest' in captured['url']
        # F3: BTC resolves via the static id cache -- queried BY ID, not
        # by symbol, and the result is marked unambiguous.
        assert captured['params'] == {'id': '1', 'convert': 'USD'}
        assert data['id_resolved'] is True

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', '', raising=False)
        with pytest.raises(RuntimeError, match='not set'):
            marketdata._fetch_cmc_quote_raw('BTC')

    def test_throttle_exhaustion_raises(self, monkeypatch):
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: False, raising=False)
        with pytest.raises(RuntimeError, match='budget exhausted'):
            marketdata._fetch_cmc_quote_raw('BTC')

    def test_parses_authentic_by_id_fixture(self, monkeypatch):
        """F3: the id-based response fixture (captured live 2026-07-19)
        parses identically to the symbol-based one -- same list shape."""
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: True, raising=False)
        _fake_get_by_url(monkeypatch, {'quotes/latest': CMC_QUOTE_BY_ID_FIXTURE})

        data = marketdata._fetch_cmc_quote_raw('BTC')
        assert data['cmc_rank'] == 1
        assert data['id_resolved'] is True
        assert data['market_cap_dominance'] == pytest.approx(58.7644)
        assert data['circulating_supply'] == 20058196

    def test_unmappable_symbol_falls_back_to_symbol_query_and_discloses(
            self, monkeypatch, isolated_symbol_cache):
        """F3: when the symbol can't be resolved to an id at all (unknown
        to both the static cache and /v1/cryptocurrency/map), the quote
        call falls back to `symbol=` -- but the result is marked
        id_resolved=False, never silently trusted."""
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: True, raising=False)
        captured = {}
        # Empty map result (unmappable) for the resolve step; the
        # symbol-based quote fallback still returns real-shaped data (the
        # collision RISK is what's being tested, not a fetch failure).
        _fake_get_by_url(
            monkeypatch,
            {'cryptocurrency/map': {'data': []}, 'quotes/latest': CMC_QUOTE_FIXTURE},
            captured=captured)

        data = marketdata._fetch_cmc_quote_raw('NOTACOIN')
        assert data['id_resolved'] is False
        quote_call = next(c for c in captured['calls'] if 'quotes/latest' in c['url'])
        assert quote_call['params'] == {'symbol': 'NOTACOIN', 'convert': 'USD'}

    def test_auto_resolved_symbol_is_queried_by_id(self, monkeypatch, isolated_symbol_cache):
        """F3: a symbol absent from the static cache but found via
        /v1/cryptocurrency/map is queried BY ID, not by symbol."""
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'fake-key', raising=False)
        monkeypatch.setattr(marketdata.coinmarketcaputil, '_rate_limit', lambda: True, raising=False)
        captured = {}
        _fake_get_by_url(
            monkeypatch,
            {'cryptocurrency/map': CMC_MAP_ONDO_FIXTURE, 'quotes/latest': CMC_QUOTE_FIXTURE},
            captured=captured)

        data = marketdata._fetch_cmc_quote_raw('ONDO')
        assert data['id_resolved'] is True
        quote_call = next(c for c in captured['calls'] if 'quotes/latest' in c['url'])
        assert quote_call['params'] == {'id': '21159', 'convert': 'USD'}


class TestFetchCmcStatus:
    """Tests fetch_cmc_status itself, so each test first restores the real
    implementation over the file-wide autouse stub (see
    _REAL_FETCH_CMC_STATUS) and mocks one layer down instead, at
    _fetch_cmc_quote_raw -- still zero network calls."""

    def test_success_classifies_present(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_cmc_status', _REAL_FETCH_CMC_STATUS, raising=False)
        monkeypatch.setattr(marketdata, '_fetch_cmc_quote_raw',
                            lambda coin: {'cmc_rank': 1}, raising=False)
        status = marketdata.fetch_cmc_status('BTC')
        assert status == {'status': 'present', 'data': {'cmc_rank': 1}, 'reason': None}

    def test_any_exception_classifies_unavailable_with_reason(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_cmc_status', _REAL_FETCH_CMC_STATUS, raising=False)

        def boom(coin):
            raise RuntimeError('HTTP 429')
        monkeypatch.setattr(marketdata, '_fetch_cmc_quote_raw', boom, raising=False)
        status = marketdata.fetch_cmc_status('BTC')
        assert status['status'] == 'unavailable'
        assert status['data'] is None
        assert 'HTTP 429' in status['reason']

    def test_never_raises(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_cmc_status', _REAL_FETCH_CMC_STATUS, raising=False)
        monkeypatch.setattr(marketdata, '_fetch_cmc_quote_raw',
                            lambda coin: (_ for _ in ()).throw(ValueError('boom')),
                            raising=False)
        marketdata.fetch_cmc_status('BTC')  # must not raise


class TestBuildCmcSection:

    def test_present_renders_rank_dominance_supply_and_changes(self):
        status = {'status': 'present', 'data': {
            'cmc_rank': 1, 'market_cap_dominance': 58.7,
            'circulating_supply': 20058175, 'max_supply': 21000000,
            'supply_ratio_pct': 95.5,
            'percent_change_1h': -0.1, 'percent_change_24h': 1.3,
            'percent_change_7d': 0.9, 'percent_change_30d': 3.2,
        }, 'reason': None}
        section = marketdata.build_cmc_section(status, 'BTC')
        assert section.startswith('CMC (CoinMarketCap, fetched this run):')
        assert 'Rank #1' in section
        assert '58.7%' in section
        assert '95.5%' in section
        assert '+1.3%' in section  # 24h
        # no id_resolved field at all (pre-F3 shape) -- no warning, unchanged
        assert 'AMBIGUITY' not in section

    def test_id_resolved_true_renders_no_ambiguity_warning(self):
        status = {'status': 'present', 'data': {
            'cmc_rank': 1, 'market_cap_dominance': 58.7,
            'circulating_supply': 20058175, 'max_supply': 21000000,
            'supply_ratio_pct': 95.5,
            'percent_change_1h': -0.1, 'percent_change_24h': 1.3,
            'percent_change_7d': 0.9, 'percent_change_30d': 3.2,
            'id_resolved': True,
        }, 'reason': None}
        section = marketdata.build_cmc_section(status, 'BTC')
        assert 'AMBIGUITY' not in section

    def test_id_resolved_false_renders_ambiguity_warning(self):
        """F3: an unmappable symbol's fallback symbol-query result must
        carry a visible, explicit disclosure -- never a silently-trusted
        data[0] for a possibly wrong asset."""
        status = {'status': 'present', 'data': {
            'cmc_rank': 1, 'market_cap_dominance': 58.7,
            'circulating_supply': 20058175, 'max_supply': 21000000,
            'supply_ratio_pct': 95.5,
            'percent_change_1h': -0.1, 'percent_change_24h': 1.3,
            'percent_change_7d': 0.9, 'percent_change_30d': 3.2,
            'id_resolved': False,
        }, 'reason': None}
        section = marketdata.build_cmc_section(status, 'WEIRDCOIN')
        assert 'AMBIGUITY WARNING' in section
        assert 'WEIRDCOIN' in section
        assert 'DIFFERENT asset' in section
        assert 'UNVERIFIED' in section
        # the warning is appended after the normal sections, not replacing them
        assert 'Rank #1' in section

    def test_unavailable_is_disclosed_never_silent(self):
        status = {'status': 'unavailable', 'data': None, 'reason': 'HTTPError: 429'}
        section = marketdata.build_cmc_section(status, 'BTC')
        assert section == 'CMC DATA UNAVAILABLE (BTC): HTTPError: 429.'

    def test_missing_status_dict_is_disclosed(self):
        section = marketdata.build_cmc_section(None, 'BTC')
        assert 'CMC DATA UNAVAILABLE (BTC)' in section

    def test_no_max_supply_degrades_gracefully(self):
        # e.g. ETH has no max_supply cap
        status = {'status': 'present', 'data': {
            'cmc_rank': 2, 'market_cap_dominance': 12.0,
            'circulating_supply': 120000000, 'max_supply': None,
            'supply_ratio_pct': None,
            'percent_change_1h': 0.0, 'percent_change_24h': 0.0,
            'percent_change_7d': 0.0, 'percent_change_30d': 0.0,
        }, 'reason': None}
        section = marketdata.build_cmc_section(status, 'ETH')
        assert 'no max supply cap' in section


# ========================== T13: LunarCrush SOCIAL ===========================

LC_COIN_FIXTURE = load_fixture('lunarcrush_coins_btc_v1.json')
LC_TOPIC_FIXTURE = load_fixture('lunarcrush_topic_bitcoin_v1.json')


class TestFetchLunarcrushRaw:
    """The two raw fetchers against the authentic fixtures, with a mocked
    `requests.get` (no network) that also asserts the auth/User-Agent
    headers the AGENTS.md gotcha requires."""

    def _fake_get(self, monkeypatch, json_body, captured):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return json_body

        def fake_get(url, headers=None, timeout=None):
            captured['url'] = url
            captured['headers'] = headers
            return FakeResp()

        import requests as real_requests
        monkeypatch.setattr(real_requests, 'get', fake_get)

    def test_coin_endpoint_parses_fixture_and_sets_headers(self, monkeypatch):
        monkeypatch.setenv('LUNARCRUSH_API_KEY', 'fake-key')
        monkeypatch.setattr(marketdata, '_lunarcrush_throttle', lambda: None, raising=False)
        captured = {}
        self._fake_get(monkeypatch, LC_COIN_FIXTURE, captured)

        data = marketdata._fetch_lunarcrush_coin_raw('BTC')
        assert data['galaxy_score'] == 66.7
        assert data['alt_rank'] == 40
        assert data['name'] == 'Bitcoin'
        assert captured['headers']['Authorization'] == 'Bearer fake-key'
        # Cloudflare 403s Python's default UA (AGENTS.md gotcha) -- must be overridden
        assert captured['headers']['User-Agent'] != ''
        assert 'python-requests' not in captured['headers']['User-Agent']
        assert '/coins/btc/v1' in captured['url']

    def test_topic_endpoint_parses_fixture(self, monkeypatch):
        monkeypatch.setenv('LUNARCRUSH_API_KEY', 'fake-key')
        monkeypatch.setattr(marketdata, '_lunarcrush_throttle', lambda: None, raising=False)
        captured = {}
        self._fake_get(monkeypatch, LC_TOPIC_FIXTURE, captured)

        data = marketdata._fetch_lunarcrush_topic_raw('bitcoin')
        assert data['interactions_24h'] == 139663499
        assert data['num_contributors'] == 47152
        assert data['num_posts'] == 118661
        assert data['topic_rank'] == 137
        assert set(data['types_sentiment'].keys()) == {
            'news', 'instagram-post', 'reddit-post', 'youtube-video',
            'tiktok-video', 'tweet'}
        assert '/topic/bitcoin/v1' in captured['url']

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv('LUNARCRUSH_API_KEY', raising=False)
        with pytest.raises(RuntimeError, match='not set'):
            marketdata._fetch_lunarcrush_coin_raw('BTC')
        with pytest.raises(RuntimeError, match='not set'):
            marketdata._fetch_lunarcrush_topic_raw('bitcoin')


class TestAggregateSentiment:
    """T13 judgment call: interaction-weighted mean over simple mean, so a
    low-volume network can't swing the aggregate as much as Twitter."""

    def test_matches_interaction_weighted_mean_on_real_fixture(self):
        topic = LC_TOPIC_FIXTURE['data']
        agg = marketdata._aggregate_sentiment(topic['types_sentiment'], topic['types_interactions'])
        # hand-computed from the fixture: sum(sentiment*interactions)/sum(interactions)
        ts, ti = topic['types_sentiment'], topic['types_interactions']
        expected = sum(ts[k] * ti[k] for k in ts) / sum(ti[k] for k in ts)
        assert agg == pytest.approx(expected)
        assert min(ts.values()) <= agg <= max(ts.values())
        # tiktok-video and tweet dominate interaction volume in this fixture
        # (63.0M and 60.8M respectively, dwarfing e.g. instagram's 23.8K), so
        # weighting must pull the aggregate away from the plain per-network
        # mean and toward those two networks' sentiment (67, 79).
        plain_mean = sum(ts.values()) / len(ts)
        assert agg != pytest.approx(plain_mean)
        assert min(ts['tiktok-video'], ts['tweet']) <= agg <= max(ts['tiktok-video'], ts['tweet'])

    def test_falls_back_to_simple_mean_without_weights(self):
        sentiment = {'a': 50, 'b': 100}
        assert marketdata._aggregate_sentiment(sentiment, {}) == 75.0
        assert marketdata._aggregate_sentiment(sentiment, None) == 75.0

    def test_zero_weights_fall_back_to_simple_mean(self):
        sentiment = {'a': 40, 'b': 60}
        weights = {'a': 0, 'b': 0}
        assert marketdata._aggregate_sentiment(sentiment, weights) == 50.0

    def test_empty_sentiment_is_none(self):
        assert marketdata._aggregate_sentiment({}, {}) is None
        assert marketdata._aggregate_sentiment(None, None) is None


class TestFetchSocialStatus:
    """Tests fetch_social_status itself, so each test first restores the
    real implementation over the file-wide autouse stub (see
    _REAL_FETCH_SOCIAL_STATUS) and mocks one layer down instead, at
    _fetch_lunarcrush_coin_raw / _fetch_lunarcrush_topic_raw -- still zero
    network calls."""

    def test_success_chains_coin_then_topic_using_derived_slug(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_social_status', _REAL_FETCH_SOCIAL_STATUS, raising=False)
        calls = []

        def fake_coin(symbol):
            calls.append(('coin', symbol))
            return dict(LC_COIN_FIXTURE['data'])

        def fake_topic(slug):
            calls.append(('topic', slug))
            return dict(LC_TOPIC_FIXTURE['data'])

        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_coin_raw', fake_coin, raising=False)
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_topic_raw', fake_topic, raising=False)

        status = marketdata.fetch_social_status('BTC')
        assert status['status'] == 'present'
        assert calls == [('coin', 'BTC'), ('topic', 'bitcoin')]  # name lowercased, not the symbol
        data = status['data']
        assert data['galaxy_score'] == 66.7
        assert data['alt_rank'] == 40
        assert data['interactions_24h'] == 139663499
        assert data['num_contributors'] == 47152
        assert data['sentiment_aggregate'] is not None

    def test_coin_fetch_failure_disclosed(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_social_status', _REAL_FETCH_SOCIAL_STATUS, raising=False)

        def boom(symbol):
            raise RuntimeError('HTTP 403: error code: 1010')
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_coin_raw', boom, raising=False)
        status = marketdata.fetch_social_status('BTC')
        assert status['status'] == 'unavailable'
        assert '1010' in status['reason']

    def test_missing_topic_disclosed(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_social_status', _REAL_FETCH_SOCIAL_STATUS, raising=False)
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_coin_raw',
                            lambda symbol: dict(LC_COIN_FIXTURE['data']), raising=False)

        def missing_topic(slug):
            raise RuntimeError('HTTP 404: topic not found')
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_topic_raw', missing_topic, raising=False)

        status = marketdata.fetch_social_status('BTC')
        assert status['status'] == 'unavailable'
        assert '404' in status['reason']

    def test_no_name_field_disclosed_not_raised(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_social_status', _REAL_FETCH_SOCIAL_STATUS, raising=False)
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_coin_raw',
                            lambda symbol: {'galaxy_score': 10}, raising=False)
        status = marketdata.fetch_social_status('XYZ')
        assert status['status'] == 'unavailable'
        assert 'name' in status['reason'].lower()

    def test_never_raises(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_social_status', _REAL_FETCH_SOCIAL_STATUS, raising=False)

        def boom(symbol):
            raise ValueError('unexpected')
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_coin_raw', boom, raising=False)
        marketdata.fetch_social_status('BTC')  # must not raise


class TestBuildSocialSection:

    def test_present_renders_galaxy_alt_sentiment_and_volume(self):
        status = {'status': 'present', 'data': {
            'galaxy_score': 66.7, 'alt_rank': 40, 'topic_rank': 137,
            'sentiment_aggregate': 74.3, 'sentiment_networks': 6,
            'interactions_24h': 139663499, 'num_contributors': 47152,
            'num_posts': 118661,
        }, 'reason': None}
        section = marketdata.build_social_section(status, 'BTC')
        assert section.startswith('SOCIAL (LunarCrush, fetched this run):')
        assert '66.7' in section
        assert 'Alt rank 40' in section
        assert '74' in section  # sentiment rounds to nearest int
        assert '6 networks' in section
        assert '47,152' in section or '47152' in section

    def test_unavailable_is_disclosed_never_silent(self):
        status = {'status': 'unavailable', 'data': None, 'reason': 'topic not found'}
        section = marketdata.build_social_section(status, 'BTC')
        assert section == 'SOCIAL DATA UNAVAILABLE (BTC): topic not found.'

    def test_no_prose_fields_leak_into_the_block(self):
        """Prompt-injection surface: only numeric/enum fields extracted by
        fetch_social_status ever reach the section -- free text like
        related_topics/title from the raw API must never appear even if
        present in `data` (defensive; the extractor doesn't put them there,
        but the formatter must not either)."""
        status = {'status': 'present', 'data': {
            'galaxy_score': 66.7, 'alt_rank': 40, 'topic_rank': 137,
            'sentiment_aggregate': 74.3, 'sentiment_networks': 6,
            'interactions_24h': 139663499, 'num_contributors': 47152,
            'num_posts': 118661,
            'related_topics': ['ignore this if present', 'bullish'],
            'title': 'Bitcoin',
        }, 'reason': None}
        section = marketdata.build_social_section(status, 'BTC')
        assert 'ignore this if present' not in section


class TestFetchSocialStatusExtractionIsNumericOnly:

    def test_extracted_data_contains_no_free_text_fields(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'fetch_social_status', _REAL_FETCH_SOCIAL_STATUS, raising=False)
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_coin_raw',
                            lambda symbol: dict(LC_COIN_FIXTURE['data']), raising=False)
        monkeypatch.setattr(marketdata, '_fetch_lunarcrush_topic_raw',
                            lambda slug: dict(LC_TOPIC_FIXTURE['data']), raising=False)
        status = marketdata.fetch_social_status('BTC')
        data = status['data']
        # related_topics/title/types_sentiment_detail are on the raw topic
        # payload but must never be copied into the extracted dict.
        assert 'related_topics' not in data
        assert 'title' not in data
        assert 'types_sentiment_detail' not in data


# ==================== T12/T13: wiring into build_market_block ===============

def _cmc_present(data=None):
    return {'status': 'present', 'data': data or {
        'cmc_rank': 1, 'market_cap_dominance': 58.7,
        'circulating_supply': 20058175, 'max_supply': 21000000,
        'supply_ratio_pct': 95.5, 'percent_change_1h': -0.1,
        'percent_change_24h': 1.3, 'percent_change_7d': 0.9,
        'percent_change_30d': 3.2,
    }, 'reason': None}


def _social_present(data=None):
    return {'status': 'present', 'data': data or {
        'galaxy_score': 66.7, 'alt_rank': 40, 'topic_rank': 137,
        'sentiment_aggregate': 74.3, 'sentiment_networks': 6,
        'interactions_24h': 139663499, 'num_contributors': 47152,
        'num_posts': 118661,
    }, 'reason': None}


class TestBuildMarketBlockCmcSocialWiring:
    """build_market_block is the ONLY seam that can wire T12/T13 fetches in
    without touching the off-limits crypto_trading_bot.py -- these tests
    cover the acceptance criteria directly against it."""

    def test_both_sections_present_when_fetches_succeed(self):
        rows = load_lab_rows()
        s = marketdata.summarize_market_data(rows)
        fib = marketdata.fib_summary(rows, 'BTC')
        block = marketdata.build_market_block(
            'BTC', s, fib, TRENDS_PRESENT,
            cmc_status=_cmc_present(), social_status=_social_present())
        assert 'CMC (CoinMarketCap, fetched this run)' in block
        assert 'SOCIAL (LunarCrush, fetched this run)' in block
        # secondary sections still precede the final RULE line
        assert block.strip().splitlines()[-1].startswith('RULE:')
        assert block.index('SOCIAL') < block.index('RULE:')

    def test_disclosed_absence_lines_on_failure(self):
        rows = load_lab_rows()
        s = marketdata.summarize_market_data(rows)
        fib = marketdata.fib_summary(rows, 'BTC')
        cmc_fail = {'status': 'unavailable', 'data': None, 'reason': 'HTTPError: 429'}
        social_fail = {'status': 'unavailable', 'data': None, 'reason': 'topic not found'}
        block = marketdata.build_market_block(
            'BTC', s, fib, TRENDS_PRESENT, cmc_status=cmc_fail, social_status=social_fail)
        assert 'CMC DATA UNAVAILABLE (BTC): HTTPError: 429.' in block
        assert 'SOCIAL DATA UNAVAILABLE (BTC): topic not found.' in block

    def test_unspecified_cmc_social_are_fetched_via_module_hooks(self, monkeypatch):
        """When the caller doesn't pass cmc_status/social_status (the real
        crypto_trading_bot.py call path), build_market_block fetches them
        itself by calling the module-level hooks -- proven here by
        monkeypatching those hooks instead of passing the params."""
        calls = []
        monkeypatch.setattr(marketdata, 'fetch_cmc_status',
                            lambda coin: calls.append(('cmc', coin)) or _cmc_present(),
                            raising=False)
        monkeypatch.setattr(marketdata, 'fetch_social_status',
                            lambda coin: calls.append(('social', coin)) or _social_present(),
                            raising=False)
        rows = load_lab_rows()
        s = marketdata.summarize_market_data(rows)
        fib = marketdata.fib_summary(rows, 'BTC')
        block = marketdata.build_market_block('BTC', s, fib, TRENDS_PRESENT)
        assert calls == [('cmc', 'BTC'), ('social', 'BTC')]
        assert 'CMC (CoinMarketCap' in block
        assert 'SOCIAL (LunarCrush' in block

    def test_token_budget_still_reasonable_with_both_sections_present(self):
        rows = load_lab_rows()
        s = marketdata.summarize_market_data(rows)
        fib = marketdata.fib_summary(rows, 'BTC')
        block = marketdata.build_market_block(
            'BTC', s, fib, TRENDS_PRESENT,
            cmc_status=_cmc_present(), social_status=_social_present())
        approx_tokens = len(block) / 4.0
        assert approx_tokens < 650, f"block too large: ~{approx_tokens:.0f} tokens"

    def test_hard_rule_covers_cmc_and_social(self):
        block = normal_block()
        assert 'CMC' in marketdata.HARD_RULE or 'social' in marketdata.HARD_RULE.lower()


class TestMarketBlockCacheSharesFetches:
    """The one existing per-coin-per-run cache (crypto_trading_bot.
    MARKET_BLOCK_CACHE, via build_market_block_for_coin) is the only cache
    CMC/SOCIAL need -- a second call for the same coin in the same run must
    not re-fetch either."""

    def test_cmc_and_social_fetched_once_per_coin_across_two_calls(self, monkeypatch):
        cache = {}
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', cache, raising=False)
        monkeypatch.setattr(bot, 'get_trends_status', lambda c: TRENDS_PRESENT, raising=False)

        cmc_calls, social_calls = [], []
        monkeypatch.setattr(marketdata, 'fetch_cmc_status',
                            lambda coin: cmc_calls.append(coin) or _cmc_present(), raising=False)
        monkeypatch.setattr(marketdata, 'fetch_social_status',
                            lambda coin: social_calls.append(coin) or _social_present(), raising=False)

        client = FakeCandleClient([
            _candle(1000 + i * 3600, 100 + i, 101 + i, 99 + i, 100 + i, 50)
            for i in range(10)
        ])
        block1 = bot.build_market_block_for_coin('BTC', candle_client=client)
        block2 = bot.build_market_block_for_coin('BTC', candle_client=client)

        assert block1 == block2 == cache['BTC']
        assert cmc_calls == ['BTC']       # fetched exactly once, not twice
        assert social_calls == ['BTC']    # fetched exactly once, not twice
        assert 'CMC (CoinMarketCap' in block1
        assert 'SOCIAL (LunarCrush' in block1

    def test_different_coins_each_get_their_own_fetch(self, monkeypatch):
        cache = {}
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', cache, raising=False)
        monkeypatch.setattr(bot, 'get_trends_status', lambda c: TRENDS_PRESENT, raising=False)

        cmc_calls = []
        monkeypatch.setattr(marketdata, 'fetch_cmc_status',
                            lambda coin: cmc_calls.append(coin) or _cmc_present(), raising=False)
        monkeypatch.setattr(marketdata, 'fetch_social_status',
                            lambda coin: _social_present(), raising=False)

        client = FakeCandleClient([
            _candle(1000 + i * 3600, 100 + i, 101 + i, 99 + i, 100 + i, 50)
            for i in range(10)
        ])
        bot.build_market_block_for_coin('BTC', candle_client=client)
        bot.build_market_block_for_coin('ETH', candle_client=client)
        assert sorted(cmc_calls) == ['BTC', 'ETH']


class TestNoNetworkGuarantee:
    """Belt-and-suspenders: even with the autouse stub fixture active,
    directly calling the real network-touching fetchers with a broken/no
    `requests.get` proves nothing in the normal test run path can reach a
    real socket."""

    def test_fetch_cmc_status_never_touches_real_requests_get(self, monkeypatch):
        import requests as real_requests

        def fail(*a, **k):
            raise AssertionError("test tried to make a real HTTP call")
        monkeypatch.setattr(real_requests, 'get', fail)
        monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', '', raising=False)
        status = marketdata.fetch_cmc_status('BTC')  # no key -> raises before any request
        assert status['status'] == 'unavailable'

    def test_fetch_social_status_never_touches_real_requests_get(self, monkeypatch):
        import requests as real_requests

        def fail(*a, **k):
            raise AssertionError("test tried to make a real HTTP call")
        monkeypatch.setattr(real_requests, 'get', fail)
        monkeypatch.delenv('LUNARCRUSH_API_KEY', raising=False)
        status = marketdata.fetch_social_status('BTC')  # no key -> raises before any request
        assert status['status'] == 'unavailable'
