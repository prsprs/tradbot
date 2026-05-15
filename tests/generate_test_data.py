#!/usr/bin/env python3
"""
Generate synthetic correlation data for testing preflight validation.

Creates JSONL files with predictable price patterns:
- Strong UP correlation: Leader rises → Follower rises after lag
- Strong DOWN correlation: Leader falls → Follower falls after lag  
- Mixed/Weak: No clear pattern

Usage:
    python tests/generate_test_data.py --scenario strong_up
    python tests/generate_test_data.py --scenario strong_down
    python tests/generate_test_data.py --scenario weak
    python tests/generate_test_data.py --scenario all
"""

import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any

# Test data output directory
TEST_DATA_DIR = Path(__file__).parent / "test_correlation_data"


def generate_price_record(
    symbol: str,
    timestamp: datetime,
    price: float,
    sequence: int,
    source: str = "test"
) -> Dict[str, Any]:
    """Generate a single price record in the expected JSONL format."""
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


def generate_strong_up_correlation(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    lag_seconds: int = 60,
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data where follower reliably follows leader UP movements.
    
    Pattern: When leader goes up, follower goes up after lag_seconds.
    Creates moves large enough to pass profitability thresholds (>1% moves).
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    leader_moves = {}  # Track leader moves for follower to follow
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Leader makes significant moves every ~10 samples (5 min at 30s intervals)
        if i % 10 == 0:
            if random.random() < 0.7:  # 70% chance of up move
                move = 1.03 + random.random() * 0.02  # 3-5% up
                leader_price *= move
                leader_moves[i] = move
            else:
                move = 0.97 - random.random() * 0.01  # 2-3% down
                leader_price *= move
                leader_moves[i] = move
        else:
            # Small random walk between big moves
            leader_price *= 1 + random.gauss(0, 0.002)
        
        # Follower follows leader UP moves after lag with high reliability
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in leader_moves:
            leader_move = leader_moves[lookback_i]
            if leader_move > 1.0:  # Leader went UP
                if random.random() < 0.90:  # 90% follow rate for up moves
                    follower_price *= 1.025 + random.random() * 0.015  # 2.5-4% follow
            # Don't follow down moves much in "strong_up" scenario
        
        # Add small noise to follower
        follower_price *= 1 + random.gauss(0, 0.001)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_strong_down_correlation(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    lag_seconds: int = 60,
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data where follower reliably follows leader DOWN movements.
    
    Pattern: When leader goes down, follower goes down after lag_seconds.
    Creates moves large enough to pass profitability thresholds (>1% moves).
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    leader_moves = {}  # Track leader moves for follower to follow
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Leader makes significant moves every ~10 samples
        if i % 10 == 0:
            if random.random() < 0.3:  # 30% chance of up move
                move = 1.02 + random.random() * 0.01  # 2-3% up
                leader_price *= move
                leader_moves[i] = move
            else:
                move = 0.96 - random.random() * 0.02  # 2-4% down
                leader_price *= move
                leader_moves[i] = move
        else:
            leader_price *= 1 + random.gauss(0, 0.002)
        
        # Follower follows leader DOWN moves after lag with high reliability
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in leader_moves:
            leader_move = leader_moves[lookback_i]
            if leader_move < 1.0:  # Leader went DOWN
                if random.random() < 0.90:  # 90% follow rate for down moves
                    follower_price *= 0.97 - random.random() * 0.015  # 2-3.5% follow down
            # Don't follow up moves much in "strong_down" scenario
        
        follower_price *= 1 + random.gauss(0, 0.001)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_weak_correlation(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data with weak/no correlation between leader and follower.
    
    Pattern: Leader and follower move independently.
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Independent random walks
        leader_price *= 1 + random.gauss(0, 0.002)
        follower_price *= 1 + random.gauss(0, 0.002)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_up_only_viable(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    lag_seconds: int = 60,
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data where ONLY UP direction is viable.
    
    Pattern: Follower follows leader UP moves with large swings,
    but during DOWN periods, follower is nearly FLAT (insufficient volatility).
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    leader_moves = {}
    in_down_period = False
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Leader makes moves
        if i % 10 == 0:
            if random.random() < 0.5:  # 50% up moves
                move = 1.04 + random.random() * 0.02  # 4-6% up (large)
                leader_price *= move
                leader_moves[i] = ('up', move)
                in_down_period = False
            else:
                move = 0.96 - random.random() * 0.02  # 2-4% down (large leader move)
                leader_price *= move
                leader_moves[i] = ('down', move)
                in_down_period = True
        else:
            leader_price *= 1 + random.gauss(0, 0.002)
        
        # Follower: strong follow on UP, nearly FLAT on DOWN
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in leader_moves:
            direction, _ = leader_moves[lookback_i]
            if direction == 'up':
                if random.random() < 0.90:  # 90% follow UP
                    follower_price *= 1.03 + random.random() * 0.02  # 3-5% follow
            else:
                # DOWN period: follower is nearly flat (tiny moves)
                follower_price *= 1 + random.gauss(0, 0.0002)  # Near-zero volatility
        elif in_down_period:
            # Stay flat during down periods
            follower_price *= 1 + random.gauss(0, 0.0001)
        else:
            follower_price *= 1 + random.gauss(0, 0.001)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_down_only_viable(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    lag_seconds: int = 60,
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data where ONLY DOWN direction is viable.
    
    Pattern: Follower follows leader DOWN moves with large swings,
    but during UP periods, follower is nearly FLAT (insufficient volatility).
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    leader_moves = {}
    in_up_period = False
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Leader makes moves
        if i % 10 == 0:
            if random.random() < 0.5:  # 50% up moves
                move = 1.04 + random.random() * 0.02  # 4-6% up (large leader move)
                leader_price *= move
                leader_moves[i] = ('up', move)
                in_up_period = True
            else:
                move = 0.96 - random.random() * 0.02  # 2-4% down (large)
                leader_price *= move
                leader_moves[i] = ('down', move)
                in_up_period = False
        else:
            leader_price *= 1 + random.gauss(0, 0.002)
        
        # Follower: strong follow on DOWN, nearly FLAT on UP
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in leader_moves:
            direction, _ = leader_moves[lookback_i]
            if direction == 'down':
                if random.random() < 0.90:  # 90% follow DOWN
                    follower_price *= 0.96 - random.random() * 0.02  # 4-6% follow down
            else:
                # UP period: follower is nearly flat (tiny moves)
                follower_price *= 1 + random.gauss(0, 0.0002)  # Near-zero volatility
        elif in_up_period:
            # Stay flat during up periods
            follower_price *= 1 + random.gauss(0, 0.0001)
        else:
            follower_price *= 1 + random.gauss(0, 0.001)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_insufficient_samples(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    duration_hours: int = 2,  # Only 2 hours of data
    sample_interval: int = 60,  # Sparse sampling
) -> List[Dict[str, Any]]:
    """
    Generate data with insufficient samples for analysis.
    
    Pattern: Too few data points to establish reliable correlation.
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval  # ~120 samples
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Simple random walk
        leader_price *= 1 + random.gauss(0, 0.003)
        follower_price *= 1 + random.gauss(0, 0.003)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_low_volatility(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    lag_seconds: int = 60,
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data with correlated but LOW volatility (moves too small).
    
    Pattern: Follower follows leader but moves are <0.5% (below break-even).
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    leader_moves = {}
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Leader makes SMALL moves
        if i % 10 == 0:
            if random.random() < 0.5:
                move = 1.003 + random.random() * 0.002  # 0.3-0.5% up
            else:
                move = 0.997 - random.random() * 0.002  # 0.3-0.5% down
            leader_price *= move
            leader_moves[i] = move
        else:
            leader_price *= 1 + random.gauss(0, 0.0005)
        
        # Follower follows with SMALL correlated moves
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in leader_moves:
            leader_move = leader_moves[lookback_i]
            if random.random() < 0.85:  # High correlation but small moves
                if leader_move > 1:
                    follower_price *= 1.002 + random.random() * 0.002  # 0.2-0.4%
                else:
                    follower_price *= 0.998 - random.random() * 0.002  # 0.2-0.4%
        
        follower_price *= 1 + random.gauss(0, 0.0003)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def generate_both_directions(
    leader: str = "LEADER",
    follower: str = "FOLLOWER",
    lag_seconds: int = 60,
    duration_hours: int = 48,
    sample_interval: int = 30,
) -> List[Dict[str, Any]]:
    """
    Generate data where follower follows leader in BOTH directions.
    
    Pattern: Strong correlation for both UP and DOWN moves.
    Creates moves large enough to pass profitability thresholds (>1% moves).
    """
    records = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hours)
    
    leader_price = 100.0
    follower_price = 50.0
    sequence = 1
    
    num_samples = (duration_hours * 3600) // sample_interval
    leader_moves = {}  # Track leader moves for follower to follow
    
    for i in range(num_samples):
        timestamp = start_time + timedelta(seconds=i * sample_interval)
        
        # Leader makes significant moves every ~10 samples
        if i % 10 == 0:
            if random.random() < 0.5:  # 50/50 up or down
                move = 1.03 + random.random() * 0.02  # 3-5% up
            else:
                move = 0.96 - random.random() * 0.02  # 2-4% down
            leader_price *= move
            leader_moves[i] = move
        else:
            leader_price *= 1 + random.gauss(0, 0.002)
        
        # Follower follows in BOTH directions after lag
        lag_samples = lag_seconds // sample_interval
        lookback_i = i - lag_samples
        if lookback_i in leader_moves:
            leader_move = leader_moves[lookback_i]
            if random.random() < 0.90:  # 90% follow rate both ways
                if leader_move > 1:
                    follower_price *= 1.025 + random.random() * 0.015  # 2.5-4% follow up
                else:
                    follower_price *= 0.97 - random.random() * 0.015  # 2-3.5% follow down
        
        follower_price *= 1 + random.gauss(0, 0.001)
        
        records.append(generate_price_record(leader, timestamp, leader_price, sequence))
        sequence += 1
        records.append(generate_price_record(follower, timestamp, follower_price, sequence))
        sequence += 1
    
    return records


def write_jsonl(records: List[Dict[str, Any]], output_path: Path):
    """Write records to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')
    print(f"  Written {len(records)} records to {output_path}")


def generate_discovery_report(
    scenario: str,
    leader: str,
    follower: str,
    output_path: Path,
    lag_seconds: int = 60,
):
    """Generate a test discovery report for the scenario."""
    
    # Configure based on scenario
    if scenario == "strong_up":
        up_significant = True
        down_significant = False
        up_corr = 0.75
        down_corr = 0.15
        stronger = "up"
    elif scenario == "strong_down":
        up_significant = False
        down_significant = True
        up_corr = 0.15
        down_corr = 0.75
        stronger = "down"
    elif scenario == "both":
        up_significant = True
        down_significant = True
        up_corr = 0.70
        down_corr = 0.72
        stronger = "symmetric"
    elif scenario == "up_only":
        up_significant = True
        down_significant = False
        up_corr = 0.80
        down_corr = 0.08
        stronger = "up"
    elif scenario == "down_only":
        up_significant = False
        down_significant = True
        up_corr = 0.08
        down_corr = 0.80
        stronger = "down"
    elif scenario == "insufficient":
        up_significant = False
        down_significant = False
        up_corr = 0.30
        down_corr = 0.30
        stronger = "none"
    elif scenario == "low_volatility":
        up_significant = False
        down_significant = False
        up_corr = 0.60  # Good correlation but low volatility
        down_corr = 0.60
        stronger = "symmetric"
    else:  # weak
        up_significant = False
        down_significant = False
        up_corr = 0.10
        down_corr = 0.12
        stronger = "none"
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_range_start": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
        "data_range_end": datetime.now(timezone.utc).isoformat(),
        "coins_analyzed": [leader, follower],
        "pairs_tested": 1,
        "significant_pairs": [
            {
                "leader": leader,
                "follower": follower,
                "optimal_lag_seconds": lag_seconds,
                "correlation": (up_corr + down_corr) / 2,
                "confidence": 0.75 if (up_significant or down_significant) else 0.3,
                "granger_significant": str(up_significant or down_significant),
                "recommendation": f"Test pair for {scenario} scenario",
                "test_results": [
                    {
                        "test_name": "Data Validation",
                        "passed": True,
                        "metrics": {"leader_samples": 5000, "follower_samples": 5000, "minimum_required": 500},
                        "reason": "Sufficient samples",
                        "reason_code": None,
                    },
                    {
                        "test_name": "Directional Analysis (UP vs DOWN)",
                        "passed": True,
                        "metrics": {
                            "up_samples": 200,
                            "up_correlation": up_corr,
                            "up_optimal_lag_seconds": lag_seconds,
                            "up_granger_pvalue": 0.001 if up_significant else 0.5,
                            "up_significant": str(up_significant),
                            "down_samples": 200,
                            "down_correlation": down_corr,
                            "down_optimal_lag_seconds": lag_seconds,
                            "down_granger_pvalue": 0.001 if down_significant else 0.5,
                            "down_significant": str(down_significant),
                            "asymmetry_score": abs(up_corr - down_corr),
                            "asymmetry_level": "low" if abs(up_corr - down_corr) < 0.2 else "moderate",
                            "stronger_direction": stronger,
                        },
                        "reason": f"Test scenario: {scenario}",
                        "reason_code": None,
                    },
                ],
                "caveats": [],
                "stability": 0.85,
                "stable_relationship": True,
                "data_range_end": datetime.now(timezone.utc).isoformat(),
                "directional_analysis": {
                    "up_samples": 200,
                    "up_correlation": up_corr,
                    "up_optimal_lag_seconds": lag_seconds,
                    "up_granger_pvalue": 0.001 if up_significant else 0.5,
                    "up_significant": str(up_significant),
                    "down_samples": 200,
                    "down_correlation": down_corr,
                    "down_optimal_lag_seconds": lag_seconds,
                    "down_granger_pvalue": 0.001 if down_significant else 0.5,
                    "down_significant": str(down_significant),
                    "asymmetry_score": abs(up_corr - down_corr),
                    "asymmetry_level": "low" if abs(up_corr - down_corr) < 0.2 else "moderate",
                    "stronger_direction": stronger,
                    "directional_recommendation": f"Test: {scenario}",
                },
            }
        ],
        "no_significant_relationship": [],
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"  Written discovery report to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic test data for preflight validation")
    parser.add_argument('--scenario', type=str, default='all',
                        choices=['strong_up', 'strong_down', 'weak', 'both', 'up_only', 'down_only', 'insufficient', 'low_volatility', 'all'],
                        help='Scenario to generate (default: all)')
    parser.add_argument('--leader', type=str, default='LEADER',
                        help='Leader symbol (default: LEADER)')
    parser.add_argument('--follower', type=str, default='FOLLOWER',
                        help='Follower symbol (default: FOLLOWER)')
    parser.add_argument('--lag', type=int, default=60,
                        help='Lag in seconds (default: 60)')
    parser.add_argument('--duration', type=int, default=48,
                        help='Duration in hours (default: 48)')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Output directory (default: tests/test_correlation_data)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed for reproducibility (default: 42)')
    
    args = parser.parse_args()
    random.seed(args.seed)
    
    output_dir = Path(args.output_dir) if args.output_dir else TEST_DATA_DIR
    
    all_scenarios = ['strong_up', 'strong_down', 'weak', 'both', 'up_only', 'down_only', 'insufficient', 'low_volatility']
    scenarios = all_scenarios if args.scenario == 'all' else [args.scenario]
    
    for scenario in scenarios:
        print(f"\nGenerating {scenario} scenario...")
        scenario_dir = output_dir / scenario
        
        # Generate price data
        if scenario == 'strong_up':
            records = generate_strong_up_correlation(
                args.leader, args.follower, args.lag, args.duration
            )
        elif scenario == 'strong_down':
            records = generate_strong_down_correlation(
                args.leader, args.follower, args.lag, args.duration
            )
        elif scenario == 'both':
            records = generate_both_directions(
                args.leader, args.follower, args.lag, args.duration
            )
        elif scenario == 'up_only':
            records = generate_up_only_viable(
                args.leader, args.follower, args.lag, args.duration
            )
        elif scenario == 'down_only':
            records = generate_down_only_viable(
                args.leader, args.follower, args.lag, args.duration
            )
        elif scenario == 'insufficient':
            records = generate_insufficient_samples(
                args.leader, args.follower
            )
        elif scenario == 'low_volatility':
            records = generate_low_volatility(
                args.leader, args.follower, args.lag, args.duration
            )
        else:  # weak
            records = generate_weak_correlation(
                args.leader, args.follower, args.duration
            )
        
        # Write JSONL file
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_path = scenario_dir / date_str / "prices_00-24.jsonl"
        write_jsonl(records, jsonl_path)
        
        # Generate discovery report
        report_path = scenario_dir / "discovery_report.json"
        generate_discovery_report(scenario, args.leader, args.follower, report_path, args.lag)
    
    print(f"\n✓ Test data generated in {output_dir}")
    print("\nTo test preflight with this data:")
    print(f"  python preflight.py --leader {args.leader} --follower {args.follower} \\")
    print(f"    --data-dir {output_dir}/<scenario> --report {output_dir}/<scenario>/discovery_report.json")


if __name__ == '__main__':
    main()
