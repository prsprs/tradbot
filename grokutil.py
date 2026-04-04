import openai
import os

class GrokTrader:
    def __init__(self):
        """Initialize the Grok client with API credentials from environment."""
        api_key = os.environ.get('XAI_API_KEY')
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set")
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )
        self.model = "grok-4"
        # Web search requires Responses API with web_search tool
        self.tools = [{"type": "web_search"}]
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
    
    def _call_responses_api(self, content):
        """Call the xAI Responses API with web search enabled."""
        response = self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": content}],
            tools=self.tools
        )
        # Extract text from response
        if hasattr(response, 'output_text'):
            return response.output_text
        elif hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'content'):
                    return item.content
        return str(response)
    
    def send_recommendation_request(self):
        """Get cryptocurrency meme coin recommendations from Grok."""
        return self._call_responses_api(
            "Using real-time web search for current market data and sentiment, what 3 cryptocurrency meme coins listed on the coinbase exchange would a sophisticated trading bot designed for short-term appreciation recommend buying right now? Once you have the top choices, number them and show me which of the coins chosen show the most positive social media trends in the last 4 hours. Put 3 plus signs around these choices at the end of your response."
        )
    
    def send_coin_check_request(self, coin_symbol):
        """Check if a specific coin should be bought, sold, or held."""
        if coin_symbol is None:
            return None
        return self._call_responses_api(
            f"Using real-time web search for current market data and sentiment, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
        )
    
    def send_trend_check_request(self, coin_symbol):
        """Check coin recommendation based on Google Trends analysis."""
        if coin_symbol is None:
            return None
        return self._call_responses_api(
            f"Using real-time web search combined with Google Trends analysis, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
        )

    def send_integrated_coin_check(self, coin_symbol, peer_analysis):
        """Round 2: Check coin with peer LLM analysis as additional context."""
        if coin_symbol is None:
            return None
        return self._call_responses_api(
            f"""Using real-time web search for current market data and sentiment, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
        )

    def send_integrated_trend_check(self, coin_symbol, peer_analysis):
        """Round 2: Check coin with Google Trends + peer LLM analysis."""
        if coin_symbol is None:
            return None
        return self._call_responses_api(
            f"""Using real-time web search combined with Google Trends analysis, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
        )
