"""Tests for extract_recommendation / extract_tagged_vote (crypto_trading_bot.py).

Ported from lab/session_tests_20260718/_extract_rec_snippet.py (formerly
test_extract_rec.py) (14 cases). Now
imported for real via crypto_trading_bot's importable module (T4a) instead of
the exec-source-extraction trick.

T8 hardening update: extract_recommendation is now the FALLBACK parser only
(grok/perplexity); gemini/claude/openai votes arrive as schema-enforced JSON
and never touch this code. The two residual parser gaps that were xfail'd
pending T8 are now closed for the fallback path too:
  - triple-backtick fenced blocks are stripped (like inline backtick spans);
  - the concluding tag must actually conclude: prose after the last tag
    means it was cited mid-sentence, not issued, and nothing parses.
The two ported cases that documented those gaps as "residual risk" have been
updated to the new (safe) expectations, marked below.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from crypto_trading_bot import extract_recommendation, extract_tagged_vote


# --- Ported from lab/session_tests_20260718/_extract_rec_snippet.py (formerly test_extract_rec.py) ---
# (name, input, expected). Two rows changed by T8 (marked): they used to
# document residual false-positive risk; the hardened parser closes both.
CASES = [
    ("normal BUY", "Analysis... upward momentum.\n<**SOL-PRS-BUY**>", "BUY"),
    ("normal HOLD", "Mixed signals.\n<**ETH-PRS-HOLD**>", "HOLD"),
    ("refusal quoting format in backticks (finding 1.1)",
     "I can't provide a real-time buy/sell/hold recommendation for ETH. "
     "The requested format (`<**ETH-PRS-BUY**>`, `<**ETH-PRS-SELL**>`, or `<**ETH-PRS-HOLD**>`) "
     "implies certainty I don't have.", None),
    ("refusal quoting format WITHOUT backticks",
     "I can't recommend. The format would be <**ETH-PRS-BUY**> for a buy, "
     "but I won't issue one.", None),  # T8: prose after the tag -> cited, not issued
    ("last occurrence wins",
     "If bullish I'd say <**ETH-PRS-BUY**>. But given the data: <**ETH-PRS-HOLD**>", "HOLD"),
    ("discussion then real tag",
     "The options are BUY, SELL, or HOLD. My recommendation: <**BONK-PRS-SELL**>", "SELL"),
    ("empty string", "", None),
    ("None input", None, None),
    ("no tag at all", "I recommend holding ETH for now.", None),
    ("partial tag missing close", "<**ETH-PRS-BUY", None),
    ("lowercase keyword", "<**eth-prs-buy**>", None),
    ("tag inside triple-backtick code block",
     "Example output:\n```\n<**ETH-PRS-BUY**>\n```\nBut I decline to recommend.", None),  # T8: fenced blocks stripped
    ("bold-wrapped tag variant", "**<**ETH-PRS-HOLD**>**", "HOLD"),
    ("whitespace inside tag", "<** ETH-PRS-BUY **>", None),
]


@pytest.mark.parametrize("name,input_text,expected", CASES, ids=[c[0] for c in CASES])
def test_extract_recommendation_ported(name, input_text, expected):
    assert extract_recommendation(input_text) == expected


# --- T8: the two former xfails, now plain passing expectations ---

def test_fenced_code_block_tag_should_not_parse():
    """A tag quoted inside a triple-backtick fenced block as an *example*
    is stripped before matching, mirroring the single-backtick stripping.
    (Was xfail pending T8; the fallback parser now strips fenced blocks.)"""
    text = "Example output:\n```\n<**ETH-PRS-BUY**>\n```\nBut I decline to recommend."
    assert extract_recommendation(text) is None


def test_unbackticked_cited_example_should_not_parse():
    """A refusal that cites the tag format as prose (no backticks at all)
    no longer parses: the prompt asks models to CONCLUDE with the tag, so a
    tag followed by more prose ("... for a buy, but I won't issue one") is a
    citation, not a recommendation. (Was xfail pending T8.)"""
    text = ("I can't recommend. The format would be <**ETH-PRS-BUY**> for a buy, "
            "but I won't issue one.")
    assert extract_recommendation(text) is None


# --- T8: new hardening coverage for the fallback parser ---

def test_unterminated_fence_is_treated_as_quoted():
    """An opening ``` with no closing fence quotes everything after it
    (conservative: an unterminated example block never yields a vote)."""
    text = "I decline. Example:\n```\n<**ETH-PRS-BUY**>"
    assert extract_recommendation(text) is None


def test_trailing_nonletter_content_is_allowed():
    """Markdown asterisks, punctuation, and bracketed citation markers after
    the concluding tag do not invalidate it (only prose does)."""
    assert extract_recommendation("Analysis...\n<**BTC-PRS-HOLD**>.") == "HOLD"
    assert extract_recommendation("Analysis...\n<**BTC-PRS-HOLD**> [1][2]") == "HOLD"


def test_trailing_prose_on_new_line_blocks_parse():
    """Fail closed: substantive prose anywhere after the last tag (even on a
    new line, e.g. a disclaimer) means the tag did not conclude the response."""
    text = "<**BTC-PRS-BUY**>\n\nDisclaimer: this is not financial advice."
    assert extract_recommendation(text) is None


def test_contradicting_prose_after_tag_never_parses():
    """F6 kept the concluding-tag rule (2026-07-18 corpus: zero over-abstain
    rejections observed). This is the case that motivated the rule: prose
    after the tag that CONTRADICTS it must never be recovered as a vote."""
    text = "<**ETH-PRS-BUY**>\nOn second thought, sell - the momentum is gone."
    assert extract_recommendation(text) is None


def test_extract_tagged_vote_returns_symbol_and_action():
    """The tag's symbol prefix is surfaced for symbol binding upstream."""
    assert extract_tagged_vote("Analysis...\n<**SOL-PRS-BUY**>") == ("SOL", "BUY")
    assert extract_tagged_vote("done <**Ethereum-PRS-HOLD**>") == ("Ethereum", "HOLD")
    assert extract_tagged_vote("no tag here") == (None, None)


def test_adjacent_tags_do_not_cross_match():
    """The symbol group cannot span across an earlier malformed tag (the
    character class excludes angle brackets)."""
    text = "see <** notes **> and final <**ETH-PRS-BUY**>"
    assert extract_tagged_vote(text) == ("ETH", "BUY")


# --- Current-behavior drift, documented as plain passing tests ---

def test_spaced_tag_returns_none_today():
    """`<**Ethereum - PRS - HOLD**>` (spaces around the dashes) does not
    match the tight tag regex, so it silently returns None rather than
    erroring. This documents a drift/gap for the FALLBACK path only: any
    whitespace variance from a model produces a silent non-parse (which the
    consensus layer records as abstain(parse_failure) — fail closed)."""
    assert extract_recommendation("<**Ethereum - PRS - HOLD**>") is None


def test_coin_agnostic_parser_binds_at_resolve_vote_layer():
    """extract_recommendation itself remains symbol-agnostic (a DOGE tag in
    an ETH analysis still parses as an action here), but T8 closes the
    coin-agnostic gap one layer up: resolve_vote binds the tag's symbol
    against the coin under analysis and turns a mismatch into
    abstain(symbol_mismatch) — see test_consensus.py::TestT8StructuredIntegration."""
    text = "Analysis of ETH market conditions... <**DOGE-PRS-BUY**>"
    assert extract_recommendation(text) == "BUY"
    assert extract_tagged_vote(text) == ("DOGE", "BUY")
