#!/usr/bin/env python3
"""
Santiment API utilities for coin discovery and cache refresh.

Provides functions to:
- Refresh the coin cache from Santiment API
- Discover coins ranked by volume change (momentum indicator)
- Filter coins by category and blockchain
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

import requests

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "coin_cache.json")
CACHE_BACKUP_FILE = os.path.join(SCRIPT_DIR, "coin_cache.backup.json")
SANTIMENT_API_URL = "https://api.santiment.net/graphql"


def refresh_cache_from_santiment(coinbase_coins: List[str], verbose: bool = True) -> Dict[str, Any]:
    """Refresh coin cache from Santiment API.
    
    Args:
        coinbase_coins: List of symbols tradeable on Coinbase
        verbose: Print progress messages
        
    Returns:
        Cache dict with coin data
    """
    if verbose:
        print("Refreshing cache from Santiment API...")
    
    # Fetch all projects with categories and blockchain info
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
        raise RuntimeError(f"Santiment API request failed: {e}")
    
    data = response.json()
    projects = data.get("data", {}).get("allProjects", [])
    
    # Build lookup by ticker
    source_data: Dict[str, Dict[str, Any]] = {}
    for project in projects:
        ticker = project.get("ticker", "").upper()
        infrastructure = project.get("infrastructure")
        
        if not ticker or not infrastructure:
            continue
        if ticker in source_data:
            continue
        
        segments = project.get("marketSegments", []) or []
        categories = [s.lower() for s in segments if s]
        blockchains = [infrastructure.lower()] if infrastructure else []
        
        source_data[ticker] = {
            "name": project.get("name", ""),
            "slug": project.get("slug", ""),
            "categories": categories,
            "blockchains": blockchains
        }
    
    if verbose:
        print(f"  Santiment projects: {len(source_data)}")
    
    # Build cache matching Coinbase coins
    coins_cache: Dict[str, Dict[str, Any]] = {}
    matched = 0
    
    for symbol in coinbase_coins:
        symbol_upper = symbol.upper()
        if symbol_upper in source_data:
            src = source_data[symbol_upper]
            coins_cache[symbol_upper] = {
                "name": src["name"],
                "categories": src["categories"],
                "blockchains": src["blockchains"]
            }
            matched += 1
        else:
            coins_cache[symbol_upper] = {
                "name": symbol_upper,
                "categories": [],
                "blockchains": []
            }
    
    if verbose:
        print(f"  Matched: {matched}/{len(coinbase_coins)}")
    
    cache = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "source": "santiment",
        "coinbase_count": len(coinbase_coins),
        "matched": matched,
        "coins": coins_cache
    }
    
    return cache


def backup_existing_cache() -> bool:
    """Create a backup of the existing cache file."""
    if not os.path.isfile(CACHE_FILE):
        return False
    
    try:
        with open(CACHE_FILE, 'r') as f:
            existing_cache = f.read()
        with open(CACHE_BACKUP_FILE, 'w') as f:
            f.write(existing_cache)
        return True
    except IOError:
        return False


def save_cache(cache: Dict[str, Any], verbose: bool = True) -> None:
    """Save cache to JSON file, creating a backup first."""
    if backup_existing_cache() and verbose:
        print(f"  Backed up existing cache")
    
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)
    
    if verbose:
        print(f"  Saved cache: {CACHE_FILE}")


def auto_refresh_cache(coinbase_coins: List[str], verbose: bool = True) -> Dict[str, Any]:
    """Auto-refresh cache from Santiment (used when santiment discovery is enabled).
    
    Args:
        coinbase_coins: List of tradeable Coinbase coins
        verbose: Print progress
        
    Returns:
        The refreshed cache dict
    """
    cache = refresh_cache_from_santiment(coinbase_coins, verbose=verbose)
    save_cache(cache, verbose=verbose)
    return cache


def get_santiment_coins_with_metrics(coinbase_coins: List[str], 
                                      chains: Optional[List[str]] = None,
                                      categories: Optional[List[str]] = None,
                                      verbose: bool = True) -> List[Tuple[str, float]]:
    """Get Coinbase coins with Santiment metrics for ranking.
    
    Fetches volumeChange24h and other metrics for ranking coins.
    Filters by chain and/or category if specified.
    
    Args:
        coinbase_coins: List of Coinbase tradeable symbols
        chains: Optional list of blockchains to filter by (OR logic)
        categories: Optional list of categories to filter by (OR logic)
        verbose: Print progress
        
    Returns:
        List of (symbol, volumeChange24h) tuples, sorted by volume change descending
    """
    if verbose:
        print("Fetching Santiment metrics for discovery...")
    
    # Fetch projects with metrics
    query = """
    {
        allProjects {
            slug
            ticker
            marketSegments
            infrastructure
            volumeChange24h
            rank
            marketcapUsd
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
        raise RuntimeError(f"Santiment API request failed: {e}")
    
    data = response.json()
    projects = data.get("data", {}).get("allProjects", [])
    
    # Build lookup by ticker
    project_data: Dict[str, Dict[str, Any]] = {}
    for project in projects:
        ticker = project.get("ticker", "").upper()
        if not ticker or ticker in project_data:
            continue
        
        infrastructure = project.get("infrastructure", "")
        segments = project.get("marketSegments", []) or []
        
        project_data[ticker] = {
            "infrastructure": infrastructure.lower() if infrastructure else "",
            "categories": [s.lower() for s in segments if s],
            "volumeChange24h": project.get("volumeChange24h"),
            "rank": project.get("rank"),
            "marketcapUsd": project.get("marketcapUsd")
        }
    
    if verbose:
        print(f"  Santiment projects with metrics: {len(project_data)}")
    
    # Filter to Coinbase coins
    coinbase_set = set(c.upper() for c in coinbase_coins)
    
    # Apply filters and collect results
    results: List[Tuple[str, float]] = []
    
    for symbol in coinbase_set:
        if symbol not in project_data:
            continue
        
        proj = project_data[symbol]
        vol_change = proj.get("volumeChange24h")
        
        # Skip if no volume change data
        if vol_change is None:
            continue
        
        # Apply chain filter (OR logic)
        if chains:
            proj_chain = proj.get("infrastructure", "")
            if not any(c.lower() == proj_chain for c in chains):
                continue
        
        # Apply category filter (OR logic)
        if categories:
            proj_cats = proj.get("categories", [])
            if not any(c.lower() in proj_cats for c in categories):
                continue
        
        results.append((symbol, vol_change))
    
    # Sort by volume change descending (highest momentum first)
    results.sort(key=lambda x: x[1] if x[1] is not None else float('-inf'), reverse=True)
    
    if verbose:
        print(f"  Coins after filtering: {len(results)}")
        if results:
            top3 = results[:3]
            print(f"  Top 3 by volume change: {[(s, f'{v:+.1f}%') for s, v in top3]}")
    
    return results


def discover_coins_santiment(coinbase_coins: List[str],
                              chains: Optional[List[str]] = None,
                              categories: Optional[List[str]] = None,
                              limit: int = 3,
                              verbose: bool = True) -> List[str]:
    """Discover top coins using Santiment metrics.
    
    Args:
        coinbase_coins: List of Coinbase tradeable symbols
        chains: Optional list of blockchains to filter by
        categories: Optional list of categories to filter by
        limit: Max number of coins to return
        verbose: Print progress
        
    Returns:
        List of coin symbols ranked by volumeChange24h
    """
    ranked = get_santiment_coins_with_metrics(
        coinbase_coins,
        chains=chains,
        categories=categories,
        verbose=verbose
    )
    
    return [symbol for symbol, _ in ranked[:limit]]
