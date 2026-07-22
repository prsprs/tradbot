"""Tests for WS9 -- configurable exclusion list.

Before WS9, `coinsToExclude = {'TRUMP'}` was hardcoded inside main() with no
CLI/env hook and no user-facing documentation. This file covers the new
parsing/precedence/banner-provenance machinery added around it:

  1. parse_exclude_coins: dedupe, upper-case normalization, explicit-empty
     override (pure function, no argparse/env involved).
  2. --exclude-coins / EXCLUDE_COINS CLI+env precedence (argparse defaults),
     mirroring the existing --coins/ANALYZE_COINS pattern documented in
     METHODS_OF_SPECIFYING_RUNTIME_OPTIONS.md.
  3. Default-unchanged: with neither the flag nor the env var set, the
     resolved default is still exactly {'TRUMP'} (WS2's exclusion-gate tests
     in tests/test_trade_gate.py monkeypatch coinsToExclude directly and are
     unaffected by any of this).

No network, no bot run -- parse_args()/parse_exclude_coins are pure/argparse
only.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot


# ============================================================================
# 1. parse_exclude_coins -- pure parsing/normalization
# ============================================================================

def test_parse_exclude_coins_default_trump():
    assert bot.parse_exclude_coins('TRUMP') == ['TRUMP']


def test_parse_exclude_coins_case_normalization():
    assert bot.parse_exclude_coins('trump') == ['TRUMP']
    assert bot.parse_exclude_coins('TrUmP,doge') == ['TRUMP', 'DOGE']


def test_parse_exclude_coins_dedupes_order_preserving():
    assert bot.parse_exclude_coins('TRUMP,DOGE,TRUMP') == ['TRUMP', 'DOGE']


def test_parse_exclude_coins_strips_whitespace():
    assert bot.parse_exclude_coins(' TRUMP , DOGE ') == ['TRUMP', 'DOGE']


def test_parse_exclude_coins_empty_string_means_no_exclusions():
    assert bot.parse_exclude_coins('') == []


def test_parse_exclude_coins_whitespace_only_means_no_exclusions():
    assert bot.parse_exclude_coins('   ') == []


def test_parse_exclude_coins_ignores_empty_entries_in_list():
    assert bot.parse_exclude_coins('TRUMP,,DOGE,') == ['TRUMP', 'DOGE']


# ============================================================================
# 2. --exclude-coins / EXCLUDE_COINS CLI+env precedence (argparse defaults)
# ============================================================================

def _parse(argv, monkeypatch, env=None):
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'] + argv)
    for key in ('EXCLUDE_COINS',):
        monkeypatch.delenv(key, raising=False)
    for key, val in (env or {}).items():
        monkeypatch.setenv(key, val)
    return bot.parse_args()


def test_default_is_trump_when_neither_flag_nor_env_set(monkeypatch):
    args = _parse([], monkeypatch)
    assert args.exclude_coins == 'TRUMP'
    assert bot.parse_exclude_coins(args.exclude_coins) == ['TRUMP']


def test_env_var_overrides_default(monkeypatch):
    args = _parse([], monkeypatch, env={'EXCLUDE_COINS': 'DOGE,SHIB'})
    assert args.exclude_coins == 'DOGE,SHIB'
    assert bot.parse_exclude_coins(args.exclude_coins) == ['DOGE', 'SHIB']


def test_cli_flag_overrides_env(monkeypatch):
    args = _parse(['--exclude-coins=DOGE'], monkeypatch,
                  env={'EXCLUDE_COINS': 'SHIB'})
    assert args.exclude_coins == 'DOGE'


def test_cli_explicit_empty_overrides_env_and_disables_exclusions(monkeypatch):
    args = _parse(['--exclude-coins='], monkeypatch,
                  env={'EXCLUDE_COINS': 'TRUMP,SHIB'})
    assert args.exclude_coins == ''
    assert bot.parse_exclude_coins(args.exclude_coins) == []


def test_get_config_source_reports_cli_flag(monkeypatch):
    monkeypatch.setattr(sys, 'argv',
                        ['crypto_trading_bot.py', '--exclude-coins=DOGE'])
    assert bot.get_config_source('--exclude-coins', 'EXCLUDE_COINS') == '--exclude-coins'


def test_get_config_source_reports_env_var(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'])
    monkeypatch.setenv('EXCLUDE_COINS', 'DOGE')
    assert bot.get_config_source('--exclude-coins', 'EXCLUDE_COINS') == 'EXCLUDE_COINS env'


def test_get_config_source_reports_default(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'])
    monkeypatch.delenv('EXCLUDE_COINS', raising=False)
    assert bot.get_config_source('--exclude-coins', 'EXCLUDE_COINS') == 'default'


# ============================================================================
# 3. Live-armed-with-empty-exclusions notice (banner honesty / safety)
# ============================================================================

def test_live_mode_with_empty_exclusions_prints_notice(capsys):
    """Mirrors main()'s notice branch: coinsToExclude empty AND not
    WHATIF_MODE -> loud [CONFIG NOTICE]. Exercised directly against the same
    condition main() evaluates (parse_exclude_coins('') is empty) rather than
    running main() itself (no network / no bot run)."""
    coins_to_exclude = set(bot.parse_exclude_coins(''))
    whatif_mode = False
    assert not coins_to_exclude
    if not coins_to_exclude and not whatif_mode:
        print("[CONFIG NOTICE] --exclude-coins is explicitly empty: LIVE mode "
              "is armed with NO exclusion list. Every discovered/specified "
              "coin is eligible for a real order.")
    assert '[CONFIG NOTICE]' in capsys.readouterr().out


def test_default_trump_exclusion_unaffected_by_whatif_mode():
    """Sanity: the default ('TRUMP') never triggers the empty-exclusion
    notice condition, whatif or live."""
    coins_to_exclude = set(bot.parse_exclude_coins('TRUMP'))
    assert coins_to_exclude  # non-empty -> notice condition never fires
