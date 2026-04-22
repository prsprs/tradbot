"""
LunarCrush Utility - Coin categorization and filtering using LunarCrush API.

Provides category and blockchain filtering for cryptocurrency coins.
Supports both live API calls and cached data from coin_cache.json.

For live API calls:
    Requires LUNARCRUSH_API_KEY environment variable ($90/month or $5/day)

For cached data:
    Run refresh_coin_cache.py to generate coin_cache.json
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Set, Optional, Dict, Any, Tuple

import requests


# LunarCrush API configuration
LUNARCRUSH_API_KEY = os.environ.get('LUNARCRUSH_API_KEY', '')
BASE_URL = "https://lunarcrush.com/api4/public"

# Cache configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "coin_cache.json")


# =============================================================================
# CACHE FUNCTIONS
# =============================================================================

def cache_exists() -> bool:
    """Check if the coin cache file exists."""
    return os.path.isfile(CACHE_FILE)


def load_cache() -> Optional[Dict[str, Any]]:
    """Load the coin cache from disk.
    
    Returns:
        Cache dict with 'refreshed_at' and 'coins' keys, or None if not found.
    """
    if not cache_exists():
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARNING] Failed to load cache: {e}")
        return None


def get_cache_age() -> Optional[str]:
    """Get human-readable age of the cache.
    
    Returns:
        String like "2 days ago" or "3 hours ago", or None if cache doesn't exist.
    """
    cache = load_cache()
    if not cache or 'refreshed_at' not in cache:
        return None
    
    try:
        refreshed = datetime.fromisoformat(cache['refreshed_at'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        delta = now - refreshed
        
        days = delta.days
        hours = delta.seconds // 3600
        
        if days > 0:
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif hours > 0:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    except (ValueError, TypeError):
        return "unknown age"


def get_cache_timestamp() -> Optional[str]:
    """Get the ISO timestamp when cache was refreshed.
    
    Returns:
        ISO timestamp string, or None if cache doesn't exist.
    """
    cache = load_cache()
    if cache and 'refreshed_at' in cache:
        return cache['refreshed_at']
    return None


def filter_from_cache(coinbase_coins: List[str],
                      chains: Optional[List[str]] = None,
                      categories: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """Filter Coinbase coins using cached LunarCrush data.
    
    Args:
        coinbase_coins: List of coin symbols from Coinbase
        chains: List of blockchain networks to filter by (OR logic)
        categories: List of categories to filter by (OR logic)
        
    Returns:
        Tuple of (filtered_coins, skipped_coins):
            - filtered_coins: Coins matching the filter criteria
            - skipped_coins: Coins not in cache (for logging)
            
    Raises:
        FileNotFoundError: If cache file doesn't exist
    """
    cache = load_cache()
    if cache is None:
        raise FileNotFoundError(
            f"Cache file not found: {CACHE_FILE}\n"
            f"Run 'python refresh_coin_cache.py' to create it."
        )
    
    coins_data = cache.get("coins", {})
    cache_age = get_cache_age()
    
    print(f"\n=== CACHE-BASED FILTERING ===")
    print(f"Cache refreshed: {cache_age}")
    if chains:
        print(f"Chain filter: {chains}")
    if categories:
        print(f"Category filter: {categories}")
    
    filtered: List[str] = []
    skipped: List[str] = []
    
    for coin in coinbase_coins:
        symbol = coin.upper()
        
        # Check if coin is in cache
        if symbol not in coins_data:
            skipped.append(symbol)
            continue
        
        coin_info = coins_data[symbol]
        coin_categories = [c.lower() for c in coin_info.get("categories", [])]
        coin_blockchains = [b.lower() for b in coin_info.get("blockchains", [])]
        
        # Check category match (OR logic)
        category_match = True
        if categories:
            category_match = any(
                cat.lower() in coin_categories
                for cat in categories
            )
        
        # Check chain match (OR logic)
        chain_match = True
        if chains:
            chain_match = any(
                chain.lower() in coin_blockchains
                for chain in chains
            )
        
        # Include if matches both filters (when specified)
        if category_match and chain_match:
            filtered.append(coin)
    
    # Log results
    print(f"Coinbase coins: {len(coinbase_coins)}")
    print(f"After filtering: {len(filtered)}")
    
    if skipped:
        print(f"Skipped (not in cache): {len(skipped)}")
        if len(skipped) <= 10:
            print(f"  → {skipped}")
    
    print("=" * 30)
    
    return filtered, skipped


class LunarCrushClient:
    """Client for interacting with the LunarCrush API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the LunarCrush client.
        
        Args:
            api_key: LunarCrush API key. If not provided, uses LUNARCRUSH_API_KEY env var.
        
        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.api_key = api_key or LUNARCRUSH_API_KEY
        if not self.api_key:
            raise ValueError(
                "LUNARCRUSH_API_KEY environment variable required. "
                "Sign up at https://lunarcrush.com for API access (~$24/month)."
            )
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
    
    def get_coins(self, 
                  chains: Optional[List[str]] = None,
                  categories: Optional[List[str]] = None) -> Set[str]:
        """Get coin symbols filtered by chains and/or categories.
        
        Uses OR logic: coin matches ANY specified chain or category.
        
        Args:
            chains: List of blockchain networks (e.g., ['solana', 'base'])
            categories: List of categories (e.g., ['meme-coins', 'defi'])
            
        Returns:
            Set of coin symbols matching the specified filters.
            
        Raises:
            requests.exceptions.RequestException: If API request fails.
        """
        # Build params - use filter parameter for primary category if specified
        params: Dict[str, Any] = {"limit": 1000}
        if categories and len(categories) > 0:
            # LunarCrush supports filter parameter for categories
            params["filter"] = categories[0]  # Primary category filter
        
        all_coins: List[Dict] = []
        cursor: Optional[str] = None
        
        # Paginate through results
        while True:
            if cursor:
                params["cursor"] = cursor
            
            response = requests.get(
                f"{BASE_URL}/coins/list/v2",
                headers=self.headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            coins = data.get("data", [])
            all_coins.extend(coins)
            
            cursor = data.get("cursor")
            if not cursor or len(coins) == 0:
                break
        
        # Filter results based on chains and categories
        result: Set[str] = set()
        
        for coin in all_coins:
            symbol = coin.get("symbol", "").upper()
            if not symbol:
                continue
            
            # Parse coin's categories (comma-delimited string)
            coin_categories_raw = coin.get("categories", "")
            coin_categories = [c.strip().lower() for c in coin_categories_raw.split(",") if c.strip()]
            
            # Parse coin's blockchains (list of dicts with 'network' field)
            coin_blockchains = [
                b.get("network", "").lower() 
                for b in coin.get("blockchains", [])
                if b.get("network")
            ]
            
            # Check category match (OR logic - match ANY specified category)
            category_match = True
            if categories:
                category_match = any(
                    cat.lower() in coin_categories 
                    for cat in categories
                )
            
            # Check chain match (OR logic - match ANY specified chain)
            chain_match = True
            if chains:
                chain_match = any(
                    chain.lower() in coin_blockchains 
                    for chain in chains
                )
            
            # Include coin if it matches both filters (when specified)
            if category_match and chain_match:
                result.add(symbol)
        
        return result
    
    def get_available_categories(self) -> List[str]:
        """Get list of available category slugs from LunarCrush.
        
        Returns:
            List of category slug strings (e.g., ['meme-coins', 'defi', 'layer-1'])
        """
        response = requests.get(
            f"{BASE_URL}/categories/list/v1",
            headers=self.headers,
            timeout=30
        )
        response.raise_for_status()
        return [c.get("slug") for c in response.json().get("data", []) if c.get("slug")]
    
    def get_coin_details(self, symbol: str) -> Optional[Dict]:
        """Get detailed information for a specific coin.
        
        Args:
            symbol: Coin symbol (e.g., 'BTC', 'DOGE')
            
        Returns:
            Dictionary with coin details, or None if not found.
        """
        try:
            response = requests.get(
                f"{BASE_URL}/coins/{symbol.lower()}/v1",
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json().get("data")
        except requests.exceptions.RequestException:
            return None


# Module-level convenience functions

_client: Optional[LunarCrushClient] = None


def _get_client() -> LunarCrushClient:
    """Get or create a singleton LunarCrush client."""
    global _client
    if _client is None:
        _client = LunarCrushClient()
    return _client


def get_coins(chains: Optional[List[str]] = None,
              categories: Optional[List[str]] = None) -> Set[str]:
    """Get coin symbols filtered by chains and/or categories.
    
    Convenience wrapper around LunarCrushClient.get_coins().
    
    Args:
        chains: List of blockchain networks (e.g., ['solana', 'base'])
        categories: List of categories (e.g., ['meme-coins', 'defi'])
        
    Returns:
        Set of coin symbols matching the specified filters.
    """
    return _get_client().get_coins(chains=chains, categories=categories)


def get_available_categories() -> List[str]:
    """Get list of available category slugs from LunarCrush.
    
    Returns:
        List of category slug strings.
    """
    return _get_client().get_available_categories()


def filter_coinbase_coins(coinbase_coins: List[str],
                          chains: Optional[List[str]] = None,
                          categories: Optional[List[str]] = None) -> List[str]:
    """Filter a list of Coinbase coins by LunarCrush chains and/or categories.
    
    Args:
        coinbase_coins: List of coin symbols from Coinbase
        chains: List of blockchain networks to filter by
        categories: List of categories to filter by
        
    Returns:
        List of coins that match both Coinbase availability AND filter criteria.
    """
    if not chains and not categories:
        # No filtering requested
        return coinbase_coins
    
    try:
        lunarcrush_coins = get_coins(chains=chains, categories=categories)
        
        # Intersection: coins must be on Coinbase AND match LunarCrush filters
        coinbase_set = set(c.upper() for c in coinbase_coins)
        filtered = [c for c in coinbase_coins if c.upper() in lunarcrush_coins]
        
        # Log filtering results
        print(f"[LUNARCRUSH] Filter applied:")
        if chains:
            print(f"  Chains: {chains}")
        if categories:
            print(f"  Categories: {categories}")
        print(f"  LunarCrush matches: {len(lunarcrush_coins)}")
        print(f"  Coinbase coins: {len(coinbase_coins)}")
        print(f"  After filtering: {len(filtered)}")
        
        # Log which coins were filtered out
        removed = coinbase_set - set(c.upper() for c in filtered)
        if removed and len(removed) <= 20:
            print(f"  Filtered out: {sorted(removed)}")
        elif removed:
            print(f"  Filtered out: {len(removed)} coins")
        
        return filtered
        
    except ValueError as e:
        # No API key - fail with clear error per MVP decisions
        raise ValueError(f"LunarCrush filtering failed: {e}")
    except requests.exceptions.RequestException as e:
        # API error - fail with clear error per MVP decisions
        raise RuntimeError(f"LunarCrush API error: {e}")
