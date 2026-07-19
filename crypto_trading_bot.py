from google import genai

from google.genai import types

import argparse
import datetime
import json
import os
import sys
import time

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from coinbase.rest import RESTClient

from coinbaseutil2 import BlobbyTrader 

from claudeutil import ClaudeTrader, compare_recommendations, get_consensus_action

from openaiutil import OpenAITrader

from grokutil import GrokTrader

from perplexityutil import PerplexityTrader

from historyutil import record_recommendation

import executionledger

from modelregistry import get_model

import llmpreflight

import voteschema

import marketdata

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
        default=os.environ.get('TRADING_MODE', 'whatif').lower(),
        help=(
            'Trading mode (default: whatif). whatif simulates only. '
            'BREAKING CHANGE: --trading-mode=live (or TRADING_MODE=live) NO '
            'LONGER enables live trading by itself; live now requires BOTH the '
            '--live flag AND the env var LIVE_TRADING_CONFIRMED=1. Any live '
            'request missing either lock downgrades to whatif with a notice.'
        )
    )

    # Live-trading arming flag (half of the double lock; see --trading-mode)
    parser.add_argument(
        '--live',
        action='store_true',
        default=False,
        help=(
            'Arm live trading. Executes REAL trades and requires BOTH this flag '
            'AND env LIVE_TRADING_CONFIRMED=1; otherwise the bot runs in whatif '
            'and prints a downgrade notice explaining what is missing.'
        )
    )

    # Per-buy notional (USD) — replaces the old hardcoded $5.00 literals
    parser.add_argument(
        '--notional-usd',
        type=float,
        default=float(os.environ.get('TRADE_NOTIONAL_USD', '5.00')),
        help=(
            'USD notional per buy order for both CEX and DEX (default: 5.00). '
            'Must be positive and at most 100.00 (this is a $5-scale experiment).'
        )
    )

    # Per-run cumulative spend cap (USD)
    parser.add_argument(
        '--run-spend-cap-usd',
        type=float,
        default=float(os.environ.get('RUN_SPEND_CAP_USD', '10.00')),
        help=(
            'Maximum cumulative intended USD spend across ALL buys in a single '
            'run (default: 10.00). A buy that would exceed the cap is refused '
            'and tallied. What-if spend counts against the cap too.'
        )
    )

    # Per-day cumulative LIVE spend cap (USD) -- T5, summed from the execution
    # ledger across ALL runs today (UTC). What-if does NOT consume this cap.
    parser.add_argument(
        '--daily-spend-cap-usd',
        type=float,
        default=float(os.environ.get('DAILY_SPEND_CAP_USD', '15.00')),
        help=(
            'Maximum cumulative intended LIVE USD spend across ALL runs in a '
            'single UTC day (default: 15.00), summed from the execution ledger. '
            'A live buy that would exceed it is refused with [DAILY CAP]. '
            'What-if spend does NOT count against this cap.'
        )
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

    # T6: LLM preflight escape hatch. Preflight is ON by default; this flag
    # skips it (e.g. for offline dev, or when a probe itself is flaky).
    parser.add_argument(
        '--skip-preflight',
        action='store_true',
        default=os.environ.get('SKIP_PREFLIGHT', 'false').lower() == 'true',
        help=(
            'Skip the LLM preflight probe before analysis (default: false, '
            'preflight runs). In live mode, a failing preflight normally '
            'aborts the run -- this flag bypasses that check entirely.'
        )
    )

    # T10: opt out of the non-fatal history-summary analyzer pass at startup.
    parser.add_argument(
        '--skip-analyzer',
        action='store_true',
        default=os.environ.get('SKIP_ANALYZER', 'false').lower() == 'true',
        help=(
            'Skip the non-fatal history-summary analyzer pass at startup '
            '(default: false, the summary runs). The summary never blocks '
            'trading -- any error is caught and warned.'
        )
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


# === T9: real Coinbase market data injection (plan Phase 2) ==================
# The market block (Coinbase OHLCV summary + Fibonacci levels PRIMARY, plus
# demoted Google-Trends, CMC (T12), and SOCIAL/LunarCrush (T13) SECONDARY
# sections) is the PRIMARY data section carried by every analysis prompt. It
# is built ONCE per coin per run and cached here; get_llm_response /
# get_primary_* read the cache and attach a per-provider grounding line. See
# marketdata.py and EVALUATION_LESSONS_LEARNED §1.4/§5.6.
MARKET_BLOCK_CACHE = {}

# F7a: MARKET_BLOCK_CACHE has no expiry -- for a normal single-pass run
# (whatif or live, coin-choice or discovery loop) that's correct, since each
# coin is only ever fetched once per run. But the cache is a module-level
# global that outlives any single loop iteration, so if the bot is ever
# driven from an in-process loop (e.g. a future scheduled-cadence runner)
# instead of one-process-per-run, every later iteration would silently reuse
# the FIRST iteration's market data forever -- stale price/fib/trends data
# feeding every panelist's prompt with no signal that anything is wrong.
# MARKET_BLOCK_FETCHED_AT tracks the wall-clock fetch time per coin
# (deliberately a separate dict, not a (block, ts) tuple stored in
# MARKET_BLOCK_CACHE itself -- tests/test_market_data.py asserts
# `MARKET_BLOCK_CACHE['BTC'] == block` and injects raw block strings
# directly into the cache; changing the stored value's shape would break
# that file, which is out of this task's ownership). build_market_block_for_
# coin treats a missing/expired timestamp as a cache miss and refetches;
# _resolve_market_block (the read side, called from within the same
# iteration right after the build call) does not re-check the TTL -- this
# preserves exactly one fetch per coin per run for normal runs, and only
# bounds staleness for the hypothetical looping case.
MARKET_BLOCK_TTL_SECONDS = int(os.environ.get('MARKET_BLOCK_TTL_SECONDS', 900))  # 15 min default
MARKET_BLOCK_FETCHED_AT = {}


def get_trends_status(coin_symbol):
    """Fetch Google Trends for `coin_symbol` and classify it (T9).

    Unlike the old pre-T9 trends helper (removed; it returned None for BOTH
    a 429 and a genuinely-empty series — doc 3.1/5.3.9), this distinguishes
    the cases so the market block can DISCLOSE absence instead of silently
    omitting it:

        'present'     -> a real, non-all-zero series (data string attached)
        'below_floor' -> all-zero series (search volume below Google's floor)
        'failed'      -> fetch/429 exception
        'unavailable' -> no series returned at all
    """
    try:
        pytrends.build_payload([coin_symbol], cat=0, timeframe='now 4-H', geo='', gprop='')
        df = pytrends.interest_over_time()
    except Exception as e:
        print(f"[TRENDS] fetch failed for {coin_symbol}: {e}")
        return {'status': 'failed', 'data': None}

    if df is None or df.empty or coin_symbol not in df:
        return {'status': 'unavailable', 'data': None}

    series = df[coin_symbol]
    try:
        if float(series.max()) == 0.0:
            return {'status': 'below_floor', 'data': None}
    except (TypeError, ValueError):
        return {'status': 'unavailable', 'data': None}

    recent_values = series.tail(10).tolist()
    summary = (
        f"Google Trends data for {coin_symbol} (last 4 hours):\n"
        f"- Average interest: {series.mean():.1f}\n"
        f"- Max interest: {series.max()}\n"
        f"- Min interest: {series.min()}\n"
        f"- Recent 10 values: {recent_values}\n"
        f"- Total data points: {len(series)}"
    )
    return {'status': 'present', 'data': summary}


def build_market_block_for_coin(coin_symbol, candle_client):
    """Build (and cache) the provider-agnostic market block for a coin.

    Called once per coin per run. Fetches 7d hourly Coinbase candles via
    `candle_client` (a RESTClient, or None in DEX mode), computes the summary
    and Fibonacci levels, and folds in the demoted Google-Trends signal.
    `marketdata.build_market_block` also self-fetches and appends the CMC
    (T12) and SOCIAL/LunarCrush (T13) SECONDARY sections here -- this is the
    only place those are fetched, so this function's MARKET_BLOCK_CACHE is
    the one per-coin-per-run cache that covers all four secondary/primary
    sections. Returns the compact text block (MARKET DATA/FIBONACCI PRIMARY,
    then GOOGLE TRENDS/CMC/SOCIAL SECONDARY). ANY fetch/compute failure
    degrades to an explicit "MARKET DATA UNAVAILABLE: <reason>" block (never
    silence); the trends/CMC/SOCIAL SECONDARY sections are each rendered
    independently either way.

    F7a: a cache hit is only honored while it's within MARKET_BLOCK_TTL_
    SECONDS of its fetch time; an expired (or timestamp-missing, e.g.
    directly-injected) entry is treated as a miss and refetched. This never
    fires within a normal run -- the TTL default (15 min) comfortably
    outlasts a single pass over ANALYZE_COINS/discovered_coins -- it only
    bounds staleness if the bot is ever driven from an in-process loop.
    """
    if coin_symbol in MARKET_BLOCK_CACHE:
        fetched_at = MARKET_BLOCK_FETCHED_AT.get(coin_symbol)
        if fetched_at is not None and (time.time() - fetched_at) < MARKET_BLOCK_TTL_SECONDS:
            return MARKET_BLOCK_CACHE[coin_symbol]
        # Expired (or fetched_at unknown) -- fall through and refetch.

    trends_status = get_trends_status(coin_symbol)
    summary = None
    fib = None
    reason = None

    if candle_client is None:
        reason = 'no Coinbase candle client available (DEX mode)'
    else:
        product_id = f"{coin_symbol}-USD"
        try:
            rows = marketdata.fetch_candles(candle_client, product_id, days=7,
                                            granularity='ONE_HOUR')
            if not rows:
                reason = f'no candles returned for {product_id}'
            else:
                summary = marketdata.summarize_market_data(rows)
                # fib degrades to None internally; disclosed in the block.
                fib = marketdata.fib_summary(rows, coin_symbol)
        except Exception as e:
            reason = f'{type(e).__name__}: {e}'
            print(f"[MARKET DATA] fetch/compute failed for {coin_symbol}: {reason}")

    block = marketdata.build_market_block(coin_symbol, summary, fib, trends_status,
                                          unavailable_reason=reason)
    MARKET_BLOCK_CACHE[coin_symbol] = block
    MARKET_BLOCK_FETCHED_AT[coin_symbol] = time.time()
    return block


def _resolve_market_block(coin_symbol, llm_name):
    """The cached market block for `coin_symbol` with `llm_name`'s grounding
    line attached (deliverable #4), or None when nothing was cached.

    F7a: this is a plain read -- it does not itself re-check
    MARKET_BLOCK_TTL_SECONDS. TTL enforcement lives entirely in
    build_market_block_for_coin (the gatekeeper always called earlier in the
    same per-coin loop iteration), so by the time this runs the entry is
    known-fresh for the current iteration; re-checking here would add no
    safety and would require this function to trigger its own refetch on
    expiry, which is out of scope for a pure read."""
    block = MARKET_BLOCK_CACHE.get(coin_symbol)
    if not block:
        return None
    return f"{block}\n{marketdata.grounding_label(llm_name)}"


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
            model=get_model('gemini'),
            contents=prompt,
            config=config,
        )
        return response
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendRecommendationRequest: {e}")
        return None



def gemini_structured_config():
    """T8: Gemini analysis-call config — search grounding PLUS native
    structured output. Probe-verified 2026-07-18 (see
    tests/fixtures/structured_output/gemini.json): response_schema and the
    google_search tool coexist in one request; the schema must not carry
    additionalProperties. Discovery calls keep the plain grounded `config`.
    """
    return types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        response_mime_type="application/json",
        response_schema=voteschema.schema_for_gemini(),
    )


def sendCoinCheckRequest(coin, market_block=None):
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    # T9: market_block (Coinbase market data + fib + demoted trends + grounding)
    # is prepended as the PRIMARY data section when present.
    prefix = f"{market_block}\n\n" if market_block else ""

    try:
        followUpResponse = client.models.generate_content(
            model=get_model('gemini'),
            contents=f'{prefix}Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin} right now? {voteschema.schema_instruction(coin)}',
            config=gemini_structured_config(),
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendCoinCheckRequest for {coin}: {e}")
        return None





def sendTrendCheckRequest(coin, trends_data=None, market_block=None):
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    # T9: market_block prepended as the PRIMARY data section when present.
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

    try:
        followUpResponse = client.models.generate_content(
            model=get_model('gemini'),
            contents=f'{prefix}Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin} right now?{trends_section}{voteschema.schema_instruction(coin)}',
            config=gemini_structured_config(),
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendTrendCheckRequest for {coin}: {e}")
        return None


def sendIntegratedCoinCheckRequest(coin_symbol, peer_analysis, market_block=None):
    """Round 2: Check coin with peer LLM analysis as additional context."""
    if coin_symbol is None:
        return None
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    # T9: market_block prepended as the PRIMARY data section when present.
    prefix = f"{market_block}\n\n" if market_block else ""
    prompt = f"""{prefix}Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin_symbol} right now?

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

{voteschema.schema_instruction(coin_symbol)}"""

    try:
        followUpResponse = client.models.generate_content(
            model=get_model('gemini'),
            contents=prompt,
            config=gemini_structured_config(),
        )
        return followUpResponse
    except Exception as e:
        print(f"[ERROR] Gemini API error in sendIntegratedCoinCheckRequest for {coin_symbol}: {e}")
        return None


def sendIntegratedTrendCheckRequest(coin_symbol, peer_analysis, trends_data=None, market_block=None):
    """Round 2: Check coin with Google Trends + peer LLM analysis."""
    if coin_symbol is None:
        return None
    # Use "cryptocurrency" when coins are specified, "meme coin" for discovery mode
    coin_type = "cryptocurrency" if not USE_COIN_DISCOVERY else "meme coin"
    # T9: market_block prepended as the PRIMARY data section when present.
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

    prompt = f"""{prefix}Based on analysis of recent data from Google Trends, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the {coin_type} with symbol {coin_symbol} right now?
{trends_section}
Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{peer_analysis}
---END PEER ANALYSIS---

After reviewing the peer analysis and the Google Trends data provided, provide your final recommendation. You may agree, disagree, or refine your position based on this input.

{voteschema.schema_instruction(coin_symbol)}"""

    try:
        followUpResponse = client.models.generate_content(
            model=get_model('gemini'),
            contents=prompt,
            config=gemini_structured_config(),
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


def get_primary_coin_check(coin_symbol):
    """Get coin check from the PRIMARY_LLM.

    Text convention (T8): None = API failure; '' = responded with no visible
    text (maps to abstain(parse_failure) downstream).
    T9: the cached market block (with the primary's grounding line) is
    prepended as the PRIMARY data section.
    """
    global claude_trader, openai_trader, grok_trader, perplexity_trader

    if PRIMARY_LLM in FAILED_INIT_LLMS:
        # F1: the primary's client is dead. Return None (no Round-1 analysis)
        # instead of falling through to the Gemini substitution below — a
        # substituted response would be cross-fed and attributed to the
        # primary. The consensus layer records the standing abstain.
        print(f"[STANDING ABSTAIN] primary {PRIMARY_LLM}/{coin_symbol}: client "
              "failed to initialize at startup; skipping Round-1 analysis "
              "(no fallback substitution)")
        return None

    mb = _resolve_market_block(coin_symbol, PRIMARY_LLM)
    if PRIMARY_LLM == 'gemini':
        response = sendCoinCheckRequest(coin_symbol, market_block=mb)
        return (response.text or "") if response else None
    elif PRIMARY_LLM == 'claude' and claude_trader:
        return claude_trader.send_coin_check_request(coin_symbol, market_block=mb)
    elif PRIMARY_LLM == 'openai' and openai_trader:
        return openai_trader.send_coin_check_request(coin_symbol, market_block=mb)
    elif PRIMARY_LLM == 'grok' and grok_trader:
        return grok_trader.send_coin_check_request(coin_symbol, market_block=mb)
    elif PRIMARY_LLM == 'perplexity' and perplexity_trader:
        return perplexity_trader.send_coin_check_request(coin_symbol, market_block=mb)
    else:
        print(f"Warning: PRIMARY_LLM '{PRIMARY_LLM}' not available, falling back to Gemini")
        response = sendCoinCheckRequest(coin_symbol, market_block=_resolve_market_block(coin_symbol, 'gemini'))
        return (response.text or "") if response else None


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


import re

_TAG_RE = re.compile(r'<\*\*([^<>\n]*?)-PRS-(BUY|SELL|HOLD)\*\*>')


def _strip_quoted_examples(text):
    """Remove code-quoted regions so cited/example tags can't parse as real.

    Order matters: triple-backtick fenced blocks first (including an
    unterminated trailing fence — conservatively treated as quoted to EOF),
    then inline single-backtick spans. Replacement is a space, not '', so
    stripping can never splice two fragments into a fresh tag.
    """
    cleaned = re.sub(r'```.*?```', ' ', text, flags=re.DOTALL)
    cleaned = re.sub(r'```.*\Z', ' ', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'`[^`\n]*`', ' ', cleaned)
    return cleaned


def extract_tagged_vote(response_text):
    """Extract (symbol, action) from the CONCLUDING delimiter tag of an LLM
    response, or (None, None).

    This is the T8-hardened fallback parser (grok/perplexity still use it;
    the structured-output providers no longer do). Hardening, in order:
      - backtick spans AND triple-backtick fenced blocks are stripped, so a
        refusal citing the format as an example can't parse as real
        (EVALUATION_LESSONS_LEARNED §1.1 spent real money on exactly this);
      - only exact uppercase keywords in a well-formed tag count;
      - the LAST tag wins (the prompt asks models to CONCLUDE with the tag);
      - the last tag must actually conclude: any prose (letters) after it
        means it was cited mid-sentence ("the format would be <**..**> for a
        buy") rather than issued, and nothing parses. Trailing punctuation,
        whitespace, markdown asterisks, and bracketed citations are allowed.
    The tag's symbol prefix is returned for symbol binding at the
    resolve_vote layer; this function itself remains symbol-agnostic.
    """
    if not response_text:
        return None, None
    cleaned = _strip_quoted_examples(response_text)
    matches = list(_TAG_RE.finditer(cleaned))
    if not matches:
        return None, None
    last = matches[-1]
    if re.search(r'[A-Za-z]', cleaned[last.end():]):
        # Prose continues after the "concluding" tag: it was a citation, not
        # a recommendation. Fail closed (no parse -> abstain upstream).
        return None, None
    symbol = last.group(1).strip()
    return (symbol or None), last.group(2)


def extract_recommendation(response_text):
    """Extract a BUY/SELL/HOLD recommendation from an LLM response (the
    delimiter-tag fallback path). See extract_tagged_vote for the hardening
    rules; this wrapper keeps the historical action-only signature."""
    return extract_tagged_vote(response_text)[1]



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
        llm_name: 'gemini', 'claude', 'openai', 'grok', or 'perplexity'
        coin_symbol: The coin symbol to analyze
        use_trend_check: If True, use trend check; otherwise use coin check
        peer_analysis: Optional peer analysis for integration mode Round 2
        trends_data: Optional Google Trends data to include in prompt (integrate mode only)

    Returns:
        tuple: (response_text, rec) where response_text is None on API
        failure / '' when the model produced no visible text, and rec is
        'BUY'/'SELL'/'HOLD', a voteschema.Abstain (explicit refusal, parse
        failure, or symbol mismatch — see resolve_vote), or None.

    T9: the cached market block for `coin_symbol` (with this provider's
    grounding line attached) is prepended as the PRIMARY data section of every
    analysis prompt this dispatches — Round 1, Round 2, trend and coin checks.
    """
    if llm_name in FAILED_INIT_LLMS:
        # F1: this provider's client failed to construct at startup — it is a
        # standing abstain for every call this run, never a shrunken panel.
        print(f"[STANDING ABSTAIN] {llm_name}/{coin_symbol}: client failed to "
              "initialize at startup -> abstain(client_init_failure)")
        return None, voteschema.Abstain('client_init_failure')

    response_text = None
    mb = _resolve_market_block(coin_symbol, llm_name)

    # F7b: the market block already carries a demoted GOOGLE TRENDS
    # SECONDARY section (T9) whenever one is cached, so forwarding
    # trends_data into a trend-check builder ALONGSIDE a populated market
    # block would double-inject trends into the prompt (the provider utils'
    # send_trend_check_request/send_integrated_trend_check still accept
    # trends_data as a genuinely-used, independently-tested parameter --
    # see claudeutil.py etc. and tests/test_framing.py's trends-disclosure
    # coverage -- it is not vestigial there, so it is kept). use_trend_check
    # is never True from either live call site in main() today (T9 folded
    # trends into the block and both loops call process_coin_with_comparison
    # with the default use_trend_check=False), so this is currently a
    # no-observable-effect guard -- but it closes the path for any future or
    # direct caller that supplies both together.
    trend_data_for_prompt = None if mb else trends_data

    try:
        if llm_name == 'claude' and claude_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = claude_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = claude_trader.send_integrated_coin_check(coin_symbol, peer_analysis, market_block=mb)
            else:
                if use_trend_check:
                    response_text = claude_trader.send_trend_check_request(coin_symbol, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = claude_trader.send_coin_check_request(coin_symbol, market_block=mb)

        elif llm_name == 'openai' and openai_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = openai_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = openai_trader.send_integrated_coin_check(coin_symbol, peer_analysis, market_block=mb)
            else:
                if use_trend_check:
                    response_text = openai_trader.send_trend_check_request(coin_symbol, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = openai_trader.send_coin_check_request(coin_symbol, market_block=mb)

        elif llm_name == 'grok' and grok_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = grok_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = grok_trader.send_integrated_coin_check(coin_symbol, peer_analysis, market_block=mb)
            else:
                if use_trend_check:
                    response_text = grok_trader.send_trend_check_request(coin_symbol, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = grok_trader.send_coin_check_request(coin_symbol, market_block=mb)

        elif llm_name == 'perplexity' and perplexity_trader:
            if peer_analysis:
                if use_trend_check:
                    response_text = perplexity_trader.send_integrated_trend_check(coin_symbol, peer_analysis, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = perplexity_trader.send_integrated_coin_check(coin_symbol, peer_analysis, market_block=mb)
            else:
                if use_trend_check:
                    response_text = perplexity_trader.send_trend_check_request(coin_symbol, trend_data_for_prompt, market_block=mb)
                else:
                    response_text = perplexity_trader.send_coin_check_request(coin_symbol, market_block=mb)

        elif llm_name == 'gemini':
            if peer_analysis:
                if use_trend_check:
                    resp = sendIntegratedTrendCheckRequest(coin_symbol, peer_analysis, trend_data_for_prompt, market_block=mb)
                else:
                    resp = sendIntegratedCoinCheckRequest(coin_symbol, peer_analysis, market_block=mb)
                response_text = (resp.text or "") if resp else None
            else:
                if use_trend_check:
                    resp = sendTrendCheckRequest(coin_symbol, trend_data_for_prompt, market_block=mb)
                else:
                    resp = sendCoinCheckRequest(coin_symbol, market_block=mb)
                response_text = (resp.text or "") if resp else None
    except Exception as e:
        print(f"Error getting {llm_name} response: {e}")
        return None, None

    rec = resolve_vote(llm_name, response_text, coin_symbol)
    return response_text, rec


# === T8 structured-output migration (plan Phase 2) ===
#
# Analysis votes (Round 1, Round 2, and solo-mode checks) arrive as
# schema-enforced JSON from the native structured-output providers; grok and
# perplexity keep the delimiter-tag parser as a loudly-logged fallback.
# Discovery parsing (+++SYM+++) is untouched.

STRUCTURED_VOTE_PROVIDERS = ('gemini', 'claude', 'openai')


def resolve_vote(llm_name, response_text, coin_symbol):
    """Provider-aware vote resolution (T8).

    Returns one of:
      'BUY'/'SELL'/'HOLD'   — a validated, symbol-bound vote;
      voteschema.Abstain    — an explicit non-vote with a reason
                              ('refusal' | 'parse_failure' | 'symbol_mismatch');
      None                  — no response at all (the tallies' legacy
                              'error'/'parse_failure' mapping applies).

    Structured providers (gemini/claude/openai) parse JSON against the vote
    schema — a delimiter tag in their output no longer counts for anything.
    Fallback providers (grok/perplexity) use the hardened delimiter parser,
    with every parse loudly logged as [FALLBACK PARSER], plus the same
    conservative symbol binding applied to the tag's symbol prefix.
    """
    if response_text is None:
        return None
    if llm_name in STRUCTURED_VOTE_PROVIDERS:
        return voteschema.resolve_structured_vote(llm_name, response_text, coin_symbol)
    if not response_text.strip():
        return None  # empty fallback response: legacy mapping in the tallies
    print(f"[FALLBACK PARSER] {llm_name}/{coin_symbol}: structured output not "
          "enabled for this provider; parsing delimiter tag")
    tag_symbol, rec = extract_tagged_vote(response_text)
    if rec is None:
        # F6 instrumentation (measured 2026-07-18, semantics unchanged):
        # distinguish "well-formed tag present but trailing content followed
        # it" (the concluding-tag rule — a potential over-abstain IF the
        # trailing content is mere boilerplate) from "no tag at all". The
        # entire available grok/perplexity corpus (lab/session_tests_20260718
        # logs: 8 responses) had ZERO concluding-rule rejections — every
        # well-formed tag genuinely concluded its response — so the rule
        # stays fail-closed as-is; this loud line makes any future
        # over-abstain trivially countable from run logs.
        if _TAG_RE.search(_strip_quoted_examples(response_text)):
            print(f"[FALLBACK PARSER] {llm_name}/{coin_symbol}: tag present but "
                  "trailing content follows the concluding tag -> no vote "
                  "(concluding-tag rule; abstain(parse_failure) upstream)")
        return None  # no parseable concluding tag: legacy parse_failure mapping
    if coin_symbol and not voteschema.bind_symbol(tag_symbol, coin_symbol):
        print(f"[FALLBACK PARSER] {llm_name}/{coin_symbol}: tag symbol "
              f"{tag_symbol!r} does not bind to the coin under analysis "
              "-> abstain(symbol_mismatch)")
        return voteschema.Abstain('symbol_mismatch')
    print(f"[FALLBACK PARSER] {llm_name}/{coin_symbol}: {rec} "
          f"(tag symbol={tag_symbol!r} ok)")
    return rec


# === T3 consensus hardening (plan Phase 0): structured panel decisions ===

SINGLE_LLM_MODES = ('gemini', 'claude', 'openai', 'grok', 'perplexity')

# F1: providers whose API client failed to CONSTRUCT at startup, mapped to a
# short error detail. Populated only by main() (via register_client_init_failure)
# and cleared at the top of each run; empty on plain import. A provider in
# this registry REMAINS in the panel as a standing abstain('client_init_failure')
# for every coin analyzed — it appears in the votes dict, counts against
# quorum, and blocks under REQUIRE_CONSENSUS like any other abstain.
FAILED_INIT_LLMS = {}


def register_client_init_failure(llm_name, error):
    """F1: record a provider whose API client failed to construct at startup.

    Pre-F1, main() silently PRUNED the provider out of COMPARE_LLMS: the
    panelist vanished with no abstain recorded and the quorum shrank — the
    same fail-open class as the 2026-07-18 eval's finding 1.1, one layer up
    (llmpreflight only partially covers it: --skip-preflight and the whatif
    path left it open). Now the provider stays configured and every coin this
    run records it as a standing abstain('client_init_failure').

    Never raises. Returns the recorded error detail string.
    """
    detail = (f'{type(error).__name__}: {error}'
              if isinstance(error, BaseException) else str(error))
    FAILED_INIT_LLMS[llm_name] = detail
    print("!" * 66)
    print(f"[CLIENT INIT FAILURE] {llm_name}: client failed to initialize ({detail}).")
    print(f"[CLIENT INIT FAILURE] {llm_name} STAYS in the panel as a standing "
          "abstain(client_init_failure):")
    print("[CLIENT INIT FAILURE] it counts against quorum, blocks under "
          "REQUIRE_CONSENSUS, and can never vote this run.")
    print("!" * 66)
    return detail


@dataclass
class PanelDecision:
    """Structured result of process_coin_with_comparison (T3).

    Fields:
        action: 'BUY'/'SELL'/'HOLD', or None when there is no actionable
            decision (single-LLM abstain, or a blocked panel decision).
        consensus_state: 'unanimous' | 'tiebreaker' | 'single' | 'blocked'.
        votes: per-LLM final votes, abstains included as 'ABSTAIN(<reason>)'
            markers (e.g. {'gemini': 'BUY', 'openai': 'ABSTAIN(error)'}).
        abstains: {llm: reason} for panelists that did not produce a vote;
            reason is 'error' (API failure / no response / missing client),
            'parse_failure' (responded, but no parseable vote),
            'refusal' (structured abstain=true), 'symbol_mismatch' (voted on
            the wrong coin), or 'client_init_failure' (F1: the provider's
            client never constructed at startup — a standing abstain for the
            whole run).
        deciding_llms: the LLM(s) whose votes produced `action` (empty when
            blocked or abstained).
        majority_action: most common non-abstain vote (None on a tie or when
            nobody voted). Recorded for MEASUREMENT even when not traded.
        block_reason: why the decision was blocked ('<code>: detail'), else None.
    """
    action: Optional[str]
    consensus_state: str
    votes: Dict[str, str] = field(default_factory=dict)
    abstains: Dict[str, str] = field(default_factory=dict)
    deciding_llms: List[str] = field(default_factory=list)
    majority_action: Optional[str] = None
    block_reason: Optional[str] = None

    @property
    def consensus(self):
        """Legacy tri-state consensus flag (kept for history-record compat):
        True = unanimous panel, None = single-LLM (not applicable),
        False = anything else (tiebreaker-resolved or blocked)."""
        if self.consensus_state == 'unanimous':
            return True
        if self.consensus_state == 'single':
            return None
        return False

    @property
    def llm_source(self):
        """The actual deciding LLM(s) for history attribution (doc 5.2:
        llm_source used to lie by always naming the primary)."""
        return ','.join(self.deciding_llms) if self.deciding_llms else 'none'


def _majority_action(votes):
    """Most common vote among real (non-abstain) votes; None on a tie or
    when the list is empty. Measurement only — never a trade signal."""
    if not votes:
        return None
    top = Counter(votes).most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None
    return top[0][0]


def decision_allows_trade(decision, llm_mode, require_consensus):
    """Mode-aware trade gate (T3). Replaces the bare `'BUY' in final_action`
    check that ignored consensus entirely (doc 5.3.8).

    Truth table:
        single-LLM modes ............................ action alone decides
            (consensus is not applicable; a naive `consensus is True` gate
            would brick these modes)
        compare/integrate, REQUIRE_CONSENSUS ........ only a unanimous,
            abstain-free panel may trade
        compare/integrate, no REQUIRE_CONSENSUS ..... unanimous OR an explicit
            tiebreaker-resolved decision may trade
        blocked decisions ........................... never trade

    Policy: unanimity is required to TRADE under REQUIRE_CONSENSUS; the
    majority vote is recorded (majority_action) for MEASUREMENT only.
    """
    if decision is None or not decision.action:
        return False
    if llm_mode in SINGLE_LLM_MODES:
        return True
    if decision.consensus_state == 'unanimous':
        return True
    if decision.consensus_state == 'tiebreaker':
        return not require_consensus
    return False  # 'blocked' or anything unrecognized: fail closed


def validate_tiebreaker_config(tiebreaker, primary_llm, llm_mode):
    """T3(d) config validation: forbid tiebreaker == primary in multi-LLM
    modes by downgrading to 'none' with a loud warning (doc 1.2: the
    primary-as-tiebreaker overrode a 2-of-3 HOLD majority and bought ETH).
    Downgrades instead of hard-erroring because the shipped default config
    (primary=gemini, tiebreaker=gemini) has exactly this misconfiguration.
    """
    if llm_mode not in ('compare', 'integrate'):
        return tiebreaker
    if tiebreaker != 'none' and tiebreaker == primary_llm:
        print("!" * 66)
        print(f"[CONFIG WARNING] INTEGRATION_TIEBREAKER == PRIMARY_LLM ('{tiebreaker}').")
        print("[CONFIG WARNING] A primary-as-tiebreaker lets the primary override the")
        print("[CONFIG WARNING] panel on any split it is part of (2026-07-18 eval: a")
        print("[CONFIG WARNING] 2-of-3 HOLD majority was overridden and ETH was bought).")
        print("[CONFIG WARNING] Downgrading tiebreaker to 'none' for this run.")
        print("!" * 66)
        return 'none'
    return tiebreaker


def process_coin_with_comparison(coin_symbol, primary_response_text, use_trend_check=False, trends_data=None):
    """Process a coin recommendation with optional LLM comparison or integration.

    T3 fail-closed semantics (plan Phase 0): every LLM in COMPARE_LLMS ends up
    represented in the vote set — as a real vote or an explicit abstain
    ('error', 'parse_failure', 'refusal', 'symbol_mismatch', or F1's standing
    'client_init_failure'). Abstains are excluded from agreement math;
    under REQUIRE_CONSENSUS any abstain blocks. Sub-quorum, an unavailable
    tiebreaker, or an exception in the multi-LLM block all yield a BLOCKED
    decision — never a silent fallback to a lone or primary vote.

    Args:
        coin_symbol: The coin symbol to analyze
        primary_response_text: The full response text from PRIMARY_LLM Round 1
        use_trend_check: If True, use trend check; otherwise use coin check
        trends_data: Optional Google Trends data to include in integrate mode prompts

    Returns:
        PanelDecision (see its docstring for field semantics).
    """
    if coin_symbol is None:
        return PanelDecision(action=None, consensus_state='blocked',
                             block_reason='no_coin: coin_symbol is None')

    # Resolve PRIMARY_LLM's Round 1 vote (T8: provider-aware — structured
    # JSON for gemini/claude/openai, hardened delimiter fallback for the rest).
    # F1: a primary whose client failed to initialize is a standing abstain,
    # and any Round-1 text present is DISCARDED — it cannot have come from the
    # dead client (defense in depth against fallback substitution upstream).
    if PRIMARY_LLM in FAILED_INIT_LLMS:
        primary_response_text = None
        primary_rec = voteschema.Abstain('client_init_failure')
    else:
        primary_rec = resolve_vote(PRIMARY_LLM, primary_response_text, coin_symbol)

    # Single LLM modes - use the single LLM exclusively (consensus not applicable)
    if LLM_MODE in SINGLE_LLM_MODES:
        llm = LLM_MODE
        if llm in FAILED_INIT_LLMS:
            # F1: single-LLM mode with a dead client can never vote. Loud, and
            # returned as a BLOCKED (not 'single') decision so the call sites'
            # record gate (`final_action or state != 'single'`) WRITES it to
            # history — a failed run must never be a silent no-op.
            reason = (f'client_init_failure: {llm} client failed to '
                      f'initialize ({FAILED_INIT_LLMS[llm]})')
            print(f"  [BLOCKED] {coin_symbol}: {reason}")
            return PanelDecision(action=None, consensus_state='blocked',
                                 votes={llm: 'ABSTAIN(client_init_failure)'},
                                 abstains={llm: 'client_init_failure'},
                                 block_reason=reason)
        if PRIMARY_LLM == llm:
            resp_text, rec = primary_response_text, primary_rec
        else:
            resp_text, rec = get_llm_response(llm, coin_symbol, use_trend_check)
        if isinstance(rec, voteschema.Abstain):
            reason = rec.reason
        elif rec:
            action = rec.upper().strip()
            return PanelDecision(action=action, consensus_state='single',
                                 votes={llm: action}, deciding_llms=[llm],
                                 majority_action=action)
        else:
            reason = 'error' if not resp_text else 'parse_failure'
        return PanelDecision(action=None, consensus_state='single',
                             votes={llm: f'ABSTAIN({reason})'},
                             abstains={llm: reason})

    if LLM_MODE not in ('compare', 'integrate'):
        # Unknown mode: fail closed — never fall back to the primary's vote.
        return PanelDecision(action=None, consensus_state='blocked',
                             block_reason=f'unknown_llm_mode: {LLM_MODE}')

    # === COMPARE/INTEGRATE MODES: Multi-LLM ===
    try:
        # The panel is every LLM in COMPARE_LLMS (deduplicated, order kept).
        # T3(a) quorum enforcement: each panelist ends up as a real vote or an
        # explicit abstain — a missing client or API error is an abstain, not
        # a silently shrunken quorum (doc 1.1).
        panel = []
        for llm in COMPARE_LLMS:
            if llm not in panel:
                panel.append(llm)

        r1_responses = {}
        r1_votes = {}    # llm -> normalized real vote ('BUY'/'SELL'/'HOLD')
        r1_abstains = {}  # llm -> 'error' | 'parse_failure'

        def tally_round1(llm, resp, rec):
            if resp:
                r1_responses[llm] = resp
            if isinstance(rec, voteschema.Abstain):
                # T8: explicit structured abstains carry their own reason
                # ('refusal' | 'parse_failure' | 'symbol_mismatch')
                r1_abstains[llm] = rec.reason
            elif rec:
                r1_votes[llm] = rec.upper().strip()
            else:
                r1_abstains[llm] = 'error' if not resp else 'parse_failure'

        for llm in panel:
            if llm == PRIMARY_LLM:
                # PRIMARY_LLM already has a response from Round 1
                tally_round1(llm, primary_response_text, primary_rec)
                continue
            # Pass trends_data to Round 1 so all LLMs have the same data
            resp, rec = get_llm_response(llm, coin_symbol, use_trend_check, None, trends_data)
            tally_round1(llm, resp, rec)
            if resp and LOG_INTEGRATION_ROUNDS:
                print(f"\n--- {llm.capitalize()} Round 1 Response for {coin_symbol} ---")
                print(resp)

        def votes_display(votes, abstains):
            display = {}
            for llm in panel:
                if llm in votes:
                    display[llm] = votes[llm]
                elif llm in abstains:
                    display[llm] = f'ABSTAIN({abstains[llm]})'
            return display

        def decide(votes, abstains):
            """Resolve a final vote set into a PanelDecision (fail closed).

            Abstains are EXCLUDED from agreement math (no empty-string
            normalization), and under REQUIRE_CONSENSUS any abstain blocks.
            Policy: unanimity is required to TRADE under REQUIRE_CONSENSUS;
            majority_action is recorded for MEASUREMENT only.
            """
            display = votes_display(votes, abstains)
            majority = _majority_action(list(votes.values()))
            for llm, reason in abstains.items():
                print(f"  [ABSTAIN] {llm}: {reason}")

            def blocked(reason):
                print(f"  [BLOCKED] {coin_symbol}: {reason}")
                return PanelDecision(action=None, consensus_state='blocked',
                                     votes=display, abstains=dict(abstains),
                                     majority_action=majority,
                                     block_reason=reason)

            # T3(b): sub-quorum never yields a lone tradeable vote
            if len(votes) < 2:
                return blocked(f'sub_quorum: only {len(votes)} of {len(panel)} panelist(s) produced a vote')

            # T3(a): under REQUIRE_CONSENSUS every configured panelist must vote
            if REQUIRE_CONSENSUS and abstains:
                detail = ', '.join(f'{llm}({reason})' for llm, reason in abstains.items())
                return blocked(f'abstain: {detail}')

            if len(set(votes.values())) == 1:
                action = next(iter(votes.values()))
                return PanelDecision(action=action, consensus_state='unanimous',
                                     votes=display, abstains=dict(abstains),
                                     deciding_llms=[llm for llm in panel if llm in votes],
                                     majority_action=majority)

            # Non-unanimous panel
            if REQUIRE_CONSENSUS:
                # T3(e): honored in BOTH modes; the tiebreaker is never consulted
                return blocked('disagreement: no unanimous consensus (REQUIRE_CONSENSUS=true)')
            if INTEGRATION_TIEBREAKER == 'none':
                print("  [TIEBREAKER] No tiebreaker set, no action taken")
                return blocked('no_tiebreaker: split vote and no tiebreaker configured')
            if INTEGRATION_TIEBREAKER == PRIMARY_LLM:
                # Defense in depth: startup config validation downgrades this
                # to 'none'; if reached anyway, fail closed (doc 1.2).
                return blocked(f'tiebreaker_is_primary: {INTEGRATION_TIEBREAKER}')
            if INTEGRATION_TIEBREAKER not in votes:
                # T3(d): configured tiebreaker absent from the final vote set
                # blocks — no first-LLM fallback (doc 5.3.2)
                return blocked(f'tiebreaker_unavailable: {INTEGRATION_TIEBREAKER} did not produce a vote')
            action = votes[INTEGRATION_TIEBREAKER]
            print(f"  [TIEBREAKER] Using {INTEGRATION_TIEBREAKER} recommendation: {action}")
            return PanelDecision(action=action, consensus_state='tiebreaker',
                                 votes=display, abstains=dict(abstains),
                                 deciding_llms=[INTEGRATION_TIEBREAKER],
                                 majority_action=majority)

        # === COMPARE MODE ===
        if LLM_MODE == 'compare':
            print(f"\n[COMPARISON] " + ", ".join(f"{k}: {v}" for k, v in votes_display(r1_votes, r1_abstains).items()))
            return decide(r1_votes, r1_abstains)

        # === INTEGRATE MODE: Round 2 cross-feeding ===
        print(f"\n[INTEGRATE] Round 1 - " + ", ".join(f"{k}: {v}" for k, v in votes_display(r1_votes, r1_abstains).items()))

        # Fail fast (and cheap) before spending Round-2 API calls:
        # - fewer than 2 responders means there is nothing to cross-feed;
        # - under REQUIRE_CONSENSUS an error-abstainer never re-enters in
        #   Round 2 (only Round-1 responders are re-queried), so the decision
        #   is already guaranteed to block.
        r1_error_abstains = {llm for llm in r1_abstains if llm not in r1_responses}
        if len(r1_responses) < 2 or (REQUIRE_CONSENSUS and r1_error_abstains):
            return decide(r1_votes, r1_abstains)

        r2_votes = {}
        r2_abstains = {}
        for llm in panel:
            if llm not in r1_responses:
                # Errored out of Round 1: abstain carries into the final set
                r2_abstains[llm] = r1_abstains[llm]
                continue
            # Build peer analysis from other LLMs' Round-1 responses
            peer_analyses = []
            for other_llm, other_resp in r1_responses.items():
                if other_llm != llm:
                    peer_analyses.append(f"[{other_llm.upper()}]: {other_resp}")
            combined_peer = "\n\n".join(peer_analyses)

            resp, rec = get_llm_response(llm, coin_symbol, use_trend_check, combined_peer, trends_data)
            if isinstance(rec, voteschema.Abstain):
                r2_abstains[llm] = rec.reason
            elif rec:
                r2_votes[llm] = rec.upper().strip()
            else:
                r2_abstains[llm] = 'error' if not resp else 'parse_failure'

            if LOG_INTEGRATION_ROUNDS:
                print(f"\n--- {llm.capitalize()} Round 2 Response for {coin_symbol} ---")
                print(resp)

            # Track flips
            r1_val = r1_votes.get(llm)
            r2_val = r2_votes.get(llm)
            if r1_val != r2_val:
                print(f"  [FLIP] {llm.capitalize()} changed: {r1_val} -> {r2_val}")

        print(f"\n[INTEGRATE FINAL] " + ", ".join(f"{k}: {v}" for k, v in votes_display(r2_votes, r2_abstains).items()))
        return decide(r2_votes, r2_abstains)

    except Exception as e:
        # T3(f): an exception in the multi-LLM block blocks the decision —
        # never a silent fallback to the primary's solo vote (doc 5.3.4).
        print(f"Error in LLM processing for {coin_symbol}: {e}")
        print(f"  [BLOCKED] {coin_symbol}: exception in multi-LLM processing")
        return PanelDecision(action=None, consensus_state='blocked',
                             block_reason=f'exception: {e}')

# === T1 safe trading defaults (plan Phase 0) =================================
# Live-by-default was the headline footgun (EVALUATION_LESSONS_LEARNED §1.7):
# a bare `--trading-mode=live`, or an unset TRADING_MODE defaulting to live,
# could place real orders. T1 flips the default to whatif and double-locks
# live behind an explicit flag AND an env confirmation, makes the $5 notional
# configurable (with a hard ceiling), and adds a per-run spend cap.

NOTIONAL_CEILING_USD = 100.0  # refuse per-buy notional above this; $5-scale experiment


def resolve_trading_mode(args, env):
    """Resolve the effective trading mode, double-locking live trading.

    Pure function (no I/O) so the full truth table is unit-testable. Live is
    granted ONLY when BOTH locks are present:
        1. the explicit --live flag (args.live), AND
        2. env LIVE_TRADING_CONFIRMED == '1'.

    A "live request" is any of: --live, --trading-mode=live, or TRADING_MODE=live
    (the latter two both arrive as args.trading_mode == 'live'). A live request
    that is missing either lock is DOWNGRADED to whatif and returns a loud,
    specific notice. --trading-mode=live alone no longer suffices (breaking
    change); it merely counts as a request.

    Args:
        args: parsed argparse namespace (reads .live and .trading_mode).
        env:  a mapping like os.environ (reads LIVE_TRADING_CONFIRMED).

    Returns:
        (mode, notice) where mode is 'live' or 'whatif'. notice is None when
        no downgrade happened (granted live, or plain whatif with no live
        request); otherwise a multi-line str explaining exactly what is missing.
    """
    live_flag = bool(getattr(args, 'live', False))
    trading_mode = getattr(args, 'trading_mode', 'whatif')
    confirmed = env.get('LIVE_TRADING_CONFIRMED') == '1'
    requested_live = live_flag or trading_mode == 'live'

    if live_flag and confirmed:
        return 'live', None

    if requested_live:
        missing = []
        if not live_flag:
            missing.append('the --live flag')
        if not confirmed:
            missing.append('env LIVE_TRADING_CONFIRMED=1')
        notice = (
            "Live trading was REQUESTED but is NOT armed -- running in WHAT-IF instead.\n"
            "Live trading requires BOTH of:\n"
            "  1. the --live command-line flag, AND\n"
            "  2. the environment variable LIVE_TRADING_CONFIRMED=1\n"
            "Missing: " + ', '.join(missing) + ".\n"
            "(--trading-mode=live / TRADING_MODE=live alone no longer enables live trading.)"
        )
        return 'whatif', notice

    return 'whatif', None


def validate_notional(value):
    """Validate the per-buy notional (USD).

    Rules: must parse as a float, be strictly positive, and not exceed
    NOTIONAL_CEILING_USD. Returns the validated float; raises ValueError on any
    violation (startup turns this into a clean sys.exit).
    """
    try:
        notional = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"notional must be a number, got {value!r}")
    if notional <= 0:
        raise ValueError(f"notional must be positive, got {notional}")
    if notional > NOTIONAL_CEILING_USD:
        raise ValueError(
            f"notional ${notional:.2f} exceeds the ${NOTIONAL_CEILING_USD:.2f} ceiling "
            "(this is a $5-scale experiment; refusing)"
        )
    return notional


class SpendTracker:
    """Tracks cumulative intended spend across every buy in a run and enforces
    a per-run cap (T1).

    Counts what-if spend too, so the cap is exercised (and testable) without
    money. The exact-cap boundary is ALLOWED: a buy landing cumulative spend
    exactly on the cap goes through; a buy that would push it strictly over is
    refused and counted in `blocked`.
    """

    def __init__(self, cap, notional):
        self.cap = float(cap)
        self.notional = float(notional)
        self.spent = 0.0
        self.blocked = 0

    def try_spend(self, amount=None):
        """Attempt to commit `amount` (defaults to the run notional) against
        the cap. Returns True and records the spend if it fits (<= cap);
        returns False and increments `blocked` if it would exceed the cap."""
        amount = self.notional if amount is None else float(amount)
        if self.spent + amount > self.cap:
            self.blocked += 1
            return False
        self.spent += amount
        return True


def _current_ask(product):
    """Best available "current ask" for a product, for the what-if synthetic
    fill. The Coinbase Product type exposes `price` and `mid_market_price` but
    not a discrete ask, so we prefer an `ask` if present, then mid_market,
    then last price. Returns a float or None."""
    if product is None:
        return None
    for attr in ('ask', 'best_ask', 'mid_market_price', 'price'):
        val = getattr(product, attr, None)
        if val:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def buy_something(coinToBuy):
        """Place (or simulate) a BUY and write the execution-ledger rows (T5).

        Write-order sequence (crash-safe by construction): the INTENT row is
        written BEFORE any order is placed, so a crash between placing the order
        and confirming the fill leaves a reconcilable stub. Then:
          * what-if  -> a synthetic {status:'simulated', avg_fill_price:<ask>}
                        fill row (no real order placed);
          * live CEX -> market_order_buy returns a confirmed OrderResult (create
                        unwrapped + get_order polled); its fields become the
                        fill row (filled / failed / unconfirmed);
          * live DEX -> the DEX trader's own result maps to the same fill row.
        The deterministic client_order_id ties a retry to the same order.
        """
        product_id = coinToBuy + "-USD"
        print("\n--- Getting coin Product Details BEFORE for: ", product_id)

        usd_product = trader.get_product_details(product_id)
        if usd_product:
                print(json.dumps(usd_product.to_dict(), indent=2))
        else:
            print("Could not retrieve product details.")

        ask = _current_ask(usd_product)
        # Notional is configurable (T1); Coinbase's API takes a string, so we
        # format the float to 2 decimals (e.g. 5.00) at the call site.
        notional = NOTIONAL_USD
        quote_size = f'{notional:.2f}'
        client_order_id = BlobbyTrader.build_client_order_id(RUN_ID, coinToBuy, 'buy')

        # INTENT row first -- reconcilable if we crash before the fill row.
        ledger_id = executionledger.append_intent(
            run_id=RUN_ID,
            trading_mode=TRADING_MODE,
            coin=coinToBuy,
            intended_notional_usd=notional,
            client_order_id=client_order_id,
            side='BUY',
        )
        print(f"[LEDGER] intent {ledger_id}: BUY {coinToBuy} ${notional:.2f} "
              f"({TRADING_MODE}, client_order_id={client_order_id})")

        if WHATIF_MODE and not DEX_MODE:
            # Uniform record of both modes: a simulated fill at the current ask.
            executionledger.record_fill(
                ledger_id, status='simulated', avg_fill_price=ask)
            print(f"[WHAT-IF] Would execute BUY for {coinToBuy} (${notional:.2f}) "
                  f"@ ask {ask if ask is not None else 'unknown'}")
        elif DEX_MODE:
            # DEX handles whatif internally and returns a dict.
            result = trader.market_order_buy(product_id, quote_size, whatif=WHATIF_MODE)
            executed = bool(result and result.get('executed'))
            if WHATIF_MODE:
                executionledger.record_fill(
                    ledger_id, status='simulated', avg_fill_price=ask)
            elif executed:
                executionledger.record_fill(
                    ledger_id, status='filled',
                    order_id=(result.get('tx_signature') or result.get('tx_url')),
                    filled_size=result.get('base_amount') or result.get('out_amount'),
                    avg_fill_price=result.get('price') or ask,
                    fees_usd=result.get('fee_usd'))
            else:
                executionledger.record_fill(ledger_id, status='failed')
            if executed:
                print(f"[DEX] Trade executed: {result.get('tx_url', 'no tx')}")
        else:
            # LIVE CEX: structured, fill-confirmed result.
            result = trader.market_order_buy(
                product_id, quote_size, run_id=RUN_ID, coin=coinToBuy)
            executionledger.record_fill(
                ledger_id,
                status=result.ledger_status(),
                order_id=result.order_id,
                filled_size=result.filled_size,
                avg_fill_price=result.avg_fill_price,
                fees_usd=result.fees_usd)
            print(f"[LEDGER] fill {ledger_id}: {result.ledger_status()} "
                  f"(order_id={result.order_id}, size={result.filled_size}, "
                  f"avg={result.avg_fill_price}, fees={result.fees_usd})")

        print("\n--- Getting coin Product Details AFTER for: ", product_id)

        usd_product = trader.get_product_details(product_id)
        if usd_product:
                print(json.dumps(usd_product.to_dict(), indent=2))
        else:
            print("Could not retrieve product details.")


def maybe_execute_buy(coin_symbol):
    """Execute (or simulate) a gate-approved BUY under the spend caps.

    Called only after the mode-aware trade gate has approved a BUY. Two caps
    apply, checked BEFORE any order is placed:
      1. Daily LIVE cap (T5, live only): sum today's (UTC) live intent rows
         from the execution ledger; a live buy that would push the day's live
         spend past DAILY_SPEND_CAP_USD is refused with [DAILY CAP]. What-if
         does not consume this cap.
      2. Per-run cap (T1): the intended notional is committed to the shared
         SpendTracker (what-if spend counts too, so the cap is exercised
         without money); a buy that would exceed it is refused with [SPEND CAP]
         and tallied.
    A refused buy commits nothing. On approval, buy_something writes the ledger
    rows and (in live mode) places the order. Mutates coinsToBuy / whatif_buys.
    """
    global whatif_buys

    # 1. Daily LIVE spend cap (live only; ledger-backed, spans runs).
    if not WHATIF_MODE and executionledger.daily_cap_would_exceed(NOTIONAL_USD, DAILY_SPEND_CAP_USD):
        already = executionledger.live_spend_today()
        print(f"[DAILY CAP] BUY for {coin_symbol} refused: ${NOTIONAL_USD:.2f} would push "
              f"today's LIVE spend past the ${DAILY_SPEND_CAP_USD:.2f} daily cap "
              f"(${already:.2f} already committed today across all runs).")
        return

    # 2. Per-run spend cap (T1; counts what-if too).
    if not spend_tracker.try_spend(NOTIONAL_USD):
        print(f"[SPEND CAP] BUY for {coin_symbol} refused: ${NOTIONAL_USD:.2f} would push "
              f"run spend past the ${spend_tracker.cap:.2f} cap "
              f"(${spend_tracker.spent:.2f} already committed).")
        return

    coinsToBuy.append(coin_symbol)
    if not WHATIF_MODE and coin_symbol in coinsToExclude:
        # Excluded from live trading: no order, and no ledger rows (we never
        # intended to buy it). Still counted in coinsToBuy for the summary.
        print(f"[EXCLUDED] {coin_symbol} is on the exclude list; no order placed.")
        return

    buy_something(coin_symbol)
    if WHATIF_MODE:
        whatif_buys += 1



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


def get_active_llm_panel(llm_mode, primary_llm, compare_llms):
    """Return the ordered, de-duplicated list of LLM providers that will
    actually be called this run.

    compare/integrate modes call PRIMARY_LLM plus every provider in
    COMPARE_LLMS (PRIMARY_LLM first, since it runs Round 1). Solo modes
    (llm_mode is itself a provider name, e.g. 'claude') call only that
    one provider -- PRIMARY_LLM is not consulted in solo mode.
    """
    if llm_mode in ('compare', 'integrate'):
        panel = []
        for provider in [primary_llm] + list(compare_llms):
            if provider and provider not in panel:
                panel.append(provider)
        return panel
    return [llm_mode] if llm_mode else []


def format_preflight_line(provider, result):
    """Render one PreflightResult as a single output line."""
    if result.ok:
        latency = f"{result.latency_ms:.0f}ms" if result.latency_ms is not None else "n/a"
        return f"  [OK]   {provider:<12} model={result.model}  latency={latency}"
    model = result.model or "unknown"
    return f"  [FAIL] {provider:<12} model={model}  error={result.error}"


def run_llm_preflight(llm_mode, primary_llm, compare_llms, trading_mode, skip_preflight=False):
    """T6: preflight the active LLM panel before spending a full analysis
    cycle (Google Trends fetch, discovery, multi-round consensus) on a
    provider that is about to fail every call.

    Policy:
      - live mode: any preflight failure is a hard exit(1). A silently
        degraded panel in live mode can produce a false "consensus" from
        fewer LLMs than the operator configured (see
        EVALUATION_LESSONS_LEARNED_2026-07-18.md S1.5) -- that is worse
        than refusing to trade.
      - whatif mode: a failure prints a WARNING and the run continues, so
        a degraded panel remains testable (what-if is explicitly meant to
        mirror the live path even when a provider is unreachable).

    --skip-preflight (or SKIP_PREFLIGHT=true) bypasses the probe (and the
    live-mode hard-exit) entirely.

    Returns the raw {provider: PreflightResult} dict from
    llmpreflight.preflight() (empty dict if skipped or the panel is
    empty), so callers/tests can inspect exactly what was probed.
    """
    if skip_preflight:
        print("[PREFLIGHT] Skipped (--skip-preflight)")
        return {}

    panel = get_active_llm_panel(llm_mode, primary_llm, compare_llms)
    if not panel:
        return {}

    print("=== LLM PREFLIGHT ===")
    results = llmpreflight.preflight(panel)
    any_failed = False
    for provider in panel:
        result = results.get(provider)
        if result is None:
            continue
        if not result.ok:
            any_failed = True
        print(format_preflight_line(provider, result))
    print("=" * 50)

    if any_failed:
        if trading_mode == 'live':
            print(
                "[PREFLIGHT] LIVE mode requires every panel provider to pass "
                "preflight. Fix the failing provider(s) above, override its "
                "model via the *_MODEL env var (see MODELS.md), or rerun "
                "with --skip-preflight to bypass this check. Exiting."
            )
            sys.exit(1)
        else:
            print(
                "[PREFLIGHT] WARNING: one or more panel providers failed "
                "preflight. Continuing in what-if mode with a degraded panel."
            )

    return results


def resolve_analyze_coins_env(use_coin_discovery, analyze_coins):
    """T7: what main() should set os.environ['ANALYZE_COINS'] to (or None to
    leave it alone), given the already-resolved coin-selection state.

    The panel traders (claudeutil/openaiutil/grokutil/perplexityutil) each
    read the ANALYZE_COINS env var in __init__ to choose "cryptocurrency" vs
    "meme coin" prompt framing, but --coins never set that env var: an
    explicit `--coins=BTC` run still framed BTC as a "meme coin" for every
    provider except Gemini (crypto_trading_bot's own sendCoinCheckRequest /
    sendTrendCheckRequest read USE_COIN_DISCOVERY directly, so Gemini was
    already correct). Pure function so the resolution is unit-testable
    without constructing traders or touching the real environment.

    Discovery mode (use_coin_discovery=True) returns None: ANALYZE_COINS
    stays unset/empty and traders keep the "meme coin" framing, which matches
    discovery's actual domain (coin discovery only ever looks for meme
    coins -- see sendRecommendationRequest).
    """
    if use_coin_discovery:
        return None
    return ','.join(analyze_coins)


def main():
    """Run the trading bot end to end.

    All former top-level executable code lives here, in its original
    execution order, so that importing this module has no side effects:
    no argument parsing, no API-client or trader construction, and no
    network calls. The configuration values remain module-level globals
    (declared below and assigned here) because functions throughout this
    file read them at call time.
    """
    global args, pytrends
    global coinsToBuy, coinsToSell, coinsToHold
    global TRADING_MODE, WHATIF_MODE, LLM_MODE, PRIMARY_LLM, COMPARE_LLMS
    global REQUIRE_CONSENSUS, INTEGRATION_TIEBREAKER, LOG_INTEGRATION_ROUNDS
    global ANALYZE_COINS_RAW, ANALYZE_COINS, USE_COIN_DISCOVERY
    global CHAINS_RAW, CHAINS, CATEGORIES_RAW, CATEGORIES, POLYMARKET_FILTER
    global USE_COIN_FILTERING, DEX_MODE, discovery_default_used, DISCOVERY_RAW
    global DISCOVERY_METHODS, USE_LLM_DISCOVERY, USE_SANTIMENT_DISCOVERY
    global DEX_SLIPPAGE, TEST_WALLET, EXCHANGE_MODE
    global EXPORT_CANDIDATES, CANDIDATE_DIR, CANDIDATE_BLOCKCHAIN
    global EXPORT_RECOMMENDATIONS, RELAX_DISCOVERY_FAILURE
    global client, claude_trader, openai_trader, grok_trader, perplexity_trader
    global grounding_tool, config, coinsToExclude
    global whatif_buys, whatif_sells, trader
    global NOTIONAL_USD, RUN_SPEND_CAP_USD, spend_tracker, DAILY_SPEND_CAP_USD
    global RUN_ID

    # Parse command-line arguments
    args = parse_args()

    # Initialize pytrends with desired language and timezone

    # hl='en-US' for English (US), tz=360 for GMT-6 (Central Time)

    pytrends = TrendReq(hl='en-US', tz=360)

    coinsToBuy = []

    coinsToSell = []

    coinsToHold = []

    # Configuration from CLI args (with env var fallback)
    # T1: resolve the effective trading mode through the double lock. Any live
    # request that is not fully armed (--live AND LIVE_TRADING_CONFIRMED=1)
    # downgrades to whatif and returns a notice we print loudly below. Resolved
    # here (before trader construction) so a downgrade also disarms the DEX
    # wallet path, which keys off WHATIF_MODE.
    TRADING_MODE, live_downgrade_notice = resolve_trading_mode(args, os.environ)
    WHATIF_MODE = TRADING_MODE == 'whatif'

    # T2 (history integrity): one run_id per process invocation, shared by
    # every history record this run writes (and later joined against T5's
    # execution ledger / client_order_id). Generated once, here, right after
    # the trading mode is resolved so it can be logged alongside it.
    RUN_ID = 'run_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    if live_downgrade_notice:
        print("\n" + "!" * 66)
        for line in live_downgrade_notice.splitlines():
            print("[LIVE LOCK] " + line)
        print("!" * 66 + "\n")

    # T10: fire-and-forget history-summary analyzer pass. Imported lazily (so
    # `import crypto_trading_bot` stays side-effect-free) and fully guarded --
    # a summary must NEVER block trading. run_startup_summary is itself
    # non-fatal; the extra guard here covers an import failure too.
    if not getattr(args, 'skip_analyzer', False):
        try:
            import tradeanalyzer
            tradeanalyzer.run_startup_summary()
        except Exception as e:
            print(f"[ANALYZER] startup summary skipped (non-fatal): {e}")

    # T1: per-buy notional (default $5) and per-run spend cap (default $10).
    try:
        NOTIONAL_USD = validate_notional(args.notional_usd)
    except ValueError as e:
        print(f"[ERROR] Invalid --notional-usd / TRADE_NOTIONAL_USD: {e}")
        sys.exit(1)
    RUN_SPEND_CAP_USD = float(args.run_spend_cap_usd)
    if RUN_SPEND_CAP_USD < NOTIONAL_USD:
        print(f"[WARNING] Run spend cap ${RUN_SPEND_CAP_USD:.2f} is below the per-buy "
              f"notional ${NOTIONAL_USD:.2f}: NO buys can execute this run "
              "(every buy would exceed the cap).")
    spend_tracker = SpendTracker(RUN_SPEND_CAP_USD, NOTIONAL_USD)

    # T5: per-day LIVE spend cap, summed from the execution ledger across all
    # runs today (UTC). Enforced only for live buys (see maybe_execute_buy).
    DAILY_SPEND_CAP_USD = float(args.daily_spend_cap_usd)

    LLM_MODE = args.llm_mode
    PRIMARY_LLM = args.primary_llm
    COMPARE_LLMS = [llm.strip() for llm in args.compare_llms.split(',')]
    REQUIRE_CONSENSUS = args.require_consensus == 'true'
    INTEGRATION_TIEBREAKER = args.tiebreaker
    LOG_INTEGRATION_ROUNDS = args.log_rounds == 'true'

    # T3(d): tiebreaker == primary is forbidden in multi-LLM modes; downgrade
    # to 'none' with a loud warning (see validate_tiebreaker_config).
    INTEGRATION_TIEBREAKER = validate_tiebreaker_config(INTEGRATION_TIEBREAKER, PRIMARY_LLM, LLM_MODE)

    # Coin choice: specify coins directly instead of LLM discovery (max 5)
    ANALYZE_COINS_RAW = args.coins.strip()
    ANALYZE_COINS = [c.strip().upper() for c in ANALYZE_COINS_RAW.split(',') if c.strip()][:5]
    USE_COIN_DISCOVERY = len(ANALYZE_COINS) == 0
    if len([c.strip() for c in ANALYZE_COINS_RAW.split(',') if c.strip()]) > 5:
        print(f"Warning: --coins limited to 5 coins, ignoring extras")

    # T7: propagate --coins framing to the panel traders, before trader
    # construction below (see resolve_analyze_coins_env docstring).
    _analyze_coins_env = resolve_analyze_coins_env(USE_COIN_DISCOVERY, ANALYZE_COINS)
    if _analyze_coins_env is not None:
        os.environ['ANALYZE_COINS'] = _analyze_coins_env

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

    # === CLIENT INITIALIZATION ===
    # F1: a client that fails to construct NEVER shrinks the panel. The old
    # behavior pruned the provider out of COMPARE_LLMS (silently shrinking the
    # quorum — finding 1.1 one layer up) or crashed the run when it was the
    # primary/single provider. Every failure is now registered as a STANDING
    # abstain('client_init_failure'): the provider stays configured, every
    # coin records the abstain, and REQUIRE_CONSENSUS blocks on it. Live-mode
    # protection is unchanged — the preflight below still hard-exits on any
    # dead provider.
    FAILED_INIT_LLMS.clear()

    # Configure the Gemini client (also used by LLM discovery; its send_*
    # helpers all catch a dead/None client and return None -> abstain).
    try:
        client = genai.Client()
    except Exception as e:
        client = None
        print(f"Warning: Could not initialize Gemini client: {e}")
        register_client_init_failure('gemini', e)

    # Initialize Claude client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
    claude_trader = None
    if LLM_MODE == 'claude' or PRIMARY_LLM == 'claude' or (LLM_MODE in ['compare', 'integrate'] and 'claude' in COMPARE_LLMS):
        try:
            claude_trader = ClaudeTrader()
            print(f"Claude client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
        except Exception as e:
            print(f"Warning: Could not initialize Claude client: {e}")
            register_client_init_failure('claude', e)

    # Initialize OpenAI client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
    openai_trader = None
    if LLM_MODE == 'openai' or PRIMARY_LLM == 'openai' or (LLM_MODE in ['compare', 'integrate'] and 'openai' in COMPARE_LLMS):
        try:
            openai_trader = OpenAITrader()
            print(f"OpenAI client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
        except Exception as e:
            print(f"Warning: Could not initialize OpenAI client: {e}")
            register_client_init_failure('openai', e)

    # Initialize Grok client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
    grok_trader = None
    if LLM_MODE == 'grok' or PRIMARY_LLM == 'grok' or (LLM_MODE in ['compare', 'integrate'] and 'grok' in COMPARE_LLMS):
        try:
            grok_trader = GrokTrader()
            print(f"Grok client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
        except Exception as e:
            print(f"Warning: Could not initialize Grok client: {e}")
            register_client_init_failure('grok', e)

    # Initialize Perplexity client if needed (for single mode, compare/integrate, or as PRIMARY_LLM)
    perplexity_trader = None
    if LLM_MODE == 'perplexity' or PRIMARY_LLM == 'perplexity' or (LLM_MODE in ['compare', 'integrate'] and 'perplexity' in COMPARE_LLMS):
        try:
            perplexity_trader = PerplexityTrader()
            print(f"Perplexity client initialized (mode: {LLM_MODE}, primary: {PRIMARY_LLM})")
        except Exception as e:
            print(f"Warning: Could not initialize Perplexity client: {e}")
            register_client_init_failure('perplexity', e)



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

    # Show resolved trading mode (T1: governed by the --live / LIVE_TRADING_CONFIRMED
    # double lock, not --trading-mode alone).
    if WHATIF_MODE:
        print(f"Trading Mode: WHAT-IF (no real trades)")
        if live_downgrade_notice:
            print("  ^ live was requested but not armed -- see the [LIVE LOCK] notice above")
    else:
        print(f"Trading Mode: LIVE (trades will execute) [--live + LIVE_TRADING_CONFIRMED=1]")

    # T2: run_id shared by every history record this process writes.
    print(f"Run ID: {RUN_ID}")

    # Show trade sizing / spend cap
    print(f"Notional per buy: ${NOTIONAL_USD:.2f}")
    print(f"Run spend cap: ${RUN_SPEND_CAP_USD:.2f}")

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

    # === LLM PREFLIGHT (T6) ===
    # After config resolution, before any analysis: probe the active panel
    # only. Live-mode failures hard-exit here, before any Trends fetch,
    # discovery call, or Coinbase order is attempted.
    run_llm_preflight(LLM_MODE, PRIMARY_LLM, COMPARE_LLMS, TRADING_MODE, args.skip_preflight)

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

            # T9: build the real market-data block once for this coin
            # (Coinbase OHLCV summary + Fibonacci levels, plus demoted Google
            # Trends/CMC/SOCIAL SECONDARY sections). It becomes the PRIMARY
            # data section of EVERY analysis prompt (all providers, both
            # rounds), read from the cache inside get_primary_* /
            # get_llm_response. Trends is now injected per-coin via this
            # block — the old first-coin-only injection (use_trend = i == 0)
            # is gone (doc 3.1/5.1/5.7 #7).
            candle_client = None if DEX_MODE else getattr(trader, 'client', None)
            build_market_block_for_coin(coin_symbol, candle_client)

            # Get analysis from PRIMARY_LLM (market block prepended internally).
            followUpResponseText = get_primary_coin_check(coin_symbol)

            print(followUpResponseText)

            # T8: the primary vote is resolved provider-aware inside
            # process_coin_with_comparison (structured JSON for
            # gemini/claude/openai, [FALLBACK PARSER] for grok/perplexity) —
            # no delimiter pre-parse here anymore.
            print(f"[PRIMARY] {PRIMARY_LLM} response for {coin_symbol}: "
                  f"{len(followUpResponseText) if followUpResponseText else 0} chars")

            # Apply comparison/integration if enabled (the market block carries
            # the demoted trends signal, so no separate trends_data is threaded).
            decision = process_coin_with_comparison(coin_symbol, followUpResponseText)
            final_action = decision.action

            # Record the panel decision to history (discovery_llm=None since
            # coin was user-specified). Multi-LLM decisions are ALWAYS recorded
            # — blocked ones as action NONE — so the analyzer can measure panel
            # behavior; single-LLM probes keep recording only real actions
            # (except F1 client-init failures, which arrive as state='blocked'
            # and are therefore recorded — never a silent no-op).
            # llm_source is the actual deciding LLM(s), not the primary (T3).
            # T2: trading_mode/run_id let the analyzer separate live from
            # what-if experiments instead of scoring them as one stream.
            if final_action or decision.consensus_state != 'single':
                record_recommendation(
                    coin_symbol=coin_symbol,
                    recommendation=final_action or 'NONE',
                    trader=trader,
                    llm_source=decision.llm_source,
                    mode=LLM_MODE,
                    consensus=decision.consensus,
                    discovery_llm=None,
                    exchange=EXCHANGE_MODE,
                    export_candidate=EXPORT_CANDIDATES,
                    candidate_dir=CANDIDATE_DIR,
                    candidate_blockchain=CANDIDATE_BLOCKCHAIN,
                    export_recommendations=EXPORT_RECOMMENDATIONS,
                    consensus_state=decision.consensus_state,
                    deciding_llms=decision.deciding_llms,
                    votes=decision.votes,
                    block_reason=decision.block_reason,
                    majority_action=decision.majority_action,
                    trading_mode=TRADING_MODE,
                    run_id=RUN_ID
                )

            # T3(c) mode-aware trade gate: unanimity is required to TRADE under
            # REQUIRE_CONSENSUS; majority_action is recorded for MEASUREMENT only.
            if decision_allows_trade(decision, LLM_MODE, REQUIRE_CONSENSUS) and 'BUY' in final_action:
                maybe_execute_buy(coin_symbol)

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

            # T9: build the real market-data block once for this coin
            # (Coinbase OHLCV summary + Fibonacci levels, plus demoted Google
            # Trends/CMC/SOCIAL SECONDARY sections). PRIMARY data section for
            # EVERY analysis prompt, read from the cache inside
            # get_primary_* / get_llm_response. Trends is now per-coin via
            # this block — the old first-coin-only
            # injection (use_trend = i == 0) is gone (doc 3.1/5.1/5.7 #7).
            candle_client = None if DEX_MODE else getattr(trader, 'client', None)
            build_market_block_for_coin(coin_symbol, candle_client)

            # Get analysis from PRIMARY_LLM (market block prepended internally).
            followUpResponseText = get_primary_coin_check(coin_symbol)

            print(followUpResponseText)

            # T8: the primary vote is resolved provider-aware inside
            # process_coin_with_comparison (structured JSON for
            # gemini/claude/openai, [FALLBACK PARSER] for grok/perplexity) —
            # no delimiter pre-parse here anymore.
            print(f"[PRIMARY] {PRIMARY_LLM} response for {coin_symbol}: "
                  f"{len(followUpResponseText) if followUpResponseText else 0} chars")

            # Apply comparison/integration if enabled (the market block carries
            # the demoted trends signal, so no separate trends_data is threaded).
            decision = process_coin_with_comparison(coin_symbol, followUpResponseText)
            final_action = decision.action

            # Record the panel decision to history. Multi-LLM decisions are
            # ALWAYS recorded — blocked ones as action NONE — so the analyzer
            # can measure panel behavior; single-LLM probes keep recording only
            # real actions (except F1 client-init failures, which arrive as
            # state='blocked' and are therefore recorded — never a silent
            # no-op). llm_source is the actual deciding LLM(s) (T3).
            # T2: trading_mode/run_id let the analyzer separate live from
            # what-if experiments instead of scoring them as one stream.
            if final_action or decision.consensus_state != 'single':
                record_recommendation(
                    coin_symbol=coin_symbol,
                    recommendation=final_action or 'NONE',
                    trader=trader,
                    llm_source=decision.llm_source,
                    mode=LLM_MODE,
                    consensus=decision.consensus,
                    discovery_llm=discovery_source,
                    exchange=EXCHANGE_MODE,
                    export_candidate=EXPORT_CANDIDATES,
                    candidate_dir=CANDIDATE_DIR,
                    candidate_blockchain=CANDIDATE_BLOCKCHAIN,
                    export_recommendations=EXPORT_RECOMMENDATIONS,
                    consensus_state=decision.consensus_state,
                    deciding_llms=decision.deciding_llms,
                    votes=decision.votes,
                    block_reason=decision.block_reason,
                    majority_action=decision.majority_action,
                    trading_mode=TRADING_MODE,
                    run_id=RUN_ID
                )

            # T3(c) mode-aware trade gate: unanimity is required to TRADE under
            # REQUIRE_CONSENSUS; majority_action is recorded for MEASUREMENT only.
            if decision_allows_trade(decision, LLM_MODE, REQUIRE_CONSENSUS) and 'BUY' in final_action:
                maybe_execute_buy(coin_symbol)

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

    # Spend cap accounting (T1): committed intended spend + refusals
    print(f"Notional per buy: ${NOTIONAL_USD:.2f}")
    print(f"Run spend cap: ${RUN_SPEND_CAP_USD:.2f} "
          f"(committed ${spend_tracker.spent:.2f})")
    print(f"Blocked by spend cap: {spend_tracker.blocked}")

    # What-if summary
    if WHATIF_MODE:
        print("\n--- WHAT-IF SUMMARY ---")
        print(f"Simulated BUY orders: {whatif_buys}")
        print("No actual trades were executed.")
    print("="*50)


if __name__ == "__main__":
    main()
