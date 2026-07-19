"""Tests for T1 safe trading defaults (crypto_trading_bot.py, plan Phase 0).

Covers the four T1 deliverables as pure-function / class unit tests (no
network, no LLM calls, no orders):

  1. resolve_trading_mode -- the full 8-row truth table over
     (--live flag, --trading-mode value, LIVE_TRADING_CONFIRMED env). Live is
     granted ONLY when BOTH the --live flag AND the env confirmation are
     present; every other live request downgrades to whatif WITH a notice.
  2. validate_notional -- default, override, the $100 ceiling (refused above,
     allowed at exactly 100), non-positive refusal, and the 2-decimal string
     formatting the Coinbase API requires.
  3. SpendTracker -- buys under the cap allowed, a crossing buy refused, the
     exact-cap boundary allowed, and the blocked tally.
  4. parse_args -- the argparse default is whatif (and --live defaults off,
     notional $5, cap $10) when the relevant env vars are unset.

resolve_trading_mode / validate_notional / SpendTracker are pure (they take
their inputs as arguments), so these tests neither touch os.environ globally
nor run main().
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot


def _args(live=False, trading_mode='whatif'):
    """Minimal stand-in for the parsed argparse namespace that
    resolve_trading_mode reads (only .live and .trading_mode)."""
    return SimpleNamespace(live=live, trading_mode=trading_mode)


def _env(confirmed):
    """LIVE_TRADING_CONFIRMED env mapping. confirmed=True -> '1'."""
    return {'LIVE_TRADING_CONFIRMED': '1'} if confirmed else {}


# ============================================================================
# 1. resolve_trading_mode -- full truth table
#
# Axes: L = --live flag, T = --trading-mode value, E = LIVE_TRADING_CONFIRMED.
# Rule: live iff (L AND E). A live request is (L OR T=='live'); a live request
# that is not granted downgrades to whatif WITH a notice.
# ============================================================================

# (name, live_flag, trading_mode, env_confirmed, expected_mode, expects_notice)
TRUTH_TABLE = [
    ("live+livemode+confirmed",   True,  'live',   True,  'live',   False),
    ("live+livemode+unconfirmed", True,  'live',   False, 'whatif', True),
    ("live+whatif+confirmed",     True,  'whatif', True,  'live',   False),
    ("live+whatif+unconfirmed",   True,  'whatif', False, 'whatif', True),
    ("nolive+livemode+confirmed", False, 'live',   True,  'whatif', True),
    ("nolive+livemode+unconfirm", False, 'live',   False, 'whatif', True),
    ("nolive+whatif+confirmed",   False, 'whatif', True,  'whatif', False),
    ("nolive+whatif+unconfirmed", False, 'whatif', False, 'whatif', False),
]


@pytest.mark.parametrize(
    "name,live,tmode,confirmed,exp_mode,exp_notice", TRUTH_TABLE,
    ids=[row[0] for row in TRUTH_TABLE],
)
def test_resolve_trading_mode_truth_table(name, live, tmode, confirmed, exp_mode, exp_notice):
    mode, notice = bot.resolve_trading_mode(_args(live=live, trading_mode=tmode), _env(confirmed))
    assert mode == exp_mode
    if exp_notice:
        assert notice is not None
    else:
        assert notice is None


def test_live_granted_only_with_both_locks():
    """Live is granted in exactly the two rows where L AND E hold."""
    granted = [row for row in TRUTH_TABLE if row[4] == 'live']
    assert len(granted) == 2
    for _name, live, _tmode, confirmed, _mode, _notice in granted:
        assert live and confirmed


def test_trading_mode_live_alone_no_longer_suffices():
    """Breaking change: --trading-mode=live with the env set but WITHOUT --live
    must downgrade to whatif (the old footgun)."""
    mode, notice = bot.resolve_trading_mode(_args(live=False, trading_mode='live'), _env(True))
    assert mode == 'whatif'
    assert notice is not None
    # The notice must name the specific missing lock (the --live flag).
    assert '--live' in notice


def test_downgrade_notice_names_missing_env():
    """--live without the env confirmation names the missing env var."""
    _mode, notice = bot.resolve_trading_mode(_args(live=True, trading_mode='live'), _env(False))
    assert 'LIVE_TRADING_CONFIRMED' in notice


def test_plain_whatif_has_no_notice():
    """No live request at all -> whatif, and crucially NO scary notice."""
    mode, notice = bot.resolve_trading_mode(_args(live=False, trading_mode='whatif'), _env(False))
    assert mode == 'whatif'
    assert notice is None


# ============================================================================
# 2. validate_notional
# ============================================================================

def test_notional_default_value():
    assert bot.validate_notional(5.00) == 5.00


def test_notional_accepts_string():
    assert bot.validate_notional('5.00') == 5.00


def test_notional_override():
    assert bot.validate_notional(25) == 25.0


def test_notional_ceiling_is_100():
    assert bot.NOTIONAL_CEILING_USD == 100.0


def test_notional_at_ceiling_allowed():
    assert bot.validate_notional(100) == 100.0


def test_notional_above_ceiling_refused():
    with pytest.raises(ValueError):
        bot.validate_notional(100.01)
    with pytest.raises(ValueError):
        bot.validate_notional(150)


def test_notional_zero_and_negative_refused():
    with pytest.raises(ValueError):
        bot.validate_notional(0)
    with pytest.raises(ValueError):
        bot.validate_notional(-5)


def test_notional_non_numeric_refused():
    with pytest.raises(ValueError):
        bot.validate_notional("abc")


def test_notional_string_formatting_two_decimals():
    """Coinbase's API takes a string; the call site formats to 2 decimals."""
    assert f'{bot.validate_notional(5.00):.2f}' == '5.00'
    assert f'{bot.validate_notional(5):.2f}' == '5.00'
    assert f'{bot.validate_notional(12.5):.2f}' == '12.50'


# ============================================================================
# 3. SpendTracker
# ============================================================================

def test_spend_tracker_buys_under_cap_allowed():
    t = bot.SpendTracker(cap=10.0, notional=5.0)
    assert t.try_spend() is True   # 5
    assert t.try_spend() is True   # 10 (exact cap)
    assert t.spent == 10.0
    assert t.blocked == 0


def test_spend_tracker_crossing_buy_refused():
    t = bot.SpendTracker(cap=10.0, notional=5.0)
    assert t.try_spend() is True   # 5
    assert t.try_spend() is True   # 10
    assert t.try_spend() is False  # would be 15 > 10
    assert t.spent == 10.0         # unchanged by the refused buy
    assert t.blocked == 1


def test_spend_tracker_exact_cap_boundary_allowed():
    """A buy landing cumulative spend EXACTLY on the cap goes through."""
    t = bot.SpendTracker(cap=5.0, notional=5.0)
    assert t.try_spend() is True   # 5 == cap -> allowed
    assert t.spent == 5.0
    assert t.try_spend() is False  # 10 > 5 -> refused
    assert t.blocked == 1


def test_spend_tracker_cap_below_notional_blocks_everything():
    t = bot.SpendTracker(cap=3.0, notional=5.0)
    assert t.try_spend() is False
    assert t.spent == 0.0
    assert t.blocked == 1


def test_spend_tracker_explicit_amount():
    t = bot.SpendTracker(cap=10.0, notional=5.0)
    assert t.try_spend(3.0) is True
    assert t.try_spend(7.0) is True   # 10 exactly
    assert t.try_spend(0.01) is False
    assert t.spent == 10.0
    assert t.blocked == 1


# ============================================================================
# 4. parse_args defaults (env unset)
# ============================================================================

def test_argparse_defaults_when_env_unset(monkeypatch):
    """With the relevant env vars unset and no CLI args, the trading mode
    default is whatif, --live is off, notional is $5 and the cap is $10."""
    monkeypatch.delenv('TRADING_MODE', raising=False)
    monkeypatch.delenv('TRADE_NOTIONAL_USD', raising=False)
    monkeypatch.delenv('RUN_SPEND_CAP_USD', raising=False)
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'])

    args = bot.parse_args()
    assert args.trading_mode == 'whatif'
    assert args.live is False
    assert args.notional_usd == 5.00
    assert args.run_spend_cap_usd == 10.00

    # And the resolver leaves a default (no-arg) invocation in whatif, quietly.
    mode, notice = bot.resolve_trading_mode(args, {})
    assert mode == 'whatif'
    assert notice is None


def test_argparse_trading_mode_env_override(monkeypatch):
    """TRADING_MODE=live still parses as 'live' (compat), but on its own it is
    only a *request* -- resolve_trading_mode is what downgrades it."""
    monkeypatch.setenv('TRADING_MODE', 'live')
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'])

    args = bot.parse_args()
    assert args.trading_mode == 'live'
    assert args.live is False
    mode, notice = bot.resolve_trading_mode(args, {})  # no --live, no env
    assert mode == 'whatif'
    assert notice is not None
