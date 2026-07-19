"""MP-5 (audit 2026-07-19, warn-only per owner decision #4).

The voting panel in process_coin_with_comparison is built from COMPARE_LLMS
only; a PRIMARY_LLM that is not in COMPARE_LLMS pays for a Round-1 analysis
whose vote never counts. warn_if_primary_off_panel must warn loudly at
startup in exactly that configuration -- and stay silent everywhere else
(single-LLM modes never consult COMPARE_LLMS). Consensus math is untouched:
these tests only assert warning behavior, never decision behavior.
"""
import crypto_trading_bot as bot


def test_warns_when_primary_not_on_panel_compare(capsys):
    fired = bot.warn_if_primary_off_panel('grok', ['gemini', 'claude'], 'compare')
    out = capsys.readouterr().out
    assert fired is True
    assert '[CONFIG WARNING]' in out
    assert 'grok' in out
    assert 'COMPARE_LLMS' in out
    assert 'NOT count' in out


def test_warns_in_integrate_mode_too(capsys):
    fired = bot.warn_if_primary_off_panel('openai', ['gemini', 'claude'], 'integrate')
    assert fired is True
    assert '[CONFIG WARNING]' in capsys.readouterr().out


def test_silent_when_primary_on_panel(capsys):
    fired = bot.warn_if_primary_off_panel('gemini', ['gemini', 'claude'], 'compare')
    assert fired is False
    assert capsys.readouterr().out == ''


def test_silent_in_single_llm_modes_even_if_off_panel(capsys):
    # Solo modes never consult COMPARE_LLMS; the panel doesn't vote, so a
    # mismatch is meaningless and must not warn.
    for mode in bot.SINGLE_LLM_MODES:
        fired = bot.warn_if_primary_off_panel('grok', ['gemini', 'claude'], mode)
        assert fired is False, mode
    assert capsys.readouterr().out == ''


def test_default_shipped_config_does_not_warn(capsys):
    # The shipped default (primary=gemini, compare=gemini,claude) must stay
    # quiet -- this warning is for genuine misconfigurations only.
    fired = bot.warn_if_primary_off_panel('gemini', ['gemini', 'claude'], 'compare')
    assert fired is False
    assert capsys.readouterr().out == ''
