"""Tests for process_coin_with_comparison consensus math (crypto_trading_bot.py).

Originally ported from lab/session_tests_20260718/_consensus_snippet.py
(formerly test_consensus.py) (11
scripted-vote run_case invocations). As of T3 (consensus hardening, plan
Phase 0) the function returns a structured PanelDecision and fails closed:

  - every LLM in COMPARE_LLMS is represented in the vote set, either as a
    real vote or an explicit abstain ('error' / 'parse_failure');
  - abstains are excluded from agreement math; under REQUIRE_CONSENSUS any
    abstain blocks the trade;
  - sub-quorum, unavailable tiebreakers, and exceptions in the multi-LLM
    block all yield BLOCKED decisions, never a lone/primary fallback vote;
  - REQUIRE_CONSENSUS is honored in integrate mode (tiebreaker never
    consulted on a non-unanimous panel);
  - trades are gated by the mode-aware decision_allows_trade, not a bare
    `'BUY' in final_action` check.

Ported cases whose expectations encoded the old buggy behavior have been
updated to the new semantics, each marked with a
`# behavior changed by T3 fail-closed hardening (plan Phase 0)` comment.

process_coin_with_comparison reads several module globals at call time
(LLM_MODE, COMPARE_LLMS, PRIMARY_LLM, REQUIRE_CONSENSUS,
INTEGRATION_TIEBREAKER, LOG_INTEGRATION_ROUNDS, and the *_trader gate flags)
and calls module-level get_llm_response. None of these exist as module
attributes until main() runs, so every setattr below uses raising=False.

T8 seam update: the PRIMARY_LLM's Round-1 text is resolved provider-aware
inside process_coin_with_comparison — structured providers (gemini/claude/
openai) parse schema JSON, not delimiter tags. The primary in these cases is
gemini, so scripted primary texts are now vote-JSON payloads (exercising the
real structured resolution path); the stubbed get_llm_response still hands
back vote strings directly, so the consensus math under test is unchanged.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import historyutil
import voteschema

C = ['gemini', 'claude', 'openai']


def _vote_json(coin, action, abstain=False, confidence=0.7, symbol=None):
    """A schema-valid structured vote payload, as a structured provider's
    response text would carry it."""
    return json.dumps({
        "symbol": symbol if symbol is not None else coin,
        "action": action,
        "confidence": confidence,
        "abstain": abstain,
        "reasons": ["scripted test vote"],
    })


def make_fake_get_llm_response(votes, calls=None):
    """votes: dict llm -> rec-or-None-or-'NORESP' (NORESP = call failed, resp None).

    If `calls` is a list, every invocation is appended to it as
    (llm, peer_analysis) so tests can assert on round structure.
    """
    def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
        if calls is not None:
            calls.append((llm, peer_analysis))
        v = votes.get(llm, 'NORESP')
        if v == 'NORESP':
            return None, None
        if v is None:
            return "some prose without a tag", None
        return f"analysis <**{coin}-PRS-{v}**>", v
    return fake


def _patch_globals(monkeypatch, llm_mode, compare_llms, primary, require_consensus,
                    tiebreaker, get_llm_response_fn):
    monkeypatch.setattr(bot, 'LLM_MODE', llm_mode, raising=False)
    monkeypatch.setattr(bot, 'COMPARE_LLMS', compare_llms, raising=False)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', primary, raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', require_consensus, raising=False)
    monkeypatch.setattr(bot, 'INTEGRATION_TIEBREAKER', tiebreaker, raising=False)
    monkeypatch.setattr(bot, 'LOG_INTEGRATION_ROUNDS', False, raising=False)
    monkeypatch.setattr(bot, 'claude_trader', True, raising=False)
    monkeypatch.setattr(bot, 'openai_trader', True, raising=False)
    monkeypatch.setattr(bot, 'grok_trader', True, raising=False)
    monkeypatch.setattr(bot, 'perplexity_trader', True, raising=False)
    monkeypatch.setattr(bot, 'get_llm_response', get_llm_response_fn, raising=False)


def _primary_text(votes, primary):
    """Scripted Round-1 text for the primary. Structured providers carry
    their vote as schema JSON (T8); fallback providers as a delimiter tag."""
    pv = votes.get(primary)
    if pv == 'NORESP':
        return None
    if pv is None:
        return "some prose without a tag"
    if primary in bot.STRUCTURED_VOTE_PROVIDERS:
        return _vote_json('ETH', pv)
    return f"analysis <**ETH-PRS-{pv}**>"


def run_case(monkeypatch, llm_mode, compare_llms, primary, require_consensus, tiebreaker, votes):
    """Scripts Round 1 (and Round 2, for integrate mode) votes via a stubbed
    get_llm_response, then calls the real process_coin_with_comparison.

    Returns (decision, trade_fires) where trade_fires runs the REAL T3
    mode-aware trade gate exactly as the call sites do.
    """
    _patch_globals(monkeypatch, llm_mode, compare_llms, primary, require_consensus,
                    tiebreaker, make_fake_get_llm_response(votes))

    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, primary))
    trade_fires = (bot.decision_allows_trade(decision, llm_mode, require_consensus)
                   and bool(decision.action) and 'BUY' in decision.action)
    return decision, trade_fires


# ============================================================================
# Ported scripted-vote matrix (originally 11 cases encoding pre-T3 behavior).
#
# Rows that encoded the old fail-open bugs now assert the T3 fail-closed
# semantics; rows that encoded correct behavior are unchanged.
# exp_consensus refers to the legacy tri-state flag (decision.consensus).
# ============================================================================

COMPARE_CASES = [
    # name, primary, require_consensus, tiebreaker, votes, exp_action, exp_consensus, exp_trade_fires
    ("A1 all BUY",
     'gemini', True, 'gemini', {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'BUY'},
     'BUY', True, True),
    ("A2 2 BUY + 1 HOLD (majority BUY)",
     'gemini', True, 'gemini', {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'HOLD'},
     None, False, False),
    # behavior changed by T3 fail-closed hardening (plan Phase 0):
    # was action='BUY', consensus=True — an API-errored openai silently shrank
    # the quorum and 2 responders formed a "unanimous" BUY (finding 1.1).
    # Now the errored panelist is an abstain and blocks under REQUIRE_CONSENSUS.
    ("A3 BUY + BUY + API-error (finding 1.1 shape)",
     'gemini', True, 'gemini', {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'NORESP'},
     None, False, False),
    # behavior changed by T3 fail-closed hardening (plan Phase 0):
    # was action='BUY', consensus=None — the len(r1_recs)<2 branch fell back
    # to "using first available" and traded a lone vote. Sub-quorum now blocks.
    ("A4 BUY + API-error + API-error (sub-quorum)",
     'gemini', True, 'gemini', {'gemini': 'BUY', 'claude': 'NORESP', 'openai': 'NORESP'},
     None, False, False),
    ("A5 BUY + unparseable-prose + unparseable-prose",
     'gemini', True, 'gemini', {'gemini': 'BUY', 'claude': None, 'openai': None},
     None, False, False),
    # behavior changed by T3 fail-closed hardening (plan Phase 0):
    # was consensus=True — three None votes normalized to '' and "agreed"
    # (empty-string false consensus). Abstains are now excluded from
    # agreement math; zero real votes is a sub-quorum block, consensus=False.
    ("A6 all unparseable prose",
     'gemini', True, 'gemini', {'gemini': None, 'claude': None, 'openai': None},
     None, False, False),
]


@pytest.mark.parametrize(
    "name,primary,require_consensus,tiebreaker,votes,exp_action,exp_consensus,exp_trade_fires",
    COMPARE_CASES, ids=[c[0] for c in COMPARE_CASES],
)
def test_compare_mode_ported(monkeypatch, name, primary, require_consensus, tiebreaker, votes,
                              exp_action, exp_consensus, exp_trade_fires):
    decision, trade_fires = run_case(
        monkeypatch, 'compare', C, primary, require_consensus, tiebreaker, votes)
    assert decision.action == exp_action
    assert decision.consensus == exp_consensus
    assert trade_fires == exp_trade_fires


INTEGRATE_CASES = [
    # behavior changed by T3 fail-closed hardening (plan Phase 0):
    # was action='BUY' — the primary-as-tiebreaker overrode the 2-of-3 HOLD
    # majority (finding 1.2, real ETH buy). REQUIRE_CONSENSUS is now honored
    # in integrate mode: non-unanimous blocks, tiebreaker never consulted.
    ("B1 minority-primary BUY vs 2x HOLD, tiebreaker=primary=gemini (finding 1.2)",
     'gemini', True, 'gemini', {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
     None, False, False),
    # behavior changed by T3 fail-closed hardening (plan Phase 0):
    # was action='HOLD' via the claude tiebreaker — but REQUIRE_CONSENSUS=True
    # now blocks any non-unanimous outcome before the tiebreaker is consulted.
    # (Tiebreaker resolution still works with require_consensus=False; see
    # TestT3TiebreakerResolution.)
    ("B2 same split, tiebreaker=claude (non-primary)",
     'gemini', True, 'claude', {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
     None, False, False),
    ("B3 same split, tiebreaker=none",
     'gemini', True, 'none', {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
     None, False, False),
    # behavior changed by T3 fail-closed hardening (plan Phase 0):
    # was action='BUY' — with the tiebreaker LLM errored out, integrate mode
    # silently fell back to the first LLM (the primary; finding 5.3.2). The
    # errored panelist is now an abstain and blocks under REQUIRE_CONSENSUS.
    ("B4 split, tiebreaker LLM itself errored",
     'gemini', True, 'openai', {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'NORESP'},
     None, False, False),
    ("B5 integrate, require_consensus=False, tiebreaker=none",
     'gemini', False, 'none', {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
     None, False, False),
]


@pytest.mark.parametrize(
    "name,primary,require_consensus,tiebreaker,votes,exp_action,exp_consensus,exp_trade_fires",
    INTEGRATE_CASES, ids=[c[0] for c in INTEGRATE_CASES],
)
def test_integrate_mode_ported(monkeypatch, name, primary, require_consensus, tiebreaker, votes,
                                exp_action, exp_consensus, exp_trade_fires):
    decision, trade_fires = run_case(
        monkeypatch, 'integrate', C, primary, require_consensus, tiebreaker, votes)
    assert decision.action == exp_action
    assert decision.consensus == exp_consensus
    assert trade_fires == exp_trade_fires


# ============================================================================
# T3 fail-closed expectations (written as failing tests pre-T3 per doc 6.4;
# xfail markers removed now that T3 has landed, and assertions tightened to
# the PanelDecision fields the old tuple shape could not express).
# ============================================================================

class TestT3FailClosedExpectations:

    def test_api_errored_panelist_blocks_under_require_consensus(self, monkeypatch):
        """2-of-3 responded and agreed; openai API-errored. The missing
        panelist is an explicit abstain and blocks under REQUIRE_CONSENSUS."""
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'NORESP'},
        )
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('abstain')
        assert decision.abstains == {'openai': 'error'}
        assert decision.votes['openai'] == 'ABSTAIN(error)'
        assert not trade_fires

    def test_sub_quorum_single_responder_blocks(self, monkeypatch):
        """Only 1 of 3 configured LLMs produced a vote (2 API errors).
        The old 'using first available' fallback is gone; sub-quorum blocks."""
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'NORESP', 'openai': 'NORESP'},
        )
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('sub_quorum')
        assert not trade_fires

    def test_integrate_mode_honors_require_consensus(self, monkeypatch):
        """Integrate mode, split vote (1 BUY vs 2 HOLD) after Round 2, with a
        configured tiebreaker (=primary=gemini) and REQUIRE_CONSENSUS=True.
        The tiebreaker is never consulted; the split blocks."""
        decision, trade_fires = run_case(
            monkeypatch, 'integrate', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
        )
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('disagreement')
        # the discarded majority is still recorded for measurement
        assert decision.majority_action == 'HOLD'
        assert not trade_fires

    def test_tiebreaker_absent_from_final_votes_blocks(self, monkeypatch):
        """INTEGRATION_TIEBREAKER is configured as 'perplexity', which isn't
        in COMPARE_LLMS at all, so it can never produce a vote. The old
        first-LLM fallback is gone; an unreachable tiebreaker blocks."""
        decision, trade_fires = run_case(
            monkeypatch, 'integrate', C, 'gemini', False, 'perplexity',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
        )
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('tiebreaker_unavailable')
        assert not trade_fires

    def test_exception_in_multi_llm_block_blocks(self, monkeypatch):
        """get_llm_response raises mid-round for one panelist (claude). The
        old catch-all fallback to the primary's Round-1 vote is gone; an
        exception inside the multi-LLM block yields a blocked decision."""
        def raising_get_llm_response(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
            if llm == 'claude':
                raise RuntimeError('simulated panelist failure')
            votes = {'gemini': 'BUY', 'openai': 'BUY'}
            v = votes.get(llm, 'NORESP')
            if v == 'NORESP':
                return None, None
            return f"analysis <**{coin}-PRS-{v}**>", v

        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini',
                        raising_get_llm_response)

        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('exception')
        assert not bot.decision_allows_trade(decision, 'compare', True)

    def test_two_abstains_is_not_consensus(self, monkeypatch):
        """Two parse-failure abstains + one API-error abstain must never
        register as consensus (the old empty-string normalization made three
        None votes 'agree'). Zero real votes is a sub-quorum block."""
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'gemini',
            {'gemini': None, 'claude': None, 'openai': 'NORESP'},
        )
        assert decision.consensus_state == 'blocked'
        assert decision.consensus is not True
        assert decision.block_reason.startswith('sub_quorum')
        assert decision.abstains == {'gemini': 'parse_failure',
                                     'claude': 'parse_failure',
                                     'openai': 'error'}


# ============================================================================
# New T3 coverage: PanelDecision fields, tiebreaker resolution, the mode-aware
# trade gate, config validation, and history-record fields.
# ============================================================================

class TestT3DecisionObject:

    def test_unanimous_decision_fields(self, monkeypatch):
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'BUY'},
        )
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'unanimous'
        assert decision.votes == {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'BUY'}
        assert decision.abstains == {}
        assert decision.deciding_llms == C
        assert decision.majority_action == 'BUY'
        assert decision.block_reason is None
        assert decision.consensus is True
        assert decision.llm_source == 'gemini,claude,openai'
        assert trade_fires

    def test_blocked_decision_attributes_no_llm(self, monkeypatch):
        decision, _ = run_case(
            monkeypatch, 'integrate', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
        )
        assert decision.deciding_llms == []
        assert decision.llm_source == 'none'
        assert decision.votes == {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'}

    def test_parse_failure_abstain_blocks_under_require_consensus(self, monkeypatch):
        """Quorum of real votes exists (2 BUY) but the parse-failure abstain
        still blocks under REQUIRE_CONSENSUS."""
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'BUY', 'openai': None},
        )
        assert decision.action is None
        assert decision.block_reason.startswith('abstain')
        assert decision.abstains == {'openai': 'parse_failure'}
        assert decision.votes['openai'] == 'ABSTAIN(parse_failure)'
        assert not trade_fires

    def test_abstain_excluded_from_agreement_without_require_consensus(self, monkeypatch):
        """Without REQUIRE_CONSENSUS an abstain is excluded from agreement
        math: the two remaining real votes agreeing is a unanimous panel."""
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', False, 'none',
            {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'NORESP'},
        )
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'unanimous'
        assert decision.deciding_llms == ['gemini', 'claude']
        assert decision.abstains == {'openai': 'error'}
        assert trade_fires

    def test_majority_action_none_on_tie(self, monkeypatch):
        decision, _ = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'none',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'NORESP'},
        )
        assert decision.action is None
        assert decision.majority_action is None  # 1-1 tie among real votes

    def test_single_llm_mode_fields_and_gate(self, monkeypatch):
        _patch_globals(monkeypatch, 'gemini', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({}))
        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'single'
        assert decision.consensus is None  # legacy: consensus n/a for single LLM
        assert decision.deciding_llms == ['gemini']
        assert decision.votes == {'gemini': 'BUY'}
        # action alone decides in single-LLM mode, even with REQUIRE_CONSENSUS
        assert bot.decision_allows_trade(decision, 'gemini', True)

    def test_single_llm_mode_abstain_no_trade(self, monkeypatch):
        _patch_globals(monkeypatch, 'gemini', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({}))
        decision = bot.process_coin_with_comparison('ETH', "prose without a tag")
        assert decision.action is None
        assert decision.consensus_state == 'single'
        assert decision.abstains == {'gemini': 'parse_failure'}
        assert not bot.decision_allows_trade(decision, 'gemini', True)


class TestT3TiebreakerResolution:

    def test_tiebreaker_resolves_without_require_consensus_integrate(self, monkeypatch):
        decision, trade_fires = run_case(
            monkeypatch, 'integrate', C, 'gemini', False, 'claude',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
        )
        assert decision.action == 'HOLD'
        assert decision.consensus_state == 'tiebreaker'
        assert decision.deciding_llms == ['claude']
        assert decision.llm_source == 'claude'
        assert decision.consensus is False
        assert not trade_fires  # gate allows the decision, but HOLD is not a BUY

    def test_tiebreaker_buy_trades_without_require_consensus(self, monkeypatch):
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', False, 'claude',
            {'gemini': 'HOLD', 'claude': 'BUY', 'openai': 'HOLD'},
        )
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'tiebreaker'
        assert trade_fires

    def test_tiebreaker_errored_blocks_without_require_consensus(self, monkeypatch):
        """The configured tiebreaker API-errored out of the panel. Without
        REQUIRE_CONSENSUS the abstain doesn't block by itself, but the split
        cannot be resolved by an absent tiebreaker: block, no substitution."""
        decision, trade_fires = run_case(
            monkeypatch, 'integrate', C, 'gemini', False, 'openai',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'NORESP'},
        )
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('tiebreaker_unavailable')
        assert not trade_fires

    def test_tiebreaker_is_primary_runtime_defense(self, monkeypatch):
        """Startup config validation downgrades tiebreaker==primary to 'none';
        if a primary tiebreaker reaches resolution anyway, it fails closed."""
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', False, 'gemini',
            {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
        )
        assert decision.action is None
        assert decision.block_reason.startswith('tiebreaker_is_primary')
        assert not trade_fires

    def test_integrate_skips_round2_when_error_abstain_guarantees_block(self, monkeypatch):
        """Under REQUIRE_CONSENSUS an error-abstainer can never re-enter in
        Round 2, so the guaranteed-blocked decision is made without spending
        Round-2 API calls (no get_llm_response call carries peer_analysis)."""
        calls = []
        votes = {'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'NORESP'}
        _patch_globals(monkeypatch, 'integrate', C, 'gemini', True, 'none',
                        make_fake_get_llm_response(votes, calls))
        decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('abstain')
        assert all(peer is None for _, peer in calls)


class TestT3TradeGate:
    """decision_allows_trade truth table (T3(c)). A naive `consensus is True`
    gate would brick single-LLM modes; the gate is mode-aware."""

    def _d(self, action, state):
        return bot.PanelDecision(action=action, consensus_state=state)

    @pytest.mark.parametrize("mode", ['gemini', 'claude', 'openai', 'grok', 'perplexity'])
    def test_single_llm_modes_action_alone_decides(self, mode):
        assert bot.decision_allows_trade(self._d('BUY', 'single'), mode, True)
        assert bot.decision_allows_trade(self._d('BUY', 'single'), mode, False)
        assert not bot.decision_allows_trade(self._d(None, 'single'), mode, True)

    @pytest.mark.parametrize("mode", ['compare', 'integrate'])
    def test_multi_mode_with_require_consensus_unanimous_only(self, mode):
        assert bot.decision_allows_trade(self._d('BUY', 'unanimous'), mode, True)
        assert not bot.decision_allows_trade(self._d('BUY', 'tiebreaker'), mode, True)
        assert not bot.decision_allows_trade(self._d(None, 'blocked'), mode, True)

    @pytest.mark.parametrize("mode", ['compare', 'integrate'])
    def test_multi_mode_without_require_consensus_allows_tiebreaker(self, mode):
        assert bot.decision_allows_trade(self._d('BUY', 'unanimous'), mode, False)
        assert bot.decision_allows_trade(self._d('BUY', 'tiebreaker'), mode, False)
        assert not bot.decision_allows_trade(self._d(None, 'blocked'), mode, False)

    def test_no_decision_or_no_action_never_trades(self):
        assert not bot.decision_allows_trade(None, 'compare', False)
        assert not bot.decision_allows_trade(self._d(None, 'unanimous'), 'compare', False)

    def test_unknown_state_fails_closed(self):
        assert not bot.decision_allows_trade(self._d('BUY', 'garbage'), 'compare', False)


class TestT3ConfigValidation:
    """validate_tiebreaker_config: tiebreaker == primary is downgraded to
    'none' with a loud warning in multi-LLM modes (doc 1.2)."""

    def test_tiebreaker_equal_primary_downgraded_with_warning(self, capsys):
        result = bot.validate_tiebreaker_config('gemini', 'gemini', 'integrate')
        out = capsys.readouterr().out
        assert result == 'none'
        assert 'CONFIG WARNING' in out
        assert 'PRIMARY_LLM' in out

    def test_tiebreaker_equal_primary_downgraded_in_compare_mode(self, capsys):
        assert bot.validate_tiebreaker_config('claude', 'claude', 'compare') == 'none'
        assert 'CONFIG WARNING' in capsys.readouterr().out

    def test_distinct_tiebreaker_unchanged(self, capsys):
        assert bot.validate_tiebreaker_config('claude', 'gemini', 'integrate') == 'claude'
        assert 'CONFIG WARNING' not in capsys.readouterr().out

    def test_none_tiebreaker_unchanged(self, capsys):
        assert bot.validate_tiebreaker_config('none', 'gemini', 'integrate') == 'none'
        assert 'CONFIG WARNING' not in capsys.readouterr().out

    def test_single_llm_mode_not_validated(self, capsys):
        # tiebreaker is irrelevant in single-LLM modes; no confusing warning
        assert bot.validate_tiebreaker_config('gemini', 'gemini', 'gemini') == 'gemini'
        assert 'CONFIG WARNING' not in capsys.readouterr().out


class TestT3HistoryRecordFields:
    """create_recommendation_record accepts action 'NONE' and the optional
    T3 panel-decision fields; legacy calls keep the old record shape."""

    _base = dict(coin_symbol='ETH', price=1900.0, bid_price=1899.0,
                 ask_price=1901.0, mode='compare')

    def test_blocked_decision_record_fields(self):
        record = historyutil.create_recommendation_record(
            recommendation='NONE',
            llm_source='none',
            consensus=False,
            consensus_state='blocked',
            deciding_llms=[],
            votes={'gemini': 'BUY', 'claude': 'BUY', 'openai': 'ABSTAIN(error)'},
            block_reason='abstain: openai(error)',
            majority_action='BUY',
            **self._base,
        )
        assert record['recommendation'] == 'NONE'
        assert record['llm_source'] == 'none'
        assert record['consensus_state'] == 'blocked'
        assert record['deciding_llms'] == []
        assert record['votes'] == {'gemini': 'BUY', 'claude': 'BUY',
                                   'openai': 'ABSTAIN(error)'}
        assert record['block_reason'] == 'abstain: openai(error)'
        assert record['majority_action'] == 'BUY'

    def test_legacy_call_keeps_old_shape(self):
        record = historyutil.create_recommendation_record(
            recommendation='BUY',
            llm_source='gemini',
            consensus=True,
            **self._base,
        )
        for key in ('consensus_state', 'deciding_llms', 'votes',
                    'block_reason', 'majority_action'):
            assert key not in record
        assert record['recommendation'] == 'BUY'

    def test_deciding_llms_attribution(self):
        record = historyutil.create_recommendation_record(
            recommendation='HOLD',
            llm_source='claude',
            consensus=False,
            consensus_state='tiebreaker',
            deciding_llms=['claude'],
            votes={'gemini': 'BUY', 'claude': 'HOLD', 'openai': 'HOLD'},
            majority_action='HOLD',
            **self._base,
        )
        assert record['llm_source'] == 'claude'
        assert record['deciding_llms'] == ['claude']
        assert 'block_reason' not in record


# ============================================================================
# T8: structured-output votes flowing into PanelDecision. The primary's text
# is resolved through the REAL structured path (voteschema JSON), and Abstain
# markers from get_llm_response carry their reasons into the abstain set.
# ============================================================================

class TestT8StructuredIntegration:

    def test_primary_explicit_refusal_blocks_as_refusal(self, monkeypatch):
        """A structured abstain=true from the primary is a first-class
        'refusal' abstain — distinct from parse_failure — and blocks under
        REQUIRE_CONSENSUS even though both other panelists voted BUY."""
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({'claude': 'BUY', 'openai': 'BUY'}))
        refusal = _vote_json('ETH', 'HOLD', abstain=True, confidence=0.0)
        decision = bot.process_coin_with_comparison('ETH', refusal)
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.abstains == {'gemini': 'refusal'}
        assert decision.votes['gemini'] == 'ABSTAIN(refusal)'
        assert decision.block_reason.startswith('abstain')
        assert not bot.decision_allows_trade(decision, 'compare', True)

    def test_primary_symbol_mismatch_blocks(self, monkeypatch):
        """A schema-valid BUY for the WRONG coin (DOGE while analyzing ETH)
        must never count as an ETH vote: abstain(symbol_mismatch)."""
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({'claude': 'BUY', 'openai': 'BUY'}))
        wrong_coin = _vote_json('ETH', 'BUY', symbol='DOGE')
        decision = bot.process_coin_with_comparison('ETH', wrong_coin)
        assert decision.action is None
        assert decision.abstains == {'gemini': 'symbol_mismatch'}
        assert decision.votes['gemini'] == 'ABSTAIN(symbol_mismatch)'
        assert not bot.decision_allows_trade(decision, 'compare', True)

    def test_primary_full_name_symbol_binds(self, monkeypatch):
        """'Ethereum' binds to ETH via the conservative alias map: the vote
        counts and a fully unanimous panel trades."""
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({'claude': 'BUY', 'openai': 'BUY'}))
        named = _vote_json('ETH', 'BUY', symbol='Ethereum')
        decision = bot.process_coin_with_comparison('ETH', named)
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'unanimous'
        assert decision.votes == {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'BUY'}
        assert bot.decision_allows_trade(decision, 'compare', True)

    def test_primary_schema_violation_is_parse_failure(self, monkeypatch):
        """Structurally invalid JSON from a structured provider maps to
        abstain(parse_failure) — and a delimiter tag in a structured
        provider's output no longer counts for anything."""
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({'claude': 'BUY', 'openai': 'BUY'}))
        # old-style tag output from a structured provider: not JSON -> abstain
        decision = bot.process_coin_with_comparison('ETH', "analysis <**ETH-PRS-BUY**>")
        assert decision.action is None
        assert decision.abstains == {'gemini': 'parse_failure'}

    def test_panelist_abstain_marker_reason_flows_through(self, monkeypatch):
        """An Abstain marker returned by get_llm_response (as the real T8
        resolution does for refusals) lands in PanelDecision.abstains with
        its own reason, not the legacy error/parse_failure mapping."""
        def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
            if llm == 'claude':
                return (_vote_json(coin, 'HOLD', abstain=True),
                        voteschema.Abstain('refusal'))
            if llm == 'openai':
                return (_vote_json(coin, 'BUY', symbol='DOGE'),
                        voteschema.Abstain('symbol_mismatch'))
            return None, None
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini', fake)
        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.abstains == {'claude': 'refusal',
                                     'openai': 'symbol_mismatch'}
        assert decision.votes['claude'] == 'ABSTAIN(refusal)'
        assert decision.votes['openai'] == 'ABSTAIN(symbol_mismatch)'

    def test_refusal_excluded_from_agreement_without_require_consensus(self, monkeypatch):
        """Without REQUIRE_CONSENSUS a refusal abstain is excluded from the
        agreement math (same policy as error abstains): the two remaining
        real votes agreeing is a unanimous panel."""
        def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
            if llm == 'openai':
                return (_vote_json(coin, 'HOLD', abstain=True),
                        voteschema.Abstain('refusal'))
            return f"analysis <**{coin}-PRS-BUY**>", 'BUY'
        _patch_globals(monkeypatch, 'compare', C, 'gemini', False, 'none', fake)
        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'unanimous'
        assert decision.deciding_llms == ['gemini', 'claude']
        assert decision.abstains == {'openai': 'refusal'}

    def test_empty_at_cap_is_parse_failure_not_vote(self, monkeypatch):
        """'' (responded, no visible text — the reasoning-token trap) maps to
        abstain(parse_failure) for a structured provider, never a vote and
        never a bare 'error'."""
        _patch_globals(monkeypatch, 'gemini', C, 'gemini', True, 'gemini',
                        make_fake_get_llm_response({}))
        decision = bot.process_coin_with_comparison('ETH', "")
        assert decision.action is None
        assert decision.abstains == {'gemini': 'parse_failure'}
        assert not bot.decision_allows_trade(decision, 'gemini', True)


class TestT8ResolveVote:
    """resolve_vote: the provider-aware seam between raw response text and
    the consensus tallies."""

    def test_structured_provider_parses_json(self, capsys):
        rec = bot.resolve_vote('claude', _vote_json('BTC', 'SELL'), 'BTC')
        assert rec == 'SELL'
        out = capsys.readouterr().out
        assert '[STRUCTURED VOTE]' in out
        assert '[FALLBACK PARSER]' not in out

    def test_structured_provider_ignores_delimiter_tag(self):
        rec = bot.resolve_vote('openai', "analysis <**BTC-PRS-BUY**>", 'BTC')
        assert rec == voteschema.Abstain('parse_failure')

    def test_structured_refusal_and_mismatch(self):
        assert bot.resolve_vote(
            'gemini', _vote_json('BTC', 'BUY', abstain=True), 'BTC'
        ) == voteschema.Abstain('refusal')
        assert bot.resolve_vote(
            'gemini', _vote_json('BTC', 'BUY', symbol='ETH'), 'BTC'
        ) == voteschema.Abstain('symbol_mismatch')

    def test_structured_empty_text_is_parse_failure(self):
        assert bot.resolve_vote('gemini', '', 'BTC') == voteschema.Abstain('parse_failure')
        assert bot.resolve_vote('gemini', '   ', 'BTC') == voteschema.Abstain('parse_failure')

    def test_no_response_is_none_for_legacy_error_mapping(self):
        assert bot.resolve_vote('gemini', None, 'BTC') is None
        assert bot.resolve_vote('perplexity', None, 'BTC') is None

    def test_fallback_provider_parses_tag_with_loud_log(self, capsys):
        rec = bot.resolve_vote('perplexity', "analysis <**BTC-PRS-BUY**>", 'BTC')
        assert rec == 'BUY'
        out = capsys.readouterr().out
        assert '[FALLBACK PARSER] perplexity/BTC' in out

    def test_fallback_provider_symbol_mismatch_abstains(self, capsys):
        rec = bot.resolve_vote('grok', "ETH analysis <**DOGE-PRS-BUY**>", 'ETH')
        assert rec == voteschema.Abstain('symbol_mismatch')
        assert 'symbol_mismatch' in capsys.readouterr().out

    def test_fallback_provider_full_name_tag_binds(self):
        rec = bot.resolve_vote('grok', "analysis <**Ethereum-PRS-HOLD**>", 'ETH')
        assert rec == 'HOLD'

    def test_fallback_provider_no_tag_is_none(self):
        assert bot.resolve_vote('perplexity', "prose without a tag", 'BTC') is None


# ============================================================================
# F1: a panelist whose API client failed to CONSTRUCT at startup is a
# STANDING abstain('client_init_failure') — it stays in the votes dict,
# counts against quorum, and blocks under REQUIRE_CONSENSUS. Pre-F1, main()
# pruned the provider out of COMPARE_LLMS: the panelist vanished with no
# abstain recorded and the quorum silently shrank (the 2026-07-18 eval's
# finding 1.1, one layer up).
# ============================================================================

class TestF1ClientInitFailure:

    def _delegate_to_real(self, failed_llm, votes):
        """Fake get_llm_response that scripts healthy panelists but routes
        `failed_llm` through the REAL get_llm_response, so the standing-
        abstain guard itself is exercised. Captures the real function BEFORE
        _patch_globals replaces the module attribute."""
        real = bot.get_llm_response

        def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
            if llm == failed_llm:
                return real(llm, coin, use_trend_check, peer_analysis, trends_data)
            v = votes[llm]
            return f"analysis <**{coin}-PRS-{v}**>", v
        return fake

    def test_register_records_reason_and_never_prunes_the_panel(self, monkeypatch, capsys):
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {})
        monkeypatch.setattr(bot, 'COMPARE_LLMS', list(C), raising=False)
        detail = bot.register_client_init_failure('openai', RuntimeError('no api key'))
        assert detail == 'RuntimeError: no api key'
        assert bot.FAILED_INIT_LLMS == {'openai': 'RuntimeError: no api key'}
        assert bot.COMPARE_LLMS == C  # the panel is NOT pruned
        out = capsys.readouterr().out
        assert 'client_init_failure' in out
        assert 'quorum' in out

    def test_get_llm_response_standing_abstain_never_consults_client(self, monkeypatch, capsys):
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'claude': 'RuntimeError: boom'})

        class Grenade:
            """Any method access proves the dead client was consulted."""
            def __getattr__(self, name):
                raise AssertionError('dead client must never be consulted')
        monkeypatch.setattr(bot, 'claude_trader', Grenade(), raising=False)

        resp, rec = bot.get_llm_response('claude', 'ETH', False)
        assert resp is None
        assert rec == voteschema.Abstain('client_init_failure')
        assert 'STANDING ABSTAIN' in capsys.readouterr().out

    def test_mixed_panel_blocks_under_require_consensus(self, monkeypatch):
        """2 healthy panelists agree on BUY; the third's client failed init.
        Under REQUIRE_CONSENSUS the standing abstain blocks — the quorum
        never silently shrinks to the two responders."""
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'openai': 'RuntimeError: boom'})
        fake = self._delegate_to_real('openai', {'claude': 'BUY'})
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini', fake)

        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason == 'abstain: openai(client_init_failure)'
        assert decision.abstains == {'openai': 'client_init_failure'}
        assert decision.votes == {'gemini': 'BUY', 'claude': 'BUY',
                                  'openai': 'ABSTAIN(client_init_failure)'}
        assert not bot.decision_allows_trade(decision, 'compare', True)

    def test_failed_init_counts_against_quorum(self, monkeypatch):
        """Two-LLM panel with one failed init: a single real vote is
        sub-quorum even WITHOUT require_consensus — the dead panelist never
        shrinks the denominator (the pre-F1 prune did exactly that)."""
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'claude': 'boom'})
        fake = self._delegate_to_real('claude', {})
        _patch_globals(monkeypatch, 'compare', ['gemini', 'claude'], 'gemini',
                       False, 'none', fake)

        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason == 'sub_quorum: only 1 of 2 panelist(s) produced a vote'
        assert decision.abstains == {'claude': 'client_init_failure'}

    def test_failed_init_excluded_from_agreement_without_require_consensus(self, monkeypatch):
        """Without REQUIRE_CONSENSUS the standing abstain follows the same
        policy as error abstains: excluded from agreement math, recorded in
        the breakdown, and the remaining quorum may decide."""
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'openai': 'boom'})
        fake = self._delegate_to_real('openai', {'claude': 'BUY'})
        _patch_globals(monkeypatch, 'compare', C, 'gemini', False, 'none', fake)

        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'unanimous'
        assert decision.deciding_llms == ['gemini', 'claude']
        assert decision.abstains == {'openai': 'client_init_failure'}
        assert decision.votes['openai'] == 'ABSTAIN(client_init_failure)'
        assert bot.decision_allows_trade(decision, 'compare', False)

    def test_single_llm_mode_failed_client_blocked_and_recorded(self, monkeypatch, capsys):
        """Single-LLM mode with a dead client: no trade, loud error, and the
        decision arrives as state='blocked' (NOT 'single') so the call sites'
        record gate (`final_action or state != 'single'`) writes it to
        history — never a silent no-op."""
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'claude': 'AuthError: bad key'})
        _patch_globals(monkeypatch, 'claude', C, 'gemini', True, 'gemini',
                       make_fake_get_llm_response({}))

        decision = bot.process_coin_with_comparison('ETH', None)
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason.startswith('client_init_failure')
        assert 'AuthError: bad key' in decision.block_reason
        assert decision.abstains == {'claude': 'client_init_failure'}
        assert decision.votes == {'claude': 'ABSTAIN(client_init_failure)'}
        assert not bot.decision_allows_trade(decision, 'claude', True)
        assert '[BLOCKED]' in capsys.readouterr().out
        # the property that makes the call sites record it:
        assert decision.consensus_state != 'single'

    def test_single_llm_mode_failed_client_when_also_primary(self, monkeypatch):
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'gemini': 'boom'})
        _patch_globals(monkeypatch, 'gemini', C, 'gemini', True, 'gemini',
                       make_fake_get_llm_response({}))
        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.abstains == {'gemini': 'client_init_failure'}

    def test_primary_failed_init_discards_round1_text(self, monkeypatch):
        """A dead-client PRIMARY is a standing abstain even when Round-1 text
        exists — the text cannot have come from the dead client (it would be
        a fallback substitution) and must never resolve as the primary's
        vote."""
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'gemini': 'boom'})
        _patch_globals(monkeypatch, 'compare', C, 'gemini', True, 'gemini',
                       make_fake_get_llm_response({'claude': 'BUY', 'openai': 'BUY'}))

        # a schema-valid BUY payload as Round-1 text: still discarded
        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.action is None
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason == 'abstain: gemini(client_init_failure)'
        assert decision.abstains == {'gemini': 'client_init_failure'}

    def test_get_primary_coin_check_no_fallback_substitution(self, monkeypatch, capsys):
        """get_primary_coin_check must NOT fall through to the Gemini
        substitution when the primary's client failed init."""
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'claude': 'boom'})
        monkeypatch.setattr(bot, 'PRIMARY_LLM', 'claude', raising=False)
        assert bot.get_primary_coin_check('ETH') is None
        out = capsys.readouterr().out
        assert 'no fallback substitution' in out
        assert 'falling back to Gemini' not in out

    def test_integrate_mode_failed_init_blocks_without_round2_spend(self, monkeypatch):
        """Integrate mode: a failed-init panelist is an error-class abstainer;
        under REQUIRE_CONSENSUS the guaranteed block is decided without
        spending Round-2 API calls (mirrors the T3 short-circuit)."""
        calls = []
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {'openai': 'boom'})
        real = bot.get_llm_response

        def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
            calls.append((llm, peer_analysis))
            if llm == 'openai':
                return real(llm, coin, use_trend_check, peer_analysis, trends_data)
            return f"analysis <**{coin}-PRS-BUY**>", 'BUY'
        _patch_globals(monkeypatch, 'integrate', C, 'gemini', True, 'none', fake)

        decision = bot.process_coin_with_comparison('ETH', _vote_json('ETH', 'BUY'))
        assert decision.consensus_state == 'blocked'
        assert decision.block_reason == 'abstain: openai(client_init_failure)'
        assert all(peer is None for _, peer in calls)

    def test_healthy_panel_unaffected_when_registry_empty(self, monkeypatch):
        monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {})
        decision, trade_fires = run_case(
            monkeypatch, 'compare', C, 'gemini', True, 'gemini',
            {'gemini': 'BUY', 'claude': 'BUY', 'openai': 'BUY'},
        )
        assert decision.action == 'BUY'
        assert decision.consensus_state == 'unanimous'
        assert trade_fires


# ============================================================================
# F6: concluding-tag rule instrumentation (semantics UNCHANGED — measured
# 2026-07-18: the entire available grok/perplexity raw-response corpus
# showed zero concluding-rule rejections, so the fail-closed rule stands).
# The distinguishing log line makes any future over-abstain countable.
# ============================================================================

class TestF6ConcludingTagInstrumentation:

    def test_trailing_boilerplate_still_abstains_with_distinct_log(self, capsys):
        """A genuine vote followed by a trailing Sources block still fails
        closed (no vote), but the log now names the concluding-tag rule so
        over-abstains are measurable from run logs."""
        text = ("Analysis...\n<**BTC-PRS-BUY**>\n\nSources:\n"
                "[1] example.com/a\n[2] example.com/b")
        assert bot.resolve_vote('perplexity', text, 'BTC') is None
        out = capsys.readouterr().out
        assert 'trailing content' in out
        assert 'concluding-tag rule' in out

    def test_contradicting_prose_after_tag_still_abstains(self, capsys):
        """The case that motivated the rule: prose after the tag that
        CONTRADICTS it must never be recovered as a vote."""
        text = ("<**BTC-PRS-BUY**>\nActually, on reflection the data is too "
                "weak - I would recommend selling instead.")
        assert bot.resolve_vote('grok', text, 'BTC') is None
        assert 'trailing content' in capsys.readouterr().out

    def test_no_tag_failure_is_not_mislabeled(self, capsys):
        """A response with no tag at all must NOT emit the concluding-rule
        line (that would poison the measurement)."""
        assert bot.resolve_vote('perplexity', 'prose without any tag', 'BTC') is None
        assert 'trailing content' not in capsys.readouterr().out

    def test_backticked_cited_tag_is_no_tag_not_trailing(self, capsys):
        """A refusal citing the format in backticks is a NO-TAG failure (the
        span is stripped before matching), not a concluding-rule rejection."""
        text = "I can't. The format would be `<**BTC-PRS-BUY**>` but I decline."
        assert bot.resolve_vote('grok', text, 'BTC') is None
        assert 'trailing content' not in capsys.readouterr().out

    def test_clean_concluding_tag_still_parses(self, capsys):
        """Corpus-shaped success: citations BEFORE the tag and bracketed
        markers after it keep parsing — instrumentation changed no
        semantics."""
        text = "analysis with citations [2][4]\n<**BTC-PRS-HOLD**> [1][2]"
        assert bot.resolve_vote('perplexity', text, 'BTC') == 'HOLD'
        assert 'trailing content' not in capsys.readouterr().out
