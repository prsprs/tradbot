"""Tests for the startup-banner daily-spend-cap line (T5 visibility fix).

Before this line existed the banner printed `Notional per buy` and `Run spend
cap` but NOT the daily spend cap, and nothing showed how much of today's (UTC)
daily cap was already consumed. The cap is only consulted when a BUY is
attempted, so a HOLD/SELL run gave the operator zero cap visibility even when
an earlier fill had already committed spend that UTC day.

crypto_trading_bot.format_daily_cap_banner_line(cap, source) renders the line.
'spent today' REUSES executionledger.live_spend_today() -- the SAME daily-sum
(intended_spend_on_date over LIVE intent rows for the current UTC day) the live
daily-cap gate consults before every buy -- read lock-free the same way the
run-start snapshot reads the ledger. This file pins:

  1. An empty/missing ledger renders $0.00 spent.
  2. A seeded live intent row today renders that committed spend.
  3. Only LIVE intents count (what-if intents never show as live spend).
  4. Only TODAY's (UTC) intents count (yesterday's are excluded).
  5. The line carries the config-source suffix, like neighboring banner lines.
  6. A corrupt/unreadable ledger degrades gracefully (never crashes the banner).

Pattern mirrors tests/test_trade_gate.py and tests/test_execution_ledger.py:
the ledger is redirected to a scratch file (no ./history/ access), rows are
built with led.append_intent, no network / no LLM / no orders.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import executionledger as led


@pytest.fixture
def scratch_ledger(tmp_path, monkeypatch):
    """Redirect the execution ledger to a scratch file so no test touches
    ./history/ (same pattern as test_trade_gate.py / test_execution_ledger.py)."""
    f = tmp_path / 'executions.json'
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(f))
    return f


def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def test_empty_ledger_shows_zero_spent(scratch_ledger):
    """Missing/empty ledger -> $0.00 spent (no crash)."""
    line = bot.format_daily_cap_banner_line(15.0, 'default')
    assert 'Daily spend cap: $15.00' in line
    assert '$0.00 spent today [UTC]' in line


def test_seeded_live_intent_today_is_reflected(scratch_ledger):
    """A live intent committed today shows up as spent-today in the banner."""
    led.append_intent(run_id='r0', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c0')
    line = bot.format_daily_cap_banner_line(10.0, '--daily-spend-cap-usd')
    assert line == (
        'Daily spend cap: $10.00 ($5.00 spent today [UTC]) '
        '[--daily-spend-cap-usd]'
    )


def test_multiple_live_intents_sum(scratch_ledger):
    """Spent-today sums every live intent for the current UTC day."""
    led.append_intent(run_id='r0', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c0')
    led.append_intent(run_id='r1', trading_mode='live', coin='BTC',
                      intended_notional_usd=5.0, client_order_id='c1')
    line = bot.format_daily_cap_banner_line(15.0, 'DAILY_SPEND_CAP_USD env')
    assert '$10.00 spent today [UTC]' in line
    assert '[DAILY_SPEND_CAP_USD env]' in line


def test_whatif_intents_are_not_counted_as_live_spend(scratch_ledger):
    """The banner always reports LIVE spend; what-if intents never inflate it."""
    led.append_intent(run_id='r0', trading_mode='whatif', coin='SOL',
                      intended_notional_usd=100.0, client_order_id='c0')
    line = bot.format_daily_cap_banner_line(15.0, 'default')
    assert '$0.00 spent today [UTC]' in line


def test_yesterdays_live_intent_is_excluded(scratch_ledger, monkeypatch):
    """Only the current UTC day counts -- an intent stamped yesterday is out."""
    # Seed one intent, then rewrite its timestamp to a prior UTC day on disk.
    led.append_intent(run_id='r0', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c0')
    rows = led.load_executions()
    rows[0]['timestamp'] = '2020-01-01T01:00:00Z'
    led._save_executions(rows)
    line = bot.format_daily_cap_banner_line(15.0, 'default')
    assert '$0.00 spent today [UTC]' in line


def test_reuses_live_spend_today(scratch_ledger, monkeypatch):
    """The banner delegates to executionledger.live_spend_today() (the SAME
    daily-sum the buy gate uses) rather than any parallel implementation."""
    calls = []

    def _spy(*a, **k):
        calls.append((a, k))
        return 7.5

    monkeypatch.setattr(led, 'live_spend_today', _spy)
    line = bot.format_daily_cap_banner_line(15.0, 'default')
    assert calls, 'expected live_spend_today() to be consulted'
    assert '$7.50 spent today [UTC]' in line


def test_corrupt_ledger_does_not_crash_banner(scratch_ledger):
    """A corrupt ledger (valid path, unparseable content) must never crash the
    banner -- it degrades to an 'unknown' note (mirrors non-fatal snapshot)."""
    Path(str(scratch_ledger)).write_text('{ this is not valid json')
    line = bot.format_daily_cap_banner_line(15.0, 'default')
    assert 'Daily spend cap: $15.00' in line
    assert 'spent today unknown [UTC]' in line
