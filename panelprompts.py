"""Central builders for the panel's analysis prompts (LM-2, audit 2026-07-19).

Before this module, the core analysis prompt existed in ~20 verbatim copies
across claudeutil.py, openaiutil.py, grokutil.py, perplexityutil.py, and the
inline Gemini senders in crypto_trading_bot.py -- so every prompt tweak (the
most frequent change in an LLM bot) was a 5-file edit that could silently
drift into panelists being asked different questions. The four builders below
are now the ONLY source of analysis-prompt text; the provider utils keep only
SDK plumbing. Byte-identical output for every call site is enforced by the
golden characterization tests in tests/test_panel_prompts.py (fixture
generated from the pre-centralization duplicated strings).

Scope: the four analysis prompt families only (coin check, trend check, and
their Round-2 integrated variants). Discovery prompts
(send_recommendation_request / sendRecommendationRequest) and the
get_llm_response dispatch are deliberately out of scope.

Inter-provider drift, PRESERVED (parameterized), not unified -- unifying any
of it is a semantic prompt change that needs its own owner-reviewed commit
with a regenerated golden fixture:
  - gemini/claude/openai are byte-identical: no preamble, structured-output
    vote instruction (voteschema.schema_instruction -- the builders' default).
  - grok prefixes GROK_SEARCH_PREAMBLE / GROK_TRENDS_PREAMBLE, and its
    (non-integrated) trend section ends "analysis." with NO trailing space,
    joined to the vote instruction by a single space (everyone else:
    "analysis. " and no join separator).
  - perplexity appends per-variant sentences after the core question
    (" Use current market data and recent news." / " Use current market
    data." / " Use live data."), joins the vote instruction with NO separator
    (so trend-check with no trends data reads "Use live data.<vote>"), and its
    two trend variants use two DIFFERENT preambles
    (PERPLEXITY_TREND_CHECK_PREAMBLE vs PERPLEXITY_INTEGRATED_TREND_PREAMBLE).

  Vote instruction (T8 phase 2, 2026-07-19): grok and perplexity now default to
  the structured-output vote instruction (voteschema.schema_instruction), same
  as the other three -- they were migrated to native json_schema output. The
  DELIMITER_VOTE_INSTRUCTION below is retained only for their schema-rejection
  FALLBACK request: grokutil/perplexityutil pass it explicitly as
  vote_instruction when a structured attempt is rejected on the schema
  parameter (see their _structured_vote). All the per-provider preamble /
  suffix / spacing drift above is unchanged and applies on BOTH paths.

Every builder takes coin_type explicitly ("cryptocurrency" vs "meme coin");
the callers keep their existing resolution (traders: self.coin_type from the
ANALYZE_COINS env var; Gemini call sites: USE_COIN_DISCOVERY).
"""
import voteschema


# --- Vote instructions -------------------------------------------------------

# The hardened-fallback-parser providers (grok/perplexity) get this delimiter
# instruction; it must stay in sync with the tag regex in
# crypto_trading_bot.extract_tagged_vote (<**SYMBOL-PRS-ACTION**>).
DELIMITER_VOTE_INSTRUCTION = (
    "Conclude your analysis with a left angle bracket, followed by two "
    "asterisks, followed by the name of the coin being analyzed, followed by "
    "a dash, followed by the string PRS, followed by another dash, followed "
    "by the recommendation expressed as either the keyword BUY, SELL, or "
    "HOLD, followed by two asterisks, followed by a right angle bracket"
)

# --- Per-provider preamble / phrasing variants (see drift notes above) -------

GROK_SEARCH_PREAMBLE = (
    "Using real-time web search for current market data and sentiment, ")
GROK_TRENDS_PREAMBLE = (
    "Using real-time web search combined with Google Trends analysis, ")
PERPLEXITY_TREND_CHECK_PREAMBLE = (
    "Based on analysis of recent social media trends and Google Trends data, ")
PERPLEXITY_INTEGRATED_TREND_PREAMBLE = (
    "Based on analysis of recent social media and search trends, ")

# Default trend preamble (gemini/claude/openai, both trend variants).
TREND_CHECK_PREAMBLE = "Based on analysis of recent data from Google Trends, "

# --- Shared fragments --------------------------------------------------------

TRENDS_NOTE = (
    "Note: values are scaled so the window maximum = 100; on low-volume "
    "tickers a single stray minute can appear as a spike to 100. Absolute "
    "search volume may be near zero."
)

TRENDS_USE_LINE = "Use this data in your analysis. "
GROK_TRENDS_USE_LINE = "Use this data in your analysis."  # no trailing space


def _prefix(market_block):
    """T9: the market block is prepended as the PRIMARY data section."""
    return f"{market_block}\n\n" if market_block else ""


def _core_question(coin_type, coin_symbol, preamble=""):
    """The shared core question. With a preamble the sentence continues in
    lowercase ('..., would a sophisticated ...'); without one it opens the
    prompt ('Would a sophisticated ...')."""
    lead_in = "would" if preamble else "Would"
    return (
        f"{preamble}{lead_in} a sophisticated trading bot designed for "
        f"short-term appreciation recommend buying, selling, or holding the "
        f"{coin_type} with symbol {coin_symbol} right now?"
    )


def _vote(vote_instruction, coin_symbol):
    return (voteschema.schema_instruction(coin_symbol)
            if vote_instruction is None else vote_instruction)


def _trend_section(trends_data, use_line):
    """The (non-integrated) trend-check GOOGLE TRENDS block; '' when there is
    no data (the market block's T9 SECONDARY section discloses absence)."""
    if not trends_data:
        return ""
    return (
        f"\n\nHere is the actual Google Trends data we collected:\n\n"
        f"---BEGIN GOOGLE TRENDS DATA---\n{trends_data}\n"
        f"---END GOOGLE TRENDS DATA---\n\n{TRENDS_NOTE}\n\n{use_line}"
    )


def _integrated_trend_section(trends_data):
    """The Round-2 (integrated) variant of the trends block; note the
    different leading/trailing newline shape vs _trend_section."""
    if not trends_data:
        return ""
    return (
        f"\nHere is the actual Google Trends data we collected:\n\n"
        f"---BEGIN GOOGLE TRENDS DATA---\n{trends_data}\n"
        f"---END GOOGLE TRENDS DATA---\n\n{TRENDS_NOTE}\n\n"
    )


# --- The four builders -------------------------------------------------------

def coin_check_prompt(coin_symbol, coin_type, market_block=None, *,
                      preamble="", question_suffix="", vote_instruction=None):
    """Round-1 coin check. Defaults produce the gemini/claude/openai bytes;
    grok passes preamble=GROK_SEARCH_PREAMBLE and the delimiter instruction;
    perplexity passes question_suffix=' Use current market data and recent
    news.' and the delimiter instruction."""
    return (
        f"{_prefix(market_block)}"
        f"{_core_question(coin_type, coin_symbol, preamble)}"
        f"{question_suffix} {_vote(vote_instruction, coin_symbol)}"
    )


def trend_check_prompt(coin_symbol, coin_type, trends_data=None,
                       market_block=None, *,
                       preamble=TREND_CHECK_PREAMBLE, question_suffix="",
                       vote_instruction=None,
                       trends_use_line=TRENDS_USE_LINE, vote_sep=""):
    """Round-1 trend check. Defaults produce the gemini/claude/openai bytes.
    grok: GROK_TRENDS_PREAMBLE, GROK_TRENDS_USE_LINE, vote_sep=' ', delimiter
    instruction. perplexity: PERPLEXITY_TREND_CHECK_PREAMBLE,
    question_suffix=' Use live data.', delimiter instruction."""
    return (
        f"{_prefix(market_block)}"
        f"{_core_question(coin_type, coin_symbol, preamble)}"
        f"{question_suffix}"
        f"{_trend_section(trends_data, trends_use_line)}"
        f"{vote_sep}{_vote(vote_instruction, coin_symbol)}"
    )


def integrated_coin_check_prompt(coin_symbol, coin_type, peer_analysis,
                                 market_block=None, *,
                                 preamble="", question_suffix="",
                                 vote_instruction=None):
    """Round-2 coin check with peer analysis cross-fed. Defaults produce the
    gemini/claude/openai bytes; grok passes preamble=GROK_SEARCH_PREAMBLE;
    perplexity passes question_suffix=' Use current market data.'."""
    return (
        f"{_prefix(market_block)}"
        f"{_core_question(coin_type, coin_symbol, preamble)}"
        f"{question_suffix}\n\n"
        f"Additionally, consider the following analysis from another AI system:\n\n"
        f"---BEGIN PEER ANALYSIS---\n{peer_analysis}\n---END PEER ANALYSIS---\n\n"
        f"After reviewing the peer analysis, provide your final recommendation. "
        f"You may agree, disagree, or refine your position based on this input.\n\n"
        f"{_vote(vote_instruction, coin_symbol)}"
    )


def integrated_trend_check_prompt(coin_symbol, coin_type, peer_analysis,
                                  trends_data=None, market_block=None, *,
                                  preamble=TREND_CHECK_PREAMBLE,
                                  question_suffix="", vote_instruction=None):
    """Round-2 trend check with peer analysis cross-fed. Defaults produce the
    gemini/claude/openai bytes; grok passes preamble=GROK_TRENDS_PREAMBLE;
    perplexity passes preamble=PERPLEXITY_INTEGRATED_TREND_PREAMBLE and
    question_suffix=' Use live data.'."""
    return (
        f"{_prefix(market_block)}"
        f"{_core_question(coin_type, coin_symbol, preamble)}"
        f"{question_suffix}\n"
        f"{_integrated_trend_section(trends_data)}\n"
        f"Additionally, consider the following analysis from another AI system:\n\n"
        f"---BEGIN PEER ANALYSIS---\n{peer_analysis}\n---END PEER ANALYSIS---\n\n"
        f"After reviewing the peer analysis and the Google Trends data provided, "
        f"provide your final recommendation. You may agree, disagree, or refine "
        f"your position based on this input.\n\n"
        f"{_vote(vote_instruction, coin_symbol)}"
    )
