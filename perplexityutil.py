import openai
import os

from modelregistry import get_model

import panelprompts

import sampling

import voteschema

class PerplexityTrader:
    # WS5: class-level default so the analysis path is safe on instances built
    # via __new__ (the request-shape tests) that skip __init__. {} =>
    # byte-identical requests; __init__ overrides per-instance.
    _sampling_params = {}

    def __init__(self):
        """Initialize the Perplexity client with API credentials from environment."""
        api_key = os.environ.get('PERPLEXITY_API_KEY')
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable not set")
        # LM-6: explicit timeout so a hung provider can't stall a scheduled run
        # for the SDK default (~600s).
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
            timeout=90
        )
        self.model = get_model('perplexity')
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
        # WS5: sampling params for ANALYSIS requests. {} unless
        # --deterministic-sampling is on (then {'temperature': 0}, honored by the
        # OpenAI-compatible chat API). Only the analysis path (_structured_vote)
        # passes these; discovery stays untouched. Splatting {} = byte-identical.
        self._sampling_params = sampling.request_params(
            'perplexity', sampling.is_enabled())

    def _call_chat(self, content, structured=False, sampling_params=None):
        """Call Perplexity chat.completions.

        T8 phase 2: when structured=True the native json_schema vote format is
        attached via response_format (the wrapper has no name/strict keys —
        Perplexity-specific). max_tokens stays at the generous 4096 the bot has
        always used: the live TRUNCATION HAZARD (unterminated JSON) appears at
        tight budgets, and a truncated tail fails closed to
        abstain('parse_failure') rather than being trusted.

        WS5: sampling_params (analysis path only) merges determinism knobs
        (temperature=0); None/{} leaves the request byte-identical to today."""
        kwargs = dict(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        if structured:
            kwargs["response_format"] = voteschema.perplexity_response_format()
        if sampling_params:
            kwargs.update(sampling_params)
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def _structured_vote(self, build_prompt):
        """Attempt a native structured-output vote; fall back to the hardened
        delimiter-tag REQUEST only if the provider rejects the schema parameter
        itself. Returns the response text tagged with the path taken
        ('structured' | 'fallback') so resolve_vote routes it to the right
        parser. Any OTHER error (timeout, auth, 5xx, content) propagates and is
        mapped to abstain('error') upstream; a structured response that came
        back as garbage or truncated JSON fails closed to
        abstain('parse_failure') at parse time — never re-parsed as a tag.

        build_prompt(vote_instruction) -> prompt text; called with None on the
        structured path (voteschema.schema_instruction) and with the delimiter
        instruction on the fallback path."""
        try:
            text = self._call_chat(build_prompt(None), structured=True,
                                   sampling_params=self._sampling_params)
            return voteschema.tag_vote_path(text, 'structured')
        except Exception as e:
            if not voteschema.schema_param_rejected(e):
                raise
            print("[FALLBACK PARSER] perplexity: native structured output "
                  f"rejected the schema parameter ({type(e).__name__}: {e}); "
                  "retrying with the delimiter-tag request")
            text = self._call_chat(
                build_prompt(panelprompts.DELIMITER_VOTE_INSTRUCTION),
                structured=False, sampling_params=self._sampling_params)
            return voteschema.tag_vote_path(text, 'fallback')

    def send_recommendation_request(self, dex_mode: bool = False, phrase: str = 'meme coins'):
        """Get cryptocurrency recommendations from Perplexity with live web search.

        WS9b: `phrase` is the resolved --discovery-universe phrase (default
        'meme coins' == today's hardcoded text, so the .replace() below is a
        no-op unless a caller passes a different universe phrase; resolved by
        crypto_trading_bot's get_primary_recommendation, mirroring
        build_discovery_prompt for the gemini path). Note Perplexity's prompt
        ending ("...you find.") is NOT byte-identical to the gemini/claude/
        openai discovery prompts ("...you are aware of.") -- only the
        "meme coins" phrase is parameterized here. See
        tests/test_discovery_universe.py.
        """
        if dex_mode:
            prompt = "What 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you find."
        else:
            prompt = "What 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you find."
        prompt = prompt.replace('meme coins', phrase, 1)

        # Discovery parsing is +++SYM+++, not a vote schema — stays unstructured.
        return self._call_chat(prompt)

    def send_coin_check_request(self, coin_symbol, market_block=None):
        """Check if a specific coin should be bought, sold, or held using live web data.

        T8 phase 2: native structured JSON vote (delimiter-tag request kept as
        the schema-rejection fallback). Returns the JSON vote as text, tagged
        with the path taken.
        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        return self._structured_vote(
            lambda vi: panelprompts.coin_check_prompt(
                coin_symbol, self.coin_type, market_block,
                question_suffix=" Use current market data and recent news.",
                vote_instruction=vi))

    def send_trend_check_request(self, coin_symbol, trends_data=None, market_block=None):
        """Check coin recommendation based on live trend analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        # Perplexity drift preserved (see panelprompts drift notes): its own
        # trend preamble, a " Use live data." suffix, and NO separator before
        # the vote instruction.
        return self._structured_vote(
            lambda vi: panelprompts.trend_check_prompt(
                coin_symbol, self.coin_type, trends_data, market_block,
                preamble=panelprompts.PERPLEXITY_TREND_CHECK_PREAMBLE,
                question_suffix=" Use live data.",
                vote_instruction=vi))

    def send_integrated_coin_check(self, coin_symbol, peer_analysis, market_block=None):
        """Round 2: Check coin with peer LLM analysis as additional context.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        return self._structured_vote(
            lambda vi: panelprompts.integrated_coin_check_prompt(
                coin_symbol, self.coin_type, peer_analysis, market_block,
                question_suffix=" Use current market data.",
                vote_instruction=vi))

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None, market_block=None):
        """Round 2: Check coin with live trends + peer LLM analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        # Note the DIFFERENT preamble vs send_trend_check_request -- historic
        # drift, preserved deliberately (see panelprompts drift notes).
        return self._structured_vote(
            lambda vi: panelprompts.integrated_trend_check_prompt(
                coin_symbol, self.coin_type, peer_analysis,
                trends_data, market_block,
                preamble=panelprompts.PERPLEXITY_INTEGRATED_TREND_PREAMBLE,
                question_suffix=" Use live data.",
                vote_instruction=vi))
