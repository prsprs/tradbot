import anthropic
import os

class ClaudeTrader:
    def __init__(self):
        """Initialize the Anthropic Claude client with API credentials from environment."""
        api_key = os.environ.get('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError("CLAUDE_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
    
    def send_recommendation_request(self):
        """Get cryptocurrency recommendations from Claude."""
        prompt = "What 3 cryptocurrency meme coins listed on the coinbase exchange would a sophisticated trading bot designed for short-term appreciation recommend buying right now? Once you have the top choices, number them and show me which of the coins chosen show the most positive social media trends in the last 4 hours. Put 3 plus signs around EACH choice separately at the end of your response. If for any reason you cannot recommend any coins, include ***FAILED*** at the end of your output. Do not include hypothetical results."
        
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
        return message.content[0].text
    
    def send_coin_check_request(self, coin_symbol):
        """Check if a specific coin should be bought, sold, or held."""
        if coin_symbol is None:
            return None
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
                }
            ]
        )
        return message.content[0].text
    
    def send_trend_check_request(self, coin_symbol, trends_data=None):
        """Check coin recommendation based on Google Trends analysis."""
        if coin_symbol is None:
            return None
        
        # Build trends section if data is available
        trends_section = ""
        if trends_data:
            trends_section = f"""

Here is the actual Google Trends data we collected:

---BEGIN GOOGLE TRENDS DATA---
{trends_data}
---END GOOGLE TRENDS DATA---

Use this data in your analysis. """
        
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?{trends_section}Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
                }
            ]
        )
        return message.content[0].text

    def send_integrated_coin_check(self, coin_symbol, peer_analysis):
        """Round 2: Check coin with peer LLM analysis as additional context."""
        if coin_symbol is None:
            return None
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"""Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the meme coin with symbol {coin_symbol} right now?

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
                }
            ]
        )
        return message.content[0].text

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None):
        """Round 2: Check coin with Google Trends + peer LLM analysis."""
        if coin_symbol is None:
            return None
        
        # Build trends section if data is available
        trends_section = ""
        if trends_data:
            trends_section = f"""
Here is the actual Google Trends data we collected:

---BEGIN GOOGLE TRENDS DATA---
{trends_data}
---END GOOGLE TRENDS DATA---

"""
        
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"""Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the meme coin with symbol {coin_symbol} right now?
{trends_section}
Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis and the Google Trends data provided, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
                }
            ]
        )
        return message.content[0].text


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
