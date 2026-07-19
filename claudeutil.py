import anthropic
import os

from modelregistry import get_model

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
    def __init__(self):
        """Initialize the Anthropic Claude client with API credentials from environment."""
        api_key = os.environ.get('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError("CLAUDE_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = get_model('claude')
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
    
    def send_recommendation_request(self, dex_mode: bool = False):
        """Get cryptocurrency recommendations from Claude."""
        if dex_mode:
            prompt = "What 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
        else:
            prompt = "What 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
        
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
        prefix = f"{market_block}\n\n" if market_block else ""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            messages=[
                {
                    "role": "user",
                    "content": f"{prefix}Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? {voteschema.schema_instruction(coin_symbol)}"
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
        prefix = f"{market_block}\n\n" if market_block else ""

        # Build trends section if data is available
        trends_section = ""
        if trends_data:
            trends_section = f"""

Here is the actual Google Trends data we collected:

---BEGIN GOOGLE TRENDS DATA---
{trends_data}
---END GOOGLE TRENDS DATA---

Note: values are scaled so the window maximum = 100; on low-volume tickers a single stray minute can appear as a spike to 100. Absolute search volume may be near zero.

Use this data in your analysis. """

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            messages=[
                {
                    "role": "user",
                    "content": f"{prefix}Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?{trends_section}{voteschema.schema_instruction(coin_symbol)}"
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")

    def send_integrated_coin_check(self, coin_symbol, peer_analysis, market_block=None):
        """Round 2: Check coin with peer LLM analysis as additional context.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        prefix = f"{market_block}\n\n" if market_block else ""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            messages=[
                {
                    "role": "user",
                    "content": f"""{prefix}Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

{voteschema.schema_instruction(coin_symbol)}"""
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None, market_block=None):
        """Round 2: Check coin with Google Trends + peer LLM analysis.

        T9: market_block prepended as the PRIMARY data section when present."""
        if coin_symbol is None:
            return None
        prefix = f"{market_block}\n\n" if market_block else ""

        # Build trends section if data is available
        trends_section = ""
        if trends_data:
            trends_section = f"""
Here is the actual Google Trends data we collected:

---BEGIN GOOGLE TRENDS DATA---
{trends_data}
---END GOOGLE TRENDS DATA---

Note: values are scaled so the window maximum = 100; on low-volume tickers a single stray minute can appear as a spike to 100. Absolute search volume may be near zero.

"""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config=_claude_output_config(),
            messages=[
                {
                    "role": "user",
                    "content": f"""{prefix}Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?
{trends_section}
Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis and the Google Trends data provided, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

{voteschema.schema_instruction(coin_symbol)}"""
                }
            ]
        )
        return next((b.text for b in message.content if b.type == "text"), "")


def compare_recommendations(gemini_rec, claude_rec):
    """Compare recommendations from Gemini and Claude.
    
    Args:
        gemini_rec (str): Recommendation from Gemini (BUY, SELL, or HOLD)
        claude_rec (str): Recommendation from Claude (BUY, SELL, or HOLD)
    
    Returns:
        dict: Comparison result with agreement status and recommendations
    """
    if gemini_rec is None or claude_rec is None:
        return {
            "agree": False,
            "gemini": gemini_rec,
            "claude": claude_rec,
            "confidence": "LOW",
            "reason": "One or both LLMs failed to provide a recommendation"
        }
    
    gemini_normalized = gemini_rec.upper().strip()
    claude_normalized = claude_rec.upper().strip()
    
    agree = gemini_normalized == claude_normalized
    
    return {
        "agree": agree,
        "gemini": gemini_normalized,
        "claude": claude_normalized,
        "confidence": "HIGH" if agree else "LOW",
        "consensus": gemini_normalized if agree else None
    }


def get_consensus_action(comparison_result, require_consensus=True):
    """Determine trading action based on LLM comparison.
    
    Args:
        comparison_result (dict): Result from compare_recommendations()
        require_consensus (bool): If True, only act when both LLMs agree
    
    Returns:
        str or None: Action to take (BUY, SELL, HOLD) or None if no action
    """
    if require_consensus:
        if comparison_result["agree"]:
            return comparison_result["consensus"]
        else:
            print(f"  [DISAGREE] Gemini: {comparison_result['gemini']}, Claude: {comparison_result['claude']} - No action taken")
            return None
    else:
        # Default to Gemini if no consensus required
        return comparison_result["gemini"]
