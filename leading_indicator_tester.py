#!/usr/bin/env python3
"""
Leading Indicator Performance Tester

Validates the predictive accuracy of discovered leading indicator pairs through
paper trading simulations. Monitors leader price movements and executes simulated
trades on the follower coin based on the correlation relationship.

Usage:
    # Basic test
    python leading_indicator_tester.py --pair BTC:ETH

    # With custom timing
    python leading_indicator_tester.py --pair BTC:ETH --sample-interval 15 --execution-pct 70

    # Limited duration
    python leading_indicator_tester.py --pair BTC:ETH --duration 24h

    # Verbose mode
    python leading_indicator_tester.py --pair BTC:ETH --verbose
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from coingeckoutil import get_multiple_prices, get_coingecko_price

# Supported exchanges for price fetching
SUPPORTED_EXCHANGES = ['coingecko', 'jupiter', 'coinbase']
DEFAULT_EXCHANGE = 'coingecko'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Time Duration Parsing (shared with correlation_tracker.py)
# ============================================================================

def parse_duration(value: str) -> int:
    """
    Parse a duration string into seconds.
    
    Supported formats:
        - Plain number: interpreted as seconds (e.g., "30" -> 30)
        - Number + 's'/'sec': seconds (e.g., "30s" -> 30)
        - Number + 'm'/'min': minutes (e.g., "5m" -> 300)
        - Number + 'h'/'hr': hours (e.g., "1h" -> 3600)
        - Number + 'd'/'day'/'days': days (e.g., "7d" -> 604800)
    """
    if value is None:
        return None
    
    value = str(value).strip().lower()
    
    if not value:
        raise ValueError("Empty duration string")
    
    # Try plain number first (default to seconds)
    try:
        return int(value)
    except ValueError:
        pass
    
    # Parse with unit suffix
    import re
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hr|d|days?)s?$', value)
    
    if not match:
        raise ValueError(f"Invalid duration format: '{value}'. Use formats like: 30, 30s, 5m, 1h, 7d")
    
    amount = float(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        's': 1, 'sec': 1,
        'm': 60, 'min': 60,
        'h': 3600, 'hr': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
    }
    
    return int(amount * multipliers[unit])


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds >= 86400:
        days = seconds // 86400
        remaining = seconds % 86400
        if remaining >= 3600:
            hours = remaining // 3600
            return f"{days}d {hours}h"
        return f"{days}d"
    elif seconds >= 3600:
        hours = seconds // 3600
        remaining = seconds % 3600
        if remaining >= 60:
            mins = remaining // 60
            return f"{hours}h {mins}m"
        return f"{hours}h"
    elif seconds >= 60:
        mins = seconds // 60
        remaining = seconds % 60
        if remaining > 0:
            return f"{mins}m {remaining}s"
        return f"{mins}m"
    else:
        return f"{seconds}s"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PairConfig:
    """Configuration loaded from discovery report."""
    leader: str
    follower: str
    optimal_lag_seconds: int
    correlation: float  # Sign indicates direction
    confidence: float
    data_range_end: str
    stronger_direction: Optional[str] = None  # 'up', 'down', or 'symmetric' from directional analysis


@dataclass
class TesterConfig:
    """Runtime configuration."""
    pair_config: PairConfig
    sample_interval: int = 30
    execution_pct: int = 80  # Execute trade at this % of lag time
    trade_frequency: int = 240
    min_move_pct: float = 0.5
    position_size_usd: float = 1000.0
    output_path: str = './paper_trades/'
    duration_seconds: Optional[int] = None
    verbose: bool = False
    dry_run: bool = False
    max_data_age_hours: int = 24
    leader_exchange: str = 'coingecko'  # Exchange for leader price data
    follower_exchange: str = 'jupiter'  # Exchange for follower price data (also used for trading)
    honor_directionality: bool = True  # Only trade in the stronger direction from analysis
    age_check_interval_hours: float = 1.0  # How often to check data age
    min_win_rate: float = 0.5  # Minimum win rate before action
    win_rate_window: int = 10  # Number of recent trades to evaluate
    auto_refresh: bool = False  # Auto re-run analyzer on breach
    report_path: str = './correlation_data/discovery_report.json'  # Path to discovery report


@dataclass
class PriceSnapshot:
    """A price observation."""
    symbol: str
    price: float
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'price': self.price,
            'timestamp': self.timestamp.isoformat()
        }


# ============================================================================
# Multi-Exchange Price Fetching
# ============================================================================

def get_jupiter_price(symbol: str) -> Optional[float]:
    """Get price from Jupiter Price API V3.
    
    Args:
        symbol: Token symbol (must be a Solana token).
    
    Returns:
        USD price or None if not found.
    """
    try:
        # Import Jupiter utilities
        from dex.token_cache import get_mint_with_fallback
        import httpx
        
        # Get mint address for the symbol
        mint = get_mint_with_fallback(symbol)
        if not mint:
            logger.warning(f"[JUPITER] No mint address found for {symbol}")
            return None
        
        # Query Jupiter Price API V3
        api_key = os.environ.get('JUPITER_API_KEY')
        headers = {'x-api-key': api_key} if api_key else {}
        url = f"https://api.jup.ag/price/v3?ids={mint}"
        
        response = httpx.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if mint in data and 'usdPrice' in data[mint]:
            return float(data[mint]['usdPrice'])
        
        logger.warning(f"[JUPITER] No price data for {symbol} ({mint})")
        return None
        
    except ImportError:
        logger.error("[JUPITER] Jupiter dependencies not available (install dex package)")
        return None
    except Exception as e:
        logger.error(f"[JUPITER] Price fetch error for {symbol}: {e}")
        return None


def get_coinbase_price(symbol: str) -> Optional[float]:
    """Get price from Coinbase API.
    
    Args:
        symbol: Token symbol (e.g., BTC, ETH).
    
    Returns:
        USD price or None if not found.
    """
    try:
        import httpx
        
        # Coinbase uses product IDs like BTC-USD
        product_id = f"{symbol.upper()}-USD"
        url = f"https://api.coinbase.com/v2/prices/{product_id}/spot"
        
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and 'amount' in data['data']:
            return float(data['data']['amount'])
        
        logger.warning(f"[COINBASE] No price data for {symbol}")
        return None
        
    except Exception as e:
        logger.error(f"[COINBASE] Price fetch error for {symbol}: {e}")
        return None


def get_price_from_exchange(symbol: str, exchange: str) -> Optional[float]:
    """Get price from the specified exchange.
    
    Args:
        symbol: Token symbol.
        exchange: Exchange name (coingecko, jupiter, coinbase).
    
    Returns:
        USD price or None if not found.
    """
    exchange = exchange.lower()
    
    if exchange == 'coingecko':
        return get_coingecko_price(symbol)
    elif exchange == 'jupiter':
        return get_jupiter_price(symbol)
    elif exchange == 'coinbase':
        return get_coinbase_price(symbol)
    else:
        logger.error(f"Unknown exchange: {exchange}")
        return None


@dataclass
class TradeSignal:
    """A detected trading signal."""
    leader_t0: PriceSnapshot
    leader_t1: PriceSnapshot
    change_pct: float
    direction: str  # 'rise' or 'fall'
    follower_action: str  # 'BUY' or 'SELL'
    scheduled_execution: datetime
    follower_price_at_signal: float


@dataclass
class PaperTrade:
    """A completed paper trade."""
    id: str
    timestamp: str
    type: str = "paper"
    pair: str = ""
    action: str = ""
    follower: str = ""
    follower_price_at_signal: float = 0.0
    follower_price_at_execution: float = 0.0
    position_size_usd: float = 0.0
    quantity: float = 0.0
    trigger: Dict[str, Any] = field(default_factory=dict)
    timing: Dict[str, Any] = field(default_factory=dict)
    outcome: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# Discovery Report Loader
# ============================================================================

class DiscoveryReportLoader:
    """Loads and parses discovery report JSON files."""
    
    def __init__(self, report_path: str):
        self.report_path = Path(report_path)
    
    def load(self) -> Dict[str, Any]:
        """Load the discovery report."""
        if not self.report_path.exists():
            raise FileNotFoundError(f"Discovery report not found: {self.report_path}")
        
        with open(self.report_path, 'r') as f:
            return json.load(f)
    
    def find_pair(self, leader: str, follower: str) -> Optional[PairConfig]:
        """
        Find a specific pair in the discovery report.
        
        Searches significant_pairs for matching leader:follower.
        Returns the most recent record (by data_range_end).
        """
        report = self.load()
        
        leader = leader.upper()
        follower = follower.upper()
        
        significant_pairs = report.get('significant_pairs', [])
        
        if not significant_pairs:
            logger.warning("No significant pairs found in discovery report")
            return None
        
        # Find matching pairs
        matches = []
        for pair in significant_pairs:
            pair_leader = pair.get('leader', '').upper()
            pair_follower = pair.get('follower', '').upper()
            
            if pair_leader == leader and pair_follower == follower:
                matches.append(pair)
        
        if not matches:
            logger.warning(f"Pair {leader}:{follower} not found in discovery report")
            return None
        
        # Get most recent by data_range_end
        matches.sort(key=lambda x: x.get('data_range_end', ''), reverse=True)
        best_match = matches[0]
        
        # Extract directional analysis if available
        directional = best_match.get('directional_analysis', {})
        stronger_direction = directional.get('stronger_direction', None) if directional else None
        
        # Extract configuration
        return PairConfig(
            leader=leader,
            follower=follower,
            optimal_lag_seconds=best_match.get('optimal_lag_seconds', 
                                               best_match.get('lag_seconds', 120)),
            correlation=best_match.get('correlation', 
                                       best_match.get('correlation_at_optimal', 0.0)),
            confidence=best_match.get('confidence', 
                                      best_match.get('confidence_score', 0.0)),
            data_range_end=best_match.get('data_range_end', ''),
            stronger_direction=stronger_direction
        )
    
    def list_pairs(self) -> List[Tuple[str, str]]:
        """List all available pairs in the discovery report."""
        report = self.load()
        pairs = []
        for pair in report.get('significant_pairs', []):
            leader = pair.get('leader', '')
            follower = pair.get('follower', '')
            if leader and follower:
                pairs.append((leader.upper(), follower.upper()))
        return pairs


# ============================================================================
# Paper Trade Logger
# ============================================================================

class PaperTradeLogger:
    """Logs paper trades to JSON files."""
    
    def __init__(self, output_dir: str, pair: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename from pair (handle multi-pair mode)
        if ':' in pair:
            leader, follower = pair.split(':')
            self.output_file = self.output_dir / f"{leader}_{follower}_trades.json"
        else:
            self.output_file = self.output_dir / f"{pair}_trades.json"
        
        self.trades: List[Dict[str, Any]] = []
        self.start_time = datetime.now(timezone.utc)
        self.pair = pair
        
        # Load existing trades if file exists
        if self.output_file.exists():
            try:
                with open(self.output_file, 'r') as f:
                    data = json.load(f)
                    self.trades = data.get('trades', [])
                    logger.info(f"Loaded {len(self.trades)} existing trades from {self.output_file}")
            except (json.JSONDecodeError, KeyError):
                self.trades = []
    
    def log_trade(self, trade: PaperTrade):
        """Log a paper trade."""
        self.trades.append(trade.to_dict())
        self._save()
        logger.info(f"Trade logged: {trade.action} {trade.follower} @ ${trade.follower_price_at_execution:.2f}")
    
    def update_trade_outcome(self, trade_id: str, outcome: Dict[str, Any]):
        """Update a trade with its outcome after lag period."""
        for trade in self.trades:
            if trade.get('id') == trade_id:
                trade['outcome'] = outcome
                self._save()
                return True
        return False
    
    def _save(self):
        """Save trades to file."""
        summary = self._calculate_summary()
        
        data = {
            'trades': self.trades,
            'summary': summary
        }
        
        with open(self.output_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _calculate_summary(self) -> Dict[str, Any]:
        """Calculate summary statistics."""
        if not self.trades:
            return {
                'pair': self.pair,
                'start_time': self.start_time.isoformat(),
                'total_trades': 0
            }
        
        completed_trades = [t for t in self.trades if t.get('outcome')]
        correct_predictions = sum(1 for t in completed_trades 
                                  if t.get('outcome', {}).get('prediction_correct', False))
        
        total_pnl = sum(t.get('outcome', {}).get('paper_pnl_usd', 0) 
                       for t in completed_trades)
        total_pnl_pct = sum(t.get('outcome', {}).get('paper_pnl_pct', 0) 
                           for t in completed_trades)
        
        accuracy = (correct_predictions / len(completed_trades) * 100) if completed_trades else 0
        
        # Win/loss breakdown
        wins = sum(1 for t in completed_trades 
                   if t.get('outcome', {}).get('paper_pnl_usd', 0) > 0)
        losses = sum(1 for t in completed_trades 
                     if t.get('outcome', {}).get('paper_pnl_usd', 0) < 0)
        breakeven = len(completed_trades) - wins - losses
        
        # BUY vs SELL breakdown
        buy_trades = [t for t in completed_trades if t.get('action') == 'BUY']
        sell_trades = [t for t in completed_trades if t.get('action') == 'SELL']
        
        buy_pnl = sum(t.get('outcome', {}).get('paper_pnl_usd', 0) for t in buy_trades)
        buy_pnl_pct = sum(t.get('outcome', {}).get('paper_pnl_pct', 0) for t in buy_trades)
        buy_wins = sum(1 for t in buy_trades if t.get('outcome', {}).get('paper_pnl_usd', 0) > 0)
        
        sell_pnl = sum(t.get('outcome', {}).get('paper_pnl_usd', 0) for t in sell_trades)
        sell_pnl_pct = sum(t.get('outcome', {}).get('paper_pnl_pct', 0) for t in sell_trades)
        sell_wins = sum(1 for t in sell_trades if t.get('outcome', {}).get('paper_pnl_usd', 0) > 0)
        
        return {
            'pair': self.pair,
            'start_time': self.start_time.isoformat(),
            'end_time': datetime.now(timezone.utc).isoformat(),
            'total_trades': len(self.trades),
            'completed_trades': len(completed_trades),
            'correct_predictions': correct_predictions,
            'accuracy_pct': round(accuracy, 1),
            'total_paper_pnl_usd': round(total_pnl, 2),
            'total_paper_pnl_pct': round(total_pnl_pct, 2),
            # Win/loss breakdown
            'wins': wins,
            'losses': losses,
            'breakeven': breakeven,
            # BUY breakdown
            'buy_count': len(buy_trades),
            'buy_wins': buy_wins,
            'buy_pnl_usd': round(buy_pnl, 2),
            'buy_pnl_pct': round(buy_pnl_pct, 2),
            # SELL breakdown
            'sell_count': len(sell_trades),
            'sell_wins': sell_wins,
            'sell_pnl_usd': round(sell_pnl, 2),
            'sell_pnl_pct': round(sell_pnl_pct, 2)
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get current summary statistics."""
        return self._calculate_summary()


# ============================================================================
# Performance Tester
# ============================================================================

class LeadingIndicatorTester:
    """
    Main tester class that monitors leader price movements and executes
    paper trades on the follower coin.
    """
    
    def __init__(self, config: TesterConfig):
        self.config = config
        self.pair_config = config.pair_config
        self.running = False
        self.last_trade_time: Optional[datetime] = None
        self.pending_outcomes: List[Tuple[str, datetime, str, float, float]] = []
        # (trade_id, outcome_check_time, action, execution_price, position_size)
        
        self.consecutive_failures = 0
        self.max_consecutive_failures = 5
        
        # Trade ID counter
        self.trade_counter = 0
        
        # Initialize logger
        pair_str = f"{self.pair_config.leader}:{self.pair_config.follower}"
        self.logger = PaperTradeLogger(config.output_path, pair_str)
        
        # Staleness and win rate monitoring
        self.last_age_check = datetime.now(timezone.utc)
        self.recent_outcomes: List[bool] = []  # True = win, False = loss
        
        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("\nReceived shutdown signal. Saving partial results...")
        self.running = False
    
    def _generate_trade_id(self) -> str:
        """Generate a unique trade ID."""
        self.trade_counter += 1
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        return f"pt_{timestamp}_{self.trade_counter:03d}"
    
    def _get_prices(self) -> Optional[Dict[str, float]]:
        """Fetch current prices for leader and follower from configured exchanges."""
        try:
            # Fetch leader price from leader exchange
            leader_price = get_price_from_exchange(
                self.pair_config.leader, 
                self.config.leader_exchange
            )
            
            # Fetch follower price from follower exchange
            follower_price = get_price_from_exchange(
                self.pair_config.follower,
                self.config.follower_exchange
            )
            
            if leader_price is None or follower_price is None:
                self.consecutive_failures += 1
                if self.config.verbose:
                    logger.warning(f"Failed to get prices: leader={leader_price} ({self.config.leader_exchange}), "
                                   f"follower={follower_price} ({self.config.follower_exchange})")
                return None
            
            self.consecutive_failures = 0
            return {
                self.pair_config.leader: leader_price,
                self.pair_config.follower: follower_price
            }
            
        except Exception as e:
            self.consecutive_failures += 1
            logger.error(f"Price fetch error: {e}")
            return None
    
    def _calculate_change(self, price_t0: float, price_t1: float) -> Tuple[float, str]:
        """Calculate percentage change and direction."""
        if price_t0 == 0:
            return 0.0, 'flat'
        
        change_pct = ((price_t1 - price_t0) / price_t0) * 100
        
        if change_pct > 0:
            direction = 'rise'
        elif change_pct < 0:
            direction = 'fall'
        else:
            direction = 'flat'
        
        return change_pct, direction
    
    def _determine_action(self, direction: str) -> str:
        """
        Determine follower action based on leader direction and correlation type.
        
        Positive correlation: same direction (rise -> BUY, fall -> SELL)
        Negative correlation: opposite direction (rise -> SELL, fall -> BUY)
        """
        is_positive_correlation = self.pair_config.correlation >= 0
        
        if direction == 'flat':
            return 'NO_ACTION'
        
        if is_positive_correlation:
            return 'BUY' if direction == 'rise' else 'SELL'
        else:
            return 'SELL' if direction == 'rise' else 'BUY'
    
    def _calculate_wait_time(self) -> int:
        """
        Calculate seconds to wait before trade execution.
        
        wait = (lag × execution_pct / 100) - sample_interval
        """
        lag = self.pair_config.optimal_lag_seconds
        execution_time = (lag * self.config.execution_pct / 100)
        wait_time = max(0, execution_time - self.config.sample_interval)
        return int(wait_time)
    
    def _can_trade(self) -> bool:
        """Check if trading is allowed (cooldown period)."""
        if self.last_trade_time is None:
            return True
        
        elapsed = (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
        return elapsed >= self.config.trade_frequency
    
    def _execute_paper_trade(self, signal: TradeSignal) -> PaperTrade:
        """Execute a paper trade based on the signal."""
        now = datetime.now(timezone.utc)
        
        # Get current follower price for execution
        prices = self._get_prices()
        if prices is None:
            execution_price = signal.follower_price_at_signal
        else:
            execution_price = prices.get(self.pair_config.follower, signal.follower_price_at_signal)
        
        # Calculate quantity
        quantity = self.config.position_size_usd / execution_price if execution_price > 0 else 0
        
        trade = PaperTrade(
            id=self._generate_trade_id(),
            timestamp=now.isoformat(),
            type="paper",
            pair=f"{self.pair_config.leader}:{self.pair_config.follower}",
            action=signal.follower_action,
            follower=self.pair_config.follower,
            follower_price_at_signal=signal.follower_price_at_signal,
            follower_price_at_execution=execution_price,
            position_size_usd=self.config.position_size_usd,
            quantity=round(quantity, 6),
            trigger={
                'leader': self.pair_config.leader,
                'leader_price_t0': signal.leader_t0.price,
                'leader_price_t1': signal.leader_t1.price,
                'leader_change_pct': round(signal.change_pct, 3),
                'correlation_direction': 'positive' if self.pair_config.correlation >= 0 else 'negative',
                'expected_follower_direction': signal.direction
            },
            timing={
                'signal_detected_at': signal.leader_t1.timestamp.isoformat(),
                'execution_at': now.isoformat(),
                'lag_seconds': self.pair_config.optimal_lag_seconds,
                'execution_pct': self.config.execution_pct,
                'wait_seconds': self._calculate_wait_time()
            }
        )
        
        # Schedule outcome check
        outcome_time = now + timedelta(seconds=self.pair_config.optimal_lag_seconds - self._calculate_wait_time())
        self.pending_outcomes.append((
            trade.id,
            outcome_time,
            signal.follower_action,
            execution_price,
            self.config.position_size_usd
        ))
        
        self.last_trade_time = now
        return trade
    
    def _check_pending_outcomes(self):
        """Check and record outcomes for trades that have reached their lag period."""
        if not self.pending_outcomes:
            return
        
        now = datetime.now(timezone.utc)
        completed = []
        
        prices = None  # Lazy fetch
        
        for i, (trade_id, outcome_time, action, exec_price, position_size) in enumerate(self.pending_outcomes):
            if now >= outcome_time:
                # Fetch prices if not already fetched
                if prices is None:
                    prices = self._get_prices()
                
                if prices is None:
                    # Can't check outcome, try again later
                    continue
                
                follower_price = prices.get(self.pair_config.follower)
                if follower_price is None:
                    continue
                
                # Calculate outcome
                if action == 'BUY':
                    pnl_pct = ((follower_price - exec_price) / exec_price) * 100
                    prediction_correct = follower_price > exec_price
                else:  # SELL
                    pnl_pct = ((exec_price - follower_price) / exec_price) * 100
                    prediction_correct = follower_price < exec_price
                
                pnl_usd = (pnl_pct / 100) * position_size
                actual_change = ((follower_price - exec_price) / exec_price) * 100
                
                outcome = {
                    'follower_price_after_lag': follower_price,
                    'actual_follower_change_pct': round(actual_change, 3),
                    'prediction_correct': prediction_correct,
                    'paper_pnl_usd': round(pnl_usd, 2),
                    'paper_pnl_pct': round(pnl_pct, 3)
                }
                
                self.logger.update_trade_outcome(trade_id, outcome)
                completed.append(i)
                
                # Record outcome for win rate tracking
                self._record_outcome(prediction_correct)
                
                result_emoji = "✓" if prediction_correct else "✗"
                logger.info(f"Outcome {result_emoji}: {trade_id} - P&L: ${pnl_usd:.2f} ({pnl_pct:.2f}%)")
        
        # Remove completed outcomes (in reverse order to preserve indices)
        for i in reversed(completed):
            self.pending_outcomes.pop(i)
    
    def _print_startup_info(self):
        """Print startup configuration and API rate estimate."""
        pair = self.pair_config
        cfg = self.config
        
        print("\n" + "="*60)
        print("LEADING INDICATOR PERFORMANCE TESTER")
        print("="*60)
        print(f"\nPair: {pair.leader} → {pair.follower}")
        print(f"Correlation: {pair.correlation:.3f} ({'positive' if pair.correlation >= 0 else 'negative'})")
        print(f"Confidence: {pair.confidence:.2f}")
        print(f"Optimal Lag: {format_duration(pair.optimal_lag_seconds)}")
        print(f"Data Range End: {pair.data_range_end}")
        
        # Check data freshness
        if pair.data_range_end:
            try:
                data_end = datetime.fromisoformat(pair.data_range_end.replace('Z', '+00:00'))
                age_hours = (datetime.now(timezone.utc) - data_end).total_seconds() / 3600
                if age_hours > cfg.max_data_age_hours:
                    print(f"\n⚠️  WARNING: Data is {age_hours:.1f} hours old (threshold: {cfg.max_data_age_hours}h)")
            except ValueError:
                pass
        
        print(f"\n--- Configuration ---")
        print(f"Sample Interval: {format_duration(cfg.sample_interval)}")
        print(f"Execution Point: {cfg.execution_pct}% of lag ({format_duration(int(pair.optimal_lag_seconds * cfg.execution_pct / 100))})")
        print(f"Trade Cooldown: {format_duration(cfg.trade_frequency)}")
        print(f"Min Move Threshold: {cfg.min_move_pct}%")
        print(f"Position Size: ${cfg.position_size_usd:.2f}")
        print(f"Output: {cfg.output_path}")
        
        # Directionality setting
        if cfg.honor_directionality:
            if pair.stronger_direction and pair.stronger_direction != 'symmetric':
                print(f"Directionality: Only trading on {pair.stronger_direction.upper()} moves")
            else:
                print(f"Directionality: Trading both directions (symmetric or no data)")
        else:
            print(f"Directionality: Disabled (trading both directions)")
        
        # Win rate monitoring
        print(f"\n--- Performance Monitoring ---")
        print(f"Min Win Rate: {cfg.min_win_rate*100:.0f}% (over last {cfg.win_rate_window} trades)")
        print(f"Auto-Refresh: {'Yes (will refresh analyzer on breach)' if cfg.auto_refresh else 'No (will stop on breach)'}")
        print(f"Age Check Interval: {cfg.age_check_interval_hours}h")
        
        print(f"\n--- Price Sources ---")
        print(f"Leader ({pair.leader}): {cfg.leader_exchange}")
        print(f"Follower ({pair.follower}): {cfg.follower_exchange}")
        
        if cfg.duration_seconds:
            print(f"Duration: {format_duration(cfg.duration_seconds)}")
        else:
            print("Duration: Indefinite (Ctrl+C to stop)")
        
        # API rate estimate
        calls_per_minute = 60 / cfg.sample_interval
        calls_per_hour = calls_per_minute * 60
        calls_per_day = calls_per_hour * 24
        
        print(f"\n--- API Call Estimate ---")
        print(f"Calls per minute: {calls_per_minute:.1f}")
        print(f"Calls per hour: {calls_per_hour:.0f}")
        print(f"Calls per day: {calls_per_day:.0f}")
        
        if calls_per_day > 500:
            print(f"⚠️  WARNING: Exceeds free tier (~500/day). Consider:")
            print(f"   - Increasing --sample-interval")
            print(f"   - Using paid CoinGecko API")
        
        print("="*60 + "\n")
    
    def _check_data_age(self) -> bool:
        """Check if data age warning should be shown. Returns True if check was performed."""
        now = datetime.now(timezone.utc)
        hours_since_check = (now - self.last_age_check).total_seconds() / 3600
        
        if hours_since_check < self.config.age_check_interval_hours:
            return False
        
        self.last_age_check = now
        
        if self.pair_config.data_range_end:
            try:
                data_end = datetime.fromisoformat(self.pair_config.data_range_end.replace('Z', '+00:00'))
                age_hours = (now - data_end).total_seconds() / 3600
                if age_hours > self.config.max_data_age_hours:
                    logger.warning(f"⚠️  Data is now {age_hours:.1f} hours old (threshold: {self.config.max_data_age_hours}h)")
            except ValueError:
                pass
        
        return True
    
    def _get_rolling_win_rate(self) -> Optional[float]:
        """Calculate win rate over the recent window. Returns None if not enough trades."""
        if len(self.recent_outcomes) < self.config.win_rate_window:
            return None
        
        # Use last N outcomes
        window = self.recent_outcomes[-self.config.win_rate_window:]
        return sum(window) / len(window)
    
    def _record_outcome(self, is_win: bool):
        """Record a trade outcome for win rate tracking."""
        self.recent_outcomes.append(is_win)
        # Keep list bounded
        if len(self.recent_outcomes) > self.config.win_rate_window * 2:
            self.recent_outcomes = self.recent_outcomes[-self.config.win_rate_window:]
    
    def _refresh_analyzer_data(self) -> bool:
        """Run the correlation analyzer to refresh data. Returns True on success."""
        import subprocess
        
        logger.info("🔄 Running correlation analyzer to refresh data...")
        
        try:
            # Run analyzer with same parameters
            cmd = [
                'python', 'correlation_tracker.py',
                '--analyze',
                '--recent', f'{self.config.max_data_age_hours}hr',
                '--min-confidence', '0.58',
                '--min-samples', '250'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"Analyzer failed: {result.stderr[:500]}")
                return False
            
            logger.info("✓ Analyzer completed successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Analyzer timed out after 5 minutes")
            return False
        except Exception as e:
            logger.error(f"Failed to run analyzer: {e}")
            return False
    
    def _reload_pair_config(self) -> bool:
        """Reload pair configuration from discovery report. Returns True on success."""
        try:
            loader = DiscoveryReportLoader(self.config.report_path)
            new_config = loader.find_pair(self.pair_config.leader, self.pair_config.follower)
            
            if new_config is None:
                logger.error(f"Pair {self.pair_config.leader}:{self.pair_config.follower} no longer in discovery report")
                return False
            
            # Update pair config
            self.pair_config = new_config
            self.config.pair_config = new_config
            
            logger.info(f"✓ Reloaded config: correlation={new_config.correlation:.3f}, "
                       f"lag={new_config.optimal_lag_seconds}s, confidence={new_config.confidence:.2f}")
            
            # Reset win rate tracking after refresh
            self.recent_outcomes = []
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to reload config: {e}")
            return False
    
    def _handle_win_rate_breach(self) -> bool:
        """Handle win rate falling below threshold. Returns True to continue, False to stop."""
        win_rate = self._get_rolling_win_rate()
        
        if win_rate is None:
            return True  # Not enough data yet
        
        if win_rate >= self.config.min_win_rate:
            return True  # Win rate is acceptable
        
        logger.warning(f"⚠️  Win rate {win_rate*100:.1f}% is below threshold {self.config.min_win_rate*100:.0f}%")
        
        if not self.config.auto_refresh:
            logger.error("Stopping due to low win rate (auto-refresh disabled)")
            return False
        
        # Try to refresh
        logger.info("Attempting auto-refresh...")
        
        if not self._refresh_analyzer_data():
            logger.error("Auto-refresh failed. Stopping.")
            return False
        
        if not self._reload_pair_config():
            logger.error("Failed to reload config after refresh. Stopping.")
            return False
        
        logger.info("✓ Auto-refresh complete. Resuming with new configuration.")
        return True
    
    def run(self):
        """Run the monitoring and trading loop."""
        self._print_startup_info()
        
        if self.config.dry_run:
            print("DRY RUN MODE - No trades will be executed")
            return
        
        self.running = True
        start_time = time.time()
        
        # Get initial price
        logger.info("Fetching initial prices...")
        prices = self._get_prices()
        
        if prices is None:
            logger.error("Failed to fetch initial prices. Exiting.")
            return
        
        leader_t0 = PriceSnapshot(
            symbol=self.pair_config.leader,
            price=prices[self.pair_config.leader],
            timestamp=datetime.now(timezone.utc)
        )
        
        logger.info(f"Initial {self.pair_config.leader}: ${leader_t0.price:.2f}")
        logger.info(f"Initial {self.pair_config.follower}: ${prices[self.pair_config.follower]:.2f}")
        logger.info("Starting monitoring loop...\n")
        
        try:
            while self.running:
                # Check pending outcomes
                self._check_pending_outcomes()
                
                # Periodic data age check
                self._check_data_age()
                
                # Check win rate and handle breach
                if not self._handle_win_rate_breach():
                    logger.info("Exiting due to win rate breach.")
                    break
                
                # Wait for sample interval (in small chunks to allow graceful shutdown)
                sleep_remaining = self.config.sample_interval
                while sleep_remaining > 0 and self.running:
                    chunk = min(sleep_remaining, 5)  # Sleep max 5 seconds at a time
                    time.sleep(chunk)
                    sleep_remaining -= chunk
                
                if not self.running:
                    break
                
                # Check duration limit
                if self.config.duration_seconds:
                    elapsed = time.time() - start_time
                    if elapsed >= self.config.duration_seconds:
                        logger.info(f"Duration limit reached ({format_duration(self.config.duration_seconds)})")
                        break
                
                # Check for too many consecutive failures
                if self.consecutive_failures >= self.max_consecutive_failures:
                    logger.error(f"Too many consecutive failures ({self.consecutive_failures}). API may be down.")
                    break
                
                # Get new prices
                prices = self._get_prices()
                if prices is None:
                    if self.config.verbose:
                        logger.warning("Skipping cycle due to price fetch failure")
                    continue
                
                # Create T1 snapshot
                leader_t1 = PriceSnapshot(
                    symbol=self.pair_config.leader,
                    price=prices[self.pair_config.leader],
                    timestamp=datetime.now(timezone.utc)
                )
                
                follower_price = prices[self.pair_config.follower]
                
                # Calculate change
                change_pct, direction = self._calculate_change(leader_t0.price, leader_t1.price)
                
                if self.config.verbose:
                    logger.info(f"{self.pair_config.leader}: ${leader_t0.price:.2f} → ${leader_t1.price:.2f} ({change_pct:+.3f}%)")
                
                # Check directionality filter FIRST (before size check)
                # This ensures "wrong direction" is reported instead of misleading "move too small"
                if self.config.honor_directionality and self.pair_config.stronger_direction:
                    stronger = self.pair_config.stronger_direction
                    # Map direction to stronger_direction format: 'rise' -> 'up', 'fall' -> 'down'
                    move_direction = 'up' if direction == 'rise' else 'down'
                    
                    if stronger != 'symmetric' and stronger != move_direction:
                        if self.config.verbose:
                            logger.debug(f"Wrong direction: {direction} (only trading on {stronger})")
                        leader_t0 = leader_t1
                        continue
                
                # Check if significant move
                if abs(change_pct) < self.config.min_move_pct:
                    if self.config.verbose:
                        logger.debug(f"Move too small ({abs(change_pct):.3f}% < {self.config.min_move_pct}%)")
                    # Update T0 for next cycle
                    leader_t0 = leader_t1
                    continue
                
                # Significant move detected in correct direction
                logger.info(f"Significant move detected: {self.pair_config.leader} {direction.upper()} {abs(change_pct):.2f}%")
                
                # Check cooldown
                if not self._can_trade():
                    remaining = self.config.trade_frequency - (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
                    logger.info(f"Trade cooldown active ({format_duration(int(remaining))} remaining)")
                    leader_t0 = leader_t1
                    continue
                
                # Determine action
                action = self._determine_action(direction)
                
                if action == 'NO_ACTION':
                    leader_t0 = leader_t1
                    continue
                
                # Create signal
                signal = TradeSignal(
                    leader_t0=leader_t0,
                    leader_t1=leader_t1,
                    change_pct=change_pct,
                    direction=direction,
                    follower_action=action,
                    scheduled_execution=datetime.now(timezone.utc) + timedelta(seconds=self._calculate_wait_time()),
                    follower_price_at_signal=follower_price
                )
                
                # Wait for execution time
                wait_time = self._calculate_wait_time()
                if wait_time > 0:
                    logger.info(f"Waiting {format_duration(wait_time)} before {action} {self.pair_config.follower}...")
                    time.sleep(wait_time)
                
                # Execute paper trade
                trade = self._execute_paper_trade(signal)
                self.logger.log_trade(trade)
                
                print(f"\n{'='*40}")
                print(f"PAPER TRADE EXECUTED")
                print(f"{'='*40}")
                print(f"Action: {trade.action} {trade.follower}")
                print(f"Price: ${trade.follower_price_at_execution:.4f}")
                print(f"Size: ${trade.position_size_usd:.2f} ({trade.quantity:.6f} {trade.follower})")
                print(f"Trigger: {self.pair_config.leader} {direction} {abs(change_pct):.2f}%")
                print(f"Outcome check in: {format_duration(self.pair_config.optimal_lag_seconds - wait_time)}")
                print(f"{'='*40}\n")
                
                # Post-trade pause: wait for remaining lag time before checking prices again
                # This avoids wasteful API calls since outcome won't materialize until lag passes
                # Also handles short lags: if remaining_lag < sample_interval, use remaining_lag
                # to avoid waiting too long before the next trade opportunity
                remaining_lag = self.pair_config.optimal_lag_seconds - wait_time
                if remaining_lag > 0:
                    # Use remaining_lag as pause time (whether shorter or longer than sample_interval)
                    pause_time = remaining_lag
                    if pause_time != self.config.sample_interval:
                        logger.info(f"Post-trade pause: waiting {format_duration(int(pause_time))} for outcome window...")
                    
                    # Sleep in chunks to allow graceful shutdown
                    pause_remaining = pause_time
                    while pause_remaining > 0 and self.running:
                        chunk = min(pause_remaining, 5)
                        time.sleep(chunk)
                        pause_remaining -= chunk
                    
                    if not self.running:
                        break
                    
                    # Get fresh prices after pause
                    prices = self._get_prices()
                    if prices is not None:
                        leader_t0 = PriceSnapshot(
                            symbol=self.pair_config.leader,
                            price=prices[self.pair_config.leader],
                            timestamp=datetime.now(timezone.utc)
                        )
                        continue  # Skip normal T0 update below
                
                # Update T0 for next cycle
                leader_t0 = leader_t1
                
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
        
        # Final outcome check
        logger.info("Checking remaining outcomes...")
        time.sleep(2)  # Brief wait for any pending outcomes
        self._check_pending_outcomes()
        
        # Print summary
        summary = self.logger.get_summary()
        print("\n" + "="*60)
        print("SESSION SUMMARY")
        print("="*60)
        print(f"Pair: {summary['pair']}")
        print(f"Total Trades: {summary['total_trades']}")
        print(f"Completed: {summary.get('completed_trades', 0)}")
        if summary.get('completed_trades', 0) > 0:
            wins = summary.get('wins', 0)
            losses = summary.get('losses', 0)
            print(f"Win/Loss: {wins}W / {losses}L ({summary['accuracy_pct']:.1f}%)")
            print(f"Total P&L: ${summary['total_paper_pnl_usd']:.2f} ({summary['total_paper_pnl_pct']:.2f}%)")
            
            # BUY vs SELL breakdown
            buy_count = summary.get('buy_count', 0)
            sell_count = summary.get('sell_count', 0)
            if buy_count > 0 or sell_count > 0:
                print("-" * 40)
                print("By Direction:")
                if buy_count > 0:
                    buy_wins = summary.get('buy_wins', 0)
                    buy_pnl = summary.get('buy_pnl_usd', 0)
                    buy_pnl_pct = summary.get('buy_pnl_pct', 0)
                    print(f"  BUY:  {buy_count} trades, {buy_wins}W / {buy_count - buy_wins}L, "
                          f"P&L: ${buy_pnl:.2f} ({buy_pnl_pct:.2f}%)")
                if sell_count > 0:
                    sell_wins = summary.get('sell_wins', 0)
                    sell_pnl = summary.get('sell_pnl_usd', 0)
                    sell_pnl_pct = summary.get('sell_pnl_pct', 0)
                    print(f"  SELL: {sell_count} trades, {sell_wins}W / {sell_count - sell_wins}L, "
                          f"P&L: ${sell_pnl:.2f} ({sell_pnl_pct:.2f}%)")
        print(f"Output: {self.logger.output_file}")
        print("="*60 + "\n")


# ============================================================================
# Multi-Pair Tester
# ============================================================================

class MultiPairTester:
    """
    Tests multiple pairs simultaneously with global cooldown and batched price fetching.
    Paper trading mode only.
    """
    
    def __init__(
        self,
        pair_configs: List[PairConfig],
        sample_interval: int,
        execution_pct: int,
        trade_frequency: int,
        min_move_pct: float,
        position_size_usd: float,
        output_path: str,
        duration_seconds: Optional[int],
        verbose: bool,
        dry_run: bool,
        max_data_age_hours: int,
        leader_exchange: str,
        follower_exchange: str,
        honor_directionality: bool,
        min_win_rate: float,
        win_rate_window: int,
        report_path: str
    ):
        self.pair_configs = pair_configs
        self.sample_interval = sample_interval
        self.execution_pct = execution_pct
        self.trade_frequency = trade_frequency
        self.min_move_pct = min_move_pct
        self.position_size_usd = position_size_usd
        self.output_path = output_path
        self.duration_seconds = duration_seconds
        self.verbose = verbose
        self.dry_run = dry_run
        self.max_data_age_hours = max_data_age_hours
        self.leader_exchange = leader_exchange
        self.follower_exchange = follower_exchange
        self.honor_directionality = honor_directionality
        self.min_win_rate = min_win_rate
        self.win_rate_window = win_rate_window
        self.report_path = report_path
        
        self.running = False
        self.last_trade_time: Optional[datetime] = None  # Global cooldown
        self.trade_counter = 0
        
        # Per-pair tracking
        self.pair_stats: Dict[str, Dict] = {}
        self.pair_t0: Dict[str, PriceSnapshot] = {}  # Last T0 per pair
        self.pending_outcomes: List[Tuple[str, str, datetime, str, float, float]] = []
        # (pair_key, trade_id, outcome_check_time, action, execution_price, position_size)
        
        for pc in pair_configs:
            key = f"{pc.leader}:{pc.follower}"
            self.pair_stats[key] = {
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'pnl_usd': 0.0,
                'recent_outcomes': []  # For per-pair win rate
            }
        
        # Initialize logger (single file for all pairs)
        self.logger = PaperTradeLogger(output_path, "MULTI_PAIR")
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info("\nReceived shutdown signal. Saving partial results...")
        self.running = False
    
    def _generate_trade_id(self, pair_key: str) -> str:
        self.trade_counter += 1
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        return f"mp_{pair_key.replace(':', '_')}_{timestamp}_{self.trade_counter:03d}"
    
    def _get_all_prices(self) -> Optional[Dict[str, float]]:
        """Batch fetch prices for all unique symbols."""
        # Collect unique symbols by exchange
        coingecko_symbols = set()
        jupiter_symbols = set()
        
        for pc in self.pair_configs:
            if self.leader_exchange == 'coingecko':
                coingecko_symbols.add(pc.leader)
            else:
                jupiter_symbols.add(pc.leader)
            
            if self.follower_exchange == 'coingecko':
                coingecko_symbols.add(pc.follower)
            else:
                jupiter_symbols.add(pc.follower)
        
        prices = {}
        
        # Fetch CoinGecko prices
        for symbol in coingecko_symbols:
            price = get_coingecko_price(symbol)
            if price is not None:
                prices[symbol] = price
        
        # Fetch Jupiter prices
        for symbol in jupiter_symbols:
            price = get_jupiter_price(symbol)
            if price is not None:
                prices[symbol] = price
        
        return prices if prices else None
    
    def _can_trade(self) -> bool:
        """Check global cooldown."""
        if self.last_trade_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
        return elapsed >= self.trade_frequency
    
    def _calculate_change(self, price_t0: float, price_t1: float) -> Tuple[float, str]:
        if price_t0 == 0:
            return 0.0, 'flat'
        change_pct = ((price_t1 - price_t0) / price_t0) * 100
        if change_pct > 0:
            return change_pct, 'rise'
        elif change_pct < 0:
            return change_pct, 'fall'
        return 0.0, 'flat'
    
    def _determine_action(self, direction: str, correlation: float) -> str:
        if correlation > 0:
            return 'BUY' if direction == 'rise' else 'SELL'
        else:
            return 'SELL' if direction == 'rise' else 'BUY'
    
    def _print_startup_info(self):
        print("\n" + "="*60)
        print("MULTI-PAIR LEADING INDICATOR TESTER")
        print("="*60)
        
        print(f"\nPairs ({len(self.pair_configs)}):")
        for pc in self.pair_configs:
            dir_str = f", {pc.stronger_direction} only" if pc.stronger_direction and pc.stronger_direction != 'symmetric' else ""
            print(f"  - {pc.leader} → {pc.follower} (lag: {format_duration(pc.optimal_lag_seconds)}, corr: {pc.correlation:.3f}{dir_str})")
        
        print(f"\n--- Configuration ---")
        print(f"Sample Interval: {format_duration(self.sample_interval)}")
        print(f"Execution Point: {self.execution_pct}% of lag")
        print(f"Trade Cooldown: {format_duration(self.trade_frequency)} (global)")
        print(f"Min Move Threshold: {self.min_move_pct}%")
        print(f"Position Size: ${self.position_size_usd:.2f}")
        print(f"Honor Directionality: {'Yes' if self.honor_directionality else 'No'}")
        
        if self.duration_seconds:
            print(f"Duration: {format_duration(self.duration_seconds)}")
        
        print("="*60 + "\n")
    
    def _check_pending_outcomes(self, prices: Dict[str, float]):
        """Check and resolve pending trade outcomes."""
        now = datetime.now(timezone.utc)
        resolved = []
        
        for i, (pair_key, trade_id, outcome_time, action, entry_price, position_size) in enumerate(self.pending_outcomes):
            if now >= outcome_time:
                # Find the follower symbol
                follower = pair_key.split(':')[1]
                current_price = prices.get(follower)
                
                if current_price is not None:
                    # Calculate outcome
                    if action == 'BUY':
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    else:  # SELL
                        pnl_pct = ((entry_price - current_price) / entry_price) * 100
                    
                    pnl_usd = position_size * (pnl_pct / 100)
                    is_win = pnl_usd > 0
                    
                    # Update stats
                    self.pair_stats[pair_key]['pnl_usd'] += pnl_usd
                    if is_win:
                        self.pair_stats[pair_key]['wins'] += 1
                    else:
                        self.pair_stats[pair_key]['losses'] += 1
                    
                    # Track for win rate
                    self.pair_stats[pair_key]['recent_outcomes'].append(is_win)
                    if len(self.pair_stats[pair_key]['recent_outcomes']) > self.win_rate_window:
                        self.pair_stats[pair_key]['recent_outcomes'].pop(0)
                    
                    outcome_str = "WIN" if is_win else "LOSS"
                    logger.info(f"[{pair_key}] Outcome: {outcome_str} ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)")
                    
                    resolved.append(i)
        
        # Remove resolved outcomes (in reverse order to preserve indices)
        for i in reversed(resolved):
            self.pending_outcomes.pop(i)
    
    def _print_summary(self):
        print("\n" + "="*60)
        print("MULTI-PAIR SESSION SUMMARY")
        print("="*60)
        print(f"{'Pair':<15} | {'Trades':>6} | {'Wins':>4} | {'Win Rate':>8} | {'P&L':>10}")
        print("-"*60)
        
        total_trades = 0
        total_wins = 0
        total_pnl = 0.0
        
        for pair_key, stats in self.pair_stats.items():
            trades = stats['trades']
            wins = stats['wins']
            pnl = stats['pnl_usd']
            
            total_trades += trades
            total_wins += wins
            total_pnl += pnl
            
            if trades > 0:
                win_rate = f"{(wins/trades)*100:.1f}%"
                pnl_str = f"${pnl:+.2f}"
            else:
                win_rate = "-"
                pnl_str = "$0.00"
            
            print(f"{pair_key:<15} | {trades:>6} | {wins:>4} | {win_rate:>8} | {pnl_str:>10}")
        
        print("="*60)
        if total_trades > 0:
            total_win_rate = f"{(total_wins/total_trades)*100:.1f}%"
        else:
            total_win_rate = "-"
        print(f"{'Total':<15} | {total_trades:>6} | {total_wins:>4} | {total_win_rate:>8} | ${total_pnl:+.2f}")
        print("="*60)
        print(f"Output: {self.logger.output_file}")
        print("="*60 + "\n")
    
    def run(self):
        """Run the multi-pair tester."""
        self._print_startup_info()
        
        if self.dry_run:
            print("DRY RUN - No trades will be executed")
            return
        
        self.running = True
        start_time = datetime.now(timezone.utc)
        
        # Initial price fetch
        prices = self._get_all_prices()
        if prices is None:
            logger.error("Failed to fetch initial prices")
            return
        
        # Initialize T0 for all pairs
        for pc in self.pair_configs:
            key = f"{pc.leader}:{pc.follower}"
            if pc.leader in prices:
                self.pair_t0[key] = PriceSnapshot(
                    symbol=pc.leader,
                    price=prices[pc.leader],
                    timestamp=datetime.now(timezone.utc)
                )
        
        logger.info("Starting multi-pair monitoring loop...")
        
        try:
            while self.running:
                # Check duration limit
                if self.duration_seconds:
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    if elapsed >= self.duration_seconds:
                        logger.info("Duration limit reached")
                        break
                
                # Wait for sample interval
                time.sleep(self.sample_interval)
                
                if not self.running:
                    break
                
                # Fetch prices
                prices = self._get_all_prices()
                if prices is None:
                    if self.verbose:
                        logger.warning("Skipping cycle due to price fetch failure")
                    continue
                
                # Check pending outcomes
                self._check_pending_outcomes(prices)
                
                # Process each pair
                for pc in self.pair_configs:
                    key = f"{pc.leader}:{pc.follower}"
                    
                    # Skip if no T0 or missing prices
                    if key not in self.pair_t0:
                        continue
                    if pc.leader not in prices or pc.follower not in prices:
                        continue
                    
                    t0 = self.pair_t0[key]
                    t1_price = prices[pc.leader]
                    
                    # Calculate change
                    change_pct, direction = self._calculate_change(t0.price, t1_price)
                    
                    if self.verbose:
                        logger.info(f"[{key}] {pc.leader}: ${t0.price:.2f} → ${t1_price:.2f} ({change_pct:+.3f}%)")
                    
                    # Update T0 for next cycle
                    self.pair_t0[key] = PriceSnapshot(
                        symbol=pc.leader,
                        price=t1_price,
                        timestamp=datetime.now(timezone.utc)
                    )
                    
                    # Check directionality filter FIRST
                    if self.honor_directionality and pc.stronger_direction:
                        move_direction = 'up' if direction == 'rise' else 'down'
                        if pc.stronger_direction != 'symmetric' and pc.stronger_direction != move_direction:
                            if self.verbose:
                                logger.debug(f"[{key}] Wrong direction: {direction} (only trading on {pc.stronger_direction})")
                            continue
                    
                    # Check if significant move
                    if abs(change_pct) < self.min_move_pct:
                        if self.verbose:
                            logger.debug(f"[{key}] Move too small ({abs(change_pct):.3f}% < {self.min_move_pct}%)")
                        continue
                    
                    # Check global cooldown
                    if not self._can_trade():
                        remaining = self.trade_frequency - (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
                        logger.info(f"[{key}] Trade cooldown active ({format_duration(int(remaining))} remaining)")
                        continue
                    
                    # Significant move detected
                    logger.info(f"[{key}] Significant move: {pc.leader} {direction.upper()} {abs(change_pct):.2f}%")
                    
                    # Determine action
                    action = self._determine_action(direction, pc.correlation)
                    
                    # Calculate execution wait
                    wait_time = int(pc.optimal_lag_seconds * (self.execution_pct / 100))
                    
                    logger.info(f"[{key}] Waiting {format_duration(wait_time)} before {action} {pc.follower}...")
                    time.sleep(wait_time)
                    
                    # Execute paper trade
                    follower_price = prices.get(pc.follower)
                    if follower_price is None:
                        logger.warning(f"[{key}] Failed to get follower price for trade")
                        continue
                    
                    trade_id = self._generate_trade_id(key)
                    quantity = self.position_size_usd / follower_price
                    
                    # Record trade
                    self.pair_stats[key]['trades'] += 1
                    self.last_trade_time = datetime.now(timezone.utc)
                    
                    # Schedule outcome check
                    outcome_time = datetime.now(timezone.utc) + timedelta(
                        seconds=pc.optimal_lag_seconds - wait_time
                    )
                    self.pending_outcomes.append(
                        (key, trade_id, outcome_time, action, follower_price, self.position_size_usd)
                    )
                    
                    # Log trade
                    trade = PaperTrade(
                        id=trade_id,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        pair=key,
                        action=action,
                        follower=pc.follower,
                        follower_price_at_signal=follower_price,
                        follower_price_at_execution=follower_price,
                        position_size_usd=self.position_size_usd,
                        quantity=quantity,
                        trigger={
                            'leader': pc.leader,
                            'leader_t0': t0.to_dict(),
                            'leader_t1': {'symbol': pc.leader, 'price': t1_price, 'timestamp': datetime.now(timezone.utc).isoformat()},
                            'change_pct': change_pct,
                            'direction': direction
                        },
                        timing={
                            'optimal_lag_seconds': pc.optimal_lag_seconds,
                            'execution_lag_seconds': wait_time,
                            'execution_pct': self.execution_pct
                        }
                    )
                    self.logger.log_trade(trade)
                    
                    print(f"\n{'='*40}")
                    print(f"[{key}] PAPER TRADE EXECUTED")
                    print(f"{'='*40}")
                    print(f"Action: {action} {pc.follower}")
                    print(f"Price: ${follower_price:.4f}")
                    print(f"Size: ${self.position_size_usd:.2f}")
                    print(f"Trigger: {pc.leader} {direction} {abs(change_pct):.2f}%")
                    print(f"Outcome check in: {format_duration(pc.optimal_lag_seconds - wait_time)}")
                    print(f"{'='*40}\n")
                    
                    # Only process one trade per cycle (global cooldown)
                    break
        
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
        
        # Final outcome check
        logger.info("Checking remaining outcomes...")
        time.sleep(2)
        prices = self._get_all_prices()
        if prices:
            self._check_pending_outcomes(prices)
        
        self._print_summary()


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Leading Indicator Performance Tester - Paper trading simulation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python leading_indicator_tester.py --pair BTC:ETH
  python leading_indicator_tester.py --pair BTC:ETH --sample-interval 15 --execution-pct 70
  python leading_indicator_tester.py --pair BTC:ETH --duration 24h --verbose
  python leading_indicator_tester.py --pair BTC:ETH --dry-run
  
  # Mixed exchange: TAO from CoinGecko, WTAO from Jupiter
  python leading_indicator_tester.py --pair TAO:WTAO --leader-exchange coingecko --follower-exchange jupiter
        """
    )
    
    # Pair arguments (mutually exclusive)
    pair_group = parser.add_mutually_exclusive_group(required=True)
    pair_group.add_argument('--pair',
                        help='Single coin pair to test (e.g., BTC:ETH)')
    pair_group.add_argument('--pairs',
                        help='Multiple pairs to test (comma-separated, e.g., BTC:TAO,ETH:SOL). '
                             'Requires --sample-interval. Paper mode only.')
    
    # Optional arguments
    parser.add_argument('--report', default='./correlation_data/discovery_report.json',
                        help='Path to discovery report JSON (default: ./correlation_data/discovery_report.json)')
    
    # Timing parameters
    parser.add_argument('--sample-interval', type=int, default=None,
                        help='Interval between leader price checks in seconds (default: calculated from lag, or 30s)')
    parser.add_argument('--execution-pct', type=int, default=80,
                        help='Percentage of lag time before trade execution (default: 80, range: 50-95)')
    parser.add_argument('--trade-frequency', type=int, default=None,
                        help='Minimum seconds between trades (default: lag × 2, minimum: lag)')
    
    # Thresholds
    parser.add_argument('--min-move-pct', type=float, default=0.5,
                        help='Minimum %% price change to trigger trade (default: 0.5)')
    parser.add_argument('--position-size', type=float, default=1000.0,
                        help='Simulated position size in USD (default: 1000)')
    
    # Output
    parser.add_argument('--output', default='./paper_trades/',
                        help='Path for paper trade log (default: ./paper_trades/)')
    parser.add_argument('--duration', type=str, default=None,
                        help='How long to run (e.g., 24h, 7d). Default: indefinite')
    
    # Exchange selection
    parser.add_argument('--leader-exchange', type=str, default='coingecko',
                        choices=SUPPORTED_EXCHANGES,
                        help='Exchange for leader price data (default: coingecko)')
    parser.add_argument('--follower-exchange', type=str, default='jupiter',
                        choices=SUPPORTED_EXCHANGES,
                        help='Exchange for follower price data and trading (default: jupiter for Solana MVP)')
    
    # Flags
    parser.add_argument('--dry-run', action='store_true',
                        help='Show configuration without executing')
    parser.add_argument('--verbose', action='store_true',
                        help='Detailed logging of each decision')
    parser.add_argument('--auto-interval', action='store_true',
                        help='Calculate optimal sample interval from lag')
    parser.add_argument('--max-data-age', type=int, default=24,
                        help='Maximum age of discovery report data in hours (default: 24)')
    parser.add_argument('--honor-directionality', type=str, default='yes',
                        choices=['yes', 'no'],
                        help='Only trade in the stronger direction from analysis (default: yes)')
    parser.add_argument('--age-check-interval', type=float, default=1.0,
                        help='Hours between data age checks (default: 1.0)')
    parser.add_argument('--min-win-rate', type=float, default=0.5,
                        help='Minimum win rate before action (default: 0.5)')
    parser.add_argument('--win-rate-window', type=int, default=10,
                        help='Number of recent trades to evaluate win rate (default: 10)')
    parser.add_argument('--auto-refresh', type=str, default='no',
                        choices=['yes', 'no'],
                        help='Auto re-run analyzer when win rate drops (default: no, will stop instead)')
    
    args = parser.parse_args()
    
    # Set logging level early
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate execution_pct
    if not (50 <= args.execution_pct <= 95):
        parser.error("execution-pct must be between 50 and 95")
    
    # Parse duration
    duration_seconds = None
    if args.duration:
        try:
            duration_seconds = parse_duration(args.duration)
        except ValueError as e:
            parser.error(str(e))
    
    # Handle multi-pair mode
    if args.pairs:
        # Multi-pair mode validation
        if args.sample_interval is None:
            parser.error("--pairs requires --sample-interval (auto-interval disabled for multi-pair)")
        if args.auto_interval:
            parser.error("--auto-interval is not supported with --pairs")
        
        # Parse pairs
        pair_strings = [p.strip() for p in args.pairs.split(',')]
        for ps in pair_strings:
            if ':' not in ps:
                parser.error(f"Invalid pair format '{ps}'. Must be LEADER:FOLLOWER (e.g., BTC:ETH)")
        
        # Load pair configurations
        try:
            loader = DiscoveryReportLoader(args.report)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            print(f"\nCreate a discovery report first using:")
            print(f"  python correlation_tracker.py --analyze --data-dir ./correlation_data")
            sys.exit(1)
        
        pair_configs = []
        for ps in pair_strings:
            leader, follower = ps.split(':', 1)
            pc = loader.find_pair(leader, follower)
            if pc is None:
                logger.warning(f"Pair {ps} not found in discovery report - skipping")
            else:
                pair_configs.append(pc)
        
        if not pair_configs:
            print("Error: No valid pairs found in discovery report")
            print(f"\nAvailable pairs:")
            for l, f in loader.list_pairs():
                print(f"  - {l}:{f}")
            sys.exit(1)
        
        # Use specified trade_frequency or default to max lag * 2 (global cooldown)
        if args.trade_frequency is None:
            max_lag = max(pc.optimal_lag_seconds for pc in pair_configs)
            trade_frequency = max_lag * 2
        else:
            trade_frequency = args.trade_frequency
        
        # Run multi-pair tester
        tester = MultiPairTester(
            pair_configs=pair_configs,
            sample_interval=args.sample_interval,
            execution_pct=args.execution_pct,
            trade_frequency=trade_frequency,
            min_move_pct=args.min_move_pct,
            position_size_usd=args.position_size,
            output_path=args.output,
            duration_seconds=duration_seconds,
            verbose=args.verbose,
            dry_run=args.dry_run,
            max_data_age_hours=args.max_data_age,
            leader_exchange=args.leader_exchange,
            follower_exchange=args.follower_exchange,
            honor_directionality=args.honor_directionality == 'yes',
            min_win_rate=args.min_win_rate,
            win_rate_window=args.win_rate_window,
            report_path=args.report
        )
        tester.run()
        return
    
    # Single pair mode
    if ':' not in args.pair:
        parser.error("Pair must be in LEADER:FOLLOWER format (e.g., BTC:ETH)")
    
    leader, follower = args.pair.split(':', 1)
    
    # Load pair configuration from discovery report
    try:
        loader = DiscoveryReportLoader(args.report)
        pair_config = loader.find_pair(leader, follower)
        
        if pair_config is None:
            print(f"Error: Pair {args.pair} not found in discovery report")
            print(f"\nAvailable pairs:")
            for l, f in loader.list_pairs():
                print(f"  - {l}:{f}")
            sys.exit(1)
            
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print(f"\nCreate a discovery report first using:")
        print(f"  python correlation_tracker.py --analyze --data-dir ./correlation_data")
        sys.exit(1)
    
    # Calculate intervals if auto-interval enabled
    lag = pair_config.optimal_lag_seconds
    
    if args.auto_interval or args.sample_interval is None:
        sample_interval = max(15, lag // 4)
    else:
        sample_interval = args.sample_interval
    
    if args.trade_frequency is None:
        trade_frequency = lag * 2
    else:
        trade_frequency = args.trade_frequency
        # Validate: cooldown must be >= lag to prevent overlapping trades
        if trade_frequency < lag:
            logger.warning(f"Trade frequency {trade_frequency}s is less than lag {lag}s - adjusting to {lag}s to prevent overlap")
            trade_frequency = lag
    
    # Create tester configuration
    config = TesterConfig(
        pair_config=pair_config,
        sample_interval=sample_interval,
        execution_pct=args.execution_pct,
        trade_frequency=trade_frequency,
        min_move_pct=args.min_move_pct,
        position_size_usd=args.position_size,
        output_path=args.output,
        duration_seconds=duration_seconds,
        verbose=args.verbose,
        dry_run=args.dry_run,
        max_data_age_hours=args.max_data_age,
        leader_exchange=args.leader_exchange,
        follower_exchange=args.follower_exchange,
        honor_directionality=args.honor_directionality == 'yes',
        age_check_interval_hours=args.age_check_interval,
        min_win_rate=args.min_win_rate,
        win_rate_window=args.win_rate_window,
        auto_refresh=args.auto_refresh == 'yes',
        report_path=args.report
    )
    
    # Run tester
    tester = LeadingIndicatorTester(config)
    tester.run()


if __name__ == '__main__':
    main()
