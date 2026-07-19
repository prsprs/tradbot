#!/usr/bin/env python3
"""
Generate multi-pair test data with mixed correlation strengths.

Creates a single dataset with multiple pairs:
- Strong correlations (should be in significant_pairs)
- Weak correlations (should be in no_significant_relationship)

This tests the full pipeline filtering.

Usage:
    python tests/generate_multi_pair_data.py
    
    # Then run correlation analyzer:
    python correlation_tracker.py --analyze --data-dir tests/test_multi_pair_data
    
    # Verify results:
    cat tests/test_multi_pair_data/discovery_report.json | python -c "import json,sys; d=json.load(sys.stdin); print('Significant:', [p['leader']+':'+p['follower'] for p in d['significant_pairs']]); print('Not significant:', [p['leader']+':'+p['follower'] for p in d['no_significant_relationship']])"
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any

TEST_DATA_DIR = Path(__file__).parent / "test_multi_pair_data"


def generate_price_record(
    symbol: str,
    timestamp: datetime,
    price: float,
    sequence: int,
    source: str = "test"
) -> Dict[str, Any]:
    """Generate a single price record."""
    return {
        "symbol": symbol,
        "timestamp": timestamp.isoformat(),
        "source": source,
        "price": round(price, 6),
        "volume_24h": None,
        "market_cap": None,
        "price_change_24h": None,
        "price_change_pct": None,
        "collection_latency_ms": 50,
        "record_sequence": sequence,
    }


def generate_multi_pair_data(
    duration_hours: int = 72,
    sample_interval: int = 30,
    lag_seconds: int = 60,
) -> List[Dict[str, Any]]:
    """
    Generate test data with multiple pairs of varying correlation strength.
    
    Pairs:
    - BTC (leader) → SOL (strong follower)
    - BTC (leader) → WEAK1 (no correlation)
    - ETH (leader) → TAO (strong follower)
    - ETH (leader) → WEAK2 (no correlation)
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    # Initialize prices
    prices = {
        "BTC": 100000.0,
        "ETH": 3000.0,
        "SOL": 150.0,
        "TAO": 400.0,
        "WEAK1": 50.0,
        "WEAK2": 25.0,
    }
    
    sequence = 1
    num_samples = (duration_hours * 3600) // sample_interval
    
    # Track leader moves for followers
    btc_moves = {}
    eth_moves = {}
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # === BTC moves ===
        if i % 10 == 0:
            if random.random() < 0.5:
                move = 1.03 + random.random() * 0.02  # 3-5% up
            else:
                move = 0.96 - random.random() * 0.02  # 2-4% down
            prices["BTC"] *= move
            btc_moves[i] = move
        else:
            prices["BTC"] *= 1 + random.gauss(0, 0.002)
        
        # === ETH moves ===
        if i % 10 == 0:
            if random.random() < 0.5:
                move = 1.03 + random.random() * 0.02
            else:
                move = 0.96 - random.random() * 0.02
            prices["ETH"] *= move
            eth_moves[i] = move
        else:
            prices["ETH"] *= 1 + random.gauss(0, 0.002)
        
        # === SOL: Strong follower of BTC ===
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in btc_moves:
            btc_move = btc_moves[lookback_i]
            if random.random() < 0.90:  # 90% follow rate
                if btc_move > 1:
                    prices["SOL"] *= 1.025 + random.random() * 0.015
                else:
                    prices["SOL"] *= 0.97 - random.random() * 0.015
        prices["SOL"] *= 1 + random.gauss(0, 0.001)
        
        # === TAO: Strong follower of ETH ===
        if lookback_i in eth_moves:
            eth_move = eth_moves[lookback_i]
            if random.random() < 0.90:
                if eth_move > 1:
                    prices["TAO"] *= 1.025 + random.random() * 0.015
                else:
                    prices["TAO"] *= 0.97 - random.random() * 0.015
        prices["TAO"] *= 1 + random.gauss(0, 0.001)
        
        # === WEAK1: Independent random walk (no correlation with BTC) ===
        prices["WEAK1"] *= 1 + random.gauss(0, 0.003)
        
        # === WEAK2: Independent random walk (no correlation with ETH) ===
        prices["WEAK2"] *= 1 + random.gauss(0, 0.003)
        
        # Add all records
        for symbol, price in prices.items():
            records.append(generate_price_record(symbol, timestamp, price, sequence))
            sequence += 1
    
    return records


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate multi-pair test data")
    parser.add_argument('--duration', type=int, default=72, help='Duration in hours (default: 72)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')
    parser.add_argument('--output-dir', type=str, default=None, help='Output directory')
    
    args = parser.parse_args()
    random.seed(args.seed)
    
    output_dir = Path(args.output_dir) if args.output_dir else TEST_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating multi-pair test data...")
    print(f"  Duration: {args.duration} hours")
    print(f"  Seed: {args.seed}")
    
    records = generate_multi_pair_data(duration_hours=args.duration)
    
    # Write JSONL file
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jsonl_dir = output_dir / date_str
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = jsonl_dir / "prices_00-24.jsonl"
    
    with open(jsonl_path, 'w') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')
    
    print(f"  Written {len(records)} records to {jsonl_path}")
    
    print(f"\n✓ Test data generated in {output_dir}")
    print(f"\nExpected pairs:")
    print(f"  STRONG (should be in significant_pairs):")
    print(f"    - BTC:SOL")
    print(f"    - ETH:TAO")
    print(f"  WEAK (should be in no_significant_relationship):")
    print(f"    - BTC:WEAK1")
    print(f"    - ETH:WEAK2")
    print(f"\nTo run correlation analysis:")
    print(f"  python correlation_tracker.py --analyze --data-dir {output_dir}")
    print(f"\nTo verify filtering:")
    print(f"  cat {output_dir}/discovery_report.json | python -c \"import json,sys; d=json.load(sys.stdin); print('Significant:', [p['leader']+':'+p['follower'] for p in d['significant_pairs']]); print('Not significant:', [p['leader']+':'+p['follower'] for p in d['no_significant_relationship']])\"")


if __name__ == '__main__':
    main()
