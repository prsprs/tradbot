import anthropic
import os

from modelregistry import get_model

import panelprompts

import sampling

import voteschema


def _claude_output_config():
    """T8 native structured output: anthropic>=0.94 supports
    output_config={'format': {'type': 'json_schema', ...}} on
    messages.create (probe-verified 2026-07-18, see
    tests/fixtures/structured_output/claude.json). The schema variant drops
    minimum/maximum, which this API rejects on number properties; the
    confidence range is validated client-side in voteschema.parse_vote."""
    return {
        "format": {
            "type": "json_schema",
            "schema": voteschema.schema_for_claude(),
        }
    }


class ClaudeTrader:
    # WS5: class-level default so `**self._sampling_params` is always safe --
    # incl. instances built via __new__ (the request-shape tests) that skip
    # __init__. {} => byte-identical requests; __init__ overrides per-instance.
    _sampling_params = {}

    def __init__(self):
        """Initialize the Anthropic Claude client with API credentials from environment."""
        # LM-1: accept the standard ANTHROPIC_API_KEY name too (CLAUDE_API_KEY
        # keeps precedence). The money path and llmpreflight must agree on
        # which env vars configure Claude, or a green preflight can precede a
        # full run of standing abstains.
        api_key = os.environ.get('CLAUDE_API_KEY') or os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("Neither CLAUDE_API_KEY nor ANTHROPIC_API_KEY environment variable set")
        # LM-6: explicit timeout so a hung provider can't stall a scheduled run
        # for the SDK default (~600s).
        self.client = anthropic.Anthropic(api_key=api_key, timeout=90)
        self.model = get_model('claude')
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
        # WS5: sampling params for ANALYSIS requests. {} unless
        # --deterministic-sampling is on (then {'temperature': 0}); read at
        # construction (main() sets the env before building traders). Splatting
        # {} leaves the request byte-identical to today.
        self._sampling_params = sampling.request_params(
            'claude', sampling.is_enabled())
    
    def send_recommendation_request(self, dex_mode: bool = False, phrase: str = 'meme coins'):
        """Get cryptocurrency recommendations from Claude.

        WS9b: `phrase` is the resolved --discovery-universe phrase (default
        'meme coins' == today's hardcoded text, so the .replace() below is a
        no-op and the prompt stays byte-identical unless a caller passes a
        different universe phrase; resolved by crypto_trading_bot's
        get_primary_recommendation, mirroring build_discovery_prompt for the
        gemini path). See tests/test_discovery_universe.py.
        """
        if dex_mode:
            prompt = "What 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
        else:
            prompt = "What 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
        prompt = prompt.replace('meme coins', phrase, 1)

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")
    
    def send_coin_check_request(self, coin_symbol, market_block=None):
        """Check if a specific coin should be bought, sold, or held.

        T8: returns the model's schema-enforced JSON vote as text ('' when no
        text block came back, e.g. the token budget was consumed — downstream
        that maps to abstain(parse_failure), never a vote).
        T9: market_block (Coinbase market-data + fib + demoted trends + a
        grounding line) is prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            **self._sampling_params,
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.coin_check_prompt(
                        coin_symbol, self.coin_type, market_block)
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")
    
    def send_trend_check_request(self, coin_symbol, trends_data=None, market_block=None):
        """Check coin recommendation based on Google Trends analysis.

        T9: market_block, when supplied, is prepended as the PRIMARY data
        section (it already carries the demoted trends signal); in the live
        bot flow trends_data is folded into market_block, but the trends_data
        path is retained for direct use and its own tests."""
        if coin_symbol is None:
            return None
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            **self._sampling_params,
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.trend_check_prompt(
                        coin_symbol, self.coin_type, trends_data, market_block)
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")

    def send_integrated_coin_check(self, coin_symbol, peer_analysis, market_block=None):
        """Round 2: Check coin with peer LLM analysis as additional context.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            **self._sampling_params,
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.integrated_coin_check_prompt(
                        coin_symbol, self.coin_type, peer_analysis, market_block)
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None, market_block=None):
        """Round 2: Check coin with Google Trends + peer LLM analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            **self._sampling_params,
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.integrated_trend_check_prompt(
                        coin_symbol, self.coin_type, peer_analysis,
                        trends_data, market_block)
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")


# LM-5 (audit 2026-07-19): the legacy 2-LLM consensus helpers
# compare_recommendations() and get_consensus_action() were DELETED from this
# module. Zero call sites existed on either branch beyond the bot's import
# line; their capability lives in crypto_trading_bot's PanelDecision /
# process_coin_with_comparison, EXCEPT the deliberately-dropped
# require_consensus=False single-model fallback (fail-open; forbidden by the
# fail-closed money-path invariant). Full record: docs/SUPERSEDED.md.
