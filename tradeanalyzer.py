#!/usr/bin/env python3
"""
Trade Analyzer - Standalone program to analyze recommendation accuracy.

Reads historical recommendations from ./history/recommendations.json
and compares to current prices to determine correctness.

Usage:
    python tradeanalyzer.py

Output:
    - Console report with per-recommendation and summary statistics
    - CSV files: ./history/analysis_24h_YYYYMMDD.csv, ./history/analysis_midterm_YYYYMMDD.csv, ./history/analysis_7d_YYYYMMDD.csv
"""

import csv
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

from historyutil import load_recommendations, HISTORY_DIR, ensure_history_dir

# Try to import Coinbase client
try:
    from coinbaseutil2 import BlobbyTrader
    COINBASE_AVAILABLE = True
except ImportError:
    COINBASE_AVAILABLE = False
    print("Warning: coinbaseutil2 not available, will use CoinGecko only")

# Try to import CoinGecko fallback
try:
    from coingeckoutil import get_coingecko_price
    COINGECKO_AVAILABLE = True
except ImportError:
    COINGECKO_AVAILABLE = False
    print("Warning: coingeckoutil not available for fallback pricing")

# Try to import DEX Jupiter client for Solana prices
try:
    from dex.jupiterutil import JupiterClient
    JUPITER_AVAILABLE = True
except ImportError:
    JUPITER_AVAILABLE = False


def get_current_price(coin_symbol: str, trader=None, exchange: str = None) -> Optional[float]:
    """Get current price from appropriate exchange, fallback to CoinGecko.
    
    Args:
        coin_symbol: Coin symbol (e.g., 'DOGE', 'SHIB', 'BONK')
        trader: Optional BlobbyTrader instance for Coinbase
        exchange: Exchange type ('cex', 'solana-dex', or None for auto)
    
    Returns:
        Current price in USD, or None if unavailable.
    """
    # For DEX recommendations, try Jupiter first
    if exchange == 'solana-dex' and JUPITER_AVAILABLE:
        try:
            jupiter = JupiterClient()
            price_data = jupiter.get_price(coin_symbol)
            if price_data:
                return price_data[0]  # (price, bid, ask) tuple
        except Exception as e:
            print(f"Jupiter error for {coin_symbol}: {e}")
    
    # Try Coinbase for CEX or as fallback
    if trader and COINBASE_AVAILABLE:
        try:
            product = trader.get_product_details(f"{coin_symbol}-USD")
            if product and hasattr(product, 'price'):
                return float(product.price)
        except Exception as e:
            print(f"Coinbase error for {coin_symbol}: {e}")
    
    # Fallback to CoinGecko
    if COINGECKO_AVAILABLE:
        price = get_coingecko_price(coin_symbol)
        if price is not None:
            return price
    
    return None


def get_recommendations_in_window(recs: List[Dict], hours_ago_start: int, hours_ago_end: int) -> List[Dict]:
    """Get recommendations made within a time window.
    
    Args:
        recs: List of recommendation records
        hours_ago_start: Start of window (e.g., 24 means "24 hours ago")
        hours_ago_end: End of window (e.g., 48 means "48 hours ago")
    
    Returns:
        Recommendations made between hours_ago_end and hours_ago_start ago.
    """
    now = datetime.utcnow()
    window_start = now - timedelta(hours=hours_ago_end)
    window_end = now - timedelta(hours=hours_ago_start)
    
    result = []
    for rec in recs:
        try:
            rec_time = datetime.fromisoformat(rec['timestamp'].replace('Z', ''))
            if window_start <= rec_time <= window_end:
                result.append(rec)
        except (KeyError, ValueError) as e:
            print(f"Warning: Could not parse timestamp for record: {e}")
            continue
    return result


def calculate_outcome(recommendation: str, price_change_pct: float) -> Tuple[str, str]:
    """Determine outcome and display string for a recommendation.
    
    Args:
        recommendation: BUY, SELL, or HOLD
        price_change_pct: Percentage change in price since recommendation
    
    Returns:
        Tuple of (outcome, outcome_display) where outcome is CORRECT/INCORRECT/empty
    """
    sign = '+' if price_change_pct >= 0 else ''
    pct_str = f"{sign}{price_change_pct:.1f}%"
    
    recommendation = recommendation.upper().strip() if recommendation else ''
    
    if recommendation == 'HOLD':
        return ('', f"({pct_str})")
    elif recommendation == 'BUY':
        outcome = 'CORRECT' if price_change_pct > 0 else 'INCORRECT'
        return (outcome, f"{outcome.capitalize()} ({pct_str})")
    elif recommendation == 'SELL':
        outcome = 'CORRECT' if price_change_pct < 0 else 'INCORRECT'
        return (outcome, f"{outcome.capitalize()} ({pct_str})")
    return ('UNKNOWN', 'Unknown')


def analyze_recommendations(recs: List[Dict], trader=None) -> List[Dict]:
    """Analyze a list of recommendations against current prices.
    
    Args:
        recs: List of recommendation records to analyze
        trader: Optional BlobbyTrader instance for Coinbase
    
    Returns:
        List of analysis result dictionaries.
    """
    results = []
    
    for rec in recs:
        # Skip non-trading records (e.g., general LLM compare records)
        if 'coin_symbol' not in rec or 'price_at_recommendation' not in rec:
            continue
        
        coin = rec.get('coin_symbol', 'UNKNOWN')
        rec_price = rec.get('price_at_recommendation', 0)
        recommendation = rec.get('recommendation', 'UNKNOWN')
        exchange = rec.get('exchange', 'cex')  # Default to cex for legacy records
        
        current_price = get_current_price(coin, trader, exchange)
        
        if current_price is None or rec_price == 0:
            outcome = 'UNKNOWN'
            outcome_display = 'Unknown (price unavailable)'
            change_pct = 0.0
        else:
            change_pct = ((current_price - rec_price) / rec_price) * 100
            outcome, outcome_display = calculate_outcome(recommendation, change_pct)
        
        # Format timestamp for display
        timestamp_raw = rec.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(timestamp_raw.replace('Z', ''))
            timestamp_display = ts.strftime('%Y-%m-%d %H:%M UTC')
        except (ValueError, AttributeError):
            timestamp_display = timestamp_raw
        
        results.append({
            'recommendation_id': rec.get('id', ''),
            'timestamp': timestamp_raw,
            'coin': coin,
            'recommendation': recommendation,
            'rec_price': rec_price,
            'current_price': current_price if current_price else 0,
            'change_pct': f"{change_pct:.1f}%",
            'outcome': outcome,
            'outcome_display': outcome_display,
            'llm_source': rec.get('llm_source', ''),
            'mode': rec.get('mode', ''),
            'consensus': rec.get('consensus'),
            'exchange': exchange
        })
        
        # Print each result with timestamp
        print(f"{coin}, {recommendation.capitalize()}, {outcome_display}, {timestamp_display}")
    
    return results


def export_to_csv(results: List[Dict], filename: str) -> str:
    """Export analysis results to CSV file.
    
    Args:
        results: List of analysis result dictionaries
        filename: CSV filename (will be placed in HISTORY_DIR)
    
    Returns:
        Full path to the created CSV file.
    """
    ensure_history_dir()
    filepath = os.path.join(HISTORY_DIR, filename)
    fieldnames = ['recommendation_id', 'timestamp', 'coin', 'recommendation', 'rec_price', 
                  'current_price', 'change_pct', 'outcome', 'outcome_display',
                  'llm_source', 'mode', 'consensus', 'exchange']
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    return filepath


def print_summary(results: List[Dict], window_name: str) -> Tuple[int, int, int, int]:
    """Print summary statistics for a set of results.
    
    Args:
        results: List of analysis result dictionaries
        window_name: Name of the analysis window (e.g., "24-HOUR")
    
    Returns:
        Tuple of (buy_correct, buy_incorrect, sell_correct, sell_incorrect)
    """
    buy_correct = sum(1 for r in results if r['recommendation'] == 'BUY' and r['outcome'] == 'CORRECT')
    buy_incorrect = sum(1 for r in results if r['recommendation'] == 'BUY' and r['outcome'] == 'INCORRECT')
    buy_unknown = sum(1 for r in results if r['recommendation'] == 'BUY' and r['outcome'] == 'UNKNOWN')
    
    sell_correct = sum(1 for r in results if r['recommendation'] == 'SELL' and r['outcome'] == 'CORRECT')
    sell_incorrect = sum(1 for r in results if r['recommendation'] == 'SELL' and r['outcome'] == 'INCORRECT')
    sell_unknown = sum(1 for r in results if r['recommendation'] == 'SELL' and r['outcome'] == 'UNKNOWN')
    
    hold_total = sum(1 for r in results if r['recommendation'] == 'HOLD')
    
    buy_judged = buy_correct + buy_incorrect
    sell_judged = sell_correct + sell_incorrect
    
    print(f"\n--- {window_name} SUMMARY ---")
    if buy_judged > 0:
        accuracy = 100 * buy_correct / buy_judged
        print(f"BUY recommendations:  {buy_correct} correct, {buy_incorrect} incorrect, {buy_unknown} unknown ({accuracy:.1f}% accuracy)")
    else:
        print("BUY recommendations:  None in window")
    
    if sell_judged > 0:
        accuracy = 100 * sell_correct / sell_judged
        print(f"SELL recommendations: {sell_correct} correct, {sell_incorrect} incorrect, {sell_unknown} unknown ({accuracy:.1f}% accuracy)")
    else:
        print("SELL recommendations: None in window")
    
    if hold_total > 0:
        print(f"HOLD recommendations: {hold_total} total (no judgment)")
    
    return buy_correct, buy_incorrect, sell_correct, sell_incorrect


def print_llm_statistics(results: List[Dict]):
    """Print per-LLM accuracy statistics.
    
    Args:
        results: List of analysis result dictionaries
    """
    llm_stats = {}
    
    for r in results:
        llm = r.get('llm_source', 'unknown')
        if llm not in llm_stats:
            llm_stats[llm] = {'correct': 0, 'incorrect': 0, 'unknown': 0, 'hold': 0}
        
        if r['recommendation'] == 'HOLD':
            llm_stats[llm]['hold'] += 1
        elif r['outcome'] == 'CORRECT':
            llm_stats[llm]['correct'] += 1
        elif r['outcome'] == 'INCORRECT':
            llm_stats[llm]['incorrect'] += 1
        else:
            llm_stats[llm]['unknown'] += 1
    
    if llm_stats:
        print("\n--- PER-LLM STATISTICS ---")
        for llm, stats in sorted(llm_stats.items()):
            judged = stats['correct'] + stats['incorrect']
            if judged > 0:
                accuracy = 100 * stats['correct'] / judged
                print(f"{llm}: {stats['correct']}/{judged} correct ({accuracy:.1f}%), {stats['unknown']} unknown, {stats['hold']} hold")
            else:
                print(f"{llm}: No judged recommendations (hold: {stats['hold']}, unknown: {stats['unknown']})")


def print_mode_statistics(results: List[Dict]):
    """Print per-mode accuracy statistics.
    
    Args:
        results: List of analysis result dictionaries
    """
    mode_stats = {}
    
    for r in results:
        mode = r.get('mode', 'unknown')
        if mode not in mode_stats:
            mode_stats[mode] = {'correct': 0, 'incorrect': 0, 'unknown': 0, 'hold': 0}
        
        if r['recommendation'] == 'HOLD':
            mode_stats[mode]['hold'] += 1
        elif r['outcome'] == 'CORRECT':
            mode_stats[mode]['correct'] += 1
        elif r['outcome'] == 'INCORRECT':
            mode_stats[mode]['incorrect'] += 1
        else:
            mode_stats[mode]['unknown'] += 1
    
    if mode_stats:
        print("\n--- PER-MODE STATISTICS ---")
        for mode, stats in sorted(mode_stats.items()):
            judged = stats['correct'] + stats['incorrect']
            if judged > 0:
                accuracy = 100 * stats['correct'] / judged
                print(f"{mode}: {stats['correct']}/{judged} correct ({accuracy:.1f}%), {stats['unknown']} unknown, {stats['hold']} hold")
            else:
                print(f"{mode}: No judged recommendations (hold: {stats['hold']}, unknown: {stats['unknown']})")


def print_exchange_statistics(results: List[Dict]):
    """Print per-exchange accuracy statistics (CEX vs DEX).
    
    Args:
        results: List of analysis result dictionaries
    """
    exchange_stats = {}
    
    for r in results:
        exchange = r.get('exchange', 'cex')
        if exchange not in exchange_stats:
            exchange_stats[exchange] = {'correct': 0, 'incorrect': 0, 'unknown': 0, 'hold': 0}
        
        if r['recommendation'] == 'HOLD':
            exchange_stats[exchange]['hold'] += 1
        elif r['outcome'] == 'CORRECT':
            exchange_stats[exchange]['correct'] += 1
        elif r['outcome'] == 'INCORRECT':
            exchange_stats[exchange]['incorrect'] += 1
        else:
            exchange_stats[exchange]['unknown'] += 1
    
    if exchange_stats:
        print("\n--- PER-EXCHANGE STATISTICS ---")
        for exchange, stats in sorted(exchange_stats.items()):
            judged = stats['correct'] + stats['incorrect']
            if judged > 0:
                accuracy = 100 * stats['correct'] / judged
                print(f"{exchange}: {stats['correct']}/{judged} correct ({accuracy:.1f}%), {stats['unknown']} unknown, {stats['hold']} hold")
            else:
                print(f"{exchange}: No judged recommendations (hold: {stats['hold']}, unknown: {stats['unknown']})")


def main():
    """Main entry point for trade analyzer."""
    print("=== TRADING BOT ANALYSIS REPORT ===")
    print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    # Initialize Coinbase client for price fetching
    trader = None
    if COINBASE_AVAILABLE:
        try:
            trader = BlobbyTrader()
        except Exception as e:
            print(f"Warning: Could not initialize Coinbase client: {e}")
            print("Price fetching may be limited to CoinGecko fallback.")
    
    # Load all recommendations
    all_recs = load_recommendations()
    if not all_recs:
        print("\nNo recommendations found in history.")
        print(f"Expected file: {os.path.abspath(os.path.join(HISTORY_DIR, 'recommendations.json'))}")
        print("\nTo generate history, run the trading bot (crypto_trading_bot.py)")
        print("Recommendations will be recorded automatically.")
        return
    
    print(f"\nTotal recommendations in history: {len(all_recs)}")
    
    # Track overall stats
    total_buy_correct = 0
    total_buy_incorrect = 0
    total_sell_correct = 0
    total_sell_incorrect = 0
    all_results = []
    
    # 24-hour analysis (recs from 24-48 hours ago)
    print("\n" + "="*50)
    print("=== 24-HOUR ANALYSIS (recs from 24-48 hrs ago) ===")
    recs_24h = get_recommendations_in_window(all_recs, 24, 48)
    print(f"Recommendations found: {len(recs_24h)}\n")
    
    csv_24h = None
    if recs_24h:
        results_24h = analyze_recommendations(recs_24h, trader)
        bc, bi, sc, si = print_summary(results_24h, "24-HOUR")
        total_buy_correct += bc
        total_buy_incorrect += bi
        total_sell_correct += sc
        total_sell_incorrect += si
        all_results.extend(results_24h)
        
        csv_24h = export_to_csv(results_24h, f"analysis_24h_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    else:
        print("No recommendations in this window.")
    
    # Mid-term analysis (recs from 2-7 days ago)
    print("\n" + "="*50)
    print("=== MID-TERM ANALYSIS (recs from 2-7 days ago) ===")
    recs_midterm = get_recommendations_in_window(all_recs, 48, 168)  # 2*24=48, 7*24=168
    print(f"Recommendations found: {len(recs_midterm)}\n")
    
    csv_midterm = None
    if recs_midterm:
        results_midterm = analyze_recommendations(recs_midterm, trader)
        bc, bi, sc, si = print_summary(results_midterm, "MID-TERM")
        total_buy_correct += bc
        total_buy_incorrect += bi
        total_sell_correct += sc
        total_sell_incorrect += si
        all_results.extend(results_midterm)
        
        csv_midterm = export_to_csv(results_midterm, f"analysis_midterm_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    else:
        print("No recommendations in this window.")
    
    # 7-day analysis (recs from 7-8 days ago)
    print("\n" + "="*50)
    print("=== 7-DAY ANALYSIS (recs from 7-8 days ago) ===")
    recs_7d = get_recommendations_in_window(all_recs, 168, 192)  # 7*24=168, 8*24=192
    print(f"Recommendations found: {len(recs_7d)}\n")
    
    csv_7d = None
    if recs_7d:
        results_7d = analyze_recommendations(recs_7d, trader)
        bc, bi, sc, si = print_summary(results_7d, "7-DAY")
        total_buy_correct += bc
        total_buy_incorrect += bi
        total_sell_correct += sc
        total_sell_incorrect += si
        all_results.extend(results_7d)
        
        csv_7d = export_to_csv(results_7d, f"analysis_7d_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    else:
        print("No recommendations in this window.")
    
    # Per-LLM, per-mode, and per-exchange statistics (if we have results)
    if all_results:
        print_llm_statistics(all_results)
        print_mode_statistics(all_results)
        print_exchange_statistics(all_results)
    
    # Overall accuracy
    print("\n" + "="*50)
    print("=== OVERALL ACCURACY ===")
    
    total_buy = total_buy_correct + total_buy_incorrect
    total_sell = total_sell_correct + total_sell_incorrect
    
    if total_buy > 0:
        print(f"BUY:  {total_buy_correct} correct / {total_buy} judged ({100*total_buy_correct/total_buy:.1f}%)")
    else:
        print("BUY:  No judged recommendations")
        
    if total_sell > 0:
        print(f"SELL: {total_sell_correct} correct / {total_sell} judged ({100*total_sell_correct/total_sell:.1f}%)")
    else:
        print("SELL: No judged recommendations")
    
    # Report CSV files
    print("\nCSV files written:")
    if csv_24h:
        print(f"  {csv_24h}")
    if csv_midterm:
        print(f"  {csv_midterm}")
    if csv_7d:
        print(f"  {csv_7d}")
    if not csv_24h and not csv_midterm and not csv_7d:
        print("  (none - no recommendations in analysis windows)")


if __name__ == "__main__":
    main()
