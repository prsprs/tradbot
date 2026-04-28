import openai
import os

class PerplexityTrader:
    def __init__(self):
        """Initialize the Perplexity client with API credentials from environment."""
        api_key = os.environ.get('PERPLEXITY_API_KEY')
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable not set")
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        self.model = "sonar-pro"
        # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
        analyze_coins = os.environ.get('ANALYZE_COINS', '').strip()
        self.coin_type = "cryptocurrency" if analyze_coins else "meme coin"
    
    def send_recommendation_request(self, dex_mode: bool = False):
        """Get cryptocurrency recommendations from Perplexity with live web search."""
        if dex_mode:
            prompt = "What 3 cryptocurrency meme coins on the SOLANA blockchain would a sophisticated trading bot designed for short-term appreciation recommend buying right now? Only recommend coins that are tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT recommend coins on other chains like Base, Ethereum, or BNB. Once you have the top choices, number them and show me which of the coins chosen show the most positive social media trends in the last 4 hours. Put 3 plus signs around EACH choice separately at the end of your response. If for any reason you cannot recommend any coins, include ***FAILED*** at the end of your output. Do not include hypothetical results."
        else:
            prompt = "What 3 cryptocurrency meme coins listed on the coinbase exchange would a sophisticated trading bot designed for short-term appreciation recommend buying right now? Once you have the top choices, number them and show me which of the coins chosen show the most positive social media trends in the last 4 hours. Put 3 plus signs around EACH choice separately at the end of your response. If for any reason you cannot recommend any coins, include ***FAILED*** at the end of your output. Do not include hypothetical results."
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        return response.choices[0].message.content
    
    def send_coin_check_request(self, coin_symbol):
        """Check if a specific coin should be bought, sold, or held using live web data."""
        if coin_symbol is None:
            return None
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Use current market data and recent news. Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
                }
            ]
        )
        return response.choices[0].message.content
    
    def send_trend_check_request(self, coin_symbol, trends_data=None):
        """Check coin recommendation based on live trend analysis."""
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
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"Based on analysis of recent social media trends and Google Trends data, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Use live data.{trends_section}Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"
                }
            ]
        )
        return response.choices[0].message.content

    def send_integrated_coin_check(self, coin_symbol, peer_analysis):
        """Round 2: Check coin with peer LLM analysis as additional context."""
        if coin_symbol is None:
            return None
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"""Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Use current market data.

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
                }
            ]
        )
        return response.choices[0].message.content

    def send_integrated_trend_check(self, coin_symbol, peer_analysis, trends_data=None):
        """Round 2: Check coin with live trends + peer LLM analysis."""
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
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"""Based on analysis of recent social media and search trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {self.coin_type} with symbol {coin_symbol} right now? Use live data.
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
        return response.choices[0].message.content
