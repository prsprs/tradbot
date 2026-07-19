"""LG-3 (audit 2026-07-19): a 5-coin --llm-mode=compare run used to dump every
panelist's FULL response inline. Grok/perplexity write multi-thousand-word
essays, so ~10 essays per run buried the one-line "[COMPARISON] ..." verdicts
the operator actually reads (owner-observed 2026-07-19).

The fix routes full panelist text to a per-run log file under
<HISTORY_DIR>/panel_responses/<run_id>.log and keeps the console concise:
a per-panelist summary (vote + confidence + first reason) plus ONE pointer
line. --show-responses / SHOW_PANEL_RESPONSES restores the old inline dump.

These tests pin: import silence (no dir at import), HISTORY_DIR-keyed path,
complete (never truncated) file capture with headers, the concise console
contract, the once-per-run pointer, the escape hatch, and the LOG_INTEGRATION_
ROUNDS=false suppression — end to end through process_coin_with_comparison.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import historyutil


# A grok/perplexity-scale essay: the exact payload that used to flood the
# terminal. It carries a valid delimiter tag so the fallback parser votes.
LONG_ESSAY = (
    "DOGE MARKET ANALYSIS\n"
    + ("Dogecoin's price action has been choppy and range-bound. " * 400)
    + "\nOn balance the risk/reward favors patience.\n"
    + "<**DOGE-PRS-HOLD**>"
)


@pytest.fixture
def panel_env(monkeypatch, tmp_path):
    """Redirect HISTORY_DIR to a scratch dir, pin a run_id, reset the
    once-per-run pointer flag, and default the escape hatch off."""
    monkeypatch.setattr(historyutil, 'HISTORY_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_20260719T101112Z_abc123', raising=False)
    monkeypatch.setattr(bot, '_panel_log_pointer_shown', False, raising=False)
    monkeypatch.setattr(bot, 'SHOW_PANEL_RESPONSES', False, raising=False)
    return tmp_path


def _log_file(tmp_path):
    return tmp_path / 'panel_responses' / 'run_20260719T101112Z_abc123.log'


# ---------------------------------------------------------------------------
# Import purity: importing the module must not create the log directory.
# ---------------------------------------------------------------------------

def test_import_creates_no_directory(tmp_path):
    """`import crypto_trading_bot` must be side-effect-free — the panel_responses
    dir is created lazily on first write, never at import time.

    Runs from an empty cwd so the default ./history/ resolves INSIDE tmp_path.
    Never assert on the repo's real history/ — the owner's legitimate runs
    create history/panel_responses/ there, and a test that asserts real user
    data doesn't exist fails forever once the feature is actually used
    (happened 2026-07-19, first evening of the feature).
    """
    repo = str(Path(__file__).parent.parent)
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {repo!r})\n"
        "import crypto_trading_bot as bot\n"
        "assert hasattr(bot, 'log_panel_response')\n"
        "print('NO_DIR' if not os.path.exists('history/panel_responses') else 'DIR')\n"
    )
    env = {**os.environ}
    env.pop('HISTORY_DIR', None)  # exercise the default ./history/ path
    out = subprocess.run(
        [sys.executable, '-c', script], cwd=str(tmp_path),
        capture_output=True, text=True, env=env,
    )
    assert out.returncode == 0, out.stderr
    assert 'NO_DIR' in out.stdout
    assert not (tmp_path / 'history' / 'panel_responses').exists()


# ---------------------------------------------------------------------------
# Path resolution keys off HISTORY_DIR (scratch runs never litter the repo).
# ---------------------------------------------------------------------------

def test_log_path_keys_off_history_dir(panel_env):
    path = bot._panel_response_log_path()
    assert path == str(panel_env / 'panel_responses' / 'run_20260719T101112Z_abc123.log')


# ---------------------------------------------------------------------------
# Full text goes to the file, complete and header-stamped.
# ---------------------------------------------------------------------------

def test_full_response_written_to_file_untruncated(panel_env, capsys):
    bot.log_panel_response('perplexity', 'DOGE', 'Round 1', LONG_ESSAY)

    logf = _log_file(panel_env)
    assert logf.exists()
    contents = logf.read_text()
    # Complete capture — the whole essay, never truncated.
    assert LONG_ESSAY in contents
    # Header carries coin, panelist, round, and an ISO-Z timestamp.
    assert 'Z | DOGE | perplexity | Round 1 =====' in contents


def test_console_stays_concise_by_default(panel_env, capsys):
    bot.log_panel_response('perplexity', 'DOGE', 'Round 1', LONG_ESSAY)
    out = capsys.readouterr().out

    # The essay body must NOT be on the console.
    assert 'Dogecoin' not in out
    assert '--- Perplexity Round 1 Response' not in out
    # A concise per-panelist summary IS on the console...
    assert '[PANEL] perplexity/DOGE Round 1:' in out
    # ...and one pointer line telling the operator where the raw text went.
    assert '[PANEL LOG] full panelist responses ->' in out
    assert 'run_20260719T101112Z_abc123.log' in out


def test_summary_shows_vote_confidence_and_first_reason(panel_env, capsys):
    vote = json.dumps({
        "symbol": "BTC", "action": "SELL", "confidence": 0.82,
        "abstain": False, "reasons": ["momentum rolled over", "resistance rejected"],
    })
    bot.log_panel_response('claude', 'BTC', 'Round 1', vote)
    out = capsys.readouterr().out
    assert 'SELL' in out
    assert 'conf=0.82' in out
    assert 'momentum rolled over' in out  # FIRST reason only
    assert 'resistance rejected' not in out


# ---------------------------------------------------------------------------
# Once-per-run pointer.
# ---------------------------------------------------------------------------

def test_pointer_printed_once_per_run(panel_env, capsys):
    bot.log_panel_response('grok', 'DOGE', 'Round 1', LONG_ESSAY)
    bot.log_panel_response('perplexity', 'ETH', 'Round 1', LONG_ESSAY)
    out = capsys.readouterr().out
    assert out.count('[PANEL LOG] full panelist responses ->') == 1
    # Both panelists still get their own concise summary line.
    assert '[PANEL] grok/DOGE' in out
    assert '[PANEL] perplexity/ETH' in out


# ---------------------------------------------------------------------------
# Escape hatch: --show-responses / SHOW_PANEL_RESPONSES echoes inline.
# ---------------------------------------------------------------------------

def test_show_responses_echoes_full_text_inline(panel_env, monkeypatch, capsys):
    monkeypatch.setattr(bot, 'SHOW_PANEL_RESPONSES', True, raising=False)
    bot.log_panel_response('perplexity', 'DOGE', 'Round 1', LONG_ESSAY)
    out = capsys.readouterr().out
    assert '--- Perplexity Round 1 Response for DOGE ---' in out
    assert 'Dogecoin' in out
    # File capture still happens regardless of the escape hatch.
    assert _log_file(panel_env).exists()


# ---------------------------------------------------------------------------
# End-to-end through process_coin_with_comparison (compare mode).
# ---------------------------------------------------------------------------

def _fake_panel(votes):
    def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
        action = votes[llm]
        return (LONG_ESSAY.replace('HOLD', action), action)
    return fake


def test_compare_mode_routes_essays_to_file_not_console(panel_env, monkeypatch, capsys):
    monkeypatch.setattr(bot, 'LLM_MODE', 'compare', raising=False)
    monkeypatch.setattr(bot, 'COMPARE_LLMS', ['grok', 'perplexity'], raising=False)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', 'gemini', raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', False, raising=False)
    monkeypatch.setattr(bot, 'INTEGRATION_TIEBREAKER', 'none', raising=False)
    monkeypatch.setattr(bot, 'LOG_INTEGRATION_ROUNDS', True, raising=False)
    monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {}, raising=False)
    monkeypatch.setattr(bot, 'get_llm_response',
                        _fake_panel({'grok': 'HOLD', 'perplexity': 'HOLD'}),
                        raising=False)

    decision = bot.process_coin_with_comparison('DOGE', None)
    out = capsys.readouterr().out

    assert decision.action == 'HOLD'
    # The verdict line survives, and is not drowned by essays.
    assert '[COMPARISON]' in out
    assert 'Dogecoin' not in out
    # Both panelists captured to the one per-run file.
    contents = _log_file(panel_env).read_text()
    assert contents.count('===== ') == 2
    assert 'grok' in contents and 'perplexity' in contents


def test_log_rounds_false_suppresses_capture(panel_env, monkeypatch, capsys):
    monkeypatch.setattr(bot, 'LLM_MODE', 'compare', raising=False)
    monkeypatch.setattr(bot, 'COMPARE_LLMS', ['grok', 'perplexity'], raising=False)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', 'gemini', raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', False, raising=False)
    monkeypatch.setattr(bot, 'INTEGRATION_TIEBREAKER', 'none', raising=False)
    monkeypatch.setattr(bot, 'LOG_INTEGRATION_ROUNDS', False, raising=False)
    monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {}, raising=False)
    monkeypatch.setattr(bot, 'get_llm_response',
                        _fake_panel({'grok': 'HOLD', 'perplexity': 'HOLD'}),
                        raising=False)

    bot.process_coin_with_comparison('DOGE', None)
    out = capsys.readouterr().out

    # No file, no panel summary, no pointer when the operator asked for quiet.
    assert not _log_file(panel_env).exists()
    assert '[PANEL LOG]' not in out
    assert '[PANEL] grok' not in out
    # The structured verdict line still prints.
    assert '[COMPARISON]' in out
