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
from preflight import PreflightValidator, PreflightResult, run_preflight

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
    # Preflight-based directional filtering (from profitability analysis)
    directional_filter: bool = False  # Enable UP/DOWN directional filtering
    up_viable: bool = True  # Whether UP direction passed profitability check
    down_viable: bool = True  # Whether DOWN direction passed profitability check
    max_trades: Optional[int] = None  # Stop after this many trades (for testing)
    live_trader: Optional[Any] = None  # LiveTrader instance for real swaps (None = paper mode)


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
# Live Trader (USDC Mode)
# ============================================================================

@dataclass
class LiveTrade:
    """A completed live trade with Jupiter swap."""
    id: str
    timestamp: str
    type: str = "live"
    pair: str = ""
    action: str = ""  # BUY or SELL
    follower: str = ""
    input_token: str = ""  # USDC for BUY, follower for SELL
    output_token: str = ""  # follower for BUY, USDC for SELL
    input_amount: float = 0.0
    output_amount: float = 0.0  # Quoted output (what Jupiter said we'd get)
    output_amount_actual: Optional[float] = None  # Actual output (post-confirmation)
    price_usd: float = 0.0
    slippage_bps: int = 100  # Tolerance setting
    slippage_actual_bps: Optional[int] = None  # Actual slippage in basis points
    trigger: Dict[str, Any] = field(default_factory=dict)
    timing: Dict[str, Any] = field(default_factory=dict)
    transaction: Dict[str, Any] = field(default_factory=dict)  # signature, status, etc.
    outcome: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LiveTrader:
    """
    Live trading with Jupiter swaps.
    
    USDC Mode (default):
        BUY signal: Swap USDC → Follower token
        SELL signal: Swap Follower token → USDC
    
    Swap Mode (--swap-mode):
        BUY signal: Swap Leader → Follower (expect follower to rise)
        SELL signal: Swap Follower → Leader (expect follower to fall)
    """
    
    def __init__(
        self,
        pair_config: PairConfig,
        position_size_usd: float = 100.0,
        slippage_bps: int = 100,
        output_path: str = './live_trades/',
        directional_filter: bool = False,
        up_viable: bool = True,
        down_viable: bool = True,
        swap_mode: bool = False,
        max_trades: Optional[int] = None,
        max_trade_usd: Optional[float] = None,
    ):
        self.pair_config = pair_config
        self.position_size_usd = position_size_usd
        self.slippage_bps = slippage_bps
        self.output_path = Path(output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        self.directional_filter = directional_filter
        self.up_viable = up_viable
        self.down_viable = down_viable
        self.swap_mode = swap_mode
        self.max_trades = max_trades
        self.max_trade_usd = max_trade_usd
        
        self.wallet = None
        self.jupiter_client = None
        self.trades: List[LiveTrade] = []
        self.trade_counter = 0
        
        # Track positions
        self.follower_balance: float = 0.0
        self.usdc_balance: float = 0.0
        self.leader_balance: float = 0.0
        
        # Load existing trades from file (persist across restarts)
        self._load_existing_trades()
    
    def _load_existing_trades(self):
        """Load existing trades from file if present."""
        output_file = self.output_path / f"{self.pair_config.leader}_{self.pair_config.follower}_live.json"
        
        if output_file.exists():
            try:
                with open(output_file, 'r') as f:
                    data = json.load(f)
                
                trade_dicts = data.get('trades', [])
                for td in trade_dicts:
                    trade = LiveTrade(
                        id=td.get('id', ''),
                        timestamp=td.get('timestamp', ''),
                        type=td.get('type', 'live'),
                        pair=td.get('pair', ''),
                        action=td.get('action', ''),
                        follower=td.get('follower', ''),
                        input_token=td.get('input_token', ''),
                        output_token=td.get('output_token', ''),
                        input_amount=td.get('input_amount', 0.0),
                        output_amount=td.get('output_amount', 0.0),
                        output_amount_actual=td.get('output_amount_actual'),
                        price_usd=td.get('price_usd', 0.0),
                        slippage_bps=td.get('slippage_bps', 100),
                        slippage_actual_bps=td.get('slippage_actual_bps'),
                        trigger=td.get('trigger', {}),
                        timing=td.get('timing', {}),
                        transaction=td.get('transaction', {}),
                        outcome=td.get('outcome'),
                    )
                    self.trades.append(trade)
                
                # Update trade counter from highest existing ID
                if self.trades:
                    max_counter = 0
                    for t in self.trades:
                        try:
                            counter = int(t.id.split('_')[-1])
                            max_counter = max(max_counter, counter)
                        except (ValueError, IndexError):
                            pass
                    self.trade_counter = max_counter
                
                logger.info(f"[LIVE] Loaded {len(self.trades)} existing trades from {output_file.name}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[LIVE] Could not load existing trades: {e}")
        
    def initialize(self) -> bool:
        """Initialize wallet and Jupiter client. Returns True on success."""
        try:
            from dex.local_wallet import get_wallet_interactive
            from dex.jupiterutil import JupiterClient, USDC_MINT
            from dex.token_cache import get_mint_with_fallback
            
            # Load wallet
            print("\n" + "=" * 60)
            print("LIVE TRADING - WALLET SETUP")
            print("=" * 60)
            self.wallet = get_wallet_interactive()
            
            if not self.wallet.is_loaded():
                print("[LIVE] Failed to load wallet")
                return False
            
            print(f"[LIVE] Wallet loaded: {self.wallet.get_address()}")
            
            # Initialize Jupiter client
            self.jupiter_client = JupiterClient(slippage_bps=self.slippage_bps)
            
            # Verify follower token is tradeable
            follower_mint = get_mint_with_fallback(self.pair_config.follower)
            if not follower_mint:
                print(f"[LIVE] Unknown token: {self.pair_config.follower}")
                return False
            
            print(f"[LIVE] Follower token: {self.pair_config.follower} ({follower_mint[:8]}...)")
            
            # TODO: Check wallet balances
            # self._refresh_balances()
            
            return True
            
        except ImportError as e:
            print(f"[LIVE] Missing dependencies: {e}")
            print("[LIVE] Install with: pip install -r requirements_dex.txt")
            return False
        except Exception as e:
            print(f"[LIVE] Initialization error: {e}")
            return False
    
    def _generate_trade_id(self) -> str:
        """Generate a unique trade ID."""
        self.trade_counter += 1
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        return f"lt_{timestamp}_{self.trade_counter:03d}"
    
    def can_execute_signal(self, direction: str) -> Tuple[bool, str]:
        """Check if a signal can be executed based on directional filtering.
        
        Args:
            direction: 'rise' or 'fall'
        
        Returns:
            (can_execute, reason)
        """
        if not self.directional_filter:
            return True, "directional filter disabled"
        
        if direction == 'rise' and not self.up_viable:
            return False, "UP direction not viable per preflight"
        elif direction == 'fall' and not self.down_viable:
            return False, "DOWN direction not viable per preflight"
        
        return True, "direction viable"
    
    def execute_buy(
        self,
        trigger_info: Dict[str, Any],
        timing_info: Dict[str, Any],
    ) -> Optional[LiveTrade]:
        """Execute a BUY: USDC → Follower token.
        
        Returns:
            LiveTrade on success, None on failure.
        """
        if not self.jupiter_client or not self.wallet:
            logger.error("[LIVE] Not initialized")
            return None
        
        # Check max trade size limit
        if self.max_trade_usd and self.position_size_usd > self.max_trade_usd:
            logger.error(f"[LIVE] Trade size ${self.position_size_usd} exceeds max ${self.max_trade_usd}")
            return None
        
        try:
            from dex.jupiterutil import USDC_MINT
            from dex.token_cache import get_mint_with_fallback
            
            follower_mint = get_mint_with_fallback(self.pair_config.follower)
            if not follower_mint:
                logger.error(f"[LIVE] Unknown token: {self.pair_config.follower}")
                return None
            
            # Convert USD to USDC amount (6 decimals)
            usdc_amount = int(self.position_size_usd * 1_000_000)
            
            # Get quote
            logger.info(f"[LIVE] Getting quote: ${self.position_size_usd} USDC → {self.pair_config.follower}")
            quote = self.jupiter_client.get_quote(
                input_mint=USDC_MINT,
                output_mint=follower_mint,
                amount=usdc_amount,
            )
            
            if not quote:
                logger.error("[LIVE] Failed to get quote")
                return None
            
            # Log quote details
            out_amount = int(quote.get("outAmount", 0))
            price_impact = float(quote.get("priceImpactPct", 0))
            logger.info(f"[LIVE] Quote: {out_amount} {self.pair_config.follower}, impact: {price_impact:.2f}%")
            
            # Get swap transaction
            swap_tx = self.jupiter_client.get_swap_transaction(
                quote=quote,
                user_public_key=self.wallet.get_address(),
            )
            
            if not swap_tx:
                logger.error("[LIVE] Failed to get swap transaction")
                return None
            
            # Sign and send transaction
            import base64
            tx_bytes = base64.b64decode(swap_tx)
            signed_tx = self.wallet.sign_transaction(tx_bytes)
            
            if not signed_tx:
                logger.error("[LIVE] Failed to sign transaction")
                return None
            
            # Send transaction
            signature = self._send_transaction(signed_tx)
            
            if not signature:
                logger.error("[LIVE] Failed to send transaction")
                return None
            
            # Calculate output amount with decimals
            from dex.token_cache import get_well_known_decimals, get_token_info
            decimals = get_well_known_decimals(self.pair_config.follower)
            if decimals is None:
                token_info = get_token_info(self.pair_config.follower)
                decimals = token_info.get("decimals", 9) if token_info else 9
            
            output_amount = out_amount / (10 ** decimals)
            price_usd = self.position_size_usd / output_amount if output_amount > 0 else 0
            
            # Create trade record
            trade = LiveTrade(
                id=self._generate_trade_id(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                type="live",
                pair=f"{self.pair_config.leader}:{self.pair_config.follower}",
                action="BUY",
                follower=self.pair_config.follower,
                input_token="USDC",
                output_token=self.pair_config.follower,
                input_amount=self.position_size_usd,
                output_amount=output_amount,
                price_usd=price_usd,
                slippage_bps=self.slippage_bps,
                trigger=trigger_info,
                timing=timing_info,
                transaction={
                    "signature": signature,
                    "status": "pending",
                    "price_impact_pct": price_impact,
                    "quoted_output": output_amount,
                },
            )
            
            # Confirm transaction and get actual output for slippage calculation
            logger.info(f"[LIVE] Waiting for confirmation...")
            confirmation = self._confirm_transaction(signature)
            
            if confirmation and confirmation.get("status") == "confirmed":
                trade.transaction["status"] = "confirmed"
                self._update_trade_with_actual_output(trade, confirmation, follower_mint)
            elif confirmation and confirmation.get("status") == "failed":
                trade.transaction["status"] = "failed"
                trade.transaction["error"] = confirmation.get("error")
                logger.error(f"[LIVE] Transaction failed: {confirmation.get('error')}")
            else:
                trade.transaction["status"] = "unconfirmed"
                logger.warning("[LIVE] Could not confirm transaction - slippage unknown")
            
            self.trades.append(trade)
            self._save_trades()
            
            logger.info(f"[LIVE] ✓ BUY executed: {output_amount:.6f} {self.pair_config.follower} @ ${price_usd:.4f}")
            logger.info(f"[LIVE] TX: {signature}")
            
            return trade
            
        except Exception as e:
            logger.error(f"[LIVE] BUY failed: {e}")
            return None
    
    def execute_sell(
        self,
        amount: float,
        trigger_info: Dict[str, Any],
        timing_info: Dict[str, Any],
    ) -> Optional[LiveTrade]:
        """Execute a SELL: Follower token → USDC.
        
        Args:
            amount: Amount of follower token to sell.
            trigger_info: Trigger data for trade record.
            timing_info: Timing data for trade record.
        
        Returns:
            LiveTrade on success, None on failure.
        """
        if not self.jupiter_client or not self.wallet:
            logger.error("[LIVE] Not initialized")
            return None
        
        try:
            from dex.jupiterutil import USDC_MINT
            from dex.token_cache import get_mint_with_fallback, get_well_known_decimals, get_token_info
            
            follower_mint = get_mint_with_fallback(self.pair_config.follower)
            if not follower_mint:
                logger.error(f"[LIVE] Unknown token: {self.pair_config.follower}")
                return None
            
            # Get token decimals
            decimals = get_well_known_decimals(self.pair_config.follower)
            if decimals is None:
                token_info = get_token_info(self.pair_config.follower)
                decimals = token_info.get("decimals", 9) if token_info else 9
            
            # Convert to smallest units
            token_amount = int(amount * (10 ** decimals))
            
            # Get quote
            logger.info(f"[LIVE] Getting quote: {amount} {self.pair_config.follower} → USDC")
            quote = self.jupiter_client.get_quote(
                input_mint=follower_mint,
                output_mint=USDC_MINT,
                amount=token_amount,
            )
            
            if not quote:
                logger.error("[LIVE] Failed to get quote")
                return None
            
            # Log quote details
            out_amount = int(quote.get("outAmount", 0))
            usdc_out = out_amount / 1_000_000  # USDC has 6 decimals
            price_impact = float(quote.get("priceImpactPct", 0))
            logger.info(f"[LIVE] Quote: ${usdc_out:.2f} USDC, impact: {price_impact:.2f}%")
            
            # Check max trade size limit (based on USD value of sell)
            if self.max_trade_usd and usdc_out > self.max_trade_usd:
                logger.error(f"[LIVE] Trade value ${usdc_out:.2f} exceeds max ${self.max_trade_usd}")
                return None
            
            # Get swap transaction
            swap_tx = self.jupiter_client.get_swap_transaction(
                quote=quote,
                user_public_key=self.wallet.get_address(),
            )
            
            if not swap_tx:
                logger.error("[LIVE] Failed to get swap transaction")
                return None
            
            # Sign and send transaction
            import base64
            tx_bytes = base64.b64decode(swap_tx)
            signed_tx = self.wallet.sign_transaction(tx_bytes)
            
            if not signed_tx:
                logger.error("[LIVE] Failed to sign transaction")
                return None
            
            # Send transaction
            signature = self._send_transaction(signed_tx)
            
            if not signature:
                logger.error("[LIVE] Failed to send transaction")
                return None
            
            price_usd = usdc_out / amount if amount > 0 else 0
            
            # Create trade record
            trade = LiveTrade(
                id=self._generate_trade_id(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                type="live",
                pair=f"{self.pair_config.leader}:{self.pair_config.follower}",
                action="SELL",
                follower=self.pair_config.follower,
                input_token=self.pair_config.follower,
                output_token="USDC",
                input_amount=amount,
                output_amount=usdc_out,
                price_usd=price_usd,
                slippage_bps=self.slippage_bps,
                trigger=trigger_info,
                timing=timing_info,
                transaction={
                    "signature": signature,
                    "status": "pending",
                    "price_impact_pct": price_impact,
                    "quoted_output": usdc_out,
                },
            )
            
            # Confirm transaction and get actual output for slippage calculation
            logger.info(f"[LIVE] Waiting for confirmation...")
            confirmation = self._confirm_transaction(signature)
            
            if confirmation and confirmation.get("status") == "confirmed":
                trade.transaction["status"] = "confirmed"
                self._update_trade_with_actual_output(trade, confirmation, USDC_MINT)
            elif confirmation and confirmation.get("status") == "failed":
                trade.transaction["status"] = "failed"
                trade.transaction["error"] = confirmation.get("error")
                logger.error(f"[LIVE] Transaction failed: {confirmation.get('error')}")
            else:
                trade.transaction["status"] = "unconfirmed"
                logger.warning("[LIVE] Could not confirm transaction - slippage unknown")
            
            self.trades.append(trade)
            self._save_trades()
            
            logger.info(f"[LIVE] ✓ SELL executed: {amount:.6f} {self.pair_config.follower} → ${usdc_out:.2f}")
            logger.info(f"[LIVE] TX: {signature}")
            
            return trade
            
        except Exception as e:
            logger.error(f"[LIVE] SELL failed: {e}")
            return None
    
    # ==================== SWAP MODE METHODS ====================
    
    def swap_leader_to_follower(
        self,
        usd_equivalent: float,
        trigger_info: Dict[str, Any],
        timing_info: Dict[str, Any],
    ) -> Optional[LiveTrade]:
        """Swap Mode BUY: Leader → Follower (expect follower to rise).
        
        Args:
            usd_equivalent: USD value to swap (determines leader token amount).
            trigger_info: Trigger data for trade record.
            timing_info: Timing data for trade record.
        
        Returns:
            LiveTrade on success, None on failure.
        """
        if not self.jupiter_client or not self.wallet:
            logger.error("[LIVE] Not initialized")
            return None
        
        try:
            from dex.token_cache import get_mint_with_fallback, get_well_known_decimals, get_token_info
            
            leader_mint = get_mint_with_fallback(self.pair_config.leader)
            follower_mint = get_mint_with_fallback(self.pair_config.follower)
            
            if not leader_mint or not follower_mint:
                logger.error(f"[LIVE] Unknown tokens: {self.pair_config.leader} or {self.pair_config.follower}")
                return None
            
            # Get leader price to calculate amount
            leader_price = self.jupiter_client.get_price(self.pair_config.leader)
            if not leader_price:
                logger.error(f"[LIVE] Could not get price for {self.pair_config.leader}")
                return None
            
            leader_usd_price = leader_price[0]
            leader_amount = usd_equivalent / leader_usd_price
            
            # Get leader decimals
            leader_decimals = get_well_known_decimals(self.pair_config.leader)
            if leader_decimals is None:
                token_info = get_token_info(self.pair_config.leader)
                leader_decimals = token_info.get("decimals", 9) if token_info else 9
            
            # Convert to smallest units
            leader_amount_raw = int(leader_amount * (10 ** leader_decimals))
            
            logger.info(f"[SWAP] Getting quote: {leader_amount:.6f} {self.pair_config.leader} → {self.pair_config.follower}")
            quote = self.jupiter_client.get_quote(
                input_mint=leader_mint,
                output_mint=follower_mint,
                amount=leader_amount_raw,
            )
            
            if not quote:
                logger.error("[SWAP] Failed to get quote")
                return None
            
            # Get follower decimals
            follower_decimals = get_well_known_decimals(self.pair_config.follower)
            if follower_decimals is None:
                token_info = get_token_info(self.pair_config.follower)
                follower_decimals = token_info.get("decimals", 9) if token_info else 9
            
            out_amount = int(quote.get("outAmount", 0))
            follower_amount = out_amount / (10 ** follower_decimals)
            price_impact = float(quote.get("priceImpactPct", 0))
            
            logger.info(f"[SWAP] Quote: {follower_amount:.6f} {self.pair_config.follower}, impact: {price_impact:.2f}%")
            
            # Get swap transaction
            swap_tx = self.jupiter_client.get_swap_transaction(
                quote=quote,
                user_public_key=self.wallet.get_address(),
            )
            
            if not swap_tx:
                logger.error("[SWAP] Failed to get swap transaction")
                return None
            
            # Sign and send
            import base64
            tx_bytes = base64.b64decode(swap_tx)
            signed_tx = self.wallet.sign_transaction(tx_bytes)
            
            if not signed_tx:
                logger.error("[SWAP] Failed to sign transaction")
                return None
            
            signature = self._send_transaction(signed_tx)
            
            if not signature:
                logger.error("[SWAP] Failed to send transaction")
                return None
            
            # Create trade record
            trade = LiveTrade(
                id=self._generate_trade_id(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                type="live_swap",
                pair=f"{self.pair_config.leader}:{self.pair_config.follower}",
                action="SWAP_BUY",
                follower=self.pair_config.follower,
                input_token=self.pair_config.leader,
                output_token=self.pair_config.follower,
                input_amount=leader_amount,
                output_amount=follower_amount,
                price_usd=usd_equivalent,  # USD equivalent of swap
                slippage_bps=self.slippage_bps,
                trigger=trigger_info,
                timing=timing_info,
                transaction={
                    "signature": signature,
                    "status": "confirmed",
                    "price_impact_pct": price_impact,
                    "mode": "swap",
                },
            )
            
            self.trades.append(trade)
            self._save_trades()
            
            logger.info(f"[SWAP] ✓ {self.pair_config.leader} → {self.pair_config.follower}: {leader_amount:.6f} → {follower_amount:.6f}")
            logger.info(f"[SWAP] TX: {signature}")
            
            return trade
            
        except Exception as e:
            logger.error(f"[SWAP] Leader→Follower failed: {e}")
            return None
    
    def swap_follower_to_leader(
        self,
        follower_amount: float,
        trigger_info: Dict[str, Any],
        timing_info: Dict[str, Any],
    ) -> Optional[LiveTrade]:
        """Swap Mode SELL: Follower → Leader (expect follower to fall).
        
        Args:
            follower_amount: Amount of follower token to swap.
            trigger_info: Trigger data for trade record.
            timing_info: Timing data for trade record.
        
        Returns:
            LiveTrade on success, None on failure.
        """
        if not self.jupiter_client or not self.wallet:
            logger.error("[LIVE] Not initialized")
            return None
        
        try:
            from dex.token_cache import get_mint_with_fallback, get_well_known_decimals, get_token_info
            
            leader_mint = get_mint_with_fallback(self.pair_config.leader)
            follower_mint = get_mint_with_fallback(self.pair_config.follower)
            
            if not leader_mint or not follower_mint:
                logger.error(f"[LIVE] Unknown tokens: {self.pair_config.leader} or {self.pair_config.follower}")
                return None
            
            # Get follower decimals
            follower_decimals = get_well_known_decimals(self.pair_config.follower)
            if follower_decimals is None:
                token_info = get_token_info(self.pair_config.follower)
                follower_decimals = token_info.get("decimals", 9) if token_info else 9
            
            # Convert to smallest units
            follower_amount_raw = int(follower_amount * (10 ** follower_decimals))
            
            logger.info(f"[SWAP] Getting quote: {follower_amount:.6f} {self.pair_config.follower} → {self.pair_config.leader}")
            quote = self.jupiter_client.get_quote(
                input_mint=follower_mint,
                output_mint=leader_mint,
                amount=follower_amount_raw,
            )
            
            if not quote:
                logger.error("[SWAP] Failed to get quote")
                return None
            
            # Get leader decimals
            leader_decimals = get_well_known_decimals(self.pair_config.leader)
            if leader_decimals is None:
                token_info = get_token_info(self.pair_config.leader)
                leader_decimals = token_info.get("decimals", 9) if token_info else 9
            
            out_amount = int(quote.get("outAmount", 0))
            leader_amount = out_amount / (10 ** leader_decimals)
            price_impact = float(quote.get("priceImpactPct", 0))
            
            logger.info(f"[SWAP] Quote: {leader_amount:.6f} {self.pair_config.leader}, impact: {price_impact:.2f}%")
            
            # Get swap transaction
            swap_tx = self.jupiter_client.get_swap_transaction(
                quote=quote,
                user_public_key=self.wallet.get_address(),
            )
            
            if not swap_tx:
                logger.error("[SWAP] Failed to get swap transaction")
                return None
            
            # Sign and send
            import base64
            tx_bytes = base64.b64decode(swap_tx)
            signed_tx = self.wallet.sign_transaction(tx_bytes)
            
            if not signed_tx:
                logger.error("[SWAP] Failed to sign transaction")
                return None
            
            signature = self._send_transaction(signed_tx)
            
            if not signature:
                logger.error("[SWAP] Failed to send transaction")
                return None
            
            # Get follower price for USD equivalent
            follower_price = self.jupiter_client.get_price(self.pair_config.follower)
            usd_equivalent = follower_amount * follower_price[0] if follower_price else 0
            
            # Create trade record
            trade = LiveTrade(
                id=self._generate_trade_id(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                type="live_swap",
                pair=f"{self.pair_config.leader}:{self.pair_config.follower}",
                action="SWAP_SELL",
                follower=self.pair_config.follower,
                input_token=self.pair_config.follower,
                output_token=self.pair_config.leader,
                input_amount=follower_amount,
                output_amount=leader_amount,
                price_usd=usd_equivalent,  # USD equivalent of swap
                slippage_bps=self.slippage_bps,
                trigger=trigger_info,
                timing=timing_info,
                transaction={
                    "signature": signature,
                    "status": "confirmed",
                    "price_impact_pct": price_impact,
                    "mode": "swap",
                },
            )
            
            self.trades.append(trade)
            self._save_trades()
            
            logger.info(f"[SWAP] ✓ {self.pair_config.follower} → {self.pair_config.leader}: {follower_amount:.6f} → {leader_amount:.6f}")
            logger.info(f"[SWAP] TX: {signature}")
            
            return trade
            
        except Exception as e:
            logger.error(f"[SWAP] Follower→Leader failed: {e}")
            return None
    
    def _send_transaction(self, signed_tx: bytes) -> Optional[str]:
        """Send a signed transaction to the network.
        
        Returns:
            Transaction signature on success, None on failure.
        """
        try:
            import base64
            import httpx
            
            tx_base64 = base64.b64encode(signed_tx).decode()
            
            # Use Solana mainnet RPC
            rpc_url = "https://api.mainnet-beta.solana.com"
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    tx_base64,
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                        "maxRetries": 3,
                    }
                ]
            }
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(rpc_url, json=payload)
                result = response.json()
                
                if "error" in result:
                    logger.error(f"[LIVE] RPC error: {result['error']}")
                    return None
                
                signature = result.get("result")
                return signature
                
        except Exception as e:
            logger.error(f"[LIVE] Send transaction error: {e}")
            return None
    
    def _confirm_transaction(self, signature: str, timeout_seconds: int = 30) -> Optional[Dict]:
        """Wait for transaction confirmation and return parsed result.
        
        Returns:
            Dict with confirmation status and token balance changes, or None on timeout/error.
        """
        import time
        import httpx
        
        rpc_url = "https://api.mainnet-beta.solana.com"
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            try:
                # Check transaction status
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        signature,
                        {
                            "encoding": "jsonParsed",
                            "commitment": "confirmed",
                            "maxSupportedTransactionVersion": 0,
                        }
                    ]
                }
                
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(rpc_url, json=payload)
                    result = response.json()
                
                if "error" in result:
                    logger.warning(f"[LIVE] Confirmation check error: {result['error']}")
                    time.sleep(2)
                    continue
                
                tx_data = result.get("result")
                if tx_data is None:
                    # Transaction not yet confirmed
                    time.sleep(1)
                    continue
                
                # Transaction confirmed - parse token balance changes
                meta = tx_data.get("meta", {})
                if meta.get("err"):
                    return {"status": "failed", "error": str(meta["err"])}
                
                # Extract pre/post token balances
                pre_balances = meta.get("preTokenBalances", [])
                post_balances = meta.get("postTokenBalances", [])
                
                # Calculate balance changes by mint
                balance_changes = {}
                for post in post_balances:
                    mint = post.get("mint", "")
                    owner = post.get("owner", "")
                    post_amount = float(post.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                    
                    # Find matching pre-balance
                    pre_amount = 0.0
                    for pre in pre_balances:
                        if pre.get("mint") == mint and pre.get("owner") == owner:
                            pre_amount = float(pre.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                            break
                    
                    change = post_amount - pre_amount
                    if abs(change) > 0.000001:  # Ignore dust
                        balance_changes[mint] = {
                            "pre": pre_amount,
                            "post": post_amount,
                            "change": change,
                        }
                
                # Also check SOL balance change
                pre_sol = meta.get("preBalances", [0])[0] / 1e9 if meta.get("preBalances") else 0
                post_sol = meta.get("postBalances", [0])[0] / 1e9 if meta.get("postBalances") else 0
                sol_change = post_sol - pre_sol
                
                return {
                    "status": "confirmed",
                    "slot": tx_data.get("slot"),
                    "token_changes": balance_changes,
                    "sol_change": sol_change,
                    "fee_sol": meta.get("fee", 0) / 1e9,
                }
                
            except Exception as e:
                logger.warning(f"[LIVE] Confirmation polling error: {e}")
                time.sleep(2)
        
        logger.warning(f"[LIVE] Transaction confirmation timeout after {timeout_seconds}s")
        return None
    
    def _update_trade_with_actual_output(
        self, 
        trade: LiveTrade, 
        confirmation: Dict,
        output_mint: str,
    ):
        """Update trade with actual output amount and calculate slippage."""
        token_changes = confirmation.get("token_changes", {})
        
        # Find the output token change
        if output_mint in token_changes:
            actual_change = token_changes[output_mint].get("change", 0)
            trade.output_amount_actual = abs(actual_change)
            
            # Calculate actual slippage in basis points
            if trade.output_amount > 0:
                slippage_pct = (trade.output_amount - trade.output_amount_actual) / trade.output_amount * 100
                trade.slippage_actual_bps = int(slippage_pct * 100)
                
                # Log slippage
                if trade.slippage_actual_bps > 0:
                    logger.info(f"[LIVE] Slippage: {trade.slippage_actual_bps/100:.2f}% "
                               f"(quoted: {trade.output_amount:.6f}, actual: {trade.output_amount_actual:.6f})")
                elif trade.slippage_actual_bps < 0:
                    logger.info(f"[LIVE] Positive slippage: {-trade.slippage_actual_bps/100:.2f}% (got more than quoted)")
            
            # Update transaction dict
            trade.transaction["actual_output"] = trade.output_amount_actual
            trade.transaction["slippage_actual_bps"] = trade.slippage_actual_bps
            trade.transaction["fee_sol"] = confirmation.get("fee_sol", 0)
        else:
            logger.warning(f"[LIVE] Could not find output token {output_mint[:8]}... in balance changes")
    
    def _save_trades(self):
        """Save trades to JSON file."""
        output_file = self.output_path / f"{self.pair_config.leader}_{self.pair_config.follower}_live.json"
        
        data = {
            "pair": f"{self.pair_config.leader}:{self.pair_config.follower}",
            "wallet": self.wallet.get_address() if self.wallet else None,
            "trades": [t.to_dict() for t in self.trades],
            "summary": self._calculate_summary(),
        }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _calculate_summary(self) -> Dict[str, Any]:
        """Calculate summary statistics including cost basis for PnL."""
        if not self.trades:
            return {"total_trades": 0}
        
        buys = [t for t in self.trades if t.action == "BUY"]
        sells = [t for t in self.trades if t.action == "SELL"]
        
        # Cost basis tracking
        total_bought_usd = sum(t.input_amount for t in buys)  # USDC spent
        total_sold_usd = sum(t.output_amount for t in sells)  # USDC received
        total_tokens_bought = sum(t.output_amount for t in buys)  # Tokens acquired
        total_tokens_sold = sum(t.input_amount for t in sells)  # Tokens disposed
        
        # Average cost basis (USDC per token)
        avg_buy_price = total_bought_usd / total_tokens_bought if total_tokens_bought > 0 else 0
        avg_sell_price = total_sold_usd / total_tokens_sold if total_tokens_sold > 0 else 0
        
        # Realized PnL (only on matched buy/sell pairs using avg cost)
        tokens_matched = min(total_tokens_bought, total_tokens_sold)
        realized_pnl = tokens_matched * (avg_sell_price - avg_buy_price) if tokens_matched > 0 else 0
        
        # Unrealized position
        tokens_held = total_tokens_bought - total_tokens_sold
        unrealized_cost_basis = tokens_held * avg_buy_price if tokens_held > 0 else 0
        
        # Slippage statistics
        trades_with_slippage = [t for t in self.trades if t.slippage_actual_bps is not None]
        if trades_with_slippage:
            slippage_values = [t.slippage_actual_bps for t in trades_with_slippage]
            avg_slippage_bps = sum(slippage_values) / len(slippage_values)
            max_slippage_bps = max(slippage_values)
            min_slippage_bps = min(slippage_values)  # Negative = got more than quoted
            trades_exceeded_tolerance = sum(1 for t in trades_with_slippage 
                                            if t.slippage_actual_bps > t.slippage_bps)
        else:
            avg_slippage_bps = None
            max_slippage_bps = None
            min_slippage_bps = None
            trades_exceeded_tolerance = 0
        
        # Transaction status counts
        confirmed = sum(1 for t in self.trades if t.transaction.get("status") == "confirmed")
        failed = sum(1 for t in self.trades if t.transaction.get("status") == "failed")
        unconfirmed = sum(1 for t in self.trades if t.transaction.get("status") == "unconfirmed")
        
        return {
            "total_trades": len(self.trades),
            "buys": len(buys),
            "sells": len(sells),
            # Cost basis fields
            "total_bought_usd": round(total_bought_usd, 2),
            "total_sold_usd": round(total_sold_usd, 2),
            "total_tokens_bought": round(total_tokens_bought, 6),
            "total_tokens_sold": round(total_tokens_sold, 6),
            "avg_buy_price_usd": round(avg_buy_price, 6),
            "avg_sell_price_usd": round(avg_sell_price, 6),
            # PnL fields
            "realized_pnl_usd": round(realized_pnl, 2),
            "tokens_held": round(tokens_held, 6),
            "unrealized_cost_basis_usd": round(unrealized_cost_basis, 2),
            "net_cash_flow_usd": round(total_sold_usd - total_bought_usd, 2),
            # Slippage fields
            "slippage_tracked_trades": len(trades_with_slippage),
            "avg_slippage_bps": round(avg_slippage_bps, 1) if avg_slippage_bps is not None else None,
            "max_slippage_bps": max_slippage_bps,
            "min_slippage_bps": min_slippage_bps,
            "trades_exceeded_tolerance": trades_exceeded_tolerance,
            # Transaction status
            "tx_confirmed": confirmed,
            "tx_failed": failed,
            "tx_unconfirmed": unconfirmed,
        }


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
                
                # NEW: Preflight-based directional filtering (UP/DOWN viability from profitability analysis)
                if self.config.directional_filter:
                    if direction == 'rise' and not self.config.up_viable:
                        if self.config.verbose:
                            logger.debug(f"Skipping UP signal: UP direction not viable per preflight")
                        leader_t0 = leader_t1
                        continue
                    elif direction == 'fall' and not self.config.down_viable:
                        if self.config.verbose:
                            logger.debug(f"Skipping DOWN signal: DOWN direction not viable per preflight")
                        leader_t0 = leader_t1
                        continue
                
                # LEGACY: Discovery report stronger_direction filter
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
                
                # Execute trade (live or paper)
                if self.config.live_trader:
                    # LIVE MODE: Execute real Jupiter swap
                    trigger_info = {
                        'leader': self.pair_config.leader,
                        'direction': direction,
                        'change_pct': change_pct,
                        'leader_price': leader_t1.price,
                    }
                    timing_info = {
                        'signal_time': signal.leader_t1.timestamp.isoformat(),
                        'execution_time': datetime.now(timezone.utc).isoformat(),
                        'wait_seconds': wait_time,
                    }
                    
                    if action == 'BUY':
                        live_trade = self.config.live_trader.execute_buy(trigger_info, timing_info)
                    else:
                        live_trade = self.config.live_trader.execute_sell(trigger_info, timing_info)
                    
                    if live_trade:
                        self.trade_counter += 1
                        print(f"\n{'='*40}")
                        print(f"LIVE TRADE EXECUTED")
                        print(f"{'='*40}")
                        print(f"Action: {live_trade.action} {live_trade.follower}")
                        print(f"Price: ${live_trade.price_usd:.4f}")
                        print(f"Size: ${live_trade.position_size_usd:.2f} ({live_trade.amount:.6f} {live_trade.follower})")
                        print(f"Trigger: {self.pair_config.leader} {direction} {abs(change_pct):.2f}%")
                        print(f"Tx: {live_trade.signature[:16]}...")
                        print(f"{'='*40}\n")
                    else:
                        print(f"\n[LIVE] Trade execution FAILED - see logs above")
                        # Don't count failed trades toward max_trades
                        leader_t0 = leader_t1
                        continue
                else:
                    # PAPER MODE: Simulate trade
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
                
                # Check max trades limit
                if self.config.max_trades and self.trade_counter >= self.config.max_trades:
                    logger.info(f"Max trades limit reached ({self.config.max_trades})")
                    print(f"\n{'='*40}")
                    print(f"MAX TRADES LIMIT REACHED ({self.config.max_trades})")
                    print(f"{'='*40}")
                    self.running = False
                    break
                
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
    parser.add_argument('--max-trades', type=int, default=None,
                        help='Stop after this many trades (for testing). Default: unlimited')
    
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
    
    # Trading mode (new for live mode support)
    parser.add_argument('--trading-mode', type=str, default='paper',
                        choices=['paper', 'live'],
                        help='Trading mode: paper (simulated) or live (real swaps) (default: paper)')
    parser.add_argument('--directional-filter', action='store_true',
                        help='Enable UP/DOWN directional filtering for live trading viability')
    parser.add_argument('--preflight-recent', type=str, default='48hr',
                        help='Data window for preflight analysis in live mode (default: 48hr)')
    parser.add_argument('--swap-mode', action='store_true',
                        help='Swap directly between tokens instead of USDC (live mode only)')
    parser.add_argument('--slippage-bps', type=int, default=100,
                        help='Slippage tolerance in basis points (default: 100 = 1%%)')
    parser.add_argument('--max-trade-usd', type=float, default=None,
                        help='Maximum trade size in USD (live mode safety limit)')
    
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
    
    # ==================== LIVE MODE PREFLIGHT ====================
    if args.trading_mode == 'live':
        print("\n" + "=" * 70)
        print("                    LIVE MODE - PRE-FLIGHT CHECK")
        print("=" * 70)
        
        # Run preflight validation
        preflight_result = run_preflight(
            leader=leader,
            follower=follower,
            directional_filter=args.directional_filter,
            recent=args.preflight_recent,
            position_size_usd=args.position_size,
            verbose=True
        )
        
        if not preflight_result.passed:
            print("\n" + "=" * 70)
            print("                    ✗ PRE-FLIGHT FAILED")
            print("=" * 70)
            print("\nLive trading BLOCKED. The pair did not pass viability checks.")
            print("\nOptions:")
            print("  1. Use --trading-mode paper to test without real funds")
            print("  2. Try a different trading pair")
            print("  3. Wait for market conditions to improve")
            print("=" * 70 + "\n")
            sys.exit(1)
        
        # Auto-configure intervals from preflight
        if preflight_result.recommended_interval_seconds:
            recommended_interval = preflight_result.recommended_interval_seconds
            # Sample interval = lag time (Option B: compare to previous sample at lag interval)
            sample_interval = preflight_result.sample_interval_seconds or recommended_interval
            trade_frequency = recommended_interval * 2
            
            # Override discovery report lag with preflight's recommended interval
            # The preflight analysis determines the minimum profitable interval
            pair_config.optimal_lag_seconds = recommended_interval
            
            print(f"\nAuto-configured from preflight:")
            print(f"  Lag time: {recommended_interval}s ({recommended_interval // 60}m)")
            print(f"  Sample interval: {sample_interval}s")
            print(f"  Trade cooldown: {trade_frequency}s")
        else:
            # Fallback to discovery report lag
            lag = pair_config.optimal_lag_seconds
            # Sample interval = lag time (Option B: compare to previous sample at lag interval)
            sample_interval = lag
            trade_frequency = lag * 2
        
        # Store directional viability for runtime filtering
        up_viable = preflight_result.up_viable
        down_viable = preflight_result.down_viable
        
        if args.directional_filter:
            print(f"\nDirectional filtering ENABLED:")
            print(f"  UP signals: {'✓ Allowed' if up_viable else '✗ Blocked'}")
            print(f"  DOWN signals: {'✓ Allowed' if down_viable else '✗ Blocked'}")
        
        # Dry-run mode: show what would happen and exit
        if args.dry_run:
            mode_str = "SWAP MODE" if args.swap_mode else "USDC MODE"
            print("\n" + "=" * 70)
            print(f"                    DRY RUN ({mode_str}) - NO TRADES EXECUTED")
            print("=" * 70)
            print("\nPreflight passed. In live mode, the system would:")
            print(f"  • Monitor {leader} price every {sample_interval}s")
            execution_wait = int(pair_config.optimal_lag_seconds * args.execution_pct / 100)
            print(f"  • Lag time: {pair_config.optimal_lag_seconds}s ({pair_config.optimal_lag_seconds // 60}m)")
            print(f"  • Execute at {args.execution_pct}%: wait {execution_wait}s ({execution_wait // 60}m) before trade")
            print(f"  • Correlation: {pair_config.correlation:.3f} ({'positive' if pair_config.correlation > 0 else 'negative'})")
            if args.swap_mode:
                print(f"  • Execute direct swaps: {leader} ↔ {follower}")
            else:
                print(f"  • Execute swaps on {follower} via Jupiter (USDC)")
            print(f"  • Position size: ${args.position_size:.2f}")
            print(f"  • Trade cooldown: {trade_frequency}s")
            print(f"  • Slippage tolerance: {args.slippage_bps/100:.1f}%")
            if args.directional_filter:
                directions = []
                if up_viable:
                    directions.append("BUY on leader rise")
                if down_viable:
                    directions.append("SELL on leader fall")
                print(f"  • Allowed actions: {', '.join(directions)}")
            print("\nRemove --dry-run to execute live trades.")
            print("=" * 70 + "\n")
            sys.exit(0)
        
        # Swap mode notice
        mode_str = "SWAP MODE" if args.swap_mode else "USDC MODE"
        print(f"\n⚠️  LIVE TRADING MODE ({mode_str}) - Real swaps will be executed!")
        print("=" * 70 + "\n")
        
        if args.swap_mode:
            print(f"[SWAP] Direct token swaps: {leader} ↔ {follower}")
            print(f"[SWAP] BUY signal: {leader} → {follower}")
            print(f"[SWAP] SELL signal: {follower} → {leader}\n")
        
        # Initialize LiveTrader
        live_trader = LiveTrader(
            pair_config=pair_config,
            position_size_usd=args.position_size,
            slippage_bps=args.slippage_bps,
            output_path='./live_trades/',
            directional_filter=args.directional_filter,
            up_viable=up_viable,
            down_viable=down_viable,
            swap_mode=args.swap_mode,
            max_trades=args.max_trades,
            max_trade_usd=args.max_trade_usd,
        )
        
        if not live_trader.initialize():
            print("\n[LIVE] Failed to initialize live trading")
            print("[LIVE] Check wallet and dependencies")
            sys.exit(1)
        
        # Create config for monitoring loop with live_trader attached
        config = TesterConfig(
            pair_config=pair_config,
            sample_interval=sample_interval,
            execution_pct=args.execution_pct,
            trade_frequency=trade_frequency,
            min_move_pct=args.min_move_pct,
            position_size_usd=args.position_size,
            output_path='./live_trades/',
            duration_seconds=duration_seconds,
            verbose=args.verbose,
            dry_run=False,
            max_data_age_hours=args.max_data_age,
            leader_exchange=args.leader_exchange,
            follower_exchange=args.follower_exchange,
            honor_directionality=args.honor_directionality == 'yes',
            age_check_interval_hours=args.age_check_interval,
            min_win_rate=args.min_win_rate,
            win_rate_window=args.win_rate_window,
            auto_refresh=args.auto_refresh == 'yes',
            report_path=args.report,
            directional_filter=args.directional_filter,
            up_viable=up_viable,
            down_viable=down_viable,
            max_trades=args.max_trades,
            live_trader=live_trader,  # Enables real Jupiter swaps
        )
        
        print("[LIVE] Starting monitoring loop...")
        print("[LIVE] Signals will trigger real Jupiter swaps")
        if args.max_trade_usd:
            print(f"[LIVE] Max trade size: ${args.max_trade_usd:.2f}")
        print("")
        print("=" * 60)
        print("⚠️  RECOMMENDATION: Use a dedicated wallet for bot trading")
        print("    Isolate trading funds from personal holdings")
        print("=" * 60)
        print("")
        
        tester = LeadingIndicatorTester(config)
        tester.run()
        sys.exit(0)
    
    # ==================== PAPER MODE ====================
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
        report_path=args.report,
        max_trades=args.max_trades,
    )
    
    # Run tester
    tester = LeadingIndicatorTester(config)
    tester.run()


if __name__ == '__main__':
    main()
