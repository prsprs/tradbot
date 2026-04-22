#!/usr/bin/env python3
"""
Refresh Coin Cache - Fetches Coinbase coins and enriches with LunarCrush data.

This script generates coin_cache.json which contains category and blockchain
information for all Coinbase-tradeable coins. Run this script periodically
(e.g., weekly) to keep the cache fresh.

Requires:
    LUNARCRUSH_API_KEY environment variable

Usage:
    LUNARCRUSH_API_KEY=xxx python refresh_coin_cache.py

Output:
    coin_cache.json in the same directory as this script
"""

import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import requests

from coinbaseutil2 import BlobbyTrader


# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "coin_cache.json")
LUNARCRUSH_API_KEY = os.environ.get('LUNARCRUSH_API_KEY', '')
LUNARCRUSH_BASE_URL = "https://lunarcrush.com/api4/public"


def get_coinbase_coins() -> List[str]:
    """Get all tradeable coin symbols from Coinbase."""
    print("Fetching Coinbase tradeable coins...")
    trader = BlobbyTrader()
    coins = trader.list_all_coins()
    print(f"  Found {len(coins)} coins on Coinbase")
    return coins


def get_lunarcrush_coins() -> Dict[str, Dict[str, Any]]:
    """Fetch all coins from LunarCrush with their categories and blockchains.
    
    Returns:
        Dict mapping symbol to coin data (categories, blockchains)
    """
    if not LUNARCRUSH_API_KEY:
        print("\n[ERROR] LUNARCRUSH_API_KEY environment variable required.")
        print("Sign up at https://lunarcrush.com for API access.")
        print("Try promo code ARCH30 for 30% off.")
        sys.exit(1)
    
    headers = {"Authorization": f"Bearer {LUNARCRUSH_API_KEY}"}
    params: Dict[str, Any] = {"limit": 1000}
    
    all_coins: Dict[str, Dict[str, Any]] = {}
    cursor: Optional[str] = None
    page = 1
    
    print("Fetching LunarCrush coin data...")
    
    while True:
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = requests.get(
                f"{LUNARCRUSH_BASE_URL}/coins/list/v2",
                headers=headers,
                params=params,
                timeout=60
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"\n[ERROR] LunarCrush API request failed: {e}")
            sys.exit(1)
        
        data = response.json()
        coins = data.get("data", [])
        
        for coin in coins:
            symbol = coin.get("symbol", "").upper()
            if not symbol:
                continue
            
            # Parse categories (comma-delimited string)
            categories_raw = coin.get("categories", "")
            categories = [c.strip().lower() for c in categories_raw.split(",") if c.strip()]
            
            # Parse blockchains (list of dicts with 'network' field)
            blockchains = [
                b.get("network", "").lower()
                for b in coin.get("blockchains", [])
                if b.get("network")
            ]
            
            all_coins[symbol] = {
                "name": coin.get("name", ""),
                "categories": categories,
                "blockchains": blockchains
            }
        
        print(f"  Page {page}: {len(coins)} coins (total: {len(all_coins)})")
        
        cursor = data.get("cursor")
        if not cursor or len(coins) == 0:
            break
        
        page += 1
    
    print(f"  Total LunarCrush coins: {len(all_coins)}")
    return all_coins


def build_cache(coinbase_coins: List[str], lunarcrush_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Build the cache combining Coinbase availability with LunarCrush data.
    
    Args:
        coinbase_coins: List of symbols tradeable on Coinbase
        lunarcrush_data: Dict of LunarCrush coin data keyed by symbol
        
    Returns:
        Cache dict ready to write to JSON
    """
    print("\nBuilding cache...")
    
    coins_cache: Dict[str, Dict[str, Any]] = {}
    matched = 0
    unmatched = 0
    
    for symbol in coinbase_coins:
        symbol_upper = symbol.upper()
        
        if symbol_upper in lunarcrush_data:
            lc_data = lunarcrush_data[symbol_upper]
            coins_cache[symbol_upper] = {
                "name": lc_data["name"],
                "categories": lc_data["categories"],
                "blockchains": lc_data["blockchains"]
            }
            matched += 1
        else:
            # Coin on Coinbase but not in LunarCrush - include with empty data
            coins_cache[symbol_upper] = {
                "name": symbol_upper,
                "categories": [],
                "blockchains": []
            }
            unmatched += 1
    
    print(f"  Matched in LunarCrush: {matched}")
    print(f"  Not in LunarCrush: {unmatched}")
    
    cache = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "coinbase_count": len(coinbase_coins),
        "lunarcrush_matched": matched,
        "coins": coins_cache
    }
    
    return cache


def save_cache(cache: Dict[str, Any]) -> None:
    """Save cache to JSON file."""
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)
    print(f"\nSaved to {CACHE_FILE}")


def print_summary(cache: Dict[str, Any]) -> None:
    """Print summary of cached data."""
    coins = cache["coins"]
    
    # Count by category
    category_counts: Dict[str, int] = {}
    for coin_data in coins.values():
        for cat in coin_data.get("categories", []):
            category_counts[cat] = category_counts.get(cat, 0) + 1
    
    # Count by blockchain
    chain_counts: Dict[str, int] = {}
    for coin_data in coins.values():
        for chain in coin_data.get("blockchains", []):
            chain_counts[chain] = chain_counts.get(chain, 0) + 1
    
    print("\n" + "="*50)
    print("CACHE SUMMARY")
    print("="*50)
    print(f"Refreshed: {cache['refreshed_at']}")
    print(f"Total coins: {len(coins)}")
    print(f"Matched with LunarCrush: {cache['lunarcrush_matched']}")
    
    if category_counts:
        print(f"\nTop categories:")
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  {cat}: {count}")
    
    if chain_counts:
        print(f"\nTop blockchains:")
        for chain, count in sorted(chain_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  {chain}: {count}")
    
    print("="*50)


def main():
    """Main entry point."""
    print("="*50)
    print("COIN CACHE REFRESH")
    print("="*50 + "\n")
    
    # Step 1: Get Coinbase coins
    coinbase_coins = get_coinbase_coins()
    
    # Step 2: Get LunarCrush data
    lunarcrush_data = get_lunarcrush_coins()
    
    # Step 3: Build cache
    cache = build_cache(coinbase_coins, lunarcrush_data)
    
    # Step 4: Save cache
    save_cache(cache)
    
    # Step 5: Print summary
    print_summary(cache)
    
    print("\nCache refresh complete!")
    print("You can now run the trading bot with --chains and --categories filters.")


if __name__ == "__main__":
    main()
