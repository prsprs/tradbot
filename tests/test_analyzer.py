"""Tests for tradeanalyzer.py (T10 overhaul).

All fixtures are synthetic and written to tmp_path -- these tests NEVER read the
repo's real history/ directory. Prices come from an in-memory MappingPriceProvider
so nothing touches the network.

Coverage (task-mandated minimums, plus a few edges):
  * bucket totality -- every record lands in exactly one category
  * trading_mode='unknown' exclusion
  * live/whatif separation
  * benchmark-relative math incl. the fee floor (coin-up-but-loss)
  * ledger-fee join + graceful degradation to the assumed floor
  * blocked-decision (NONE) panel stats
  * *.bak-* files are never read as data
  * judged-flag persistence / freezing
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tradeanalyzer as ta

NOW = datetime(2026, 7, 18, 12, 0, 0)
BTC = 'BTC'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def rec(rec_id, coin, action, price=100.0, hours_ago=48, mode='live',
        llm='gemini', run_id=None, **extra):
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
        'consensus': None,
        'trading_mode': mode,
        'run_id': run_id,
    }
    r.update(extra)
    return r


def provider(current=None, historical=None):
    return ta.MappingPriceProvider(current=current or {}, historical=historical or {})


def hist_key(coin, hours_ago):
    """Historical key matching how score_record parses the timestamp."""
    return (coin, (NOW - timedelta(hours=hours_ago)).isoformat())


# ===========================================================================
# Pure math: benchmark-relative grading incl. the fee floor
# ===========================================================================
def test_buy_up_but_loses_to_benchmark_is_a_loss():
    # coin +3%, BTC +10%, fee 2.4 -> excess -9.4 -> LOSS even though coin rose.
    outcome, excess = ta.grade('BUY', 3.0, 10.0, 2.4)
    assert outcome == ta.LOSS
    assert excess == pytest.approx(3.0 - 10.0 - 2.4)


def test_buy_beats_benchmark_but_not_fees_is_a_loss():
    # coin +2%, BTC 0%, fee 2.4 -> excess -0.4 -> LOSS.
    outcome, excess = ta.grade('BUY', 2.0, 0.0, 2.4)
    assert outcome == ta.LOSS


def test_buy_beats_both_is_a_win():
    outcome, excess = ta.grade('BUY', 20.0, 1.667, 2.4)
    assert outcome == ta.WIN
    assert excess == pytest.approx(20.0 - 1.667 - 2.4)


def test_sell_wins_when_coin_underperforms_benchmark_beyond_fees():
    # coin -20%, BTC +5% -> rel -25 -> SELL excess = 25 - 2.4 = 22.6 -> WIN.
    outcome, excess = ta.grade('SELL', -20.0, 5.0, 2.4)
    assert outcome == ta.WIN
    assert excess == pytest.approx(22.6)


def test_grade_tie_is_a_loss():
    # exactly zero excess -> flat trade still lost its fees -> LOSS.
    outcome, excess = ta.grade('BUY', 2.4, 0.0, 2.4)
    assert excess == pytest.approx(0.0)
    assert outcome == ta.LOSS


# ===========================================================================
# score_record: end-to-end classification with a fake provider
# ===========================================================================
def test_scored_buy_win_uses_benchmark_window():
    r = rec('b1', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p = provider(current={'DOGE': 0.12, BTC: 61000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.SCORED
    assert s.outcome == ta.WIN
    assert s.coin_return_pct == pytest.approx(20.0)
    assert s.benchmark_return_pct == pytest.approx((61000 - 60000) / 60000 * 100)
    assert s.fee_source == 'assumed'
    assert s.fee_floor_pct == 2.4


def test_scored_buy_coin_up_but_loss():
    r = rec('b2', 'FOO', 'BUY', price=100.0, hours_ago=48)
    p = provider(current={'FOO': 103.0, BTC: 66000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.SCORED
    assert s.outcome == ta.LOSS  # +3% coin, +10% BTC -> loss


def test_benchmark_coin_judged_absolute_vs_fees():
    # A BUY on BTC itself: benchmark return := 0, judged on absolute vs fees.
    r = rec('b3', 'BTC', 'BUY', price=60000.0, hours_ago=48)
    p = provider(current={BTC: 63000.0})  # +5%, no historical needed
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.SCORED
    assert s.benchmark_return_pct == 0.0
    assert s.outcome == ta.WIN  # 5 - 0 - 2.4 > 0


def test_pending_when_too_fresh():
    r = rec('p1', 'DOGE', 'BUY', hours_ago=5)  # < 24h maturity
    p = provider(current={'DOGE': 999.0, BTC: 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.PENDING


def test_expired_unscorable_when_no_current_price():
    r = rec('e1', 'DOGE', 'BUY', hours_ago=48)
    p = provider(current={BTC: 60000.0}, historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.EXPIRED_UNSCORABLE
    assert s.reason == 'no_current_price'


def test_expired_unscorable_when_no_benchmark():
    r = rec('e2', 'DOGE', 'BUY', hours_ago=48)
    p = provider(current={'DOGE': 0.12, BTC: 60000.0})  # no historical BTC key
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.EXPIRED_UNSCORABLE
    assert s.reason == 'no_benchmark'


def test_expired_unscorable_when_rec_price_zero():
    r = rec('e3', 'DOGE', 'BUY', price=0, hours_ago=48)
    p = provider(current={'DOGE': 0.12, BTC: 61000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.EXPIRED_UNSCORABLE
    assert s.reason == 'no_rec_price'


def test_hold_is_scored_neutral():
    r = rec('h1', 'ETH', 'HOLD', price=2000.0, hours_ago=48)
    p = provider(current={'ETH': 2100.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.SCORED
    assert s.outcome == ta.NEUTRAL
    assert s.coin_return_pct == pytest.approx(5.0)


def test_blocked_none_is_blocked_category():
    r = rec('bl1', 'SOL', 'NONE', hours_ago=48, block_reason='abstain(openai:error)',
            consensus_state='blocked')
    s = ta.score_record(r, NOW, 24, 2.4, BTC, provider(), [], {})
    assert s.category == ta.BLOCKED


def test_unknown_mode_excluded():
    r = rec('u1', 'DOGE', 'BUY', hours_ago=48, mode='unknown')
    p = provider(current={'DOGE': 0.12, BTC: 61000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.EXCLUDED_UNKNOWN


def test_missing_trading_mode_treated_as_unknown():
    r = rec('u2', 'DOGE', 'BUY', hours_ago=48)
    del r['trading_mode']
    s = ta.score_record(r, NOW, 24, 2.4, BTC, provider(), [], {})
    assert s.category == ta.EXCLUDED_UNKNOWN


def test_non_trading_record():
    r = {'id': 'nt1', 'timestamp': NOW.isoformat() + 'Z', 'kind': 'llm_compare'}
    s = ta.score_record(r, NOW, 24, 2.4, BTC, provider(), [], {})
    assert s.category == ta.NON_TRADING


def test_bad_timestamp_is_expired_unscorable():
    r = rec('bt1', 'DOGE', 'BUY', hours_ago=48)
    r['timestamp'] = 'not-a-date'
    s = ta.score_record(r, NOW, 24, 2.4, BTC, provider(), [], {})
    assert s.category == ta.EXPIRED_UNSCORABLE
    assert s.reason == 'bad_timestamp'


# ===========================================================================
# Ledger-fee join + graceful degradation
# ===========================================================================
def test_actual_roundtrip_fee_from_ledger():
    ledger = [
        {'status': 'intent', 'run_id': 'run_x', 'coin': 'SOL', 'side': 'BUY',
         'ledger_id': 'led1'},
        {'status': 'filled', 'ledger_id': 'led1', 'filled_size': 1.0,
         'avg_fill_price': 100.0, 'fees_usd': 1.0},
    ]
    # entry fee = 1/100 = 1%; round trip estimate = 2%.
    assert ta.actual_roundtrip_fee_pct('run_x', 'SOL', ledger) == pytest.approx(2.0)


def test_actual_fee_none_without_run_id():
    assert ta.actual_roundtrip_fee_pct(None, 'SOL', []) is None


def test_actual_fee_none_when_only_intent_no_fill():
    ledger = [{'status': 'intent', 'run_id': 'run_x', 'coin': 'SOL', 'side': 'BUY',
               'ledger_id': 'led1'}]
    assert ta.actual_roundtrip_fee_pct('run_x', 'SOL', ledger) is None


def test_score_uses_ledger_fee_when_available():
    r = rec('lf1', 'SOL', 'BUY', price=100.0, hours_ago=48, run_id='run_x')
    ledger = [
        {'status': 'intent', 'run_id': 'run_x', 'coin': 'SOL', 'side': 'BUY',
         'ledger_id': 'led1'},
        {'status': 'filled', 'ledger_id': 'led1', 'filled_size': 1.0,
         'avg_fill_price': 100.0, 'fees_usd': 1.0},
    ]
    p = provider(current={'SOL': 105.0, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, ledger, {})
    assert s.fee_source == 'ledger'
    assert s.fee_floor_pct == pytest.approx(2.0)
    # coin +5%, BTC 0%, fee 2% -> excess +3 -> WIN
    assert s.outcome == ta.WIN


def test_score_degrades_to_assumed_fee_without_ledger():
    r = rec('lf2', 'SOL', 'BUY', price=100.0, hours_ago=48, run_id='run_y')
    p = provider(current={'SOL': 105.0, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})  # empty ledger
    assert s.fee_source == 'assumed'
    assert s.fee_floor_pct == 2.4


# ===========================================================================
# analyze(): totality, separation, unknown exclusion
# ===========================================================================
def _mixed_records():
    return [
        rec('live_buy', 'DOGE', 'BUY', price=0.10, hours_ago=48, mode='live'),
        rec('live_sell', 'PEPE', 'SELL', price=10.0, hours_ago=48, mode='live'),
        rec('whatif_buy', 'ETH', 'BUY', price=2000.0, hours_ago=48, mode='whatif'),
        rec('live_hold', 'ADA', 'HOLD', price=1.0, hours_ago=48, mode='live'),
        rec('live_pending', 'SOL', 'BUY', price=100.0, hours_ago=3, mode='live'),
        rec('unknown_buy', 'XRP', 'BUY', price=1.0, hours_ago=48, mode='unknown'),
        rec('blocked', 'LTC', 'NONE', hours_ago=48, mode='live',
            block_reason='sub_quorum: 1 of 3', consensus_state='blocked',
            votes={'gemini': 'BUY', 'openai': 'ABSTAIN(error)'}),
        {'id': 'compare', 'timestamp': NOW.isoformat() + 'Z', 'kind': 'llm_compare'},
        rec('live_expired', 'MISS', 'BUY', price=5.0, hours_ago=48, mode='live'),
    ]


def _full_provider():
    return provider(
        current={'DOGE': 0.12, 'PEPE': 8.0, 'ETH': 2200.0, 'ADA': 1.1,
                 'SOL': 105.0, BTC: 61000.0},
        historical={hist_key(BTC, 48): 60000.0},
    )


def test_totality_every_record_in_exactly_one_category():
    records = _mixed_records()
    result = ta.analyze(records, NOW, 24, 2.4, BTC, _full_provider(), [], {})
    counts = result.category_counts()
    assert sum(counts.values()) == len(records)
    assert len(result.all_records) == len(records)
    # every record got exactly one category value from the known set
    known = {ta.NON_TRADING, ta.EXCLUDED_UNKNOWN, ta.BLOCKED, ta.PENDING,
             ta.SCORED, ta.EXPIRED_UNSCORABLE}
    assert all(s.category in known for s in result.all_records)


def test_lifecycle_buckets_cover_scoring_universe():
    records = _mixed_records()
    result = ta.analyze(records, NOW, 24, 2.4, BTC, _full_provider(), [], {})
    lc = result.lifecycle_counts()
    universe = result.scoring_universe()
    assert sum(lc.values()) == len(universe)
    # 'MISS' has no current price -> expired; SOL fresh -> pending; the rest scored
    assert lc[ta.PENDING] == 1
    assert lc[ta.EXPIRED_UNSCORABLE] == 1
    assert lc[ta.SCORED] >= 3


def test_live_and_whatif_scored_separately():
    records = _mixed_records()
    result = ta.analyze(records, NOW, 24, 2.4, BTC, _full_provider(), [], {})
    live_scored = [s for s in result.scored if s.trading_mode == 'live']
    whatif_scored = [s for s in result.scored if s.trading_mode == 'whatif']
    assert {s.coin for s in whatif_scored} == {'ETH'}
    assert 'ETH' not in {s.coin for s in live_scored}
    # unknown mode never appears in scored
    assert 'XRP' not in {s.coin for s in result.scored}


def test_unknown_excluded_from_scoring_but_counted():
    records = _mixed_records()
    result = ta.analyze(records, NOW, 24, 2.4, BTC, _full_provider(), [], {})
    counts = result.category_counts()
    assert counts[ta.EXCLUDED_UNKNOWN] == 1
    assert all(s.trading_mode != 'unknown' for s in result.scoring_universe())


# ===========================================================================
# Panel behavior from blocked records
# ===========================================================================
def test_panel_stats():
    records = [
        rec('bl1', 'SOL', 'NONE', block_reason='abstain(openai:error)',
            consensus_state='blocked',
            votes={'gemini': 'BUY', 'claude': 'BUY', 'openai': 'ABSTAIN(error)'}),
        rec('bl2', 'ETH', 'NONE', block_reason='sub_quorum: 1 of 3',
            consensus_state='blocked',
            votes={'gemini': 'HOLD', 'openai': 'ABSTAIN(parse_failure)'}),
        rec('live_buy', 'DOGE', 'BUY'),  # not blocked -> ignored
    ]
    ps = ta.panel_stats(records)
    assert ps['blocked_total'] == 2
    assert ps['block_reason_hist'] == {'abstain': 1, 'sub_quorum': 1}
    assert ps['consensus_state_hist'] == {'blocked': 2}
    assert ps['per_llm_votes']['gemini'] == {'BUY': 1, 'HOLD': 1}
    assert ps['per_llm_votes']['openai'] == {'ABSTAIN': 2}


def test_normalize_block_reason_variants():
    assert ta.normalize_block_reason('abstain(openai:error)') == 'abstain'
    assert ta.normalize_block_reason('sub_quorum: 1 of 3') == 'sub_quorum'
    assert ta.normalize_block_reason('disagreement') == 'disagreement'
    assert ta.normalize_block_reason(None) == 'unknown'


# ===========================================================================
# Loading: *.bak-* skipping and ledger loading
# ===========================================================================
def test_backup_files_never_read(tmp_path):
    real = tmp_path / 'recommendations.json'
    real.write_text(json.dumps({'recommendations': [rec('keep', 'DOGE', 'BUY')]}))
    backup = tmp_path / 'recommendations.json.bak-20260718T205904Z'
    backup.write_text(json.dumps({'recommendations': [rec('drop', 'PEPE', 'SELL')]}))

    loaded = ta.load_records(str(tmp_path))
    ids = {r['id'] for r in loaded}
    assert ids == {'keep'}
    assert 'drop' not in ids


def test_is_backup_file():
    assert ta.is_backup_file('recommendations.json.bak-20260718T205904Z')
    assert not ta.is_backup_file('recommendations.json')


def test_load_ledger(tmp_path):
    (tmp_path / 'executions.json').write_text(
        json.dumps({'executions': [{'status': 'intent', 'ledger_id': 'l1'}]}))
    rows = ta.load_ledger(str(tmp_path))
    assert len(rows) == 1
    # missing file -> empty
    assert ta.load_ledger(str(tmp_path / 'nope')) == []


# ===========================================================================
# Judged-flag persistence / freezing
# ===========================================================================
def test_scored_record_frozen_across_reruns():
    r = rec('freeze1', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    win_provider = provider(current={'DOGE': 0.20, BTC: 60000.0},
                            historical={hist_key(BTC, 48): 60000.0})
    state = {}
    first = ta.analyze([r], NOW, 24, 2.4, BTC, win_provider, [], state)
    assert first.scored[0].outcome == ta.WIN
    # F4 (intentional change): state is now keyed on the collision-safe composite
    # key (state_key), not the bare record id 'freeze1'.
    assert ta.state_key(r) in state
    assert 'freeze1' not in state

    # Market moves against us; a fresh score would be a LOSS...
    loss_provider = provider(current={'DOGE': 0.05, BTC: 90000.0},
                             historical={hist_key(BTC, 48): 60000.0})
    second = ta.analyze([r], NOW, 24, 2.4, BTC, loss_provider, [], state)
    # ...but the frozen state keeps the original WIN.
    assert second.scored[0].outcome == ta.WIN
    assert second.scored[0].frozen is True


def test_state_file_roundtrip(tmp_path):
    path = tmp_path / 'analyzer_state.json'
    ta.save_state(str(path), {'r1': {'outcome': 'WIN'}})
    loaded = ta.load_state(str(path))
    assert loaded == {'r1': {'outcome': 'WIN'}}
    assert ta.load_state(str(tmp_path / 'missing.json')) == {}


def test_no_state_means_records_regrade():
    r = rec('nostate', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p1 = provider(current={'DOGE': 0.20, BTC: 60000.0},
                  historical={hist_key(BTC, 48): 60000.0})
    first = ta.analyze([r], NOW, 24, 2.4, BTC, p1, [], None)  # no state
    assert first.scored[0].outcome == ta.WIN
    p2 = provider(current={'DOGE': 0.05, BTC: 90000.0},
                  historical={hist_key(BTC, 48): 60000.0})
    second = ta.analyze([r], NOW, 24, 2.4, BTC, p2, [], None)
    assert second.scored[0].outcome == ta.LOSS  # re-graded, not frozen


# ===========================================================================
# F4 -- collision-safe state keys + score-at-maturity
# ===========================================================================
# The maturity horizon for a rec 48h ago with maturity 24h is 24h before NOW;
# an at-maturity historical key is therefore hist_key(coin, 24).

def test_same_second_collision_no_longer_collides():
    """Two records sharing the SAME id but a different coin get DISTINCT state
    keys, so one no longer inherits the other's frozen verdict (the old id-only
    key collided). (F4 (a))"""
    r_win = rec('dup', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    r_loss = rec('dup', 'FOO', 'BUY', price=100.0, hours_ago=48)  # same id!
    p = provider(current={'DOGE': 0.20, 'FOO': 100.5, BTC: 60000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    state = {}
    res = ta.analyze([r_win, r_loss], NOW, 24, 2.4, BTC, p, [], state)
    assert ta.state_key(r_win) != ta.state_key(r_loss)
    assert len(state) == 2
    by_coin = {s.coin: s for s in res.scored}
    # DOGE +100% -> WIN; FOO +0.5% (< 2.4% fees) -> LOSS. Under the OLD id-only
    # key the second 'dup' would have inherited the first's WIN.
    assert by_coin['DOGE'].outcome == ta.WIN
    assert by_coin['FOO'].outcome == ta.LOSS


def test_state_key_depends_on_all_identifying_fields():
    base = rec('x', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    assert ta.state_key(base) == ta.state_key(dict(base))          # stable
    assert ta.state_key(base) != ta.state_key(rec('x', 'DOGE', 'SELL', hours_ago=48))
    assert ta.state_key(base) != ta.state_key(rec('x', 'PEPE', 'BUY', hours_ago=48))
    assert ta.state_key(base) != ta.state_key(rec('y', 'DOGE', 'BUY', hours_ago=48))


def test_scored_at_maturity_uses_maturity_prices():
    """When coin AND benchmark maturity candles are available, the grade uses
    the maturity-horizon prices (not run-time) and is flagged at_maturity. (F4 (b))"""
    r = rec('m1', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p = provider(
        current={'DOGE': 999.0, BTC: 999999.0},        # run-time -- must be IGNORED
        historical={
            hist_key(BTC, 48): 60000.0,                # benchmark at rec_time
            hist_key('DOGE', 24): 0.12,                # coin at maturity (+20%)
            hist_key(BTC, 24): 60600.0,                # benchmark at maturity (+1%)
        })
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.SCORED
    assert s.methodology == ta.AT_MATURITY
    assert s.coin_return_pct == pytest.approx(20.0)    # from maturity 0.12, not 999
    assert s.benchmark_return_pct == pytest.approx((60600 - 60000) / 60000 * 100)
    assert s.current_price == pytest.approx(0.12)      # endpoint is the maturity price
    assert s.outcome == ta.WIN                         # 20 - 1 - 2.4 > 0


def test_missing_maturity_candle_degrades_to_run_time():
    """If a needed maturity candle is unreachable, BOTH endpoints degrade to
    run-time (never mixed) and the record is flagged scored_at_run_time. (F4 (b))"""
    r = rec('m2', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p = provider(
        current={'DOGE': 0.12, BTC: 61000.0},          # used on degrade
        historical={
            hist_key(BTC, 48): 60000.0,                # benchmark at rec_time
            hist_key('DOGE', 24): 0.50,                # coin maturity present...
            # ...but NO hist_key(BTC, 24) -> benchmark maturity unreachable
        })
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.category == ta.SCORED
    assert s.methodology == ta.AT_RUN_TIME
    # Degraded: current DOGE 0.12 (+20%) and current BTC 61000 (+1.667%),
    # NOT the coin maturity 0.50 -- methodologies are never mixed.
    assert s.coin_return_pct == pytest.approx(20.0)
    assert s.benchmark_return_pct == pytest.approx((61000 - 60000) / 60000 * 100)
    assert s.outcome == ta.WIN


def test_benchmark_coin_scored_at_maturity():
    """A BUY on BTC itself scores at maturity when the BTC maturity candle is
    present (benchmark return := 0)."""
    r = rec('m3', 'BTC', 'BUY', price=60000.0, hours_ago=48)
    p = provider(current={BTC: 999999.0},
                 historical={hist_key(BTC, 24): 63000.0})  # BTC at maturity +5%
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.methodology == ta.AT_MATURITY
    assert s.benchmark_return_pct == 0.0
    assert s.coin_return_pct == pytest.approx(5.0)     # from maturity 63000
    assert s.outcome == ta.WIN


def test_existing_scored_records_stay_run_time_when_only_current_prices():
    """Back-compat: with only run-time current prices (the existing test
    fixtures' shape), scoring degrades to run-time and matches the old numbers."""
    r = rec('bc1', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p = provider(current={'DOGE': 0.12, BTC: 61000.0},
                 historical={hist_key(BTC, 48): 60000.0})
    s = ta.score_record(r, NOW, 24, 2.4, BTC, p, [], {})
    assert s.methodology == ta.AT_RUN_TIME
    assert s.outcome == ta.WIN


def test_state_version_mismatch_is_discarded_and_regenerated(tmp_path):
    """A v1-style state file (no 'version', id-keyed) is discarded on load and
    regenerated (derived data); a current-version file round-trips. (F4 (a))"""
    path = tmp_path / 'analyzer_state.json'
    path.write_text(json.dumps({'scored': {'oldid': {'outcome': 'WIN'}}}))
    assert ta.load_state(str(path)) == {}     # v1 discarded
    key = ta.state_key(rec('x', 'DOGE', 'BUY'))
    ta.save_state(str(path), {key: {'outcome': 'WIN'}})
    reloaded = ta.load_state(str(path))
    assert reloaded == {key: {'outcome': 'WIN'}}   # v2 round-trips
    # And the file carries the version marker.
    assert json.loads(path.read_text())['version'] == ta.STATE_VERSION


def test_methodology_frozen_across_reruns():
    """The methodology flag is persisted and restored on a frozen re-score."""
    r = rec('fm1', 'DOGE', 'BUY', price=0.10, hours_ago=48)
    p = provider(
        current={'DOGE': 999.0, BTC: 999999.0},
        historical={hist_key(BTC, 48): 60000.0,
                    hist_key('DOGE', 24): 0.12, hist_key(BTC, 24): 60600.0})
    state = {}
    first = ta.analyze([r], NOW, 24, 2.4, BTC, p, [], state)
    assert first.scored[0].methodology == ta.AT_MATURITY
    second = ta.analyze([r], NOW, 24, 2.4, BTC, provider(), [], state)
    assert second.scored[0].frozen is True
    assert second.scored[0].methodology == ta.AT_MATURITY


# ===========================================================================
# timing_preview + startup summary (price-free, non-fatal)
# ===========================================================================
def test_timing_preview_counts():
    p = ta.timing_preview(_mixed_records(), NOW, 24)
    assert p['total'] == 9
    assert p['non_trading'] == 1
    assert p['blocked'] == 1
    assert p['unknown'] == 1
    assert p['pending_directional'] == 1
    assert p['hold'] == 1
    assert p['live'] + p['whatif'] == 6  # live+whatif trading records (excl. blocked? no)


def test_startup_summary_non_fatal_on_missing_dir(capsys):
    # Must never raise, even for a nonexistent dir.
    ta.run_startup_summary(history_dir='/nonexistent/path/xyz')
    out = capsys.readouterr().out
    assert 'ANALYZER' in out


# ===========================================================================
# CLI smoke test against a synthetic history in tmp_path
# ===========================================================================
def test_cli_offline_run(tmp_path, capsys):
    (tmp_path / 'recommendations.json').write_text(json.dumps({'recommendations': [
        rec('live_buy', 'DOGE', 'BUY', price=0.10, hours_ago=48, mode='live'),
        rec('blocked', 'LTC', 'NONE', hours_ago=48, mode='live',
            block_reason='disagreement', consensus_state='blocked'),
    ]}))
    code = ta.cli_main([
        '--history-dir', str(tmp_path),
        '--offline',  # NullPriceProvider -> no network
        '--now', NOW.isoformat(),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert 'RECORD ACCOUNTING' in out
    assert 'PANEL BEHAVIOR' in out
    # state file written
    assert (tmp_path / 'analyzer_state.json').exists()


# ===========================================================================
# DI-1 -- timezone-independent epoch conversion (utc_epoch + price_at)
#
# History timestamps are stored naive-UTC; `.timestamp()` on a naive datetime
# reads it as LOCAL time (a real past 4-hour bug -- AGENTS.md:23). These tests
# pin that utc_epoch (and price_at, which uses it) produce identical results
# regardless of the machine's $TZ.
# ===========================================================================
@pytest.fixture
def tz_guard():
    """Save/restore $TZ around a test that mutates it.

    We set os.environ['TZ'] + time.tzset() inside the test and restore both in
    teardown. Per the house rule we NEVER setattr the stdlib `time` module (a
    process-global singleton); we only drive it through the documented
    os.environ + tzset() path.
    """
    old = os.environ.get('TZ')
    yield
    if old is None:
        os.environ.pop('TZ', None)
    else:
        os.environ['TZ'] = old
    time.tzset()


def _cb_provider(monkeypatch, candles_by_product=None, fetch=None):
    """A CoinbasePriceProvider wired to synthetic candles (no network).

    Built via __new__ so __init__ (which imports BlobbyTrader / hits Coinbase
    credentials) never runs; _client is a non-None sentinel so price_at proceeds,
    and marketdata.fetch_candles is monkeypatched to return canned rows.
    """
    import marketdata
    if fetch is None:
        candles_by_product = candles_by_product or {}
        def fetch(client, product, days=None, granularity=None):  # noqa: ANN001
            return candles_by_product.get(product, [])
    monkeypatch.setattr(marketdata, 'fetch_candles', fetch)
    prov = ta.CoinbasePriceProvider.__new__(ta.CoinbasePriceProvider)
    prov._client = object()          # non-None sentinel -> price_at runs
    prov._trader = None
    prov._candle_cache = {}
    return prov


def test_utc_epoch_treats_naive_as_utc():
    dt = datetime(2026, 4, 10, 19, 48, 6, 600002)
    # The corrected epoch is the UTC interpretation, not the local one.
    assert ta.utc_epoch(dt) == pytest.approx(dt.replace(tzinfo=timezone.utc).timestamp())


def test_utc_epoch_honors_aware_datetime():
    aware = datetime(2026, 4, 10, 19, 48, 6, tzinfo=timezone.utc)
    assert ta.utc_epoch(aware) == pytest.approx(aware.timestamp())


def test_utc_epoch_identical_under_utc_and_new_york(tz_guard):
    dt = datetime(2026, 4, 10, 19, 48, 6, 600002)
    os.environ['TZ'] = 'UTC'
    time.tzset()
    under_utc = ta.utc_epoch(dt)
    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    under_ny = ta.utc_epoch(dt)
    # TZ-independent by construction of the fix.
    assert under_utc == under_ny
    # And under New_York the buggy naive interpretation really diverges (proving
    # the bug this fix closes exists), by the ~4-5h EDT/EST offset.
    assert dt.timestamp() != pytest.approx(under_ny)


def test_price_at_is_tz_independent(monkeypatch, tz_guard):
    when = datetime(2026, 1, 1, 12, 0, 0)         # far past -> ONE_DAY granularity
    target = ta.utc_epoch(when)
    rows = [
        {'time': target, 'close': 100.0},          # the correct UTC candle
        {'time': target + 5 * 3600, 'close': 200.0},  # +5h: what a local-time lookup nears
    ]
    os.environ['TZ'] = 'UTC'
    time.tzset()
    prov_utc = _cb_provider(monkeypatch, {'DOGE-USD': rows})
    under_utc = prov_utc.price_at('DOGE', when)

    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    prov_ny = _cb_provider(monkeypatch, {'DOGE-USD': rows})
    under_ny = prov_ny.price_at('DOGE', when)

    # Same candle chosen under both zones -- and it's the correct 100.0, not the
    # +5h 200.0 that the naive-`.timestamp()` bug would have picked under NY.
    assert under_utc == under_ny == 100.0


# ===========================================================================
# DI-2 -- cache-key span isolation + nearest-candle distance guard
# ===========================================================================
def test_price_at_cache_key_isolates_lookback_span(monkeypatch):
    """Same coin+granularity, different lookback spans -> distinct cache keys, so
    one span's candles never contaminate the other; a repeat of the same span is
    served from cache (no re-fetch)."""
    calls = []

    def fetch(client, product, days=None, granularity=None):  # noqa: ANN001
        calls.append(days)
        return []  # content irrelevant here; we assert on fetch behavior

    prov = _cb_provider(monkeypatch, fetch=fetch)
    when_recent = datetime(2026, 6, 1, 12, 0, 0)   # ~short span, ONE_DAY
    when_old = datetime(2026, 1, 1, 12, 0, 0)      # ~long span, ONE_DAY

    prov.price_at('DOGE', when_recent)
    prov.price_at('DOGE', when_old)
    # Different lookback spans -> two distinct cache keys -> two fetches.
    assert len(calls) == 2
    assert calls[0] != calls[1]                    # the day-spans really differ
    # Same coin+span again -> served from cache, no third fetch.
    prov.price_at('DOGE', when_recent)
    assert len(calls) == 2


def test_price_at_distance_guard_returns_none_when_nearest_too_far(monkeypatch):
    when = datetime(2026, 1, 1, 12, 0, 0)          # far past -> ONE_DAY (86400s)
    target = ta.utc_epoch(when)
    # Nearest candle is 3 days off -> beyond 1.5x the ONE_DAY granularity.
    far = [{'time': target + 3 * 86400, 'close': 123.0}]
    prov = _cb_provider(monkeypatch, {'DOGE-USD': far})
    assert prov.price_at('DOGE', when) is None


def test_price_at_returns_close_when_within_distance_guard(monkeypatch):
    when = datetime(2026, 1, 1, 12, 0, 0)          # ONE_DAY granularity
    target = ta.utc_epoch(when)
    near = [{'time': target + 3600, 'close': 123.0}]  # 1h off, well within 1.5 days
    prov = _cb_provider(monkeypatch, {'DOGE-USD': near})
    assert prov.price_at('DOGE', when) == 123.0


def test_distance_guard_degrades_record_honestly_not_at_maturity(monkeypatch):
    """End-to-end: when the maturity candle is beyond the distance guard,
    price_at returns None, so score_record must NOT stamp AT_MATURITY -- it
    degrades to run-time (or, absent a run-time price, EXPIRED_UNSCORABLE)."""
    when = datetime(2026, 1, 1, 12, 0, 0)
    maturity = when + timedelta(hours=24)
    mtarget = ta.utc_epoch(maturity)
    # Only far-off candles exist for both coin and benchmark -> guard trips.
    far_coin = [{'time': mtarget + 5 * 86400, 'close': 0.50}]
    far_bench = [{'time': mtarget + 5 * 86400, 'close': 70000.0}]
    prov = _cb_provider(monkeypatch,
                        {'DOGE-USD': far_coin, 'BTC-USD': far_bench})
    # No run-time price either (trader is None, and no network reachable).
    monkeypatch.setattr(ta, 'get_current_price', lambda *a, **k: None)

    r = rec('dg1', 'DOGE', 'BUY', price=0.10)
    r['timestamp'] = when.isoformat() + 'Z'
    s = ta.score_record(r, when + timedelta(hours=48), 24, 2.4, BTC, prov, [], {})
    assert s.category == ta.EXPIRED_UNSCORABLE      # honest degradation
    assert s.methodology != ta.AT_MATURITY          # never falsely stamped at-maturity


# ===========================================================================
# DI-1 -- STATE_VERSION bump so frozen (wrong) verdicts re-score once
# ===========================================================================
def test_state_version_bumped_and_prior_version_discarded(tmp_path):
    """STATE_VERSION is 4 (WS3 added hold_class to the frozen shape), and any
    prior-version state file is discarded on load -- forcing the naive-timestamp-era
    (v2) and hold_class-less (v3) frozen verdicts to be re-scored once."""
    assert ta.STATE_VERSION == 4
    path = tmp_path / 'analyzer_state.json'
    key = ta.state_key(rec('x', 'DOGE', 'BUY'))
    # Prior formats (v2 DI-1-era, v3 pre-hold_class) must be discarded.
    for stale in (2, 3):
        path.write_text(json.dumps({'version': stale, 'scored': {key: {'outcome': 'WIN'}}}))
        assert ta.load_state(str(path)) == {}
    # A current-version file still round-trips.
    ta.save_state(str(path), {key: {'outcome': 'WIN'}})
    assert ta.load_state(str(path)) == {key: {'outcome': 'WIN'}}
    assert json.loads(path.read_text())['version'] == 4
