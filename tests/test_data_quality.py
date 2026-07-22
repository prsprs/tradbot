"""WS-4 (improvement cycle 2): structured per-source data_quality.

In a recent live session Google Trends and LunarCrush 429'd; the bot degraded
gracefully but the run summary and records carried NO trace of which sources
were missing, so different runs reasoned from different evidence subsets
invisibly. This adds a per-coin

    data_quality = {source: {"status": ok|degraded|failed|skipped,
                             "detail": str}}

derived at market-block assembly time from the SAME branch variables that
decide what actually reaches the prompt (EFFECT HONESTY: a source that failed
and was omitted from the block is "failed"; a source disabled by config is
"skipped"; partial data is "degraded"), and threads it into:

  (1) crypto_trading_bot.build_run_summary (per coin -> --json-summary), and
  (2) the recommendation record as a NEW OPTIONAL field via historyutil
      (mirrors prompt_hash / market_block_ref: omitted => record bytes
      identical to a v1 record).

Conventions mirror tests/test_market_data.py (autouse CMC/SOCIAL fetch stubs,
FakeCandleClient, no network / no LLM / no orders) and tests/test_schema_v2.py
(byte-identity pin for the new optional record field).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import historyutil
import marketdata


# ---------------------------------------------------------------------------
# Fakes / fixtures (mirroring tests/test_market_data.py)
# ---------------------------------------------------------------------------

def _candle(t, o, h, l, c, v):
    return {'start': str(t), 'open': str(o), 'high': str(h),
            'low': str(l), 'close': str(c), 'volume': str(v)}


class FakeCandleClient:
    def __init__(self, candles):
        self._candles = candles

    def get_candles(self, **kwargs):
        return {'candles': self._candles}


def _good_candles(n=10):
    return [_candle(1000 + i * 3600, 100 + i, 101 + i, 99 + i, 100 + i, 50)
            for i in range(n)]


CMC_PRESENT = {'status': 'present', 'reason': None, 'data': {
    'cmc_rank': 1, 'market_cap_dominance': 52.0, 'circulating_supply': 19_000_000,
    'max_supply': 21_000_000, 'supply_ratio_pct': 90.4,
    'percent_change_1h': 0.1, 'percent_change_24h': 1.2,
    'percent_change_7d': 3.4, 'percent_change_30d': 5.6, 'id_resolved': True}}
CMC_SYMBOL_ONLY = {'status': 'present', 'reason': None,
                   'data': dict(CMC_PRESENT['data'], id_resolved=False)}
CMC_FAIL = {'status': 'unavailable', 'data': None,
            'reason': 'HTTPError: 429 Too Many Requests'}
SOCIAL_PRESENT = {'status': 'present', 'reason': None, 'data': {
    'galaxy_score': 70, 'alt_rank': 3, 'sentiment_aggregate': 66.0,
    'sentiment_networks': 4, 'interactions_24h': 1_000_000,
    'num_contributors': 5000, 'num_posts': 20000}}
SOCIAL_FAIL = {'status': 'unavailable', 'data': None,
               'reason': 'HTTPError: 429 Too Many Requests'}
TRENDS_PRESENT = {'status': 'present', 'data': 'Google Trends: avg 42, max 100'}
TRENDS_BELOW = {'status': 'below_floor', 'data': None}
TRENDS_FAILED = {'status': 'failed', 'data': None}
TRENDS_NONE = {'status': 'unavailable', 'data': None}


@pytest.fixture
def keys_present(monkeypatch):
    """Both secondary-source API keys configured (so an 'unavailable' status
    is a real failure, not a config skip)."""
    monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', 'k', raising=False)
    monkeypatch.setenv('LUNARCRUSH_API_KEY', 'k')


@pytest.fixture
def keys_absent(monkeypatch):
    monkeypatch.setattr(marketdata.coinmarketcaputil, 'CMC_API_KEY', '', raising=False)
    monkeypatch.delenv('LUNARCRUSH_API_KEY', raising=False)


def _summary():
    return marketdata.summarize_market_data(
        marketdata.fetch_candles(FakeCandleClient(_good_candles()), 'BTC-USD'))


# ===========================================================================
# 1. derive_data_quality: the ok/degraded/failed/skipped mapping per source
# ===========================================================================

def test_all_sources_ok(keys_present):
    s = _summary()
    fib = {'trend_direction': 'up'}
    dq = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=s, fib=fib, market_data_reason=None,
        trends_status=TRENDS_PRESENT, cmc_status=CMC_PRESENT, social_status=SOCIAL_PRESENT)
    assert set(dq) == {'coinbase', 'fibonacci', 'google_trends', 'cmc', 'social'}
    assert {k: v['status'] for k, v in dq.items()} == {
        'coinbase': 'ok', 'fibonacci': 'ok', 'google_trends': 'ok',
        'cmc': 'ok', 'social': 'ok'}
    # every entry carries a non-empty string detail
    assert all(isinstance(v['detail'], str) and v['detail'] for v in dq.values())


def test_coinbase_failed_vs_skipped(keys_present):
    # candle client present but no series reached the block -> FAILED
    failed = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=None, fib=None,
        market_data_reason='no candles returned for BTC-USD',
        trends_status=TRENDS_PRESENT, cmc_status=CMC_PRESENT, social_status=SOCIAL_PRESENT)
    assert failed['coinbase']['status'] == 'failed'
    assert 'no candles' in failed['coinbase']['detail']

    # DEX mode: no candle client by config -> SKIPPED (not failed)
    skipped = bot.derive_data_quality(
        'BTC', candle_client=None, summary=None, fib=None,
        market_data_reason='no Coinbase candle client available (DEX mode)',
        trends_status=TRENDS_PRESENT, cmc_status=CMC_PRESENT, social_status=SOCIAL_PRESENT)
    assert skipped['coinbase']['status'] == 'skipped'


def test_fibonacci_degraded_and_skipped(keys_present):
    s = _summary()
    # market data present but fib failed to compute -> DEGRADED (not failed)
    degraded = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=s, fib=None, market_data_reason=None,
        trends_status=TRENDS_PRESENT, cmc_status=CMC_PRESENT, social_status=SOCIAL_PRESENT)
    assert degraded['fibonacci']['status'] == 'degraded'
    # no market data at all -> fib never attempted -> SKIPPED
    skipped = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=None, fib=None,
        market_data_reason='boom', trends_status=TRENDS_PRESENT,
        cmc_status=CMC_PRESENT, social_status=SOCIAL_PRESENT)
    assert skipped['fibonacci']['status'] == 'skipped'


@pytest.mark.parametrize('trends_status,expected', [
    (TRENDS_PRESENT, 'ok'),
    (TRENDS_BELOW, 'degraded'),
    (TRENDS_FAILED, 'failed'),
    (TRENDS_NONE, 'failed'),
])
def test_google_trends_mapping(keys_present, trends_status, expected):
    s = _summary()
    dq = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=s, fib={'trend_direction': 'up'},
        market_data_reason=None, trends_status=trends_status,
        cmc_status=CMC_PRESENT, social_status=SOCIAL_PRESENT)
    assert dq['google_trends']['status'] == expected


def test_cmc_skipped_when_key_absent(keys_absent):
    s = _summary()
    dq = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=s, fib={'trend_direction': 'up'},
        market_data_reason=None, trends_status=TRENDS_PRESENT,
        cmc_status=CMC_FAIL, social_status=SOCIAL_FAIL)
    # no API key configured -> the source was disabled by config, not an error
    assert dq['cmc']['status'] == 'skipped'
    assert dq['social']['status'] == 'skipped'


def test_cmc_failed_when_key_present(keys_present):
    s = _summary()
    dq = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=s, fib={'trend_direction': 'up'},
        market_data_reason=None, trends_status=TRENDS_PRESENT,
        cmc_status=CMC_FAIL, social_status=SOCIAL_FAIL)
    # key configured but the fetch failed (429) -> FAILED, reason carried
    assert dq['cmc']['status'] == 'failed'
    assert '429' in dq['cmc']['detail']
    assert dq['social']['status'] == 'failed'


def test_cmc_degraded_on_symbol_only_ambiguity(keys_present):
    s = _summary()
    dq = bot.derive_data_quality(
        'BTC', candle_client=object(), summary=s, fib={'trend_direction': 'up'},
        market_data_reason=None, trends_status=TRENDS_PRESENT,
        cmc_status=CMC_SYMBOL_ONLY, social_status=SOCIAL_PRESENT)
    # present, but symbol-only lookup can be a wrong-asset -> DEGRADED not ok
    assert dq['cmc']['status'] == 'degraded'


# ===========================================================================
# 2. Injected fetch failures propagate into the cache + run summary (E2E)
# ===========================================================================

def test_build_market_block_for_coin_caches_data_quality(monkeypatch, keys_present):
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
    monkeypatch.setattr(bot, 'DATA_QUALITY_CACHE', {}, raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_FETCHED_AT', {}, raising=False)
    monkeypatch.setattr(bot, 'get_trends_status', lambda c: TRENDS_FAILED, raising=False)
    monkeypatch.setattr(marketdata, 'fetch_cmc_status', lambda c: CMC_PRESENT, raising=False)
    monkeypatch.setattr(marketdata, 'fetch_social_status', lambda c: SOCIAL_FAIL, raising=False)

    bot.build_market_block_for_coin('BTC', candle_client=FakeCandleClient(_good_candles()))
    dq = bot.DATA_QUALITY_CACHE['BTC']
    assert dq['coinbase']['status'] == 'ok'
    assert dq['google_trends']['status'] == 'failed'   # injected 429
    assert dq['cmc']['status'] == 'ok'
    assert dq['social']['status'] == 'failed'           # injected 429


def test_market_data_failure_marks_coinbase_failed(monkeypatch, keys_present):
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
    monkeypatch.setattr(bot, 'DATA_QUALITY_CACHE', {}, raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_FETCHED_AT', {}, raising=False)
    monkeypatch.setattr(bot, 'get_trends_status', lambda c: TRENDS_PRESENT, raising=False)
    monkeypatch.setattr(marketdata, 'fetch_cmc_status', lambda c: CMC_PRESENT, raising=False)
    monkeypatch.setattr(marketdata, 'fetch_social_status', lambda c: SOCIAL_PRESENT, raising=False)

    class Boom:
        def get_candles(self, **kwargs):
            raise RuntimeError('coinbase down')

    bot.build_market_block_for_coin('BTC', candle_client=Boom())
    dq = bot.DATA_QUALITY_CACHE['BTC']
    assert dq['coinbase']['status'] == 'failed'
    assert dq['fibonacci']['status'] == 'skipped'


# ===========================================================================
# 3. build_run_summary threads per-coin data_quality (--json-summary shape)
# ===========================================================================

def _build_summary(**overrides):
    kwargs = dict(
        run_id='run_x', trading_mode='whatif', llm_mode='compare',
        primary_llm='gemini', compare_llms=['gemini', 'claude'],
        use_coin_discovery=False, discovery_methods=['llm'],
        analyze_coins=['BTC', 'ETH'], coins_to_buy=['BTC'], coins_excluded=[],
        coin_vote_outcomes=[('BTC', 'BUY->ordered'), ('ETH', 'HOLD')],
        spend_tracker=bot.SpendTracker(10.0, 5.0), daily_spend_cap_usd=15.0,
        daily_cap_blocked=0, whatif_mode=True, whatif_buys=1,
    )
    kwargs.update(overrides)
    return bot.build_run_summary(**kwargs)


def test_run_summary_includes_per_coin_data_quality():
    dq = {'BTC': {'coinbase': {'status': 'ok', 'detail': '10 candles'},
                  'google_trends': {'status': 'failed', 'detail': '429'}}}
    summary = _build_summary(data_quality_by_coin=dq)
    coins = {c['coin']: c for c in summary['coins']}
    assert coins['BTC']['data_quality'] == dq['BTC']
    # ETH had no cached data_quality -> key omitted, never a fabricated blank
    assert 'data_quality' not in coins['ETH']


def test_run_summary_omits_data_quality_when_not_supplied():
    """Backward-compat: without data_quality_by_coin the coin entries are the
    pre-WS4 shape exactly (guards the existing test_run_summary expectations)."""
    summary = _build_summary()
    for c in summary['coins']:
        assert set(c) == {'coin', 'outcome', 'bought', 'excluded'}


# ===========================================================================
# 4. Record field: present iff supplied; byte-identity pin when omitted
# ===========================================================================

_BASE = dict(
    coin_symbol='ETH', recommendation='BUY', price=1900.0,
    bid_price=1899.0, ask_price=1901.0, llm_source='gemini,claude',
    mode='compare',
)

_DQ = {'coinbase': {'status': 'ok', 'detail': '168 candles / 7.0d'},
       'social': {'status': 'failed', 'detail': 'HTTPError: 429'}}


def test_record_writes_data_quality_when_supplied():
    rec = historyutil.create_recommendation_record(data_quality=_DQ, **_BASE)
    assert rec['data_quality'] == _DQ
    # stored as an independent copy, not the caller's object
    assert rec['data_quality'] is not _DQ


def test_record_byte_identical_when_data_quality_omitted():
    with_omitted = historyutil.create_recommendation_record(trading_mode='whatif', **_BASE)
    assert 'data_quality' not in with_omitted


def test_record_data_quality_none_is_omitted():
    rec = historyutil.create_recommendation_record(
        trading_mode='whatif', data_quality=None, **_BASE)
    assert 'data_quality' not in rec


# ===========================================================================
# 5. _record_provenance carries data_quality from the cache (both loops use it)
# ===========================================================================

def test_record_provenance_includes_data_quality(monkeypatch):
    monkeypatch.setattr(bot, 'RUN_ID', 'run_prov', raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {'ETH': 'block'}, raising=False)
    monkeypatch.setattr(bot, 'DATA_QUALITY_CACHE', {'ETH': _DQ}, raising=False)
    dec = bot.PanelDecision(action='BUY', consensus_state='unanimous',
                            vote_details={'gemini': {'action': 'BUY', 'confidence': 0.9}})
    prov = bot._record_provenance('ETH', dec)
    assert prov['data_quality'] == _DQ


def test_record_provenance_data_quality_none_for_uncached_coin(monkeypatch):
    monkeypatch.setattr(bot, 'RUN_ID', 'run_prov', raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
    monkeypatch.setattr(bot, 'DATA_QUALITY_CACHE', {}, raising=False)
    dec = bot.PanelDecision(action='BUY', consensus_state='unanimous',
                            vote_details={'gemini': {'action': 'BUY', 'confidence': 0.9}})
    prov = bot._record_provenance('ETH', dec)
    assert prov['data_quality'] is None
