"""Tests for voteschema (T8): schema validation, symbol binding, and the
failure mapping that feeds T3's PanelDecision abstain machinery."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import voteschema
from voteschema import (Abstain, Vote, bind_symbol, parse_vote,
                        resolve_structured_vote)


def vote_payload(**overrides):
    obj = {"symbol": "BTC", "action": "BUY", "confidence": 0.8,
           "abstain": False, "reasons": ["momentum", "volume"]}
    obj.update(overrides)
    return json.dumps(obj)


# ============================= parse_vote ==================================

class TestParseVote:

    def test_valid_vote(self):
        vote, err = parse_vote(vote_payload())
        assert err is None
        assert vote == Vote(symbol='BTC', action='BUY', confidence=0.8,
                            abstain=False, reasons=['momentum', 'volume'])

    def test_action_case_normalized(self):
        vote, err = parse_vote(vote_payload(action='buy'))
        assert err is None
        assert vote.action == 'BUY'

    def test_trailing_whitespace_tolerated(self):
        # Gemini quirk (probe-verified): response.text can carry trailing
        # whitespace after the closing brace.
        vote, err = parse_vote(vote_payload() + " \n")
        assert err is None and vote.action == 'BUY'

    def test_fenced_json_wrapper_tolerated(self):
        vote, err = parse_vote("```json\n" + vote_payload() + "\n```")
        assert err is None and vote.action == 'BUY'

    @pytest.mark.parametrize("text,fragment", [
        (None, 'no text'),
        ("", 'empty'),
        ("   ", 'empty'),
        ("not json at all", 'invalid JSON'),
        ('{"symbol": "BTC", "action": "BUY"', 'invalid JSON'),  # unterminated (perplexity probe shape)
        ('[1, 2, 3]', 'not an object'),
        ('"BUY"', 'not an object'),
    ])
    def test_non_object_payloads(self, text, fragment):
        vote, err = parse_vote(text)
        assert vote is None
        assert fragment in err

    @pytest.mark.parametrize("missing", ["symbol", "action", "confidence",
                                          "abstain", "reasons"])
    def test_missing_field(self, missing):
        obj = json.loads(vote_payload())
        del obj[missing]
        vote, err = parse_vote(json.dumps(obj))
        assert vote is None
        assert missing in err

    @pytest.mark.parametrize("payload,fragment", [
        (vote_payload(action='LEVERAGE'), 'action'),
        (vote_payload(action=7), 'action'),
        (vote_payload(symbol=''), 'symbol'),
        (vote_payload(symbol=42), 'symbol'),
        (vote_payload(confidence=1.5), 'confidence'),
        (vote_payload(confidence=-0.1), 'confidence'),
        (vote_payload(confidence='high'), 'confidence'),
        (vote_payload(confidence=True), 'confidence'),
        (vote_payload(abstain='yes'), 'abstain'),
        (vote_payload(abstain=0), 'abstain'),
        (vote_payload(reasons='because'), 'reasons'),
        (vote_payload(reasons=[1, 2]), 'reasons'),
    ])
    def test_schema_violations(self, payload, fragment):
        vote, err = parse_vote(payload)
        assert vote is None
        assert fragment in err

    def test_confidence_boundaries_inclusive(self):
        assert parse_vote(vote_payload(confidence=0))[0].confidence == 0.0
        assert parse_vote(vote_payload(confidence=1))[0].confidence == 1.0

    def test_empty_reasons_list_is_valid(self):
        vote, err = parse_vote(vote_payload(reasons=[]))
        assert err is None and vote.reasons == []

    # ---- reasons CONTENT hygiene (live-observed 2026-07-19: Claude JSON
    # self-correction debris landed as valid string elements inside reasons
    # while every typed field parsed clean) ----

    def test_minority_junk_reasons_are_filtered_vote_kept(self):
        # The real live shape: mostly-good reasons plus trailing debris.
        vote, err = parse_vote(vote_payload(reasons=[
            "No clear momentum trigger for aggressive entry",
            "Falling volume weakens conviction",
            "Sitting just above 38.2% fib support",
            "Positive social sentiment supportive but not decisive",
            ",",
            ']}[REDACTED]__ERROR__ retrying:{',
            "abstain",
        ]))
        assert err is None
        assert vote.reasons == [
            "No clear momentum trigger for aggressive entry",
            "Falling volume weakens conviction",
            "Sitting just above 38.2% fib support",
            "Positive social sentiment supportive but not decisive",
        ]

    @pytest.mark.parametrize("junk", [
        ",", "]}", "{", '"]}', "   ",              # structural / empty
        "]}__ERROR__ retrying:{",                   # artifact marker
        "[REDACTED] something",                     # artifact marker
        "abstain", "ABSTAIN", "confidence",         # bare schema keyword echo
        "unbalanced { brace",                       # unbalanced braces
        "control\x00char",                          # control character
    ])
    def test_majority_junk_reasons_fail_closed(self, junk):
        # A single-element all-junk array = majority junk -> parse error
        # (feeds abstain('parse_failure'), same vocabulary as any violation).
        vote, err = parse_vote(vote_payload(reasons=[junk]))
        assert vote is None
        assert 'reasons content corrupt' in err

    def test_reasons_count_and_length_capped(self):
        vote, err = parse_vote(vote_payload(
            reasons=["r%d" % i for i in range(50)] + ["x" * 10_000]))
        assert err is None
        assert len(vote.reasons) == voteschema.MAX_REASONS
        assert all(len(r) <= voteschema.MAX_REASON_LEN for r in vote.reasons)

    def test_trailing_debris_after_object_is_ignored(self):
        # Self-correction can also append a retry AFTER a complete object;
        # only the first complete JSON object counts.
        vote, err = parse_vote(
            vote_payload() + ' ]}__ERROR__ Let me re-emit clean JSON.]}{"]}')
        assert err is None and vote.action == 'BUY'

    def test_first_object_wins_over_trailing_retry_object(self):
        vote, err = parse_vote(
            vote_payload(action='HOLD') + "\n" + vote_payload(action='BUY'))
        assert err is None and vote.action == 'HOLD'

    def test_never_raises(self):
        # Every weird payload must return (None, err), not raise.
        for weird in (b"bytes", 123, {"a": 1}, ["x"], object()):
            vote, err = parse_vote(weird)
            assert vote is None and err


# ============================ bind_symbol ==================================

class TestBindSymbol:

    @pytest.mark.parametrize("vote_sym,coin", [
        ("BTC", "BTC"),
        ("btc", "BTC"),
        ("  BTC  ", "BTC"),
        ("BTC-USD", "BTC"),
        ("BTC/USD", "BTC"),
        ("SOL/USDT", "SOL"),
        ("Bitcoin", "BTC"),
        ("ETHEREUM", "ETH"),
        ("ether", "ETH"),
        ("Solana", "SOL"),
        ("dogwifhat", "WIF"),
        ("Shiba Inu", "SHIB"),
        ("Bitcoin (BTC)", "BTC"),
        ("Dogecoin (DOGE)", "DOGE"),
    ])
    def test_binds(self, vote_sym, coin):
        assert bind_symbol(vote_sym, coin)

    @pytest.mark.parametrize("vote_sym,coin", [
        ("DOGE", "ETH"),            # the coin-agnostic gap this closes
        ("Ethereum", "BTC"),
        ("WETH", "ETH"),            # wrapped token is NOT the coin
        ("ETH-BTC", "BTC"),         # trading pair, ambiguous -> reject
        ("SomeRandomCoin", "BTC"),
        ("", "BTC"),
        (None, "BTC"),
        ("BTC", ""),
        ("BTC", None),
    ])
    def test_rejects(self, vote_sym, coin):
        assert not bind_symbol(vote_sym, coin)


# ======================= resolve_structured_vote ===========================

class TestResolveStructuredVote:
    """The full failure-mapping table (T8 deliverable 5)."""

    def test_valid_vote_returns_action(self, capsys):
        rec = resolve_structured_vote('claude', vote_payload(action='SELL'), 'BTC')
        assert rec == 'SELL'
        assert '[STRUCTURED VOTE] claude/BTC: SELL' in capsys.readouterr().out

    def test_no_response_returns_none(self):
        # None = API error: the caller's legacy abstain('error') mapping.
        assert resolve_structured_vote('gemini', None, 'BTC') is None

    def test_empty_at_cap_is_parse_failure(self, capsys):
        assert resolve_structured_vote('openai', '', 'BTC') == Abstain('parse_failure')
        assert 'parse_failure' in capsys.readouterr().out

    def test_schema_violation_is_parse_failure(self):
        assert resolve_structured_vote(
            'gemini', '{"symbol": "BTC"}', 'BTC') == Abstain('parse_failure')
        assert resolve_structured_vote(
            'gemini', 'total garbage', 'BTC') == Abstain('parse_failure')

    def test_explicit_abstain_is_refusal(self, capsys):
        rec = resolve_structured_vote(
            'claude', vote_payload(abstain=True, action='HOLD'), 'BTC')
        assert rec == Abstain('refusal')
        assert 'refusal' in capsys.readouterr().out

    def test_symbol_mismatch(self, capsys):
        rec = resolve_structured_vote(
            'openai', vote_payload(symbol='DOGE'), 'ETH')
        assert rec == Abstain('symbol_mismatch')
        assert 'symbol_mismatch' in capsys.readouterr().out

    def test_refusal_checked_before_symbol_binding(self):
        # An abstain with a junk symbol is still a refusal, not a mismatch:
        # the model declined; which coin it declined about is secondary.
        rec = resolve_structured_vote(
            'gemini', vote_payload(abstain=True, symbol='???'), 'BTC')
        assert rec == Abstain('refusal')

    def test_never_raises_even_on_hostile_input(self):
        # Fail closed, not fail loud: no exception may escape to the outer
        # handler for these cases (T8 deliverable 5).
        assert resolve_structured_vote('gemini', 12345, 'BTC') == Abstain('parse_failure')
        assert resolve_structured_vote('gemini', {"a": 1}, 'BTC') == Abstain('parse_failure')


# ====================== provider schema variants ===========================

def _find_key(node, key):
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_find_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_find_key(v, key) for v in node)
    return False


class TestSchemaVariants:

    def test_canonical_schema_fields(self):
        s = voteschema.VOTE_SCHEMA
        assert set(s['properties']) == {'symbol', 'action', 'confidence',
                                        'abstain', 'reasons'}
        assert set(s['required']) == set(s['properties'])
        assert s['properties']['action']['enum'] == ['BUY', 'SELL', 'HOLD']
        assert s['additionalProperties'] is False

    def test_gemini_variant_strips_additional_properties(self):
        # Probe-verified: the Gemini API 400s on additionalProperties.
        s = voteschema.schema_for_gemini()
        assert not _find_key(s, 'additionalProperties')
        assert _find_key(s, 'minimum')  # numeric bounds retained

    def test_claude_variant_strips_numeric_bounds(self):
        # Probe-verified: the Claude API 400s on minimum/maximum for numbers.
        s = voteschema.schema_for_claude()
        assert not _find_key(s, 'minimum')
        assert not _find_key(s, 'maximum')
        assert s['additionalProperties'] is False  # retained (accepted)

    def test_openai_response_format_shape(self):
        rf = voteschema.openai_response_format()
        assert rf['type'] == 'json_schema'
        assert rf['json_schema']['name'] == 'trading_vote'
        assert rf['json_schema']['strict'] is True
        assert rf['json_schema']['schema'] == voteschema.VOTE_SCHEMA

    def test_variants_do_not_mutate_canonical(self):
        before = json.dumps(voteschema.VOTE_SCHEMA, sort_keys=True)
        voteschema.schema_for_gemini()
        voteschema.schema_for_claude()
        voteschema.openai_response_format()
        assert json.dumps(voteschema.VOTE_SCHEMA, sort_keys=True) == before


class TestSchemaInstruction:

    def test_mentions_coin_and_fields(self):
        text = voteschema.schema_instruction('BONK')
        assert 'BONK' in text
        for f in ('"symbol"', '"action"', '"confidence"', '"abstain"', '"reasons"'):
            assert f in text
        assert 'BUY, SELL, or HOLD' in text

    def test_replaces_delimiter_contract_entirely(self):
        text = voteschema.schema_instruction('BTC')
        assert 'angle bracket' not in text
        assert 'PRS' not in text
