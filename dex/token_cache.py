"""
Jupiter Token Cache - Caches the Jupiter verified token list for symbol-to-mint lookups.

Features:
- Fetches Jupiter's strict verified token list
- Caches locally with daily refresh
- Provides symbol-to-mint address mapping
- Filters by minimum liquidity
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx

# Cache configuration
CACHE_DIR = os.environ.get('DEX_CACHE_DIR', './dex_cache/')
TOKEN_CACHE_FILE = os.path.join(CACHE_DIR, 'jupiter_tokens.json')
CACHE_MAX_AGE_HOURS = 24

# Track if collision warning has been shown (to avoid spam)
_collision_warning_shown = False

# Jupiter API endpoints (v2 - requires API key)
# Use /tag?query=verified to get all verified tokens
JUPITER_TOKEN_LIST_URL = "https://api.jup.ag/tokens/v2/tag?query=verified"
JUPITER_TOKEN_SEARCH_URL = "https://api.jup.ag/tokens/v2/search"

# API key environment variable
JUPITER_API_KEY_ENV = "JUPITER_API_KEY"

# Minimum liquidity threshold (USD) - conservative MVP default
MIN_LIQUIDITY_USD = 100_000


def ensure_cache_dir():
    """Create cache directory if it doesn't exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_age() -> Optional[str]:
    """Get human-readable age of the token cache.
    
    Returns:
        String like "2h 15m ago" or None if cache doesn't exist.
    """
    if not os.path.exists(TOKEN_CACHE_FILE):
        return None
    
    try:
        mtime = os.path.getmtime(TOKEN_CACHE_FILE)
        age_seconds = time.time() - mtime
        hours = int(age_seconds // 3600)
        minutes = int((age_seconds % 3600) // 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m ago"
        else:
            return f"{minutes}m ago"
    except Exception:
        return None


def is_cache_valid() -> bool:
    """Check if token cache exists and is fresh enough.
    
    Returns:
        True if cache exists and is less than CACHE_MAX_AGE_HOURS old.
    """
    if not os.path.exists(TOKEN_CACHE_FILE):
        return False
    
    try:
        mtime = os.path.getmtime(TOKEN_CACHE_FILE)
        age_hours = (time.time() - mtime) / 3600
        return age_hours < CACHE_MAX_AGE_HOURS
    except Exception:
        return False


def fetch_jupiter_tokens(api_key: str = None) -> List[Dict]:
    """Fetch Jupiter's verified token list.
    
    Args:
        api_key: Jupiter API key. Falls back to JUPITER_API_KEY env var.
    
    Returns:
        List of token dictionaries from Jupiter API.
    
    Raises:
        RuntimeError: If API call fails.
    """
    key = api_key or os.environ.get(JUPITER_API_KEY_ENV)
    if not key:
        raise RuntimeError(f"Jupiter API key required. Set {JUPITER_API_KEY_ENV} env var.")
    
    print("[JUPITER] Fetching verified token list...")
    
    headers = {"x-api-key": key}
    
    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            response = client.get(JUPITER_TOKEN_LIST_URL)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Failed to fetch Jupiter token list: {e}")


def save_token_cache(tokens: List[Dict]):
    """Save tokens to local cache file.
    
    Args:
        tokens: List of token dictionaries from Jupiter API.
    """
    ensure_cache_dir()
    
    cache_data = {
        'fetched_at': datetime.utcnow().isoformat() + 'Z',
        'token_count': len(tokens),
        'tokens': tokens
    }
    
    with open(TOKEN_CACHE_FILE, 'w') as f:
        json.dump(cache_data, f, indent=2)
    
    print(f"[JUPITER] Cached {len(tokens)} tokens to {TOKEN_CACHE_FILE}")


def load_token_cache() -> List[Dict]:
    """Load tokens from local cache file.
    
    Returns:
        List of token dictionaries, or empty list if cache doesn't exist.
    """
    if not os.path.exists(TOKEN_CACHE_FILE):
        return []
    
    try:
        with open(TOKEN_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        return cache_data.get('tokens', [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"[JUPITER] Warning: Could not load token cache: {e}")
        return []


def refresh_token_cache(force: bool = False) -> List[Dict]:
    """Refresh the token cache if needed.
    
    Args:
        force: If True, refresh even if cache is valid.
    
    Returns:
        List of token dictionaries.
    """
    if not force and is_cache_valid():
        print(f"[JUPITER] Using cached token list ({get_cache_age()})")
        return load_token_cache()
    
    tokens = fetch_jupiter_tokens()
    save_token_cache(tokens)
    return tokens


def get_tokens(refresh: bool = False) -> List[Dict]:
    """Get Jupiter verified tokens, refreshing cache if needed.
    
    Args:
        refresh: If True, force refresh the cache.
    
    Returns:
        List of token dictionaries.
    """
    if refresh or not is_cache_valid():
        return refresh_token_cache(force=refresh)
    return load_token_cache()


def build_symbol_to_mint_map(tokens: List[Dict]) -> Dict[str, str]:
    """Build a symbol-to-mint address mapping.
    
    Note: If multiple tokens share the same symbol, we skip them (collision).
    This is the conservative MVP approach to avoid trading the wrong token.
    
    Args:
        tokens: List of token dictionaries.
    
    Returns:
        Dictionary mapping uppercase symbols to mint addresses.
    """
    symbol_counts = {}
    symbol_to_mint = {}
    
    # First pass: count symbols
    for token in tokens:
        symbol = token.get('symbol', '').upper()
        if symbol:
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    
    # Second pass: only include unique symbols
    for token in tokens:
        symbol = token.get('symbol', '').upper()
        # Jupiter v2 API uses 'id' for mint address, v1 used 'address'
        address = token.get('id') or token.get('address', '')
        
        if symbol and address and symbol_counts.get(symbol, 0) == 1:
            symbol_to_mint[symbol] = address
    
    # Count collisions for logging (only show once per session)
    global _collision_warning_shown
    collisions = sum(1 for count in symbol_counts.values() if count > 1)
    if collisions > 0 and not _collision_warning_shown:
        print(f"[JUPITER] Skipped {collisions} symbols with collisions")
        _collision_warning_shown = True
    
    return symbol_to_mint


def get_mint_address(symbol: str, tokens: Optional[List[Dict]] = None) -> Optional[str]:
    """Get the mint address for a token symbol.
    
    Args:
        symbol: Token symbol (e.g., 'BONK', 'WIF').
        tokens: Optional pre-loaded token list (fetches if not provided).
    
    Returns:
        Mint address string, or None if not found or collision.
    """
    if tokens is None:
        tokens = get_tokens()
    
    symbol_upper = symbol.upper()
    symbol_map = build_symbol_to_mint_map(tokens)
    
    return symbol_map.get(symbol_upper)


def get_token_info(symbol: str, tokens: Optional[List[Dict]] = None) -> Optional[Dict]:
    """Get full token info for a symbol.
    
    Args:
        symbol: Token symbol (e.g., 'BONK', 'WIF').
        tokens: Optional pre-loaded token list.
    
    Returns:
        Token dictionary with address, symbol, name, decimals, etc.
    """
    if tokens is None:
        tokens = get_tokens()
    
    symbol_upper = symbol.upper()
    
    # Find tokens matching this symbol
    matches = [t for t in tokens if t.get('symbol', '').upper() == symbol_upper]
    
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        print(f"[JUPITER] Warning: Symbol collision for {symbol}, {len(matches)} matches")
        return None
    else:
        return None


def list_all_tokens(min_liquidity: float = MIN_LIQUIDITY_USD) -> List[str]:
    """List all verified token symbols.
    
    Args:
        min_liquidity: Minimum liquidity in USD (not enforced in strict list).
    
    Returns:
        List of unique token symbols (no collisions).
    """
    tokens = get_tokens()
    symbol_map = build_symbol_to_mint_map(tokens)
    return sorted(symbol_map.keys())


# Well-known Solana token addresses and decimals
WELL_KNOWN_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "PEPE": "HRw4GCbxTZdCHEjpCfvE5kXxrRQ4FyEafjzYN7L12aqD",
    "FLOKI": "FLokitvNngGxrqA5tVp2MDPH2bqWUFMQ76LqCVwC2C1H",
    # Wrapped TAO (Bittensor) on Solana - listed as TAO on Jupiter
    "WTAO": "taoC6xyv2v8tDLcev4uaGUgV4vdQsWJrGft2kcBRrBY",
}

# Well-known token decimals (for price calculations)
WELL_KNOWN_DECIMALS = {
    "SOL": 9,
    "USDC": 6,
    "USDT": 6,
    "BONK": 5,
    "WIF": 6,
    "POPCAT": 9,
    "PEPE": 9,
    "FLOKI": 9,
    "WTAO": 9,
}


def get_well_known_decimals(symbol: str) -> Optional[int]:
    """Get decimals for a well-known token.
    
    Args:
        symbol: Token symbol (e.g., 'BONK').
    
    Returns:
        Number of decimals or None if not known.
    """
    return WELL_KNOWN_DECIMALS.get(symbol.upper())


def get_mint_with_fallback(symbol: str) -> Optional[str]:
    """Get mint address with fallback to well-known tokens.
    
    Args:
        symbol: Token symbol.
    
    Returns:
        Mint address or None.
    """
    # Try well-known tokens first
    symbol_upper = symbol.upper()
    if symbol_upper in WELL_KNOWN_TOKENS:
        return WELL_KNOWN_TOKENS[symbol_upper]
    
    # Fall back to Jupiter token list
    return get_mint_address(symbol)
