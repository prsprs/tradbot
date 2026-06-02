"""
Candidate Coins Utility - Manages the candidate coins CSV datastore.

This module provides functions to:
- Add or update candidate coins (upsert)
- Load candidate coins for analysis
- Manage the candidate_coins.csv file
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

DEFAULT_CANDIDATE_DIR = './correlation_data'


def upsert_candidate_coin(
    symbol: str,
    blockchain: str,
    source: str,
    data_dir: str = DEFAULT_CANDIDATE_DIR
) -> bool:
    """
    Add or update a candidate coin in the CSV datastore.
    
    - New coin: creates record with added_at timestamp
    - Existing coin: updates updated_at timestamp and source
    
    Args:
        symbol: Token/coin symbol (e.g., BTC, SOL, BONK)
        blockchain: Blockchain name (e.g., Solana, Bitcoin, Ethereum)
        source: Origin of the candidate (e.g., llm_recommendation_gemini)
        data_dir: Directory containing candidate_coins.csv
        
    Returns:
        True if successful, False on error
    """
    csv_path = Path(data_dir) / 'candidate_coins.csv'
    now = datetime.now(timezone.utc).isoformat()
    symbol = symbol.upper().strip()
    
    if not symbol:
        print(f"[CANDIDATE] Error: Empty symbol provided")
        return False
    
    # Read existing records
    records = {}
    if csv_path.exists():
        try:
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_symbol = row.get('symbol', '').upper().strip()
                    if existing_symbol:
                        records[existing_symbol] = row
        except Exception as e:
            print(f"[CANDIDATE] Warning: Could not read existing file: {e}")
    
    # Upsert
    if symbol in records:
        records[symbol]['updated_at'] = now
        records[symbol]['source'] = source
        action = "Updated"
    else:
        records[symbol] = {
            'symbol': symbol,
            'blockchain': blockchain,
            'added_at': now,
            'updated_at': '',
            'source': source
        }
        action = "Added"
    
    # Write all records
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, 'w', newline='') as f:
            fieldnames = ['symbol', 'blockchain', 'added_at', 'updated_at', 'source']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in sorted(records.values(), key=lambda r: r['symbol']):
                writer.writerow(rec)
        
        print(f"[CANDIDATE] {action}: {symbol} ({blockchain}) from {source}")
        return True
    except Exception as e:
        print(f"[CANDIDATE] Error writing candidate coins: {e}")
        return False


def load_candidate_coins(data_dir: str = DEFAULT_CANDIDATE_DIR) -> List[str]:
    """
    Load candidate coins from CSV datastore.
    
    Args:
        data_dir: Directory containing candidate_coins.csv
        
    Returns:
        List of unique coin symbols (uppercase, deduplicated, sorted)
    """
    csv_path = Path(data_dir) / 'candidate_coins.csv'
    
    if not csv_path.exists():
        print(f"[CANDIDATE] File not found: {csv_path}")
        return []
    
    coins = set()
    try:
        with open(csv_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get('symbol', '').strip().upper()
                if symbol:
                    coins.add(symbol)
        
        coin_list = sorted(coins)
        print(f"[CANDIDATE] Loaded {len(coin_list)} coins from {csv_path}")
        return coin_list
        
    except Exception as e:
        print(f"[CANDIDATE] Error reading candidate coins: {e}")
        return []


def get_candidate_count(data_dir: str = DEFAULT_CANDIDATE_DIR) -> int:
    """
    Get the number of candidate coins in the datastore.
    
    Args:
        data_dir: Directory containing candidate_coins.csv
        
    Returns:
        Number of candidate coins, or 0 if file doesn't exist
    """
    return len(load_candidate_coins(data_dir))
