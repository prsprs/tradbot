"""
CoinGecko Utility - Fallback price fetcher using CoinGecko API.

Provides price data when Coinbase is unavailable for a particular coin.
Uses the free CoinGecko API by default, or a pro API key if provided.
"""

import os
import time
from typing import Optional, Dict

# Optional API key for CoinGecko Pro
COINGECKO_API_KEY = os.environ.get('COINGECKO_API_KEY', '')

# Rate limiting - CoinGecko free tier is strict (~10-30 calls/minute)
_last_request_time = 0
_min_request_interval = 6.0  # seconds between requests (conservative for free tier)


# Common coin symbol to CoinGecko ID mapping
SYMBOL_TO_ID = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'DOGE': 'dogecoin',
    'SHIB': 'shiba-inu',
    'PEPE': 'pepe',
    'BONK': 'bonk',
    'FLOKI': 'floki',
    'WIF': 'dogwifcoin',
    'SOL': 'solana',
    'XRP': 'ripple',
    'ADA': 'cardano',
    'AVAX': 'avalanche-2',
    'DOT': 'polkadot',
    'MATIC': 'matic-network',
    'LINK': 'chainlink',
    'UNI': 'uniswap',
    'LTC': 'litecoin',
    'BCH': 'bitcoin-cash',
    'ATOM': 'cosmos',
    'FIL': 'filecoin',
    'APT': 'aptos',
    'ARB': 'arbitrum',
    'OP': 'optimism',
    'NEAR': 'near',
    'IMX': 'immutable-x',
    'INJ': 'injective-protocol',
    'SUI': 'sui',
    'SEI': 'sei-network',
    'TIA': 'celestia',
    'JUP': 'jupiter-exchange-solana',
    'RENDER': 'render-token',
    'FET': 'fetch-ai',
    'RNDR': 'render-token',
    'GRT': 'the-graph',
    'MANA': 'decentraland',
    'SAND': 'the-sandbox',
    'AXS': 'axie-infinity',
    'APE': 'apecoin',
    'CRV': 'curve-dao-token',
    'MKR': 'maker',
    'AAVE': 'aave',
    'COMP': 'compound-governance-token',
    'SNX': 'havven',
    'YFI': 'yearn-finance',
    'SUSHI': 'sushi',
    '1INCH': '1inch',
    'ENS': 'ethereum-name-service',
    'LDO': 'lido-dao',
    'RPL': 'rocket-pool',
    'BLUR': 'blur',
    'MAGIC': 'magic',
    'GMX': 'gmx',
    'PENDLE': 'pendle',
    'STX': 'blockstack',
    'CFX': 'conflux-token',
    'MEME': 'meme-coin',
    'TURBO': 'turbo',
    'MOG': 'mog-coin',
    'BRETT': 'brett',
    'POPCAT': 'popcat-sol',
    'NEIRO': 'neiro-ethereum',
    'TAO': 'bittensor',
    'WTAO': 'wrapped-tao',
}


def _rate_limit():
    """Ensure we don't exceed CoinGecko rate limits."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _min_request_interval:
        time.sleep(_min_request_interval - elapsed)
    _last_request_time = time.time()


def search_coingecko_coin(symbol: str) -> Optional[Dict]:
    """Search CoinGecko API for a coin by symbol.
    
    Args:
        symbol: Coin symbol to search for (e.g., 'ONDO', 'JTO')
    
    Returns:
        Dict with 'id', 'symbol', 'name' if found, None otherwise.
    """
    try:
        import requests
    except ImportError:
        print("Warning: requests library not available")
        return None
    
    _rate_limit()
    
    try:
        if COINGECKO_API_KEY:
            url = "https://pro-api.coingecko.com/api/v3/search"
            headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
        else:
            url = "https://api.coingecko.com/api/v3/search"
            headers = {}
        
        params = {"query": symbol}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        coins = data.get('coins', [])
        
        # Find exact symbol match (case-insensitive)
        symbol_upper = symbol.upper()
        for coin in coins:
            if coin.get('symbol', '').upper() == symbol_upper:
                return {
                    'id': coin['id'],
                    'symbol': coin['symbol'].upper(),
                    'name': coin.get('name', '')
                }
        
        # If no exact match, return first result if symbol is close
        if coins and coins[0].get('symbol', '').upper().startswith(symbol_upper[:2]):
            coin = coins[0]
            print(f"[COINGECKO] No exact match for '{symbol}', using closest: {coin['symbol']} ({coin['id']})")
            return {
                'id': coin['id'],
                'symbol': coin['symbol'].upper(),
                'name': coin.get('name', '')
            }
        
        return None
        
    except Exception as e:
        print(f"[COINGECKO] Search error for {symbol}: {e}")
        return None


def auto_resolve_symbol(symbol: str, add_to_cache: bool = True) -> Optional[str]:
    """Automatically resolve a coin symbol to CoinGecko ID.
    
    First checks local cache, then searches CoinGecko API if not found.
    Optionally adds discovered mappings to the runtime cache.
    
    Args:
        symbol: Coin symbol (e.g., 'ONDO', 'JTO')
        add_to_cache: If True, add discovered mapping to SYMBOL_TO_ID
    
    Returns:
        CoinGecko ID or None if not found.
    """
    symbol_upper = symbol.upper()
    
    # Check existing mapping first
    if symbol_upper in SYMBOL_TO_ID:
        return SYMBOL_TO_ID[symbol_upper]
    
    # Search CoinGecko
    print(f"[COINGECKO] Searching for unknown symbol: {symbol_upper}")
    result = search_coingecko_coin(symbol_upper)
    
    if result:
        coin_id = result['id']
        print(f"[COINGECKO] Found: {symbol_upper} -> {coin_id} ({result['name']})")
        
        if add_to_cache:
            SYMBOL_TO_ID[symbol_upper] = coin_id
            print(f"[COINGECKO] Added to runtime cache: {symbol_upper} -> {coin_id}")
        
        return coin_id
    
    print(f"[COINGECKO] Could not find coin: {symbol_upper}")
    return None


def get_coingecko_id(symbol: str, auto_search: bool = False) -> Optional[str]:
    """Convert a coin symbol to CoinGecko ID.
    
    Args:
        symbol: Coin symbol (e.g., 'DOGE', 'SHIB')
        auto_search: If True, search CoinGecko API for unknown symbols
    
    Returns:
        CoinGecko ID or None if not found.
    """
    symbol_upper = symbol.upper()
    coin_id = SYMBOL_TO_ID.get(symbol_upper)
    
    if coin_id is None and auto_search:
        coin_id = auto_resolve_symbol(symbol_upper)
    
    return coin_id


def get_coingecko_price(symbol: str) -> Optional[float]:
    """Get current USD price for a coin from CoinGecko.
    
    Args:
        symbol: Coin symbol (e.g., 'DOGE', 'SHIB')
    
    Returns:
        Current price in USD, or None if unavailable.
    """
    try:
        import requests
    except ImportError:
        print("Warning: requests library not available for CoinGecko fallback")
        return None
    
    coin_id = get_coingecko_id(symbol)
    if not coin_id:
        print(f"[COINGECKO] Unknown symbol: {symbol}")
        return None
    
    _rate_limit()
    
    try:
        if COINGECKO_API_KEY:
            url = f"https://pro-api.coingecko.com/api/v3/simple/price"
            headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
        else:
            url = f"https://api.coingecko.com/api/v3/simple/price"
            headers = {}
        
        params = {
            "ids": coin_id,
            "vs_currencies": "usd"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if coin_id in data and 'usd' in data[coin_id]:
            price = float(data[coin_id]['usd'])
            return price
        else:
            print(f"[COINGECKO] No price data for {symbol} ({coin_id})")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"[COINGECKO] Request error for {symbol}: {e}")
        return None
    except (ValueError, KeyError) as e:
        print(f"[COINGECKO] Parse error for {symbol}: {e}")
        return None


# Static curated coin lists by category (avoids CoinGecko API rate limits)
MEME_COINS = {
    'DOGE', 'SHIB', 'PEPE', 'BONK', 'FLOKI', 'WIF', 'MEME', 'TURBO', 'MOG', 
    'BRETT', 'POPCAT', 'NEIRO', 'COQ', 'MYRO', 'TOSHI', 'MOCHI', 'SPX',
    'GIGA', 'PONKE', 'SLERF', 'BOME', 'MEW', 'CAT', 'TREMP', 'PORK',
    'TAMA', 'ELON', 'BABYDOGE', 'KISHU', 'AKITA', 'SAMO', 'CATE', 'HOGE',
    'DOGELON', 'VOLT', 'PIT', 'KING', 'TSUKA', 'WOJAK', 'CHAD', 'PEPE2',
    'AIDOGE', 'LADYS', 'MILADY', 'BOB', 'BITCOIN', 'HarryPotterObamaSonic10Inu',
    'BEN', 'PSYOP', 'FINALE', 'CAPO', 'JESUS', 'SIMPSON', 'APU', 'ANDY',
    'LANDWOLF', 'BOBO', 'MUMU', 'BILLY', 'HOBBES', 'REDO', 'HOPPY', 'FWOG',
    'GOAT', 'PNUT', 'ACT', 'LUCE', 'CHILLGUY', 'MOODENG', 'SHOGGOTH'
}

BASE_MEME_COINS = {
    'BRETT', 'TOSHI', 'DEGEN', 'HIGHER', 'MOCHI', 'NORMIE', 'DOGINME',
    'BASED', 'BALD', 'BRIAN', 'BENJI', 'KEYBOARD', 'MFER', 'CHOMP'
}

SOLANA_MEME_COINS = {
    'BONK', 'WIF', 'POPCAT', 'MEW', 'BOME', 'SLERF', 'MYRO', 'PONKE', 
    'SAMO', 'SILLY', 'ANALOS', 'SLOTH', 'SOLAMA', 'COPE', 'FIDA',
    'GOAT', 'PNUT', 'ACT', 'MOODENG', 'FWOG', 'CHILLGUY'
}

AI_COINS = {
    'FET', 'AGIX', 'OCEAN', 'RNDR', 'RENDER', 'TAO', 'ARKM', 'WLD', 
    'AIOZ', 'NMR', 'GRT', 'CTXC', 'ALI', 'ORAI', 'OLAS', 'POND'
}

DEFI_COINS = {
    'UNI', 'AAVE', 'MKR', 'CRV', 'COMP', 'SNX', 'YFI', 'SUSHI', '1INCH',
    'LDO', 'RPL', 'PENDLE', 'GMX', 'DYDX', 'CAKE', 'JOE', 'BAL', 'LQTY'
}

LAYER1_COINS = {
    'BTC', 'ETH', 'SOL', 'ADA', 'AVAX', 'DOT', 'ATOM', 'NEAR', 'APT',
    'SUI', 'SEI', 'TIA', 'INJ', 'FTM', 'ALGO', 'XTZ', 'EGLD', 'HBAR'
}

# Map category names to coin sets
CATEGORY_COINS = {
    'meme': MEME_COINS,
    'base': BASE_MEME_COINS,
    'base meme': BASE_MEME_COINS,
    'solana': SOLANA_MEME_COINS,
    'solana meme': SOLANA_MEME_COINS,
    'ai': AI_COINS,
    'artificial intelligence': AI_COINS,
    'defi': DEFI_COINS,
    'layer1': LAYER1_COINS,
    'layer 1': LAYER1_COINS,
    'l1': LAYER1_COINS,
}


def get_coins_by_category(category: str) -> Optional[list]:
    """Get all coins in a category from static curated lists.
    
    Uses local static lists to avoid CoinGecko API rate limits.
    
    Args:
        category: Category name (e.g., 'meme', 'base', 'solana')
    
    Returns:
        List of coin symbols in the category, or None if unknown category.
    """
    category_lower = category.lower()
    
    if category_lower in CATEGORY_COINS:
        coins = list(CATEGORY_COINS[category_lower])
        print(f"[CATEGORY] Found {len(coins)} coins in category '{category}'")
        return coins
    else:
        print(f"[CATEGORY] Unknown category '{category}'. Available: {list(CATEGORY_COINS.keys())}")
        return None


def filter_coins_by_category(symbols: list, target_categories: list, match_any: bool = True) -> list:
    """Filter a list of coin symbols by CoinGecko categories.
    
    Uses bulk category fetch (single API call per category) instead of per-coin lookups.
    
    Args:
        symbols: List of coin symbols to filter (e.g., ['BTC', 'DOGE', 'PEPE'])
        target_categories: Categories to match (e.g., ['meme', 'base'])
        match_any: If True, match any category; if False, must match all
    
    Returns:
        List of symbols that match the category criteria.
    """
    # Get all coins for each target category (one API call per category)
    category_coins = {}
    for cat in target_categories:
        coins = get_coins_by_category(cat)
        if coins:
            category_coins[cat] = set(coins)
        else:
            category_coins[cat] = set()
    
    # Convert input symbols to uppercase set for fast lookup
    symbols_upper = set(s.upper() for s in symbols)
    
    # Filter symbols based on category membership
    matching = []
    for symbol in symbols:
        symbol_upper = symbol.upper()
        if match_any:
            # Match if symbol is in ANY target category
            if any(symbol_upper in coins for coins in category_coins.values()):
                matching.append(symbol)
        else:
            # Match if symbol is in ALL target categories
            if all(symbol_upper in coins for coins in category_coins.values()):
                matching.append(symbol)
    
    return matching


# Common category constants (for reference)
CATEGORY_MEME = "meme"
CATEGORY_BASE = "base"
CATEGORY_SOLANA = "solana"
CATEGORY_DEFI = "defi"
CATEGORY_LAYER1 = "layer 1"
CATEGORY_GAMING = "gaming"
CATEGORY_AI = "ai"


def get_multiple_prices(symbols: list, auto_search: bool = False) -> Dict[str, Optional[float]]:
    """Get prices for multiple coins in a single request.
    
    Args:
        symbols: List of coin symbols (e.g., ['DOGE', 'SHIB', 'PEPE'])
        auto_search: If True, search CoinGecko API for unknown symbols
    
    Returns:
        Dictionary mapping symbols to prices (None for unavailable).
    """
    try:
        import requests
    except ImportError:
        print("Warning: requests library not available for CoinGecko fallback")
        return {s: None for s in symbols}
    
    # Convert symbols to CoinGecko IDs
    id_to_symbol = {}
    for symbol in symbols:
        coin_id = get_coingecko_id(symbol, auto_search=auto_search)
        if coin_id:
            id_to_symbol[coin_id] = symbol
    
    if not id_to_symbol:
        return {s: None for s in symbols}
    
    _rate_limit()
    
    try:
        if COINGECKO_API_KEY:
            url = f"https://pro-api.coingecko.com/api/v3/simple/price"
            headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
        else:
            url = f"https://api.coingecko.com/api/v3/simple/price"
            headers = {}
        
        params = {
            "ids": ",".join(id_to_symbol.keys()),
            "vs_currencies": "usd"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Build result dictionary
        result = {s: None for s in symbols}
        for coin_id, symbol in id_to_symbol.items():
            if coin_id in data and 'usd' in data[coin_id]:
                result[symbol] = float(data[coin_id]['usd'])
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"[COINGECKO] Request error for multiple prices: {e}")
        return {s: None for s in symbols}
    except (ValueError, KeyError) as e:
        print(f"[COINGECKO] Parse error for multiple prices: {e}")
        return {s: None for s in symbols}
