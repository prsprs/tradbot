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
    
    def send_recommendation_request(self, dex_mode: bool = False):
        """Get cryptocurrency recommendations from Grok."""
        if dex_mode:
            prompt = "Using real-time web search for current market data and sentiment, what 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you find."
        else:
            prompt = "Using real-time web search for current market data and sentiment, what 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you find."
        
        return self._call_responses_api(prompt)
    
    def send_coin_check_request(self, coin_symbol):
        """Check if a specific coin should be bought, sold, or held."""
        if coin_symbol is None:
            return None
        return self._call_responses_api(
            f"Using real-time web search for current market data and sentiment, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
        )
    
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

Use this data in your analysis."""
        
        return self._call_responses_api(
            f"Using real-time web search combined with Google Trends analysis, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?{trends_section} Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
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
        
        return self._call_responses_api(
            f"""Using real-time web search combined with Google Trends analysis, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now?
{trends_section}
Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis and the Google Trends data provided, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
        )
