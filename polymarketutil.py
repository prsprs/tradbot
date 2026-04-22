"""
Polymarket Utility - Market-validated coin selection using Polymarket prediction markets.

Provides coin filtering based on active Polymarket prediction markets.
Uses pattern matching to identify crypto-related markets and extract coin symbols.

No API key required - uses free Polymarket CLOB/Gamma API.
"""

import os
import re
import requests
from typing import Set, List, Dict, Tuple, Optional


# Polymarket API configuration
GAMMA_API_URL = "https://gamma-api.polymarket.com"


class PolymarketClient:
    """Client for interacting with the Polymarket API."""
    
    # Coin symbol patterns for matching event titles
    # Format: (symbol, regex_pattern)
    COIN_PATTERNS: List[Tuple[str, str]] = [
        ('BTC', r'bitcoin|\bbtc\b'),
        ('ETH', r'ethereum|\beth\b'),
        ('SOL', r'solana|\bsol\b'),
        ('DOGE', r'dogecoin|\bdoge\b'),
        ('XRP', r'\bxrp\b'),
        ('BNB', r'\bbnb\b'),
        ('ADA', r'cardano|\bada\b'),
        ('SHIB', r'shiba|\bshib\b'),
        ('PEPE', r'\bpepe\b'),
        ('BONK', r'\bbonk\b'),
        ('WIF', r'dogwifhat|\bwif\b'),
        ('FLOKI', r'\bfloki\b'),
        ('TRUMP', r'trump.*(?:token|coin|crypto)|\$trump'),
        ('AVAX', r'avalanche|\bavax\b'),
        ('DOT', r'polkadot|\bdot\b'),
        ('MATIC', r'polygon|\bmatic\b'),
        ('LINK', r'chainlink|\blink\b'),
        ('UNI', r'uniswap|\buni\b'),
        ('LTC', r'litecoin|\bltc\b'),
        ('ATOM', r'cosmos|\batom\b'),
        ('APT', r'aptos|\bapt\b'),
        ('ARB', r'arbitrum|\barb\b'),
        ('OP', r'optimism|\bop\b'),
        ('NEAR', r'\bnear\b'),
        ('SUI', r'\bsui\b'),
        ('SEI', r'\bsei\b'),
        ('TIA', r'celestia|\btia\b'),
        ('FET', r'fetch.*ai|\bfet\b'),
        ('RENDER', r'\brndr\b|\brender\b'),
        ('INJ', r'injective|\binj\b'),
        ('MEME', r'\bmeme\b.*coin'),
        ('GOAT', r'\bgoat\b'),
        ('PNUT', r'\bpnut\b|peanut'),
        ('ACT', r'\bact\b.*ai'),
    ]
    
    def __init__(self):
        """Initialize the Polymarket client."""
        pass  # No API key needed
    
    def get_active_events(self, limit: int = 500) -> List[Dict]:
        """Get active prediction market events from Polymarket.
        
        Args:
            limit: Maximum number of events to fetch (default: 500)
            
        Returns:
            List of event dictionaries.
        """
        try:
            response = requests.get(
                f"{GAMMA_API_URL}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[POLYMARKET] Error fetching events: {e}")
            return []
    
    def get_coins_with_markets(self) -> Tuple[Set[str], Dict[str, List[str]]]:
        """Get all coin symbols that have active Polymarket prediction markets.
        
        Returns:
            Tuple of:
                - Set of coin symbols (e.g., {'BTC', 'ETH', 'SOL', 'DOGE'})
                - Dict mapping symbol to list of matching event titles (for verification)
        """
        events = self.get_active_events()
        
        coins: Set[str] = set()
        coin_events: Dict[str, List[str]] = {}  # symbol -> [event titles]
        
        for event in events:
            title = event.get("title", "").lower()
            description = event.get("description", "").lower()
            search_text = f"{title} {description}"
            
            for symbol, pattern in self.COIN_PATTERNS:
                if re.search(pattern, search_text, re.IGNORECASE):
                    coins.add(symbol)
                    if symbol not in coin_events:
                        coin_events[symbol] = []
                    # Store the original title (not lowercased) for verification
                    coin_events[symbol].append(event.get("title", ""))
        
        return coins, coin_events
    
    def get_crypto_events(self) -> List[Dict]:
        """Get events that appear to be crypto-related.
        
        Returns:
            List of event dictionaries that match crypto patterns.
        """
        events = self.get_active_events()
        crypto_events = []
        
        crypto_keywords = [
            'bitcoin', 'ethereum', 'crypto', 'blockchain', 'token', 'coin',
            'btc', 'eth', 'sol', 'doge', 'defi', 'nft', 'web3'
        ]
        
        for event in events:
            title = event.get("title", "").lower()
            description = event.get("description", "").lower()
            search_text = f"{title} {description}"
            
            if any(kw in search_text for kw in crypto_keywords):
                crypto_events.append(event)
        
        return crypto_events


# Module-level convenience functions

_client: Optional[PolymarketClient] = None


def _get_client() -> PolymarketClient:
    """Get or create a singleton Polymarket client."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client


def get_coins_with_markets() -> Set[str]:
    """Get all coin symbols that have active Polymarket prediction markets.
    
    Returns:
        Set of coin symbols (e.g., {'BTC', 'ETH', 'SOL', 'DOGE'})
    """
    coins, _ = _get_client().get_coins_with_markets()
    return coins


def get_coins_with_markets_verbose() -> Tuple[Set[str], Dict[str, List[str]]]:
    """Get coins with markets and the event titles they matched.
    
    Returns:
        Tuple of (coin symbols set, dict mapping symbol to event titles)
    """
    return _get_client().get_coins_with_markets()


def filter_coins_by_polymarket(coins: List[str], verbose: bool = True) -> List[str]:
    """Filter a list of coins to only those with active Polymarket markets.
    
    Args:
        coins: List of coin symbols to filter
        verbose: If True, print matching event titles for verification
        
    Returns:
        List of coins that have active Polymarket prediction markets.
    """
    polymarket_coins, coin_events = _get_client().get_coins_with_markets()
    
    # Filter to coins that have Polymarket markets
    filtered = [c for c in coins if c.upper() in polymarket_coins]
    
    # Log results
    print(f"\n=== POLYMARKET FILTER ===")
    print(f"Input coins: {len(coins)}")
    print(f"Coins with active markets: {len(polymarket_coins)}")
    print(f"After filtering: {len(filtered)}")
    
    if verbose and filtered:
        print(f"\nMatched coins from active markets:")
        for coin in filtered:
            events = coin_events.get(coin.upper(), [])
            if events:
                # Show first event title for verification
                print(f"  {coin}: \"{events[0]}\"")
    
    return filtered
