#!/usr/bin/env python3
"""
Refresh Coin Cache - Fetches Coinbase coins and enriches with category/blockchain data.

This script generates coin_cache.json which contains category and blockchain
information for all Coinbase-tradeable coins. Run this script periodically
(e.g., weekly) to keep the cache fresh.

Data Sources:
    --source=santiment   (default) Free API, single bulk GraphQL query
    --source=lunarcrush  Requires LUNARCRUSH_API_KEY, Builder plan ($300+/mo)

Usage:
    # Using LunarCrush (requires paid Builder plan)
    LUNARCRUSH_API_KEY=xxx python refresh_coin_cache.py --source=lunarcrush
    
    # Using Santiment (free)
    python refresh_coin_cache.py --source=santiment

Output:
    coin_cache.json in the same directory as this script
"""

import argparse
import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import requests

from coinbaseutil2 import BlobbyTrader

# Supported data sources
SOURCES = ['lunarcrush', 'santiment']


# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "coin_cache.json")
CACHE_BACKUP_FILE = os.path.join(SCRIPT_DIR, "coin_cache.backup.json")
LUNARCRUSH_API_KEY = os.environ.get('LUNARCRUSH_API_KEY', '')
LUNARCRUSH_BASE_URL = "https://lunarcrush.com/api4/public"


def get_coinbase_coins() -> List[str]:
    """Get all tradeable coin symbols from Coinbase."""
    print("Fetching Coinbase tradeable coins...")
    trader = BlobbyTrader()
    coins = trader.list_all_coins()
    print(f"  Found {len(coins)} coins on Coinbase")
    return coins


# =============================================================================
# LUNARCRUSH DATA SOURCE
# =============================================================================

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


# =============================================================================
# SANTIMENT DATA SOURCE
# =============================================================================

SANTIMENT_API_URL = "https://api.santiment.net/graphql"

def get_santiment_coins() -> Dict[str, Dict[str, Any]]:
    """Fetch all coins from Santiment with their categories and blockchains.
    
    Uses a single GraphQL bulk query to get all projects.
    
    Returns:
        Dict mapping symbol (ticker) to coin data (categories, blockchains)
    """
    print("Fetching Santiment coin data...")
    
    query = """
    {
        allProjects {
            slug
            name
            ticker
            marketSegments
            infrastructure
        }
    }
    """
    
    try:
        response = requests.post(
            SANTIMENT_API_URL,
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"\n[ERROR] Santiment API request failed: {e}")
        sys.exit(1)
    
    data = response.json()
    projects = data.get("data", {}).get("allProjects", [])
    
    all_coins: Dict[str, Dict[str, Any]] = {}
    
    for project in projects:
        ticker = project.get("ticker", "").upper()
        infrastructure = project.get("infrastructure")
        
        # Skip entries without ticker or infrastructure (e.g., ETFs)
        if not ticker or not infrastructure:
            continue
        
        # Skip if we already have this ticker (keep first match, usually highest market cap)
        if ticker in all_coins:
            continue
        
        # Parse categories from marketSegments
        segments = project.get("marketSegments", []) or []
        categories = [s.lower() for s in segments if s]
        
        # Parse blockchain from infrastructure
        blockchains = [infrastructure.lower()] if infrastructure else []
        
        all_coins[ticker] = {
            "name": project.get("name", ""),
            "slug": project.get("slug", ""),
            "categories": categories,
            "blockchains": blockchains
        }
    
    print(f"  Total Santiment coins: {len(all_coins)}")
    return all_coins


# =============================================================================
# CACHE BUILDING
# =============================================================================

def build_cache(coinbase_coins: List[str], source_data: Dict[str, Dict[str, Any]], source: str) -> Dict[str, Any]:
    """Build the cache combining Coinbase availability with source data.
    
    Args:
        coinbase_coins: List of symbols tradeable on Coinbase
        source_data: Dict of coin data keyed by symbol
        source: Name of the data source used
        
    Returns:
        Cache dict ready to write to JSON
    """
    print("\nBuilding cache...")
    
    coins_cache: Dict[str, Dict[str, Any]] = {}
    matched = 0
    unmatched = 0
    
    for symbol in coinbase_coins:
        symbol_upper = symbol.upper()
        
        if symbol_upper in source_data:
            src_data = source_data[symbol_upper]
            coins_cache[symbol_upper] = {
                "name": src_data["name"],
                "categories": src_data["categories"],
                "blockchains": src_data["blockchains"]
            }
            matched += 1
        else:
            # Coin on Coinbase but not in source - include with empty data
            coins_cache[symbol_upper] = {
                "name": symbol_upper,
                "categories": [],
                "blockchains": []
            }
            unmatched += 1
    
    print(f"  Matched in {source}: {matched}")
    print(f"  Not in {source}: {unmatched}")
    
    cache = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "coinbase_count": len(coinbase_coins),
        "matched": matched,
        "coins": coins_cache
    }
    
    return cache


def backup_existing_cache() -> bool:
    """Create a backup of the existing cache file before overwriting.
    
    Returns:
        True if backup was created, False if no existing cache to backup.
    """
    if not os.path.isfile(CACHE_FILE):
        return False
    
    try:
        # Copy current cache to backup
        with open(CACHE_FILE, 'r') as f:
            existing_cache = f.read()
        with open(CACHE_BACKUP_FILE, 'w') as f:
            f.write(existing_cache)
        print(f"Backed up existing cache to {CACHE_BACKUP_FILE}")
        return True
    except IOError as e:
        print(f"[WARNING] Failed to create backup: {e}")
        return False


def save_cache(cache: Dict[str, Any]) -> None:
    """Save cache to JSON file, creating a backup of any existing cache first."""
    # Create backup of existing cache before overwriting
    backup_existing_cache()
    
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)
    print(f"Saved to {CACHE_FILE}")


def print_summary(cache: Dict[str, Any]) -> None:
    """Print summary of cached data."""
    coins = cache["coins"]
    source = cache.get("source", "unknown")
    
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
    print(f"Source: {source}")
    print(f"Refreshed: {cache['refreshed_at']}")
    print(f"Total coins: {len(coins)}")
    print(f"Matched: {cache.get('matched', cache.get('lunarcrush_matched', 0))}")
    
    if category_counts:
        print(f"\nTop categories:")
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  {cat}: {count}")
    
    if chain_counts:
        print(f"\nTop blockchains:")
        for chain, count in sorted(chain_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  {chain}: {count}")
    
    print("="*50)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Refresh coin cache with category and blockchain data.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using Santiment (free, recommended)
  python refresh_coin_cache.py --source=santiment
  
  # Using LunarCrush (requires paid Builder plan)
  LUNARCRUSH_API_KEY=xxx python refresh_coin_cache.py --source=lunarcrush
"""
    )
    
    parser.add_argument(
        '--source',
        choices=SOURCES,
        default='santiment',
        help='Data source for category/blockchain info (default: santiment)'
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    source = args.source
    
    print("="*50)
    print("COIN CACHE REFRESH")
    print(f"Source: {source}")
    print("="*50 + "\n")
    
    # Step 1: Get Coinbase coins
    coinbase_coins = get_coinbase_coins()
    
    # Step 2: Get source data based on selected source
    if source == 'lunarcrush':
        source_data = get_lunarcrush_coins()
    elif source == 'santiment':
        source_data = get_santiment_coins()
    else:
        print(f"[ERROR] Unknown source: {source}")
        sys.exit(1)
    
    # Step 3: Build cache
    cache = build_cache(coinbase_coins, source_data, source)
    
    # Step 4: Save cache
    save_cache(cache)
    
    # Step 5: Print summary
    print_summary(cache)
    
    print("\nCache refresh complete!")
    print("You can now run the trading bot with --chains and --categories filters.")


if __name__ == "__main__":
    main()
