from google import genai

from google.genai import types

import argparse
import datetime
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from coinbase.rest import RESTClient

from coinbaseutil2 import BlobbyTrader 

from claudeutil import ClaudeTrader, compare_recommendations, get_consensus_action

from openaiutil import OpenAITrader

from grokutil import GrokTrader

from perplexityutil import PerplexityTrader

from historyutil import record_recommendation

from lunarcrushutil import filter_from_cache, cache_exists, get_cache_age

from polymarketutil import filter_coins_by_polymarket

from santimentutil import auto_refresh_cache, discover_coins_santiment

from pytrends.request import TrendReq

import pandas as pd


def parse_args():
    """Parse command-line arguments with environment variable fallbacks."""
    parser = argparse.ArgumentParser(
        description='Trading Bot - Cryptocurrency recommendation engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python crypto_trading_bot.py --llm-mode=compare --coins=PEPE,BONK
  python crypto_trading_bot.py --trading-mode=whatif --llm-mode=integrate
  
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
    
    # Discovery method
    parser.add_argument(
        '--discovery',
        default=os.environ.get('DISCOVERY', 'llm'),
        help='Discovery method: llm, santiment, or both comma-separated (default: llm)'
    )
    
    # DEX mode - Solana DEX trading via Jupiter + WalletConnect
    parser.add_argument(
        '--dex',
        action='store_true',
        default=os.environ.get('DEX_MODE', 'false').lower() == 'true',
        help='Enable DEX mode: Trade on Solana via Jupiter + Phantom wallet (default: false)'
    )
    
    # DEX slippage tolerance
    parser.add_argument(
        '--slippage',
        type=float,
        default=float(os.environ.get('DEX_SLIPPAGE', '1.0')),
        help='DEX slippage tolerance as percentage (default: 1.0 = 1%%)'
    )
    
    # DEX wallet test on startup
    parser.add_argument(
        '--test-wallet',
        action='store_true',
        default=False,
        help='Test wallet connection on startup (DEX mode only, default: false)'
    )
    
    # Candidate coins export - write recommended coins to candidate_coins.csv
    parser.add_argument(
        '--export-candidates',
        action='store_true',
        default=os.environ.get('EXPORT_CANDIDATES', 'false').lower() == 'true',
        help='Export recommended coins to candidate_coins.csv for correlation analysis (default: false)'
    )
    
    parser.add_argument(
        '--candidate-dir',
        default=os.environ.get('CANDIDATE_DIR', './correlation_data'),
        help='Directory for candidate_coins.csv (default: ./correlation_data)'
    )
    
    parser.add_argument(
        '--candidate-blockchain',
        default=os.environ.get('CANDIDATE_BLOCKCHAIN', 'Solana'),
        help='Blockchain to record for exported candidates (default: Solana)'
    )
    
    parser.add_argument(
        '--export-recommendations',
        default=os.environ.get('EXPORT_RECOMMENDATIONS', 'ALL'),
        help='Which recommendations to export: ALL, BUY, or BUY,HOLD (default: ALL)'
    )
    
    # Relax discovery failure check
    parser.add_argument(
        '--relax-discovery-failure',
        action='store_true',
        default=os.environ.get('RELAX_DISCOVERY_FAILURE', 'false').lower() == 'true',
        help='Proceed with discovered coins even if LLM indicates caveats (default: false)'
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

# DEX mode configuration (needed early for discovery default)
DEX_MODE = args.dex

# Discovery methods: llm, santiment, or both
# DEX mode defaults to santiment (Solana tokens), CEX defaults to llm
discovery_default_used = (args.discovery == os.environ.get('DISCOVERY', 'llm') and 
                          not os.environ.get('DISCOVERY'))
if DEX_MODE and discovery_default_used:
    DISCOVERY_RAW = 'santiment'
    print("[DEX] Using santiment discovery (default for DEX mode)")
else:
    DISCOVERY_RAW = args.discovery.strip().lower()
DISCOVERY_METHODS = [m.strip() for m in DISCOVERY_RAW.split(',') if m.strip()]
# Validate discovery methods
VALID_DISCOVERY = {'llm', 'santiment'}
for method in DISCOVERY_METHODS:
    if method not in VALID_DISCOVERY:
        print(f"[ERROR] Invalid discovery method: '{method}'. Valid: llm, santiment")
        sys.exit(1)
USE_LLM_DISCOVERY = 'llm' in DISCOVERY_METHODS
USE_SANTIMENT_DISCOVERY = 'santiment' in DISCOVERY_METHODS
DEX_SLIPPAGE = args.slippage
TEST_WALLET = args.test_wallet
EXCHANGE_MODE = "solana-dex" if DEX_MODE else "cex"

# Candidate coins export configuration
EXPORT_CANDIDATES = args.export_candidates
CANDIDATE_DIR = args.candidate_dir
CANDIDATE_BLOCKCHAIN = args.candidate_blockchain
EXPORT_RECOMMENDATIONS = args.export_recommendations.upper()

# Discovery failure relaxation
RELAX_DISCOVERY_FAILURE = args.relax_discovery_failure

# Validate chain filter compatibility with DEX mode
if DEX_MODE and not WHATIF_MODE:
    # Live DEX mode: only Solana chain is supported
    non_solana_chains = [c for c in CHAINS if c != 'solana']
    if non_solana_chains:
        print(f"[ERROR] DEX live mode only supports Solana chain")
        print(f"        Invalid chains specified: {', '.join(non_solana_chains)}")
        print(f"        Remove --chains or use --chains=solana")
        print(f"        (Use --trading-mode=whatif to research other chains)")
        sys.exit(1)
    # Auto-set to solana if no chain specified (for discovery filtering)
    if not CHAINS:
        CHAINS = ['solana']
        print(f"[DEX] Auto-filtering to Solana chain for live trading")
elif DEX_MODE and WHATIF_MODE and CHAINS:
    # What-if mode with non-Solana chains: warn but allow
    non_solana_chains = [c for c in CHAINS if c != 'solana']
    if non_solana_chains:
        print(f"[DEX] Warning: What-if mode with non-Solana chains: {', '.join(non_solana_chains)}")
        print(f"[DEX] These coins cannot be traded in DEX live mode")

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
    if DEX_MODE:
        # Solana DEX mode: only recommend Solana meme coins tradeable via Jupiter
        prompt = "What 3 Solana blockchain meme coins are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Only include coins tradeable on Solana DEX aggregators like Jupiter (e.g., BONK, WIF, POPCAT, JUP, PYTH, RAY, ORCA, MANGO, or other Solana SPL tokens). Do NOT include coins on other chains like Base, Ethereum, or BNB. Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
    else:
        # CEX mode: Coinbase-listed coins
        prompt = "What 3 meme coins listed on the Coinbase exchange are major crypto analysts and influencers online currently discussing as having potential for short-term price appreciation? Once you have identified the top 3 being discussed, number them and indicate which show the most positive social media sentiment in the last 4 hours. Put 3 plus signs around EACH coin symbol separately at the end of your response. If you cannot identify any coins being actively discussed, include ***FAILED*** at the end of your output. Base your response on actual analyst discussions you are aware of."
    
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
        return claude_trader.send_recommendation_request(dex_mode=DEX_MODE)
    elif PRIMARY_LLM == 'openai' and openai_trader:
        return openai_trader.send_recommendation_request(dex_mode=DEX_MODE)
    elif PRIMARY_LLM == 'grok' and grok_trader:
        return grok_trader.send_recommendation_request(dex_mode=DEX_MODE)
    elif PRIMARY_LLM == 'perplexity' and perplexity_trader:
        return perplexity_trader.send_recommendation_request(dex_mode=DEX_MODE)
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
            print("Could not retrieve product details.")

        # Execute buy order (DEX mode handles whatif internally)
        if DEX_MODE:
            result = trader.market_order_buy(coinToBuy+'-USD', '25.00', whatif=WHATIF_MODE)
            if result and result.get('executed'):
                print(f"[DEX] Trade executed: {result.get('tx_url', 'no tx')}")
        else:
            trader.market_order_buy(coinToBuy+'-USD', '25.00')

        print("\n--- Getting coin Product Details AFTER for: ",(coinToBuy+"-USD") )

        usd_product = trader.get_product_details(coinToBuy+"-USD")

        if usd_product:
                print(json.dumps(usd_product.to_dict(), indent=2))
        else:
            print("Could not retrieve product details.")

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
    
    Uses cached LunarCrush data from coin_cache.json for filtering.
    
    Args:
        coins: List of coin symbols to filter
        
    Returns:
        Filtered list of coins matching all specified criteria
    """
    filtered = coins
    
    # Step 1: Apply LunarCrush filters from cache (chains and/or categories)
    if CHAINS or CATEGORIES:
        # Check if cache exists
        if not cache_exists():
            print("\n" + "="*60)
            print("[ERROR] Coin cache file not found!")
            print("="*60)
            print("\nThe --chains and --categories filters require coin_cache.json")
            print("which contains LunarCrush category/blockchain data.")
            print("\nTo create the cache, run:")
            print("  LUNARCRUSH_API_KEY=your_key python refresh_coin_cache.py")
            print("\nNote: LunarCrush requires a paid subscription ($5/day or $90/month)")
            print("Try promo code ARCH30 for 30% off.")
            print("="*60 + "\n")
            sys.exit(1)
        
        try:
            filtered, skipped = filter_from_cache(
                filtered,
                chains=CHAINS if CHAINS else None,
                categories=CATEGORIES if CATEGORIES else None
            )
        except FileNotFoundError as e:
            print(f"\n[ERROR] {e}")
            sys.exit(1)
    
    # Step 2: Apply Polymarket filter (always live - free API)
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

# Initialize trader based on exchange mode
if DEX_MODE:
    try:
        from dex.trader import SolanaDEXTrader
        # Live mode if not whatif OR if testing wallet
        need_wallet = (not WHATIF_MODE) or TEST_WALLET
        trader = SolanaDEXTrader(slippage_bps=int(DEX_SLIPPAGE * 100), live_mode=need_wallet)
        print(f"[DEX] Solana DEX trader initialized (slippage: {DEX_SLIPPAGE}%)")
        
        # Test wallet connection if requested
        if TEST_WALLET:
            if not trader.test_wallet_connection():
                print("[ERROR] Wallet test failed. Exiting.")
                sys.exit(1)
            print("")  # Blank line after test output
    except ImportError as e:
        print(f"[ERROR] DEX mode requires dex module: {e}")
        print("[ERROR] Ensure dex/ directory exists with required files")
        sys.exit(1)
else:
    trader = BlobbyTrader()

# === STARTUP BANNER ===
print("\n" + "="*50)
print("=== TRADING BOT ===")
print("="*50)

# Show exchange mode
if DEX_MODE:
    dex_source = get_config_source('--dex', 'DEX_MODE')
    print(f"Exchange: SOLANA DEX (Jupiter + Phantom) [{dex_source}]")
    slippage_source = get_config_source('--slippage', 'DEX_SLIPPAGE')
    print(f"Slippage: {DEX_SLIPPAGE}% [{slippage_source}]")
else:
    print(f"Exchange: COINBASE CEX")

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
    discovery_source = get_config_source('--discovery', 'DISCOVERY')
    print(f"Coin Selection: Discovery Mode [{coins_source}]")
    print(f"Discovery Methods: {', '.join(DISCOVERY_METHODS)} [{discovery_source}]")
else:
    print(f"Coin Selection: {', '.join(ANALYZE_COINS)} [{coins_source}]")

# Show filter settings
if CHAINS:
    chains_source = get_config_source('--chains', 'CHAINS')
    print(f"Chain Filter: {', '.join(CHAINS)} [{chains_source}]")
if CATEGORIES:
    categories_source = get_config_source('--categories', 'CATEGORIES')
    print(f"Category Filter: {', '.join(CATEGORIES)} [{categories_source}]")
if CHAINS or CATEGORIES:
    cache_age = get_cache_age()
    if cache_age:
        print(f"Cache Age: {cache_age}")
    else:
        print(f"Cache Age: NOT FOUND (run refresh_coin_cache.py)")
if POLYMARKET_FILTER:
    polymarket_source = get_config_source('--polymarket-filter', 'POLYMARKET_FILTER')
    print(f"Polymarket Filter: Enabled [{polymarket_source}]")

consensus_source = get_config_source('--require-consensus', 'REQUIRE_CONSENSUS')
print(f"Require Consensus: {REQUIRE_CONSENSUS} [{consensus_source}]")

if LLM_MODE in ['compare', 'integrate']:
    tiebreaker_source = get_config_source('--tiebreaker', 'INTEGRATION_TIEBREAKER')
    print(f"Tiebreaker: {INTEGRATION_TIEBREAKER} [{tiebreaker_source}]")

print("="*50 + "\n")

# === AUTO-REFRESH CACHE IF SANTIMENT DISCOVERY ENABLED ===
if USE_COIN_DISCOVERY and USE_SANTIMENT_DISCOVERY:
    print("=== SANTIMENT DISCOVERY: AUTO-REFRESH CACHE ===")
    try:
        all_coinbase = trader.list_all_coins()
        auto_refresh_cache(all_coinbase, verbose=True)
        print("")
    except Exception as e:
        print(f"[WARNING] Cache refresh failed: {e}")
        print("Continuing with existing cache if available...")
        print("")


def extract_coins_from_llm_response(response_text, relax_failure=False):
    """Extract up to 3 coin symbols from LLM discovery response.
    
    Args:
        response_text: The LLM response text to parse
        relax_failure: If True, attempt extraction even if ***FAILED*** is present
    
    Returns:
        List of valid coin symbols extracted from the response
    """
    coins = []
    
    if not response_text:
        return coins
    
    # Check for failure indicator (skip if relaxed)
    if '***FAILED***' in response_text and not relax_failure:
        return coins
    
    # First try the +++SYMBOL+++ format (requested in prompt)
    import re
    plus_matches = re.findall(r'\+\+\+([A-Za-z0-9]+)\+\+\+', response_text)
    if plus_matches:
        for match in plus_matches[:3]:
            if is_valid_coin_symbol(match):
                coins.append(match.upper())
        if coins:
            return coins
    
    # Fallback: Helper to extract symbol from numbered item
    def extract_symbol_from_item(text):
        if not text:
            return None
        # Try **SYMBOL** format first
        symbol = get_text_between_strings(text, "**", "**")
        if is_valid_coin_symbol(symbol):
            return symbol.upper()
        # Try (SYMBOL) format
        symbol = get_text_between_strings(text, "(", ")")
        if is_valid_coin_symbol(symbol):
            return symbol.upper()
        # Try first word (e.g., "PEPE - description...")
        first_word = text.strip().split()[0].strip('.,:-') if text.strip() else None
        if first_word and is_valid_coin_symbol(first_word):
            return first_word.upper()
        return None
    
    # Extract coin 1 (after "1.")
    result = get_text_after_delimiter(response_text, "1.")
    symbol = extract_symbol_from_item(result)
    if symbol:
        coins.append(symbol)
    
    # Extract coin 2 (after "2.")
    result = get_text_after_delimiter(response_text, "2.")
    symbol = extract_symbol_from_item(result)
    if symbol:
        coins.append(symbol)
    
    # Extract coin 3 (after "3.")
    result = get_text_after_delimiter(response_text, "3.")
    symbol = extract_symbol_from_item(result)
    if symbol:
        coins.append(symbol)
    
    return coins


def run_llm_discovery():
    """Run LLM-based coin discovery.
    
    Returns:
        List of discovered coin symbols (up to 3)
    """
    print("=== LLM DISCOVERY ===")
    print(f"Asking {PRIMARY_LLM.upper()} for coin recommendations...")
    
    response_text = get_primary_recommendation()
    if not response_text:
        print("[WARNING] LLM returned no response")
        return []
    
    print(response_text)
    print(f"--------------ABOVE IS CONTENT OF {PRIMARY_LLM.upper()} RESPONSE----")
    
    # Check for explicit failure indicator
    if '***FAILED***' in response_text:
        if RELAX_DISCOVERY_FAILURE:
            print("[INFO] LLM indicated caveats, but --relax-discovery-failure is set")
            print("[INFO] Attempting to extract coins anyway...")
        else:
            print("[WARNING] LLM explicitly indicated it cannot provide recommendations")
            return []
    
    # Extract coins (will also check for ***FAILED*** if not relaxed)
    coins = extract_coins_from_llm_response(response_text, relax_failure=RELAX_DISCOVERY_FAILURE)
    print(f"LLM discovered coins: {coins}")
    return coins


def run_santiment_discovery():
    """Run Santiment-based coin discovery (ranked by volume change).
    
    Returns:
        List of discovered coin symbols (up to 3)
    """
    print("=== SANTIMENT DISCOVERY ===")
    print("Finding coins with highest 24h volume change...")
    
    try:
        all_coinbase = trader.list_all_coins()
        coins = discover_coins_santiment(
            all_coinbase,
            chains=CHAINS if CHAINS else None,
            categories=CATEGORIES if CATEGORIES else None,
            limit=3,
            verbose=True
        )
        print(f"Santiment discovered coins: {coins}")
        return coins
    except Exception as e:
        print(f"[WARNING] Santiment discovery failed: {e}")
        return []


# === APPLY COIN FILTERING (legacy - when filters set but no santiment discovery) ===
# If filters are set, no specific coins provided, and NOT using santiment discovery
if USE_COIN_FILTERING and USE_COIN_DISCOVERY and not USE_SANTIMENT_DISCOVERY:
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
                discovery_llm=None,
                exchange=EXCHANGE_MODE,
                export_candidate=EXPORT_CANDIDATES,
                candidate_dir=CANDIDATE_DIR,
                candidate_blockchain=CANDIDATE_BLOCKCHAIN,
                export_recommendations=EXPORT_RECOMMENDATIONS
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

# === HYBRID DISCOVERY MODE ===
else:
    print("=== HYBRID DISCOVERY MODE ===")
    
    # Collect discovered coins from enabled sources
    llm_coins = []
    santiment_coins = []
    
    # Run LLM discovery if enabled
    if USE_LLM_DISCOVERY:
        llm_coins = run_llm_discovery()
        print("")
    
    # Run Santiment discovery if enabled
    if USE_SANTIMENT_DISCOVERY:
        santiment_coins = run_santiment_discovery()
        print("")
    
    # Union and deduplicate (LLM coins first, then Santiment)
    discovered_coins = []
    seen = set()
    
    # Add LLM coins first
    for coin in llm_coins:
        if coin.upper() not in seen:
            discovered_coins.append(coin.upper())
            seen.add(coin.upper())
    
    # Add Santiment coins (deduplicating)
    for coin in santiment_coins:
        if coin.upper() not in seen:
            discovered_coins.append(coin.upper())
            seen.add(coin.upper())
    
    # Cap at 6 coins (3 LLM + 3 Santiment max)
    if len(discovered_coins) > 6:
        print(f"Capping discovered coins from {len(discovered_coins)} to 6")
        discovered_coins = discovered_coins[:6]
    
    print("="*50)
    print(f"DISCOVERED COINS: {discovered_coins}")
    if llm_coins:
        print(f"  From LLM: {llm_coins}")
    if santiment_coins:
        print(f"  From Santiment: {santiment_coins}")
    print("="*50 + "\n")
    
    # Check if we discovered any coins
    if not discovered_coins:
        print("\n" + "="*50)
        print("=== DISCOVERY FAILED ===")
        print("="*50)
        print("No coins were discovered from any source.")
        print("\nConsider:")
        print("  - Using a different PRIMARY_LLM (e.g., gemini, grok)")
        print("  - Adding santiment to discovery methods: --discovery=llm,santiment")
        print("  - Using COIN CHOICE MODE with --coins")
        print("="*50)
        sys.exit(1)
    
    # Analyze each discovered coin
    for i, coin_symbol in enumerate(discovered_coins):
        # Determine discovery source for this coin
        discovery_source = None
        if coin_symbol in [c.upper() for c in llm_coins]:
            discovery_source = PRIMARY_LLM
        elif coin_symbol in [c.upper() for c in santiment_coins]:
            discovery_source = "santiment"
        
        print(f"\n--- Analyzing discovered coin {i+1}/{len(discovered_coins)}: {coin_symbol} (from {discovery_source}) ---")
        
        # Run Google Trends check
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
        
        # Apply comparison/integration if enabled
        final_action, consensus = process_coin_with_comparison(coin_symbol, followUpResponseText, use_trend_check=use_trend, trends_data=trends_data)
        
        # Record recommendation to history
        if final_action:
            record_recommendation(
                coin_symbol=coin_symbol,
                recommendation=final_action,
                trader=trader,
                llm_source=PRIMARY_LLM,
                mode=LLM_MODE,
                consensus=consensus,
                discovery_llm=discovery_source,
                exchange=EXCHANGE_MODE,
                export_candidate=EXPORT_CANDIDATES,
                candidate_dir=CANDIDATE_DIR,
                candidate_blockchain=CANDIDATE_BLOCKCHAIN,
                export_recommendations=EXPORT_RECOMMENDATIONS
            )
        
        # Track and execute trade if recommended
        if final_action and 'BUY' in final_action:
            coinsToBuy.append(coin_symbol)
            if not WHATIF_MODE:
                if coin_symbol not in coinsToExclude:
                    buy_something(coin_symbol)
            else:
                whatif_buys += 1
                print(f"[WHAT-IF] Would execute BUY for {coin_symbol}")

# Print summary
print("\n" + "="*50)
print("=== RUN SUMMARY ===")
print("="*50)
print(f"Exchange: {EXCHANGE_MODE.upper()}")
print(f"Trading Mode: {TRADING_MODE.upper()}")
print(f"LLM Mode: {LLM_MODE}")
print(f"Primary LLM: {PRIMARY_LLM}")
if USE_COIN_DISCOVERY:
    print(f"Coin Selection: Discovery Mode ({', '.join(DISCOVERY_METHODS)})")
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
if EXPORT_CANDIDATES:
    print(f"Candidate Export: Enabled ({EXPORT_RECOMMENDATIONS} recommendations)")
    print(f"Candidate Dir: {CANDIDATE_DIR}")
print(f"Coins to buy: {coinsToBuy}")

# What-if summary
if WHATIF_MODE:
    print("\n--- WHAT-IF SUMMARY ---")
    print(f"Simulated BUY orders: {whatif_buys}")
    print("No actual trades were executed.")
print("="*50)
