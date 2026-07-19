"""Tests for the gate->execute assembly (TS-2, audit 2026-07-19).

Before this file existed, maybe_execute_buy (daily cap -> run cap ->
exclusion -> dispatch) was referenced by NO test, and the gate wiring
`decision_allows_trade(...) and 'BUY' in final_action: maybe_execute_buy(...)`
was duplicated verbatim at the two analysis-loop call sites -- an agent could
reorder the cap checks or break one call site with the whole suite green.
Now both live in tested module-level functions:

  * gate_and_maybe_buy(decision, final_action, coin_symbol) -- the ONE wiring
    used by the coin-choice and discovery loops;
  * maybe_execute_buy(coin_symbol) -- caps + exclusion + dispatch.

Covered here (the leaf logic -- consensus math, ledger sums -- is spec'd
elsewhere; this file pins the ASSEMBLY):
  1. An approved BUY dispatches to buy_something exactly once.
  2. A blocked decision never dispatches.
  3. A non-BUY action (HOLD) never dispatches.
  4. A gate-approved SELL never dispatches and prints [NO SELL PATH] (MP-7).
  5. A daily-cap refusal refuses (no dispatch, no run-cap commit).
  6. A run-cap refusal refuses (no dispatch).
  7. An excluded coin is excluded (no dispatch).

Pattern: monkeypatched module globals (see tests/test_consensus.py
_patch_globals) with buy_something stubbed -- no network, no orders, ledger
redirected to a scratch file.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import executionledger as led


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def scratch_ledger(tmp_path, monkeypatch):
    """Redirect the execution ledger (and its lock/backup siblings) to a
    scratch file so no test ever touches ./history/."""
    f = tmp_path / 'executions.json'
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(f))
    return f


@pytest.fixture
def buy_calls(monkeypatch, scratch_ledger):
    """Standard bot-global environment (LIVE mode, caps open) with
    buy_something stubbed. Returns the list of dispatched coins.

    maybe_execute_buy reads these module globals at call time; none exist as
    module attributes until main() runs, hence raising=False (the
    test_consensus.py pattern)."""
    monkeypatch.setattr(bot, 'LLM_MODE', 'compare', raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', True, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'live', raising=False)
    monkeypatch.setattr(bot, 'WHATIF_MODE', False, raising=False)
    monkeypatch.setattr(bot, 'NOTIONAL_USD', 5.0, raising=False)
    monkeypatch.setattr(bot, 'DAILY_SPEND_CAP_USD', 15.0, raising=False)
    monkeypatch.setattr(bot, 'spend_tracker', bot.SpendTracker(10.0, 5.0), raising=False)
    monkeypatch.setattr(bot, 'coinsToBuy', [], raising=False)
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
# 1-4. gate_and_maybe_buy: gate semantics + exactly-once dispatch
# ============================================================================

def test_approved_buy_dispatches_exactly_once(buy_calls):
    dispatched = bot.gate_and_maybe_buy(_decision('BUY'), 'BUY', 'ETH')
    assert dispatched is True
    assert buy_calls == ['ETH']          # exactly once, right coin


def test_blocked_decision_never_dispatches(buy_calls):
    dec = _decision(None, state='blocked', block_reason='no_quorum: 1 of 3')
    dispatched = bot.gate_and_maybe_buy(dec, None, 'ETH')
    assert dispatched is False
    assert buy_calls == []


def test_blocked_decision_with_buy_text_never_dispatches(buy_calls):
    """Even if a blocked decision somehow carried a BUY action string, the
    mode-aware gate (consensus_state == 'blocked') must refuse it."""
    dec = _decision('BUY', state='blocked', block_reason='abstain: openai')
    assert bot.gate_and_maybe_buy(dec, 'BUY', 'ETH') is False
    assert buy_calls == []


def test_non_buy_action_never_dispatches(buy_calls):
    assert bot.gate_and_maybe_buy(_decision('HOLD'), 'HOLD', 'ETH') is False
    assert buy_calls == []


def test_gate_approved_sell_prints_no_sell_path_and_never_dispatches(
        buy_calls, capsys):
    """MP-7 interim: a consensus SELL the gate would allow has no execution
    path today -- it must be loudly logged, never silently dropped, and never
    dispatched."""
    assert bot.gate_and_maybe_buy(_decision('SELL'), 'SELL', 'ETH') is False
    assert buy_calls == []
    out = capsys.readouterr().out
    assert '[NO SELL PATH]' in out
    assert 'ETH' in out


def test_gate_uses_mode_aware_trade_gate_not_bare_substring(buy_calls, monkeypatch):
    """Under REQUIRE_CONSENSUS a tiebreaker-resolved BUY must NOT trade --
    proves the extracted wiring still routes through decision_allows_trade."""
    dec = _decision('BUY', state='tiebreaker')
    assert bot.gate_and_maybe_buy(dec, 'BUY', 'ETH') is False
    assert buy_calls == []
    # ...and with REQUIRE_CONSENSUS off, the same decision may trade.
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', False, raising=False)
    assert bot.gate_and_maybe_buy(dec, 'BUY', 'ETH') is True
    assert buy_calls == ['ETH']


def test_single_llm_mode_buy_dispatches(buy_calls, monkeypatch):
    monkeypatch.setattr(bot, 'LLM_MODE', 'gemini', raising=False)
    dec = _decision('BUY', state='single')
    assert bot.gate_and_maybe_buy(dec, 'BUY', 'DOGE') is True
    assert buy_calls == ['DOGE']


# ============================================================================
# 5. Daily-cap refusal refuses (live)
# ============================================================================

def test_daily_cap_refusal_refuses_and_commits_nothing(buy_calls, monkeypatch, capsys):
    """A live buy that would push today's LIVE spend past the daily cap is
    refused BEFORE the run cap is touched and never dispatches."""
    monkeypatch.setattr(bot, 'DAILY_SPEND_CAP_USD', 0.0, raising=False)
    assert bot.gate_and_maybe_buy(_decision('BUY'), 'BUY', 'ETH') is True  # dispatched to maybe_execute_buy...
    assert buy_calls == []                                   # ...which refused it
    assert bot.spend_tracker.spent == 0.0                    # no run-cap commit
    assert '[DAILY CAP]' in capsys.readouterr().out


def test_daily_cap_counts_todays_live_intents(buy_calls, scratch_ledger, capsys):
    """The refusal is driven by the ledger's live intent rows for today."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    led.append_intent(run_id='r0', trading_mode='live', coin='SOL',
                      intended_notional_usd=12.0, client_order_id='c0',
                      timestamp=f'{today}T01:00:00Z')
    # 12 committed today, cap 15, notional 5 -> 17 > 15 -> refuse.
    bot.maybe_execute_buy('ETH')
    assert buy_calls == []
    assert '[DAILY CAP]' in capsys.readouterr().out


# ============================================================================
# 6. Run-cap refusal refuses
# ============================================================================

def test_run_cap_refusal_refuses(buy_calls, monkeypatch, capsys):
    monkeypatch.setattr(bot, 'spend_tracker', bot.SpendTracker(4.0, 5.0),
                        raising=False)   # cap below one notional
    bot.maybe_execute_buy('ETH')
    assert buy_calls == []
    assert bot.spend_tracker.blocked == 1
    assert '[SPEND CAP]' in capsys.readouterr().out


def test_run_cap_allows_exact_boundary_then_refuses_next(buy_calls, monkeypatch):
    monkeypatch.setattr(bot, 'spend_tracker', bot.SpendTracker(5.0, 5.0),
                        raising=False)
    bot.maybe_execute_buy('ETH')       # lands exactly on the cap -> allowed
    bot.maybe_execute_buy('DOGE')      # would exceed -> refused
    assert buy_calls == ['ETH']


# ============================================================================
# 7. Exclusion excludes
# ============================================================================

def test_excluded_coin_never_dispatches(buy_calls, monkeypatch, capsys):
    monkeypatch.setattr(bot, 'coinsToExclude', {'TRUMP'}, raising=False)
    bot.maybe_execute_buy('TRUMP')
    assert buy_calls == []
    assert '[EXCLUDED]' in capsys.readouterr().out


def test_non_excluded_coin_still_dispatches(buy_calls, monkeypatch):
    monkeypatch.setattr(bot, 'coinsToExclude', {'TRUMP'}, raising=False)
    bot.maybe_execute_buy('ETH')
    assert buy_calls == ['ETH']


# ============================================================================
# MP-2 + DI-4: corrupt-ledger recovery at the LIVE buy gate, and the whatif
# quarantine-and-continue policy.
# ============================================================================

import json as _json
from datetime import datetime as _dt, timezone as _tz


def _today():
    return _dt.now(_tz.utc).strftime('%Y-%m-%d')


def _snapshot_with_live_spend(scratch_ledger, notional, date_str='2026-01-01'):
    """Write a .bak- snapshot next to the scratch ledger containing one live
    intent row of `notional` USD timestamped TODAY (so it counts against the
    daily cap after restore)."""
    row = {'ledger_id': 'SNAP1', 'run_id': 'r0', 'trading_mode': 'live',
           'coin': 'SOL', 'side': 'BUY', 'intended_notional_usd': notional,
           'client_order_id': 'c0', 'timestamp': f'{_today()}T01:00:00Z',
           'status': 'intent'}
    p = Path(str(scratch_ledger) + f'.bak-{date_str}')
    p.write_text(_json.dumps({'executions': [row]}))
    return p


def test_live_corrupt_ledger_auto_restores_and_buy_proceeds(
        buy_calls, scratch_ledger, capsys):
    """Corrupt ledger + snapshot: quarantine -> auto-restore -> loud
    [LEDGER ERROR] recovered-from-snapshot -> cap re-checked against the
    SNAPSHOT's real spend -> buy proceeds (under cap)."""
    _snapshot_with_live_spend(scratch_ledger, 5.0)   # 5 + 5 = 10 <= cap 15
    scratch_ledger.write_text('{"executions": [')    # corrupt
    bot.maybe_execute_buy('ETH')
    out = capsys.readouterr().out
    assert '[LEDGER ERROR]' in out
    assert 'recovered from snapshot' in out
    assert buy_calls == ['ETH']
    # The corrupt file was preserved (quarantined), never deleted.
    assert list(scratch_ledger.parent.glob('executions.json.corrupt-*'))
    # The restored ledger IS the snapshot's cap data.
    assert led.live_spend_today() == 5.0


def test_live_recovered_cap_equals_snapshot_spend_and_still_refuses(
        buy_calls, scratch_ledger, capsys):
    """The restore must carry the snapshot's REAL spend: with $12 already
    committed today in the snapshot, a $5 buy against the $15 cap is refused
    AFTER recovery -- recovery never resets the cap to $0."""
    _snapshot_with_live_spend(scratch_ledger, 12.0)  # 12 + 5 = 17 > cap 15
    scratch_ledger.write_text('CORRUPT')
    bot.maybe_execute_buy('ETH')
    out = capsys.readouterr().out
    assert 'recovered from snapshot' in out
    assert '[DAILY CAP]' in out
    assert buy_calls == []


def test_live_corrupt_ledger_without_snapshot_refuses_with_recovery_command(
        buy_calls, scratch_ledger, capsys):
    """Fail-closed: no snapshot -> the LIVE buy is refused, and the refusal
    text contains the exact copy-paste recovery command."""
    scratch_ledger.write_text('CORRUPT')
    bot.maybe_execute_buy('ETH')
    out = capsys.readouterr().out
    assert buy_calls == []
    assert 'refusing LIVE BUY' in out
    quarantines = list(scratch_ledger.parent.glob('executions.json.corrupt-*'))
    assert len(quarantines) == 1                      # quarantined, not deleted
    assert f"cp '{quarantines[0]}' '{scratch_ledger}'" in out   # exact command
    assert 'Ledger recovery' in out                   # manual pointer


def test_whatif_corrupt_ledger_quarantines_and_continues(
        buy_calls, scratch_ledger, monkeypatch, capsys):
    """Whatif policy: quarantine-and-continue -- the learning-loop stream
    keeps flowing; the corrupt file is preserved, never silently rewritten."""
    monkeypatch.setattr(bot, 'WHATIF_MODE', True, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'whatif', raising=False)
    scratch_ledger.write_text('CORRUPT')
    bot.maybe_execute_buy('BTC')
    out = capsys.readouterr().out
    assert buy_calls == ['BTC']                       # run continues
    assert '[LEDGER ERROR]' in out
    assert list(scratch_ledger.parent.glob('executions.json.corrupt-*'))
    assert not scratch_ledger.exists()                # renamed aside, not wiped
    assert bot.whatif_buys == 1


# ============================================================================
# MP-1a/b: run-id collision suffix + --coins dedupe (the two cheap duplicate
# triggers: same-second cross-run RUN_ID collisions and '--coins=BTC,ETH,BTC').
# ============================================================================

import re as _re


def test_new_run_id_keeps_timestamp_z_contract_and_adds_suffix():
    rid = bot.new_run_id()
    assert _re.match(r'^run_\d{8}T\d{6}Z_[0-9a-f]{6}$', rid), rid


def test_new_run_id_same_second_runs_do_not_collide():
    from datetime import datetime, timezone
    frozen = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    ids = {bot.new_run_id(now=frozen) for _ in range(20)}
    assert len(ids) == 20                       # suffix differentiates
    assert all(i.startswith('run_20260719T120000Z_') for i in ids)


def test_parse_analyze_coins_dedupes_preserving_order():
    coins, dropped = bot.parse_analyze_coins('BTC,ETH,BTC')
    assert coins == ['BTC', 'ETH']
    assert dropped == 0


def test_parse_analyze_coins_normalizes_and_caps_at_five():
    coins, dropped = bot.parse_analyze_coins(' btc , eth ,sol,doge,ada,xrp ')
    assert coins == ['BTC', 'ETH', 'SOL', 'DOGE', 'ADA']
    assert dropped == 1


def test_parse_analyze_coins_dedupes_before_capping():
    """'A,A,A,A,A,B' used to warn and take five copies of A, silently dropping
    B; dedupe-first keeps both real symbols."""
    coins, dropped = bot.parse_analyze_coins('A,A,A,A,A,B')
    assert coins == ['A', 'B']
    assert dropped == 0


def test_parse_analyze_coins_empty_means_discovery():
    assert bot.parse_analyze_coins('') == ([], 0)


# ============================================================================
# MP-6 + MP-9: whatif honesty -- exclusion first (both modes), whatif daily
# cap (soft-fail), and MP-8's distinct daily-cap counter.
# ============================================================================

def _whatif(monkeypatch):
    monkeypatch.setattr(bot, 'WHATIF_MODE', True, raising=False)
    monkeypatch.setattr(bot, 'TRADING_MODE', 'whatif', raising=False)


def test_exclusion_applies_in_whatif_too(buy_calls, monkeypatch, capsys):
    """MP-6a: whatif used to 'buy' excluded coins live never could."""
    _whatif(monkeypatch)
    monkeypatch.setattr(bot, 'coinsToExclude', {'TRUMP'}, raising=False)
    bot.maybe_execute_buy('TRUMP')
    assert buy_calls == []
    assert bot.whatif_buys == 0
    assert '[EXCLUDED]' in capsys.readouterr().out


def test_exclusion_burns_no_run_cap_budget(buy_calls, monkeypatch):
    """MP-9: the run-cap budget used to be committed BEFORE the exclusion
    check, so an excluded coin silently ate headroom with no order."""
    monkeypatch.setattr(bot, 'coinsToExclude', {'TRUMP'}, raising=False)
    bot.maybe_execute_buy('TRUMP')
    assert bot.spend_tracker.spent == 0.0     # nothing committed
    bot.maybe_execute_buy('ETH')              # headroom fully available
    assert buy_calls == ['ETH']


def test_excluded_coin_still_counted_in_coins_to_buy_summary(buy_calls, monkeypatch):
    monkeypatch.setattr(bot, 'coinsToExclude', {'TRUMP'}, raising=False)
    bot.maybe_execute_buy('TRUMP')
    assert bot.coinsToBuy == ['TRUMP']        # summary shows the intent


def test_whatif_daily_cap_refuses_from_whatif_intents_and_is_labeled(
        buy_calls, scratch_ledger, monkeypatch, capsys):
    """MP-6b: the daily cap now applies in whatif, computed from WHATIF
    intent rows, and the refusal is visibly labeled whatif-simulated."""
    _whatif(monkeypatch)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    led.append_intent(run_id='r0', trading_mode='whatif', coin='SOL',
                      intended_notional_usd=12.0, client_order_id='c0',
                      timestamp=f'{today}T01:00:00Z')
    bot.maybe_execute_buy('ETH')              # 12 + 5 > 15 -> refused
    out = capsys.readouterr().out
    assert buy_calls == []
    assert '[DAILY CAP]' in out
    assert 'whatif-simulated' in out          # honest labeling (MP-6/MP-9)
    assert bot.daily_cap_blocked == 1


def test_whatif_daily_cap_ignores_live_intents(buy_calls, scratch_ledger, monkeypatch):
    """Mode tallies never mix: live spend doesn't throttle whatif."""
    _whatif(monkeypatch)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    led.append_intent(run_id='r0', trading_mode='live', coin='SOL',
                      intended_notional_usd=14.0, client_order_id='c0',
                      timestamp=f'{today}T01:00:00Z')
    bot.maybe_execute_buy('ETH')
    assert buy_calls == ['ETH']


def test_whatif_daily_cap_soft_fails_on_compute_error(buy_calls, monkeypatch, capsys):
    """MP-6b: an error computing the whatif cap must log and CONTINUE -- the
    whatif cap must never crash (or block) a learning-loop run."""
    _whatif(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError('simulated tally bug')

    monkeypatch.setattr(bot.executionledger, 'daily_cap_would_exceed', boom)
    bot.maybe_execute_buy('ETH')
    assert buy_calls == ['ETH']               # continued
    assert '[LEDGER ERROR]' in capsys.readouterr().out


def test_live_daily_cap_refusal_increments_distinct_counter(buy_calls, monkeypatch):
    """MP-8: daily-cap refusals get their own tally, separate from the
    run-cap tracker (which they never touched)."""
    monkeypatch.setattr(bot, 'DAILY_SPEND_CAP_USD', 0.0, raising=False)
    bot.maybe_execute_buy('ETH')
    bot.maybe_execute_buy('DOGE')
    assert bot.daily_cap_blocked == 2
    assert bot.spend_tracker.blocked == 0     # run-cap tally untouched


# ============================================================================
# MP-6c: simulated fills carry ESTIMATED fees (status stays 'simulated').
# ============================================================================

def test_whatif_simulated_fill_records_estimated_fees(scratch_ledger, monkeypatch):
    """Exercise the REAL buy_something whatif path (fake trader, no network):
    the simulated fill row must carry fees_usd ~= notional*1.2% and the
    fees_estimated marker, with status still 'simulated'."""

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
    monkeypatch.setattr(bot, 'RUN_ID', 'run_20260719T000000Z_test01', raising=False)

    bot.buy_something('BTC')

    rows = led.load_executions()
    intent, fill = rows
    assert intent['trading_mode'] == 'whatif'
    assert fill['status'] == 'simulated'                  # honest label kept
    assert fill['fees_usd'] == pytest.approx(0.06)        # 5.00 * 1.2%
    assert fill['fees_estimated'] is True                 # marked as estimate
    assert fill['avg_fill_price'] == pytest.approx(100.0)


# ============================================================================
# Review-gate fixes: wrong-shape ledgers follow the SAME quarantine/restore
# path as decode errors at the live gate, and the restored-also-corrupt
# refusal carries recovery guidance.
# ============================================================================

def test_live_wrong_shape_ledger_follows_recovery_path(
        buy_calls, scratch_ledger, capsys):
    """A {}-shaped (valid-JSON, wrong-shape) ledger triggers the full MP-2
    live recovery: quarantine -> snapshot restore -> buy proceeds (MAJOR 1)."""
    _snapshot_with_live_spend(scratch_ledger, 5.0)
    scratch_ledger.write_text('{}')
    bot.maybe_execute_buy('ETH')
    out = capsys.readouterr().out
    assert 'recovered from snapshot' in out
    assert buy_calls == ['ETH']
    assert list(scratch_ledger.parent.glob('executions.json.corrupt-*'))


def test_live_list_shaped_ledger_no_snapshot_refuses_not_crashes(
        buy_calls, scratch_ledger, capsys):
    """A [1,2,3]-shaped file used to raise AttributeError straight through
    the gate (uncaught crash). It must now refuse cleanly, fail-closed,
    with the recovery command (MAJOR 1)."""
    scratch_ledger.write_text('[1, 2, 3]')
    bot.maybe_execute_buy('ETH')          # must not raise
    out = capsys.readouterr().out
    assert buy_calls == []
    assert 'refusing LIVE BUY' in out
    assert "cp '" in out


def test_whatif_wrong_shape_ledger_quarantines_and_continues(
        buy_calls, scratch_ledger, monkeypatch, capsys):
    """Whatif + wrong-shape: same quarantine-and-continue as decode errors
    (previously: swallowed, then AttributeError inside append_intent)."""
    _whatif(monkeypatch)
    scratch_ledger.write_text('[]')
    bot.maybe_execute_buy('BTC')          # must not raise
    assert buy_calls == ['BTC']
    assert '[LEDGER ERROR]' in capsys.readouterr().out
    assert list(scratch_ledger.parent.glob('executions.json.corrupt-*'))


def test_restored_snapshot_also_corrupt_refusal_includes_recovery_guidance(
        buy_calls, scratch_ledger, monkeypatch, capsys):
    """MINOR 3: the err2 branch (restore 'succeeded' but the restored file is
    also unreadable) must print the same recovery command / manual pointer as
    the no-snapshot refusal."""
    # A snapshot exists but its content is wrong-shape -> restore copies it,
    # the cap re-check raises again -> err2 branch.
    Path(str(scratch_ledger) + '.bak-2026-01-01').write_text('{}')
    scratch_ledger.write_text('CORRUPT')
    bot.maybe_execute_buy('ETH')
    out = capsys.readouterr().out
    assert buy_calls == []
    assert 'restored ledger is itself unreadable' in out
    assert 'cp ' in out                       # recovery command present
    assert 'Ledger recovery' in out           # manual pointer present
