"""WS-6: `--print-config` and `--plan` -- a zero-network way to see what a run
WOULD do.

Motivation (owner, live session): inspecting resolved .env defaults safely
required a hand-written Python heredoc. These flags emit the fully-resolved
operational config (with flag-vs-env-vs-default provenance) as JSON, and --plan
adds a human-readable plan, BOTH exiting 0 before any network/LLM call, before
the instance lock, and before the analyzer summary.

Two test layers:

  * In-process tests of the pure builders (build_config_report / build_plan_lines)
    -- fast, and they exercise the SAME provenance machinery (get_config_source)
    and resolution helpers (resolve_trading_mode, parse_analyze_coins, ...) the
    real run uses. sys.argv + os.environ are set via monkeypatch so
    get_config_source sees them, exactly as in a real invocation.

  * Subprocess tests that run `main()` end-to-end under a POISONED network
    (socket constructors are grenades, mirroring tests/test_import_purity.py and
    tests/conftest.py) with dotenv faked to a no-op so NO .env keys load -- the
    only faithful proof that the flags reach exit 0 with zero network and no
    money-record side effects.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import executionledger as led
import modelregistry


# ----------------------------------------------------------------------------
# Hermeticity: the builders resolve config from os.environ (via parse_args'
# argparse defaults and get_config_source) and from *_API_KEY / *_MODEL vars.
# The suite is run in one process, so ANY test (in this file or another, in any
# order) that leaves a config env var set -- or a developer shell / .env that
# exported one -- would perturb source attribution and resolved values here.
# Root-caused as the pollution vector for the intermittent, order-dependent
# failures the orchestrator observed. Fix: an autouse fixture scrubs the FULL
# set of config-relevant env vars before every test, so each test starts from a
# known-empty config environment regardless of what ran before it. The scrub
# also cleans the PARENT env the subprocess tests inherit, hermeticizing those
# too. monkeypatch restores everything on teardown, so this file never leaks
# state outward either.
# ----------------------------------------------------------------------------

# Every env var parse_args reads as an argparse default, plus resolve_trading_mode's
# lock var, plus the credential and model-override vars build_config_report reads.
_CONFIG_ENV_VARS = [
    'TRADING_MODE', 'LLM_MODE', 'PRIMARY_LLM', 'COMPARE_LLMS', 'ANALYZE_COINS',
    'EXCLUDE_COINS', 'CHAINS', 'CATEGORIES', 'POLYMARKET_FILTER',
    'REQUIRE_CONSENSUS', 'INTEGRATION_TIEBREAKER', 'DISCOVERY',
    'DISCOVERY_UNIVERSE', 'DEX_MODE',
    'DEX_SLIPPAGE', 'TRADE_NOTIONAL_USD', 'RUN_SPEND_CAP_USD',
    'DAILY_SPEND_CAP_USD', 'LOG_INTEGRATION_ROUNDS', 'SHOW_PANEL_RESPONSES',
    'EXPORT_CANDIDATES', 'CANDIDATE_DIR', 'CANDIDATE_BLOCKCHAIN',
    'EXPORT_RECOMMENDATIONS', 'RELAX_DISCOVERY_FAILURE', 'SKIP_PREFLIGHT',
    'SKIP_ANALYZER', 'QUIET', 'LIVE_TRADING_CONFIRMED',
    'COINBASE_CREDENTIALS_FILE',
    # Credential presence vars (values never emitted, but presence shifts the
    # credentials block, so scrub them to a known-absent baseline).
    'GOOGLE_API_KEY', 'GEMINI_API_KEY', 'CLAUDE_API_KEY', 'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY', 'XAI_API_KEY', 'PERPLEXITY_API_KEY', 'CMC_API_KEY',
    'COINMARKETCAP_API_KEY', 'LUNARCRUSH_API_KEY',
    # Model overrides.
    'GEMINI_MODEL', 'CLAUDE_MODEL', 'OPENAI_MODEL', 'GROK_MODEL',
    'PERPLEXITY_MODEL',
]


@pytest.fixture(autouse=True)
def _hermetic_config_env(monkeypatch, tmp_path):
    """Scrub every config-relevant env var before each test so ambient state
    (another test, the shell, .env) can never perturb resolution. Also defends
    against a var whose name matches the *_API_KEY / *_MODEL patterns but isn't
    in the explicit list above.

    Second vector closed here: build_plan_lines / _instance_lock_held read the
    executionledger.EXECUTIONS_FILE MODULE GLOBAL (to derive the lock path and
    history dir). Another test can leave that pointed anywhere -- or it defaults
    to the real ./history/ -- so redirect it to a per-test tmp path. This keeps
    every in-process test off shared ledger/lock state AND off the owner's real
    history dir (the lock probe would otherwise read ./history/bot_instance.*)."""
    for k in list(os.environ):
        if k in _CONFIG_ENV_VARS or k.endswith('_API_KEY') or k.endswith('_MODEL'):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(tmp_path / 'executions.json'))


# ============================================================================
# In-process builder tests
# ============================================================================

def _resolve(monkeypatch, argv, env):
    """Set sys.argv + os.environ the way a real invocation would, then parse
    args and build the config report. get_config_source reads both globals.
    The autouse fixture has already scrubbed all config env vars, so `env`
    supplies exactly (and only) the vars under test."""
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'] + argv)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    args = bot.parse_args()
    return bot.build_config_report(args, os.environ)


def test_shape_is_key_value_source(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config'], {})
    assert 'settings' in report and 'credentials' in report
    settings = report['settings']
    assert settings, "expected a non-empty settings map"
    for key, entry in settings.items():
        assert set(entry) == {'value', 'source'}, f"{key}: {entry!r}"
        assert entry['source'] in ('cli', 'env', 'default'), f"{key}: {entry}"
    # Spot-check the operational keys the owner listed are present.
    for key in ('trading_mode', 'llm_mode', 'primary_llm', 'coins',
                'exclude_coins', 'notional_usd', 'run_spend_cap_usd',
                'daily_spend_cap_usd', 'polymarket_filter', 'tiebreaker',
                'discovery_universe',
                'model_gemini', 'model_claude'):
        assert key in settings, f"missing operational key: {key}"


def test_defaults_report_default_source(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config'], {})
    s = report['settings']
    assert s['trading_mode']['value'] == 'whatif'
    assert s['trading_mode']['source'] == 'default'
    assert s['coins']['value'] == []
    assert s['coins']['source'] == 'default'


def test_cli_override_source(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config', '--coins=BTC,ETH'], {})
    coins = report['settings']['coins']
    assert coins['value'] == ['BTC', 'ETH']
    assert coins['source'] == 'cli'


def test_env_provided_source(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config'], {'ANALYZE_COINS': 'SOL,DOGE'})
    coins = report['settings']['coins']
    assert coins['value'] == ['SOL', 'DOGE']
    assert coins['source'] == 'env'


def test_cli_beats_env_for_source(monkeypatch):
    # Both present -> CLI wins, and the source must say so (not 'env').
    report = _resolve(monkeypatch, ['--print-config', '--llm-mode=gemini'],
                      {'LLM_MODE': 'compare'})
    llm = report['settings']['llm_mode']
    assert llm['value'] == 'gemini'
    assert llm['source'] == 'cli'


def test_models_resolved_from_registry(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config'], {})
    s = report['settings']
    assert s['model_gemini']['value'] == modelregistry.get_model('gemini')
    assert s['model_gemini']['source'] == 'default'


def test_model_env_override_source(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config'], {'CLAUDE_MODEL': 'claude-test-xyz'})
    s = report['settings']
    assert s['model_claude']['value'] == 'claude-test-xyz'
    assert s['model_claude']['source'] == 'env'


def test_credentials_presence_only_no_secret_values(monkeypatch):
    report = _resolve(monkeypatch, ['--print-config'],
                      {'OPENAI_API_KEY': 'sk-test123', 'XAI_API_KEY': 'xai-secret-abc'})
    creds = report['credentials']
    assert creds['openai'] == 'present'
    assert creds['grok'] == 'present'
    assert creds['claude'] == 'absent'
    # Redaction: the whole serialized report must never leak a key value.
    dumped = json.dumps(report)
    assert 'sk-test123' not in dumped
    assert 'xai-secret-abc' not in dumped
    for v in creds.values():
        assert v in ('present', 'absent')


def test_plan_max_buys_and_spend_arithmetic(monkeypatch):
    # led.EXECUTIONS_FILE is redirected to a tmp path by the autouse fixture,
    # so build_plan_lines' lock probe touches no shared/real ledger state.
    report = _resolve(monkeypatch, ['--plan', '--run-spend-cap-usd=20', '--notional-usd=5'], {})
    lines = bot.build_plan_lines(report, os.environ)
    joined = "\n".join(lines)
    # 20 / 5 = 4 possible buys; whatif -> only the run cap applies to max spend.
    assert any('Max buys this run: 4' in ln for ln in lines), joined
    assert '$20.00' in joined
    assert '$5.00' in joined
    # Effective mode + live-armed status must appear (banner honesty).
    assert 'WHAT-IF' in joined
    assert 'live armed: NO' in joined


def test_plan_lines_contain_no_secret(monkeypatch):
    report = _resolve(monkeypatch, ['--plan'], {'OPENAI_API_KEY': 'sk-plan-secret'})
    lines = bot.build_plan_lines(report, os.environ)
    assert 'sk-plan-secret' not in "\n".join(lines)


# ============================================================================
# Subprocess (end-to-end) tests: exit 0, zero network, no side effects
# ============================================================================

def _run_cli(flag, env=None, history_dir=None):
    """Run `main()` with `flag` under poisoned sockets and a no-op dotenv so
    no .env keys load and any network attempt raises. Returns CompletedProcess.
    """
    code = (
        "import socket\n"
        "def _b(*a, **k):\n"
        "    raise RuntimeError('network use before exit')\n"
        "socket.socket.connect = _b\n"
        "socket.socket.connect_ex = _b\n"
        "socket.create_connection = _b\n"
        "socket.getaddrinfo = _b\n"
        "import sys, types\n"
        "fake = types.ModuleType('dotenv')\n"
        "fake.load_dotenv = lambda *a, **k: True\n"
        "sys.modules['dotenv'] = fake\n"
        f"sys.argv = ['crypto_trading_bot.py', {flag!r}]\n"
        "import crypto_trading_bot\n"
        "crypto_trading_bot.main()\n"
    )
    run_env = {k: v for k, v in os.environ.items()
               if not (k.endswith('_API_KEY'))}
    if env:
        run_env.update(env)
    if history_dir:
        run_env['HISTORY_DIR'] = str(history_dir)
    return subprocess.run(
        [sys.executable, '-c', code],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
        env=run_env,
    )


def test_print_config_exits_zero_and_emits_json(tmp_path):
    r = _run_cli('--print-config', history_dir=tmp_path)
    assert r.returncode == 0, r.stderr
    parsed = json.loads(r.stdout)
    assert 'settings' in parsed and 'credentials' in parsed
    # No API keys in the env -> every LLM/data credential 'absent' (coinbase
    # is a repo-root file, so it may legitimately be 'present').
    creds = parsed['credentials']
    for provider in ('gemini', 'claude', 'openai', 'grok', 'perplexity',
                     'coinmarketcap', 'lunarcrush'):
        assert creds[provider] == 'absent', creds
    assert set(creds.values()) <= {'absent', 'present'}


def test_plan_exits_zero_and_prints_plan(tmp_path):
    r = _run_cli('--plan', history_dir=tmp_path)
    assert r.returncode == 0, r.stderr
    assert 'RUN PLAN' in r.stdout


def test_flags_write_no_history_and_take_no_lock(tmp_path):
    # A fresh HISTORY_DIR: after --print-config it must be empty (no ledger, no
    # recommendations, no bot_instance lock file).
    hist = tmp_path / 'hist'
    r = _run_cli('--print-config', history_dir=hist)
    assert r.returncode == 0, r.stderr
    leftovers = list(hist.rglob('*')) if hist.exists() else []
    assert leftovers == [], f"print-config created files: {leftovers}"


def test_plan_takes_no_lock_file(tmp_path):
    hist = tmp_path / 'hist'
    r = _run_cli('--plan', history_dir=hist)
    assert r.returncode == 0, r.stderr
    locks = list(hist.rglob('bot_instance*.lock')) if hist.exists() else []
    assert locks == [], f"--plan created a lock file: {locks}"


def test_redaction_end_to_end(tmp_path):
    # A real-looking secret in the env must never appear anywhere in output.
    r = _run_cli('--plan', env={'OPENAI_API_KEY': 'sk-live-DEADBEEF'},
                 history_dir=tmp_path)
    assert r.returncode == 0, r.stderr
    assert 'sk-live-DEADBEEF' not in r.stdout
    assert 'sk-live-DEADBEEF' not in r.stderr
    # ...but presence is still reported.
    assert '"openai": "present"' in r.stdout or 'openai' in r.stdout
