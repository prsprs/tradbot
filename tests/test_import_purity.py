"""TS-3/CQ-4 (audit 2026-07-19): pin the documented invariant that
`import crypto_trading_bot` is side-effect-free (AGENTS.md: no argv parsing,
no network, no client construction, no output).

These tests run the import in a fresh subprocess -- the only way to observe
true import-time behavior, since the suite's own conftest/imports would mask
it in-process. Three pins:

  1. the import is SILENT (empty stdout AND stderr) and exits 0;
  2. the import performs no network I/O (socket constructors are replaced
     with grenades before the import);
  3. the import does not load .env (load_dotenv is a main()-time action --
     an import must not mutate os.environ from a developer's .env; tests and
     tools that import the bot must see the environment they were given).
"""
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(code):
    return subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_import_is_silent():
    result = _run('import crypto_trading_bot')
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''
    assert result.stderr == ''


def test_import_makes_no_network_calls():
    # Replace the socket-level constructors BEFORE the import, mirroring
    # tests/conftest.py's suite-wide guard. Any import-time network attempt
    # (DNS lookup, connect, socket construction) raises and fails the run.
    # Patch METHODS (connect/connect_ex) and module functions, never the
    # socket class itself -- ssl subclasses socket.socket at import time, so
    # replacing the class would break unrelated stdlib imports and test the
    # wrong thing. Same layer as tests/conftest.py's suite-wide guard.
    code = (
        "import socket\n"
        "def _blocked(*a, **k):\n"
        "    raise RuntimeError('network use at import time')\n"
        "socket.socket.connect = _blocked\n"
        "socket.socket.connect_ex = _blocked\n"
        "socket.create_connection = _blocked\n"
        "socket.getaddrinfo = _blocked\n"
        "import crypto_trading_bot\n"
        "print('IMPORT_OK')\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'IMPORT_OK\n'


def test_import_does_not_load_dotenv():
    # TS-3: load_dotenv() must run in main(), not at module scope. Preload a
    # recording fake of the dotenv module so any import-time call is caught
    # regardless of what the local .env contains.
    code = (
        "import sys, types\n"
        "calls = []\n"
        "fake = types.ModuleType('dotenv')\n"
        "fake.load_dotenv = lambda *a, **k: calls.append((a, k)) or True\n"
        "sys.modules['dotenv'] = fake\n"
        "import crypto_trading_bot\n"
        "assert not calls, 'load_dotenv ran at import time: %r' % (calls,)\n"
        "print('NO_DOTENV_AT_IMPORT')\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'NO_DOTENV_AT_IMPORT\n'


def test_env_snapshot_refresh_repoints_import_time_globals(monkeypatch):
    """The companion to moving load_dotenv() into main(): several modules
    capture env-derived globals at import time (historyutil/executionledger
    HISTORY_DIR + derived paths, coinmarketcaputil CMC_API_KEY,
    lunarcrushutil LUNARCRUSH_API_KEY, the bot's own
    MARKET_BLOCK_TTL_SECONDS). Those imports now happen BEFORE .env is
    loaded, so main() re-resolves the snapshots right after load_dotenv()
    via _refresh_env_snapshots() -- otherwise .env-only settings (the
    documented home of the CMC/LunarCrush keys) would silently stop
    working. This test pins that the refresh actually repoints them.
    """
    import crypto_trading_bot as bot
    import historyutil
    import executionledger
    import coinmarketcaputil
    import lunarcrushutil

    # Preserve current values (monkeypatch restores attributes on teardown).
    for mod, attr in [
        (historyutil, 'HISTORY_DIR'), (historyutil, 'RECOMMENDATIONS_FILE'),
        (executionledger, 'HISTORY_DIR'), (executionledger, 'EXECUTIONS_FILE'),
        (coinmarketcaputil, 'CMC_API_KEY'),
        (lunarcrushutil, 'LUNARCRUSH_API_KEY'),
        (bot, 'MARKET_BLOCK_TTL_SECONDS'),
    ]:
        monkeypatch.setattr(mod, attr, getattr(mod, attr))

    monkeypatch.setenv('HISTORY_DIR', '/tmp/tradbot_refresh_test/')
    monkeypatch.setenv('CMC_API_KEY', 'cmc-refresh-sentinel')
    monkeypatch.setenv('LUNARCRUSH_API_KEY', 'lc-refresh-sentinel')
    monkeypatch.setenv('MARKET_BLOCK_TTL_SECONDS', '123')

    bot._refresh_env_snapshots()

    assert historyutil.HISTORY_DIR == '/tmp/tradbot_refresh_test/'
    assert historyutil.RECOMMENDATIONS_FILE == os.path.join(
        '/tmp/tradbot_refresh_test/', 'recommendations.json')
    assert executionledger.HISTORY_DIR == '/tmp/tradbot_refresh_test/'
    assert executionledger.EXECUTIONS_FILE == os.path.join(
        '/tmp/tradbot_refresh_test/', 'executions.json')
    assert coinmarketcaputil.CMC_API_KEY == 'cmc-refresh-sentinel'
    assert lunarcrushutil.LUNARCRUSH_API_KEY == 'lc-refresh-sentinel'
    assert bot.MARKET_BLOCK_TTL_SECONDS == 123
