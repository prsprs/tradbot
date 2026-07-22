"""WS-3 (cycle 2): HOLD counterfactual scoring.

A matured HOLD keeps outcome=NEUTRAL (it is never WIN/LOSS and stays out of every
existing aggregation universe), but now also carries a NEW derived `hold_class`
that grades the "had we BOUGHT instead?" counterfactual under the SAME
fee-adjusted BUY excess kernel the analyzer already uses:

  * GOOD_AVOID      -- counterfactual BUY excess <= -band: buying would have lost.
  * MISSED_WIN      -- counterfactual BUY excess >= +band: buying would have beaten
                       the benchmark net of fees.
  * CORRECT_NEUTRAL -- excess strictly inside the band: HOLD was right to sit out.
  * HOLD_UNSCORABLE -- no maturity/rec price or no benchmark: no counterfactual.

Boundary (pinned): edges are inclusive to the outer, decisive classes -- exactly
+band is MISSED_WIN, exactly -band is GOOD_AVOID -- mirroring grade(), where the
excess==0 tie is decisive (a LOSS), not parked in a neutral band.

All fixtures are synthetic and priced via an in-memory MappingPriceProvider --
nothing touches the network or the real history/ directory.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tradeanalyzer as ta

NOW = datetime(2026, 7, 18, 12, 0, 0)
BTC = 'BTC'


def rec(rec_id, coin, action, price=100.0, hours_ago=48, mode='whatif',
        llm='gemini', run_id=None, vote_details=None, **extra):
    ts = (NOW - timedelta(hours=hours_ago))
    r = {
        'id': rec_id,
        'timestamp': ts.isoformat() + 'Z',
        'coin_symbol': coin,
        'recommendation': action,
        'price_at_recommendation': price,
        'bid_price': price,
        'ask_price': price,
        'llm_source': llm,
        'mode': 'compare',
        'trading_mode': mode,
        'run_id': run_id,
    }
    if vote_details is not None:
        r['vote_details'] = vote_details
    r.update(extra)
    return r


def provider(current=None, historical=None):
    return ta.MappingPriceProvider(current=current or {}, historical=historical or {})


def hist_key(coin, hours_ago):
    return (coin, (NOW - timedelta(hours=hours_ago)).isoformat())


def _hold_provider(coin, coin_end, bench_then=60000.0, bench_end=60000.0):
    """AT-maturity provider for a HOLD on `coin` (maturity = rec_time + 24h)."""
    return provider(
        current={coin: coin_end, BTC: bench_end},
        historical={
            hist_key(coin, 24): coin_end,    # coin at maturity horizon
            hist_key(BTC, 24): bench_end,     # benchmark at maturity horizon
            hist_key(BTC, 48): bench_then,    # benchmark at rec time
        })


def _score(r, p):
    return ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})


# ===========================================================================
# Pure classifier: the band cut + boundary semantics
# ===========================================================================
def test_classify_hold_counterfactual_bands():
    band = ta.HOLD_COUNTERFACTUAL_BAND_PCT
    assert ta.classify_hold_counterfactual(band + 5) == ta.MISSED_WIN
    assert ta.classify_hold_counterfactual(-(band + 5)) == ta.GOOD_AVOID
    assert ta.classify_hold_counterfactual(0.0) == ta.CORRECT_NEUTRAL
    assert ta.classify_hold_counterfactual(None) == ta.HOLD_UNSCORABLE


def test_classify_hold_boundary_is_inclusive_to_outer_classes():
    band = ta.HOLD_COUNTERFACTUAL_BAND_PCT
    # Exactly +/-band is decisive, not neutral (mirrors grade()'s 0-tie -> LOSS).
    assert ta.classify_hold_counterfactual(band) == ta.MISSED_WIN
    assert ta.classify_hold_counterfactual(-band) == ta.GOOD_AVOID
    # A hair inside the band is neutral on both sides.
    assert ta.classify_hold_counterfactual(band - 0.001) == ta.CORRECT_NEUTRAL
    assert ta.classify_hold_counterfactual(-(band - 0.001)) == ta.CORRECT_NEUTRAL


# ===========================================================================
# score_record: one fixture record per class, outcome stays NEUTRAL
# ===========================================================================
def test_hold_good_avoid_buying_would_have_lost():
    # coin -10% (0.10 -> 0.09), bench +5% -> excess = -15 - 2.4 = -17.4 -> GOOD_AVOID.
    r = rec('ga', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    s = _score(r, _hold_provider('DOGE', 0.09, bench_then=60000.0, bench_end=63000.0))
    assert s.category == ta.SCORED
    assert s.outcome == ta.NEUTRAL           # regression pin
    assert s.hold_class == ta.GOOD_AVOID
    assert s.excess_return_pct == pytest.approx((-10.0 - 5.0) - 2.4)


def test_hold_missed_win_buying_would_have_won():
    # coin +20% (0.10 -> 0.12), bench 0% -> excess = 20 - 2.4 = 17.6 -> MISSED_WIN.
    r = rec('mw', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    s = _score(r, _hold_provider('DOGE', 0.12))
    assert s.category == ta.SCORED
    assert s.outcome == ta.NEUTRAL           # regression pin
    assert s.hold_class == ta.MISSED_WIN
    assert s.coin_return_pct == pytest.approx(20.0)
    assert s.benchmark_return_pct == pytest.approx(0.0)


def test_hold_correct_neutral_inside_band():
    # coin +2.4% (0.10 -> 0.1024), bench 0% -> excess = 2.4 - 2.4 = 0.0 -> CORRECT_NEUTRAL.
    r = rec('cn', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    s = _score(r, _hold_provider('DOGE', 0.1024))
    assert s.category == ta.SCORED
    assert s.outcome == ta.NEUTRAL           # regression pin
    assert s.hold_class == ta.CORRECT_NEUTRAL
    assert s.excess_return_pct == pytest.approx(0.0, abs=1e-9)


def test_hold_missing_benchmark_is_unscorable_but_still_neutral():
    # Provider has the coin price but NO benchmark -> no counterfactual excess.
    r = rec('u1', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    p = provider(current={'DOGE': 0.12})    # no BTC anywhere
    s = _score(r, p)
    assert s.category == ta.SCORED
    assert s.outcome == ta.NEUTRAL           # regression pin
    assert s.hold_class == ta.HOLD_UNSCORABLE
    assert s.excess_return_pct is None
    # Legacy best-effort coin move is still recorded where a coin price exists.
    assert s.coin_return_pct == pytest.approx(20.0)


def test_hold_missing_price_entirely_is_unscorable():
    # No coin price anywhere -> no move, unscorable, but still NEUTRAL/SCORED.
    r = rec('u2', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    s = _score(r, provider())               # empty provider
    assert s.category == ta.SCORED
    assert s.outcome == ta.NEUTRAL           # regression pin
    assert s.hold_class == ta.HOLD_UNSCORABLE
    assert s.coin_return_pct is None


# ===========================================================================
# Band-edge cases through score_record (pin the boundary end-to-end)
# ===========================================================================
def test_hold_exactly_plus_band_is_missed_win():
    # coin +4.4%, bench 0% -> excess = 4.4 - 2.4 = +2.0 == +band -> MISSED_WIN.
    band = ta.HOLD_COUNTERFACTUAL_BAND_PCT
    coin_end = 0.10 * (1 + (band + 2.4) / 100.0)
    r = rec('e+', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    s = _score(r, _hold_provider('DOGE', coin_end))
    assert s.excess_return_pct == pytest.approx(band)
    assert s.hold_class == ta.MISSED_WIN


def test_hold_exactly_minus_band_is_good_avoid():
    # excess = -band exactly -> GOOD_AVOID (inclusive to outer class).
    band = ta.HOLD_COUNTERFACTUAL_BAND_PCT
    coin_end = 0.10 * (1 + (2.4 - band) / 100.0)
    r = rec('e-', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    s = _score(r, _hold_provider('DOGE', coin_end))
    assert s.excess_return_pct == pytest.approx(-band)
    assert s.hold_class == ta.GOOD_AVOID


# ===========================================================================
# Directional records are untouched (hold_class stays None)
# ===========================================================================
def test_directional_buy_has_no_hold_class():
    r = rec('b', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = _score(r, p)
    assert s.category == ta.SCORED
    assert s.outcome in (ta.WIN, ta.LOSS)
    assert s.hold_class is None


# ===========================================================================
# State-version bump discards pre-existing analyzer_state
# ===========================================================================
def test_state_version_bumped_past_v3():
    assert ta.STATE_VERSION >= 4


def test_prior_version_state_is_discarded(tmp_path):
    old = tmp_path / 'analyzer_state.json'
    old.write_text(json.dumps({'version': 3, 'scored': {'k': {'outcome': 'NEUTRAL'}}}))
    assert ta.load_state(str(old)) == {}     # discarded, not migrated


def test_hold_class_survives_freeze_thaw():
    r = rec('mw', 'DOGE', 'HOLD', price=0.10, hours_ago=48)
    p = _hold_provider('DOGE', 0.12)
    state = {}
    first = ta.analyze([r], NOW, 24, 2.4, BTC, p, [], state)
    assert first.scored[0].hold_class == ta.MISSED_WIN
    assert len(state) == 1
    # Second run reads it back from frozen state -- price provider now empty.
    second = ta.analyze([r], NOW, 24, 2.4, BTC, provider(), [], state)
    assert second.scored[0].frozen is True
    assert second.scored[0].hold_class == ta.MISSED_WIN
    assert second.scored[0].outcome == ta.NEUTRAL


# ===========================================================================
# Report: HOLD-classification counts + per-provider HOLD tally
# ===========================================================================
def test_hold_class_counts_over_result():
    recs = [
        rec('mw', 'DOGE', 'HOLD', price=0.10, hours_ago=48),
        rec('ga', 'PEPE', 'HOLD', price=0.10, hours_ago=48),
    ]
    p = provider(
        current={'DOGE': 0.12, 'PEPE': 0.09, BTC: 63000.0},
        historical={
            hist_key('DOGE', 24): 0.12, hist_key('PEPE', 24): 0.09,
            hist_key(BTC, 24): 63000.0, hist_key(BTC, 48): 60000.0,
        })
    result = ta.analyze(recs, NOW, 24, 2.4, BTC, p, [], {})
    counts = result.hold_class_counts()
    assert counts[ta.MISSED_WIN] == 1     # DOGE +20% vs bench +5% -> missed
    assert counts[ta.GOOD_AVOID] == 1     # PEPE -10% vs bench +5% -> avoided
    assert counts[ta.CORRECT_NEUTRAL] == 0
    assert counts[ta.HOLD_UNSCORABLE] == 0


def test_provider_hold_quality_credits_only_own_hold_votes():
    vd = {'gemini': {'action': 'HOLD', 'confidence': 0.6},
          'claude': {'action': 'HOLD', 'confidence': 0.5},
          'openai': {'action': 'BUY', 'confidence': 0.7},   # not a HOLD -> ignored
          'grok': {'action': None, 'confidence': None}}      # abstain -> ignored
    r = rec('mw', 'DOGE', 'HOLD', price=0.10, hours_ago=48,
            llm='gemini,claude,openai,grok', vote_details=vd)
    s = _score(r, _hold_provider('DOGE', 0.12))   # MISSED_WIN
    assert s.hold_class == ta.MISSED_WIN
    hq = ta.provider_hold_quality([s])
    assert hq['gemini'] == {'good_avoids': 0, 'missed_wins': 1,
                            'correct_neutral': 0, 'unscorable': 0, 'n': 1}
    assert hq['claude']['missed_wins'] == 1
    assert 'openai' not in hq             # voted BUY, not credited a HOLD
    assert 'grok' not in hq               # abstain


def test_provider_hold_quality_legacy_fallback():
    r = rec('ga', 'DOGE', 'HOLD', price=0.10, hours_ago=48, llm='gemini,claude')
    s = _score(r, _hold_provider('DOGE', 0.09, bench_then=60000.0, bench_end=63000.0))
    assert s.hold_class == ta.GOOD_AVOID
    hq = ta.provider_hold_quality([s])
    assert hq['gemini,claude']['good_avoids'] == 1


def test_report_emits_hold_classification_and_per_provider_tally(tmp_path, capsys):
    vd = {'gemini': {'action': 'HOLD', 'confidence': 0.6}}
    recs = {'recommendations': [
        rec('mw', 'BTC', 'HOLD', price=60000.0, hours_ago=48, mode='whatif',
            vote_details=vd),
    ]}
    (tmp_path / 'recommendations.json').write_text(json.dumps(recs))
    # BTC-as-benchmark: only a current price needed (bench return := 0), so the
    # offline null provider still can't price it -> keep it simple with a mapping.
    # cli_main --offline uses the null provider; assert the SECTION HEADER prints
    # regardless (a HOLD is always SCORED, so the classification section appears).
    ta.cli_main(['--history-dir', str(tmp_path), '--offline', '--now', NOW.isoformat()])
    out = capsys.readouterr().out
    assert 'HOLD COUNTERFACTUAL CLASSIFICATION' in out
    assert 'per-provider HOLD quality' in out
    assert 'gemini' in out
