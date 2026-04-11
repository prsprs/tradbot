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

# Rate limiting - CoinGecko free tier allows 10-50 calls/minute
_last_request_time = 0
_min_request_interval = 1.2  # seconds between requests


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
}


def _rate_limit():
    """Ensure we don't exceed CoinGecko rate limits."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _min_request_interval:
        time.sleep(_min_request_interval - elapsed)
    _last_request_time = time.time()


def get_coingecko_id(symbol: str) -> Optional[str]:
    """Convert a coin symbol to CoinGecko ID.
    
    Args:
        symbol: Coin symbol (e.g., 'DOGE', 'SHIB')
    
    Returns:
        CoinGecko ID or None if not found.
    """
    return SYMBOL_TO_ID.get(symbol.upper())


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


def get_multiple_prices(symbols: list) -> Dict[str, Optional[float]]:
    """Get prices for multiple coins in a single request.
    
    Args:
        symbols: List of coin symbols (e.g., ['DOGE', 'SHIB', 'PEPE'])
    
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
        coin_id = get_coingecko_id(symbol)
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
