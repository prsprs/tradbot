"""WS5 (improvement cycle 2): bid/ask/spread capture + sampling metadata.

Covers:
  A. _honest_bid_ask / _spread_pct / _bid_ask_spread_kwargs: a stubbed Coinbase
     get_best_bid_ask payload yields real bid/ask/spread; missing fields / no
     client / errors yield None with NO exception (never blocks the decision).
  B. record_recommendation stores caller-supplied honest bid/ask/spread,
     overriding the product-attribute fallback; honest values, never fabricated.
  C. sampling policy: flag OFF => every provider records 'provider-default' and
     sends NO sampling kwargs (byte-identical requests); flag ON => temperature
     (+ seed for gemini) only for supporting providers, and the recorded value
     equals what was sent (honesty over invention).

All offline/mocked -- no network, no live trading, no real history writes.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import historyutil
import sampling
from claudeutil import ClaudeTrader
from openaiutil import OpenAITrader
from perplexityutil import PerplexityTrader
from grokutil import GrokTrader


# ===========================================================================
# A. bid/ask/spread extraction from a stubbed Coinbase get_best_bid_ask payload
# ===========================================================================

def _bidask_client(bid=None, ask=None, pricebooks=None):
    """A fake Coinbase client exposing get_best_bid_ask -> pricebooks shape."""
    if pricebooks is None:
        bids = [SimpleNamespace(price=bid)] if bid is not None else []
        asks = [SimpleNamespace(price=ask)] if ask is not None else []
        pricebooks = [SimpleNamespace(bids=bids, asks=asks)]

    def get_best_bid_ask(product_ids=None):
        return SimpleNamespace(pricebooks=pricebooks)

    return SimpleNamespace(get_best_bid_ask=get_best_bid_ask)


def _set_trader(monkeypatch, client):
    monkeypatch.setattr(bot, 'trader', SimpleNamespace(client=client),
                        raising=False)


def test_honest_bid_ask_reads_real_prices(monkeypatch):
    _set_trader(monkeypatch, _bidask_client(bid='100.0', ask='100.50'))
    bid, ask = bot._honest_bid_ask('BTC')
    assert bid == 100.0
    assert ask == 100.5


def test_spread_pct_derivation():
    # mid = 100.25; spread = 0.5 / 100.25 * 100
    assert bot._spread_pct(100.0, 100.5) == pytest.approx(0.5 / 100.25 * 100)
    assert bot._spread_pct(None, 100.5) is None
    assert bot._spread_pct(100.0, None) is None
    assert bot._spread_pct(0.0, 100.5) is None  # non-positive => None
    assert bot._spread_pct(-1.0, 100.5) is None


def test_bid_ask_spread_kwargs_full(monkeypatch):
    _set_trader(monkeypatch, _bidask_client(bid='100.0', ask='100.50'))
    kw = bot._bid_ask_spread_kwargs('BTC')
    assert kw['bid_price'] == 100.0
    assert kw['ask_price'] == 100.5
    assert kw['spread_pct'] == pytest.approx(0.5 / 100.25 * 100)


def test_missing_ask_yields_none_no_spread(monkeypatch):
    _set_trader(monkeypatch, _bidask_client(bid='100.0', ask=None))
    kw = bot._bid_ask_spread_kwargs('BTC')
    assert kw['bid_price'] == 100.0
    assert kw['ask_price'] is None
    assert kw['spread_pct'] is None  # never fabricated from one side


def test_empty_pricebooks_yields_all_none(monkeypatch):
    _set_trader(monkeypatch, _bidask_client(pricebooks=[]))
    kw = bot._bid_ask_spread_kwargs('BTC')
    assert kw == {'bid_price': None, 'ask_price': None, 'spread_pct': None}


def test_no_client_yields_all_none(monkeypatch):
    # DEX mode / a trader whose client lacks get_best_bid_ask.
    monkeypatch.setattr(bot, 'trader', SimpleNamespace(client=None),
                        raising=False)
    assert bot._bid_ask_spread_kwargs('BTC') == {
        'bid_price': None, 'ask_price': None, 'spread_pct': None}


def test_fetch_exception_is_swallowed(monkeypatch, capsys):
    def boom(product_ids=None):
        raise RuntimeError("network down")
    _set_trader(monkeypatch, SimpleNamespace(get_best_bid_ask=boom))
    kw = bot._bid_ask_spread_kwargs('BTC')  # must NOT raise
    assert kw == {'bid_price': None, 'ask_price': None, 'spread_pct': None}
    assert 'best_bid_ask fetch failed' in capsys.readouterr().out


def test_malformed_price_string_is_none(monkeypatch):
    _set_trader(monkeypatch, _bidask_client(bid='not-a-number', ask='100.5'))
    kw = bot._bid_ask_spread_kwargs('BTC')
    assert kw['bid_price'] is None
    assert kw['ask_price'] == 100.5
    assert kw['spread_pct'] is None


# ===========================================================================
# B. record_recommendation stores caller-supplied honest bid/ask/spread
# ===========================================================================

class _FakeProduct:
    price = '1900.0'
    # NOTE: a real Coinbase product exposes NO bid/ask -- these are absent, so
    # the record's honest bid/ask can only come from the caller (WS5).


class _FakeTrader:
    def get_product_details(self, symbol):
        return _FakeProduct()


def test_record_recommendation_uses_caller_bid_ask_spread(monkeypatch):
    saved = {}
    monkeypatch.setattr(historyutil, 'save_recommendation',
                        lambda rec: saved.update(rec))
    result = historyutil.record_recommendation(
        coin_symbol='ETH', recommendation='HOLD', trader=_FakeTrader(),
        llm_source='gemini', mode='compare', trading_mode='whatif',
        bid_price=100.0, ask_price=100.5, spread_pct=0.499,
    )
    assert result['price_at_recommendation'] == 1900.0  # price still fetched
    assert result['bid_price'] == 100.0
    assert result['ask_price'] == 100.5
    assert result['spread_pct'] == 0.499
    assert saved['bid_price'] == 100.0


def test_record_recommendation_bid_ask_omitted_when_none(monkeypatch):
    """A product exposing no bid/ask and a caller passing none => bid/ask None,
    spread_pct absent (byte-identical to the prior shape)."""
    monkeypatch.setattr(historyutil, 'save_recommendation', lambda rec: None)
    result = historyutil.record_recommendation(
        coin_symbol='ETH', recommendation='HOLD', trader=_FakeTrader(),
        llm_source='gemini', mode='compare', trading_mode='whatif',
    )
    assert result['bid_price'] is None
    assert result['ask_price'] is None
    assert 'spread_pct' not in result


# ===========================================================================
# C. sampling policy: default byte-identity + flag-on knobs per provider
# ===========================================================================

def test_sampling_record_provider_default_when_flag_off():
    for p in ('gemini', 'claude', 'openai', 'grok', 'perplexity'):
        assert sampling.request_params(p, deterministic=False) == {}
        assert sampling.record(p, deterministic=False) == 'provider-default'


def test_sampling_record_flag_on_per_provider():
    # supporting providers get knobs; unsupported stay provider-default
    assert sampling.record('gemini', True) == {'temperature': 0.0, 'seed': 42}
    assert sampling.record('claude', True) == {'temperature': 0.0}
    assert sampling.record('perplexity', True) == {'temperature': 0.0}
    assert sampling.record('openai', True) == 'provider-default'
    assert sampling.record('grok', True) == 'provider-default'


def test_sampling_is_enabled_parsing():
    assert sampling.is_enabled({'DETERMINISTIC_SAMPLING': 'true'}) is True
    assert sampling.is_enabled({'DETERMINISTIC_SAMPLING': '1'}) is True
    assert sampling.is_enabled({'DETERMINISTIC_SAMPLING': 'on'}) is True
    assert sampling.is_enabled({'DETERMINISTIC_SAMPLING': 'false'}) is False
    assert sampling.is_enabled({}) is False


def test_request_params_returns_fresh_dict():
    a = sampling.request_params('gemini', True)
    a['temperature'] = 99
    assert sampling.request_params('gemini', True)['temperature'] == 0.0


# --- per-provider REQUEST-KWARGS capture (flag off byte-identity; on = knobs) --

class _Capture:
    def __init__(self, response):
        self.kwargs = None
        self._response = response

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self._response


def _openai_response(text='{}'):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text))])


def _claude_response(text='{}'):
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)],
                           stop_reason='end_turn')


def _make(cls, capture, provider, deterministic):
    trader = cls.__new__(cls)
    trader.model = f'{provider}-test'
    trader.coin_type = 'cryptocurrency'
    trader._sampling_params = sampling.request_params(provider, deterministic)
    return trader


def test_openai_request_never_carries_temperature_either_flag():
    # gpt-5.x rejects temperature -> openai must NEVER send it, flag on or off.
    for det in (False, True):
        cap = _Capture(_openai_response())
        t = _make(OpenAITrader, cap, 'openai', det)
        t.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=cap)))
        t.send_coin_check_request('BTC')
        assert 'temperature' not in cap.kwargs
        assert 'seed' not in cap.kwargs


def test_claude_request_temperature_only_when_flag_on():
    # flag off: byte-identical (no temperature)
    cap = _Capture(_claude_response())
    t = _make(ClaudeTrader, cap, 'claude', False)
    t.client = SimpleNamespace(messages=SimpleNamespace(create=cap))
    t.send_coin_check_request('BTC')
    assert 'temperature' not in cap.kwargs

    # flag on: temperature=0 present, no seed (Anthropic has no seed param)
    cap = _Capture(_claude_response())
    t = _make(ClaudeTrader, cap, 'claude', True)
    t.client = SimpleNamespace(messages=SimpleNamespace(create=cap))
    t.send_coin_check_request('BTC')
    assert cap.kwargs['temperature'] == 0.0
    assert 'seed' not in cap.kwargs
    # structured output preserved alongside the knob
    assert 'output_config' in cap.kwargs


def test_perplexity_request_temperature_only_when_flag_on():
    cap = _Capture(_openai_response())
    t = _make(PerplexityTrader, cap, 'perplexity', False)
    t.client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=cap)))
    t.send_coin_check_request('BTC')
    assert 'temperature' not in cap.kwargs

    cap = _Capture(_openai_response())
    t = _make(PerplexityTrader, cap, 'perplexity', True)
    t.client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=cap)))
    t.send_coin_check_request('BTC')
    assert cap.kwargs['temperature'] == 0.0
    assert cap.kwargs['response_format'] is not None  # structured preserved


def test_grok_request_untouched_both_flags():
    # grok is provider-default -> request shape unchanged regardless of flag.
    for det in (False, True):
        cap = _Capture(SimpleNamespace(output_text='{}'))
        t = _make(GrokTrader, cap, 'grok', det)
        t.tools = [{"type": "web_search"}]
        t.client = SimpleNamespace(responses=SimpleNamespace(create=cap))
        t.send_coin_check_request('BTC')
        assert 'temperature' not in cap.kwargs
        assert 'seed' not in cap.kwargs


def test_gemini_structured_config_sampling(monkeypatch):
    # flag off: config carries no temperature/seed
    monkeypatch.setattr(bot, 'DETERMINISTIC_SAMPLING', False, raising=False)
    cfg = bot.gemini_structured_config()
    assert getattr(cfg, 'temperature', None) is None
    assert getattr(cfg, 'seed', None) is None

    # flag on: temperature=0 + seed folded into the config (still structured)
    monkeypatch.setattr(bot, 'DETERMINISTIC_SAMPLING', True, raising=False)
    cfg = bot.gemini_structured_config()
    assert cfg.temperature == 0.0
    assert cfg.seed == 42
    assert cfg.response_schema is not None  # structured output preserved
