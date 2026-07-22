"""Tests for WS4 -- analyzer extensions (per-provider attribution, aggregation
policy counterfactuals, confidence calibration, multi-horizon sweep).

All fixtures are synthetic and priced via an in-memory MappingPriceProvider --
nothing touches the network or the real history/ directory. The WS4 analytics
are read-only over already-loaded records; these tests pin the pure kernels
(policy functions, calibration bucketing/Brier, provider attribution + legacy
fallback) and the state-safety of the horizon sweep.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
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


def _score_one(r, p, ledger=None):
    return ta.score_record(r, NOW, 24, 2.4, BTC, p, ledger or [], {})


# ===========================================================================
# grade_provider_vote -- the shared per-vote grader
# ===========================================================================
def test_grade_provider_vote_directional_and_hold_and_abstain():
    # coin +20%, bench 0%, fee 2.4 -> BUY wins, SELL loses
    assert ta.grade_provider_vote('BUY', 20.0, 0.0, 2.4) == ta.WIN
    assert ta.grade_provider_vote('SELL', 20.0, 0.0, 2.4) == ta.LOSS
    assert ta.grade_provider_vote('HOLD', 20.0, 0.0, 2.4) == ta.NEUTRAL
    assert ta.grade_provider_vote(None, 20.0, 0.0, 2.4) is None
    assert ta.grade_provider_vote('WATCH', 20.0, 0.0, 2.4) is None


# ===========================================================================
# Deliverable 1 -- per-provider attribution + legacy fallback
# ===========================================================================
def _scored_directional_with_votes():
    # DOGE +20% vs BTC 0%, fee 2.4 -> a BUY here WINS, a SELL LOSES.
    vd = {'gemini': {'action': 'BUY', 'confidence': 0.9},
          'claude': {'action': 'SELL', 'confidence': 0.8},
          'openai': {'action': None, 'confidence': None},
          'grok': {'action': 'HOLD', 'confidence': 0.5}}
    r = rec('d1', 'DOGE', 'BUY', price=0.10, hours_ago=48,
            llm='gemini,claude,openai,grok', vote_details=vd)
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = _score_one(r, p)
    assert s.category == ta.SCORED and s.outcome == ta.WIN
    return s


def test_provider_attribution_decomposes_each_vote():
    s = _scored_directional_with_votes()
    attr = ta.provider_attribution([s])
    prov = attr['providers']
    assert prov['gemini'] == {'win': 1, 'loss': 0, 'neutral': 0, 'n': 1}   # BUY -> WIN
    assert prov['claude'] == {'win': 0, 'loss': 1, 'neutral': 0, 'n': 1}   # SELL -> LOSS
    assert prov['grok'] == {'win': 0, 'loss': 0, 'neutral': 1, 'n': 1}     # HOLD -> NEUTRAL
    assert 'openai' not in prov          # abstain -> no position, not counted
    assert attr['legacy'] == {} and attr['legacy_n'] == 0


def test_provider_attribution_legacy_fallback_for_v1_records():
    # No vote_details -> legacy comma-joined llm_source keying, record's own outcome.
    r = rec('v1', 'DOGE', 'BUY', price=0.10, hours_ago=48, llm='gemini,claude')
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = _score_one(r, p)
    attr = ta.provider_attribution([s])
    assert attr['providers'] == {}
    assert attr['legacy'] == {'gemini,claude': {'win': 1, 'loss': 0}}
    assert attr['legacy_n'] == 1


def test_provider_attribution_mixes_v1_and_v2():
    s_v2 = _scored_directional_with_votes()
    r_v1 = rec('v1', 'DOGE', 'BUY', price=0.10, hours_ago=48, llm='perplexity')
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s_v1 = _score_one(r_v1, p)
    attr = ta.provider_attribution([s_v2, s_v1])
    assert set(attr['providers']) == {'gemini', 'claude', 'grok'}
    assert attr['legacy'] == {'perplexity': {'win': 1, 'loss': 0}}


# ===========================================================================
# Deliverable 2 -- pure policy functions
# ===========================================================================
def vd(**actions):
    """Build a vote_details dict from provider=action kwargs (action None ok)."""
    return {p: {'action': a, 'confidence': None} for p, a in actions.items()}


def test_policy_unanimous_buy():
    assert ta.policy_unanimous_buy(vd(a='BUY', b='BUY')) is True
    assert ta.policy_unanimous_buy(vd(a='BUY', b='HOLD')) is False
    assert ta.policy_unanimous_buy(vd(a='BUY', b=None)) is False   # abstain breaks it
    assert ta.policy_unanimous_buy({}) is False


def test_policy_majority_buy():
    assert ta.policy_majority_buy(vd(a='BUY', b='BUY', c='HOLD')) is True   # 2/3
    assert ta.policy_majority_buy(vd(a='BUY', b='HOLD')) is False           # 1/2 not > half
    assert ta.policy_majority_buy(vd(a='BUY', b='SELL', c='SELL')) is False


def test_policy_n_of_and_any_buy():
    assert ta.policy_n_of_buy(vd(a='BUY', b='BUY', c='HOLD'), 2) is True
    assert ta.policy_n_of_buy(vd(a='BUY', b='HOLD'), 2) is False
    assert ta.policy_any_buy(vd(a='HOLD', b='BUY')) is True
    assert ta.policy_any_buy(vd(a='HOLD', b='SELL')) is False


def test_policy_single_provider_buy():
    assert ta.policy_single_provider_buy(vd(gemini='BUY', claude='HOLD'), 'gemini') is True
    assert ta.policy_single_provider_buy(vd(gemini='HOLD'), 'gemini') is False
    assert ta.policy_single_provider_buy(vd(claude='BUY'), 'gemini') is False  # absent


def test_abstain_null_counts_as_non_buy_everywhere():
    v = vd(a=None, b=None)
    assert ta.policy_any_buy(v) is False
    assert ta.policy_majority_buy(v) is False
    assert ta.policy_unanimous_buy(v) is False


def test_standard_policies_set_and_ordering():
    pols = ta.standard_policies(['gemini', 'claude'])
    assert 'unanimous-BUY' in pols and 'majority-BUY' in pols
    assert '2-of-N-BUY' in pols and 'any-BUY' in pols
    assert 'only-claude-BUY' in pols and 'only-gemini-BUY' in pols
    # single-provider universe: no 2-of-N policy
    assert '2-of-N-BUY' not in ta.standard_policies(['gemini'])


# ===========================================================================
# Deliverable 2 -- shadow scoring pass + counterfactual aggregation
# ===========================================================================
def _cf_records():
    # Two matured BUY-ish records + one blocked record (all with vote_details).
    win_vd = vd(gemini='BUY', claude='BUY', openai='BUY')      # unanimous BUY
    split_vd = vd(gemini='BUY', claude='HOLD', openai='SELL')  # only gemini BUY
    blocked_vd = vd(gemini='BUY', claude='BUY', openai=None)   # blocked (abstain)
    return [
        rec('win', 'DOGE', 'BUY', price=0.10, hours_ago=48, vote_details=win_vd),
        rec('split', 'PEPE', 'HOLD', price=10.0, hours_ago=48, vote_details=split_vd),
        rec('blk', 'SOL', 'NONE', price=None, hours_ago=48, vote_details=blocked_vd,
            block_reason='disagreement'),
    ]


def _cf_provider():
    # DOGE 0.10->0.12 (+20%), PEPE 10->10.5 (+5%), BTC flat -> DOGE BUY WINS,
    # PEPE BUY LOSES (5% < 2.4%? no: excess = 5-0-2.4 = +2.6 -> WIN). Adjust:
    # make PEPE +1% so its BUY LOSES.
    return provider(
        current={'DOGE': 0.12, 'PEPE': 10.1, BTC: 60000.0},
        historical={hist_key(BTC, 48): 60000.0})


def test_shadow_score_prices_matured_and_marks_unpriced():
    rows = ta.shadow_score(_cf_records(), NOW, 24, 2.4, BTC, _cf_provider(), [])
    assert len(rows) == 3
    by_coin = {r.coin: r for r in rows}
    assert by_coin['DOGE'].matured is True
    assert by_coin['DOGE'].coin_return_pct == pytest.approx(20.0)
    assert by_coin['PEPE'].matured is True    # HOLD-consensus, but priced anyway
    assert by_coin['SOL'].matured is False    # blocked record has no rec price


def test_aggregation_counterfactuals_win_rate_and_excess():
    rows = ta.shadow_score(_cf_records(), NOW, 24, 2.4, BTC, _cf_provider(), [])
    cf = ta.aggregation_counterfactuals(rows, ['gemini', 'claude', 'openai'])
    assert cf['matured_total'] == 2  # DOGE + PEPE
    pols = cf['policies']
    # any-BUY trades on DOGE (unanimous), PEPE (gemini BUY), SOL (2 BUY) = 3 would_trade;
    # matured traded = DOGE + PEPE. DOGE wins (+17.6), PEPE loses (-1.4).
    assert pols['any-BUY']['would_trade'] == 3
    assert pols['any-BUY']['matured_trades'] == 2
    assert pols['any-BUY']['wins'] == 1
    assert pols['any-BUY']['win_rate'] == pytest.approx(0.5)
    # unanimous-BUY: only DOGE (matured) + SOL (unmatured) -> DOGE wins 100%.
    assert pols['unanimous-BUY']['matured_trades'] == 1
    assert pols['unanimous-BUY']['win_rate'] == pytest.approx(1.0)
    assert pols['unanimous-BUY']['mean_excess'] == pytest.approx(20.0 - 0.0 - 2.4)
    # only-gemini-BUY trades DOGE + PEPE (gemini BUY on both) -> 50%.
    assert pols['only-gemini-BUY']['matured_trades'] == 2


def test_counterfactual_policy_with_no_matured_trades_reports_none():
    # A single BLOCKED record (no rec price) -> would_trade counts it, but there
    # are zero MATURED trades, so win_rate/mean_excess report None.
    blocked = rec('blk', 'SOL', 'NONE', price=None, hours_ago=48,
                  vote_details=vd(gemini='BUY', claude='BUY'), block_reason='x')
    rows = ta.shadow_score([blocked], NOW, 24, 2.4, BTC, _cf_provider(), [])
    cf = ta.aggregation_counterfactuals(rows, ['gemini', 'claude'])
    assert cf['matured_total'] == 0
    d = cf['policies']['any-BUY']
    assert d['would_trade'] == 1 and d['matured_trades'] == 0
    assert d['win_rate'] is None and d['mean_excess'] is None


# ===========================================================================
# Deliverable 3 -- confidence calibration (bucketing + Brier)
# ===========================================================================
def test_confidence_bucket_edges():
    assert ta.confidence_bucket(0.55) == (0.5, 0.6)
    assert ta.confidence_bucket(0.6) == (0.6, 0.7)
    assert ta.confidence_bucket(0.0) == (0.0, 0.1)
    assert ta.confidence_bucket(1.0) == (0.9, 1.0)   # clamps the top edge


def test_confidence_calibration_buckets_and_brier():
    # DOGE +20% (BUY wins), FOO +0.5% (BUY loses vs 2.4 fee).
    win_vd = {'gemini': {'action': 'BUY', 'confidence': 0.9},
              'claude': {'action': 'HOLD', 'confidence': 0.4}}   # HOLD excluded
    loss_vd = {'gemini': {'action': 'BUY', 'confidence': 0.6},
               'openai': {'action': 'BUY', 'confidence': None}}  # null conf excluded
    recs = [
        rec('w', 'DOGE', 'BUY', price=0.10, hours_ago=48, vote_details=win_vd),
        rec('l', 'FOO', 'BUY', price=100.0, hours_ago=48, vote_details=loss_vd),
    ]
    p = provider(current={'DOGE': 0.12, 'FOO': 100.5, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    rows = ta.shadow_score(recs, NOW, 24, 2.4, BTC, p, [])
    cal = ta.confidence_calibration(rows)
    # two graded directional votes with numeric conf: 0.9 (win) and 0.6 (loss)
    assert cal['n'] == 2
    assert cal['buckets'][(0.9, 1.0)] == {'n': 1, 'wins': 1, 'win_rate': 1.0}
    assert cal['buckets'][(0.6, 0.7)] == {'n': 1, 'wins': 0, 'win_rate': 0.0}
    # Brier = mean((0.9-1)^2, (0.6-0)^2) = mean(0.01, 0.36) = 0.185
    assert cal['brier'] == pytest.approx((0.01 + 0.36) / 2)


def test_confidence_calibration_empty_when_no_numeric_confidence():
    v = {'gemini': {'action': 'BUY', 'confidence': None}}
    r = rec('n', 'DOGE', 'BUY', price=0.10, hours_ago=48, vote_details=v)
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    rows = ta.shadow_score([r], NOW, 24, 2.4, BTC, p, [])
    cal = ta.confidence_calibration(rows)
    assert cal['n'] == 0 and cal['brier'] is None and cal['buckets'] == {}


def test_calibration_ignores_bool_confidence():
    # A stray boolean must not be treated as a 0/1 confidence.
    v = {'gemini': {'action': 'BUY', 'confidence': True}}
    r = rec('b', 'DOGE', 'BUY', price=0.10, hours_ago=48, vote_details=v)
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    rows = ta.shadow_score([r], NOW, 24, 2.4, BTC, p, [])
    assert ta.confidence_calibration(rows)['n'] == 0


# ===========================================================================
# Deliverable 4 -- horizon sweep STATE-SAFETY (never touches judged state)
# ===========================================================================
def test_horizon_sweep_reports_per_horizon_distribution():
    r = rec('h', 'DOGE', 'BUY', price=0.10, hours_ago=48, mode='whatif')
    # At 24h maturity DOGE matured; at 168h (7d) it's younger than horizon -> pending.
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    sweep = ta.horizon_sweep([r], NOW, [6, 24, 168], 2.4, BTC, p, [])
    assert set(sweep) == {6, 24, 168}
    assert sweep[24]['scored'] == 1
    assert sweep[168]['pending'] == 1   # 48h old < 168h horizon
    assert sweep[24]['win'] + sweep[24]['loss'] == 1


def test_horizon_sweep_does_not_persist_or_read_state():
    """The sweep must compute-without-persisting: a shared frozen_state dict
    passed to nothing here stays empty, and the sweep never freezes a verdict
    under the non-horizon-aware state key (which would corrupt the 24h grade)."""
    r = rec('h', 'DOGE', 'BUY', price=0.10, hours_ago=48, mode='whatif')
    p = provider(current={'DOGE': 0.12, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    state = {}
    # A canonical single-horizon analyze at 24h freezes exactly one verdict.
    ta.analyze([r], NOW, 24, 2.4, BTC, p, [], state)
    assert len(state) == 1
    key = ta.state_key(r)
    canonical = dict(state[key])
    # Now run a sweep at OTHER horizons; it must not touch `state` at all.
    ta.horizon_sweep([r], NOW, [6, 72, 168], 2.4, BTC, p, [])
    assert state[key] == canonical          # untouched
    assert len(state) == 1                  # no new/overwritten keys


def test_horizon_sweep_grade_can_flip_between_horizons():
    """Different horizons can produce different verdicts -- proving the sweep
    scores each horizon independently (and why sharing state would corrupt)."""
    r = rec('flip', 'DOGE', 'BUY', price=0.10, hours_ago=100)
    p = provider(
        current={'DOGE': 999.0, BTC: 999.0},   # run-time ignored when maturity candles exist
        historical={
            hist_key(BTC, 100): 60000.0,                    # bench at rec time
            hist_key('DOGE', 76): 0.20, hist_key(BTC, 76): 60000.0,   # +24h: DOGE +100% WIN
            hist_key('DOGE', 28): 0.10, hist_key(BTC, 28): 60000.0,   # +72h: DOGE flat LOSS
        })
    sweep = ta.horizon_sweep([r], NOW, [24, 72], 2.4, BTC, p, [])
    assert sweep[24]['win'] == 1 and sweep[24]['loss'] == 0
    assert sweep[72]['loss'] == 1 and sweep[72]['win'] == 0


# ===========================================================================
# Output discipline -- new sections gated on vote_details / --horizons
# ===========================================================================
def test_cli_no_ws4_sections_for_legacy_v1_history(tmp_path, capsys):
    (tmp_path / 'recommendations.json').write_text(json.dumps({'recommendations': [
        rec('v1a', 'DOGE', 'BUY', price=0.10, hours_ago=48, mode='whatif'),
    ]}))
    ta.cli_main(['--history-dir', str(tmp_path), '--offline', '--now', NOW.isoformat()])
    out = capsys.readouterr().out
    assert 'RECORD ACCOUNTING' in out                 # default shape intact
    assert 'AGGREGATION-POLICY COUNTERFACTUALS' not in out
    assert 'CONFIDENCE CALIBRATION' not in out
    assert 'MULTI-HORIZON' not in out


def test_cli_horizon_sweep_only_when_flag_passed(tmp_path, capsys):
    (tmp_path / 'recommendations.json').write_text(json.dumps({'recommendations': [
        rec('v1a', 'DOGE', 'BUY', price=0.10, hours_ago=48, mode='whatif'),
    ]}))
    ta.cli_main(['--history-dir', str(tmp_path), '--offline',
                 '--now', NOW.isoformat(), '--horizons', '6,24,72'])
    out = capsys.readouterr().out
    assert 'MULTI-HORIZON MATURATION SWEEP' in out


def test_cli_research_sections_appear_with_vote_details(tmp_path, capsys):
    vote = {'gemini': {'action': 'BUY', 'confidence': 0.7},
            'claude': {'action': 'BUY', 'confidence': 0.8}}
    (tmp_path / 'recommendations.json').write_text(json.dumps({'recommendations': [
        rec('v2a', 'BTC', 'BUY', price=60000.0, hours_ago=48, mode='whatif',
            vote_details=vote),
    ]}))
    # BTC-as-benchmark scores with only a current price (no historical needed).
    # Use a non-offline path is unnecessary; offline NullProvider yields no price,
    # so provide a mapping provider by monkeypatching is overkill -- instead assert
    # the sections are emitted (headers print even with zero matured rows).
    ta.cli_main(['--history-dir', str(tmp_path), '--offline', '--now', NOW.isoformat()])
    out = capsys.readouterr().out
    assert 'AGGREGATION-POLICY COUNTERFACTUALS' in out
    assert 'RESEARCH ONLY' in out
    assert 'CONFIDENCE CALIBRATION' in out
