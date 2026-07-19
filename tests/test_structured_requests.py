"""T8: per-provider structured-output request construction, checked against
the probe fixtures in tests/fixtures/structured_output/ with the SDK calls
mocked — no network. The fixtures are the empirically verified minimal
working request/response shapes (captured live 2026-07-18); these tests pin
the code to them.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crypto_trading_bot as bot
import voteschema
from claudeutil import ClaudeTrader
from openaiutil import OpenAITrader
from grokutil import GrokTrader
from perplexityutil import PerplexityTrader

FIXTURES = Path(__file__).parent / "fixtures" / "structured_output"


def load_fixture(provider):
    with open(FIXTURES / f"{provider}.json") as f:
        return json.load(f)


def vote_json(symbol='BTC', action='BUY', abstain=False):
    return json.dumps({"symbol": symbol, "action": action, "confidence": 0.8,
                       "abstain": abstain, "reasons": ["r1"]})


class Capture:
    """Callable that records kwargs and returns a canned result."""
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.result


# ============================ fixtures sanity ==============================

def _no_descriptions(node):
    """Schema minus 'description' strings: descriptions are non-enforcing
    prose (the probes used shorter ones); everything else — types, enum,
    required, bounds, additionalProperties — must match exactly."""
    if isinstance(node, dict):
        return {k: _no_descriptions(v) for k, v in node.items()
                if k != 'description'}
    if isinstance(node, list):
        return [_no_descriptions(v) for v in node]
    return node


class TestFixturesMatchCode:
    """The schemas the code builds are exactly the probe-verified ones."""

    def test_openai_fixture_schema_matches_code(self):
        fx = load_fixture('openai')
        assert (_no_descriptions(fx['request']['params']['response_format'])
                == _no_descriptions(voteschema.openai_response_format()))

    def test_claude_fixture_schema_matches_code(self):
        fx = load_fixture('claude')
        fx_schema = fx['request']['params']['output_config']['format']['schema']
        assert (_no_descriptions(fx_schema)
                == _no_descriptions(voteschema.schema_for_claude()))

    def test_gemini_fixture_schema_matches_code(self):
        fx = load_fixture('gemini')
        fx_schema = fx['request']['params']['config']['response_schema']
        assert (_no_descriptions(fx_schema)
                == _no_descriptions(voteschema.schema_for_gemini()))

    def test_grok_fixture_format_matches_code(self):
        # T8 phase 2: grok's Responses-API text.format param.
        fx = load_fixture('grok')
        fx_fmt = fx['request']['params']['text']['format']
        assert (_no_descriptions(fx_fmt)
                == _no_descriptions(voteschema.grok_text_format()))

    def test_perplexity_fixture_format_matches_code(self):
        # T8 phase 2: perplexity's chat.completions response_format param
        # (no name/strict wrapper).
        fx = load_fixture('perplexity')
        fx_fmt = fx['request']['params']['response_format']
        assert (_no_descriptions(fx_fmt)
                == _no_descriptions(voteschema.perplexity_response_format()))

    @pytest.mark.parametrize("provider", ['gemini', 'claude', 'openai',
                                           'grok', 'perplexity'])
    def test_fixture_response_payload_parses_and_validates(self, provider):
        """Every provider's captured live response payload passes the
        client-side validator (proving the schema round-trips)."""
        fx = load_fixture(provider)
        resp = fx['response']
        text = resp.get('text') or resp.get('content') or resp.get('output_text')
        vote, err = voteschema.parse_vote(text)
        assert err is None, err
        assert vote.symbol == 'BTC'
        assert vote.action in voteschema.ACTIONS

    def test_malformed_stream_regression_2026_07_19(self):
        """Full-blob regression for the live-observed Claude emission: debris
        elements inside reasons AND self-correction retry text after the
        object. The typed fields must parse, the debris reasons must be
        filtered out, and the trailing bytes ignored."""
        blob = json.dumps({
            "symbol": "ETH", "action": "HOLD", "confidence": 0.6,
            "abstain": False,
            "reasons": [
                "Price mid-range at 62% of 7d range",
                "Sitting just above 38.2% fib support",
                "Falling volume weakens conviction",
                "Low intraday volatility limits short-term edge",
                "Positive social sentiment supportive but not decisive",
                "No clear momentum trigger for aggressive entry",
                ",",
                ']}[REDACTED]__ERROR__ retrying:{',
                ']}[REDACTED]__ERROR__ Let me re-emit clean JSON.]}{"]}',
            ],
        }) + ' ]}trailing debris{"]}'
        vote, err = voteschema.parse_vote(blob)
        assert err is None, err
        assert vote.action == 'HOLD' and vote.symbol == 'ETH'
        assert len(vote.reasons) == 6
        assert all('__ERROR__' not in r and r.strip('{}[],:" ') for r in vote.reasons)

    @pytest.mark.parametrize("provider", ['gemini', 'claude', 'openai',
                                          'grok', 'perplexity'])
    def test_all_five_adopted_structured_output(self, provider):
        # T8 phase 2 (2026-07-19): grok and perplexity are now migrated, so
        # every provider's fixture records adopted=true.
        assert load_fixture(provider)['adopted'] is True

    @pytest.mark.parametrize("provider", ['gemini', 'claude', 'openai'])
    def test_trio_is_statically_structured(self, provider):
        # gemini/claude/openai are ALWAYS structured — a plain str with no
        # path tag still routes to the structured parser.
        assert provider in bot.STRUCTURED_VOTE_PROVIDERS

    @pytest.mark.parametrize("provider", ['grok', 'perplexity'])
    def test_grok_perplexity_are_path_driven_not_static(self, provider):
        # grok/perplexity attempt structured FIRST but keep a delimiter-tag
        # fallback, so they are routed by the response's vote_path tag, not by
        # static membership in STRUCTURED_VOTE_PROVIDERS (which would force the
        # structured parser onto a delimiter-tagged fallback response).
        assert provider not in bot.STRUCTURED_VOTE_PROVIDERS


# =============================== Claude ====================================

def make_claude(capture):
    trader = ClaudeTrader.__new__(ClaudeTrader)
    trader.client = SimpleNamespace(messages=SimpleNamespace(create=capture))
    trader.model = 'claude-test'
    trader.coin_type = 'cryptocurrency'
    return trader


def claude_message(text=None, stop_reason='end_turn'):
    blocks = [] if text is None else [SimpleNamespace(type='text', text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class TestClaudeRequests:

    def test_coin_check_builds_fixture_request_shape(self):
        cap = Capture(claude_message(vote_json()))
        out = make_claude(cap).send_coin_check_request('BTC')
        assert out == vote_json()
        assert cap.kwargs['output_config'] == {
            'format': {'type': 'json_schema',
                       'schema': voteschema.schema_for_claude()}}
        prompt = cap.kwargs['messages'][0]['content']
        assert voteschema.schema_instruction('BTC') in prompt
        assert 'angle bracket' not in prompt  # delimiter contract fully replaced
        assert 'BTC' in prompt

    @pytest.mark.parametrize("method,args", [
        ('send_trend_check_request', ('BTC', 'trend data')),
        ('send_integrated_coin_check', ('BTC', 'peer says HOLD')),
        ('send_integrated_trend_check', ('BTC', 'peer says HOLD', 'trend data')),
    ])
    def test_all_analysis_methods_are_structured(self, method, args):
        cap = Capture(claude_message(vote_json()))
        trader = make_claude(cap)
        assert getattr(trader, method)(*args) == vote_json()
        assert 'output_config' in cap.kwargs
        prompt = cap.kwargs['messages'][0]['content']
        assert voteschema.schema_instruction('BTC') in prompt
        assert 'angle bracket' not in prompt

    def test_empty_at_cap_returns_empty_string(self):
        # stop_reason=max_tokens with no text block (reasoning ate the
        # budget): '' propagates -> abstain(parse_failure) downstream.
        cap = Capture(claude_message(text=None, stop_reason='max_tokens'))
        assert make_claude(cap).send_coin_check_request('BTC') == ""

    def test_discovery_request_is_untouched(self):
        cap = Capture(claude_message("1. PEPE +++PEPE+++"))
        make_claude(cap).send_recommendation_request()
        assert 'output_config' not in cap.kwargs
        assert 'plus signs' in cap.kwargs['messages'][0]['content']


# =============================== OpenAI ====================================

def make_openai(capture):
    trader = OpenAITrader.__new__(OpenAITrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    trader.model = 'gpt-test'
    trader.coin_type = 'cryptocurrency'
    return trader


def openai_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason='stop')])


class TestOpenAIRequests:

    def test_coin_check_builds_fixture_request_shape(self):
        cap = Capture(openai_response(vote_json()))
        out = make_openai(cap).send_coin_check_request('BTC')
        assert out == vote_json()
        assert cap.kwargs['response_format'] == voteschema.openai_response_format()
        # gpt-5.x rules: max_completion_tokens, never max_tokens/temperature
        assert 'max_completion_tokens' in cap.kwargs
        assert 'max_tokens' not in cap.kwargs
        assert 'temperature' not in cap.kwargs
        prompt = cap.kwargs['messages'][0]['content']
        assert voteschema.schema_instruction('BTC') in prompt
        assert 'angle bracket' not in prompt

    @pytest.mark.parametrize("method,args", [
        ('send_trend_check_request', ('BTC', 'trend data')),
        ('send_integrated_coin_check', ('BTC', 'peer says HOLD')),
        ('send_integrated_trend_check', ('BTC', 'peer says HOLD', 'trend data')),
    ])
    def test_all_analysis_methods_are_structured(self, method, args):
        cap = Capture(openai_response(vote_json()))
        trader = make_openai(cap)
        assert getattr(trader, method)(*args) == vote_json()
        assert cap.kwargs['response_format'] == voteschema.openai_response_format()
        assert 'angle bracket' not in cap.kwargs['messages'][0]['content']

    def test_none_content_at_cap_returns_empty_string(self):
        # finish_reason=length with content None (reasoning consumed the
        # budget — probe-verified trap): '' -> abstain(parse_failure).
        cap = Capture(openai_response(None))
        assert make_openai(cap).send_coin_check_request('BTC') == ""

    def test_discovery_request_is_untouched(self):
        cap = Capture(openai_response("1. PEPE +++PEPE+++"))
        make_openai(cap).send_recommendation_request()
        assert 'response_format' not in cap.kwargs
        assert 'plus signs' in cap.kwargs['messages'][0]['content']


# =============================== Gemini ====================================

def gemini_response(text):
    return SimpleNamespace(text=text)


def patch_gemini(monkeypatch, capture):
    monkeypatch.setattr(bot, 'client',
                        SimpleNamespace(models=SimpleNamespace(generate_content=capture)),
                        raising=False)
    monkeypatch.setattr(bot, 'USE_COIN_DISCOVERY', False, raising=False)


class Capture3:
    """generate_content is called with keyword args model/contents/config."""
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def __call__(self, *, model, contents, config):
        self.kwargs = {'model': model, 'contents': contents, 'config': config}
        return self.result


class TestGeminiRequests:

    def _assert_structured_config(self, config):
        assert config.response_mime_type == 'application/json'
        # Rendered through the SDK type; compare the JSON-facing dict.
        schema = config.response_schema
        dumped = json.loads(json.dumps(schema, default=lambda o: getattr(o, '__dict__', str(o))))
        assert 'additional_properties' not in json.dumps(dumped)
        assert 'additionalProperties' not in json.dumps(dumped)
        assert config.tools, "search grounding tool must be retained"

    def test_coin_check_builds_fixture_request_shape(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap)
        resp = bot.sendCoinCheckRequest('BTC')
        assert resp.text == vote_json()
        self._assert_structured_config(cap.kwargs['config'])
        assert voteschema.schema_instruction('BTC') in cap.kwargs['contents']
        assert 'angle bracket' not in cap.kwargs['contents']

    def test_trend_and_integrated_checks_are_structured(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json()))
        patch_gemini(monkeypatch, cap)
        for call in (lambda: bot.sendTrendCheckRequest('BTC', 'trend data'),
                     lambda: bot.sendIntegratedCoinCheckRequest('BTC', 'peer'),
                     lambda: bot.sendIntegratedTrendCheckRequest('BTC', 'peer', 'trend data')):
            assert call().text == vote_json()
            self._assert_structured_config(cap.kwargs['config'])
            assert voteschema.schema_instruction('BTC') in cap.kwargs['contents']
            assert 'angle bracket' not in cap.kwargs['contents']

    def test_get_llm_response_maps_none_text_to_parse_failure(self, monkeypatch):
        # response.text None at MAX_TOKENS (probe-verified reasoning trap):
        # text becomes '' and the vote is abstain(parse_failure), never a
        # vote and never a bare 'error'.
        cap = Capture3(gemini_response(None))
        patch_gemini(monkeypatch, cap)
        text, rec = bot.get_llm_response('gemini', 'BTC', use_trend_check=False)
        assert text == ""
        assert rec == voteschema.Abstain('parse_failure')

    def test_get_llm_response_parses_structured_vote(self, monkeypatch):
        cap = Capture3(gemini_response(vote_json(action='HOLD')))
        patch_gemini(monkeypatch, cap)
        text, rec = bot.get_llm_response('gemini', 'BTC', use_trend_check=False)
        assert rec == 'HOLD'

    def test_discovery_request_is_untouched(self, monkeypatch):
        cap = Capture3(gemini_response("1. PEPE +++PEPE+++"))
        patch_gemini(monkeypatch, cap)
        monkeypatch.setattr(bot, 'DEX_MODE', False, raising=False)
        monkeypatch.setattr(bot, 'config', 'DISCOVERY_CONFIG_SENTINEL', raising=False)
        bot.sendRecommendationRequest()
        # discovery keeps the plain grounded config -- no structured schema
        assert cap.kwargs['config'] == 'DISCOVERY_CONFIG_SENTINEL'
        assert 'plus signs' in cap.kwargs['contents']


# ================================ Grok =====================================
# T8 phase 2: grok attempts native structured output (Responses API
# text.format json_schema, coexisting with the web_search tool) and falls back
# to the delimiter-tag REQUEST only when the provider rejects the schema
# parameter itself.

def make_grok(create_fn):
    trader = GrokTrader.__new__(GrokTrader)
    trader.client = SimpleNamespace(responses=SimpleNamespace(create=create_fn))
    trader.model = 'grok-test'
    trader.tools = [{"type": "web_search"}]
    trader.coin_type = 'cryptocurrency'
    return trader


def grok_response(output_text):
    return SimpleNamespace(output_text=output_text, status='completed')


# Realistic error message shapes for an OpenAI-compatible 400 that rejects the
# structured-output parameter itself (the only fallback trigger).
GROK_SCHEMA_400 = ("Error code: 400 - Invalid value for 'text.format': "
                   "json_schema output is not supported for this model")
PPLX_SCHEMA_400 = ("Error code: 400 - response_format json_schema is not "
                   "supported")


class _SchemaRejectingResponses:
    """responses.create stub: raises a schema-param 400 on the structured
    attempt (kwargs carry 'text'), returns a delimiter-tag response on the
    unstructured fallback retry."""
    def __init__(self, fallback_text):
        self.calls = []
        self.fallback_text = fallback_text

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if 'text' in kwargs:
            raise Exception(GROK_SCHEMA_400)
        return grok_response(self.fallback_text)


class TestGrokRequests:

    def test_coin_check_builds_structured_request(self):
        cap = Capture(grok_response(vote_json()))
        out = make_grok(cap).send_coin_check_request('BTC')
        assert out == vote_json()
        assert voteschema.vote_path_of(out) == 'structured'
        assert cap.kwargs['text'] == {'format': voteschema.grok_text_format()}
        # search grounding retained alongside the schema (coexistence verified)
        assert cap.kwargs['tools'] == [{"type": "web_search"}]
        prompt = cap.kwargs['input'][0]['content']
        assert voteschema.schema_instruction('BTC') in prompt
        assert 'angle bracket' not in prompt  # delimiter contract not on this path
        # grok's web-search preamble drift is preserved
        assert prompt.startswith('Using real-time web search')

    @pytest.mark.parametrize("method,args", [
        ('send_trend_check_request', ('BTC', 'trend data')),
        ('send_integrated_coin_check', ('BTC', 'peer says HOLD')),
        ('send_integrated_trend_check', ('BTC', 'peer says HOLD', 'trend data')),
    ])
    def test_all_analysis_methods_are_structured(self, method, args):
        cap = Capture(grok_response(vote_json()))
        trader = make_grok(cap)
        out = getattr(trader, method)(*args)
        assert voteschema.vote_path_of(out) == 'structured'
        assert cap.kwargs['text'] == {'format': voteschema.grok_text_format()}
        assert 'angle bracket' not in cap.kwargs['input'][0]['content']

    def test_structured_vote_resolves_to_action(self):
        cap = Capture(grok_response(vote_json(action='HOLD')))
        text = make_grok(cap).send_coin_check_request('BTC')
        assert bot.resolve_vote('grok', text, 'BTC') == 'HOLD'

    def test_garbage_structured_response_abstains_never_falls_back(self):
        # A structured attempt that returns non-JSON garbage must fail closed
        # to abstain(parse_failure) — NOT be re-parsed as a delimiter tag even
        # though the garbage happens to carry one.
        cap = Capture(grok_response('nonsense <**BTC-PRS-BUY**> trailing'))
        text = make_grok(cap).send_coin_check_request('BTC')
        assert voteschema.vote_path_of(text) == 'structured'
        assert bot.resolve_vote('grok', text, 'BTC') == voteschema.Abstain('parse_failure')

    def test_schema_param_rejection_falls_back_to_tag(self):
        stub = _SchemaRejectingResponses('analysis <**BTC-PRS-BUY**>')
        text = make_grok(stub).send_coin_check_request('BTC')
        assert voteschema.vote_path_of(text) == 'fallback'
        # structured attempt first (carried text=), then the unstructured retry
        assert 'text' in stub.calls[0] and 'text' not in stub.calls[1]
        # the fallback request used the delimiter instruction, not the schema one
        fb_prompt = stub.calls[1]['input'][0]['content']
        assert 'angle bracket' in fb_prompt
        assert voteschema.schema_instruction('BTC') not in fb_prompt
        # and it resolves through the delimiter parser
        assert bot.resolve_vote('grok', text, 'BTC') == 'BUY'

    def test_non_schema_error_propagates_no_fallback(self):
        # A timeout is not a schema-param rejection: it must propagate (never a
        # silent fallback), so get_llm_response maps it to abstain('error').
        def boom(**kwargs):
            raise Exception('Request timed out.')
        with pytest.raises(Exception, match='timed out'):
            make_grok(boom).send_coin_check_request('BTC')

    def test_discovery_request_is_unstructured(self):
        cap = Capture(grok_response("1. PEPE +++PEPE+++"))
        make_grok(cap).send_recommendation_request()
        assert 'text' not in cap.kwargs  # no schema on discovery
        assert 'plus signs' in cap.kwargs['input'][0]['content']


# ============================= Perplexity ==================================

def make_perplexity(create_fn):
    trader = PerplexityTrader.__new__(PerplexityTrader)
    trader.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn)))
    trader.model = 'sonar-test'
    trader.coin_type = 'cryptocurrency'
    return trader


def perplexity_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason='stop')])


class _SchemaRejectingCompletions:
    """chat.completions.create stub: raises a schema-param 400 on the
    structured attempt (kwargs carry 'response_format'), returns a delimiter
    response on the unstructured fallback retry."""
    def __init__(self, fallback_text):
        self.calls = []
        self.fallback_text = fallback_text

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if 'response_format' in kwargs:
            raise Exception(PPLX_SCHEMA_400)
        return perplexity_response(self.fallback_text)


class TestPerplexityRequests:

    def test_coin_check_builds_structured_request(self):
        cap = Capture(perplexity_response(vote_json()))
        out = make_perplexity(cap).send_coin_check_request('BTC')
        assert out == vote_json()
        assert voteschema.vote_path_of(out) == 'structured'
        assert cap.kwargs['response_format'] == voteschema.perplexity_response_format()
        prompt = cap.kwargs['messages'][0]['content']
        assert voteschema.schema_instruction('BTC') in prompt
        assert 'angle bracket' not in prompt
        # perplexity's coin-check suffix drift is preserved
        assert 'Use current market data and recent news.' in prompt

    @pytest.mark.parametrize("method,args", [
        ('send_trend_check_request', ('BTC', 'trend data')),
        ('send_integrated_coin_check', ('BTC', 'peer says HOLD')),
        ('send_integrated_trend_check', ('BTC', 'peer says HOLD', 'trend data')),
    ])
    def test_all_analysis_methods_are_structured(self, method, args):
        cap = Capture(perplexity_response(vote_json()))
        trader = make_perplexity(cap)
        out = getattr(trader, method)(*args)
        assert voteschema.vote_path_of(out) == 'structured'
        assert cap.kwargs['response_format'] == voteschema.perplexity_response_format()
        assert 'angle bracket' not in cap.kwargs['messages'][0]['content']

    def test_structured_vote_resolves_to_action(self):
        cap = Capture(perplexity_response(vote_json(action='SELL')))
        text = make_perplexity(cap).send_coin_check_request('BTC')
        assert bot.resolve_vote('perplexity', text, 'BTC') == 'SELL'

    def test_truncated_unterminated_json_abstains_parse_failure(self):
        # The live truncation hazard: an unterminated JSON tail must fail
        # closed to abstain(parse_failure), never be repaired or trusted.
        truncated = ('{"symbol":"BTC","action":"BUY","confidence":0.7,'
                     '"abstain":false,"reasons":["strong momentum and ')
        cap = Capture(perplexity_response(truncated))
        text = make_perplexity(cap).send_coin_check_request('BTC')
        assert voteschema.vote_path_of(text) == 'structured'
        assert bot.resolve_vote('perplexity', text, 'BTC') == \
            voteschema.Abstain('parse_failure')

    def test_empty_content_returns_empty_string(self):
        cap = Capture(perplexity_response(None))
        out = make_perplexity(cap).send_coin_check_request('BTC')
        assert out == ""
        assert bot.resolve_vote('perplexity', out, 'BTC') == \
            voteschema.Abstain('parse_failure')

    def test_schema_param_rejection_falls_back_to_tag(self):
        stub = _SchemaRejectingCompletions('analysis <**BTC-PRS-SELL**>')
        text = make_perplexity(stub).send_coin_check_request('BTC')
        assert voteschema.vote_path_of(text) == 'fallback'
        assert 'response_format' in stub.calls[0] and 'response_format' not in stub.calls[1]
        fb_prompt = stub.calls[1]['messages'][0]['content']
        assert 'angle bracket' in fb_prompt
        assert voteschema.schema_instruction('BTC') not in fb_prompt
        assert bot.resolve_vote('perplexity', text, 'BTC') == 'SELL'

    def test_non_schema_error_propagates_no_fallback(self):
        def boom(**kwargs):
            raise Exception('429 rate limit exceeded')
        with pytest.raises(Exception, match='rate limit'):
            make_perplexity(boom).send_coin_check_request('BTC')

    def test_discovery_request_is_unstructured(self):
        cap = Capture(perplexity_response("1. PEPE +++PEPE+++"))
        make_perplexity(cap).send_recommendation_request()
        assert 'response_format' not in cap.kwargs
        assert 'plus signs' in cap.kwargs['messages'][0]['content']
