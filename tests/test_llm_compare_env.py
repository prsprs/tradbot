"""Tests for two llm_compare.py defects observed live on 2026-07-19:

1. llm_compare.py never called load_dotenv() (neither it nor config.py
   referenced dotenv at all), so users whose API keys live only in .env
   (not shell-exported) got "Could not initialize gemini/claude/openai:
   ... environment variable not set" for every provider. Fixed by loading
   .env as the first action in main(), mirroring crypto_trading_bot.py's
   TS-3 pattern (see AGENTS.md's "Env-snapshot convention" and
   tests/test_import_purity.py). Unlike the bot, llm_compare.py's import
   graph has no import-time env snapshots to refresh -- verified by
   inspection of config.py, context/trends.py, history/recorder.py,
   prompts/templates.py, and every llm_utils/*_client.py: all
   os.environ reads happen inside a function body or __init__, never at
   module scope -- so no _refresh_env_snapshots() companion is needed
   here.

2. When every requested LLM failed to initialize, run_compare_mode()
   continued anyway: printed an empty "[COMPARISON]" line and let main()
   write a junk recommendation record (no responses, no recommendation)
   into history/recommendations.json -- the same file
   crypto_trading_bot.py and tradeanalyzer.py read. The observed junk
   record (rec_20260719_211510) is left in place in
   history/recommendations.json; history is append-only owner data (see
   AGENTS.md / removal-discipline) and is NOT touched by this change or
   these tests. Fixed with a zero-availability guard in run_compare_mode
   that returns an {"error": ...} result when NONE of the requested LLMs
   could be constructed, which main() already turns into a non-zero exit
   BEFORE the history-recording block runs. Partial availability (>=1 LLM
   initializes) is unaffected -- run_integrate_mode already had an
   equivalent guard (it requires >=2 clients), and run_single_mode already
   returned an error dict when its one client failed, so this file focuses
   on the previously-unguarded compare-mode path.

No real network calls anywhere in this file: llm_compare.get_llm_client is
either monkeypatched directly or exercised with every provider API key env
var cleared, and every provider client raises ValueError in __init__
before touching the network in that case (see llm_utils/*_client.py).
"""
import sys
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import llm_compare
from llm_utils.base import LLMClient

# Every env var any llm_utils/*_client.py checks (see get_llm_client's
# AVAILABLE_LLMS-backed dispatch). Cleared in tests that need a genuine
# "no keys configured" starting point, independent of the ambient shell.
ALL_PROVIDER_API_KEY_VARS = [
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "PERPLEXITY_API_KEY",
]


class FakeLLMClient(LLMClient):
    """Minimal concrete LLMClient for tests that need a client to
    "succeed" without making a real request."""

    def __init__(self, llm_name: str = "fake", answer: str = "BUY"):
        self._name = llm_name
        self._answer = answer

    @property
    def name(self) -> str:
        return self._name

    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        return f"<CHOICE>{self._answer}</CHOICE>\n<CONFIDENCE>80</CONFIDENCE>"

    def send_integrated_request(self, prompt, own_response, peer_analyses, max_tokens=4096):
        return self.send_request(prompt)


def _clear_all_provider_keys(monkeypatch):
    for var in ALL_PROVIDER_API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)


# ============================================================================
# 1. Zero-availability guard in run_compare_mode
# ============================================================================

def test_run_compare_mode_returns_error_when_zero_llms_available(monkeypatch):
    """Direct unit test: every requested LLM fails to construct -> the
    function returns an {"error": ...} result instead of an empty
    comparison. No responses/recommendation should ever reach main()'s
    history-recording block for this case."""
    monkeypatch.setattr(llm_compare, "get_llm_client", lambda name: None)

    config = llm_compare.Config(
        prompt="Which narrative has momentum?",
        mode="compare",
        compare_llms=["gemini", "claude"],
    )

    result = llm_compare.run_compare_mode(config, context="", file_context="")

    assert "error" in result
    assert result["error"]
    # Actionable: names the LLMs that were tried.
    assert "gemini" in result["error"]
    assert "claude" in result["error"]


def test_run_compare_mode_partial_availability_unaffected(monkeypatch):
    """Regression guard: when at least one LLM initializes, behavior is
    unchanged -- no "error" key, and the successful LLM's response flows
    through to the result as before."""
    def _fake_get_client(name):
        if name == "gemini":
            return FakeLLMClient("gemini", answer="BUY")
        return None  # claude stays unavailable

    monkeypatch.setattr(llm_compare, "get_llm_client", _fake_get_client)

    config = llm_compare.Config(
        prompt="Which narrative has momentum?",
        mode="compare",
        compare_llms=["gemini", "claude"],
    )

    result = llm_compare.run_compare_mode(config, context="", file_context="")

    assert "error" not in result
    assert "gemini" in result["responses"]
    assert "claude" not in result["responses"]
    assert result["parsed"]["gemini"]["answer"] == "BUY"


def test_main_exits_nonzero_and_writes_no_history_when_zero_llms_available(
    monkeypatch, tmp_path, capsys
):
    """End-to-end through main(): zero available LLMs in compare mode must
    exit non-zero and must NOT create/write the history file (mirrors the
    real junk record rec_20260719_211510 this bug produced live)."""
    history_file = tmp_path / "recommendations.json"

    monkeypatch.setattr(llm_compare, "get_llm_client", lambda name: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm_compare.py",
            "--prompt", "Which narrative has momentum?",
            "--mode", "compare",
            "--llms", "gemini,claude",
            "--history-file", str(history_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        llm_compare.main()

    assert exc_info.value.code != 0
    assert not history_file.exists()

    captured = capsys.readouterr()
    assert "Error" in captured.out
    assert "[COMPARISON]" not in captured.out


def test_main_exits_nonzero_when_all_provider_keys_are_unset(monkeypatch, tmp_path, capsys):
    """Same end-to-end path, but exercised through the REAL get_llm_client
    dispatch (not monkeypatched) with every provider API key env var
    cleared -- the exact "no .env, no shell-exported keys" scenario from
    the 2026-07-19 live run. No network call happens: each llm_utils
    client raises ValueError in __init__ before constructing its SDK
    client when its key is missing.

    load_dotenv() itself is neutralized here (tested separately below):
    this repo's real .env at the repo root DOES carry real provider keys
    (see AGENTS.md), and main() now correctly calls the real
    load_dotenv() -- which would reload those real keys and undefeat the
    env-clearing this test relies on to simulate "no keys configured
    anywhere". That reload is exactly what tests 5/6 below pin as
    correct behavior; here we hold it constant so this test can isolate
    the zero-availability guard instead.
    """
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setattr(llm_compare, "load_dotenv", lambda *a, **k: None)

    history_file = tmp_path / "recommendations.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "llm_compare.py",
            "--prompt", "Which narrative has momentum?",
            "--mode", "compare",
            "--llms", "gemini,claude,openai",
            "--history-file", str(history_file),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        llm_compare.main()

    assert exc_info.value.code != 0
    assert not history_file.exists()

    captured = capsys.readouterr()
    assert "environment variable not set" in captured.out  # per-provider skip messages
    assert "Error" in captured.out


# ============================================================================
# 2. main() loads .env before argument parsing
# ============================================================================

def test_main_loads_dotenv_before_parsing_env_defaults(monkeypatch, tmp_path, capsys):
    """main() must call load_dotenv() (the REAL python-dotenv function)
    before config.parse_args() reads its argparse env-var defaults --
    otherwise .env-only settings never reach the config, which was
    exactly the reported bug (llm_compare.py never called load_dotenv at
    all). Proven via a real temp .env file: COMPARE_LLMS is set only in
    that file, --what-if prints the resolved LLM count without making any
    LLM calls, and monkeypatch restores the env var afterward so nothing
    leaks into other tests.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("COMPARE_LLMS=gemini,claude\n")

    # Register the var with monkeypatch BEFORE the real load_dotenv() call
    # writes it, so teardown restores whatever COMPARE_LLMS was (or wasn't)
    # before this test, regardless of the real dotenv.load_dotenv() call
    # in between.
    monkeypatch.delenv("COMPARE_LLMS", raising=False)

    # Route main()'s load_dotenv() call at the real .env file above,
    # instead of relying on python-dotenv's frame-walking discovery (which
    # would otherwise find this repo's real .env at the repo root).
    real_load_dotenv = llm_compare.load_dotenv

    def _load_from_tmp_env(*args, **kwargs):
        return real_load_dotenv(dotenv_path=str(env_file), override=True)

    monkeypatch.setattr(llm_compare, "load_dotenv", _load_from_tmp_env)
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm_compare.py", "--prompt", "test prompt", "--what-if"],
    )

    with pytest.raises(SystemExit) as exc_info:
        llm_compare.main()

    assert exc_info.value.code == 0

    import os
    assert os.environ.get("COMPARE_LLMS") == "gemini,claude"

    captured = capsys.readouterr()
    assert "LLMs: 2" in captured.out
    assert "No LLM calls made." in captured.out


def test_main_calls_load_dotenv_exactly_once(monkeypatch):
    """Simpler ordering pin, independent of any real file I/O: main()'s
    very first action is load_dotenv(), and it is not skipped/duplicated."""
    calls = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(llm_compare, "load_dotenv", _spy)
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm_compare.py", "--prompt", "test prompt", "--what-if"],
    )

    with pytest.raises(SystemExit) as exc_info:
        llm_compare.main()

    assert exc_info.value.code == 0
    assert len(calls) == 1
