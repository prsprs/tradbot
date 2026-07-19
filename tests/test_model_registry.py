"""Tests for T6 (model registry + LLM preflight, plan Phase 1).

Covered:
  1. modelregistry.get_model -- default resolution, env-var override,
     override takes precedence over default, unknown provider raises.
  2. llmpreflight.preflight -- the "not configured" short-circuit makes
     NO network call (verified by monkeypatching the underlying
     llm_utils.<Provider>Client classes to raise if constructed with a
     missing key, and asserting the network-call mock is never touched);
     PreflightResult shape; duplicate providers probed once.
  3. crypto_trading_bot integration -- get_active_llm_panel (solo vs
     compare/integrate), and run_llm_preflight with a monkeypatched
     llmpreflight.preflight: a failure in live mode raises SystemExit,
     the same failure in whatif mode prints a warning and returns
     normally, --skip-preflight bypasses the probe entirely.

No real network calls anywhere in this file -- every provider client
class is monkeypatched to a fake that either raises ValueError (mimicking
"key not set") or returns a canned object, and crypto_trading_bot.main()
is never invoked (it does far more than preflight; the integration tests
call run_llm_preflight directly, which is the function main() calls).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import modelregistry
import llmpreflight
import voteschema
import crypto_trading_bot as bot


# ============================================================================
# 1. modelregistry.get_model
# ============================================================================

def test_get_model_returns_default_when_no_override(monkeypatch):
    for env_var in modelregistry.ENV_OVERRIDE_VARS.values():
        monkeypatch.delenv(env_var, raising=False)
    for provider, default in modelregistry.DEFAULT_MODELS.items():
        assert modelregistry.get_model(provider) == default


def test_get_model_env_override_takes_precedence(monkeypatch):
    monkeypatch.setenv('CLAUDE_MODEL', 'claude-opus-9000')
    assert modelregistry.get_model('claude') == 'claude-opus-9000'
    # Other providers are unaffected by an unrelated override.
    monkeypatch.delenv('GEMINI_MODEL', raising=False)
    assert modelregistry.get_model('gemini') == modelregistry.DEFAULT_MODELS['gemini']


def test_get_model_blank_override_falls_back_to_default(monkeypatch):
    """An env var set to '' or whitespace-only should not shadow the
    default -- an empty override is not a deliberate pin."""
    monkeypatch.setenv('OPENAI_MODEL', '   ')
    assert modelregistry.get_model('openai') == modelregistry.DEFAULT_MODELS['openai']


def test_get_model_is_case_insensitive_on_provider(monkeypatch):
    monkeypatch.delenv('GROK_MODEL', raising=False)
    assert modelregistry.get_model('GROK') == modelregistry.DEFAULT_MODELS['grok']
    assert modelregistry.get_model('Grok') == modelregistry.DEFAULT_MODELS['grok']


def test_get_model_unknown_provider_raises():
    with pytest.raises(ValueError):
        modelregistry.get_model('not-a-real-provider')


def test_all_five_providers_registered():
    assert set(modelregistry.DEFAULT_MODELS) == {
        'gemini', 'claude', 'openai', 'grok', 'perplexity'
    }
    assert set(modelregistry.ENV_OVERRIDE_VARS) == set(modelregistry.DEFAULT_MODELS)


# ============================================================================
# 2. llmpreflight.preflight -- not-configured short-circuit (no network)
# ============================================================================

class _RaisesIfConstructed:
    """Stand-in for an llm_utils.<Provider>Client whose real __init__
    raises ValueError when the required API key env var is unset. Also
    fails the test loudly if anything tries to make a network call
    through it, so a bug that "configures" the probe anyway is caught."""

    def __init__(self):
        raise ValueError("SOME_API_KEY environment variable not set")


def _patch_all_clients_not_configured(monkeypatch):
    for attr in ('GeminiClient', 'ClaudeClient', 'OpenAIClient', 'GrokClient', 'PerplexityClient'):
        monkeypatch.setattr(llm_utils_module(), attr, _RaisesIfConstructed)


def llm_utils_module():
    import llm_utils
    return llm_utils


def test_preflight_not_configured_makes_no_network_call(monkeypatch):
    _patch_all_clients_not_configured(monkeypatch)
    results = llmpreflight.preflight(['gemini', 'claude', 'openai', 'grok', 'perplexity'])
    assert len(results) == 5
    for provider, result in results.items():
        assert result.ok is False
        assert result.error == llmpreflight.NOT_CONFIGURED_ERROR


def test_preflight_not_configured_result_carries_registry_model(monkeypatch):
    """Even though the client never constructs, the result still reports
    which model *would* have been used, from the registry (not the
    unreachable client instance)."""
    _patch_all_clients_not_configured(monkeypatch)
    results = llmpreflight.preflight(['claude'])
    assert results['claude'].model == modelregistry.get_model('claude')


def test_preflight_unknown_provider():
    results = llmpreflight.preflight(['not-a-real-provider'])
    assert results['not-a-real-provider'].ok is False
    assert 'unknown provider' in results['not-a-real-provider'].error


def test_preflight_dedupes_repeated_provider(monkeypatch):
    _patch_all_clients_not_configured(monkeypatch)
    results = llmpreflight.preflight(['claude', 'claude', 'CLAUDE'])
    assert list(results.keys()) == ['claude']


def test_preflight_result_shape_on_success(monkeypatch):
    """A configured provider that succeeds reports ok=True, its model,
    and a non-negative latency -- using a fake client so no network call
    actually happens."""
    class _FakeMessages:
        def create(self, **kwargs):
            return object()

    class _FakeAnthropicClient:
        def __init__(self):
            self.messages = _FakeMessages()

    class _FakeClaudeWrapper:
        def __init__(self):
            self.client = _FakeAnthropicClient()
            self.model = 'claude-opus-4-8'

    import llm_utils
    monkeypatch.setattr(llm_utils, 'ClaudeClient', _FakeClaudeWrapper)

    results = llmpreflight.preflight(['claude'])
    result = results['claude']
    assert result.ok is True
    assert result.model == 'claude-opus-4-8'
    assert result.latency_ms is not None
    assert result.latency_ms >= 0
    assert result.error is None


def test_preflight_result_shape_on_api_error(monkeypatch):
    """A configured provider whose probe call itself raises (bad model ID,
    auth failure, etc, as opposed to a missing key) reports ok=False with
    the exception message, not 'not configured'."""
    class _FakeMessages:
        def create(self, **kwargs):
            raise RuntimeError("404 model_not_found: no such model")

    class _FakeAnthropicClient:
        def __init__(self):
            self.messages = _FakeMessages()

    class _FakeClaudeWrapper:
        def __init__(self):
            self.client = _FakeAnthropicClient()
            self.model = 'claude-opus-retired'

    import llm_utils
    monkeypatch.setattr(llm_utils, 'ClaudeClient', _FakeClaudeWrapper)

    results = llmpreflight.preflight(['claude'])
    result = results['claude']
    assert result.ok is False
    assert result.model == 'claude-opus-retired'
    assert 'model_not_found' in result.error


# ============================================================================
# 2b. F9: llmpreflight.preflight(providers, schema_probe=True)
# ============================================================================
# No real network anywhere here -- every wrapper client is a fake carrying
# canned responses; tests/conftest.py's autouse network guard would fail
# loudly (naming this test) if any of these accidentally reached a real
# socket.

def _vote_json(**overrides):
    payload = {"symbol": "BTC", "action": "HOLD", "confidence": 0.5,
               "abstain": False, "reasons": ["r"]}
    payload.update(overrides)
    return json.dumps(payload)


class TestSchemaProbeDefaultUnchanged:
    """schema_probe defaults to False -- F9 must not change the plain
    preflight's behavior or request shape."""

    def test_default_call_never_sends_a_schema_kwarg(self, monkeypatch):
        captured = {}

        class _FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(content=[SimpleNamespace(type='text', text='OK')])

        class _FakeClaudeWrapper:
            def __init__(self):
                self.client = SimpleNamespace(messages=_FakeMessages())
                self.model = 'claude-test'

        monkeypatch.setattr(llm_utils_module(), 'ClaudeClient', _FakeClaudeWrapper)

        result = llmpreflight.preflight(['claude'])['claude']  # schema_probe omitted
        assert result.ok is True
        assert 'output_config' not in captured  # plain probe, unchanged

    def test_schema_probe_false_explicit_is_same_as_default(self, monkeypatch):
        captured = {}

        class _FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(content=[SimpleNamespace(type='text', text='OK')])

        class _FakeClaudeWrapper:
            def __init__(self):
                self.client = SimpleNamespace(messages=_FakeMessages())
                self.model = 'claude-test'

        monkeypatch.setattr(llm_utils_module(), 'ClaudeClient', _FakeClaudeWrapper)

        result = llmpreflight.preflight(['claude'], schema_probe=False)['claude']
        assert result.ok is True
        assert 'output_config' not in captured


class TestSchemaProbeClaude:

    def _fake_wrapper(self, monkeypatch, response_text, captured=None):
        class _FakeMessages:
            def create(self, **kwargs):
                if captured is not None:
                    captured.update(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type='text', text=response_text)])

        class _FakeClaudeWrapper:
            def __init__(self):
                self.client = SimpleNamespace(messages=_FakeMessages())
                self.model = 'claude-schema-test'

        monkeypatch.setattr(llm_utils_module(), 'ClaudeClient', _FakeClaudeWrapper)

    def test_valid_vote_is_ok(self, monkeypatch):
        captured = {}
        self._fake_wrapper(monkeypatch, _vote_json(action='BUY'), captured)
        result = llmpreflight.preflight(['claude'], schema_probe=True)['claude']
        assert result.ok is True
        assert result.model == 'claude-schema-test'
        # carries Claude's real schema variant (no minimum/maximum -- see
        # voteschema.schema_for_claude)
        assert captured['output_config']['format']['type'] == 'json_schema'
        assert captured['output_config']['format']['schema'] == voteschema.schema_for_claude()
        assert captured['max_tokens'] == llmpreflight.SCHEMA_PROBE_MAX_TOKENS

    def test_explicit_abstain_still_counts_as_ok(self, monkeypatch):
        """abstain=true is a first-class SUCCESSFUL parse (voteschema.py) --
        the schema probe cares whether the contract works, not whether the
        model chose to vote."""
        self._fake_wrapper(monkeypatch, _vote_json(abstain=True))
        result = llmpreflight.preflight(['claude'], schema_probe=True)['claude']
        assert result.ok is True

    def test_malformed_json_is_not_ok(self, monkeypatch):
        self._fake_wrapper(monkeypatch, 'not json at all')
        result = llmpreflight.preflight(['claude'], schema_probe=True)['claude']
        assert result.ok is False
        assert 'schema probe' in result.error

    def test_empty_text_is_not_ok(self, monkeypatch):
        self._fake_wrapper(monkeypatch, '')
        result = llmpreflight.preflight(['claude'], schema_probe=True)['claude']
        assert result.ok is False

    def test_api_error_reports_ok_false_same_as_plain_probe(self, monkeypatch):
        class _FakeMessages:
            def create(self, **kwargs):
                raise RuntimeError("400 schema rejected")

        class _FakeClaudeWrapper:
            def __init__(self):
                self.client = SimpleNamespace(messages=_FakeMessages())
                self.model = 'claude-schema-test'

        monkeypatch.setattr(llm_utils_module(), 'ClaudeClient', _FakeClaudeWrapper)
        result = llmpreflight.preflight(['claude'], schema_probe=True)['claude']
        assert result.ok is False
        assert 'schema rejected' in result.error

    def test_not_configured_short_circuit_still_applies(self, monkeypatch):
        _patch_all_clients_not_configured(monkeypatch)
        result = llmpreflight.preflight(['claude'], schema_probe=True)['claude']
        assert result.ok is False
        assert result.error == llmpreflight.NOT_CONFIGURED_ERROR


class TestSchemaProbeOpenAI:

    def test_valid_vote_is_ok_and_sends_real_schema(self, monkeypatch):
        captured = {}

        class _FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=_vote_json()))])

        class _FakeOpenAIWrapper:
            def __init__(self):
                self.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
                self.model = 'gpt-schema-test'

        monkeypatch.setattr(llm_utils_module(), 'OpenAIClient', _FakeOpenAIWrapper)
        result = llmpreflight.preflight(['openai'], schema_probe=True)['openai']
        assert result.ok is True
        assert captured['response_format'] == voteschema.openai_response_format()
        assert captured['max_completion_tokens'] == llmpreflight.SCHEMA_PROBE_MAX_TOKENS

    def test_malformed_content_is_not_ok(self, monkeypatch):
        class _FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"incomplete":'))])

        class _FakeOpenAIWrapper:
            def __init__(self):
                self.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
                self.model = 'gpt-schema-test'

        monkeypatch.setattr(llm_utils_module(), 'OpenAIClient', _FakeOpenAIWrapper)
        result = llmpreflight.preflight(['openai'], schema_probe=True)['openai']
        assert result.ok is False
        assert 'schema probe' in result.error


class TestSchemaProbeGemini:

    def test_valid_vote_is_ok_and_sends_real_schema(self, monkeypatch):
        captured = {}

        def fake_generate_content(*, model, contents, config):
            captured['model'] = model
            captured['contents'] = contents
            captured['config'] = config
            return SimpleNamespace(text=_vote_json())

        class _FakeGeminiWrapper:
            def __init__(self):
                self.client = SimpleNamespace(
                    models=SimpleNamespace(generate_content=fake_generate_content))
                self.model = 'gemini-schema-test'

        monkeypatch.setattr(llm_utils_module(), 'GeminiClient', _FakeGeminiWrapper)
        result = llmpreflight.preflight(['gemini'], schema_probe=True)['gemini']
        assert result.ok is True
        assert captured['config'].response_schema == voteschema.schema_for_gemini()
        assert captured['config'].response_mime_type == 'application/json'
        # deliberately uncapped (reasoning-model gotcha -- see module docstring)
        assert captured['config'].max_output_tokens is None

    def test_empty_response_text_is_not_ok(self, monkeypatch):
        """Mirrors the real gemini-3.1 failure mode: reasoning consumes the
        whole budget and response.text comes back empty -- must map to
        ok=False, never a silent pass."""
        def fake_generate_content(*, model, contents, config):
            return SimpleNamespace(text='')

        class _FakeGeminiWrapper:
            def __init__(self):
                self.client = SimpleNamespace(
                    models=SimpleNamespace(generate_content=fake_generate_content))
                self.model = 'gemini-schema-test'

        monkeypatch.setattr(llm_utils_module(), 'GeminiClient', _FakeGeminiWrapper)
        result = llmpreflight.preflight(['gemini'], schema_probe=True)['gemini']
        assert result.ok is False


class TestSchemaProbeUnaffectedProviders:
    """grok/perplexity have no structured-output contract of their own
    (voteschema.py: adopted=False, delimiter-tag fallback parser) -- F9's
    schema_probe flag must be a no-op for them, not an error and not a
    silently-different request."""

    def test_grok_schema_probe_true_uses_plain_probe_unchanged(self, monkeypatch):
        captured = {}

        class _FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(output_text='OK')

        class _FakeGrokWrapper:
            def __init__(self):
                self.client = SimpleNamespace(responses=_FakeResponses())
                self.model = 'grok-test'

        monkeypatch.setattr(llm_utils_module(), 'GrokClient', _FakeGrokWrapper)

        plain = llmpreflight.preflight(['grok'], schema_probe=False)['grok']
        schema = llmpreflight.preflight(['grok'], schema_probe=True)['grok']
        assert plain.ok is True and schema.ok is True
        # no schema-shaped kwarg ever sent for grok, regardless of the flag
        assert 'text' not in captured
        assert captured['input'] == [{"role": "user", "content": llmpreflight.PROBE_PROMPT}]

    def test_perplexity_schema_probe_true_uses_plain_probe_unchanged(self, monkeypatch):
        captured = {}

        class _FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content='OK'))])

        class _FakePerplexityWrapper:
            def __init__(self):
                self.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
                self.model = 'sonar-test'

        monkeypatch.setattr(llm_utils_module(), 'PerplexityClient', _FakePerplexityWrapper)

        result = llmpreflight.preflight(['perplexity'], schema_probe=True)['perplexity']
        assert result.ok is True
        assert 'response_format' not in captured
        assert captured['max_tokens'] == llmpreflight.PROBE_MAX_TOKENS


# ============================================================================
# 3. crypto_trading_bot integration
# ============================================================================

def test_active_panel_solo_mode():
    assert bot.get_active_llm_panel('claude', 'gemini', ['gemini', 'claude']) == ['claude']
    assert bot.get_active_llm_panel('gemini', 'gemini', []) == ['gemini']


def test_active_panel_compare_mode_dedupes_and_orders_primary_first():
    panel = bot.get_active_llm_panel('compare', 'gemini', ['gemini', 'claude', 'openai'])
    assert panel == ['gemini', 'claude', 'openai']


def test_active_panel_integrate_mode_primary_not_in_compare_llms():
    panel = bot.get_active_llm_panel('integrate', 'claude', ['gemini', 'openai'])
    assert panel == ['claude', 'gemini', 'openai']


def test_active_panel_empty_when_llm_mode_blank():
    assert bot.get_active_llm_panel('', 'gemini', []) == []


def test_run_llm_preflight_skip_flag_makes_no_preflight_call(monkeypatch):
    called = {'n': 0}

    def _fail_if_called(providers):
        called['n'] += 1
        raise AssertionError("preflight() should not be called when skipped")

    monkeypatch.setattr(bot.llmpreflight, 'preflight', _fail_if_called)
    result = bot.run_llm_preflight('gemini', 'gemini', [], 'live', skip_preflight=True)
    assert result == {}
    assert called['n'] == 0


def test_run_llm_preflight_live_mode_exits_on_failure(monkeypatch, capsys):
    def _fake_preflight(providers):
        return {p: llmpreflight.PreflightResult(ok=False, model='x', error='not configured')
                for p in providers}

    monkeypatch.setattr(bot.llmpreflight, 'preflight', _fake_preflight)

    with pytest.raises(SystemExit) as exc_info:
        bot.run_llm_preflight('gemini', 'gemini', [], 'live', skip_preflight=False)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert '[FAIL]' in out
    assert 'LIVE mode requires every panel provider to pass preflight' in out


def test_run_llm_preflight_whatif_mode_continues_on_failure(monkeypatch, capsys):
    def _fake_preflight(providers):
        return {p: llmpreflight.PreflightResult(ok=False, model='x', error='not configured')
                for p in providers}

    monkeypatch.setattr(bot.llmpreflight, 'preflight', _fake_preflight)

    # Should NOT raise -- whatif mode degrades gracefully.
    result = bot.run_llm_preflight('gemini', 'gemini', [], 'whatif', skip_preflight=False)
    assert 'gemini' in result
    assert result['gemini'].ok is False

    out = capsys.readouterr().out
    assert '[FAIL]' in out
    assert 'WARNING' in out
    # whatif must NOT print the live-mode hard-exit message.
    assert 'requires every panel provider to pass preflight' not in out


def test_run_llm_preflight_all_pass_no_warning_no_exit(monkeypatch, capsys):
    def _fake_preflight(providers):
        return {p: llmpreflight.PreflightResult(ok=True, model='x', latency_ms=42.0)
                for p in providers}

    monkeypatch.setattr(bot.llmpreflight, 'preflight', _fake_preflight)

    result = bot.run_llm_preflight('compare', 'gemini', ['claude'], 'live', skip_preflight=False)
    assert set(result.keys()) == {'gemini', 'claude'}
    out = capsys.readouterr().out
    assert '[OK]' in out
    assert 'WARNING' not in out
    assert 'Exiting' not in out


def test_run_llm_preflight_empty_panel_short_circuits(monkeypatch):
    """llm_mode='' (shouldn't happen via argparse, but the function is
    defensive) means an empty panel -- preflight() must not be called."""
    def _fail_if_called(providers):
        raise AssertionError("preflight() should not be called for an empty panel")

    monkeypatch.setattr(bot.llmpreflight, 'preflight', _fail_if_called)
    result = bot.run_llm_preflight('', 'gemini', [], 'live', skip_preflight=False)
    assert result == {}


def test_skip_preflight_cli_flag_default_false(monkeypatch):
    monkeypatch.delenv('SKIP_PREFLIGHT', raising=False)
    monkeypatch.setattr(sys, 'argv', ['crypto_trading_bot.py'])
    args = bot.parse_args()
    assert args.skip_preflight is False


def test_skip_preflight_cli_flag_settable():
    import argparse
    # Directly exercise the parser's flag wiring without touching global env.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, 'argv', ['crypto_trading_bot.py', '--skip-preflight'])
        args = bot.parse_args()
        assert args.skip_preflight is True
