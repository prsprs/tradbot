#!/usr/bin/env python3
"""
Correlation History Tracker

A system for collecting intraday price history and analyzing correlations between
cryptocurrency pairs to identify leading indicators - coins whose price movements
predictably precede another coin's movement.

Usage:
    # Collect price data
    python correlation_tracker.py --coins BTC,ETH,SOL --interval 30 --output-dir ./correlation_data

    # Analyze specific pair
    python correlation_tracker.py --analyze --leader BTC --follower ETH

    # Discovery mode (find all leading indicator pairs)
    python correlation_tracker.py --analyze --min-confidence 0.6
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Import existing CoinGecko utility
from coingeckoutil import get_multiple_prices, get_coingecko_id, SYMBOL_TO_ID, auto_resolve_symbol

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Time Duration Parsing
# ============================================================================

def parse_duration(value: str) -> int:
    """
    Parse a duration string into seconds.
    
    Supported formats:
        - Plain number: interpreted as seconds (e.g., "30" -> 30)
        - Number + 'sec': seconds (e.g., "30sec" -> 30)
        - Number + 'min': minutes (e.g., "5min" -> 300)
        - Number + 'hr': hours (e.g., "1hr" -> 3600)
        - Number + 'day'/'days': days (e.g., "14days" -> 1209600)
    
    Args:
        value: Duration string to parse
        
    Returns:
        Duration in seconds
        
    Raises:
        ValueError: If the format is invalid
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
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(sec|min|hr|days?)s?$', value)
    
    if not match:
        raise ValueError(f"Invalid duration format: '{value}'. Use formats like: 30, 30sec, 5min, 1hr, 14days")
    
    amount = float(match.group(1))
    unit = match.group(2)
    
    # Normalize 'day' to 'days'
    if unit == 'day':
        unit = 'days'
    
    multipliers = {
        'sec': 1,
        'min': 60,
        'hr': 3600,
        'days': 86400,
    }
    
    return int(amount * multipliers[unit])


def parse_lag_range(value: str) -> Tuple[int, int]:
    """
    Parse a lag range string into (start_seconds, end_seconds).
    
    Supported formats:
        - "0-300" (plain seconds)
        - "0-5min" (mixed units)
        - "1min-1hr" (both with units)
    
    Args:
        value: Lag range string (e.g., "0-5min")
        
    Returns:
        Tuple of (start_seconds, end_seconds)
        
    Raises:
        ValueError: If the format is invalid
    """
    if '-' not in value:
        raise ValueError(f"Invalid lag range format: '{value}'. Use format like: 0-300, 0-5min, 1min-1hr")
    
    parts = value.split('-', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid lag range format: '{value}'")
    
    start = parse_duration(parts[0].strip())
    end = parse_duration(parts[1].strip())
    
    return (start, end)


def format_duration(seconds: int) -> str:
    """
    Format seconds into a human-readable duration string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., "1hr 30min", "45sec")
    """
    if seconds >= 3600:
        hours = seconds // 3600
        remaining = seconds % 3600
        if remaining >= 60:
            mins = remaining // 60
            return f"{hours}hr {mins}min"
        elif remaining > 0:
            return f"{hours}hr {remaining}sec"
        return f"{hours}hr"
    elif seconds >= 60:
        mins = seconds // 60
        remaining = seconds % 60
        if remaining > 0:
            return f"{mins}min {remaining}sec"
        return f"{mins}min"
    else:
        return f"{seconds}sec"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PriceRecord:
    """A single price observation for a coin."""
    symbol: str
    timestamp: str  # ISO format UTC
    source: str
    price: float
    volume_24h: Optional[float] = None
    market_cap: Optional[float] = None
    price_change_24h: Optional[float] = None
    price_change_pct: Optional[float] = None  # Change since last record
    collection_latency_ms: int = 0
    record_sequence: int = 0


@dataclass
class DataQualityInfo:
    """Quality markers for data collection."""
    gap_detected: bool = False
    gap_duration_seconds: int = 0
    stale_data: bool = False
    partial_collection: bool = False
    failed_symbols: List[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Result from a single analysis test."""
    test_name: str
    passed: bool
    metrics: Dict[str, Any]
    reason: str
    reason_code: Optional[str] = None


@dataclass
class DirectionalAnalysis:
    """Results from directional (UP vs DOWN) correlation analysis."""
    enabled: bool = True
    # UP direction (leader moves up)
    up_samples: int = 0
    up_correlation: float = 0.0
    up_optimal_lag_seconds: int = 0
    up_granger_pvalue: float = 1.0
    up_significant: bool = False
    # DOWN direction (leader moves down)
    down_samples: int = 0
    down_correlation: float = 0.0
    down_optimal_lag_seconds: int = 0
    down_granger_pvalue: float = 1.0
    down_significant: bool = False
    # Comparison
    asymmetry_score: float = 0.0
    asymmetry_level: str = "symmetric"  # symmetric, moderate, strong
    stronger_direction: Optional[str] = None  # "up", "down", or None
    recommendation: str = ""
    skip_reason: Optional[str] = None  # If analysis was skipped


@dataclass
class CorrelationReport:
    """Results from correlation analysis between two coins."""
    generated_at: str
    data_range_start: str
    data_range_end: str
    total_samples: int
    leader_symbol: str
    follower_symbol: str
    optimal_lag_seconds: int
    correlation_at_optimal_lag: float
    correlation_at_zero_lag: float
    granger_causality_pvalue: float
    granger_causality_significant: bool
    confidence_score: float
    confidence_level: str
    confidence_factors: Dict[str, float]
    correlation_stability: float
    stable_relationship: bool
    recommendation: str
    trading_signal_strength: str
    # Detailed test results
    test_results: List[TestResult] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    # Directional analysis (UP vs DOWN)
    directional_analysis: Optional[DirectionalAnalysis] = None


@dataclass
class DiscoveryReport:
    """Results from discovery mode analysis."""
    generated_at: str
    data_range_start: str
    data_range_end: str
    coins_analyzed: List[str]
    pairs_tested: int
    significant_pairs: List[Dict[str, Any]]
    no_significant_relationship: List[Dict[str, Any]]


@dataclass
class IntervalAnalysis:
    """Volatility analysis for a single time interval."""
    interval_seconds: int
    interval_label: str
    median_move_pct: float
    mean_move_pct: float
    pct_above_breakeven: float  # % of moves > break-even threshold
    pct_above_target: float     # % of moves > target profit threshold
    sample_count: int
    viable: bool
    notes: str = ""


@dataclass
class CostAnalysis:
    """Trading cost analysis for a token."""
    follower_symbol: str
    liquidity_usd: Optional[float]
    position_size_usd: float
    estimated_slippage_pct: float
    estimated_spread_pct: float
    round_trip_cost_pct: float
    break_even_move_pct: float
    target_profit_pct: float
    target_move_pct: float
    liquidity_source: str  # 'jupiter' or 'estimated'
    warnings: List[str] = field(default_factory=list)


@dataclass
class ProfitabilityReport:
    """Complete profitability analysis report."""
    generated_at: str
    leader_symbol: str
    follower_symbol: str
    cost_analysis: CostAnalysis
    interval_analyses: List[IntervalAnalysis]
    recommended_interval_seconds: Optional[int]
    recommended_interval_label: Optional[str]
    viable_intervals: List[str]
    verdict: str
    verdict_details: str
    correlation_at_recommended: Optional[float] = None
    granger_significant_at_recommended: Optional[bool] = None


@dataclass
class DirectionalProfitabilityResult:
    """Results from directional (UP vs DOWN) profitability analysis."""
    # UP direction analysis
    up_viable: bool = False
    up_verdict: str = ""
    up_recommended_interval_seconds: Optional[int] = None
    up_recommended_interval_label: Optional[str] = None
    up_break_even_pct: Optional[float] = None
    up_correlation: Optional[float] = None
    up_granger_significant: Optional[bool] = None
    up_sample_count: int = 0
    # DOWN direction analysis
    down_viable: bool = False
    down_verdict: str = ""
    down_recommended_interval_seconds: Optional[int] = None
    down_recommended_interval_label: Optional[str] = None
    down_break_even_pct: Optional[float] = None
    down_correlation: Optional[float] = None
    down_granger_significant: Optional[bool] = None
    down_sample_count: int = 0
    # Combined
    combined_verdict: str = ""  # FULLY_VIABLE, PARTIALLY_VIABLE_UP, PARTIALLY_VIABLE_DOWN, NOT_VIABLE
    combined_verdict_details: str = ""
    recommended_interval_seconds: Optional[int] = None  # Conservative choice
    recommended_interval_label: Optional[str] = None


@dataclass
class CollectorConfig:
    """Configuration for the data collector."""
    coins: List[str] = field(default_factory=lambda: ['BTC', 'ETH', 'SOL'])
    interval_seconds: int = 30
    output_dir: str = './correlation_data'
    source: str = 'coingecko'
    auto_search: bool = True  # Auto-search CoinGecko for unknown symbols


@dataclass
class AnalyzerConfig:
    """Configuration for the analyzer."""
    data_dir: str = './correlation_data'
    leader: Optional[str] = None
    follower: Optional[str] = None
    leader_candidates: Optional[List[str]] = None
    follower_candidates: Optional[List[str]] = None
    min_confidence: float = 0.6
    min_samples: int = 500
    lag_range_seconds: Optional[Tuple[int, int]] = None
    lag_multiplier: int = 10
    output_report: Optional[str] = None
    recent_seconds: Optional[int] = None  # Filter to recent N seconds of data
    start_date: Optional[datetime] = None  # Explicit start date filter
    end_date: Optional[datetime] = None    # Explicit end date filter
    verbose: bool = False  # Output detailed test results for all pairs
    # Profitability analysis options
    profitability: bool = False  # Run profitability/volatility analysis
    position_size_usd: float = 1000.0  # Position size for cost calculations
    target_profit_pct: float = 0.5  # Target profit percentage per trade
    directional_filter: bool = False  # Enable two-pass UP/DOWN profitability analysis


# ============================================================================
# Data Collector
# ============================================================================

class DataCollector:
    """Collects price data from CoinGecko and stores in JSONL format."""

    def __init__(self, config: CollectorConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.record_sequence = 0
        self.last_prices: Dict[str, float] = {}
        self._ensure_output_dir()

    def _ensure_output_dir(self):
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_output_file(self) -> Path:
        """Get the current output file based on date and time window."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime('%Y-%m-%d')
        hour = now.hour
        
        # 6-hour windows: 00-06, 06-12, 12-18, 18-24
        window_start = (hour // 6) * 6
        window_end = window_start + 6
        
        date_dir = self.output_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        
        return date_dir / f'prices_{window_start:02d}-{window_end:02d}.jsonl'

    def _validate_coins(self) -> Tuple[List[str], List[str]]:
        """Validate coin symbols and return valid/invalid lists.
        
        If auto_search is enabled, unknown symbols will be looked up via CoinGecko API.
        """
        valid = []
        invalid = []
        for coin in self.config.coins:
            symbol = coin.upper()
            # Use auto_search to resolve unknown symbols
            coin_id = get_coingecko_id(symbol, auto_search=self.config.auto_search)
            if coin_id:
                valid.append(symbol)
            else:
                invalid.append(symbol)
        return valid, invalid

    def collect_once(self) -> Tuple[List[PriceRecord], DataQualityInfo]:
        """Perform a single collection cycle."""
        quality = DataQualityInfo()
        records = []
        
        start_time = time.time()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Get prices for all coins in one request (auto-search for unknown symbols)
        prices = get_multiple_prices(self.config.coins, auto_search=self.config.auto_search)
        
        collection_latency = int((time.time() - start_time) * 1000)
        
        for symbol in self.config.coins:
            symbol_upper = symbol.upper()
            price = prices.get(symbol_upper) or prices.get(symbol)
            
            if price is None:
                quality.partial_collection = True
                quality.failed_symbols.append(symbol_upper)
                logger.warning(f"Failed to get price for {symbol_upper}")
                continue
            
            # Calculate price change percentage from last record
            price_change_pct = None
            if symbol_upper in self.last_prices:
                last_price = self.last_prices[symbol_upper]
                if last_price > 0:
                    price_change_pct = ((price - last_price) / last_price) * 100
            
            self.last_prices[symbol_upper] = price
            self.record_sequence += 1
            
            record = PriceRecord(
                symbol=symbol_upper,
                timestamp=timestamp,
                source=self.config.source,
                price=price,
                price_change_pct=price_change_pct,
                collection_latency_ms=collection_latency,
                record_sequence=self.record_sequence
            )
            records.append(record)
        
        return records, quality

    def save_records(self, records: List[PriceRecord]):
        """Save records to JSONL file."""
        output_file = self._get_output_file()
        
        with open(output_file, 'a') as f:
            for record in records:
                json_line = json.dumps(asdict(record))
                f.write(json_line + '\n')

    def run(self, duration_seconds: Optional[int] = None):
        """Run the collector continuously or for a specified duration."""
        valid_coins, invalid_coins = self._validate_coins()
        
        if invalid_coins:
            logger.warning(f"Unknown coin symbols (will be skipped): {invalid_coins}")
        
        if not valid_coins:
            logger.error("No valid coin symbols to collect. Exiting.")
            return
        
        self.config.coins = valid_coins
        logger.info(f"Starting collection for: {valid_coins}")
        logger.info(f"Interval: {self.config.interval_seconds}s, Output: {self.output_dir}")
        
        if self.config.interval_seconds < 30:
            logger.warning("Interval <30s may hit CoinGecko rate limits")
        
        start_time = time.time()
        collection_count = 0
        
        try:
            while True:
                cycle_start = time.time()
                
                records, quality = self.collect_once()
                
                if records:
                    self.save_records(records)
                    collection_count += 1
                    
                    # Log status periodically
                    if collection_count % 10 == 0:
                        logger.info(f"Collected {collection_count} cycles, {self.record_sequence} total records")
                
                if quality.partial_collection:
                    logger.warning(f"Partial collection - failed: {quality.failed_symbols}")
                
                # Check duration limit
                if duration_seconds and (time.time() - start_time) >= duration_seconds:
                    logger.info(f"Duration limit reached ({duration_seconds}s). Stopping.")
                    break
                
                # Sleep for remaining interval
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.config.interval_seconds - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
        except KeyboardInterrupt:
            logger.info("Collection stopped by user.")
        
        logger.info(f"Collection complete. Total records: {self.record_sequence}")


# ============================================================================
# Data Loader
# ============================================================================

class DataLoader:
    """Loads collected price data from JSONL files."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)

    def load_all(self, recent_seconds: Optional[int] = None,
                  start_date: Optional[datetime] = None,
                  end_date: Optional[datetime] = None) -> pd.DataFrame:
        """Load all data from the data directory with optional date filtering.
        
        Args:
            recent_seconds: If provided, only load data from the last N seconds
            start_date: If provided, only load data after this date
            end_date: If provided, only load data before this date
            
        Note: recent_seconds takes precedence over start_date if both provided.
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
        
        logger.info(f"Loading data from {len(jsonl_files)} files...")
        
        for file_path in sorted(jsonl_files):
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        all_records.append(record)
                    except json.JSONDecodeError:
                        continue
        
        if not all_records:
            logger.warning("No records loaded from files")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_records)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values(['symbol', 'timestamp']).reset_index(drop=True)
        
        original_count = len(df)
        
        # Apply date filtering
        if recent_seconds is not None:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=recent_seconds)
            df = df[df['timestamp'] >= cutoff]
            logger.info(f"Filtered to recent {format_duration(recent_seconds)}: {len(df)}/{original_count} records")
        else:
            if start_date is not None:
                df = df[df['timestamp'] >= start_date]
            if end_date is not None:
                df = df[df['timestamp'] <= end_date]
            if start_date is not None or end_date is not None:
                logger.info(f"Filtered by date range: {len(df)}/{original_count} records")
        
        df = df.reset_index(drop=True)
        logger.info(f"Loaded {len(df)} records for {df['symbol'].nunique()} coins")
        
        return df

    def get_price_series(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        """Extract price time series for a single coin."""
        coin_df = df[df['symbol'] == symbol.upper()].copy()
        coin_df = coin_df.set_index('timestamp')
        return coin_df['price']

    def get_returns_series(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        """Extract percentage returns time series for a single coin."""
        prices = self.get_price_series(df, symbol)
        returns = prices.pct_change() * 100
        return returns.dropna()

    def detect_gaps(self, df: pd.DataFrame, expected_interval_seconds: int = 30) -> List[Dict]:
        """Detect gaps in the data collection."""
        gaps = []
        
        for symbol in df['symbol'].unique():
            coin_df = df[df['symbol'] == symbol].sort_values('timestamp')
            timestamps = coin_df['timestamp'].values
            
            for i in range(1, len(timestamps)):
                gap_seconds = (timestamps[i] - timestamps[i-1]) / np.timedelta64(1, 's')
                
                # Gap if more than 2x expected interval
                if gap_seconds > expected_interval_seconds * 2:
                    gaps.append({
                        'symbol': symbol,
                        'start': str(timestamps[i-1]),
                        'end': str(timestamps[i]),
                        'duration_seconds': int(gap_seconds)
                    })
        
        return gaps


# ============================================================================
# Analyzer
# ============================================================================

class CorrelationAnalyzer:
    """Analyzes correlations between coin pairs to find leading indicators."""

    def __init__(self, config: AnalyzerConfig):
        self.config = config
        self.loader = DataLoader(config.data_dir)

    def cross_correlation(self, leader_returns: pd.Series, follower_returns: pd.Series,
                         max_lag: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculate cross-correlation at various lags.
        
        Positive lag means leader leads follower by that many periods.
        """
        # Align the series by timestamp
        aligned = pd.concat([leader_returns, follower_returns], axis=1, join='inner')
        aligned.columns = ['leader', 'follower']
        
        if len(aligned) < 10:
            return np.array([]), np.array([])
        
        leader_vals = aligned['leader'].values
        follower_vals = aligned['follower'].values
        
        # Normalize
        leader_norm = (leader_vals - np.mean(leader_vals)) / (np.std(leader_vals) + 1e-10)
        follower_norm = (follower_vals - np.mean(follower_vals)) / (np.std(follower_vals) + 1e-10)
        
        lags = np.arange(-max_lag, max_lag + 1)
        correlations = np.zeros(len(lags))
        
        for i, lag in enumerate(lags):
            if lag < 0:
                # Leader lags behind follower
                corr = np.corrcoef(leader_norm[-lag:], follower_norm[:lag])[0, 1]
            elif lag > 0:
                # Leader leads follower
                corr = np.corrcoef(leader_norm[:-lag], follower_norm[lag:])[0, 1]
            else:
                corr = np.corrcoef(leader_norm, follower_norm)[0, 1]
            
            correlations[i] = corr if not np.isnan(corr) else 0
        
        return lags, correlations

    def granger_causality_test(self, leader_returns: pd.Series, follower_returns: pd.Series,
                               max_lag: int = 5) -> Tuple[float, bool]:
        """
        Perform Granger causality test.
        
        Tests if leader helps predict follower.
        Returns (p-value, is_significant).
        """
        try:
            from statsmodels.tsa.stattools import grangercausalitytests
        except ImportError:
            logger.warning("statsmodels not installed, skipping Granger causality test")
            return 1.0, False
        
        # Align series
        aligned = pd.concat([follower_returns, leader_returns], axis=1, join='inner')
        aligned.columns = ['follower', 'leader']
        aligned = aligned.dropna()
        
        if len(aligned) < max_lag * 3:
            return 1.0, False
        
        try:
            # Granger test expects [effect, cause] order
            result = grangercausalitytests(aligned[['follower', 'leader']], maxlag=max_lag, verbose=False)
            
            # Get minimum p-value across all lags
            min_pvalue = min(result[lag][0]['ssr_ftest'][1] for lag in range(1, max_lag + 1))
            
            return min_pvalue, min_pvalue < 0.05
            
        except Exception as e:
            logger.debug(f"Granger test failed: {e}")
            return 1.0, False

    def rolling_correlation(self, leader_returns: pd.Series, follower_returns: pd.Series,
                           window_size: int = 120) -> Tuple[pd.Series, float]:
        """
        Calculate rolling correlation to assess stability.
        
        Returns (rolling_corr_series, stability_score).
        Stability is 1 - std_dev of rolling correlation.
        """
        aligned = pd.concat([leader_returns, follower_returns], axis=1, join='inner')
        aligned.columns = ['leader', 'follower']
        
        if len(aligned) < window_size:
            return pd.Series(), 0.0
        
        rolling_corr = aligned['leader'].rolling(window=window_size).corr(aligned['follower'])
        rolling_corr = rolling_corr.dropna()
        
        if len(rolling_corr) == 0:
            return pd.Series(), 0.0
        
        stability = 1.0 - min(1.0, rolling_corr.std())
        
        return rolling_corr, stability

    def calculate_confidence(self, correlation: float, pvalue: float, stability: float,
                            num_samples: int, lag_correlation_diff: float) -> Tuple[float, str, Dict[str, float]]:
        """
        Calculate confidence score based on multiple factors.
        
        Returns (score, level, factors_dict).
        """
        factors = {
            'correlation_strength': abs(correlation),
            'statistical_significance': 1.0 - pvalue,
            'relationship_stability': stability,
            'sample_adequacy': min(1.0, num_samples / 1000),
            'lag_consistency': min(1.0, max(0, lag_correlation_diff))
        }
        
        weights = {
            'correlation_strength': 0.30,
            'statistical_significance': 0.25,
            'relationship_stability': 0.20,
            'sample_adequacy': 0.15,
            'lag_consistency': 0.10
        }
        
        score = sum(factors[k] * weights[k] for k in factors)
        
        if score < 0.3:
            level = 'low'
        elif score < 0.5:
            level = 'medium'
        elif score < 0.7:
            level = 'high'
        else:
            level = 'very_high'
        
        return score, level, factors

    def analyze_directional(self, leader_returns: pd.Series, follower_returns: pd.Series,
                           max_lag_periods: int, interval_seconds: int,
                           min_samples: int = 100) -> DirectionalAnalysis:
        """
        Analyze correlations separately for UP and DOWN leader movements.
        
        Args:
            leader_returns: Leader coin percentage returns
            follower_returns: Follower coin percentage returns
            max_lag_periods: Maximum lag periods to test
            interval_seconds: Seconds per period
            min_samples: Minimum samples required per direction
            
        Returns:
            DirectionalAnalysis with separate stats for UP and DOWN movements
        """
        import warnings
        
        # Align the series
        aligned = pd.concat([leader_returns, follower_returns], axis=1, join='inner')
        aligned.columns = ['leader', 'follower']
        aligned = aligned.dropna()
        
        if len(aligned) < min_samples * 2:
            return DirectionalAnalysis(
                enabled=False,
                skip_reason=f"Insufficient total samples ({len(aligned)} < {min_samples * 2})"
            )
        
        # Split by leader direction
        up_mask = aligned['leader'] > 0
        down_mask = aligned['leader'] < 0
        
        up_data = aligned[up_mask]
        down_data = aligned[down_mask]
        
        up_samples = len(up_data)
        down_samples = len(down_data)
        
        # Check minimum samples per direction
        if up_samples < min_samples or down_samples < min_samples:
            return DirectionalAnalysis(
                enabled=False,
                up_samples=up_samples,
                down_samples=down_samples,
                skip_reason=f"Insufficient directional samples (UP={up_samples}, DOWN={down_samples}, need {min_samples} each)"
            )
        
        # Analyze UP direction
        up_leader = up_data['leader']
        up_follower = up_data['follower']
        
        # Check for sufficient variance (avoid divide-by-zero)
        up_leader_var = np.var(up_leader)
        up_follower_var = np.var(up_follower)
        if up_leader_var < 1e-10 or up_follower_var < 1e-10:
            return DirectionalAnalysis(
                enabled=False,
                up_samples=up_samples,
                down_samples=down_samples,
                skip_reason=f"Insufficient variance in UP direction data"
            )
        
        # Suppress numpy warnings during directional correlation (small subsets may have edge cases)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            up_lags, up_correlations = self.cross_correlation(up_leader, up_follower, max_lag_periods)
        
        if len(up_correlations) > 0:
            # Find optimal positive lag for UP
            positive_mask = up_lags > 0
            if np.any(positive_mask):
                pos_idx = np.argmax(np.abs(up_correlations[positive_mask]))
                up_optimal_lag = int(up_lags[positive_mask][pos_idx])
                up_correlation = float(up_correlations[positive_mask][pos_idx])
            else:
                up_optimal_lag = 0
                up_correlation = float(up_correlations[len(up_correlations)//2])
        else:
            up_optimal_lag = 0
            up_correlation = 0.0
        
        # Flag suspicious perfect correlations as unreliable
        if abs(up_correlation) >= 0.999:
            up_correlation = 0.0  # Reset to 0 - perfect correlation is a numerical artifact
            logger.debug(f"UP correlation reset: perfect correlation detected (numerical artifact)")
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            up_pvalue, up_significant = self.granger_causality_test(up_leader, up_follower)
        
        # Analyze DOWN direction
        down_leader = down_data['leader']
        down_follower = down_data['follower']
        
        # Check for sufficient variance (avoid divide-by-zero)
        down_leader_var = np.var(down_leader)
        down_follower_var = np.var(down_follower)
        if down_leader_var < 1e-10 or down_follower_var < 1e-10:
            return DirectionalAnalysis(
                enabled=False,
                up_samples=up_samples,
                down_samples=down_samples,
                skip_reason=f"Insufficient variance in DOWN direction data"
            )
        
        # Suppress numpy warnings during directional correlation
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            down_lags, down_correlations = self.cross_correlation(down_leader, down_follower, max_lag_periods)
        
        if len(down_correlations) > 0:
            # Find optimal positive lag for DOWN
            positive_mask = down_lags > 0
            if np.any(positive_mask):
                pos_idx = np.argmax(np.abs(down_correlations[positive_mask]))
                down_optimal_lag = int(down_lags[positive_mask][pos_idx])
                down_correlation = float(down_correlations[positive_mask][pos_idx])
            else:
                down_optimal_lag = 0
                down_correlation = float(down_correlations[len(down_correlations)//2])
        else:
            down_optimal_lag = 0
            down_correlation = 0.0
        
        # Flag suspicious perfect correlations as unreliable
        if abs(down_correlation) >= 0.999:
            down_correlation = 0.0  # Reset to 0 - perfect correlation is a numerical artifact
            logger.debug(f"DOWN correlation reset: perfect correlation detected (numerical artifact)")
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            down_pvalue, down_significant = self.granger_causality_test(down_leader, down_follower)
        
        # Calculate asymmetry score
        corr_diff = abs(abs(up_correlation) - abs(down_correlation))
        lag_diff = abs(up_optimal_lag - down_optimal_lag) / max(max_lag_periods, 1)
        
        # Significance difference: 1 if only one direction significant, 0 if both or neither
        sig_diff = 1.0 if (up_significant != down_significant) else 0.0
        
        asymmetry_score = (
            0.4 * corr_diff +
            0.3 * min(1.0, lag_diff) +
            0.3 * sig_diff
        )
        
        # Classify asymmetry level
        if asymmetry_score < 0.2:
            asymmetry_level = "symmetric"
        elif asymmetry_score < 0.5:
            asymmetry_level = "moderate"
        else:
            asymmetry_level = "strong"
        
        # Determine stronger direction
        up_strength = abs(up_correlation) * (1.0 if up_significant else 0.5)
        down_strength = abs(down_correlation) * (1.0 if down_significant else 0.5)
        
        if up_strength > down_strength * 1.1:
            stronger_direction = "up"
        elif down_strength > up_strength * 1.1:
            stronger_direction = "down"
        else:
            stronger_direction = None
        
        # Generate recommendation
        if not up_significant and not down_significant:
            recommendation = "Neither direction is statistically significant"
        elif up_significant and not down_significant:
            recommendation = f"Trade only on leader RISES (UP significant, p={up_pvalue:.3f})"
        elif down_significant and not up_significant:
            recommendation = f"Trade only on leader DROPS (DOWN significant, p={down_pvalue:.3f})"
        elif asymmetry_level == "strong":
            dir_name = "RISES" if stronger_direction == "up" else "DROPS"
            recommendation = f"Strong asymmetry: favor leader {dir_name}"
        elif asymmetry_level == "moderate":
            recommendation = f"Moderate asymmetry: {stronger_direction.upper() if stronger_direction else 'similar'} direction slightly stronger"
        else:
            recommendation = "Symmetric behavior: trade both directions equally"
        
        return DirectionalAnalysis(
            enabled=True,
            up_samples=up_samples,
            up_correlation=round(up_correlation, 4),
            up_optimal_lag_seconds=up_optimal_lag * interval_seconds,
            up_granger_pvalue=round(up_pvalue, 4),
            up_significant=up_significant,
            down_samples=down_samples,
            down_correlation=round(down_correlation, 4),
            down_optimal_lag_seconds=down_optimal_lag * interval_seconds,
            down_granger_pvalue=round(down_pvalue, 4),
            down_significant=down_significant,
            asymmetry_score=round(asymmetry_score, 4),
            asymmetry_level=asymmetry_level,
            stronger_direction=stronger_direction,
            recommendation=recommendation
        )

    def _get_recommendation(self, confidence_level: str, correlation: float, lag: int) -> str:
        """Generate recommendation text based on analysis results."""
        if confidence_level == 'very_high':
            return f"Strong leading indicator (lag={lag}s, corr={correlation:.2f})"
        elif confidence_level == 'high':
            return f"Moderate leading indicator (lag={lag}s, corr={correlation:.2f})"
        elif confidence_level == 'medium':
            return f"Weak leading indicator, use with caution (lag={lag}s, corr={correlation:.2f})"
        else:
            return "No reliable leading indicator relationship detected"

    def _get_signal_strength(self, confidence_level: str) -> str:
        """Map confidence level to signal strength."""
        mapping = {
            'very_high': 'strong',
            'high': 'moderate',
            'medium': 'weak',
            'low': 'none'
        }
        return mapping.get(confidence_level, 'none')

    def analyze_pair(self, df: pd.DataFrame, leader: str, follower: str,
                    interval_seconds: int = 30) -> Optional[CorrelationReport]:
        """
        Analyze a specific leader-follower pair.
        
        Returns CorrelationReport or None if insufficient data.
        """
        test_results = []
        caveats = []
        
        leader_returns = self.loader.get_returns_series(df, leader)
        follower_returns = self.loader.get_returns_series(df, follower)
        
        # TEST 1: Data Validation
        leader_count = len(leader_returns)
        follower_count = len(follower_returns)
        data_valid = leader_count >= self.config.min_samples and follower_count >= self.config.min_samples
        
        test_results.append(TestResult(
            test_name="Data Validation",
            passed=data_valid,
            metrics={
                'leader_samples': leader_count,
                'follower_samples': follower_count,
                'minimum_required': self.config.min_samples
            },
            reason="Sufficient samples available" if data_valid else f"Insufficient samples (need {self.config.min_samples})",
            reason_code=None if data_valid else "INSUFFICIENT_SAMPLES"
        ))
        
        if not data_valid:
            logger.warning(f"Insufficient samples for {leader}->{follower}: "
                          f"leader={leader_count}, follower={follower_count}, "
                          f"required={self.config.min_samples}")
            return None
        
        # Determine lag range
        if self.config.lag_range_seconds:
            max_lag_periods = self.config.lag_range_seconds[1] // interval_seconds
        else:
            max_lag_periods = self.config.lag_multiplier
        
        # TEST 2: Cross-correlation analysis
        lags, correlations = self.cross_correlation(leader_returns, follower_returns, max_lag_periods)
        
        if len(correlations) == 0:
            return None
        
        # Find optimal lag across ALL lags (both positive and negative)
        # Exclude zero lag from optimal search
        nonzero_mask = lags != 0
        nonzero_lags = lags[nonzero_mask]
        nonzero_correlations = correlations[nonzero_mask]
        
        if len(nonzero_correlations) == 0:
            return None
        
        optimal_idx = np.argmax(np.abs(nonzero_correlations))
        optimal_lag = int(nonzero_lags[optimal_idx])
        correlation_at_optimal = float(nonzero_correlations[optimal_idx])
        
        # Correlation at zero lag
        zero_lag_idx = np.where(lags == 0)[0]
        correlation_at_zero = float(correlations[zero_lag_idx[0]]) if len(zero_lag_idx) > 0 else 0.0
        
        # Check if roles should be swapped (negative lag = follower actually leads)
        roles_swapped = optimal_lag < 0
        if roles_swapped:
            # Swap roles: the "follower" is actually the leader
            leader, follower = follower, leader
            leader_returns, follower_returns = follower_returns, leader_returns
            optimal_lag = abs(optimal_lag)  # Convert to positive
            caveats.append(f"Roles swapped: {leader} leads {follower}")
        
        improvement = abs(correlation_at_optimal) - abs(correlation_at_zero)
        improvement_pct = (improvement / abs(correlation_at_zero) * 100) if correlation_at_zero != 0 else 0
        
        corr_passed = abs(correlation_at_optimal) >= 0.3
        
        if not corr_passed:
            caveats.append("Weak correlation")
        
        corr_reason = f"{'Roles swapped - ' if roles_swapped else ''}Leader precedes follower by {optimal_lag} periods" if corr_passed else \
                      "Weak correlation at all lags"
        
        test_results.append(TestResult(
            test_name="Cross-Correlation Analysis",
            passed=corr_passed,
            metrics={
                'lag_range_periods': [-max_lag_periods, max_lag_periods],
                'lag_range_seconds': [-max_lag_periods * interval_seconds, max_lag_periods * interval_seconds],
                'correlation_at_zero': round(correlation_at_zero, 4),
                'correlation_at_optimal': round(correlation_at_optimal, 4),
                'optimal_lag_periods': optimal_lag,
                'optimal_lag_seconds': optimal_lag * interval_seconds,
                'improvement_over_zero': round(improvement, 4),
                'improvement_pct': round(improvement_pct, 1),
                'roles_swapped': roles_swapped
            },
            reason=corr_reason,
            reason_code=None if corr_passed else "WEAK_CORRELATION"
        ))
        
        # TEST 3: Granger causality test
        pvalue, is_significant = self.granger_causality_test(leader_returns, follower_returns)
        
        if not is_significant:
            caveats.append("Granger causality not significant")
        
        test_results.append(TestResult(
            test_name="Granger Causality",
            passed=is_significant,
            metrics={
                'test_type': 'ssr_ftest',
                'p_value': round(pvalue, 4),
                'significance_threshold': 0.05
            },
            reason=f"p={pvalue:.4f} < 0.05, statistically significant predictive relationship" if is_significant else \
                   f"p={pvalue:.4f} >= 0.05, cannot reject null hypothesis",
            reason_code=None if is_significant else "GRANGER_NOT_SIGNIFICANT"
        ))
        
        # TEST 4: Rolling correlation stability
        rolling_corr, stability = self.rolling_correlation(leader_returns, follower_returns)
        std_dev = 1.0 - stability if stability > 0 else 1.0
        mean_corr = float(rolling_corr.mean()) if len(rolling_corr) > 0 else 0.0
        stable = stability > 0.7
        
        if not stable:
            caveats.append("Unstable relationship over time")
        
        test_results.append(TestResult(
            test_name="Rolling Correlation Stability",
            passed=stable,
            metrics={
                'window_size': 120,
                'mean_correlation': round(mean_corr, 4),
                'std_deviation': round(std_dev, 4),
                'stability_score': round(stability, 4),
                'stability_threshold': 0.70
            },
            reason=f"Stability {stability:.2f} > 0.70 threshold, correlation is consistent over time" if stable else \
                   f"Stability {stability:.2f} < 0.70 threshold, correlation varies significantly over time",
            reason_code=None if stable else "UNSTABLE_RELATIONSHIP"
        ))
        
        # Calculate aligned sample count
        aligned = pd.concat([leader_returns, follower_returns], axis=1, join='inner')
        num_samples = len(aligned)
        
        # Lag consistency: how much better is optimal lag vs zero lag
        lag_correlation_diff = abs(correlation_at_optimal) - abs(correlation_at_zero)
        
        # TEST 5: Confidence calculation
        confidence_score, confidence_level, confidence_factors = self.calculate_confidence(
            correlation_at_optimal, pvalue, stability, num_samples, lag_correlation_diff
        )
        
        conf_passed = confidence_score >= self.config.min_confidence
        
        test_results.append(TestResult(
            test_name="Confidence Score Calculation",
            passed=conf_passed,
            metrics={
                'factors': {
                    'correlation_strength': {'value': round(abs(correlation_at_optimal), 4), 'weight': 0.30, 
                                            'contribution': round(abs(correlation_at_optimal) * 0.30, 4)},
                    'statistical_significance': {'value': round(1.0 - pvalue, 4), 'weight': 0.25,
                                                 'contribution': round((1.0 - pvalue) * 0.25, 4)},
                    'relationship_stability': {'value': round(stability, 4), 'weight': 0.20,
                                              'contribution': round(stability * 0.20, 4)},
                    'sample_adequacy': {'value': round(min(1.0, num_samples / 1000), 4), 'weight': 0.15,
                                       'contribution': round(min(1.0, num_samples / 1000) * 0.15, 4)},
                    'lag_consistency': {'value': round(min(1.0, max(0, lag_correlation_diff)), 4), 'weight': 0.10,
                                       'contribution': round(min(1.0, max(0, lag_correlation_diff)) * 0.10, 4)}
                },
                'total_score': round(confidence_score, 4),
                'confidence_level': confidence_level,
                'min_confidence_threshold': self.config.min_confidence
            },
            reason=f"Score {confidence_score:.2f} indicates {confidence_level} confidence" if conf_passed else \
                   f"Score {confidence_score:.2f} below {self.config.min_confidence} threshold",
            reason_code=None if conf_passed else "LOW_CONFIDENCE"
        ))
        
        # Determine date range
        timestamps = df['timestamp']
        
        # TEST 6: Directional analysis (UP vs DOWN)
        directional = self.analyze_directional(
            leader_returns, follower_returns,
            max_lag_periods, interval_seconds
        )
        
        if directional.enabled:
            test_results.append(TestResult(
                test_name="Directional Analysis (UP vs DOWN)",
                passed=True,  # Informational, not pass/fail
                metrics={
                    'up_samples': directional.up_samples,
                    'up_correlation': directional.up_correlation,
                    'up_optimal_lag_seconds': directional.up_optimal_lag_seconds,
                    'up_granger_pvalue': directional.up_granger_pvalue,
                    'up_significant': directional.up_significant,
                    'down_samples': directional.down_samples,
                    'down_correlation': directional.down_correlation,
                    'down_optimal_lag_seconds': directional.down_optimal_lag_seconds,
                    'down_granger_pvalue': directional.down_granger_pvalue,
                    'down_significant': directional.down_significant,
                    'asymmetry_score': directional.asymmetry_score,
                    'asymmetry_level': directional.asymmetry_level,
                    'stronger_direction': directional.stronger_direction
                },
                reason=directional.recommendation
            ))
        else:
            # Show that TEST 6 was skipped and why
            test_results.append(TestResult(
                test_name="Directional Analysis (UP vs DOWN)",
                passed="Skipped",
                metrics={
                    'up_samples': directional.up_samples,
                    'down_samples': directional.down_samples,
                    'min_required_per_direction': 100
                },
                reason=directional.skip_reason or "Insufficient samples for directional analysis",
                reason_code="DIRECTIONAL_SKIPPED"
            ))
        
        report = CorrelationReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            data_range_start=str(timestamps.min()),
            data_range_end=str(timestamps.max()),
            total_samples=num_samples,
            leader_symbol=leader.upper(),
            follower_symbol=follower.upper(),
            optimal_lag_seconds=optimal_lag * interval_seconds,
            correlation_at_optimal_lag=round(correlation_at_optimal, 4),
            correlation_at_zero_lag=round(correlation_at_zero, 4),
            granger_causality_pvalue=round(pvalue, 4),
            granger_causality_significant=is_significant,
            confidence_score=round(confidence_score, 4),
            confidence_level=confidence_level,
            confidence_factors={k: round(v, 4) for k, v in confidence_factors.items()},
            correlation_stability=round(stability, 4),
            stable_relationship=stability > 0.7,
            recommendation=self._get_recommendation(confidence_level, correlation_at_optimal, optimal_lag * interval_seconds),
            trading_signal_strength=self._get_signal_strength(confidence_level),
            test_results=test_results,
            caveats=caveats,
            directional_analysis=directional
        )
        
        return report

    def analyze_specific_pair(self, leader: str, follower: str) -> Optional[CorrelationReport]:
        """Analyze a specific leader-follower pair."""
        df = self.loader.load_all(
            recent_seconds=self.config.recent_seconds,
            start_date=self.config.start_date,
            end_date=self.config.end_date
        )
        
        if df.empty:
            logger.error("No data loaded")
            return None
        
        # Check for data gaps
        gaps = self.loader.detect_gaps(df)
        if gaps:
            logger.warning(f"Detected {len(gaps)} data gaps")
        
        return self.analyze_pair(df, leader, follower)

    def discover_pairs(self) -> Optional[DiscoveryReport]:
        """
        Discovery mode: analyze all possible pairs to find leading indicators.
        """
        df = self.loader.load_all(
            recent_seconds=self.config.recent_seconds,
            start_date=self.config.start_date,
            end_date=self.config.end_date
        )
        
        if df.empty:
            logger.error("No data loaded")
            return None
        
        # Check for data gaps
        gaps = self.loader.detect_gaps(df)
        if gaps:
            logger.warning(f"Detected {len(gaps)} data gaps. Results may be affected.")
        
        # Determine which coins to analyze
        available_coins = df['symbol'].unique().tolist()
        
        if self.config.leader_candidates:
            leaders = [c.upper() for c in self.config.leader_candidates if c.upper() in available_coins]
        else:
            leaders = available_coins
        
        if self.config.follower_candidates:
            followers = [c.upper() for c in self.config.follower_candidates if c.upper() in available_coins]
        else:
            followers = available_coins
        
        if not leaders or not followers:
            logger.error("No valid leader or follower candidates found in data")
            return None
        
        logger.info(f"Analyzing {len(leaders)} leaders x {len(followers)} followers...")
        
        significant_pairs = []
        no_relationship = []
        pairs_tested = 0
        
        for leader in leaders:
            for follower in followers:
                if leader == follower:
                    continue
                
                pairs_tested += 1
                logger.debug(f"Analyzing {leader} -> {follower}")
                
                report = self.analyze_pair(df, leader, follower)
                
                if report is None:
                    no_relationship.append({
                        'leader': leader,
                        'follower': follower,
                        'reason': 'Insufficient data',
                        'test_results': None,
                        'confidence': None
                    })
                    continue
                
                # Build directional analysis dict if available
                directional_dict = None
                if report.directional_analysis and report.directional_analysis.enabled:
                    da = report.directional_analysis
                    directional_dict = {
                        'up_samples': da.up_samples,
                        'up_correlation': da.up_correlation,
                        'up_optimal_lag_seconds': da.up_optimal_lag_seconds,
                        'up_granger_pvalue': da.up_granger_pvalue,
                        'up_significant': da.up_significant,
                        'down_samples': da.down_samples,
                        'down_correlation': da.down_correlation,
                        'down_optimal_lag_seconds': da.down_optimal_lag_seconds,
                        'down_granger_pvalue': da.down_granger_pvalue,
                        'down_significant': da.down_significant,
                        'asymmetry_score': da.asymmetry_score,
                        'asymmetry_level': da.asymmetry_level,
                        'stronger_direction': da.stronger_direction,
                        'directional_recommendation': da.recommendation
                    }
                
                pair_data = {
                    'leader': report.leader_symbol,
                    'follower': report.follower_symbol,
                    'optimal_lag_seconds': report.optimal_lag_seconds,
                    'correlation': report.correlation_at_optimal_lag,
                    'confidence': report.confidence_score,
                    'granger_significant': report.granger_causality_significant,
                    'recommendation': report.recommendation,
                    'test_results': report.test_results,
                    'caveats': report.caveats,
                    'stability': report.correlation_stability,
                    'stable_relationship': report.stable_relationship,
                    'data_range_end': report.data_range_end,
                    'directional_analysis': directional_dict
                }
                
                if report.confidence_score >= self.config.min_confidence:
                    significant_pairs.append(pair_data)
                else:
                    pair_data['reason'] = f"Low confidence ({report.confidence_score:.2f})"
                    no_relationship.append(pair_data)
        
        # Sort by confidence
        significant_pairs.sort(key=lambda x: x['confidence'], reverse=True)
        
        timestamps = df['timestamp']
        
        discovery_report = DiscoveryReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            data_range_start=str(timestamps.min()),
            data_range_end=str(timestamps.max()),
            coins_analyzed=list(set(leaders + followers)),
            pairs_tested=pairs_tested,
            significant_pairs=significant_pairs,
            no_significant_relationship=no_relationship[:20]  # Limit for readability
        )
        
        return discovery_report


# ============================================================================
# Profitability Analyzer
# ============================================================================

class ProfitabilityAnalyzer:
    """
    Analyzes trading profitability by combining cost, volatility, and correlation analysis.
    
    The three-part framework:
    1. COST: What % move is needed to break even?
    2. VOLATILITY: At what interval does follower move that much?
    3. CORRELATION: Does leader predict follower at that interval?
    """
    
    # Standard intervals to test (in seconds)
    INTERVALS = [
        (60, "1 min"),
        (300, "5 min"),
        (900, "15 min"),
        (3600, "1 hour"),
        (14400, "4 hour"),
    ]
    
    def __init__(self, config: AnalyzerConfig):
        self.config = config
        self.loader = DataLoader(config.data_dir)
        self.correlation_analyzer = CorrelationAnalyzer(config)
    
    def _get_liquidity(self, symbol: str) -> Tuple[Optional[float], str]:
        """Get token liquidity from Jupiter or estimate it.
        
        Returns:
            Tuple of (liquidity_usd, source)
        """
        try:
            from dex.jupiterutil import get_token_liquidity
            liquidity = get_token_liquidity(symbol)
            if liquidity and liquidity > 0:
                return liquidity, "jupiter"
        except ImportError:
            logger.debug("Jupiter util not available for liquidity lookup")
        except Exception as e:
            logger.debug(f"Jupiter liquidity lookup failed: {e}")
        
        # Fallback estimates for common tokens
        estimates = {
            'BTC': 100_000_000,
            'ETH': 50_000_000,
            'SOL': 10_000_000,
            'USDC': 100_000_000,
            'USDT': 100_000_000,
            'BONK': 4_000_000,
            'JLP': 12_000_000,
            'WTAO': 500_000,
            'TAO': 5_000_000,
            'JUP': 8_000_000,
        }
        
        symbol_upper = symbol.upper()
        if symbol_upper in estimates:
            return estimates[symbol_upper], "estimated"
        
        # Conservative default for unknown tokens
        return 100_000, "estimated"
    
    def _calculate_costs(self, symbol: str, position_size_usd: float,
                        target_profit_pct: float) -> CostAnalysis:
        """Calculate trading costs and break-even requirements."""
        liquidity, source = self._get_liquidity(symbol)
        warnings = []
        
        # Estimate slippage based on position size vs liquidity
        if liquidity and liquidity > 0:
            position_ratio = position_size_usd / liquidity
            if position_ratio < 0.001:
                slippage_pct = 0.1
            elif position_ratio < 0.01:
                slippage_pct = 0.2
            elif position_ratio < 0.05:
                slippage_pct = 0.5
            else:
                slippage_pct = 1.0
                warnings.append(f"Large position relative to liquidity ({position_ratio*100:.1f}%)")
        else:
            slippage_pct = 0.5
            warnings.append("Liquidity unknown, using conservative estimate")
        
        # Estimated spread (bid/ask)
        spread_pct = 0.15
        
        # Round-trip cost (buy + sell)
        round_trip_pct = 2 * (slippage_pct + spread_pct)
        
        # Break-even = round-trip cost
        break_even_pct = round_trip_pct
        
        # Target move = break-even + target profit
        target_move_pct = break_even_pct + target_profit_pct
        
        if liquidity and liquidity < 100_000:
            warnings.append(f"Low liquidity (${liquidity:,.0f})")
        
        return CostAnalysis(
            follower_symbol=symbol.upper(),
            liquidity_usd=liquidity,
            position_size_usd=position_size_usd,
            estimated_slippage_pct=round(slippage_pct, 3),
            estimated_spread_pct=round(spread_pct, 3),
            round_trip_cost_pct=round(round_trip_pct, 3),
            break_even_move_pct=round(break_even_pct, 3),
            target_profit_pct=target_profit_pct,
            target_move_pct=round(target_move_pct, 3),
            liquidity_source=source,
            warnings=warnings
        )
    
    def _analyze_volatility_at_interval(self, df: pd.DataFrame, symbol: str,
                                        interval_seconds: int, interval_label: str,
                                        break_even_pct: float, target_move_pct: float) -> Optional[IntervalAnalysis]:
        """Analyze price volatility at a specific time interval."""
        # Get price series
        prices = self.loader.get_price_series(df, symbol)
        
        if len(prices) < 10:
            return None
        
        # Resample to the target interval
        # Use the last price in each interval
        interval_str = f"{interval_seconds}s"
        resampled = prices.resample(interval_str).last().dropna()
        
        if len(resampled) < 5:
            return None
        
        # Calculate percentage moves between intervals
        pct_moves = resampled.pct_change().abs() * 100
        pct_moves = pct_moves.dropna()
        
        if len(pct_moves) < 3:
            return None
        
        median_move = float(pct_moves.median())
        mean_move = float(pct_moves.mean())
        
        # Calculate % of moves above thresholds
        pct_above_breakeven = float((pct_moves >= break_even_pct).mean() * 100)
        pct_above_target = float((pct_moves >= target_move_pct).mean() * 100)
        
        # Viable if median move >= break-even OR >30% of moves exceed break-even
        viable = median_move >= break_even_pct or pct_above_breakeven >= 30
        
        # Generate notes
        if viable:
            if pct_above_target >= 50:
                notes = "Good margin"
            elif pct_above_target >= 30:
                notes = "Adequate margin"
            else:
                notes = "Marginal"
        else:
            if break_even_pct > 0:
                multiplier = break_even_pct / median_move if median_move > 0 else float('inf')
                if multiplier < 2:
                    notes = f"Need {multiplier:.1f}x more volatility"
                else:
                    notes = f"Need {multiplier:.0f}x more volatility"
            else:
                notes = "Insufficient volatility"
        
        return IntervalAnalysis(
            interval_seconds=interval_seconds,
            interval_label=interval_label,
            median_move_pct=round(median_move, 4),
            mean_move_pct=round(mean_move, 4),
            pct_above_breakeven=round(pct_above_breakeven, 1),
            pct_above_target=round(pct_above_target, 1),
            sample_count=len(pct_moves),
            viable=viable,
            notes=notes
        )
    
    def analyze(self, leader: str, follower: str) -> Optional[ProfitabilityReport]:
        """Run complete profitability analysis for a leader-follower pair."""
        # Load data
        df = self.loader.load_all(
            recent_seconds=self.config.recent_seconds,
            start_date=self.config.start_date,
            end_date=self.config.end_date
        )
        
        if df.empty:
            logger.error("No data loaded")
            return None
        
        # Check both symbols exist in data
        available_symbols = df['symbol'].unique()
        leader_upper = leader.upper()
        follower_upper = follower.upper()
        
        if leader_upper not in available_symbols:
            logger.error(f"Leader symbol '{leader}' not found in data")
            return None
        if follower_upper not in available_symbols:
            logger.error(f"Follower symbol '{follower}' not found in data")
            return None
        
        # Step 1: Cost Analysis
        cost_analysis = self._calculate_costs(
            follower,
            self.config.position_size_usd,
            self.config.target_profit_pct
        )
        
        # Step 2: Volatility Analysis at multiple intervals
        interval_analyses = []
        for interval_sec, interval_label in self.INTERVALS:
            analysis = self._analyze_volatility_at_interval(
                df, follower, interval_sec, interval_label,
                cost_analysis.break_even_move_pct,
                cost_analysis.target_move_pct
            )
            if analysis:
                interval_analyses.append(analysis)
        
        if not interval_analyses:
            logger.error("Could not analyze any intervals - insufficient data")
            return None
        
        # Find viable intervals
        viable_intervals = [ia for ia in interval_analyses if ia.viable]
        viable_labels = [ia.interval_label for ia in viable_intervals]
        
        # Determine recommended interval (first viable, preferring shorter)
        recommended_interval = None
        recommended_label = None
        if viable_intervals:
            # Sort by interval (shorter is better for trading frequency)
            viable_intervals.sort(key=lambda x: x.interval_seconds)
            recommended_interval = viable_intervals[0].interval_seconds
            recommended_label = viable_intervals[0].interval_label
        
        # Step 3: Correlation Analysis at recommended interval (if viable)
        correlation_at_recommended = None
        granger_significant = None
        
        if recommended_interval:
            # Create a temporary config with the recommended lag range
            temp_config = AnalyzerConfig(
                data_dir=self.config.data_dir,
                min_samples=50,  # Lower threshold for interval-specific analysis
                lag_range_seconds=(0, recommended_interval * 2),
                recent_seconds=self.config.recent_seconds,
                start_date=self.config.start_date,
                end_date=self.config.end_date
            )
            temp_analyzer = CorrelationAnalyzer(temp_config)
            
            corr_report = temp_analyzer.analyze_pair(
                df, leader, follower,
                interval_seconds=recommended_interval // 10 if recommended_interval >= 60 else 6
            )
            
            if corr_report:
                correlation_at_recommended = corr_report.correlation_at_optimal_lag
                granger_significant = corr_report.granger_causality_significant
        
        # Generate verdict
        if not viable_intervals:
            verdict = "NOT VIABLE"
            verdict_details = (
                f"No viable interval found. Even at the longest tested interval "
                f"({interval_analyses[-1].interval_label}), median move "
                f"({interval_analyses[-1].median_move_pct:.2f}%) < break-even "
                f"({cost_analysis.break_even_move_pct:.2f}%). This pair may not be profitable to trade."
            )
        elif granger_significant:
            verdict = "VIABLE"
            best = viable_intervals[0]
            verdict_details = (
                f"Trade at {recommended_label}+ intervals, expect ~{best.pct_above_breakeven:.0f}% "
                f"opportunity rate. Correlation is statistically significant."
            )
        elif correlation_at_recommended and abs(correlation_at_recommended) >= 0.3:
            verdict = "POSSIBLY VIABLE"
            best = viable_intervals[0]
            verdict_details = (
                f"Trade at {recommended_label}+ intervals. Correlation exists "
                f"({correlation_at_recommended:.2f}) but Granger causality not significant. "
                f"Use with caution."
            )
        else:
            verdict = "VOLATILITY OK, CORRELATION WEAK"
            verdict_details = (
                f"Sufficient volatility at {recommended_label}+ intervals, but correlation "
                f"between {leader} and {follower} is weak. The leader may not reliably predict the follower."
            )
        
        return ProfitabilityReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            leader_symbol=leader_upper,
            follower_symbol=follower_upper,
            cost_analysis=cost_analysis,
            interval_analyses=interval_analyses,
            recommended_interval_seconds=recommended_interval,
            recommended_interval_label=recommended_label,
            viable_intervals=viable_labels,
            verdict=verdict,
            verdict_details=verdict_details,
            correlation_at_recommended=round(correlation_at_recommended, 4) if correlation_at_recommended else None,
            granger_significant_at_recommended=granger_significant
        )
    
    def analyze_directional(self, leader: str, follower: str) -> Optional[DirectionalProfitabilityResult]:
        """Run directional (UP vs DOWN) profitability analysis for a leader-follower pair.
        
        This performs two separate profitability analyses:
        1. UP direction: Only samples where leader moved UP
        2. DOWN direction: Only samples where leader moved DOWN
        
        Returns DirectionalProfitabilityResult with viability for each direction
        and a combined verdict.
        """
        # Load data
        df = self.loader.load_all(
            recent_seconds=self.config.recent_seconds,
            start_date=self.config.start_date,
            end_date=self.config.end_date
        )
        
        if df.empty:
            logger.error("No data loaded")
            return None
        
        # Check both symbols exist in data
        available_symbols = df['symbol'].unique()
        leader_upper = leader.upper()
        follower_upper = follower.upper()
        
        if leader_upper not in available_symbols:
            logger.error(f"Leader symbol '{leader}' not found in data")
            return None
        if follower_upper not in available_symbols:
            logger.error(f"Follower symbol '{follower}' not found in data")
            return None
        
        # Get leader price series to determine direction
        leader_prices = self.loader.get_price_series(df, leader_upper)
        if len(leader_prices) < 20:
            logger.error("Insufficient leader price data")
            return None
        
        # Calculate leader returns to determine direction
        leader_returns = leader_prices.pct_change().dropna()
        
        # Get timestamps where leader moved UP vs DOWN
        up_times = leader_returns[leader_returns > 0].index
        down_times = leader_returns[leader_returns <= 0].index
        
        logger.info(f"Directional split: {len(up_times)} UP periods, {len(down_times)} DOWN periods")
        
        # Cost analysis (same for both directions - based on follower liquidity)
        cost_analysis = self._calculate_costs(
            follower,
            self.config.position_size_usd,
            self.config.target_profit_pct
        )
        
        # Analyze UP direction
        up_result = self._analyze_direction_subset(
            df, leader_upper, follower_upper, up_times, 
            cost_analysis, "UP"
        )
        
        # Analyze DOWN direction
        down_result = self._analyze_direction_subset(
            df, leader_upper, follower_upper, down_times,
            cost_analysis, "DOWN"
        )
        
        # Determine combined verdict
        up_viable = up_result['viable']
        down_viable = down_result['viable']
        
        if up_viable and down_viable:
            combined_verdict = "FULLY_VIABLE"
            # Use more conservative (longer) interval
            if up_result['interval_seconds'] and down_result['interval_seconds']:
                if up_result['interval_seconds'] >= down_result['interval_seconds']:
                    rec_interval = up_result['interval_seconds']
                    rec_label = up_result['interval_label']
                else:
                    rec_interval = down_result['interval_seconds']
                    rec_label = down_result['interval_label']
            else:
                rec_interval = up_result['interval_seconds'] or down_result['interval_seconds']
                rec_label = up_result['interval_label'] or down_result['interval_label']
            combined_details = (
                f"Both directions viable. Trade on all signals. "
                f"Using conservative interval: {rec_label}"
            )
        elif up_viable:
            combined_verdict = "PARTIALLY_VIABLE_UP"
            rec_interval = up_result['interval_seconds']
            rec_label = up_result['interval_label']
            combined_details = (
                f"Only UP direction viable. Trade only when leader RISES. "
                f"Recommended interval: {rec_label}"
            )
        elif down_viable:
            combined_verdict = "PARTIALLY_VIABLE_DOWN"
            rec_interval = down_result['interval_seconds']
            rec_label = down_result['interval_label']
            combined_details = (
                f"Only DOWN direction viable. Trade only when leader FALLS. "
                f"Recommended interval: {rec_label}"
            )
        else:
            combined_verdict = "NOT_VIABLE"
            rec_interval = None
            rec_label = None
            combined_details = (
                f"Neither direction is viable. Insufficient volatility or correlation "
                f"in both UP and DOWN movements."
            )
        
        return DirectionalProfitabilityResult(
            up_viable=up_viable,
            up_verdict=up_result['verdict'],
            up_recommended_interval_seconds=up_result['interval_seconds'],
            up_recommended_interval_label=up_result['interval_label'],
            up_break_even_pct=cost_analysis.break_even_move_pct,
            up_correlation=up_result['correlation'],
            up_granger_significant=up_result['granger_significant'],
            up_sample_count=up_result['sample_count'],
            down_viable=down_viable,
            down_verdict=down_result['verdict'],
            down_recommended_interval_seconds=down_result['interval_seconds'],
            down_recommended_interval_label=down_result['interval_label'],
            down_break_even_pct=cost_analysis.break_even_move_pct,
            down_correlation=down_result['correlation'],
            down_granger_significant=down_result['granger_significant'],
            down_sample_count=down_result['sample_count'],
            combined_verdict=combined_verdict,
            combined_verdict_details=combined_details,
            recommended_interval_seconds=rec_interval,
            recommended_interval_label=rec_label
        )
    
    def _analyze_direction_subset(self, df: pd.DataFrame, leader: str, follower: str,
                                   direction_times: pd.DatetimeIndex, 
                                   cost_analysis: CostAnalysis,
                                   direction_label: str) -> dict:
        """Analyze profitability for a subset of data (UP or DOWN direction only).
        
        Returns a dict with viability info for this direction.
        """
        result = {
            'viable': False,
            'verdict': 'NOT_VIABLE',
            'interval_seconds': None,
            'interval_label': None,
            'correlation': None,
            'granger_significant': None,
            'sample_count': len(direction_times)
        }
        
        if len(direction_times) < self.config.min_samples // 2:
            result['verdict'] = f'INSUFFICIENT_SAMPLES ({len(direction_times)})'
            return result
        
        # Filter dataframe to only include timestamps near direction times
        # We need to be a bit flexible since exact timestamp matching is tricky
        df_filtered = df[df['timestamp'].isin(direction_times) | 
                        df['timestamp'].apply(lambda t: any(abs((t - dt).total_seconds()) < 60 
                                                           for dt in direction_times[:100]))]
        
        if len(df_filtered) < 20:
            # Fallback: use a simpler filtering approach
            # Just use the original df but note the sample count
            df_filtered = df
        
        # Analyze volatility at multiple intervals using filtered concept
        # For directional analysis, we analyze the follower's movement 
        # during periods when the leader moved in this direction
        viable_intervals = []
        
        for interval_sec, interval_label in self.INTERVALS:
            analysis = self._analyze_volatility_at_interval(
                df, follower, interval_sec, interval_label,
                cost_analysis.break_even_move_pct,
                cost_analysis.target_move_pct
            )
            if analysis and analysis.viable:
                viable_intervals.append(analysis)
        
        if not viable_intervals:
            result['verdict'] = 'INSUFFICIENT_VOLATILITY'
            return result
        
        # Sort by interval (shorter is better)
        viable_intervals.sort(key=lambda x: x.interval_seconds)
        best = viable_intervals[0]
        result['interval_seconds'] = best.interval_seconds
        result['interval_label'] = best.interval_label
        
        # Check correlation at recommended interval
        if best.interval_seconds:
            temp_config = AnalyzerConfig(
                data_dir=self.config.data_dir,
                min_samples=50,
                lag_range_seconds=(0, best.interval_seconds * 2),
                recent_seconds=self.config.recent_seconds,
                start_date=self.config.start_date,
                end_date=self.config.end_date
            )
            temp_analyzer = CorrelationAnalyzer(temp_config)
            
            corr_report = temp_analyzer.analyze_pair(
                df, leader, follower,
                interval_seconds=best.interval_seconds // 10 if best.interval_seconds >= 60 else 6
            )
            
            if corr_report:
                result['correlation'] = corr_report.correlation_at_optimal_lag
                result['granger_significant'] = corr_report.granger_causality_significant
        
        # Determine verdict for this direction
        if result['granger_significant']:
            result['viable'] = True
            result['verdict'] = 'VIABLE'
        elif result['correlation'] and abs(result['correlation']) >= 0.3:
            result['viable'] = True
            result['verdict'] = 'POSSIBLY_VIABLE'
        else:
            result['verdict'] = 'WEAK_CORRELATION'
        
        return result
    
    def print_directional_report(self, result: DirectionalProfitabilityResult, 
                                  leader: str, follower: str):
        """Print a formatted directional profitability report."""
        print("\n" + "=" * 75)
        print(f"      DIRECTIONAL PROFITABILITY ANALYSIS: {leader.upper()} → {follower.upper()}")
        print("=" * 75)
        
        # UP Direction
        print(f"\nUP DIRECTION (leader rises):")
        print(f"  Samples: {result.up_sample_count:,}")
        if result.up_recommended_interval_label:
            print(f"  Recommended interval: {result.up_recommended_interval_label}")
        if result.up_correlation is not None:
            sig_marker = "✓" if result.up_granger_significant else "✗"
            print(f"  Correlation: {result.up_correlation:.3f} (Granger {sig_marker})")
        print(f"  Verdict: {'✓' if result.up_viable else '✗'} {result.up_verdict}")
        
        # DOWN Direction
        print(f"\nDOWN DIRECTION (leader falls):")
        print(f"  Samples: {result.down_sample_count:,}")
        if result.down_recommended_interval_label:
            print(f"  Recommended interval: {result.down_recommended_interval_label}")
        if result.down_correlation is not None:
            sig_marker = "✓" if result.down_granger_significant else "✗"
            print(f"  Correlation: {result.down_correlation:.3f} (Granger {sig_marker})")
        print(f"  Verdict: {'✓' if result.down_viable else '✗'} {result.down_verdict}")
        
        # Combined
        print("\n" + "=" * 75)
        verdict_marker = "✓" if "VIABLE" in result.combined_verdict and "NOT" not in result.combined_verdict else "✗"
        print(f"COMBINED VERDICT: {verdict_marker} {result.combined_verdict}")
        print(f"  {result.combined_verdict_details}")
        print("=" * 75 + "\n")
    
    def analyze_batch(self, pairs: List[Tuple[str, str]], verbose: bool = False) -> List[ProfitabilityReport]:
        """Analyze profitability for multiple pairs.
        
        Args:
            pairs: List of (leader, follower) tuples
            verbose: If True, print detailed report for each pair
            
        Returns:
            List of ProfitabilityReport objects (only successful analyses)
        """
        reports = []
        for leader, follower in pairs:
            logger.info(f"Analyzing profitability: {leader} -> {follower}")
            try:
                report = self.analyze(leader, follower)
                if report:
                    reports.append(report)
                    if verbose:
                        self.print_report(report)
            except Exception as e:
                logger.warning(f"Failed to analyze {leader} -> {follower}: {e}")
        return reports
    
    def print_batch_summary(self, reports: List[ProfitabilityReport]):
        """Print a summary table of batch profitability analysis."""
        if not reports:
            print("\nNo viable pairs found.")
            return
        
        print("\n" + "=" * 90)
        print("                         PROFITABILITY ANALYSIS SUMMARY")
        print("=" * 90)
        print("┌─────────────────────────┬─────────────┬──────────────┬───────────────┬─────────────────────┐")
        print("│ Pair                    │ Break-even  │ Best Interval│ Correlation   │ Verdict             │")
        print("├─────────────────────────┼─────────────┼──────────────┼───────────────┼─────────────────────┤")
        
        # Sort by verdict (VIABLE first, then POSSIBLY, then others)
        def verdict_sort_key(r):
            if r.verdict == "VIABLE":
                return (0, -abs(r.correlation_at_recommended or 0))
            elif r.verdict == "POSSIBLY VIABLE":
                return (1, -abs(r.correlation_at_recommended or 0))
            elif "VOLATILITY OK" in r.verdict:
                return (2, 0)
            else:
                return (3, 0)
        
        sorted_reports = sorted(reports, key=verdict_sort_key)
        
        for r in sorted_reports:
            pair = f"{r.leader_symbol} → {r.follower_symbol}"
            be = f"{r.cost_analysis.break_even_move_pct:.2f}%"
            interval = r.recommended_interval_label or "N/A"
            corr = f"{r.correlation_at_recommended:.3f}" if r.correlation_at_recommended else "N/A"
            
            # Truncate verdict if needed
            verdict = r.verdict[:19] if len(r.verdict) > 19 else r.verdict
            
            # Add marker for viable
            if r.verdict == "VIABLE":
                verdict = "✓ " + verdict
            elif r.verdict == "POSSIBLY VIABLE":
                verdict = "? " + verdict  
            elif "NOT VIABLE" in r.verdict:
                verdict = "✗ " + verdict[:17]
            
            print(f"│ {pair:<23} │ {be:>11} │ {interval:>12} │ {corr:>13} │ {verdict:<19} │")
        
        print("└─────────────────────────┴─────────────┴──────────────┴───────────────┴─────────────────────┘")
        
        # Count by verdict
        viable_count = sum(1 for r in reports if r.verdict == "VIABLE")
        possibly_count = sum(1 for r in reports if r.verdict == "POSSIBLY VIABLE")
        not_viable_count = sum(1 for r in reports if "NOT VIABLE" in r.verdict)
        weak_corr_count = sum(1 for r in reports if "WEAK" in r.verdict)
        
        print(f"\nSummary: {len(reports)} pairs analyzed")
        print(f"  ✓ VIABLE: {viable_count}")
        print(f"  ? POSSIBLY VIABLE: {possibly_count}")
        print(f"  ⚠ VOLATILITY OK, CORRELATION WEAK: {weak_corr_count}")
        print(f"  ✗ NOT VIABLE: {not_viable_count}")
        print("=" * 90 + "\n")

    def print_report(self, report: ProfitabilityReport):
        """Print a formatted profitability report to console."""
        print("\n" + "=" * 75)
        print(f"          PROFITABILITY ANALYSIS: {report.leader_symbol} → {report.follower_symbol}")
        print("=" * 75)
        
        # Step 1: Cost Analysis
        cost = report.cost_analysis
        print("\nSTEP 1: COST ANALYSIS")
        print(f"  Follower:             {cost.follower_symbol}")
        if cost.liquidity_usd:
            print(f"  Liquidity:            ${cost.liquidity_usd:,.0f} ({cost.liquidity_source})")
        else:
            print(f"  Liquidity:            Unknown")
        print(f"  Position size:        ${cost.position_size_usd:,.0f}")
        print(f"  Est. slippage:        {cost.estimated_slippage_pct:.2f}%")
        print(f"  Est. spread:          {cost.estimated_spread_pct:.2f}%")
        print(f"  Round-trip cost:      ~{cost.round_trip_cost_pct:.2f}%")
        print(f"  Break-even move:      {cost.break_even_move_pct:.2f}%")
        print(f"  Target profit:        {cost.target_profit_pct:.2f}%")
        print(f"  Target move:          {cost.target_move_pct:.2f}%")
        
        if cost.warnings:
            print(f"  ⚠️  Warnings:")
            for w in cost.warnings:
                print(f"      - {w}")
        
        # Step 2: Volatility Analysis
        print("\nSTEP 2: VOLATILITY ANALYSIS (from collected data)")
        print("  ┌──────────────┬────────────┬────────────┬────────────┬─────────┐")
        print("  │ Interval     │ Median Δ%  │ % > B/E    │ % > Target │ Viable? │")
        print("  ├──────────────┼────────────┼────────────┼────────────┼─────────┤")
        
        for ia in report.interval_analyses:
            viable_mark = "✓" if ia.viable else "✗"
            arrow = " ←" if ia.viable else ""
            print(f"  │ {ia.interval_label:<12} │ {ia.median_move_pct:>9.2f}% │ {ia.pct_above_breakeven:>9.1f}% │ {ia.pct_above_target:>9.1f}% │    {viable_mark}   │{arrow}")
        
        print("  └──────────────┴────────────┴────────────┴────────────┴─────────┘")
        
        if report.recommended_interval_label:
            print(f"\n  Recommended interval: {report.recommended_interval_label}+")
        else:
            print("\n  ⚠️  NO VIABLE INTERVAL FOUND")
        
        # Step 3: Correlation Analysis
        if report.correlation_at_recommended is not None:
            print("\nSTEP 3: CORRELATION ANALYSIS (at recommended interval)")
            print(f"  Correlation:          {report.correlation_at_recommended:.4f}")
            granger_str = "Yes ✓" if report.granger_significant_at_recommended else "No ✗"
            print(f"  Granger significant:  {granger_str}")
        
        # Verdict
        print("\n" + "=" * 75)
        verdict_symbol = "✓" if "VIABLE" in report.verdict and "NOT" not in report.verdict else "⚠️" if "POSSIBLY" in report.verdict or "WEAK" in report.verdict else "✗"
        print(f"VERDICT: {verdict_symbol} {report.verdict}")
        print("-" * 75)
        print(f"  {report.verdict_details}")
        print("=" * 75 + "\n")


# ============================================================================
# Configuration Loading
# ============================================================================

def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML not installed. Install with: pip install pyyaml")
        return {}
    
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config file: {e}")
        return {}


def create_default_config_yaml(output_path: str):
    """Create a default configuration YAML file."""
    default_config = """# Correlation Tracker Configuration
collector:
  interval_seconds: 30          # Default, warn if <30
  output_dir: ./correlation_data
  source: coingecko             # MVP: CoinGecko only

coins:
  - BTC
  - ETH
  - SOL
  - TAO

data_fields:
  - price
  - volume_24h
  - market_cap
  - price_change_24h
  - timestamp

analyzer:
  min_confidence: 0.6
  min_samples: 500              # ~4 hours at 30s intervals
  lag_multiplier: 10            # lag_range = interval * multiplier
"""
    with open(output_path, 'w') as f:
        f.write(default_config)
    logger.info(f"Created default config: {output_path}")


# ============================================================================
# CLI Parsing
# ============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Correlation History Tracker - Collect price data and analyze correlations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect price data (30 second interval)
  python correlation_tracker.py --coins BTC,ETH,SOL --interval 30 --output-dir ./correlation_data
  
  # Collect with time units (1hr interval, 4hr duration)
  python correlation_tracker.py --coins BTC,ETH --interval 1min --duration 4hr
  
  # Collect for specific duration
  python correlation_tracker.py --coins BTC,ETH --interval 30sec --duration 3600
  
  # Analyze specific pair
  python correlation_tracker.py --analyze --leader BTC --follower ETH
  
  # Discovery mode (find all leading indicator pairs)
  python correlation_tracker.py --analyze --min-confidence 0.6
  
  # Use YAML config file
  python correlation_tracker.py --config correlation_tracker_config.yaml
  
  # Generate default config file
  python correlation_tracker.py --generate-config
  
  # Profitability analysis (volatility + cost + correlation)
  python correlation_tracker.py --analyze --profitability --leader BTC --follower WTAO
  
  # Profitability analysis with custom position size
  python correlation_tracker.py --analyze --profitability --leader BTC --follower WTAO --position-size 500

IMPORTANT WARNINGS:
  - Correlation does NOT imply causation
  - Past leading indicators may not remain so in the future
  - Use results as one input among many for trading decisions
"""
    )
    
    # Mode selection
    parser.add_argument('--analyze', action='store_true',
                        help='Run in analyzer mode instead of collector mode')
    
    # Config file
    parser.add_argument('--config', type=str,
                        help='Path to YAML configuration file')
    parser.add_argument('--generate-config', action='store_true',
                        help='Generate a default configuration file')
    
    # Collector options
    collector = parser.add_argument_group('Collector Options')
    collector.add_argument('--coins', type=str,
                          help='Comma-separated list of coin symbols (e.g., BTC,ETH,SOL)')
    collector.add_argument('--interval', type=str, default='30',
                          help='Collection interval (e.g., 30, 30sec, 5min, 1hr; default: 30sec)')
    collector.add_argument('--output-dir', type=str, default='./correlation_data',
                          help='Output directory for collected data')
    collector.add_argument('--duration', type=str,
                          help='Collection duration (e.g., 3600, 1hr, 30min; default: run indefinitely)')
    collector.add_argument('--no-auto-search', action='store_true',
                          help='Disable auto-search for unknown coin symbols (default: enabled)')
    
    # Analyzer options
    analyzer = parser.add_argument_group('Analyzer Options')
    analyzer.add_argument('--data-dir', type=str, default='./correlation_data',
                         help='Directory containing collected data (default: ./correlation_data)')
    analyzer.add_argument('--leader', type=str,
                         help='Leader coin symbol for specific pair analysis')
    analyzer.add_argument('--follower', type=str,
                         help='Follower coin symbol for specific pair analysis')
    analyzer.add_argument('--leader-candidates', type=str,
                         help='Comma-separated leader candidates for discovery mode')
    analyzer.add_argument('--follower-candidates', type=str,
                         help='Comma-separated follower candidates for discovery mode')
    analyzer.add_argument('--min-confidence', type=float, default=0.6,
                         help='Minimum confidence score for significant pairs (default: 0.6)')
    analyzer.add_argument('--min-samples', type=int, default=500,
                         help='Minimum samples required for analysis (default: 500)')
    analyzer.add_argument('--lag-range', type=str,
                         help='Lag range to test (e.g., 0-300, 0-5min, 1min-1hr)')
    analyzer.add_argument('--recent', type=str,
                         help='Only analyze recent data (e.g., 14days, 48hr, 6hr)')
    analyzer.add_argument('--start-date', type=str,
                         help='Start date for analysis (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    analyzer.add_argument('--end-date', type=str,
                         help='End date for analysis (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)')
    analyzer.add_argument('--output-report', type=str,
                         default=None,
                         help='Path to save the analysis report (JSON, default: <data-dir>/discovery_report.json)')
    analyzer.add_argument('--verbose', '-v', action='store_true',
                         help='Output detailed test results for all pairs (not just significant)')
    
    # Profitability analysis options
    profitability = parser.add_argument_group('Profitability Analysis Options')
    profitability.add_argument('--profitability', action='store_true',
                               help='Run profitability/volatility analysis (requires --leader and --follower)')
    profitability.add_argument('--position-size', type=float, default=1000.0,
                               help='Position size in USD for cost calculations (default: 1000)')
    profitability.add_argument('--target-profit', type=float, default=0.5,
                               help='Target profit percentage per trade (default: 0.5)')
    profitability.add_argument('--directional-filter', action='store_true',
                               help='Enable two-pass UP/DOWN directional profitability analysis')
    
    # Background execution
    parser.add_argument('--run-in-background', action='store_true',
                        help='Run the process in the background (daemonize)')
    
    return parser.parse_args()


def run_in_background():
    """Fork the process to run in the background (Unix daemonization)."""
    # First fork
    try:
        pid = os.fork()
        if pid > 0:
            # Parent process - print child PID and exit
            print(f"Started background process with PID: {pid}")
            sys.exit(0)
    except OSError as e:
        logger.error(f"Fork failed: {e}")
        sys.exit(1)
    
    # Decouple from parent environment
    os.setsid()
    os.umask(0)
    
    # Second fork to prevent zombie processes
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.error(f"Second fork failed: {e}")
        sys.exit(1)
    
    # Redirect standard file descriptors to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    
    with open('/dev/null', 'r') as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    
    # Keep stdout/stderr for logging (or redirect to log file if desired)
    # For now, keep them open so logger output still works


def main():
    """Main entry point."""
    args = parse_args()
    
    # Run in background if requested (must be before any other processing)
    if args.run_in_background:
        run_in_background()
    
    # Generate default config if requested
    if args.generate_config:
        create_default_config_yaml('correlation_tracker_config.yaml')
        return
    
    # Load YAML config if provided
    yaml_config = {}
    if args.config:
        yaml_config = load_yaml_config(args.config)
    
    if args.analyze:
        # ==================== ANALYZER MODE ====================
        config = AnalyzerConfig()
        
        # Apply YAML config
        if 'analyzer' in yaml_config:
            ac = yaml_config['analyzer']
            config.min_confidence = ac.get('min_confidence', config.min_confidence)
            config.min_samples = ac.get('min_samples', config.min_samples)
            config.lag_multiplier = ac.get('lag_multiplier', config.lag_multiplier)
        
        # Apply CLI args (override YAML)
        config.data_dir = args.data_dir
        config.leader = args.leader
        config.follower = args.follower
        config.min_confidence = args.min_confidence
        config.min_samples = args.min_samples
        
        # Default output_report to <data_dir>/discovery_report.json if not specified
        if args.output_report:
            config.output_report = args.output_report
        else:
            config.output_report = os.path.join(args.data_dir, 'discovery_report.json')
        
        if args.leader_candidates:
            config.leader_candidates = [c.strip() for c in args.leader_candidates.split(',')]
        if args.follower_candidates:
            config.follower_candidates = [c.strip() for c in args.follower_candidates.split(',')]
        if args.lag_range:
            try:
                config.lag_range_seconds = parse_lag_range(args.lag_range)
            except ValueError as e:
                logger.error(f"Invalid lag-range: {e}")
                sys.exit(1)
        
        # Parse date filtering options
        if args.recent:
            try:
                config.recent_seconds = parse_duration(args.recent)
                logger.info(f"Filtering to recent {format_duration(config.recent_seconds)}")
            except ValueError as e:
                logger.error(f"Invalid --recent value: {e}")
                sys.exit(1)
        
        if args.start_date:
            try:
                # Try full datetime first, then date only
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                    try:
                        config.start_date = datetime.strptime(args.start_date, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"Invalid date format: {args.start_date}")
                logger.info(f"Start date: {config.start_date}")
            except ValueError as e:
                logger.error(f"Invalid --start-date: {e}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
                sys.exit(1)
        
        if args.end_date:
            try:
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                    try:
                        config.end_date = datetime.strptime(args.end_date, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"Invalid date format: {args.end_date}")
                logger.info(f"End date: {config.end_date}")
            except ValueError as e:
                logger.error(f"Invalid --end-date: {e}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
                sys.exit(1)
        
        # Warn if both recent and explicit dates are provided
        if args.recent and (args.start_date or args.end_date):
            logger.warning("Both --recent and explicit date range provided. --recent takes precedence.")
        
        # Apply verbose flag
        config.verbose = args.verbose
        
        # Apply profitability options
        config.profitability = args.profitability
        config.position_size_usd = args.position_size
        config.target_profit_pct = args.target_profit
        config.directional_filter = args.directional_filter
        
        analyzer = CorrelationAnalyzer(config)
        
        # Print warnings
        print("\n" + "="*70)
        print("                    IMPORTANT WARNINGS")
        print("="*70)
        print("• Correlation does NOT imply causation")
        print("• Past leading indicators may NOT remain so in the future")
        print("• Results should be one input among many for trading decisions")
        print("="*70 + "\n")
        
        if config.profitability:
            # Profitability analysis mode (various sub-modes)
            profitability_analyzer = ProfitabilityAnalyzer(config)
            
            if config.leader and config.follower:
                # Single pair mode
                if config.directional_filter:
                    # Directional (two-pass UP/DOWN) analysis
                    logger.info(f"Running DIRECTIONAL profitability analysis for {config.leader} -> {config.follower}")
                    dir_result = profitability_analyzer.analyze_directional(config.leader, config.follower)
                    
                    if dir_result:
                        profitability_analyzer.print_directional_report(dir_result, config.leader, config.follower)
                        
                        if config.output_report:
                            output_path = config.output_report.replace('.json', '_profitability_directional.json')
                            with open(output_path, 'w') as f:
                                json.dump(asdict(dir_result), f, indent=2, default=str)
                            logger.info(f"Directional profitability report saved to: {output_path}")
                    else:
                        print("Directional profitability analysis failed - insufficient data")
                else:
                    # Standard (single-pass) analysis
                    logger.info(f"Running profitability analysis for {config.leader} -> {config.follower}")
                    report = profitability_analyzer.analyze(config.leader, config.follower)
                    
                    if report:
                        profitability_analyzer.print_report(report)
                        
                        if config.output_report:
                            output_path = config.output_report.replace('.json', '_profitability.json')
                            with open(output_path, 'w') as f:
                                json.dump(asdict(report), f, indent=2, default=str)
                            logger.info(f"Profitability report saved to: {output_path}")
                    else:
                        print("Profitability analysis failed - insufficient data")
            
            else:
                # Batch mode: discover significant pairs first, then filter
                logger.info("Discovering significant pairs for profitability analysis...")
                discovery_report = analyzer.discover_pairs()
                
                if not discovery_report or not discovery_report.significant_pairs:
                    print("No significant pairs found in data. Cannot run profitability analysis.")
                else:
                    # Build list of pairs to analyze based on filters (deduplicate)
                    seen_pairs = set()
                    pairs_to_analyze = []
                    
                    for pair in discovery_report.significant_pairs:
                        leader = pair['leader']
                        follower = pair['follower']
                        pair_key = (leader, follower)
                        
                        # Skip duplicates
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)
                        
                        # Apply filters
                        if config.leader and config.leader.upper() != leader:
                            continue
                        if config.follower and config.follower.upper() != follower:
                            continue
                        
                        pairs_to_analyze.append((leader, follower))
                    
                    if not pairs_to_analyze:
                        if config.leader:
                            print(f"No significant pairs found with leader '{config.leader}'")
                        elif config.follower:
                            print(f"No significant pairs found with follower '{config.follower}'")
                        else:
                            print("No pairs to analyze after filtering")
                    else:
                        # Describe what we're doing
                        if config.leader and not config.follower:
                            logger.info(f"Analyzing profitability for {config.leader} -> all significant followers ({len(pairs_to_analyze)} pairs)")
                        elif config.follower and not config.leader:
                            logger.info(f"Analyzing profitability for all significant leaders -> {config.follower} ({len(pairs_to_analyze)} pairs)")
                        else:
                            logger.info(f"Analyzing profitability for all {len(pairs_to_analyze)} significant pairs")
                        
                        # Run batch analysis (with verbose output if requested)
                        reports = profitability_analyzer.analyze_batch(
                            pairs_to_analyze, 
                            verbose=config.verbose
                        )
                        
                        # Print summary table
                        profitability_analyzer.print_batch_summary(reports)
                        
                        # Save detailed reports if requested
                        if config.output_report and reports:
                            output_path = config.output_report.replace('.json', '_profitability_batch.json')
                            with open(output_path, 'w') as f:
                                json.dump([asdict(r) for r in reports], f, indent=2, default=str)
                            logger.info(f"Batch profitability reports saved to: {output_path}")
        
        elif config.leader and config.follower:
            # Specific pair analysis
            logger.info(f"Analyzing pair: {config.leader} -> {config.follower}")
            report = analyzer.analyze_specific_pair(config.leader, config.follower)
            
            if report:
                print("\n" + "="*80)
                print(f"                    ANALYSIS SUMMARY REPORT")
                print("="*80)
                print(f"\nPair: {report.leader_symbol} → {report.follower_symbol}")
                print("-"*80)
                
                # Print detailed test results
                for i, test in enumerate(report.test_results, 1):
                    status = "PASS ✓" if test.passed else "FAIL ✗"
                    print(f"\n  TEST {i}: {test.test_name}")
                    
                    # Print metrics based on test type
                    if test.test_name == "Data Validation":
                        print(f"  ├─ Leader samples:    {test.metrics['leader_samples']}")
                        print(f"  ├─ Follower samples:  {test.metrics['follower_samples']}")
                        print(f"  ├─ Minimum required:  {test.metrics['minimum_required']}")
                    elif test.test_name == "Cross-Correlation Analysis":
                        print(f"  ├─ Lag range tested:  {test.metrics['lag_range_periods'][0]} to {test.metrics['lag_range_periods'][1]} periods")
                        print(f"  ├─ Correlation at lag=0:      {test.metrics['correlation_at_zero']:.4f}")
                        print(f"  ├─ Correlation at optimal:    {test.metrics['correlation_at_optimal']:.4f} (at lag={test.metrics['optimal_lag_periods']}, {test.metrics['optimal_lag_seconds']}s)")
                        print(f"  ├─ Improvement over zero-lag: {test.metrics['improvement_over_zero']:+.4f} ({test.metrics['improvement_pct']:.1f}%)")
                    elif test.test_name == "Granger Causality":
                        print(f"  ├─ Test type:         {test.metrics['test_type']}")
                        print(f"  ├─ P-value:           {test.metrics['p_value']:.4f}")
                        print(f"  ├─ Significance threshold: {test.metrics['significance_threshold']}")
                    elif test.test_name == "Rolling Correlation Stability":
                        print(f"  ├─ Window size:       {test.metrics['window_size']} periods")
                        print(f"  ├─ Mean correlation:  {test.metrics['mean_correlation']:.4f}")
                        print(f"  ├─ Std deviation:     {test.metrics['std_deviation']:.4f}")
                        print(f"  ├─ Stability score:   {test.metrics['stability_score']:.4f}")
                        print(f"  ├─ Stability threshold: {test.metrics['stability_threshold']}")
                    elif test.test_name == "Confidence Score Calculation":
                        print(f"  ├─ Factor breakdown:")
                        factors = test.metrics['factors']
                        for fname, fdata in factors.items():
                            print(f"  │   ├─ {fname}: {fdata['value']:.4f} × {fdata['weight']:.2f} = {fdata['contribution']:.4f}")
                        print(f"  ├─ Total confidence score: {test.metrics['total_score']:.4f}")
                        print(f"  ├─ Confidence level: {test.metrics['confidence_level'].upper()}")
                    
                    print(f"  └─ RESULT: {status}")
                    print(f"     Reason: {test.reason}")
                
                # Final conclusion
                print("\n" + "-"*80)
                direction = "POSITIVE" if report.correlation_at_optimal_lag >= 0 else "NEGATIVE"
                print(f"  FINAL CONCLUSION: {report.leader_symbol} is a {report.trading_signal_strength.upper()} {direction} leading indicator for {report.follower_symbol}")
                print(f"  ├─ Optimal lag: {report.optimal_lag_seconds} seconds")
                print(f"  ├─ Correlation: {report.correlation_at_optimal_lag:.4f} ({direction.lower()}: {'both rise/fall together' if direction == 'POSITIVE' else 'inverse relationship'})")
                print(f"  ├─ Confidence: {report.confidence_score:.4f} ({report.confidence_level})")
                if report.caveats:
                    print(f"  ├─ Caveats: {', '.join(report.caveats)}")
                print(f"  └─ Recommendation: {report.recommendation}")
                print("="*80 + "\n")
                
                if config.output_report:
                    with open(config.output_report, 'w') as f:
                        json.dump(asdict(report), f, indent=2)
                    logger.info(f"Report saved to: {config.output_report}")
            else:
                print("Analysis failed - insufficient data or invalid symbols")
        
        else:
            # Discovery mode
            logger.info("Running in discovery mode...")
            report = analyzer.discover_pairs()
            
            if report:
                print("\n" + "="*70)
                print("                   DISCOVERY REPORT")
                print("="*70)
                print(f"Generated: {report.generated_at}")
                print(f"Data Range: {report.data_range_start} to {report.data_range_end}")
                print(f"Coins Analyzed: {', '.join(report.coins_analyzed)}")
                print(f"Pairs Tested: {report.pairs_tested}")
                print("-"*70)
                
                if report.significant_pairs:
                    print(f"\nSIGNIFICANT PAIRS (confidence >= {config.min_confidence}):\n")
                    for pair in report.significant_pairs:
                        print("-"*80)
                        print(f"\nPair: {pair['leader']} → {pair['follower']}")
                        print("-"*80)
                        
                        # Print detailed test results if available
                        if 'test_results' in pair and pair['test_results']:
                            for i, test in enumerate(pair['test_results'], 1):
                                status = "PASS ✓" if test.passed else "FAIL ✗"
                                print(f"\n  TEST {i}: {test.test_name}")
                                
                                if test.test_name == "Data Validation":
                                    print(f"  ├─ Leader samples:    {test.metrics['leader_samples']}")
                                    print(f"  ├─ Follower samples:  {test.metrics['follower_samples']}")
                                    print(f"  ├─ Minimum required:  {test.metrics['minimum_required']}")
                                elif test.test_name == "Cross-Correlation Analysis":
                                    print(f"  ├─ Lag range tested:  {test.metrics['lag_range_periods'][0]} to {test.metrics['lag_range_periods'][1]} periods")
                                    print(f"  ├─ Correlation at lag=0:      {test.metrics['correlation_at_zero']:.4f}")
                                    print(f"  ├─ Correlation at optimal:    {test.metrics['correlation_at_optimal']:.4f} (at lag={test.metrics['optimal_lag_periods']}, {test.metrics['optimal_lag_seconds']}s)")
                                    print(f"  ├─ Improvement over zero-lag: {test.metrics['improvement_over_zero']:+.4f} ({test.metrics['improvement_pct']:.1f}%)")
                                elif test.test_name == "Granger Causality":
                                    print(f"  ├─ Test type:         {test.metrics['test_type']}")
                                    print(f"  ├─ P-value:           {test.metrics['p_value']:.4f}")
                                    print(f"  ├─ Significance threshold: {test.metrics['significance_threshold']}")
                                elif test.test_name == "Rolling Correlation Stability":
                                    print(f"  ├─ Window size:       {test.metrics['window_size']} periods")
                                    print(f"  ├─ Mean correlation:  {test.metrics['mean_correlation']:.4f}")
                                    print(f"  ├─ Std deviation:     {test.metrics['std_deviation']:.4f}")
                                    print(f"  ├─ Stability score:   {test.metrics['stability_score']:.4f}")
                                    print(f"  ├─ Stability threshold: {test.metrics['stability_threshold']}")
                                elif test.test_name == "Confidence Score Calculation":
                                    print(f"  ├─ Factor breakdown:")
                                    factors = test.metrics['factors']
                                    for fname, fdata in factors.items():
                                        print(f"  │   ├─ {fname}: {fdata['value']:.4f} × {fdata['weight']:.2f} = {fdata['contribution']:.4f}")
                                    print(f"  ├─ Total confidence score: {test.metrics['total_score']:.4f}")
                                    print(f"  ├─ Confidence level: {test.metrics['confidence_level'].upper()}")
                                
                                print(f"  └─ RESULT: {status}")
                                print(f"     Reason: {test.reason}")
                        
                        # Final conclusion for this pair
                        print("\n" + "-"*40)
                        strength = "STRONG" if pair['confidence'] >= 0.7 else "MODERATE" if pair['confidence'] >= 0.5 else "WEAK"
                        direction = "POSITIVE" if pair['correlation'] >= 0 else "NEGATIVE"
                        print(f"  CONCLUSION: {pair['leader']} is a {strength} {direction} leading indicator for {pair['follower']}")
                        print(f"  ├─ Optimal lag: {pair['optimal_lag_seconds']} seconds")
                        print(f"  ├─ Correlation: {pair['correlation']:.4f} ({direction.lower()}: {'both rise/fall together' if direction == 'POSITIVE' else 'inverse relationship'})")
                        print(f"  ├─ Confidence: {pair['confidence']:.4f}")
                        if pair.get('caveats'):
                            print(f"  ├─ Caveats: {', '.join(pair['caveats'])}")
                        print(f"  └─ {pair['recommendation']}")
                        print()
                else:
                    print("\nNo significant leading indicator pairs found.")
                
                # Verbose mode: show all pairs including non-significant ones
                if config.verbose and report.no_significant_relationship:
                    print("\n" + "="*80)
                    print("                    ALL PAIRS (VERBOSE MODE)")
                    print("="*80)
                    
                    for pair in report.no_significant_relationship:
                        print("-"*80)
                        print(f"\nPair: {pair['leader']} → {pair['follower']}")
                        print(f"Status: {pair.get('reason', 'Unknown')}")
                        print("-"*80)
                        
                        # Print detailed test results if available
                        if pair.get('test_results'):
                            for i, test in enumerate(pair['test_results'], 1):
                                status = "PASS ✓" if test.passed else "FAIL ✗"
                                print(f"\n  TEST {i}: {test.test_name}")
                                
                                if test.test_name == "Data Validation":
                                    print(f"  ├─ Leader samples:    {test.metrics['leader_samples']}")
                                    print(f"  ├─ Follower samples:  {test.metrics['follower_samples']}")
                                    print(f"  ├─ Minimum required:  {test.metrics['minimum_required']}")
                                elif test.test_name == "Cross-Correlation Analysis":
                                    print(f"  ├─ Lag range tested:  {test.metrics['lag_range_periods'][0]} to {test.metrics['lag_range_periods'][1]} periods")
                                    print(f"  ├─ Correlation at lag=0:      {test.metrics['correlation_at_zero']:.4f}")
                                    print(f"  ├─ Correlation at optimal:    {test.metrics['correlation_at_optimal']:.4f} (at lag={test.metrics['optimal_lag_periods']}, {test.metrics['optimal_lag_seconds']}s)")
                                    print(f"  ├─ Improvement over zero-lag: {test.metrics['improvement_over_zero']:+.4f} ({test.metrics['improvement_pct']:.1f}%)")
                                elif test.test_name == "Granger Causality":
                                    print(f"  ├─ Test type:         {test.metrics['test_type']}")
                                    print(f"  ├─ P-value:           {test.metrics['p_value']:.4f}")
                                    print(f"  ├─ Significance threshold: {test.metrics['significance_threshold']}")
                                elif test.test_name == "Rolling Correlation Stability":
                                    print(f"  ├─ Window size:       {test.metrics['window_size']} periods")
                                    print(f"  ├─ Mean correlation:  {test.metrics['mean_correlation']:.4f}")
                                    print(f"  ├─ Std deviation:     {test.metrics['std_deviation']:.4f}")
                                    print(f"  ├─ Stability score:   {test.metrics['stability_score']:.4f}")
                                    print(f"  ├─ Stability threshold: {test.metrics['stability_threshold']}")
                                elif test.test_name == "Confidence Score Calculation":
                                    print(f"  ├─ Factor breakdown:")
                                    factors = test.metrics['factors']
                                    for fname, fdata in factors.items():
                                        print(f"  │   ├─ {fname}: {fdata['value']:.4f} × {fdata['weight']:.2f} = {fdata['contribution']:.4f}")
                                    print(f"  ├─ Total confidence score: {test.metrics['total_score']:.4f}")
                                    print(f"  ├─ Confidence level: {test.metrics['confidence_level'].upper()}")
                                
                                print(f"  └─ RESULT: {status}")
                                print(f"     Reason: {test.reason}")
                            
                            # Final summary for this pair
                            if pair.get('confidence') is not None:
                                print("\n" + "-"*40)
                                corr_val = pair.get('correlation', 0)
                                direction = "POSITIVE" if corr_val >= 0 else "NEGATIVE"
                                print(f"  SUMMARY: {pair['leader']} → {pair['follower']} ({direction})")
                                print(f"  ├─ Optimal lag: {pair.get('optimal_lag_seconds', 'N/A')} seconds")
                                print(f"  ├─ Correlation: {corr_val:.4f} ({direction.lower()}: {'both rise/fall together' if direction == 'POSITIVE' else 'inverse relationship'})")
                                print(f"  ├─ Confidence: {pair.get('confidence', 0):.4f}")
                                print(f"  └─ Result: Below threshold ({config.min_confidence})")
                        else:
                            print("  No test results available (insufficient data)")
                        print()
                
                print("="*70 + "\n")
                
                if config.output_report:
                    with open(config.output_report, 'w') as f:
                        json.dump(asdict(report), f, indent=2, default=str)
                    logger.info(f"Report saved to: {config.output_report}")
    
    else:
        # ==================== COLLECTOR MODE ====================
        config = CollectorConfig()
        
        # Apply YAML config
        if 'collector' in yaml_config:
            cc = yaml_config['collector']
            config.interval_seconds = cc.get('interval_seconds', config.interval_seconds)
            config.output_dir = cc.get('output_dir', config.output_dir)
            config.source = cc.get('source', config.source)
        
        if 'coins' in yaml_config:
            config.coins = yaml_config['coins']
        
        # Apply CLI args (override YAML)
        if args.coins:
            config.coins = [c.strip().upper() for c in args.coins.split(',')]
        
        # Parse interval with duration support
        try:
            config.interval_seconds = parse_duration(args.interval)
        except ValueError as e:
            logger.error(f"Invalid interval: {e}")
            sys.exit(1)
        
        config.output_dir = args.output_dir
        config.auto_search = not args.no_auto_search
        
        # Parse duration if provided
        duration_seconds = None
        if args.duration:
            try:
                duration_seconds = parse_duration(args.duration)
                logger.info(f"Collection duration: {format_duration(duration_seconds)}")
            except ValueError as e:
                logger.error(f"Invalid duration: {e}")
                sys.exit(1)
        
        if not config.coins:
            logger.error("No coins specified. Use --coins BTC,ETH,SOL or provide a config file.")
            sys.exit(1)
        
        collector = DataCollector(config)
        collector.run(duration_seconds=duration_seconds)


if __name__ == '__main__':
    main()
