from google import genai

from google.genai import types

import argparse
import datetime
import json
import os
import sys

from coinbase.rest import RESTClient

from coinbaseutil2 import BlobbyTrader 

from claudeutil import ClaudeTrader, compare_recommendations, get_consensus_action

from openaiutil import OpenAITrader

from grokutil import GrokTrader

from perplexityutil import PerplexityTrader

from historyutil import record_recommendation

from lunarcrushutil import filter_coinbase_coins as lunarcrush_filter

from polymarketutil import filter_coins_by_polymarket

from pytrends.request import TrendReq

import pandas as pd


def parse_args():
    """Parse command-line arguments with environment variable fallbacks."""
    parser = argparse.ArgumentParser(
        description='Trading Bot - Cryptocurrency recommendation engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python geminigroundlin15.py --llm-mode=compare --coins=PEPE,BONK
  python geminigroundlin15.py --trading-mode=whatif --llm-mode=integrate
  
Environment variables can also be used (CLI takes precedence):
  TRADING_MODE, LLM_MODE, PRIMARY_LLM, COMPARE_LLMS, ANALYZE_COINS, etc.
"""
    )
    
    # Trading mode
    parser.add_argument(
        '--trading-mode',
        choices=['live', 'whatif'],
        default=os.environ.get('TRADING_MODE', 'live').lower(),
        help='Trading mode: live executes trades, whatif simulates (default: live)'
    )
    
    # LLM mode
    parser.add_argument(
        '--llm-mode',
        choices=['gemini', 'claude', 'openai', 'grok', 'perplexity', 'compare', 'integrate'],
        default=os.environ.get('LLM_MODE', 'compare').lower(),
        help='LLM mode for recommendations (default: compare)'
    )
    
    # Primary LLM
    parser.add_argument(
        '--primary-llm',
        choices=['gemini', 'claude', 'openai', 'grok', 'perplexity'],
        default=os.environ.get('PRIMARY_LLM', 'gemini').lower(),
        help='Primary LLM for discovery (default: gemini)'
    )
    
    # Compare LLMs
    parser.add_argument(
        '--compare-llms',
        default=os.environ.get('COMPARE_LLMS', 'gemini,claude').lower(),
        help='Comma-separated LLMs for compare/integrate mode (default: gemini,claude)'
    )
    
    # Coins to analyze
    parser.add_argument(
        '--coins',
        default=os.environ.get('ANALYZE_COINS', ''),
        help='Comma-separated coins to analyze (max 5), or empty for discovery mode'
    )
    
    # Chain filter (LunarCrush)
    parser.add_argument(
        '--chains',
        default=os.environ.get('CHAINS', ''),
        help='Comma-separated blockchain filter (e.g., solana,base). Requires LUNARCRUSH_API_KEY'
    )
    
    # Category filter (LunarCrush)
    parser.add_argument(
        '--categories',
        default=os.environ.get('CATEGORIES', ''),
        help='Comma-separated category filter (e.g., meme-coins,defi). Requires LUNARCRUSH_API_KEY'
    )
    
    # Polymarket filter
    parser.add_argument(
        '--polymarket-filter',
        choices=['true', 'false'],
        default=os.environ.get('POLYMARKET_FILTER', 'false').lower(),
        help='Only analyze coins with active Polymarket prediction markets (default: false)'
    )
    
    # Require consensus
    parser.add_argument(
        '--require-consensus',
        choices=['true', 'false'],
        default=os.environ.get('REQUIRE_CONSENSUS', 'true').lower(),
        help='Require LLM consensus for action (default: true)'
    )
    
    # Tiebreaker
    parser.add_argument(
        '--tiebreaker',
        choices=['gemini', 'claude', 'openai', 'grok', 'perplexity', 'none'],
        default=os.environ.get('INTEGRATION_TIEBREAKER', 'gemini').lower(),
        help='Tiebreaker LLM when no consensus (default: gemini)'
    )
    
    # Log integration rounds
    parser.add_argument(
        '--log-rounds',
        choices=['true', 'false'],
        default=os.environ.get('LOG_INTEGRATION_ROUNDS', 'true').lower(),
        help='Log integration round details (default: true)'
    )
    
    return parser.parse_args()


def get_config_source(arg_name, env_name):
    """Determine the source of a configuration value."""
    for arg in sys.argv:
        if arg.startswith(arg_name):
            return f"{arg_name}"
    if os.environ.get(env_name):
        return f"{env_name} env"
    return "default"


# Parse command-line arguments
args = parse_args()





# Initialize pytrends with desired language and timezone

# hl='en-US' for English (US), tz=360 for GMT-6 (Central Time)

pytrends = TrendReq(hl='en-US', tz=360)

def googleTrendsRequest(keyword):
    """Fetches Google Trends data for a given keyword. Returns the data as a string for LLM context."""
    try:
        pytrends.build_payload([keyword], cat=0, timeframe='now 4-H', geo='', gprop='')
        interest_over_time_df = pytrends.interest_over_time()
        if not interest_over_time_df.empty:
            print(f"Google Trends data for {keyword}:")
            print(interest_over_time_df)
            # Return summary for LLM context
            recent_values = interest_over_time_df[keyword].tail(10).tolist()
            avg_interest = interest_over_time_df[keyword].mean()
            max_interest = interest_over_time_df[keyword].max()
            min_interest = interest_over_time_df[keyword].min()
            trend_summary = f"Google Trends data for {keyword} (last 4 hours):\n"
            trend_summary += f"- Average interest: {avg_interest:.1f}\n"
            trend_summary += f"- Max interest: {max_interest}\n"
            trend_summary += f"- Min interest: {min_interest}\n"
            trend_summary += f"- Recent 10 values: {recent_values}\n"
            trend_summary += f"- Total data points: {len(interest_over_time_df)}"
            return trend_summary
        else:
            print(f"No Google Trends data found for {keyword}")
            return None
    except Exception as e:
        print(f"Error fetching Google Trends data for {keyword}: {e}")
        return None

coinsToBuy = []

coinsToSell = []

coinsToHold = []

# Configuration from CLI args (with env var fallback)
TRADING_MODE = args.trading_mode
WHATIF_MODE = TRADING_MODE == 'whatif'
LLM_MODE = args.llm_mode
PRIMARY_LLM = args.primary_llm
COMPARE_LLMS = [llm.strip() for llm in args.compare_llms.split(',')]
REQUIRE_CONSENSUS = args.require_consensus == 'true'
INTEGRATION_TIEBREAKER = args.tiebreaker
LOG_INTEGRATION_ROUNDS = args.log_rounds == 'true'

# Coin choice: specify coins directly instead of LLM discovery (max 5)
ANALYZE_COINS_RAW = args.coins.strip()
ANALYZE_COINS = [c.strip().upper() for c in ANALYZE_COINS_RAW.split(',') if c.strip()][:5]
USE_COIN_DISCOVERY = len(ANALYZE_COINS) == 0
if len([c.strip() for c in ANALYZE_COINS_RAW.split(',') if c.strip()]) > 5:
    print(f"Warning: --coins limited to 5 coins, ignoring extras")

# Chain and category filters (LunarCrush)
CHAINS_RAW = args.chains.strip()
CHAINS = [c.strip().lower() for c in CHAINS_RAW.split(',') if c.strip()]
CATEGORIES_RAW = args.categories.strip()
CATEGORIES = [c.strip().lower() for c in CATEGORIES_RAW.split(',') if c.strip()]
POLYMARKET_FILTER = args.polymarket_filter == 'true'

# Check if filtering is requested
USE_COIN_FILTERING = len(CHAINS) > 0 or len(CATEGORIES) > 0 or POLYMARKET_FILTER

def is_valid_coin_symbol(text):
    """Check if text looks like a valid coin symbol."""
    if not text:
        return False
    text = text.strip()
    # Valid symbols are 2-10 alphanumeric characters
    if len(text) < 2 or len(text) > 10:
        return False
    # Must be alphanumeric only
    if not text.replace('-', '').isalnum():
        return False
    return True


def sendRecommendationRequest():
    """Get coin recommendations from Gemini."""
    prompt = "What 3 cryptocurrency meme coins listed on the coinbase exchange would a sophisticated trading bot designed for short-term appreciation recommend buying right now?  Once you have the top choices, number them and show me which of the coins chosen show the most positive social media trends in the last 4 hours. Put 3 plus signs around EACH choice separately at the end of your response. If for any reason you cannot recommend any coins, include ***FAILED*** at the end of your output. Do not include hypothetical results."
    
    try:
        response = client.models.generate_content(
            model="models/gemini-2.5-pro",
            contents=prompt,
            config=config,
        )
        return response
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendRecommendationRequest: {e}")
        return None



def sendCoinCheckRequest(coin):
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    
    try:
        followUpResponse = client.models.generate_content(
            model="models/gemini-2.5-pro",
            contents=f'Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin} right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket',
            config=config,
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendCoinCheckRequest for {coin}: {e}")
        return None





def sendTrendCheckRequest(coin, trends_data=None):
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    
    # Build trends section if data is available
    trends_section = ""
    if trends_data:
        trends_section = f"""

Here is the actual Google Trends data we collected:

---BEGIN GOOGLE TRENDS DATA---
{trends_data}
---END GOOGLE TRENDS DATA---

Use this data in your analysis. """
    
    try:
        followUpResponse = client.models.generate_content(
            model="models/gemini-2.5-pro",
            contents=f'Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin} right now?{trends_section}Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket',
            config=config,
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendTrendCheckRequest for {coin}: {e}")
        return None


def sendIntegratedCoinCheckRequest(coin_symbol, peer_analysis):
    """Round 2: Check coin with peer LLM analysis as additional context."""
    if coin_symbol is None:
        return None
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    prompt = f"""Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin_symbol} right now?

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
    
    try:
        followUpResponse = client.models.generate_content(
            model="models/gemini-2.5-pro",
            contents=prompt,
            config=config,
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendIntegratedCoinCheckRequest for {coin_symbol}: {e}")
        return None


def sendIntegratedTrendCheckRequest(coin_symbol, peer_analysis, trends_data=None):
    """Round 2: Check coin with Google Trends + peer LLM analysis."""
    if coin_symbol is None:
        return None
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    
    # Build trends section if data is available
    trends_section = ""
    if trends_data:
        trends_section = f"""
Here is the actual Google Trends data we collected:

---BEGIN GOOGLE TRENDS DATA---
{trends_data}
---END GOOGLE TRENDS DATA---

"""
    
    prompt = f"""Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin_symbol} right now?
{trends_section}
Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis and the Google Trends data provided, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, followed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket"""
    
    try:
        followUpResponse = client.models.generate_content(
            model="models/gemini-2.5-pro",
            contents=prompt,
            config=config,
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendIntegratedTrendCheckRequest for {coin_symbol}: {e}")
        return None


def get_primary_recommendation():
    """Get coin recommendations from the PRIMARY_LLM."""
    global claude_trader, openai_trader, grok_trader, perplexity_trader
    
    if PRIMARY_LLM == 'gemini':
        response = sendRecommendationRequest()
        return response.text if response else None
    elif PRIMARY_LLM == 'claude' and claude_trader:
        return claude_trader.send_recommendation_request()
    elif PRIMARY_LLM == 'openai' and openai_trader:
        return openai_trader.send_recommendation_request()
    elif PRIMARY_LLM == 'grok' and grok_trader:
        return grok_trader.send_recommendation_request()
    elif PRIMARY_LLM == 'perplexity' and perplexity_trader:
        return perplexity_trader.send_recommendation_request()
    else:
        print(f"Warning: PRIMARY_LLM '{PRIMARY_LLM}' not available, falling back to Gemini")
        response = sendRecommendationRequest()
        return response.text if response else None


def get_primary_trend_check(coin_symbol, trends_data=None):
    """Get trend check from the PRIMARY_LLM."""
    global claude_trader, openai_trader, grok_trader, perplexity_trader
    
    if PRIMARY_LLM == 'gemini':
        response = sendTrendCheckRequest(coin_symbol, trends_data)
        return response.text if response else None
    elif PRIMARY_LLM == 'claude' and claude_trader:
        return claude_trader.send_trend_check_request(coin_symbol, trends_data)
    elif PRIMARY_LLM == 'openai' and openai_trader:
        return openai_trader.send_trend_check_request(coin_symbol, trends_data)
    elif PRIMARY_LLM == 'grok' and grok_trader:
        return grok_trader.send_trend_check_request(coin_symbol, trends_data)
    elif PRIMARY_LLM == 'perplexity' and perplexity_trader:
        return perplexity_trader.send_trend_check_request(coin_symbol, trends_data)
    else:
        print(f"Warning: PRIMARY_LLM '{PRIMARY_LLM}' not available, falling back to Gemini")
        response = sendTrendCheckRequest(coin_symbol, trends_data)
        return response.text if response else None


def get_primary_coin_check(coin_symbol):
    """Get coin check from the PRIMARY_LLM."""
    global claude_trader, openai_trader, grok_trader, perplexity_trader
    
    if PRIMARY_LLM == 'gemini':
        response = sendCoinCheckRequest(coin_symbol)
        return response.text if response else None
    elif PRIMARY_LLM == 'claude' and claude_trader:
        return claude_trader.send_coin_check_request(coin_symbol)
    elif PRIMARY_LLM == 'openai' and openai_trader:
        return openai_trader.send_coin_check_request(coin_symbol)
    elif PRIMARY_LLM == 'grok' and grok_trader:
        return grok_trader.send_coin_check_request(coin_symbol)
    elif PRIMARY_LLM == 'perplexity' and perplexity_trader:
        return perplexity_trader.send_coin_check_request(coin_symbol)
    else:
        print(f"Warning: PRIMARY_LLM '{PRIMARY_LLM}' not available, falling back to Gemini")
        response = sendCoinCheckRequest(coin_symbol)
        return response.text if response else None


def get_text_between_strings(main_string, start_string, end_string):

    """Extracts the text between two specified strings in a given main string.



    Args:

        main_string (str): The string to search within.

        start_string (str): The string marking the beginning of the desired text.

        end_string (str): The string marking the end of the desired text.



    Returns:

        str or None: The extracted text, or None if the start or end string is not found.

    """

    start_index = main_string.find(start_string)

    if start_index == -1:

        return None  # Start string not found



    # Adjust start_index to point after the start_string

    start_of_content = start_index + len(start_string)



    end_index = main_string.find(end_string, start_of_content)

    if end_index == -1:

        return None  # End string not found after the start string



    return main_string[start_of_content:end_index]



def get_text_after_delimiter(text_string, delimiter):

    """

    Extracts all text after the first occurrence of a specified delimiter.



    Args:

        text_string (str): The input string.

        delimiter (str): The delimiter to split the string by.



    Returns:

        str: The text after the delimiter, or an empty string if the delimiter

             is not found or if there's no text after it.

    """

    parts = text_string.split(delimiter, 1)  # Split only at the first occurrence

    if len(parts) > 1:

        return parts[1]

    else:

        return ""

def get_llm_response(llm_name, coin_symbol, use_trend_check, peer_analysis=None, trends_data=None):
    """Get response from specified LLM.
    
    Args:
        llm_name: 'gemini', 'claude', or 'openai'
        coin_symbol: The coin symbol to analyze
        use_trend_check: If True, use trend check; otherwise use coin check
        peer_analysis: Optional peer analysis for integration mode Round 2
        trends_data: Optional Google Trends data to include in prompt (integrate mode only)
    
    Returns:
        tuple: (response_text, parsed_recommendation)
    """
    response_text = None
    
    try:
        if llm_name == 'claude' and claude_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = claude_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trends_data)
                else:
                    response_text = claude_trader.send_integrated_coin_check(coin_symbol, peer_analysis)
            else:
                if use_trend_check:
                    response_text = claude_trader.send_trend_check_request(coin_symbol, trends_data)
                else:
                    response_text = claude_trader.send_coin_check_request(coin_symbol)
                    
        elif llm_name == 'openai' and openai_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = openai_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trends_data)
                else:
                    response_text = openai_trader.send_integrated_coin_check(coin_symbol, peer_analysis)
            else:
                if use_trend_check:
                    response_text = openai_trader.send_trend_check_request(coin_symbol, trends_data)
                else:
                    response_text = openai_trader.send_coin_check_request(coin_symbol)
                    
        elif llm_name == 'grok' and grok_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = grok_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trends_data)
                else:
                    response_text = grok_trader.send_integrated_coin_check(coin_symbol, peer_analysis)
            else:
                if use_trend_check:
                    response_text = grok_trader.send_trend_check_request(coin_symbol, trends_data)
                else:
                    response_text = grok_trader.send_coin_check_request(coin_symbol)
                    
        elif llm_name == 'perplexity' and perplexity_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = perplexity_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trends_data)
                else:
                    response_text = perplexity_trader.send_integrated_coin_check(coin_symbol, peer_analysis)
            else:
                if use_trend_check:
                    response_text = perplexity_trader.send_trend_check_request(coin_symbol, trends_data)
                else:
                    response_text = perplexity_trader.send_coin_check_request(coin_symbol)
                    
        elif llm_name == 'gemini':
            if peer_analysis:
                if use_trend_check:
                    resp = sendIntegratedTrendCheckRequest(coin_symbol, peer_analysis, trends_data)
                else:
                    resp = sendIntegratedCoinCheckRequest(coin_symbol, peer_analysis)
                response_text = resp.text if resp else None
            else:
                if use_trend_check:
                    resp = sendTrendCheckRequest(coin_symbol, trends_data)
                else:
                    resp = sendCoinCheckRequest(coin_symbol)
                response_text = resp.text if resp else None
    except Exception as e:
        print(f"Error getting {llm_name} response: {e}")
        return None, None
    
    rec = get_text_between_strings(response_text, "-PRS-", "**>") if response_text else None
    return response_text, rec


def process_coin_with_comparison(coin_symbol, primary_response_text, use_trend_check=False, trends_data=None):
    """Process a coin recommendation with optional LLM comparison or integration.
    
    Args:
        coin_symbol: The coin symbol to analyze
        primary_response_text: The full response text from PRIMARY_LLM Round 1
        use_trend_check: If True, use trend check; otherwise use coin check
        trends_data: Optional Google Trends data to include in integrate mode prompts
    
    Returns:
        tuple: (action, consensus) where:
            - action: str or None - The final action to take (BUY/SELL/HOLD or None)
            - consensus: bool or None - True if all LLMs agreed, False if tiebreaker used, None for single LLM
    """
    if coin_symbol is None:
        return None, None
    
    # Parse PRIMARY_LLM's Round 1 recommendation
    primary_rec = get_text_between_strings(primary_response_text, "-PRS-", "**>") if primary_response_text else None
    
    # Single LLM modes - use the single LLM exclusively (consensus=None for single LLM)
    if LLM_MODE == 'gemini':
        if PRIMARY_LLM == 'gemini':
            return primary_rec, None
        _, rec = get_llm_response('gemini', coin_symbol, use_trend_check)
        return rec, None
    
    if LLM_MODE == 'claude':
        if PRIMARY_LLM == 'claude':
            return primary_rec, None
        _, rec = get_llm_response('claude', coin_symbol, use_trend_check)
        return rec, None
    
    if LLM_MODE == 'openai':
        if PRIMARY_LLM == 'openai':
            return primary_rec, None
        _, rec = get_llm_response('openai', coin_symbol, use_trend_check)
        return rec, None
    
    if LLM_MODE == 'grok':
        if PRIMARY_LLM == 'grok':
            return primary_rec, None
        _, rec = get_llm_response('grok', coin_symbol, use_trend_check)
        return rec, None
    
    if LLM_MODE == 'perplexity':
        if PRIMARY_LLM == 'perplexity':
            return primary_rec, None
        _, rec = get_llm_response('perplexity', coin_symbol, use_trend_check)
        return rec, None
    
    # === COMPARE/INTEGRATE MODES: Multi-LLM ===
    try:
        # Collect Round 1 responses from all configured LLMs
        r1_responses = {}
        r1_recs = {}
        
        # PRIMARY_LLM already has a response, add it if in COMPARE_LLMS
        if PRIMARY_LLM in COMPARE_LLMS:
            r1_responses[PRIMARY_LLM] = primary_response_text
            r1_recs[PRIMARY_LLM] = primary_rec
        
        # Query other LLMs in COMPARE_LLMS (skip PRIMARY_LLM since we already have it)
        # Pass trends_data to Round 1 so all LLMs have the same data to work with
        if 'gemini' in COMPARE_LLMS and PRIMARY_LLM != 'gemini':
            resp, rec = get_llm_response('gemini', coin_symbol, use_trend_check, None, trends_data)
            if resp:
                r1_responses['gemini'] = resp
                r1_recs['gemini'] = rec
                if LOG_INTEGRATION_ROUNDS:
                    print(f"\n--- Gemini Round 1 Response for {coin_symbol} ---")
                    print(resp)
        
        if 'claude' in COMPARE_LLMS and PRIMARY_LLM != 'claude' and claude_trader:
            resp, rec = get_llm_response('claude', coin_symbol, use_trend_check, None, trends_data)
            if resp:
                r1_responses['claude'] = resp
                r1_recs['claude'] = rec
                if LOG_INTEGRATION_ROUNDS:
                    print(f"\n--- Claude Round 1 Response for {coin_symbol} ---")
                    print(resp)
        
        if 'openai' in COMPARE_LLMS and PRIMARY_LLM != 'openai' and openai_trader:
            resp, rec = get_llm_response('openai', coin_symbol, use_trend_check, None, trends_data)
            if resp:
                r1_responses['openai'] = resp
                r1_recs['openai'] = rec
                if LOG_INTEGRATION_ROUNDS:
                    print(f"\n--- OpenAI Round 1 Response for {coin_symbol} ---")
                    print(resp)
        
        if 'grok' in COMPARE_LLMS and PRIMARY_LLM != 'grok' and grok_trader:
            resp, rec = get_llm_response('grok', coin_symbol, use_trend_check, None, trends_data)
            if resp:
                r1_responses['grok'] = resp
                r1_recs['grok'] = rec
                if LOG_INTEGRATION_ROUNDS:
                    print(f"\n--- Grok Round 1 Response for {coin_symbol} ---")
                    print(resp)
        
        if 'perplexity' in COMPARE_LLMS and PRIMARY_LLM != 'perplexity' and perplexity_trader:
            resp, rec = get_llm_response('perplexity', coin_symbol, use_trend_check, None, trends_data)
            if resp:
                r1_responses['perplexity'] = resp
                r1_recs['perplexity'] = rec
                if LOG_INTEGRATION_ROUNDS:
                    print(f"\n--- Perplexity Round 1 Response for {coin_symbol} ---")
                    print(resp)
        
        if len(r1_recs) < 2:
            print(f"Only {len(r1_recs)} LLM(s) responded, using first available")
            return (list(r1_recs.values())[0] if r1_recs else primary_rec), None
        
        # === COMPARE MODE ===
        if LLM_MODE == 'compare':
            llm_names = list(r1_recs.keys())
            recs_list = list(r1_recs.values())
            
            # Check if all agree
            all_agree = len(set(r.upper().strip() if r else '' for r in recs_list)) == 1
            
            print(f"\n[COMPARISON] " + ", ".join(f"{k}: {v}" for k, v in r1_recs.items()) + f", Agree: {all_agree}")
            
            if all_agree:
                return recs_list[0], True  # All LLMs agreed
            elif REQUIRE_CONSENSUS:
                print("  [DISAGREE] No consensus - no action taken")
                return None, False  # No consensus, no action
            else:
                # Use tiebreaker or first LLM
                if INTEGRATION_TIEBREAKER in r1_recs:
                    return r1_recs[INTEGRATION_TIEBREAKER], False  # Tiebreaker used
                return recs_list[0], False  # First LLM used as fallback
        
        # === INTEGRATE MODE: Round 2 cross-feeding ===
        if LLM_MODE == 'integrate':
            print(f"\n[INTEGRATE] Round 1 - " + ", ".join(f"{k}: {v}" for k, v in r1_recs.items()))
            
            # Combine all peer analyses for Round 2
            r2_recs = {}
            
            for llm in r1_recs.keys():
                # Build peer analysis from other LLMs
                peer_analyses = []
                for other_llm, other_resp in r1_responses.items():
                    if other_llm != llm:
                        peer_analyses.append(f"[{other_llm.upper()}]: {other_resp}")
                combined_peer = "\n\n".join(peer_analyses)
                
                resp, rec = get_llm_response(llm, coin_symbol, use_trend_check, combined_peer, trends_data)
                r2_recs[llm] = rec
                
                if LOG_INTEGRATION_ROUNDS:
                    print(f"\n--- {llm.capitalize()} Round 2 Response for {coin_symbol} ---")
                    print(resp)
                
                # Track flips
                if r1_recs[llm] != rec:
                    print(f"  [FLIP] {llm.capitalize()} changed: {r1_recs[llm]} -> {rec}")
            
            print(f"\n[INTEGRATE] Round 2 - " + ", ".join(f"{k}: {v}" for k, v in r2_recs.items()))
            
            # Check if all agree after Round 2
            recs_list = list(r2_recs.values())
            all_agree = len(set(r.upper().strip() if r else '' for r in recs_list)) == 1
            
            print(f"\n[INTEGRATE FINAL] " + ", ".join(f"{k}: {v}" for k, v in r2_recs.items()) + f", Agree: {all_agree}")
            
            if all_agree:
                return recs_list[0], True  # All LLMs agreed after Round 2
            else:
                if INTEGRATION_TIEBREAKER in r2_recs:
                    print(f"  [TIEBREAKER] Using {INTEGRATION_TIEBREAKER} recommendation: {r2_recs[INTEGRATION_TIEBREAKER]}")
                    return r2_recs[INTEGRATION_TIEBREAKER], False  # Tiebreaker used
                elif INTEGRATION_TIEBREAKER == 'none':
                    print("  [TIEBREAKER] No tiebreaker set, no action taken")
                    return None, False  # No consensus, no action
                else:
                    return recs_list[0], False  # First LLM used as fallback
        
    except Exception as e:
        print(f"Error in LLM processing for {coin_symbol}: {e}")
        print(f"Falling back to {PRIMARY_LLM} recommendation only")
        return primary_rec, None  # Fallback, no consensus info
    
    return primary_rec, None  # Default fallback

def buy_something(coinToBuy):

        print("\n--- Getting coin Product Details BEFORE for: ",(coinToBuy+"-USD") )

        usd_product = trader.get_product_details(coinToBuy+"-USD")

        if usd_product:

                print(json.dumps(usd_product.to_dict(), indent=2))



        else:

            print("Could not retrieve  product details.")

        trader.market_order_buy(coinToBuy+'-USD', '25.00')



        print("\n--- Getting coin Product Details AFTER for: ",(coinToBuy+"-USD") )

        usd_product = trader.get_product_details(coinToBuy+"-USD")

        if usd_product:

                print(json.dumps(usd_product.to_dict(), indent=2))



        else:

            print("Could not retrieve  product details.")

# Configure the Gemini client
client = genai.Client()

# Initialize Claude client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
claude_trader = None
if LLM_MODE == 'claude' or PRIMARY_LLM == 'claude' or (LLM_MODE in ['compare', 'integrate'] and 'claude' in COMPARE_LLMS):
    try:
        claude_trader = ClaudeTrader()
        print(f"Claude client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
    except Exception as e:
        print(f"Warning: Could not initialize Claude client: {e}")
        if LLM_MODE == 'claude' or PRIMARY_LLM == 'claude':
            raise
        COMPARE_LLMS = [llm for llm in COMPARE_LLMS if llm != 'claude']

# Initialize OpenAI client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
openai_trader = None
if LLM_MODE == 'openai' or PRIMARY_LLM == 'openai' or (LLM_MODE in ['compare', 'integrate'] and 'openai' in COMPARE_LLMS):
    try:
        openai_trader = OpenAITrader()
        print(f"OpenAI client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
    except Exception as e:
        print(f"Warning: Could not initialize OpenAI client: {e}")
        if LLM_MODE == 'openai' or PRIMARY_LLM == 'openai':
            raise
        COMPARE_LLMS = [llm for llm in COMPARE_LLMS if llm != 'openai']

# Initialize Grok client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
grok_trader = None
if LLM_MODE == 'grok' or PRIMARY_LLM == 'grok' or (LLM_MODE in ['compare', 'integrate'] and 'grok' in COMPARE_LLMS):
    try:
        grok_trader = GrokTrader()
        print(f"Grok client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
    except Exception as e:
        print(f"Warning: Could not initialize Grok client: {e}")
        if LLM_MODE == 'grok' or PRIMARY_LLM == 'grok':
            raise
        COMPARE_LLMS = [llm for llm in COMPARE_LLMS if llm != 'grok']

# Initialize Perplexity client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
perplexity_trader = None
if LLM_MODE == 'perplexity' or PRIMARY_LLM == 'perplexity' or (LLM_MODE in ['compare', 'integrate'] and 'perplexity' in COMPARE_LLMS):
    try:
        perplexity_trader = PerplexityTrader()
        print(f"Perplexity client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
    except Exception as e:
        print(f"Warning: Could not initialize Perplexity client: {e}")
        if LLM_MODE == 'perplexity' or PRIMARY_LLM == 'perplexity':
            raise
        COMPARE_LLMS = [llm for llm in COMPARE_LLMS if llm != 'perplexity']



# Define the grounding tool, gives us realtime searches 

grounding_tool = types.Tool(

    google_search=types.GoogleSearch()

)



# Configure generation settings

config = types.GenerateContentConfig(

    tools=[grounding_tool]

)



# Coinbase credentials are loaded from JSON file (cdp_api_key.json)
# Can be overridden with COINBASE_CREDENTIALS_FILE env var

coinsToExclude = {'TRUMP'}


def apply_coin_filters(coins: list) -> list:
    """Apply chain, category, and Polymarket filters to a list of coins.
    
    Args:
        coins: List of coin symbols to filter
        
    Returns:
        Filtered list of coins matching all specified criteria
    """
    filtered = coins
    
    # Step 1: Apply LunarCrush filters (chains and/or categories)
    if CHAINS or CATEGORIES:
        print(f"\n=== COIN FILTERING ===")
        print(f"Input coins: {len(filtered)}")
        try:
            filtered = lunarcrush_filter(
                filtered,
                chains=CHAINS if CHAINS else None,
                categories=CATEGORIES if CATEGORIES else None
            )
        except (ValueError, RuntimeError) as e:
            print(f"[ERROR] {e}")
            raise
    
    # Step 2: Apply Polymarket filter
    if POLYMARKET_FILTER:
        filtered = filter_coins_by_polymarket(filtered, verbose=True)
    
    if CHAINS or CATEGORIES or POLYMARKET_FILTER:
        print(f"\nFinal filtered coins: {len(filtered)}")
        if filtered:
            print(f"  → {filtered[:20]}{'...' if len(filtered) > 20 else ''}")
        print("=" * 50)
    
    return filtered


def get_filtered_coinbase_coins() -> list:
    """Get all Coinbase coins with optional filtering applied.
    
    Returns:
        List of coin symbols after applying chain/category/Polymarket filters.
    """
    # Get all tradeable coins from Coinbase
    all_coins = trader.list_all_coins()
    print(f"Coinbase tradeable coins: {len(all_coins)}")
    
    if not USE_COIN_FILTERING:
        return all_coins
    
    return apply_coin_filters(all_coins)




# What-if mode tracking
whatif_buys = 0
whatif_sells = 0

trader = BlobbyTrader()

# === STARTUP BANNER ===
print("\n" + "="*50)
print("=== TRADING BOT ===")
print("="*50)

# Show trading mode with source
trading_mode_source = get_config_source('--trading-mode', 'TRADING_MODE')
if WHATIF_MODE:
    print(f"Trading Mode: WHAT-IF (no real trades) [{trading_mode_source}]")
else:
    print(f"Trading Mode: LIVE (trades will execute) [{trading_mode_source}]")

# Show LLM configuration
llm_mode_source = get_config_source('--llm-mode', 'LLM_MODE')
print(f"LLM Mode: {LLM_MODE} [{llm_mode_source}]")

primary_llm_source = get_config_source('--primary-llm', 'PRIMARY_LLM')
print(f"Primary LLM: {PRIMARY_LLM} [{primary_llm_source}]")

if LLM_MODE in ['compare', 'integrate']:
    compare_llms_source = get_config_source('--compare-llms', 'COMPARE_LLMS')
    print(f"Compare LLMs: {COMPARE_LLMS} [{compare_llms_source}]")

coins_source = get_config_source('--coins', 'ANALYZE_COINS')
if USE_COIN_DISCOVERY:
    print(f"Coin Selection: Discovery Mode [{coins_source}]")
else:
    print(f"Coin Selection: {', '.join(ANALYZE_COINS)} [{coins_source}]")

# Show filter settings
if CHAINS:
    chains_source = get_config_source('--chains', 'CHAINS')
    print(f"Chain Filter: {', '.join(CHAINS)} [{chains_source}]")
if CATEGORIES:
    categories_source = get_config_source('--categories', 'CATEGORIES')
    print(f"Category Filter: {', '.join(CATEGORIES)} [{categories_source}]")
if POLYMARKET_FILTER:
    polymarket_source = get_config_source('--polymarket-filter', 'POLYMARKET_FILTER')
    print(f"Polymarket Filter: Enabled [{polymarket_source}]")

consensus_source = get_config_source('--require-consensus', 'REQUIRE_CONSENSUS')
print(f"Require Consensus: {REQUIRE_CONSENSUS} [{consensus_source}]")

if LLM_MODE in ['compare', 'integrate']:
    tiebreaker_source = get_config_source('--tiebreaker', 'INTEGRATION_TIEBREAKER')
    print(f"Tiebreaker: {INTEGRATION_TIEBREAKER} [{tiebreaker_source}]")

print("="*50 + "\n")

# === APPLY COIN FILTERING ===
# If filters are set and no specific coins provided, get filtered Coinbase coins
if USE_COIN_FILTERING and USE_COIN_DISCOVERY:
    print("=== FILTERED DISCOVERY MODE ===")
    print("Filters specified - getting filtered coin list from Coinbase...")
    try:
        filtered_coins = get_filtered_coinbase_coins()
        if not filtered_coins:
            print("\n[ERROR] No coins match the specified filters.")
            print("Check your CHAINS/CATEGORIES values or try different filters.")
            sys.exit(1)
        # Use filtered coins as ANALYZE_COINS (limit to 5 for analysis)
        ANALYZE_COINS = filtered_coins[:5]
        USE_COIN_DISCOVERY = False  # Switch to coin choice mode with filtered coins
        print(f"\nSelected top {len(ANALYZE_COINS)} coins for analysis: {ANALYZE_COINS}")
        print("")
    except Exception as e:
        print(f"\n[ERROR] Coin filtering failed: {e}")
        sys.exit(1)

# === COIN CHOICE MODE: Analyze specified coins directly ===
if not USE_COIN_DISCOVERY:
    print("=== COIN CHOICE MODE ===")
    print(f"Analyzing specified coins: {ANALYZE_COINS}")
    print("")
    
    for i, coin_symbol in enumerate(ANALYZE_COINS):
        print(f"\n--- Analyzing coin {i+1}/{len(ANALYZE_COINS)}: {coin_symbol} ---")
        
        # Run Google Trends check and capture data for integrate mode
        trends_data = googleTrendsRequest(coin_symbol)
        
        # Get analysis from PRIMARY_LLM (first coin uses trend check, rest use coin check)
        use_trend = (i == 0)
        if use_trend:
            followUpResponseText = get_primary_trend_check(coin_symbol, trends_data)
        else:
            followUpResponseText = get_primary_coin_check(coin_symbol)
        
        print(followUpResponseText)
        
        # Parse recommendation
        followUp_coin = get_text_between_strings(followUpResponseText, "<**", "-PRS-") if followUpResponseText else None
        followUp_rec = get_text_between_strings(followUpResponseText, "-PRS-", "**>") if followUpResponseText else None
        print(f"Coin and rec: {followUp_coin}, {followUp_rec}")
        
        # Apply comparison/integration if enabled (pass trends_data for integrate mode)
        final_action, consensus = process_coin_with_comparison(coin_symbol, followUpResponseText, use_trend_check=use_trend, trends_data=trends_data)
        
        # Record recommendation to history (discovery_llm=None since coin was user-specified)
        if final_action:
            record_recommendation(
                coin_symbol=coin_symbol,
                recommendation=final_action,
                trader=trader,
                llm_source=PRIMARY_LLM,
                mode=LLM_MODE,
                consensus=consensus,
                discovery_llm=None
            )
        
        # Track and execute trade if recommended
        if final_action and 'BUY' in final_action:
            coinsToBuy.append(coin_symbol)
        
        if final_action and 'BUY' in final_action:
            if not WHATIF_MODE:
                if coin_symbol not in coinsToExclude:
                    buy_something(coin_symbol)
            else:
                whatif_buys += 1
                print(f"[WHAT-IF] Would execute BUY for {coin_symbol}")

# === DISCOVERY MODE: LLM discovers coins ===
else:
    # Make the request using PRIMARY_LLM
    primary_response_text = get_primary_recommendation()

    # Print the grounded response
    print(primary_response_text)

    print (f"--------------ABOVE IS CONTENT OF INITIAL {PRIMARY_LLM.upper()} RESPONSE----")

    # Check for explicit failure marker from LLM
    if '***FAILED***' in primary_response_text:
        print("\n" + "="*50)
        print("=== DISCOVERY FAILED ===")
        print("="*50)
        print(f"The {PRIMARY_LLM.upper()} LLM explicitly indicated it cannot provide recommendations.")
        print("\nConsider:")
        print("  - Using a different PRIMARY_LLM (e.g., gemini, grok)")
        print("  - Using COIN CHOICE MODE with --analyze-coins")
        print("="*50)
        import sys
        sys.exit(1)

    print ("------WE DOUBLE CHECK THE INITIAL RESPONSE WITH NEW QUERIES")

    print ("----------")

    my_string = primary_response_text

    # get the text following the first numbered recommendation
    delimiter_char = "1."

    result = get_text_after_delimiter(primary_response_text, delimiter_char)

    #print(f"Text after '{delimiter_char}': '{result}'")

    # Extract coin symbol from **SYMBOL** format (preferred) or (SYMBOL) format (fallback)
    start = "**"
    end = "**"
    extracted_content = get_text_between_strings(result, start, end) if result else None
    
    # Fallback to parentheses if no ** markers found
    if not extracted_content:
        start = "("
        end = ")"
        extracted_content = get_text_between_strings(result, start, end) if result else None

    print(f"Extracted content: {extracted_content}")

    # Check for discovery failure - validate extracted content looks like a coin symbol
    if not is_valid_coin_symbol(extracted_content):
        print("\n" + "="*50)
        print("=== DISCOVERY FAILED ===")
        print("="*50)
        print(f"The {PRIMARY_LLM.upper()} LLM did not return valid coin recommendations.")
        print(f"Extracted content: '{extracted_content}' is not a valid coin symbol.")
        print("\nThis typically happens when the LLM cannot access real-time data")
        print("or refuses to provide trading recommendations.")
        print("\nConsider:")
        print("  - Using a different PRIMARY_LLM (e.g., gemini, grok)")
        print("  - Using COIN CHOICE MODE with --analyze-coins")
        print("="*50)
        import sys
        sys.exit(1)

    if extracted_content:
        trends_data = googleTrendsRequest(extracted_content)
        followUpResponseText = get_primary_trend_check(extracted_content, trends_data)
        print(followUpResponseText)
        start = "<**"
        end = "-PRS-"
        followUp_coin1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        start = "-PRS-"
        end = "**>"
        followUp_rec1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        print("Trend check coin and rec1: ", followUp_coin1, followUp_rec1)
        
        # Use comparison/integration if enabled - pass full response text and trends_data for integration mode
        final_action, consensus = process_coin_with_comparison(extracted_content, followUpResponseText, use_trend_check=True, trends_data=trends_data)
        
        # Record recommendation to history (discovery_llm=PRIMARY_LLM since coin was discovered)
        if final_action:
            record_recommendation(
                coin_symbol=extracted_content,
                recommendation=final_action,
                trader=trader,
                llm_source=PRIMARY_LLM,
                mode=LLM_MODE,
                consensus=consensus,
                discovery_llm=PRIMARY_LLM
            )
        
        if final_action and 'BUY' in final_action:
            coinsToBuy.append(followUp_coin1)
            if not WHATIF_MODE:
                if extracted_content not in coinsToExclude:
                    buy_something(followUp_coin1)
            else:
                whatif_buys += 1
                print(f"[WHAT-IF] Would execute BUY for {extracted_content}")
    else:
        print("Could not extract coin 1 from response")

    # get the text following the second  numbered recommendation

    delimiter_char = "2."

    result = get_text_after_delimiter(primary_response_text, delimiter_char)

    #print(f"Text after '{delimiter_char}': '{result}'")

    # Extract coin symbol from **SYMBOL** format (preferred) or (SYMBOL) format (fallback)
    start = "**"
    end = "**"
    extracted_content = get_text_between_strings(result, start, end)
    
    # Fallback to parentheses if no ** markers found
    if not extracted_content:
        start = "("
        end = ")"
        extracted_content = get_text_between_strings(result, start, end)

    print(f"Extracted content: {extracted_content}")

    if extracted_content:
        trends_data = googleTrendsRequest(extracted_content)
        followUpResponseText = get_primary_coin_check(extracted_content)
        print(followUpResponseText)
        start = "<**"
        end = "-PRS-"
        followUp_coin1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        start = "-PRS-"
        end = "**>"
        followUp_rec1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        print("coin and rec1: ", followUp_coin1, followUp_rec1)
        
        # Use comparison/integration if enabled - pass full response text and trends_data for integration mode
        final_action, consensus = process_coin_with_comparison(extracted_content, followUpResponseText, use_trend_check=False, trends_data=trends_data)
        
        # Record recommendation to history (discovery_llm=PRIMARY_LLM since coin was discovered)
        if final_action:
            record_recommendation(
                coin_symbol=extracted_content,
                recommendation=final_action,
                trader=trader,
                llm_source=PRIMARY_LLM,
                mode=LLM_MODE,
                consensus=consensus,
                discovery_llm=PRIMARY_LLM
            )
        
        if final_action and 'BUY' in final_action:
            coinsToBuy.append(followUp_coin1)
            if not WHATIF_MODE:
                if extracted_content not in coinsToExclude:
                    buy_something(followUp_coin1)
            else:
                whatif_buys += 1
                print(f"[WHAT-IF] Would execute BUY for {extracted_content}")
    else:
        print("Could not extract coin 2 from response")

    # get the text following the third  numbered recommendation

    delimiter_char = "3."

    result = get_text_after_delimiter(primary_response_text, delimiter_char)

    #print(f"Text after '{delimiter_char}': '{result}'")

    # Extract coin symbol from **SYMBOL** format (preferred) or (SYMBOL) format (fallback)
    start = "**"
    end = "**"
    extracted_content = get_text_between_strings(result, start, end)
    
    # Fallback to parentheses if no ** markers found
    if not extracted_content:
        start = "("
        end = ")"
        extracted_content = get_text_between_strings(result, start, end)

    print(f"Extracted content: {extracted_content}")

    if extracted_content:
        trends_data = googleTrendsRequest(extracted_content)
        followUpResponseText = get_primary_coin_check(extracted_content)
        print(followUpResponseText)
        start = "<**"
        end = "-PRS-"
        followUp_coin1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        if followUp_coin1 is not None:
            start = "-PRS-"
            end = "**>"
            followUp_rec1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
            print("coin and rec1: ", followUp_coin1, followUp_rec1)
            
            # Use comparison/integration if enabled - pass full response text and trends_data for integration mode
            final_action, consensus = process_coin_with_comparison(extracted_content, followUpResponseText, use_trend_check=False, trends_data=trends_data)
            
            # Record recommendation to history (discovery_llm=PRIMARY_LLM since coin was discovered)
            if final_action:
                record_recommendation(
                    coin_symbol=extracted_content,
                    recommendation=final_action,
                    trader=trader,
                    llm_source=PRIMARY_LLM,
                    mode=LLM_MODE,
                    consensus=consensus,
                    discovery_llm=PRIMARY_LLM
                )
            
            if final_action and 'BUY' in final_action:
                coinsToBuy.append(followUp_coin1)
                if not WHATIF_MODE:
                    if extracted_content not in coinsToExclude:
                        buy_something(followUp_coin1)
                else:
                    whatif_buys += 1
                    print(f"[WHAT-IF] Would execute BUY for {extracted_content}")
        else:
            print("Could not extract coin 3 from response")

    # get the text after the string that indicates the social media recommendation
    # Format is +++COIN1+++ +++COIN2+++ - after first +++, coin is before next +++

    delimiter_char = "+++"

    result = get_text_after_delimiter(primary_response_text, delimiter_char)

    print(f"Text after '{delimiter_char}': '{result}'")

    # Social media format: after first +++, coin symbol is before the next +++
    # e.g., "+++PEPE+++ +++DOGE+++" -> after first +++ we get "PEPE+++ +++DOGE+++"
    # So extract from start of result to the first +++
    extracted_content = None
    if result:
        next_delimiter = result.find("+++")
        if next_delimiter > 0:
            extracted_content = result[:next_delimiter].strip()
    
    # Fallback to ** or () if no +++ format found
    if not extracted_content:
        start = "**"
        end = "**"
        extracted_content = get_text_between_strings(result, start, end)
    if not extracted_content:
        start = "("
        end = ")"
        extracted_content = get_text_between_strings(result, start, end)

    print(f"Extracted content: {extracted_content}")

    if extracted_content:
        trends_data = googleTrendsRequest(extracted_content)
        followUpResponseText = get_primary_trend_check(extracted_content, trends_data)
        print(followUpResponseText)
        start = "<**"
        end = "-PRS-"
        followUp_coin1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        start = "-PRS-"
        end = "**>"
        followUp_rec1 = get_text_between_strings(followUpResponseText, start, end) if followUpResponseText else None
        print("Trend check coin and rec1: ", followUp_coin1, followUp_rec1)
        
        # Use comparison/integration if enabled - pass full response text and trends_data for integration mode
        final_action, consensus = process_coin_with_comparison(extracted_content, followUpResponseText, use_trend_check=True, trends_data=trends_data)
        
        # Record recommendation to history (discovery_llm=PRIMARY_LLM since coin was discovered)
        if final_action:
            record_recommendation(
                coin_symbol=extracted_content,
                recommendation=final_action,
                trader=trader,
                llm_source=PRIMARY_LLM,
                mode=LLM_MODE,
                consensus=consensus,
                discovery_llm=PRIMARY_LLM
            )
        
        if final_action and 'BUY' in final_action:
            coinsToBuy.append(followUp_coin1)
            if not WHATIF_MODE:
                if extracted_content not in coinsToExclude:
                    buy_something(followUp_coin1)
            else:
                whatif_buys += 1
                print(f"[WHAT-IF] Would execute BUY for {extracted_content}")
    else:
        print("No social media recommendation found in response")

# Print summary
print("\n" + "="*50)
print("=== RUN SUMMARY ===")
print("="*50)
print(f"Trading Mode: {TRADING_MODE.upper()}")
print(f"LLM Mode: {LLM_MODE}")
print(f"Primary LLM: {PRIMARY_LLM}")
if USE_COIN_DISCOVERY:
    print("Coin Selection: Discovery Mode")
else:
    print(f"Coin Selection: {', '.join(ANALYZE_COINS)}")
if CHAINS:
    print(f"Chain Filter: {', '.join(CHAINS)}")
if CATEGORIES:
    print(f"Category Filter: {', '.join(CATEGORIES)}")
if POLYMARKET_FILTER:
    print("Polymarket Filter: Enabled")
if LLM_MODE in ['compare', 'integrate']:
    print(f"Compare LLMs: {COMPARE_LLMS}")
    print(f"Require Consensus: {REQUIRE_CONSENSUS}")
    print(f"Tiebreaker: {INTEGRATION_TIEBREAKER}")
print(f"Coins to buy: {coinsToBuy}")

# What-if summary
if WHATIF_MODE:
    print("\n--- WHAT-IF SUMMARY ---")
    print(f"Simulated BUY orders: {whatif_buys}")
    print("No actual trades were executed.")
print("="*50)
