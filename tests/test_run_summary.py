"""Tests for the two RUN SUMMARY additions (operator visibility gap):

  1. The daily LIVE spend cap state, reusing the SAME startup-banner helper
     (format_daily_cap_banner_line) rather than a second implementation --
     called again at summary time so a run that placed fills shows the
     POST-run figure (the ledger may have gained fills during the run).
  2. A compact per-coin vote outcome table, e.g.:
       Votes: BTC HOLD | ETH HOLD | SOL HOLD | DOGE BUY->ordered | LINK HOLD
     built from coin_vote_outcomes, a list of (coin_symbol, label) pairs
     appended once per coin -- in both the coin-choice and discovery loops --
     right after the trade gate runs (gate_and_maybe_buy's return value is
     the 'ordered' vs 'gate-blocked' signal for a BUY).

Pattern mirrors tests/test_daily_cap_banner.py (pure formatter, scratch
ledger, no network / no LLM / no orders) and tests/test_trade_gate.py
(gate_and_maybe_buy wired through monkeypatched module globals -- these
globals don't exist as module attributes until main() runs, hence
raising=False).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import executionledger as led


# ============================================================================
# Fixtures (same shape as test_trade_gate.py's buy_calls / scratch_ledger)
# ============================================================================

@pytest.fixture
def scratch_ledger(tmp_path, monkeypatch):
    """Redirect the execution ledger to a scratch file so no test touches
    ./history/ (same pattern as test_daily_cap_banner.py / test_trade_gate.py)."""
    f = tmp_path / 'executions.json'
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(f))
    return f


@pytest.fixture
def buy_calls(monkeypatch, scratch_ledger):
    """Standard bot-global environment (LIVE mode, caps open) with
    buy_something stubbed, so gate_and_maybe_buy can be driven end-to-end
    without placing a real order."""
    monkeypatch.setattr(bot, 'LLM_MODE', 'compare', raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', True, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'live', raising=False)
    monkeypatch.setattr(bot, 'WHATIF_MODE', False, raising=False)
    monkeypatch.setattr(bot, 'NOTIONAL_USD', 5.0, raising=False)
    monkeypatch.setattr(bot, 'DAILY_SPEND_CAP_USD', 15.0, raising=False)
    monkeypatch.setattr(bot, 'spend_tracker', bot.SpendTracker(10.0, 5.0), raising=False)
    monkeypatch.setattr(bot, 'coinsToBuy', [], raising=False)
    monkeypatch.setattr(bot, 'coinsExcluded', [], raising=False)
    monkeypatch.setattr(bot, 'coinsToExclude', set(), raising=False)
    monkeypatch.setattr(bot, 'whatif_buys', 0, raising=False)
    monkeypatch.setattr(bot, 'daily_cap_blocked', 0, raising=False)
    calls = []
    monkeypatch.setattr(bot, 'buy_something', lambda coin: calls.append(coin),
                        raising=False)
    return calls


def _decision(action, state='unanimous', block_reason=None):
    return bot.PanelDecision(action=action, consensus_state=state,
                             block_reason=block_reason)


# ============================================================================
# 1. Daily-cap line: reused helper, and reflects fills gained DURING the run
# ============================================================================

def test_daily_cap_line_reflects_fills_committed_during_the_run(scratch_ledger):
    """The summary calls format_daily_cap_banner_line() fresh (not a cached
    startup-banner string), so a fill recorded mid-run shows up in the
    summary's line -- this is the whole point of calling it again rather
    than reusing the banner's rendered text."""
    banner_line = bot.format_daily_cap_banner_line(15.0, '--daily-spend-cap-usd')
    assert '$0.00 spent today [UTC]' in banner_line

    # A buy lands during the run (e.g. via gate_and_maybe_buy -> buy_something
    # -> executionledger.append_intent in the real flow); simulate the ledger
    # write directly, same as test_daily_cap_banner.py's seeding pattern.
    led.append_intent(run_id='r0', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c0')

    summary_line = bot.format_daily_cap_banner_line(15.0, '--daily-spend-cap-usd')
    assert '$5.00 spent today [UTC]' in summary_line
    assert summary_line != banner_line


def test_daily_cap_line_is_the_reused_helper_not_a_reimplementation():
    """Sanity pin: the exact string shape the summary prints is produced by
    format_daily_cap_banner_line (see tests/test_daily_cap_banner.py for the
    full spec of this helper) -- guards against a future edit reimplementing
    the line inline in main() instead of calling the shared helper."""
    line = bot.format_daily_cap_banner_line(15.0, 'default')
    assert line.startswith('Daily spend cap: $15.00 (')
    assert line.endswith('[default]')


# ============================================================================
# 2. Vote outcome label + line formatting
# ============================================================================

def test_vote_outcome_label_hold_and_sell_render_as_is():
    assert bot.vote_outcome_label('HOLD', dispatched=False) == 'HOLD'
    assert bot.vote_outcome_label('SELL', dispatched=False) == 'SELL'


def test_vote_outcome_label_buy_ordered():
    assert bot.vote_outcome_label('BUY', dispatched=True) == 'BUY->ordered'


def test_vote_outcome_label_buy_gate_blocked():
    """A BUY the trade gate declined (e.g. REQUIRE_CONSENSUS + tiebreaker
    state) must not look identical to an ordered one."""
    assert bot.vote_outcome_label('BUY', dispatched=False) == 'BUY->gate-blocked'


def test_vote_outcome_label_blocked_decision():
    assert bot.vote_outcome_label(None, dispatched=False) == 'BLOCKED'


def test_format_vote_outcomes_line_empty_outcomes_is_blank():
    """No coins analyzed (edge case) -> caller skips the line entirely
    rather than printing a bare 'Votes:'."""
    assert bot.format_vote_outcomes_line([]) == ''


def test_format_vote_outcomes_line_renders_from_populated_outcomes():
    outcomes = [
        ('BTC', 'HOLD'),
        ('ETH', 'HOLD'),
        ('SOL', 'HOLD'),
        ('DOGE', 'BUY->ordered'),
        ('LINK', 'HOLD'),
    ]
    line = bot.format_vote_outcomes_line(outcomes)
    assert line == (
        'Votes: BTC HOLD | ETH HOLD | SOL HOLD | DOGE BUY->ordered | LINK HOLD'
    )


# ============================================================================
# 3. End-to-end wiring: gate_and_maybe_buy's return value drives the label,
#    the same way main()'s two analysis loops use it (TS-2's single tested
#    gate->execute wiring; no second gate implementation for the summary).
# ============================================================================

def test_wiring_approved_buy_yields_ordered_label(buy_calls):
    dec = _decision('BUY')
    dispatched = bot.gate_and_maybe_buy(dec, 'BUY', 'DOGE')
    label = bot.vote_outcome_label('BUY', dispatched)
    assert (('DOGE', label)) == ('DOGE', 'BUY->ordered')
    assert buy_calls == ['DOGE']


def test_wiring_tiebreaker_buy_under_require_consensus_yields_gate_blocked_label(
        buy_calls):
    dec = _decision('BUY', state='tiebreaker')
    dispatched = bot.gate_and_maybe_buy(dec, 'BUY', 'LINK')
    label = bot.vote_outcome_label('BUY', dispatched)
    assert label == 'BUY->gate-blocked'
    assert buy_calls == []


def test_wiring_hold_never_dispatches_and_labels_plain(buy_calls):
    dec = _decision('HOLD')
    dispatched = bot.gate_and_maybe_buy(dec, 'HOLD', 'BTC')
    assert bot.vote_outcome_label('HOLD', dispatched) == 'HOLD'
    assert buy_calls == []


def test_wiring_blocked_decision_labels_blocked(buy_calls):
    dec = _decision(None, state='blocked', block_reason='no_quorum: 1 of 3')
    dispatched = bot.gate_and_maybe_buy(dec, None, 'ETH')
    assert bot.vote_outcome_label(None, dispatched) == 'BLOCKED'
    assert buy_calls == []


# ============================================================================
# WS8a: --json-summary path resolution (pure function, no I/O)
# ============================================================================

def test_resolve_json_summary_path_none_means_disabled():
    """The flag was never given (args.json_summary defaults to None) ->
    summary generation is skipped entirely."""
    assert bot.resolve_json_summary_path(None, 'run_x') is None


def test_resolve_json_summary_path_bare_flag_defaults_under_history_dir(
        monkeypatch, tmp_path):
    """Bare `--json-summary` (argparse const='') resolves to
    <dir-of-RECOMMENDATIONS_FILE>/run_summaries/<run_id>.json -- the same
    dir-resolution write_market_blocks uses for market_blocks/, so a
    redirected/scratch HISTORY_DIR is respected."""
    import historyutil
    monkeypatch.setattr(
        historyutil, 'RECOMMENDATIONS_FILE',
        str(tmp_path / 'recommendations.json'), raising=False)
    path = bot.resolve_json_summary_path('', 'run_20260721T000000Z_test01')
    assert path == str(
        tmp_path / 'run_summaries' / 'run_20260721T000000Z_test01.json')


def test_resolve_json_summary_path_explicit_path_used_verbatim():
    assert bot.resolve_json_summary_path('/tmp/custom/summary.json', 'run_x') \
        == '/tmp/custom/summary.json'


# ============================================================================
# WS8b: build_run_summary -- pure, reuses in-memory run state
# ============================================================================

def _build_summary(**overrides):
    kwargs = dict(
        run_id='run_20260721T000000Z_test01',
        trading_mode='whatif',
        llm_mode='compare',
        primary_llm='gemini',
        compare_llms=['gemini', 'claude'],
        use_coin_discovery=False,
        discovery_methods=['llm'],
        analyze_coins=['BTC', 'ETH'],
        coins_to_buy=['BTC'],
        coins_excluded=['TRUMP'],
        coin_vote_outcomes=[('BTC', 'BUY->ordered'), ('ETH', 'HOLD'),
                            ('TRUMP', 'BUY->ordered')],
        spend_tracker=bot.SpendTracker(10.0, 5.0),
        daily_spend_cap_usd=15.0,
        daily_cap_blocked=0,
        whatif_mode=True,
        whatif_buys=1,
    )
    kwargs.update(overrides)
    return bot.build_run_summary(**kwargs)


def test_build_run_summary_shape_and_content():
    summary = _build_summary()
    assert summary['run_id'] == 'run_20260721T000000Z_test01'
    assert summary['trading_mode'] == 'whatif'
    assert summary['panel'] == {
        'llm_mode': 'compare', 'primary_llm': 'gemini',
        'compare_llms': ['gemini', 'claude'],
    }
    assert summary['discovery']['use_coin_discovery'] is False
    assert summary['discovery']['analyze_coins'] == ['BTC', 'ETH']
    assert summary['discovery']['discovery_methods'] == []  # inert in coin-choice mode
    coins = {c['coin']: c for c in summary['coins']}
    assert coins['BTC'] == {'coin': 'BTC', 'outcome': 'BUY->ordered',
                            'bought': True, 'excluded': False}
    assert coins['TRUMP'] == {'coin': 'TRUMP', 'outcome': 'BUY->ordered',
                              'bought': False, 'excluded': True}
    assert summary['spend']['committed_usd'] == 0.0
    assert summary['spend']['run_spend_cap_usd'] == 10.0
    assert summary['spend']['daily_spend_cap_usd'] == 15.0
    assert summary['orders'] == {'live_buys': 0, 'simulated_buys': 1}
    # ISO 8601 UTC timestamp, parseable
    import datetime
    datetime.datetime.fromisoformat(summary['timestamp'])


def test_build_run_summary_discovery_mode_reports_methods_not_coins():
    summary = _build_summary(use_coin_discovery=True, discovery_methods=['llm', 'santiment'])
    assert summary['discovery']['discovery_methods'] == ['llm', 'santiment']
    assert summary['discovery']['analyze_coins'] == []


def test_build_run_summary_live_mode_counts_live_not_simulated_buys():
    summary = _build_summary(whatif_mode=False, whatif_buys=0,
                             coins_to_buy=['BTC', 'ETH'])
    assert summary['orders'] == {'live_buys': 2, 'simulated_buys': 0}


# ============================================================================
# WS8c: write_run_summary -- atomic write, best-effort (never raises)
# ============================================================================

def test_write_run_summary_writes_valid_json(tmp_path):
    path = str(tmp_path / 'run_summaries' / 'r1.json')
    summary = {'run_id': 'r1', 'coins': []}
    result = bot.write_run_summary(path, summary)
    assert result == path
    with open(path) as f:
        assert json.load(f) == summary


def test_write_run_summary_never_raises_on_failure(tmp_path):
    """A write failure (parent path component is a FILE, not a directory) is
    caught, warned, and returns None -- writing the summary must never be
    able to abort a trading run."""
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory')
    bad_path = str(blocker / 'sub' / 'r1.json')
    result = bot.write_run_summary(bad_path, {'run_id': 'r1'})
    assert result is None


# ============================================================================
# WS8d: --quiet suppresses product-detail dumps, never safety lines
# ============================================================================

def test_quiet_mode_suppresses_product_json_dumps(scratch_ledger, monkeypatch):
    """Real buy_something whatif path (same fixture as
    tests/test_trade_gate.py::test_whatif_simulated_fill_records_estimated_fees)
    with QUIET_MODE on: the product-detail JSON dump and progress header must
    not appear on stdout."""
    class FakeProduct:
        price = '100.0'

        def to_dict(self):
            return {'price': '100.0'}

    class FakeTrader:
        def get_product_details(self, product_id):
            return FakeProduct()

    monkeypatch.setattr(bot, 'trader', FakeTrader(), raising=False)
    monkeypatch.setattr(bot, 'WHATIF_MODE', True, raising=False)
    monkeypatch.setattr(bot, 'DEX_MODE', False, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'whatif', raising=False)
    monkeypatch.setattr(bot, 'NOTIONAL_USD', 5.0, raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_20260721T000000Z_test02', raising=False)
    monkeypatch.setattr(bot, 'QUIET_MODE', True, raising=False)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bot.buy_something('BTC')
    out = buf.getvalue()
    assert 'Getting coin Product Details' not in out
    assert '"price": "100.0"' not in out


def test_quiet_mode_does_not_suppress_product_dumps_by_default(
        scratch_ledger, monkeypatch):
    """Sanity pin: without --quiet (QUIET_MODE False, the module default),
    the product-detail dump is unchanged from before WS8."""
    class FakeProduct:
        price = '100.0'

        def to_dict(self):
            return {'price': '100.0'}

    class FakeTrader:
        def get_product_details(self, product_id):
            return FakeProduct()

    monkeypatch.setattr(bot, 'trader', FakeTrader(), raising=False)
    monkeypatch.setattr(bot, 'WHATIF_MODE', True, raising=False)
    monkeypatch.setattr(bot, 'DEX_MODE', False, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'whatif', raising=False)
    monkeypatch.setattr(bot, 'NOTIONAL_USD', 5.0, raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_20260721T000000Z_test03', raising=False)
    monkeypatch.setattr(bot, 'QUIET_MODE', False, raising=False)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bot.buy_something('BTC')
    out = buf.getvalue()
    assert 'Getting coin Product Details' in out
    assert '"price": "100.0"' in out


def test_quiet_mode_never_suppresses_exclusion_safety_line(monkeypatch):
    """[EXCLUDED] is a safety line (must survive --quiet). maybe_execute_buy
    prints it unconditionally regardless of QUIET_MODE -- this pins that the
    quiet gate was never applied to it."""
    monkeypatch.setattr(bot, 'coinsToExclude', {'TRUMP'}, raising=False)
    monkeypatch.setattr(bot, 'coinsExcluded', [], raising=False)
    monkeypatch.setattr(bot, 'QUIET_MODE', True, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'whatif', raising=False)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bot.maybe_execute_buy('TRUMP')
    assert '[EXCLUDED]' in buf.getvalue()
