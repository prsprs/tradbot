"""F7a: MARKET_BLOCK_CACHE TTL.

From the T9 implementer's reflection (docs/reflections-2026-07-18/reflection-T9.md
section 3, "Design doubts"): MARKET_BLOCK_CACHE is a module-level dict keyed
only by coin symbol, with no expiry. That's correct for a normal single-pass
run (whatif or live, coin-choice or discovery loop) -- each coin is fetched
exactly once per process. But because the cache is a module global, it
outlives any single loop iteration; if the bot were ever driven from an
in-process loop instead of one-process-per-run, every later iteration would
silently keep returning the FIRST iteration's market data forever, with no
signal that the price/fib/trends data feeding every panelist's prompt had
gone stale.

crypto_trading_bot.build_market_block_for_coin now tracks a per-coin fetch
timestamp in MARKET_BLOCK_FETCHED_AT and treats an entry older than
MARKET_BLOCK_TTL_SECONDS (module constant, env-overridable, default 900s /
15 min) as a cache miss. This file pins:
  1. within-TTL calls still share one fetch (the existing one-fetch-per-
     coin-per-run behavior for normal runs must not regress);
  2. past-TTL calls refetch and the cache is refreshed with new content and
     a new timestamp;
  3. a cached entry with no recorded timestamp (e.g. injected directly, as
     tests/test_market_data.py's tests do) is treated as stale rather than
     trusted indefinitely;
  4. the TTL default is sensible and the override wiring exists (the
     constant is read once at module import time, so this is checked
     without a subprocess re-import -- see TestEnvOverride's docstring for
     why that approach was tried and abandoned).

No network: candle_client=None (the DEX-mode / "MARKET DATA UNAVAILABLE"
degrade path, same one tests/test_market_data.py's
test_dex_mode_no_client_discloses_unavailable uses) is used throughout, so
these tests exercise only the cache/TTL bookkeeping in
build_market_block_for_coin, not real candle fetch/summarize/fib logic
(already covered elsewhere). get_trends_status is replaced with a
call-counting fake so "was this a cache hit or a refetch" can be observed
directly instead of inferred from block content.

A near-miss while writing this file: marketdata.build_market_block
self-fetches CMC (T12) and SOCIAL (T13) data by calling
marketdata.fetch_cmc_status/fetch_social_status internally whenever they
aren't passed in -- exactly the behavior tests/test_market_data.py's own
docstring warns about and stubs against with an autouse fixture. An early
version of this file didn't carry that stub, so every
build_market_block_for_coin() call here made a REAL self-fetch attempt;
tests/conftest.py's network guard (F5) blocked the sockets, but
coinmarketcaputil.py/lunarcrushutil.py's retry/backoff around that (using
the real `time` module, not the `bot.time` this file patches) turned each
call into several real seconds of retries instead of a hang -- slow enough
to look identical to a hang from the outside. The autouse fixture below
mirrors test_market_data.py's `_stub_cmc_social_fetches` exactly for that
reason.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import marketdata


@pytest.fixture(autouse=True)
def _stub_cmc_social_fetches(monkeypatch):
    """No test in this file may reach CoinMarketCap or LunarCrush over the
    network -- see the module docstring's "near-miss" note. Mirrors
    tests/test_market_data.py's fixture of the same name/purpose."""
    monkeypatch.setattr(marketdata, 'fetch_cmc_status',
                        lambda coin: {'status': 'unavailable', 'data': None,
                                     'reason': 'test stub: not fetched'},
                        raising=False)
    monkeypatch.setattr(marketdata, 'fetch_social_status',
                        lambda coin: {'status': 'unavailable', 'data': None,
                                     'reason': 'test stub: not fetched'},
                        raising=False)


class FakeClock:
    """Controllable stand-in for time.time() -- advances only when told to,
    so TTL boundaries can be tested exactly instead of racing a real clock.

    IMPORTANT: never monkeypatch the real `time` module's `.time` attribute
    (e.g. `monkeypatch.setattr(bot.time, 'time', clock)`) -- `bot.time` IS
    the process-wide `time` module (modules are singletons), so that would
    freeze time.time() for the ENTIRE test process, including pytest's own
    internals. A first version of this file did exactly that and hung
    indefinitely (killed manually). Use `patched_clock()` below instead,
    which rebinds only crypto_trading_bot's own `time` name to a decoy
    object -- every other consumer of the real `time` module is
    unaffected."""

    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def patched_clock(monkeypatch, start=1_000_000.0):
    """Install a FakeClock as crypto_trading_bot's own `time.time`, without
    touching the real `time` module (see FakeClock's docstring)."""
    clock = FakeClock(start=start)
    monkeypatch.setattr(bot, 'time', SimpleNamespace(time=clock), raising=False)
    return clock


def _fresh_state(monkeypatch, ttl=900, trends_status=None):
    """Isolate the cache/TTL globals and stub the trends fetch with a
    call-counting fake. Returns the list `get_trends_status` calls append
    to -- its length is the number of real (non-cached) builds performed."""
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_FETCHED_AT', {}, raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_TTL_SECONDS', ttl, raising=False)
    calls = []

    def fake_trends(coin):
        calls.append(coin)
        return trends_status or {'status': 'unavailable', 'data': None}

    monkeypatch.setattr(bot, 'get_trends_status', fake_trends, raising=False)
    return calls


class TestFreshWithinTTLSharing:

    def test_second_call_within_ttl_is_a_cache_hit(self, monkeypatch):
        calls = _fresh_state(monkeypatch, ttl=900)
        clock = patched_clock(monkeypatch)

        block1 = bot.build_market_block_for_coin('BTC', candle_client=None)
        clock.advance(60)  # 1 minute later -- well within the 15-min TTL
        block2 = bot.build_market_block_for_coin('BTC', candle_client=None)

        assert block1 == block2
        assert calls == ['BTC']  # only one real fetch -- the 2nd call was a hit

    def test_different_coins_are_independent_cache_entries(self, monkeypatch):
        calls = _fresh_state(monkeypatch, ttl=900)
        clock = patched_clock(monkeypatch)

        bot.build_market_block_for_coin('BTC', candle_client=None)
        bot.build_market_block_for_coin('ETH', candle_client=None)
        clock.advance(60)
        bot.build_market_block_for_coin('BTC', candle_client=None)
        bot.build_market_block_for_coin('ETH', candle_client=None)

        assert calls == ['BTC', 'ETH']  # each coin fetched exactly once

    def test_records_fetch_timestamp_on_miss(self, monkeypatch):
        _fresh_state(monkeypatch, ttl=900)
        clock = patched_clock(monkeypatch, start=5000.0)

        bot.build_market_block_for_coin('BTC', candle_client=None)

        assert bot.MARKET_BLOCK_FETCHED_AT['BTC'] == 5000.0


class TestTTLExpiryRefresh:

    def test_call_after_ttl_elapses_refetches(self, monkeypatch):
        calls = _fresh_state(monkeypatch, ttl=900)
        clock = patched_clock(monkeypatch)

        bot.build_market_block_for_coin('BTC', candle_client=None)
        clock.advance(901)  # just past the TTL
        bot.build_market_block_for_coin('BTC', candle_client=None)

        assert calls == ['BTC', 'BTC']  # refetched, not served stale

    def test_call_just_before_ttl_elapses_is_still_a_hit(self, monkeypatch):
        """Boundary check the other direction -- the TTL window itself must
        not have been narrowed by an off-by-one."""
        calls = _fresh_state(monkeypatch, ttl=900)
        clock = patched_clock(monkeypatch)

        bot.build_market_block_for_coin('BTC', candle_client=None)
        clock.advance(899)
        bot.build_market_block_for_coin('BTC', candle_client=None)

        assert calls == ['BTC']

    def test_expired_entry_updates_the_fetch_timestamp(self, monkeypatch):
        _fresh_state(monkeypatch, ttl=900)
        clock = patched_clock(monkeypatch, start=1000.0)

        bot.build_market_block_for_coin('BTC', candle_client=None)
        clock.advance(1000)  # past TTL
        bot.build_market_block_for_coin('BTC', candle_client=None)

        assert bot.MARKET_BLOCK_FETCHED_AT['BTC'] == 2000.0

    def test_expired_entry_replaces_stale_content(self, monkeypatch):
        """The refetched block reflects the new trends status, not a copy
        of the stale one -- proves this is a real refetch, not just a
        timestamp bump on the same cached string."""
        clock = patched_clock(monkeypatch)
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
        monkeypatch.setattr(bot, 'MARKET_BLOCK_FETCHED_AT', {}, raising=False)
        monkeypatch.setattr(bot, 'MARKET_BLOCK_TTL_SECONDS', 900, raising=False)

        statuses = [{'status': 'unavailable', 'data': None},
                    {'status': 'present', 'data': 'Google Trends data for BTC: avg 77'}]

        def fake_trends(coin):
            return statuses.pop(0)

        monkeypatch.setattr(bot, 'get_trends_status', fake_trends, raising=False)

        block1 = bot.build_market_block_for_coin('BTC', candle_client=None)
        clock.advance(901)
        block2 = bot.build_market_block_for_coin('BTC', candle_client=None)

        assert block1 != block2
        assert 'avg 77' in block2
        assert 'avg 77' not in block1

    def test_missing_timestamp_with_cached_block_is_treated_as_expired(self, monkeypatch):
        """A directly-injected cache entry (as tests/test_market_data.py's
        TestGetLlmResponseReadsCache does, and as any future caller that
        bypasses build_market_block_for_coin might) has no recorded fetch
        time. The safe default is to treat unknown age as stale and
        refetch, not to trust it indefinitely."""
        calls = _fresh_state(monkeypatch, ttl=900)
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {'BTC': 'STALE_INJECTED_BLOCK'},
                            raising=False)
        # MARKET_BLOCK_FETCHED_AT stays empty -- no timestamp recorded for 'BTC'.

        block = bot.build_market_block_for_coin('BTC', candle_client=None)

        assert calls == ['BTC']  # refetched, not blindly trusted
        assert block != 'STALE_INJECTED_BLOCK'
        assert 'BTC' in bot.MARKET_BLOCK_FETCHED_AT  # now has a real timestamp


class TestEnvOverride:
    """MARKET_BLOCK_TTL_SECONDS is read once at import time
    (os.environ.get('MARKET_BLOCK_TTL_SECONDS', 900) coerced through int()).

    A first attempt at this test spawned a subprocess to get a clean
    re-import with a different env var value; it hung indefinitely (killed
    manually) and was replaced with the two checks below. In hindsight the
    hang was very likely caused by an earlier version of the TTL tests
    above monkeypatching the REAL `time` module's `.time` attribute
    (`monkeypatch.setattr(bot.time, 'time', clock)` instead of the
    `patched_clock()` helper's `monkeypatch.setattr(bot, 'time', ...)`) --
    see FakeClock's docstring -- which froze wall-clock time for pytest's
    own internals process-wide and ran before this class in file order, not
    something specific to subprocess.run itself. Left un-reintroduced
    anyway: the checks below verify the same contract (sensible default +
    override wiring exists) without spawning a process or touching the
    network."""

    def test_default_is_a_sensible_10_to_15_minute_window(self):
        # Only meaningful when MARKET_BLOCK_TTL_SECONDS isn't already set in
        # the environment this test process happened to import under --
        # true today (a brand-new var; nothing in the repo sets it yet).
        assert 600 <= bot.MARKET_BLOCK_TTL_SECONDS <= 900

    def test_source_reads_env_override_with_int_coercion(self):
        src = (Path(__file__).parent.parent / 'crypto_trading_bot.py').read_text()
        assert "os.environ.get('MARKET_BLOCK_TTL_SECONDS'" in src
        assert "int(os.environ.get('MARKET_BLOCK_TTL_SECONDS'" in src
