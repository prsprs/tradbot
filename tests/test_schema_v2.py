"""Tests for WS3 (schema v2: persist the full decision record).

Covers:
  1. vote_details (per-LLM {action, confidence}) is populated on DIRECTIONAL
     (unanimous/tiebreaker/single) AND on BLOCKED decisions by
     process_coin_with_comparison -- confidence round-trips as a float for a
     real structured vote and as None for an abstain / non-JSON fallback.
  2. create_recommendation_record writes the v2 fields when supplied, and is
     byte-identical to a v1 record when they are omitted (backward compat).
  3. A legacy v1 record and an equivalent v2 record score IDENTICALLY through
     tradeanalyzer.score_record (analyzer tolerates unknown fields).
  4. write_market_blocks writes {coin: block} under the redirected HISTORY_DIR
     and returns the relative ref; a write FAILURE warns and returns None
     (never raises); market_block_ref is stable/relative.
  5. prompt_hash is stable for the same prompt and differs for a different one.
  6. _record_provenance assembles the schema-v2 kwargs (schema_version, models,
     prompt_hash, market_block_ref, per-coin market_block_present).

All offline/mocked -- no network, no live trading, no real history/ writes.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot
import historyutil
import tradeanalyzer as ta
import voteschema


# ---------------------------------------------------------------------------
# Panel-decision scaffolding (mirrors tests/test_consensus.py's approach, but
# every panelist returns schema JSON so per-LLM confidence is controllable).
# ---------------------------------------------------------------------------

def _json_vote(coin, action, confidence, abstain=False):
    return json.dumps({
        "symbol": coin, "action": action, "confidence": confidence,
        "abstain": abstain, "reasons": ["scripted"],
    })


def _fake_get_llm_response(votes):
    """votes: llm -> (action, confidence) | 'NORESP'. Non-primary panelists
    answer with schema JSON so _vote_confidence can parse a real float."""
    def fake(llm, coin, use_trend_check, peer_analysis=None, trends_data=None):
        v = votes.get(llm, 'NORESP')
        if v == 'NORESP':
            return None, None
        action, conf = v
        text = _json_vote(coin, action, conf)
        return text, action
    return fake


def _patch_panel(monkeypatch, votes, primary='gemini',
                 compare=('gemini', 'claude', 'openai'),
                 require_consensus=True, tiebreaker='none', mode='compare'):
    monkeypatch.setattr(bot, 'LLM_MODE', mode, raising=False)
    monkeypatch.setattr(bot, 'COMPARE_LLMS', list(compare), raising=False)
    monkeypatch.setattr(bot, 'PRIMARY_LLM', primary, raising=False)
    monkeypatch.setattr(bot, 'REQUIRE_CONSENSUS', require_consensus, raising=False)
    monkeypatch.setattr(bot, 'INTEGRATION_TIEBREAKER', tiebreaker, raising=False)
    monkeypatch.setattr(bot, 'LOG_INTEGRATION_ROUNDS', False, raising=False)
    for t in ('claude_trader', 'openai_trader', 'grok_trader', 'perplexity_trader'):
        monkeypatch.setattr(bot, t, True, raising=False)
    monkeypatch.setattr(bot, 'get_llm_response', _fake_get_llm_response(votes),
                        raising=False)
    monkeypatch.setattr(bot, 'FAILED_INIT_LLMS', {}, raising=False)


def _primary_text(votes, primary):
    v = votes.get(primary)
    if v == 'NORESP' or v is None:
        return None
    action, conf = v
    return _json_vote('ETH', action, conf)


# ---------------------------------------------------------------------------
# 1. vote_details populated on directional AND blocked decisions
# ---------------------------------------------------------------------------

def test_directional_record_carries_vote_details_with_float_confidence(monkeypatch):
    votes = {'gemini': ('BUY', 0.9), 'claude': ('BUY', 0.8), 'openai': ('BUY', 0.7)}
    _patch_panel(monkeypatch, votes)
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))

    assert decision.action == 'BUY'
    assert decision.consensus_state == 'unanimous'
    # every panelist represented, each with its float confidence
    assert set(decision.vote_details) == {'gemini', 'claude', 'openai'}
    assert decision.vote_details['gemini'] == {'action': 'BUY', 'confidence': 0.9}
    assert decision.vote_details['claude'] == {'action': 'BUY', 'confidence': 0.8}
    assert decision.vote_details['openai'] == {'action': 'BUY', 'confidence': 0.7}


def test_blocked_record_carries_vote_details_with_null_confidence(monkeypatch):
    # openai errored (no response) -> abstain('error'); under REQUIRE_CONSENSUS
    # this blocks. The blocked decision still records vote_details for all.
    votes = {'gemini': ('BUY', 0.6), 'claude': ('BUY', 0.55), 'openai': 'NORESP'}
    _patch_panel(monkeypatch, votes)
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))

    assert decision.action is None
    assert decision.consensus_state == 'blocked'
    assert decision.vote_details['gemini'] == {'action': 'BUY', 'confidence': 0.6}
    assert decision.vote_details['claude'] == {'action': 'BUY', 'confidence': 0.55}
    # the abstainer: action None, confidence null (float and null both round-trip)
    assert decision.vote_details['openai'] == {'action': None, 'confidence': None}


def test_single_llm_directional_carries_vote_details(monkeypatch):
    votes = {'gemini': ('BUY', 0.42)}
    _patch_panel(monkeypatch, votes, mode='gemini', compare=('gemini',))
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))
    assert decision.consensus_state == 'single'
    assert decision.vote_details == {'gemini': {'action': 'BUY', 'confidence': 0.42}}


def test_vote_confidence_none_for_non_json_fallback():
    # a delimiter-tag (fallback provider) response is not JSON -> None, never raises
    assert bot._vote_confidence("analysis <**ETH-PRS-BUY**>") is None
    assert bot._vote_confidence(None) is None
    assert bot._vote_confidence("") is None


# ---------------------------------------------------------------------------
# 2. create_recommendation_record: v2 fields present; omission == v1
# ---------------------------------------------------------------------------

_BASE = dict(
    coin_symbol='ETH', recommendation='BUY', price=1900.0,
    bid_price=1899.0, ask_price=1901.0, llm_source='gemini,claude,openai',
    mode='compare',
)


def test_v2_fields_written_when_supplied():
    rec = historyutil.create_recommendation_record(
        schema_version=2,
        vote_details={'gemini': {'action': 'BUY', 'confidence': 0.9},
                      'openai': {'action': None, 'confidence': None}},
        prompt_hash='abc123def4567890',
        models={'gemini': 'gemini-3.1-pro-preview', 'openai': 'gpt-5.5'},
        market_block_ref='market_blocks/run_x.json',
        market_block_present=True,
        **_BASE,
    )
    assert rec['schema_version'] == 2
    assert rec['vote_details']['gemini'] == {'action': 'BUY', 'confidence': 0.9}
    assert rec['vote_details']['openai'] == {'action': None, 'confidence': None}
    assert rec['prompt_hash'] == 'abc123def4567890'
    assert rec['models'] == {'gemini': 'gemini-3.1-pro-preview', 'openai': 'gpt-5.5'}
    assert rec['market_block_ref'] == 'market_blocks/run_x.json'
    assert rec['market_block_present'] is True


def test_v1_record_byte_identical_when_v2_fields_omitted():
    rec = historyutil.create_recommendation_record(trading_mode='whatif', **_BASE)
    for k in ('schema_version', 'vote_details', 'prompt_hash', 'models',
              'market_block_ref', 'market_block_present'):
        assert k not in rec


# ---------------------------------------------------------------------------
# 3. Analyzer tolerance: v2 scores identically to an equivalent v1 record
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
BTC = 'BTC'


def _score(rec):
    ts = (NOW - timedelta(hours=48))
    rec = dict(rec)
    rec.setdefault('id', 'r1')
    rec['timestamp'] = ts.isoformat() + 'Z'
    p = ta.MappingPriceProvider(
        current={'DOGE': 0.12, BTC: 61000.0},
        historical={(BTC, ts.isoformat()): 60000.0},
    )
    return ta.score_record(rec, NOW, 24, 2.4, BTC, p, [], {})


def test_v2_record_scores_identically_to_v1():
    v1 = dict(coin_symbol='DOGE', recommendation='BUY',
              price_at_recommendation=0.10, bid_price=0.10, ask_price=0.10,
              llm_source='gemini', mode='compare', trading_mode='whatif',
              run_id='run_a')
    v2 = dict(v1)
    v2.update(schema_version=2,
              vote_details={'gemini': {'action': 'BUY', 'confidence': 0.9}},
              prompt_hash='deadbeefdeadbeef',
              models={'gemini': 'gemini-3.1-pro-preview'},
              market_block_ref='market_blocks/run_a.json',
              market_block_present=True)

    s1, s2 = _score(v1), _score(v2)
    assert s1.category == s2.category == ta.SCORED
    assert s1.outcome == s2.outcome
    assert s1.excess_return_pct == s2.excess_return_pct
    assert s1.coin_return_pct == s2.coin_return_pct


def test_v1_and_v2_blocked_records_score_identically():
    v1 = dict(coin_symbol='ETH', recommendation='NONE',
              price_at_recommendation=None, bid_price=None, ask_price=None,
              llm_source='none', mode='compare', trading_mode='whatif',
              block_reason='disagreement: no unanimous consensus')
    v2 = dict(v1, schema_version=2,
              vote_details={'gemini': {'action': 'BUY', 'confidence': 0.9},
                            'claude': {'action': 'HOLD', 'confidence': 0.4}})
    s1, s2 = _score(v1), _score(v2)
    assert s1.category == s2.category == ta.BLOCKED
    assert s1.reason == s2.reason


# ---------------------------------------------------------------------------
# 4. Market-block persistence: written under HISTORY_DIR; failure warns
# ---------------------------------------------------------------------------

def test_write_market_blocks_under_redirected_history_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(historyutil, 'RECOMMENDATIONS_FILE',
                        str(tmp_path / 'history' / 'recommendations.json'))
    ref = historyutil.write_market_blocks('run_20260720T101112Z',
                                          {'BTC': 'BTC block', 'ETH': 'ETH block'})
    assert ref == 'market_blocks/run_20260720T101112Z.json'
    out = tmp_path / 'history' / 'market_blocks' / 'run_20260720T101112Z.json'
    assert out.exists()
    assert json.loads(out.read_text()) == {'BTC': 'BTC block', 'ETH': 'ETH block'}


def test_write_market_blocks_empty_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(historyutil, 'RECOMMENDATIONS_FILE',
                        str(tmp_path / 'history' / 'recommendations.json'))
    assert historyutil.write_market_blocks('run_x', {}) is None


def test_write_market_blocks_failure_warns_but_does_not_raise(tmp_path, monkeypatch, capsys):
    # Make the history dir a regular FILE so makedirs(<dir>/market_blocks) fails.
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a dir')
    monkeypatch.setattr(historyutil, 'RECOMMENDATIONS_FILE',
                        str(blocker / 'recommendations.json'))
    ref = historyutil.write_market_blocks('run_x', {'BTC': 'block'})  # must not raise
    assert ref is None
    assert 'could not write market blocks' in capsys.readouterr().out


def test_market_block_ref_is_relative_and_stable():
    assert historyutil.market_block_ref('run_abc') == 'market_blocks/run_abc.json'


# ---------------------------------------------------------------------------
# 5. prompt_hash stability
# ---------------------------------------------------------------------------

def test_prompt_hash_stable_and_distinct():
    a1 = historyutil.prompt_hash('analyze ETH with this market block')
    a2 = historyutil.prompt_hash('analyze ETH with this market block')
    b = historyutil.prompt_hash('analyze BTC with this market block')
    assert a1 == a2
    assert a1 != b
    assert len(a1) == 16
    assert a1 == hashlib.sha256(
        'analyze ETH with this market block'.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 6. _record_provenance assembles the schema-v2 kwargs
# ---------------------------------------------------------------------------

def test_record_provenance_fields(monkeypatch):
    votes = {'gemini': ('BUY', 0.9), 'claude': ('BUY', 0.8), 'openai': ('BUY', 0.7)}
    _patch_panel(monkeypatch, votes)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_prov', raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {'ETH': 'ETH market block'},
                        raising=False)
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))

    prov = bot._record_provenance('ETH', decision)
    assert prov['schema_version'] == 2
    assert prov['vote_details'] == decision.vote_details
    assert prov['market_block_ref'] == 'market_blocks/run_prov.json'
    assert prov['market_block_present'] is True
    # models: every panelist that ran, mapped to its resolved model id
    assert set(prov['models']) == {'gemini', 'claude', 'openai'}
    assert prov['models']['gemini'] == bot.get_model('gemini')
    # prompt_hash is a real 16-char digest reconstructed from the cached block
    assert isinstance(prov['prompt_hash'], str) and len(prov['prompt_hash']) == 16


def test_record_provenance_market_block_absent_for_uncached_coin(monkeypatch):
    votes = {'gemini': ('BUY', 0.9), 'claude': ('BUY', 0.8), 'openai': ('BUY', 0.7)}
    _patch_panel(monkeypatch, votes)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_prov', raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))

    prov = bot._record_provenance('ETH', decision)
    assert prov['market_block_present'] is False


# ---------------------------------------------------------------------------
# 7. WS5: market_block_hash (decision fingerprint) + spread_pct + sampling
# ---------------------------------------------------------------------------

def test_market_block_hash_matches_sha256_of_exact_block():
    block = 'MARKET DATA for ETH ...\nFIBONACCI ...\n'
    h = historyutil.market_block_hash(block)
    assert h == hashlib.sha256(block.encode()).hexdigest()[:16]
    assert len(h) == 16


def test_market_block_hash_none_for_missing_block():
    assert historyutil.market_block_hash(None) is None
    assert historyutil.market_block_hash('') is None


def test_market_block_hash_recomputable_from_written_sidecar(tmp_path, monkeypatch):
    """The hash the record carries is recomputable from the EXACT string
    write_market_blocks persists -- i.e. a reader can verify the fingerprint."""
    monkeypatch.setattr(historyutil, 'RECOMMENDATIONS_FILE',
                        str(tmp_path / 'history' / 'recommendations.json'))
    blocks = {'BTC': 'BTC block text\nwith newlines', 'ETH': 'ETH block'}
    ref = historyutil.write_market_blocks('run_hash', blocks)
    # record-time hash for BTC
    rec_hash = historyutil.market_block_hash(blocks['BTC'])
    # reader recomputes from the persisted sidecar
    sidecar = tmp_path / 'history' / ref
    persisted = json.loads(sidecar.read_text())
    assert historyutil.market_block_hash(persisted['BTC']) == rec_hash


def test_record_provenance_carries_market_block_hash(monkeypatch):
    votes = {'gemini': ('BUY', 0.9), 'claude': ('BUY', 0.8), 'openai': ('BUY', 0.7)}
    _patch_panel(monkeypatch, votes)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_prov', raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {'ETH': 'ETH market block'},
                        raising=False)
    monkeypatch.setattr(bot, 'DETERMINISTIC_SAMPLING', False, raising=False)
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))

    prov = bot._record_provenance('ETH', decision)
    assert prov['market_block_hash'] == historyutil.market_block_hash('ETH market block')
    # sampling recorded per panelist; flag off => provider-default for all
    assert set(prov['sampling']) == {'gemini', 'claude', 'openai'}
    assert all(v == 'provider-default' for v in prov['sampling'].values())


def test_record_provenance_hash_none_for_uncached_coin(monkeypatch):
    votes = {'gemini': ('BUY', 0.9), 'claude': ('BUY', 0.8), 'openai': ('BUY', 0.7)}
    _patch_panel(monkeypatch, votes)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)
    monkeypatch.setattr(bot, 'RUN_ID', 'run_prov', raising=False)
    monkeypatch.setattr(bot, 'MARKET_BLOCK_CACHE', {}, raising=False)
    decision = bot.process_coin_with_comparison('ETH', _primary_text(votes, 'gemini'))
    prov = bot._record_provenance('ETH', decision)
    assert prov['market_block_hash'] is None


def test_ws5_fields_written_when_supplied():
    rec = historyutil.create_recommendation_record(
        market_block_hash='0123456789abcdef',
        spread_pct=0.25,
        sampling={'gemini': {'temperature': 0}, 'openai': 'provider-default'},
        **_BASE,
    )
    assert rec['market_block_hash'] == '0123456789abcdef'
    assert rec['spread_pct'] == 0.25
    assert rec['sampling'] == {'gemini': {'temperature': 0},
                               'openai': 'provider-default'}


def test_ws5_fields_absent_when_omitted_byte_identity():
    rec = historyutil.create_recommendation_record(trading_mode='whatif', **_BASE)
    for k in ('market_block_hash', 'spread_pct', 'sampling'):
        assert k not in rec


def test_ws5_sampling_deep_copied_from_caller():
    src = {'gemini': {'temperature': 0}}
    rec = historyutil.create_recommendation_record(sampling=src, **_BASE)
    src['gemini']['temperature'] = 99  # mutate after the fact
    assert rec['sampling']['gemini'] == {'temperature': 0}
