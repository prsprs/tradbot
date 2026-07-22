"""WS1: Polymarket filter must apply in HYBRID DISCOVERY mode (santiment in
--discovery), not just the legacy santiment-free filtered-discovery path.

Verified defect (docs/IMPROVEMENT_PLAN_2026-07-20.md, "Confirmed and WORSE"):
the only route to filter_coins_by_polymarket was
get_filtered_coinbase_coins(), invoked solely from the branch gated
`if USE_COIN_FILTERING and USE_COIN_DISCOVERY and not USE_SANTIMENT_DISCOVERY`.
When santiment is in --discovery, main() takes HYBRID DISCOVERY MODE, which
unions run_llm_discovery() + run_santiment_discovery() and analyzes candidates
directly -- the Polymarket filter was never applied to ANY candidate, while
the banner still printed "Polymarket Filter: Enabled".

The fix extracts apply_polymarket_filter_to_candidates(), a pure seam called
by main()'s hybrid branch. No network anywhere: filter_fn is injected, and the
legacy-path test stubs both filter_coins_by_polymarket and cache access. These
tests never invoke bot.main() (the repo's documented no-main() convention --
see tests/test_model_registry.py / tests/test_framing.py).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot


# ---------------------------------------------------------------------------
# 1. Hybrid discovery + polymarket-filter=true -> filter IS applied to the
#    UNION; both llm- and santiment-sourced candidates can be removed, with
#    correct source provenance.
# ---------------------------------------------------------------------------

def test_hybrid_filter_enabled_applies_to_union_both_sources():
    llm_coins = ['BTC', 'PEPE']          # PEPE has no Polymarket market
    santiment_coins = ['SOL', 'FARTCOIN']  # FARTCOIN has no market
    # Union as main() builds it (llm first, then santiment, upper-cased).
    candidates = ['BTC', 'PEPE', 'SOL', 'FARTCOIN']

    # Stub the Polymarket call: keep only BTC and SOL (mirrors
    # filter_coins_by_polymarket's own list-comprehension shape).
    def fake_filter(coins, verbose=True):
        keep = {'BTC', 'SOL'}
        return [c for c in coins if c.upper() in keep]

    kept, removed = bot.apply_polymarket_filter_to_candidates(
        candidates, llm_coins, enabled=True, filter_fn=fake_filter)

    assert kept == ['BTC', 'SOL']           # order preserved
    # An llm coin AND a santiment coin were both removed, each labeled by source.
    assert ('PEPE', 'llm') in removed
    assert ('FARTCOIN', 'santiment') in removed
    assert len(removed) == 2


def test_hybrid_filter_provenance_llm_wins_on_overlap():
    # A coin discovered by BOTH sources is labeled 'llm' (llm unioned first),
    # matching main()'s per-coin discovery_source resolution.
    llm_coins = ['DOGE']
    santiment_coins = ['DOGE']
    candidates = ['DOGE']

    def fake_filter(coins, verbose=True):
        return []  # remove everything

    _, removed = bot.apply_polymarket_filter_to_candidates(
        candidates, llm_coins, enabled=True, filter_fn=fake_filter)
    assert removed == [('DOGE', 'llm')]


# ---------------------------------------------------------------------------
# 2. Hybrid discovery + polymarket-filter=false -> unchanged behavior: the
#    filter is never invoked and the union passes through intact.
# ---------------------------------------------------------------------------

def test_hybrid_filter_disabled_is_noop_passthrough():
    candidates = ['BTC', 'PEPE', 'SOL']
    called = []

    def spy_filter(coins, verbose=True):
        called.append(coins)
        return []

    kept, removed = bot.apply_polymarket_filter_to_candidates(
        candidates, ['BTC', 'PEPE'], enabled=False, filter_fn=spy_filter)

    assert kept == candidates      # unchanged
    assert kept is not candidates  # a copy, safe to reassign
    assert removed == []
    assert called == []            # filter_fn never called when disabled


def test_empty_candidate_set_never_calls_filter():
    called = []

    def spy_filter(coins, verbose=True):
        called.append(coins)
        return []

    kept, removed = bot.apply_polymarket_filter_to_candidates(
        [], [], enabled=True, filter_fn=spy_filter)
    assert kept == []
    assert removed == []
    assert called == []            # no point hitting Polymarket for 0 coins


# ---------------------------------------------------------------------------
# 3. Legacy (non-santiment) filtered-discovery path is UNCHANGED: apply_coin_
#    filters still routes through filter_coins_by_polymarket when
#    POLYMARKET_FILTER is set. (The WS1 change did not touch this function.)
# ---------------------------------------------------------------------------

def test_legacy_apply_coin_filters_still_filters_by_polymarket(monkeypatch):
    monkeypatch.setattr(bot, 'CHAINS', [], raising=False)
    monkeypatch.setattr(bot, 'CATEGORIES', [], raising=False)
    monkeypatch.setattr(bot, 'POLYMARKET_FILTER', True, raising=False)

    captured = {}

    def fake_pm(coins, verbose=True):
        captured['coins'] = list(coins)
        return [c for c in coins if c in ('BTC', 'ETH')]

    monkeypatch.setattr(bot, 'filter_coins_by_polymarket', fake_pm)

    out = bot.apply_coin_filters(['BTC', 'ETH', 'NOPEcoin'])
    assert out == ['BTC', 'ETH']
    assert captured['coins'] == ['BTC', 'ETH', 'NOPEcoin']


# ---------------------------------------------------------------------------
# 4. Filter-failure semantics MATCH the legacy path: a Polymarket API error
#    makes filter_coins_by_polymarket return [] (get_active_events swallows the
#    RequestException). The hybrid seam then yields an empty kept set (every
#    candidate removed) -- fail-closed, mirroring the legacy path where the
#    empty list triggers main()'s no-coins abort. It never falls open onto the
#    unfiltered union.
# ---------------------------------------------------------------------------

def test_hybrid_filter_api_failure_drops_all_candidates_fail_closed():
    candidates = ['BTC', 'PEPE', 'SOL']

    def failing_filter(coins, verbose=True):
        # Mirrors the real behavior on an API error: get_active_events()
        # returns [], get_coins_with_markets() -> empty set, so the
        # comprehension keeps nothing.
        return []

    kept, removed = bot.apply_polymarket_filter_to_candidates(
        candidates, ['BTC', 'PEPE'], enabled=True, filter_fn=failing_filter)

    assert kept == []                          # fail-closed, not the union
    assert {c for c, _ in removed} == set(candidates)


def test_hybrid_filter_failure_matches_legacy_empty_result(monkeypatch):
    """Cross-check: the legacy path also collapses to [] on the same failure,
    so both routes now behave identically (empty -> main aborts the run)."""
    monkeypatch.setattr(bot, 'CHAINS', [], raising=False)
    monkeypatch.setattr(bot, 'CATEGORIES', [], raising=False)
    monkeypatch.setattr(bot, 'POLYMARKET_FILTER', True, raising=False)
    monkeypatch.setattr(bot, 'filter_coins_by_polymarket',
                        lambda coins, verbose=True: [])

    legacy_out = bot.apply_coin_filters(['BTC', 'PEPE', 'SOL'])
    hybrid_out, _ = bot.apply_polymarket_filter_to_candidates(
        ['BTC', 'PEPE', 'SOL'], ['BTC', 'PEPE'], enabled=True,
        filter_fn=lambda coins, verbose=True: [])

    assert legacy_out == [] == hybrid_out
