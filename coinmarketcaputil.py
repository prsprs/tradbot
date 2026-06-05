"""
CoinMarketCap Utility - Alternative price fetcher using CoinMarketCap API.

Provides price data as an alternative to CoinGecko when hitting rate limits.
Requires a free API key from https://coinmarketcap.com/api/

Free tier limits:
- 15,000 call credits per month (~500/day)
- 35+ endpoints
- Updates every 60 seconds
"""

import os
import time
from typing import Optional, Dict, List

# API key from environment (required)
CMC_API_KEY = os.environ.get('CMC_API_KEY', '') or os.environ.get('COINMARKETCAP_API_KEY', '')

# API base URL
CMC_API_BASE = "https://pro-api.coinmarketcap.com"

# Rate limiting - CMC free tier is limited (~500 calls/day)
_last_request_time = 0
_min_request_interval = 5.0  # seconds between requests (conservative)

# Track daily usage (resets at midnight UTC)
_daily_calls = 0
_daily_reset_time = 0
_daily_limit = 450  # Conservative limit to stay under 500/day


# Common coin symbol to CoinMarketCap ID mapping
# CMC IDs can be found at: https://coinmarketcap.com/api/documentation/v1/#section/Best-Practices
SYMBOL_TO_CMC_ID = {
    'BTC': 1,
    'ETH': 1027,
    'DOGE': 74,
    'SHIB': 5994,
    'PEPE': 24478,
    'BONK': 23095,
    'FLOKI': 10804,
    'WIF': 28752,
    'SOL': 5426,
    'XRP': 52,
    'ADA': 2010,
    'AVAX': 5805,
    'DOT': 6636,
    'MATIC': 3890,
    'LINK': 1975,
    'UNI': 7083,
    'LTC': 2,
    'BCH': 1831,
    'ATOM': 3794,
    'FIL': 2280,
    'APT': 21794,
    'ARB': 11841,
    'OP': 11840,
    'NEAR': 6535,
    'IMX': 10603,
    'INJ': 7226,
    'SUI': 20947,
    'SEI': 23149,
    'TIA': 22861,
    'JUP': 29210,
    'RENDER': 5690,
    'FET': 3773,
    'RNDR': 5690,
    'GRT': 6719,
    'MANA': 1966,
    'SAND': 6210,
    'AXS': 6783,
    'APE': 18876,
    'CRV': 6538,
    'MKR': 1518,
    'AAVE': 7278,
    'TAO': 22974,
}


def _check_api_key() -> bool:
    """Check if API key is configured."""
    if not CMC_API_KEY:
        print("[CMC] Warning: CMC_API_KEY not set. Get a free key at https://coinmarketcap.com/api/")
        return False
    return True


def _rate_limit():
    """Ensure we don't exceed CoinMarketCap rate limits."""
    global _last_request_time, _daily_calls, _daily_reset_time
    
    # Check daily limit
    current_time = time.time()
    if current_time - _daily_reset_time > 86400:  # 24 hours
        _daily_calls = 0
        _daily_reset_time = current_time
    
    if _daily_calls >= _daily_limit:
        print(f"[CMC] Daily limit reached ({_daily_limit} calls). Waiting until reset.")
        return False
    
    # Enforce minimum interval
    elapsed = current_time - _last_request_time
    if elapsed < _min_request_interval:
        time.sleep(_min_request_interval - elapsed)
    
    _last_request_time = time.time()
    _daily_calls += 1
    return True


def get_cmc_id(symbol: str) -> Optional[int]:
    """Convert a coin symbol to CoinMarketCap ID.
    
    Args:
        symbol: Coin symbol (e.g., 'BTC', 'ETH')
    
    Returns:
        CoinMarketCap ID or None if not found.
    """
    return SYMBOL_TO_CMC_ID.get(symbol.upper())


def get_cmc_price(symbol: str) -> Optional[float]:
    """Get current USD price for a coin from CoinMarketCap.
    
    Uses the /v3/cryptocurrency/quotes/latest endpoint which supports symbol lookup.
    
    Args:
        symbol: Coin symbol (e.g., 'BTC', 'DOGE')
    
    Returns:
        Current price in USD, or None if unavailable.
    """
    if not _check_api_key():
        return None
    
    try:
        import requests
    except ImportError:
        print("[CMC] Warning: requests library not available")
        return None
    
    if not _rate_limit():
        return None
    
    try:
        url = f"{CMC_API_BASE}/v3/cryptocurrency/quotes/latest"
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accept": "application/json"
        }
        params = {
            "symbol": symbol.upper(),
            "convert": "USD"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # V3 returns array of results
        if 'data' in data and len(data['data']) > 0:
            coin_data = data['data'][0]
            # Get USD quote
            quotes = coin_data.get('quote', [])
            for quote in quotes:
                if quote.get('symbol') == 'USD' or quote.get('id') == 2781:  # USD CMC ID
                    price = quote.get('price')
                    if price is not None:
                        return float(price)
        
        print(f"[CMC] No price data for {symbol}")
        return None
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print(f"[CMC] Rate limit exceeded")
        elif e.response.status_code == 401:
            print(f"[CMC] Invalid API key")
        else:
            print(f"[CMC] HTTP error for {symbol}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[CMC] Request error for {symbol}: {e}")
        return None
    except (ValueError, KeyError, IndexError) as e:
        print(f"[CMC] Parse error for {symbol}: {e}")
        return None


def get_multiple_prices_cmc(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Get prices for multiple coins in a single request.
    
    Uses the /v3/cryptocurrency/quotes/latest endpoint with comma-separated symbols.
    More efficient than individual calls.
    
    Args:
        symbols: List of coin symbols (e.g., ['BTC', 'ETH', 'DOGE'])
    
    Returns:
        Dictionary mapping symbols to prices (None for unavailable).
    """
    if not _check_api_key():
        return {s: None for s in symbols}
    
    try:
        import requests
    except ImportError:
        print("[CMC] Warning: requests library not available")
        return {s: None for s in symbols}
    
    if not _rate_limit():
        return {s: None for s in symbols}
    
    # Build result dict
    result = {s.upper(): None for s in symbols}
    
    try:
        url = f"{CMC_API_BASE}/v3/cryptocurrency/quotes/latest"
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accept": "application/json"
        }
        params = {
            "symbol": ",".join(s.upper() for s in symbols),
            "convert": "USD",
            "skip_invalid": "true"  # Don't fail on unknown symbols
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # V3 returns array of results
        if 'data' in data:
            for coin_data in data['data']:
                symbol = coin_data.get('symbol', '').upper()
                quotes = coin_data.get('quote', [])
                for quote in quotes:
                    if quote.get('symbol') == 'USD' or quote.get('id') == 2781:
                        price = quote.get('price')
                        if price is not None and symbol in result:
                            result[symbol] = float(price)
                        break
        
        # Log credit usage
        if 'status' in data:
            credits_used = data['status'].get('credit_count', 0)
            if credits_used > 1:
                print(f"[CMC] Used {credits_used} credits for {len(symbols)} symbols")
        
        return result
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print(f"[CMC] Rate limit exceeded")
        elif e.response.status_code == 401:
            print(f"[CMC] Invalid API key")
        else:
            print(f"[CMC] HTTP error: {e}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"[CMC] Request error: {e}")
        return result
    except (ValueError, KeyError) as e:
        print(f"[CMC] Parse error: {e}")
        return result


def search_cmc_coin(symbol: str) -> Optional[Dict]:
    """Search CoinMarketCap for a coin by symbol.
    
    Args:
        symbol: Coin symbol to search for
    
    Returns:
        Dict with 'id', 'symbol', 'name' if found, None otherwise.
    """
    if not _check_api_key():
        return None
    
    try:
        import requests
    except ImportError:
        return None
    
    if not _rate_limit():
        return None
    
    try:
        url = f"{CMC_API_BASE}/v1/cryptocurrency/map"
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accept": "application/json"
        }
        params = {
            "symbol": symbol.upper(),
            "limit": 1
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            coin = data['data'][0]
            return {
                'id': coin['id'],
                'symbol': coin['symbol'].upper(),
                'name': coin.get('name', ''),
                'slug': coin.get('slug', '')
            }
        
        return None
        
    except Exception as e:
        print(f"[CMC] Search error for {symbol}: {e}")
        return None


def auto_resolve_symbol(symbol: str, add_to_cache: bool = True) -> Optional[int]:
    """Automatically resolve a coin symbol to CoinMarketCap ID.
    
    First checks local cache, then searches CMC API if not found.
    
    Args:
        symbol: Coin symbol (e.g., 'ONDO', 'JTO')
        add_to_cache: If True, add discovered mapping to cache
    
    Returns:
        CoinMarketCap ID or None if not found.
    """
    symbol_upper = symbol.upper()
    
    # Check existing mapping first
    if symbol_upper in SYMBOL_TO_CMC_ID:
        return SYMBOL_TO_CMC_ID[symbol_upper]
    
    # Search CMC
    print(f"[CMC] Searching for unknown symbol: {symbol_upper}")
    result = search_cmc_coin(symbol_upper)
    
    if result:
        cmc_id = result['id']
        print(f"[CMC] Found: {symbol_upper} -> ID {cmc_id} ({result['name']})")
        
        if add_to_cache:
            SYMBOL_TO_CMC_ID[symbol_upper] = cmc_id
            print(f"[CMC] Added to runtime cache: {symbol_upper} -> {cmc_id}")
        
        return cmc_id
    
    print(f"[CMC] Could not find coin: {symbol_upper}")
    return None


def get_api_status() -> Optional[Dict]:
    """Get current API key status and credit usage.
    
    Returns:
        Dict with usage info, or None if unavailable.
    """
    if not _check_api_key():
        return None
    
    try:
        import requests
    except ImportError:
        return None
    
    try:
        url = f"{CMC_API_BASE}/v1/key/info"
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if 'data' in data:
            usage = data['data'].get('usage', {})
            plan = data['data'].get('plan', {})
            return {
                'plan': plan.get('credit_limit_monthly', 0),
                'used_this_month': usage.get('current_month', {}).get('credits_used', 0),
                'used_today': usage.get('current_day', {}).get('credits_used', 0),
                'remaining': plan.get('credit_limit_monthly', 0) - usage.get('current_month', {}).get('credits_used', 0)
            }
        
        return None
        
    except Exception as e:
        print(f"[CMC] Error getting API status: {e}")
        return None


# Convenience function matching CoinGecko interface
def get_coinmarketcap_price(symbol: str) -> Optional[float]:
    """Alias for get_cmc_price for consistency with coingeckoutil."""
    return get_cmc_price(symbol)


def get_multiple_prices(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Alias for get_multiple_prices_cmc for consistency."""
    return get_multiple_prices_cmc(symbols)
