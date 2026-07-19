import openai
import os

from modelregistry import get_model

import panelprompts

import voteschema

class GrokTrader:
    def __init__(self):
        """Initialize the Grok client with API credentials from environment."""
        api_key = os.environ.get('XAI_API_KEY')
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set")
        # LM-6: explicit timeout so a hung provider can't stall a scheduled run
        # for the SDK default (~600s).
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            timeout=90
        )
        self.model = get_model('grok')
        # Web search requires Responses API with web_search tool
        self.tools = [{"type": "web_search"}]
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"

    def _call_responses_api(self, content, structured=False):
        """Call the xAI Responses API with web search enabled.

        T8 phase 2: when structured=True the native json_schema vote format is
        attached via the Responses-shape ``text={'format': ...}`` param (NOT
        chat-completions' response_format). Search grounding (self.tools) is
        kept on BOTH paths; max_output_tokens is left unset (it is a SOFT cap
        on this API, so a tight budget invites truncation, and Grok's analysis
        calls have always run uncapped)."""
        kwargs = dict(
            model=self.model,
            input=[{"role": "user", "content": content}],
            tools=self.tools,
        )
        if structured:
            kwargs["text"] = {"format": voteschema.grok_text_format()}
        response = self.client.responses.create(**kwargs)
        # Extract text from response
        if hasattr(response, 'output_text'):
            return response.output_text
        elif hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'content'):
                    return item.content
        return str(response)

    def _structured_vote(self, build_prompt):
        """Attempt a native structured-output vote; fall back to the hardened
        delimiter-tag REQUEST only if the provider rejects the schema parameter
        itself. Returns the response text tagged with the path taken
        ('structured' | 'fallback') so resolve_vote routes it to the right
        parser. Any OTHER error (timeout, auth, 5xx, content) propagates and is
        mapped to abstain('error') upstream — never a silent fallback, and a
        structured response that returned garbage fails closed to
        abstain('parse_failure') at parse time, never a re-parse of the same
        garbage as a delimiter tag.

        build_prompt(vote_instruction) -> prompt text; called with None on the
        structured path (voteschema.schema_instruction) and with the delimiter
        instruction on the fallback path."""
        try:
            text = self._call_responses_api(build_prompt(None), structured=True)
            return voteschema.tag_vote_path(text, 'structured')
        except Exception as e:
            if not voteschema.schema_param_rejected(e):
                raise
            print("[FALLBACK PARSER] grok: native structured output rejected "
                  f"the schema parameter ({type(e).__name__}: {e}); retrying "
                  "with the delimiter-tag request")
            text = self._call_responses_api(
                build_prompt(panelprompts.DELIMITER_VOTE_INSTRUCTION),
                structured=False)
            return voteschema.tag_vote_path(text, 'fallback')

    def send_recommendation_request(self, dex_mode: bool = False):
        """Get cryptocurrency recommendations from Grok."""
        if dex_mode:
            prompt = "Using real-time web search for current market data and sentiment, what 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you find."
        else:
            prompt = "Using real-time web search for current market data and sentiment, what 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you find."

        # Discovery parsing is +++SYM+++, not a vote schema — stays unstructured.
        return self._call_responses_api(prompt)

    def send_coin_check_request(self, coin_symbol, market_block=None):
        """Check if a specific coin should be bought, sold, or held.

        T8 phase 2: native structured JSON vote (delimiter-tag request kept as
        the schema-rejection fallback). Returns the JSON vote as text, tagged
        with the path taken.
        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        return self._structured_vote(
            lambda vi: panelprompts.coin_check_prompt(
                coin_symbol, self.coin_type, market_block,
                preamble=panelprompts.GROK_SEARCH_PREAMBLE,
                vote_instruction=vi))

    def send_trend_check_request(self, coin_symbol, trends_data=None, market_block=None):
        """Check coin recommendation based on Google Trends analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        # Grok drift preserved (see panelprompts drift notes): its trends
        # block ends without a trailing space and the vote instruction is
        # joined by a single space.
        return self._structured_vote(
            lambda vi: panelprompts.trend_check_prompt(
                coin_symbol, self.coin_type, trends_data, market_block,
                preamble=panelprompts.GROK_TRENDS_PREAMBLE,
                vote_instruction=vi,
                trends_use_line=panelprompts.GROK_TRENDS_USE_LINE,
                vote_sep=" "))

    def send_integrated_coin_check(self, coin_symbol, peer_analysis, market_block=None):
        """Round 2: Check coin with peer LLM analysis as additional context.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        return self._structured_vote(
            lambda vi: panelprompts.integrated_coin_check_prompt(
                coin_symbol, self.coin_type, peer_analysis, market_block,
                preamble=panelprompts.GROK_SEARCH_PREAMBLE,
                vote_instruction=vi))

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None, market_block=None):
        """Round 2: Check coin with Google Trends + peer LLM analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        return self._structured_vote(
            lambda vi: panelprompts.integrated_trend_check_prompt(
                coin_symbol, self.coin_type, peer_analysis, trends_data,
                market_block,
                preamble=panelprompts.GROK_TRENDS_PREAMBLE,
                vote_instruction=vi))
