#!/usr/bin/env python3
"""
LP Analyzer - Historical analysis tool for LP arbitrage data.

Analyzes collected snapshots and trades to:
- Calculate what P&L would have been if trades executed
- Identify optimal threshold settings from historical data
- Compare actual spread movements to predictions
- Generate reports by time period

Usage:
    python lp_analyzer.py                    # Full analysis
    python lp_analyzer.py --period=7d        # Last 7 days
    python lp_analyzer.py --platform=jupiter # Filter by platform
    python lp_analyzer.py --export=csv       # Export to CSV
    python lp_analyzer.py --optimize         # Find optimal thresholds
"""

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from lp_history import LPHistoryManager, DEFAULT_HISTORY_DIR


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class AnalyzerConfig:
    """Configuration for LP analyzer."""
    period: str = "7d"  # 24h, 7d, 30d, all
    platform: Optional[str] = None  # jupiter, drift, hyperliquid, or None for all
    export: Optional[str] = None  # csv, json, or None
    optimize: bool = False
    history_dir: str = DEFAULT_HISTORY_DIR
    verbose: bool = False


def parse_period(period_str: str) -> int:
    """Parse period string to hours."""
    period_str = period_str.lower().strip()
    
    if period_str == "all":
        return 365 * 24 * 10  # 10 years
    elif period_str.endswith("h"):
        return int(period_str[:-1])
    elif period_str.endswith("d"):
        return int(period_str[:-1]) * 24
    elif period_str.endswith("w"):
        return int(period_str[:-1]) * 24 * 7
    elif period_str.endswith("m"):
        return int(period_str[:-1]) * 24 * 30
    else:
        try:
            return int(period_str)
        except ValueError:
            print(f"[WARNING] Invalid period '{period_str}', defaulting to 7d")
            return 7 * 24


def parse_args() -> AnalyzerConfig:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='LP Analyzer - Historical analysis for LP arbitrage',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python lp_analyzer.py                    # Full analysis, last 7 days
  python lp_analyzer.py --period=24h       # Last 24 hours
  python lp_analyzer.py --period=30d       # Last 30 days
  python lp_analyzer.py --platform=jupiter # Filter by Jupiter
  python lp_analyzer.py --export=csv       # Export to CSV
  python lp_analyzer.py --optimize         # Find optimal thresholds
"""
    )
    
    parser.add_argument(
        '--period',
        default=os.environ.get('ANALYSIS_PERIOD', '7d'),
        help='Analysis period: 24h, 7d, 30d, all (default: 7d)'
    )
    parser.add_argument(
        '--platform',
        choices=['jupiter', 'drift', 'hyperliquid'],
        default=None,
        help='Filter by platform (default: all)'
    )
    parser.add_argument(
        '--export',
        choices=['csv', 'json'],
        default=None,
        help='Export format (default: none, print to console)'
    )
    parser.add_argument(
        '--optimize',
        action='store_true',
        help='Find optimal buy/sell thresholds from historical data'
    )
    parser.add_argument(
        '--history-dir',
        default=os.environ.get('HISTORY_DIR', DEFAULT_HISTORY_DIR),
        help='History directory path'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output'
    )
    
    args = parser.parse_args()
    
    return AnalyzerConfig(
        period=args.period,
        platform=args.platform,
        export=args.export,
        optimize=args.optimize,
        history_dir=args.history_dir,
        verbose=args.verbose
    )


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================

class LPAnalyzer:
    """Analyzer for LP arbitrage history."""
    
    def __init__(self, config: AnalyzerConfig):
        self.config = config
        self.history = LPHistoryManager(config.history_dir)
        self.hours = parse_period(config.period)
    
    def load_filtered_snapshots(self) -> List[Dict]:
        """Load snapshots filtered by period and platform."""
        snapshots = self.history.get_snapshots_by_period(self.hours)
        
        if self.config.platform:
            snapshots = [s for s in snapshots if s.get('platform') == self.config.platform]
        
        return snapshots
    
    def load_filtered_trades(self) -> List[Dict]:
        """Load trades filtered by period and platform."""
        trades = self.history.get_trades_by_period(self.hours)
        
        if self.config.platform:
            trades = [t for t in trades if t.get('platform') == self.config.platform]
        
        return trades
    
    def analyze_snapshots(self) -> Dict:
        """Analyze snapshot data."""
        snapshots = self.load_filtered_snapshots()
        
        if not snapshots:
            return {
                'count': 0,
                'error': 'No snapshots found for the specified period'
            }
        
        # Basic counts
        total = len(snapshots)
        buys = [s for s in snapshots if s.get('recommendation') == 'BUY']
        sells = [s for s in snapshots if s.get('recommendation') == 'SELL']
        holds = [s for s in snapshots if s.get('recommendation') == 'HOLD']
        
        # Spread statistics
        spreads = [s.get('spread_pct', 0) for s in snapshots]
        min_spread = min(spreads) if spreads else 0
        max_spread = max(spreads) if spreads else 0
        avg_spread = sum(spreads) / len(spreads) if spreads else 0
        
        # Premium vs discount distribution
        premiums = [s for s in spreads if s > 0]
        discounts = [s for s in spreads if s < 0]
        
        # Time range
        timestamps = [s.get('timestamp', '') for s in snapshots]
        first_ts = min(timestamps) if timestamps else None
        last_ts = max(timestamps) if timestamps else None
        
        return {
            'period': self.config.period,
            'platform': self.config.platform or 'all',
            'count': total,
            'first_snapshot': first_ts,
            'last_snapshot': last_ts,
            'recommendations': {
                'buy': len(buys),
                'sell': len(sells),
                'hold': len(holds)
            },
            'spread_stats': {
                'min': round(min_spread, 4),
                'max': round(max_spread, 4),
                'avg': round(avg_spread, 4),
                'premium_count': len(premiums),
                'discount_count': len(discounts),
                'avg_premium': round(sum(premiums) / len(premiums), 4) if premiums else 0,
                'avg_discount': round(sum(discounts) / len(discounts), 4) if discounts else 0
            },
            'buy_opportunities': [
                {
                    'timestamp': s.get('timestamp'),
                    'spread_pct': s.get('spread_pct'),
                    'market_price': s.get('market_price'),
                    'virtual_price': s.get('virtual_price')
                }
                for s in buys
            ],
            'sell_opportunities': [
                {
                    'timestamp': s.get('timestamp'),
                    'spread_pct': s.get('spread_pct'),
                    'market_price': s.get('market_price'),
                    'virtual_price': s.get('virtual_price')
                }
                for s in sells
            ]
        }
    
    def analyze_trades(self) -> Dict:
        """Analyze trade data."""
        trades = self.load_filtered_trades()
        
        if not trades:
            return {
                'count': 0,
                'error': 'No trades found for the specified period'
            }
        
        # Separate by execution status
        executed = [t for t in trades if t.get('executed')]
        simulated = [t for t in trades if not t.get('executed')]
        
        # Separate by action
        buys = [t for t in trades if t.get('action') == 'BUY']
        sells = [t for t in trades if t.get('action') == 'SELL']
        
        # Calculate totals
        total_buy_usd = sum(t.get('amount_usd', 0) for t in buys)
        total_sell_usd = sum(t.get('amount_usd', 0) for t in sells)
        
        # Simulated P&L estimation
        simulated_pnl = 0.0
        for t in simulated:
            spread = abs(t.get('spread_pct', 0))
            amount = t.get('amount_usd', 0)
            # Assume spread capture as profit
            simulated_pnl += amount * (spread / 100)
        
        return {
            'period': self.config.period,
            'platform': self.config.platform or 'all',
            'count': len(trades),
            'executed_count': len(executed),
            'simulated_count': len(simulated),
            'buy_count': len(buys),
            'sell_count': len(sells),
            'total_buy_usd': round(total_buy_usd, 2),
            'total_sell_usd': round(total_sell_usd, 2),
            'simulated_pnl': round(simulated_pnl, 2),
            'trades': trades if self.config.verbose else []
        }
    
    def calculate_simulated_pnl(self) -> Dict:
        """
        Calculate what P&L would have been if all simulated trades executed.
        
        This uses a simple model: assume the spread normalizes after each trade,
        so profit = trade_amount * spread_captured.
        """
        snapshots = self.load_filtered_snapshots()
        
        if not snapshots:
            return {'error': 'No data available'}
        
        # Group snapshots by buy/sell opportunities
        opportunities = [s for s in snapshots if s.get('recommendation') != 'HOLD']
        
        total_potential_profit = 0.0
        trade_details = []
        
        for opp in opportunities:
            spread = abs(opp.get('spread_pct', 0))
            # Assume $50 trade (default trade amount)
            trade_amount = 50
            potential_profit = trade_amount * (spread / 100)
            total_potential_profit += potential_profit
            
            trade_details.append({
                'timestamp': opp.get('timestamp'),
                'action': opp.get('recommendation'),
                'spread_pct': opp.get('spread_pct'),
                'potential_profit': round(potential_profit, 2)
            })
        
        return {
            'period': self.config.period,
            'opportunities_count': len(opportunities),
            'total_potential_profit': round(total_potential_profit, 2),
            'avg_profit_per_trade': round(total_potential_profit / len(opportunities), 2) if opportunities else 0,
            'trade_details': trade_details if self.config.verbose else []
        }
    
    def find_optimal_thresholds(self) -> Dict:
        """
        Find optimal buy/sell thresholds from historical data.
        
        This backtests different threshold combinations to find
        which would have captured the most profitable opportunities.
        """
        snapshots = self.load_filtered_snapshots()
        
        if len(snapshots) < 10:
            return {'error': 'Insufficient data for optimization (need at least 10 snapshots)'}
        
        # Test different threshold combinations
        buy_thresholds = [-0.005, -0.01, -0.015, -0.02, -0.025, -0.03]
        sell_thresholds = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
        
        results = []
        
        for buy_thresh in buy_thresholds:
            for sell_thresh in sell_thresholds:
                # Count opportunities at these thresholds
                buys = [s for s in snapshots if s.get('spread_pct', 0) / 100 < buy_thresh]
                sells = [s for s in snapshots if s.get('spread_pct', 0) / 100 > sell_thresh]
                
                # Calculate potential profit
                buy_profit = sum(abs(s.get('spread_pct', 0)) * 0.5 for s in buys)  # $50 trade
                sell_profit = sum(abs(s.get('spread_pct', 0)) * 0.5 for s in sells)
                total_profit = buy_profit + sell_profit
                
                results.append({
                    'buy_threshold': buy_thresh,
                    'sell_threshold': sell_thresh,
                    'buy_opportunities': len(buys),
                    'sell_opportunities': len(sells),
                    'total_opportunities': len(buys) + len(sells),
                    'estimated_profit': round(total_profit, 2)
                })
        
        # Sort by profit
        results.sort(key=lambda x: x['estimated_profit'], reverse=True)
        
        best = results[0] if results else None
        
        return {
            'period': self.config.period,
            'snapshots_analyzed': len(snapshots),
            'best_thresholds': best,
            'top_5_combinations': results[:5],
            'recommendation': f"Buy at {best['buy_threshold']*100:.1f}%, Sell at {best['sell_threshold']*100:.1f}%" if best else "Insufficient data"
        }
    
    def generate_report(self) -> Dict:
        """Generate comprehensive analysis report."""
        return {
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'config': {
                'period': self.config.period,
                'platform': self.config.platform or 'all',
                'history_dir': self.config.history_dir
            },
            'snapshot_analysis': self.analyze_snapshots(),
            'trade_analysis': self.analyze_trades(),
            'pnl_simulation': self.calculate_simulated_pnl(),
            'threshold_optimization': self.find_optimal_thresholds() if self.config.optimize else None
        }


# ============================================================================
# OUTPUT FUNCTIONS
# ============================================================================

def print_report(report: Dict):
    """Print report to console."""
    print("\n" + "=" * 70)
    print(f"=== LP ARBITRAGE ANALYSIS (Last {report['config']['period']}) ===")
    print("=" * 70)
    
    # Snapshot analysis
    snap = report.get('snapshot_analysis', {})
    if snap.get('error'):
        print(f"\n[SNAPSHOTS] {snap['error']}")
    else:
        print(f"\nPlatform: {snap.get('platform', 'all').upper()}")
        print(f"Total snapshots: {snap.get('count', 0)}")
        print(f"Period: {snap.get('first_snapshot', 'N/A')} to {snap.get('last_snapshot', 'N/A')}")
        
        recs = snap.get('recommendations', {})
        print(f"\nOpportunities detected:")
        print(f"  BUY opportunities: {recs.get('buy', 0)}")
        print(f"  SELL opportunities: {recs.get('sell', 0)}")
        print(f"  HOLD (no action): {recs.get('hold', 0)}")
        
        stats = snap.get('spread_stats', {})
        print(f"\nSpread statistics:")
        print(f"  Min spread: {stats.get('min', 0):+.2f}%")
        print(f"  Max spread: {stats.get('max', 0):+.2f}%")
        print(f"  Avg spread: {stats.get('avg', 0):+.2f}%")
        print(f"  Premium observations: {stats.get('premium_count', 0)} (avg: {stats.get('avg_premium', 0):+.2f}%)")
        print(f"  Discount observations: {stats.get('discount_count', 0)} (avg: {stats.get('avg_discount', 0):+.2f}%)")
    
    # Trade analysis
    trades = report.get('trade_analysis', {})
    if trades.get('count', 0) > 0:
        print(f"\nTrade history:")
        print(f"  Total trades: {trades.get('count', 0)}")
        print(f"  Executed: {trades.get('executed_count', 0)}")
        print(f"  Simulated: {trades.get('simulated_count', 0)}")
        print(f"  Total BUY volume: ${trades.get('total_buy_usd', 0):.2f}")
        print(f"  Total SELL volume: ${trades.get('total_sell_usd', 0):.2f}")
        print(f"  Simulated P&L: ${trades.get('simulated_pnl', 0):.2f}")
    
    # P&L simulation
    pnl = report.get('pnl_simulation', {})
    if not pnl.get('error') and pnl.get('opportunities_count', 0) > 0:
        print(f"\nP&L simulation (if all opportunities traded):")
        print(f"  Opportunities: {pnl.get('opportunities_count', 0)}")
        print(f"  Total potential profit: ${pnl.get('total_potential_profit', 0):.2f}")
        print(f"  Avg profit per trade: ${pnl.get('avg_profit_per_trade', 0):.2f}")
    
    # Threshold optimization
    opt = report.get('threshold_optimization')
    if opt and not opt.get('error'):
        print(f"\nOptimal threshold analysis:")
        print(f"  Snapshots analyzed: {opt.get('snapshots_analyzed', 0)}")
        best = opt.get('best_thresholds', {})
        if best:
            print(f"  Best buy threshold: {best.get('buy_threshold', 0)*100:.1f}%")
            print(f"  Best sell threshold: {best.get('sell_threshold', 0)*100:.1f}%")
            print(f"  Opportunities at these thresholds: {best.get('total_opportunities', 0)}")
            print(f"  Estimated profit: ${best.get('estimated_profit', 0):.2f}")
        print(f"\n  Recommendation: {opt.get('recommendation', 'N/A')}")
    
    print("\n" + "=" * 70)


def export_to_csv(report: Dict, output_path: str = None):
    """Export analysis to CSV files."""
    if not output_path:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        output_path = f"./history/lp/analysis_{timestamp}"
    
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    # Export snapshot summary
    snap = report.get('snapshot_analysis', {})
    if snap.get('count', 0) > 0:
        summary_file = f"{output_path}_summary.csv"
        with open(summary_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Period', report['config']['period']])
            writer.writerow(['Platform', snap.get('platform', 'all')])
            writer.writerow(['Total Snapshots', snap.get('count', 0)])
            writer.writerow(['BUY Opportunities', snap['recommendations'].get('buy', 0)])
            writer.writerow(['SELL Opportunities', snap['recommendations'].get('sell', 0)])
            writer.writerow(['Min Spread', snap['spread_stats'].get('min', 0)])
            writer.writerow(['Max Spread', snap['spread_stats'].get('max', 0)])
            writer.writerow(['Avg Spread', snap['spread_stats'].get('avg', 0)])
        print(f"[EXPORT] Summary: {summary_file}")
        
        # Export opportunities
        opportunities = snap.get('buy_opportunities', []) + snap.get('sell_opportunities', [])
        if opportunities:
            opp_file = f"{output_path}_opportunities.csv"
            with open(opp_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['timestamp', 'spread_pct', 'market_price', 'virtual_price'])
                writer.writeheader()
                writer.writerows(opportunities)
            print(f"[EXPORT] Opportunities: {opp_file}")


def export_to_json(report: Dict, output_path: str = None):
    """Export analysis to JSON file."""
    if not output_path:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        output_path = f"./history/lp/analysis_{timestamp}.json"
    
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"[EXPORT] JSON: {output_path}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point."""
    config = parse_args()
    
    # Check if history directory exists
    if not os.path.exists(config.history_dir):
        print(f"[ERROR] History directory not found: {config.history_dir}")
        print("[INFO] Run lp_arbitrage.py first to collect data")
        sys.exit(1)
    
    # Initialize analyzer
    analyzer = LPAnalyzer(config)
    
    # Generate report
    print("[ANALYZING] Loading history data...")
    report = analyzer.generate_report()
    
    # Output
    if config.export == 'csv':
        export_to_csv(report)
    elif config.export == 'json':
        export_to_json(report)
    else:
        print_report(report)
    
    return report


if __name__ == "__main__":
    main()
