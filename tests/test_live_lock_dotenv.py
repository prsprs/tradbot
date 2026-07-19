"""The live-confirmation lock must not be satisfiable from .env.

T1's double lock exists so no persistent config can arm live trading by
itself. load_dotenv() imports .env into os.environ before the lock check,
so main() snapshots the shell state pre-dotenv and strips a .env-supplied
LIVE_TRADING_CONFIRMED afterward (crypto_trading_bot.strip_dotenv_live_confirmation).
Verified need 2026-07-19: without the strip, `LIVE_TRADING_CONFIRMED=1` in
.env plus a bare `--live` would place real orders.
"""

from types import SimpleNamespace

from crypto_trading_bot import resolve_trading_mode, strip_dotenv_live_confirmation


def test_dotenv_supplied_confirmation_is_stripped_and_warned():
    environ = {'LIVE_TRADING_CONFIRMED': '1', 'OTHER': 'x'}
    warning = strip_dotenv_live_confirmation(False, environ)
    assert 'LIVE_TRADING_CONFIRMED' not in environ
    assert environ['OTHER'] == 'x'
    assert warning is not None and 'IGNORED' in warning


def test_shell_supplied_confirmation_is_preserved():
    environ = {'LIVE_TRADING_CONFIRMED': '1'}
    warning = strip_dotenv_live_confirmation(True, environ)
    assert environ['LIVE_TRADING_CONFIRMED'] == '1'
    assert warning is None


def test_absent_confirmation_is_a_no_op():
    environ = {}
    assert strip_dotenv_live_confirmation(False, environ) is None
    assert strip_dotenv_live_confirmation(True, environ) is None
    assert environ == {}


def test_stripped_dotenv_value_downgrades_live_request():
    # End-to-end through the gate: .env said confirmed, shell did not.
    # After the strip, --live alone must downgrade to whatif.
    environ = {'LIVE_TRADING_CONFIRMED': '1'}
    strip_dotenv_live_confirmation(False, environ)
    args = SimpleNamespace(live=True, trading_mode='live')
    mode, notice = resolve_trading_mode(args, environ)
    assert mode == 'whatif'
    assert notice is not None and 'LIVE_TRADING_CONFIRMED=1' in notice
