"""LG-2 (audit 2026-07-19): the two consensus-path exception handlers print a
full traceback (an unattended cron run's only clue used to be a one-line
str(e)). Logging only -- these tests also pin that the fail-closed semantics
and the pinned block_reason string survived the logging change byte-for-byte.

traceback.print_exc() writes to stderr; the pre-existing one-line messages
stay on stdout unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import voteschema


def _patch_panel_globals(monkeypatch):
    monkeypatch.setattr(bot, 'LLM_MODE', 'compare', raising=False)
    monkeypatch.setattr(bot, 'COMPARE_LLMS', ['gemini', 'claude'], raising=False)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', 'gemini', raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', True, raising=False)
    monkeypatch.setattr(bot, 'INTEGRATION_TIEBREAKER', 'none', raising=False)
    monkeypatch.setattr(bot, 'LOG_INTEGRATION_ROUNDS', False, raising=False)
    monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {})


class TestProcessCoinExceptionHandler:
    def test_traceback_printed_and_block_reason_unchanged(self, monkeypatch, capsys):
        def raising_get_llm_response(llm, coin, use_trend_check,
                                     peer_analysis=None, trends_data=None):
            raise RuntimeError('simulated panelist failure')

        _patch_panel_globals(monkeypatch)
        monkeypatch.setattr(bot, 'get_llm_response', raising_get_llm_response,
                            raising=False)

        decision = bot.process_coin_with_comparison('ETH', None)

        # Fail-closed semantics unchanged, block_reason byte-identical.
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason == 'exception: simulated panelist failure'

        captured = capsys.readouterr()
        assert 'Error in LLM processing for ETH: simulated panelist failure' in captured.out
        assert '[BLOCKED] ETH' in captured.out
        # LG-2: the full traceback (stderr) names the real raise site.
        assert 'Traceback (most recent call last)' in captured.err
        assert 'RuntimeError: simulated panelist failure' in captured.err


class TestGetLlmResponseExceptionHandler:
    def test_traceback_printed_and_none_none_returned(self, monkeypatch, capsys):
        class ExplodingTrader:
            def send_coin_check_request(self, coin_symbol, market_block=None):
                raise ValueError('simulated SDK failure')

        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {})
        monkeypatch.setattr(bot, 'claude_trader', ExplodingTrader(), raising=False)
        monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)

        resp, rec = bot.get_llm_response('claude', 'BTC', False)

        # Fail-closed return unchanged: (None, None) -> abstain('error') upstream.
        assert resp is None
        assert rec is None

        captured = capsys.readouterr()
        assert 'Error getting claude response: simulated SDK failure' in captured.out
        assert 'Traceback (most recent call last)' in captured.err
        assert 'ValueError: simulated SDK failure' in captured.err
