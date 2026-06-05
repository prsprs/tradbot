#!/usr/bin/env python3
"""
Fibonacci Retracement Analysis Module

Analyzes historical price data to identify Fibonacci retracement levels and
evaluate their effectiveness as support/resistance indicators.

Usage:
    # Standalone analysis
    python fibonacci_analyzer.py --symbol SOL --window 7d --granularity 5min \
        --data-dir ./correlation_data \
        --confirmation-periods 3 \
        --touch-tolerance 0.5 \
        --min-touches 2

    # As a library
    from fibonacci_analyzer import FibonacciAnalyzer, FibonacciReport
    analyzer = FibonacciAnalyzer(data_dir='./correlation_data')
    report = analyzer.analyze('SOL', window_seconds=7*86400)
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Price Formatting Utilities
# ============================================================================

def format_price(price: float, symbol: str = '$') -> str:
    """
    Format a price for display, using scientific notation for very small values.
    
    Args:
        price: The price to format
        symbol: Currency symbol (default: '$')
    
    Returns:
        Formatted price string that's readable for both large and micro-cap coins
    """
    if price is None or price == 0:
        return f"{symbol}0.00"
    
    abs_price = abs(price)
    
    # For very small prices (< 0.0001), use scientific notation
    if abs_price < 0.0001:
        return f"{symbol}{price:.2e}"
    # For small prices (< 0.01), show more decimals
    elif abs_price < 0.01:
        return f"{symbol}{price:.6f}"
    # For normal prices (< 1000), show 4 decimals
    elif abs_price < 1000:
        return f"{symbol}{price:.4f}"
    # For large prices, show 2 decimals
    else:
        return f"{symbol}{price:.2f}"


# ============================================================================
# Time Duration Parsing (shared with correlation_tracker.py)
# ============================================================================

def parse_duration(value: str, default_unit: str = 'sec') -> int:
    """
    Parse a duration string into seconds.
    
    Supported formats:
        - Plain number: interpreted using default_unit (e.g., "30" -> 30 sec or 30 hr)
        - Number + 's'/'sec'/'secs': seconds (e.g., "30s", "30sec" -> 30)
        - Number + 'm'/'min'/'mins': minutes (e.g., "5m", "5min" -> 300)
        - Number + 'h'/'hr'/'hrs'/'hour'/'hours': hours (e.g., "1h", "1hr", "1hour" -> 3600)
        - Number + 'd'/'day'/'days': days (e.g., "5d", "14days" -> 432000, 1209600)
    
    Args:
        value: Duration string to parse
        default_unit: Unit to use when no suffix provided ('sec' or 'hr')
    """
    if value is None:
        return None
    
    value = str(value).strip().lower()
    
    if not value:
        raise ValueError("Empty duration string")
    
    # Parse with unit suffix
    import re
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|h|hr|hrs|hour|hours|d|day|days)?$', value)
    
    if not match:
        raise ValueError(f"Invalid duration format: '{value}'. Use formats like: 30s, 5min, 1hr, 72h, 5d, 14days")
    
    amount = float(match.group(1))
    unit = match.group(2)
    
    # If no unit specified, use default
    if not unit:
        unit = default_unit
    
    # Normalize units
    unit_map = {
        's': 'sec', 'sec': 'sec', 'secs': 'sec',
        'm': 'min', 'min': 'min', 'mins': 'min',
        'h': 'hr', 'hr': 'hr', 'hrs': 'hr', 'hour': 'hr', 'hours': 'hr',
        'd': 'days', 'day': 'days', 'days': 'days',
    }
    unit = unit_map.get(unit, unit)
    
    multipliers = {
        'sec': 1,
        'min': 60,
        'hr': 3600,
        'days': 86400,
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
class PricePoint:
    """A single price observation."""
    timestamp: datetime
    price: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp.isoformat(),
            'price': self.price
        }


@dataclass
class FibonacciLevel:
    """Statistics for a single Fibonacci level."""
    ratio: float           # 0.236, 0.382, etc.
    price: float           # Calculated price at this level
    touch_count: int = 0   # Number of times price touched this level
    bounce_count: int = 0  # Number of times price bounced off this level
    breakthrough_count: int = 0  # Number of times price broke through
    avg_bounce_magnitude: float = 0.0  # Average % move after bounce
    bounce_magnitudes: List[float] = field(default_factory=list)  # Individual bounce magnitudes
    
    @property
    def effectiveness(self) -> Optional[float]:
        """Percentage of touches that resulted in bounces."""
        if self.touch_count == 0:
            return None
        return (self.bounce_count / self.touch_count) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            'ratio': self.ratio,
            'price': self.price,
            'touch_count': self.touch_count,
            'bounce_count': self.bounce_count,
            'breakthrough_count': self.breakthrough_count,
            'effectiveness_pct': self.effectiveness,
            'avg_bounce_magnitude': self.avg_bounce_magnitude
        }
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FibonacciLevel':
        """Reconstruct a FibonacciLevel from a dictionary."""
        return cls(
            ratio=data['ratio'],
            price=data['price'],
            touch_count=data.get('touch_count', 0),
            bounce_count=data.get('bounce_count', 0),
            breakthrough_count=data.get('breakthrough_count', 0),
            avg_bounce_magnitude=data.get('avg_bounce_magnitude', 0.0),
            bounce_magnitudes=data.get('bounce_magnitudes', [])
        )


@dataclass
class FibonacciReport:
    """Complete Fibonacci analysis report."""
    symbol: str
    analysis_window: str
    window_start: datetime
    window_end: datetime
    high_price: float
    high_timestamp: datetime
    low_price: float
    low_timestamp: datetime
    trend_direction: str   # 'up' if low before high, 'down' if high before low
    levels: Dict[str, FibonacciLevel]  # keyed by ratio string (e.g., "23.6%")
    
    # Summary statistics
    most_respected_level: Optional[str] = None
    overall_effectiveness: float = 0.0  # % of touches that resulted in bounces
    total_touches: int = 0
    total_bounces: int = 0
    
    # Configuration used
    touch_tolerance_pct: float = 0.5
    confirmation_periods: int = 3
    min_touches: int = 2
    data_points_analyzed: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'analysis_window': self.analysis_window,
            'window_start': self.window_start.isoformat(),
            'window_end': self.window_end.isoformat(),
            'high_price': self.high_price,
            'high_timestamp': self.high_timestamp.isoformat(),
            'low_price': self.low_price,
            'low_timestamp': self.low_timestamp.isoformat(),
            'trend_direction': self.trend_direction,
            'levels': {k: v.to_dict() for k, v in self.levels.items()},
            'most_respected_level': self.most_respected_level,
            'overall_effectiveness': self.overall_effectiveness,
            'total_touches': self.total_touches,
            'total_bounces': self.total_bounces,
            'touch_tolerance_pct': self.touch_tolerance_pct,
            'confirmation_periods': self.confirmation_periods,
            'min_touches': self.min_touches,
            'data_points_analyzed': self.data_points_analyzed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FibonacciReport':
        """Reconstruct a FibonacciReport from a dictionary (e.g., loaded from JSON cache)."""
        # Parse timestamps
        def parse_ts(ts_str):
            if isinstance(ts_str, datetime):
                return ts_str
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        
        # Reconstruct levels
        levels = {}
        for key, level_data in data.get('levels', {}).items():
            levels[key] = FibonacciLevel.from_dict(level_data)
        
        return cls(
            symbol=data['symbol'],
            analysis_window=data['analysis_window'],
            window_start=parse_ts(data['window_start']),
            window_end=parse_ts(data['window_end']),
            high_price=data['high_price'],
            high_timestamp=parse_ts(data['high_timestamp']),
            low_price=data['low_price'],
            low_timestamp=parse_ts(data['low_timestamp']),
            trend_direction=data['trend_direction'],
            levels=levels,
            most_respected_level=data.get('most_respected_level'),
            overall_effectiveness=data.get('overall_effectiveness', 0.0),
            total_touches=data.get('total_touches', 0),
            total_bounces=data.get('total_bounces', 0),
            touch_tolerance_pct=data.get('touch_tolerance_pct', 0.5),
            confirmation_periods=data.get('confirmation_periods', 3),
            min_touches=data.get('min_touches', 2),
            data_points_analyzed=data.get('data_points_analyzed', 0)
        )


# ============================================================================
# Fib Report Cache
# ============================================================================

FIB_REPORTS_DIR = 'fib_reports'


def get_fib_report_path(data_dir: str, symbol: str) -> Path:
    """Get the path for a symbol's Fib report cache file."""
    return Path(data_dir) / FIB_REPORTS_DIR / f"{symbol.upper()}_fib_report.json"


def save_fib_report(report: FibonacciReport, data_dir: str = './correlation_data') -> Path:
    """
    Save a Fibonacci report to the cache.
    
    Args:
        report: The FibonacciReport to save
        data_dir: Base data directory (default: ./correlation_data)
        
    Returns:
        Path to the saved report file
    """
    report_path = get_fib_report_path(data_dir, report.symbol)
    
    # Ensure directory exists
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save as JSON
    with open(report_path, 'w') as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    
    logger.info(f"Saved Fib report for {report.symbol} to {report_path}")
    return report_path


def load_fib_report(symbol: str, data_dir: str = './correlation_data') -> Optional[FibonacciReport]:
    """
    Load a Fibonacci report from the cache.
    
    Args:
        symbol: Token symbol (e.g., 'SOL', 'BTC')
        data_dir: Base data directory (default: ./correlation_data)
        
    Returns:
        FibonacciReport if found, None otherwise
    """
    report_path = get_fib_report_path(data_dir, symbol)
    
    if not report_path.exists():
        logger.debug(f"No cached Fib report found for {symbol} at {report_path}")
        return None
    
    try:
        with open(report_path, 'r') as f:
            data = json.load(f)
        
        report = FibonacciReport.from_dict(data)
        logger.info(f"Loaded Fib report for {symbol} from cache (generated: {data.get('generated_at', 'unknown')})")
        return report
    except Exception as e:
        logger.error(f"Failed to load Fib report for {symbol}: {e}")
        return None


def list_cached_reports(data_dir: str = './correlation_data') -> List[str]:
    """List all symbols with cached Fib reports."""
    reports_dir = Path(data_dir) / FIB_REPORTS_DIR
    if not reports_dir.exists():
        return []
    
    symbols = []
    for f in reports_dir.glob('*_fib_report.json'):
        symbol = f.stem.replace('_fib_report', '')
        symbols.append(symbol)
    
    return sorted(symbols)


# ============================================================================
# Data Loader
# ============================================================================

class DataLoader:
    """Loads collected price data from JSONL files."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)

    def load_symbol(
        self,
        symbol: str,
        recent_seconds: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Load price data for a specific symbol.
        
        Args:
            symbol: Token symbol (e.g., 'SOL', 'BTC')
            recent_seconds: If provided, only load data from the last N seconds
            start_date: If provided, only load data after this date
            end_date: If provided, only load data before this date
            
        Returns:
            DataFrame with columns: timestamp, price (sorted by timestamp)
        """
        all_records = []
        
        if not self.data_dir.exists():
            logger.error(f"Data directory does not exist: {self.data_dir}")
            return pd.DataFrame()
        
        # Find all JSONL files
        jsonl_files = list(self.data_dir.glob('**/*.jsonl'))
        
        if not jsonl_files:
            logger.warning(f"No JSONL files found in {self.data_dir}")
            return pd.DataFrame()
        
        symbol_upper = symbol.upper()
        
        for file_path in sorted(jsonl_files):
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        if record.get('symbol', '').upper() == symbol_upper:
                            all_records.append({
                                'timestamp': record['timestamp'],
                                'price': record['price']
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue
        
        if not all_records:
            logger.warning(f"No records found for symbol {symbol}")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_records)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Apply time filters
        now = datetime.now(timezone.utc)
        
        if recent_seconds:
            cutoff = now - timedelta(seconds=recent_seconds)
            df = df[df['timestamp'] >= cutoff]
        elif start_date or end_date:
            if start_date:
                # Ensure timezone-aware comparison
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                df = df[df['timestamp'] >= start_date]
            if end_date:
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                df = df[df['timestamp'] <= end_date]
        
        return df.reset_index(drop=True)

    def get_available_symbols(self) -> List[str]:
        """Get list of symbols available in the data directory."""
        symbols = set()
        
        if not self.data_dir.exists():
            return []
        
        jsonl_files = list(self.data_dir.glob('**/*.jsonl'))
        
        for file_path in jsonl_files:
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        if 'symbol' in record:
                            symbols.add(record['symbol'].upper())
                    except (json.JSONDecodeError, KeyError):
                        continue
        
        return sorted(symbols)

    def load_csv(self, csv_filename: str) -> pd.DataFrame:
        """
        Load price data from a CSV file with OHLCV format.
        
        Expected CSV format:
            - First column: timestamp (auto-detected, any name)
            - Must have 'Close' column for price data
            - Optional: Open, High, Low, Volume columns
        
        Args:
            csv_filename: Name of CSV file (located in data_dir)
            
        Returns:
            DataFrame with columns: timestamp, price (sorted by timestamp)
        """
        csv_path = self.data_dir / csv_filename
        
        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            logger.error(f"Failed to read CSV file: {e}")
            return pd.DataFrame()
        
        if df.empty:
            logger.warning(f"CSV file is empty: {csv_path}")
            return pd.DataFrame()
        
        # Auto-detect timestamp column (first column)
        timestamp_col = df.columns[0]
        logger.debug(f"Using '{timestamp_col}' as timestamp column")
        
        # Find Close column (case-insensitive)
        close_col = None
        for col in df.columns:
            if col.lower() == 'close':
                close_col = col
                break
        
        if close_col is None:
            logger.error(f"CSV must have a 'Close' column. Found columns: {list(df.columns)}")
            return pd.DataFrame()
        
        # Create standardized DataFrame
        result = pd.DataFrame({
            'timestamp': pd.to_datetime(df[timestamp_col]),
            'price': pd.to_numeric(df[close_col], errors='coerce')
        })
        
        # Remove any rows with invalid data
        result = result.dropna()
        
        # Sort by timestamp
        result = result.sort_values('timestamp').reset_index(drop=True)
        
        logger.info(f"Loaded {len(result)} price points from CSV: {csv_filename}")
        
        return result


# ============================================================================
# Fibonacci Analyzer
# ============================================================================

class FibonacciAnalyzer:
    """
    Analyzes price data for Fibonacci retracement levels.
    
    Standard Fibonacci ratios:
        0.0%   = 0.000 (High point)
        23.6%  = 0.236 (Shallow retracement)
        38.2%  = 0.382 (Common retracement)
        50.0%  = 0.500 (Midpoint - not Fibonacci, but commonly used)
        61.8%  = 0.618 (Golden ratio retracement)
        78.6%  = 0.786 (Deep retracement)
        100.0% = 1.000 (Low point)
    """
    
    STANDARD_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    
    def __init__(
        self,
        data_dir: str = './correlation_data',
        touch_tolerance_pct: float = 0.5,
        confirmation_periods: int = 3,
        min_touches: int = 2
    ):
        """
        Initialize the Fibonacci analyzer.
        
        Args:
            data_dir: Directory containing price data JSONL files
            touch_tolerance_pct: How close price must be to level to count as "touch" (%)
            confirmation_periods: Number of periods price must stay above/below level
                                  after touch to confirm bounce vs breakthrough
            min_touches: Minimum touches to report a level as significant
        """
        self.data_dir = data_dir
        self.data_loader = DataLoader(data_dir)
        self.touch_tolerance_pct = touch_tolerance_pct
        self.confirmation_periods = confirmation_periods
        self.min_touches = min_touches
    
    def analyze(
        self,
        symbol: str,
        window_seconds: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        prices: Optional[List[PricePoint]] = None
    ) -> Optional[FibonacciReport]:
        """
        Perform Fibonacci retracement analysis on price data.
        
        Args:
            symbol: Token symbol to analyze
            window_seconds: Analysis window in seconds (e.g., 7*86400 for 7 days)
            start_date: Start of analysis window
            end_date: End of analysis window
            prices: Optional pre-loaded price data (skips data loading)
            
        Returns:
            FibonacciReport with analysis results, or None if insufficient data
        """
        # Load price data
        if prices is None:
            df = self.data_loader.load_symbol(
                symbol,
                recent_seconds=window_seconds,
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty:
                logger.error(f"No price data found for {symbol}")
                return None
            
            prices = [
                PricePoint(timestamp=row['timestamp'].to_pydatetime(), price=row['price'])
                for _, row in df.iterrows()
            ]
        
        if len(prices) < self.confirmation_periods + 1:
            logger.error(f"Insufficient data points: {len(prices)} (need at least {self.confirmation_periods + 1})")
            return None
        
        # Step 1: Find swing points (high and low)
        high_price, high_idx, low_price, low_idx = self._find_swing_points(prices)
        
        if high_price is None or low_price is None:
            logger.error("Could not identify high/low points")
            return None
        
        high_timestamp = prices[high_idx].timestamp
        low_timestamp = prices[low_idx].timestamp
        
        # Determine trend direction
        trend_direction = 'up' if low_idx < high_idx else 'down'
        
        # Step 2: Calculate Fibonacci levels
        levels = self._calculate_fib_levels(high_price, low_price)
        
        # Step 3: Detect touches and bounces
        self._detect_level_interactions(prices, levels, trend_direction)
        
        # Step 4: Calculate summary statistics
        total_touches = sum(lvl.touch_count for lvl in levels.values())
        total_bounces = sum(lvl.bounce_count for lvl in levels.values())
        
        overall_effectiveness = 0.0
        if total_touches > 0:
            overall_effectiveness = (total_bounces / total_touches) * 100
        
        # Find most respected level (highest bounce rate with min touches)
        most_respected = None
        best_effectiveness = 0.0
        for key, lvl in levels.items():
            if lvl.touch_count >= self.min_touches and lvl.effectiveness is not None:
                if lvl.effectiveness > best_effectiveness:
                    best_effectiveness = lvl.effectiveness
                    most_respected = key
        
        # Determine window string
        if window_seconds:
            window_str = format_duration(window_seconds)
        elif start_date and end_date:
            delta = end_date - start_date
            window_str = format_duration(int(delta.total_seconds()))
        else:
            delta = prices[-1].timestamp - prices[0].timestamp
            window_str = format_duration(int(delta.total_seconds()))
        
        return FibonacciReport(
            symbol=symbol.upper(),
            analysis_window=window_str,
            window_start=prices[0].timestamp,
            window_end=prices[-1].timestamp,
            high_price=high_price,
            high_timestamp=high_timestamp,
            low_price=low_price,
            low_timestamp=low_timestamp,
            trend_direction=trend_direction,
            levels=levels,
            most_respected_level=most_respected,
            overall_effectiveness=overall_effectiveness,
            total_touches=total_touches,
            total_bounces=total_bounces,
            touch_tolerance_pct=self.touch_tolerance_pct,
            confirmation_periods=self.confirmation_periods,
            min_touches=self.min_touches,
            data_points_analyzed=len(prices)
        )
    
    def _find_swing_points(
        self, 
        prices: List[PricePoint]
    ) -> Tuple[Optional[float], Optional[int], Optional[float], Optional[int]]:
        """
        Find the significant high and low within the price data.
        
        Option A (MVP): Absolute high and low in window.
        
        Returns:
            (high_price, high_index, low_price, low_index)
        """
        if not prices:
            return None, None, None, None
        
        high_price = prices[0].price
        high_idx = 0
        low_price = prices[0].price
        low_idx = 0
        
        for i, pp in enumerate(prices):
            if pp.price > high_price:
                high_price = pp.price
                high_idx = i
            if pp.price < low_price:
                low_price = pp.price
                low_idx = i
        
        return high_price, high_idx, low_price, low_idx
    
    def _calculate_fib_levels(
        self,
        high: float,
        low: float
    ) -> Dict[str, FibonacciLevel]:
        """
        Calculate Fibonacci retracement levels.
        
        Formula: retracement_price = high - (high - low) * ratio
        
        Returns:
            Dictionary of FibonacciLevel objects keyed by ratio string
        """
        levels = {}
        price_range = high - low
        
        for ratio in self.STANDARD_RATIOS:
            price = high - (price_range * ratio)
            key = f"{ratio * 100:.1f}%"
            levels[key] = FibonacciLevel(ratio=ratio, price=price)
        
        return levels
    
    def _detect_level_interactions(
        self,
        prices: List[PricePoint],
        levels: Dict[str, FibonacciLevel],
        trend_direction: str
    ):
        """
        Detect touches and bounces at Fibonacci levels.
        
        A "touch" = price comes within tolerance of level
        A "bounce" = after touch, price stays on same side of level for N periods
        A "breakthrough" = after touch, price moves through level and stays for N periods
        
        Args:
            prices: List of price points (sorted by time)
            levels: Dictionary of Fibonacci levels to analyze
            trend_direction: 'up' or 'down' - affects interpretation
        """
        # Skip the extreme levels (0% and 100%) as they are the high/low points themselves
        active_levels = {k: v for k, v in levels.items() if k not in ['0.0%', '100.0%']}
        
        # Track state for each level
        in_touch = {k: False for k in active_levels}
        touch_start_idx = {k: None for k in active_levels}
        touch_side = {k: None for k in active_levels}  # 'above' or 'below'
        
        for i, pp in enumerate(prices):
            price = pp.price
            
            for key, level in active_levels.items():
                level_price = level.price
                tolerance = level_price * (self.touch_tolerance_pct / 100)
                
                distance = abs(price - level_price)
                is_within_tolerance = distance <= tolerance
                is_above = price > level_price
                is_below = price < level_price
                
                if not in_touch[key]:
                    # Check for new touch
                    if is_within_tolerance:
                        in_touch[key] = True
                        touch_start_idx[key] = i
                        # Record which side we approached from
                        if i > 0:
                            prev_price = prices[i - 1].price
                            touch_side[key] = 'above' if prev_price > level_price else 'below'
                        else:
                            touch_side[key] = 'above' if is_above else 'below'
                else:
                    # We're in a touch - check if we've exited
                    if not is_within_tolerance:
                        # Touch ended - classify as bounce or breakthrough
                        periods_in_touch = i - touch_start_idx[key]
                        
                        if periods_in_touch >= 1:
                            level.touch_count += 1
                            
                            # Determine outcome based on exit direction
                            entry_side = touch_side[key]
                            exit_side = 'above' if is_above else 'below'
                            
                            if entry_side == exit_side:
                                # Bounced back to same side
                                level.bounce_count += 1
                                
                                # Calculate bounce magnitude (how far price moved away)
                                if i + self.confirmation_periods < len(prices):
                                    # Look at price after confirmation periods
                                    future_price = prices[i + self.confirmation_periods].price
                                    bounce_pct = abs((future_price - level_price) / level_price) * 100
                                    level.bounce_magnitudes.append(bounce_pct)
                            else:
                                # Broke through to other side
                                level.breakthrough_count += 1
                        
                        # Reset touch state
                        in_touch[key] = False
                        touch_start_idx[key] = None
                        touch_side[key] = None
        
        # Calculate average bounce magnitudes
        for level in active_levels.values():
            if level.bounce_magnitudes:
                level.avg_bounce_magnitude = sum(level.bounce_magnitudes) / len(level.bounce_magnitudes)


# ============================================================================
# Report Formatter
# ============================================================================

def format_report(report: FibonacciReport) -> str:
    """Format a FibonacciReport as a human-readable string."""
    lines = []
    
    lines.append("=" * 70)
    lines.append("                    FIBONACCI RETRACEMENT ANALYSIS")
    lines.append("=" * 70)
    lines.append(f"Symbol: {report.symbol}")
    lines.append(f"Analysis Window: {report.analysis_window} ({report.window_start.strftime('%Y-%m-%d')} to {report.window_end.strftime('%Y-%m-%d')})")
    lines.append(f"Trend Direction: {report.trend_direction.upper()}TREND ({'low before high' if report.trend_direction == 'up' else 'high before low'})")
    lines.append(f"Data Points Analyzed: {report.data_points_analyzed}")
    lines.append("")
    lines.append("Price Range:")
    lines.append(f"  High: {format_price(report.high_price)} ({report.high_timestamp.strftime('%Y-%m-%d %H:%M')} UTC)")
    lines.append(f"  Low:  {format_price(report.low_price)} ({report.low_timestamp.strftime('%Y-%m-%d %H:%M')} UTC)")
    price_range = report.high_price - report.low_price
    range_pct = (price_range / report.low_price) * 100 if report.low_price > 0 else 0
    lines.append(f"  Range: {format_price(price_range)} ({range_pct:.1f}%)")
    lines.append("")
    lines.append("-" * 70)
    lines.append("                         FIBONACCI LEVELS")
    lines.append("-" * 70)
    lines.append(f"{'Level':<10}{'Price':<14}{'Touches':<10}{'Bounces':<10}{'Break':<12}{'Effectiveness':<14}")
    lines.append("-" * 70)
    
    for key in ['0.0%', '23.6%', '38.2%', '50.0%', '61.8%', '78.6%', '100.0%']:
        level = report.levels.get(key)
        if level:
            if key == '0.0%':
                eff_str = "(High)"
            elif key == '100.0%':
                eff_str = "(Low)"
            elif level.effectiveness is not None:
                eff_str = f"{level.effectiveness:.1f}%"
            else:
                eff_str = "-"
            
            touch_str = str(level.touch_count) if level.touch_count > 0 else "-"
            bounce_str = str(level.bounce_count) if level.bounce_count > 0 else "-"
            break_str = str(level.breakthrough_count) if level.breakthrough_count > 0 else "-"
            
            price_str = format_price(level.price)
            lines.append(f"{key:<10}{price_str:<14}{touch_str:<10}{bounce_str:<10}{break_str:<12}{eff_str:<14}")
    
    lines.append("-" * 70)
    lines.append("")
    
    # Summary
    if report.most_respected_level:
        level = report.levels[report.most_respected_level]
        lines.append(f"Most Respected Level: {report.most_respected_level} ({format_price(level.price)}) - {level.effectiveness:.1f}% bounce rate")
    else:
        lines.append("Most Respected Level: (insufficient touches to determine)")
    
    lines.append(f"Overall Effectiveness: {report.overall_effectiveness:.1f}% ({report.total_bounces}/{report.total_touches} touches resulted in bounces)")
    lines.append("")
    
    # Interpretation
    lines.append("Interpretation:")
    
    # Find strong support/resistance zones
    significant_levels = [
        (k, v) for k, v in report.levels.items() 
        if v.touch_count >= report.min_touches and v.effectiveness is not None and v.effectiveness >= 60
    ]
    
    if significant_levels:
        # Sort by price
        significant_levels.sort(key=lambda x: x[1].price, reverse=True)
        
        if len(significant_levels) >= 2:
            high_lvl = significant_levels[0]
            low_lvl = significant_levels[-1]
            lines.append(f"  • Strong support/resistance zone: {low_lvl[0]}-{high_lvl[0]} ({format_price(low_lvl[1].price)}-{format_price(high_lvl[1].price)})")
        else:
            lvl = significant_levels[0]
            zone_type = "resistance" if report.trend_direction == 'up' else "support"
            lines.append(f"  • Key {zone_type} level: {lvl[0]} ({format_price(lvl[1].price)})")
    
    # Find weak levels
    weak_levels = [
        (k, v) for k, v in report.levels.items()
        if v.touch_count >= report.min_touches and v.effectiveness is not None and v.effectiveness < 50
    ]
    
    for key, level in weak_levels:
        lines.append(f"  • {key} level showed weakness (more breakthroughs than bounces)")
    
    if significant_levels:
        lines.append("  • Consider these levels for entry/exit planning")
    else:
        lines.append("  • No levels met significance criteria (try adjusting --min-touches)")
    
    lines.append("=" * 70)
    
    return "\n".join(lines)


def format_summary_table(reports: List[FibonacciReport]) -> str:
    """Format a summary table for multiple symbol reports."""
    lines = []
    
    lines.append("=" * 90)
    lines.append("                         FIBONACCI ANALYSIS SUMMARY")
    lines.append("=" * 90)
    lines.append(f"{'Symbol':<10}{'Trend':<8}{'High':<12}{'Low':<12}{'Range%':<10}{'Touches':<10}{'Effect%':<10}{'Best Level':<12}")
    lines.append("-" * 90)
    
    for report in sorted(reports, key=lambda r: r.overall_effectiveness, reverse=True):
        range_pct = ((report.high_price - report.low_price) / report.low_price * 100) if report.low_price > 0 else 0
        best_level = report.most_respected_level or "-"
        
        lines.append(
            f"{report.symbol:<10}"
            f"{report.trend_direction.upper():<8}"
            f"${report.high_price:<11.4f}"
            f"${report.low_price:<11.4f}"
            f"{range_pct:<10.1f}"
            f"{report.total_touches:<10}"
            f"{report.overall_effectiveness:<10.1f}"
            f"{best_level:<12}"
        )
    
    lines.append("-" * 90)
    lines.append(f"Total symbols analyzed: {len(reports)}")
    
    # Find top performers
    effective_reports = [r for r in reports if r.overall_effectiveness >= 60 and r.total_touches >= 5]
    if effective_reports:
        lines.append("\nTop Fibonacci responders (>60% effectiveness, >5 touches):")
        for r in sorted(effective_reports, key=lambda x: x.overall_effectiveness, reverse=True)[:5]:
            lines.append(f"  • {r.symbol}: {r.overall_effectiveness:.1f}% effectiveness at {r.most_respected_level}")
    
    lines.append("=" * 90)
    
    return "\n".join(lines)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Fibonacci Retracement Analysis - Analyze price data for Fib levels',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze SOL for the last 7 days (from JSONL data)
  python fibonacci_analyzer.py --symbol SOL --window 7d
  
  # Analyze from CSV file (OHLCV format)
  python fibonacci_analyzer.py --symbol BTC --csv btc_prices.csv
  
  # Analyze multiple symbols
  python fibonacci_analyzer.py --symbol SOL,BTC,ETH --window 7d
  
  # Analyze ALL symbols in data directory
  python fibonacci_analyzer.py --window 7d
  
  # With custom tolerance and confirmation
  python fibonacci_analyzer.py --symbol BTC --window 24h --touch-tolerance 0.3 --confirmation-periods 5
  
  # Output as JSON
  python fibonacci_analyzer.py --symbol ETH --window 3d --output-format json
  
  # Save report to cache for use by leading_indicator_tester --use-fib
  python fibonacci_analyzer.py --symbol SOL --window 7d --save-report
  
  # List cached reports
  python fibonacci_analyzer.py --list-cached
  
  # List available symbols
  python fibonacci_analyzer.py --list-symbols
        """
    )
    
    parser.add_argument('--symbol', type=str,
                        help='Token symbol(s) to analyze. Comma-separated for multiple (e.g., SOL,BTC,ETH). '
                             'If omitted, analyzes ALL symbols in data directory. Required when using --csv.')
    parser.add_argument('--window', type=str, default='7d',
                        help='Analysis window (e.g., 24h, 7d, 14days). Default: 7d. Ignored when using --csv.')
    parser.add_argument('--data-dir', type=str, default='./correlation_data',
                        help='Directory containing price data (default: ./correlation_data)')
    parser.add_argument('--csv', type=str, metavar='FILENAME',
                        help='Load data from CSV file (OHLCV format) instead of JSONL. '
                             'File should be in --data-dir. Requires --symbol.')
    
    # Analysis parameters
    parser.add_argument('--touch-tolerance', type=float, default=0.5,
                        help='Tolerance %% for level touch detection (default: 0.5)')
    parser.add_argument('--confirmation-periods', type=int, default=3,
                        help='Periods to confirm bounce vs breakthrough (default: 3)')
    parser.add_argument('--min-touches', type=int, default=2,
                        help='Minimum touches to report level as significant (default: 2)')
    
    # Output options
    parser.add_argument('--output-format', type=str, default='text',
                        choices=['text', 'json'],
                        help='Output format (default: text)')
    parser.add_argument('--output-file', type=str,
                        help='Write output to file instead of stdout')
    parser.add_argument('--summary-only', action='store_true',
                        help='Only show summary table when analyzing multiple symbols')
    
    # Cache options
    parser.add_argument('--save-report', action='store_true',
                        help='Save analysis report(s) to cache for use by leading_indicator_tester --use-fib')
    parser.add_argument('--list-cached', action='store_true',
                        help='List symbols with cached Fib reports')
    
    # Utility options
    parser.add_argument('--list-symbols', action='store_true',
                        help='List available symbols in data directory')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize data loader for symbol discovery
    loader = DataLoader(args.data_dir)
    
    # Handle --list-symbols
    if args.list_symbols:
        symbols = loader.get_available_symbols()
        if symbols:
            print("Available symbols:")
            for sym in symbols:
                print(f"  - {sym}")
        else:
            print(f"No data found in {args.data_dir}")
        return
    
    # Handle --list-cached
    if args.list_cached:
        cached = list_cached_reports(args.data_dir)
        if cached:
            print("Cached Fib reports:")
            for sym in cached:
                report_path = get_fib_report_path(args.data_dir, sym)
                # Get generated_at from file
                try:
                    with open(report_path, 'r') as f:
                        data = json.load(f)
                    generated = data.get('generated_at', 'unknown')
                    trend = data.get('trend_direction', '?')
                    print(f"  - {sym}: {trend}trend (generated: {generated})")
                except:
                    print(f"  - {sym}")
        else:
            print(f"No cached Fib reports in {args.data_dir}/fib_reports/")
        return
    
    # Validate CSV mode requirements
    if args.csv and not args.symbol:
        parser.error("--symbol is required when using --csv")
    
    # Run analysis
    analyzer = FibonacciAnalyzer(
        data_dir=args.data_dir,
        touch_tolerance_pct=args.touch_tolerance,
        confirmation_periods=args.confirmation_periods,
        min_touches=args.min_touches
    )
    
    reports = []
    failed_symbols = []
    
    # CSV mode: load from CSV file
    if args.csv:
        symbols = [s.strip().upper() for s in args.symbol.split(',') if s.strip()]
        
        # Load CSV data once
        csv_df = loader.load_csv(args.csv)
        if csv_df.empty:
            print(f"Error: Could not load data from CSV file: {args.csv}")
            print(f"Make sure the file exists in {args.data_dir} and has a 'Close' column")
            sys.exit(1)
        
        # Convert to PricePoints for analysis
        prices = [
            PricePoint(timestamp=row['timestamp'].to_pydatetime(), price=row['price'])
            for _, row in csv_df.iterrows()
        ]
        
        # Analyze each symbol with the same CSV data
        for symbol in symbols:
            report = analyzer.analyze(symbol, prices=prices)
            if report:
                reports.append(report)
            else:
                failed_symbols.append(symbol)
        
        if not reports:
            print(f"Error: Could not generate any reports from CSV data")
            sys.exit(1)
    
    # JSONL mode: load from data directory
    else:
        # Parse window
        try:
            window_seconds = parse_duration(args.window)
        except ValueError as e:
            parser.error(f"Invalid --window: {e}")
        
        # Determine symbols to analyze
        if args.symbol:
            # Parse comma-separated list
            symbols = [s.strip().upper() for s in args.symbol.split(',') if s.strip()]
        else:
            # Analyze all available symbols
            symbols = loader.get_available_symbols()
            if not symbols:
                print(f"No symbols found in {args.data_dir}")
                print("Use --list-symbols to check available data or specify --symbol")
                sys.exit(1)
            print(f"No --symbol specified. Analyzing all {len(symbols)} symbols in {args.data_dir}...\n")
        
        for symbol in symbols:
            report = analyzer.analyze(symbol, window_seconds=window_seconds)
            if report:
                reports.append(report)
            else:
                failed_symbols.append(symbol)
                if args.verbose:
                    logger.warning(f"Could not generate report for {symbol}")
        
        if not reports:
            print("Error: Could not generate any reports")
            print(f"Failed symbols: {', '.join(failed_symbols)}")
            sys.exit(1)
    
    # Save reports to cache if requested
    if args.save_report:
        saved_count = 0
        for report in reports:
            try:
                save_fib_report(report, args.data_dir)
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save report for {report.symbol}: {e}")
        print(f"\nSaved {saved_count} report(s) to {args.data_dir}/fib_reports/")
    
    # Format output
    if args.output_format == 'json':
        if len(reports) == 1:
            output = json.dumps(reports[0].to_dict(), indent=2, default=str)
        else:
            output = json.dumps({
                'summary': {
                    'total_symbols': len(reports),
                    'failed_symbols': failed_symbols,
                    'window': args.window
                },
                'reports': [r.to_dict() for r in reports]
            }, indent=2, default=str)
    else:
        if len(reports) == 1:
            output = format_report(reports[0])
        else:
            # Multiple reports - show summary and optionally full reports
            output_parts = []
            
            if not args.summary_only:
                for report in reports:
                    output_parts.append(format_report(report))
                    output_parts.append("")  # Blank line between reports
            
            output_parts.append(format_summary_table(reports))
            
            if failed_symbols:
                output_parts.append(f"\nNote: Failed to analyze {len(failed_symbols)} symbol(s): {', '.join(failed_symbols)}")
            
            output = "\n".join(output_parts)
    
    # Write output
    if args.output_file:
        with open(args.output_file, 'w') as f:
            f.write(output)
        print(f"Report written to {args.output_file}")
    else:
        print(output)


if __name__ == '__main__':
    main()
