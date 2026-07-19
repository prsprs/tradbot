import openai
import os

from modelregistry import get_model

import panelprompts

import voteschema


class OpenAITrader:
    def __init__(self):
        """Initialize the OpenAI client with API credentials from environment."""
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        # LM-6: explicit timeout so a hung provider can't stall a scheduled run
        # for the SDK default (~600s).
        self.client = openai.OpenAI(api_key=api_key, timeout=90)
        self.model = get_model('openai')
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
    
    def send_recommendation_request(self, dex_mode: bool = False):
        """Get cryptocurrency recommendations from OpenAI."""
        if dex_mode:
            prompt = "What 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
        else:
            prompt = "What 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        return response.choices[0].message.content
    
    def send_coin_check_request(self, coin_symbol, market_block=None):
        """Check if a specific coin should be bought, sold, or held.

        T8: native structured output (response_format json_schema strict,
        probe-verified for gpt-5.5 — see
        tests/fixtures/structured_output/openai.json). Returns the JSON vote
        as text; '' when content is empty (e.g. finish_reason=length with the
        budget consumed by reasoning) so downstream maps it to
        abstain(parse_failure), never a vote.
        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        response = self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=4096,
            response_format=voteschema.openai_response_format(),
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.coin_check_prompt(
                        coin_symbol, self.coin_type, market_block)
                }
            ]
        )
        return response.choices[0].message.content or ""
    
    def send_trend_check_request(self, coin_symbol, trends_data=None, market_block=None):
        """Check coin recommendation based on Google Trends analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        response = self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=4096,
            response_format=voteschema.openai_response_format(),
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.trend_check_prompt(
                        coin_symbol, self.coin_type, trends_data, market_block)
                }
            ]
        )
        return response.choices[0].message.content or ""

    def send_integrated_coin_check(self, coin_symbol, peer_analysis, market_block=None):
        """Round 2: Check coin with peer LLM analysis as additional context.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        response = self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=4096,
            response_format=voteschema.openai_response_format(),
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.integrated_coin_check_prompt(
                        coin_symbol, self.coin_type, peer_analysis, market_block)
                }
            ]
        )
        return response.choices[0].message.content or ""

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None, market_block=None):
        """Round 2: Check coin with Google Trends + peer LLM analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        response = self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=4096,
            response_format=voteschema.openai_response_format(),
            messages=[
                {
                    "role": "user",
                    "content": panelprompts.integrated_trend_check_prompt(
                        coin_symbol, self.coin_type, peer_analysis,
                        trends_data, market_block)
                }
            ]
        )
        return response.choices[0].message.content or ""
