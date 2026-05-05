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
    python correlation_tracker.py --analyze --leader BTC --follower ETH --data-dir ./correlation_data

    # Discovery mode (find all leading indicator pairs)
    python correlation_tracker.py --analyze --data-dir ./correlation_data --min-confidence 0.6
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
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(sec|min|hr)s?$', value)
    
    if not match:
        raise ValueError(f"Invalid duration format: '{value}'. Use formats like: 30, 30sec, 5min, 1hr")
    
    amount = float(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        'sec': 1,
        'min': 60,
        'hr': 3600,
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

    def load_all(self) -> pd.DataFrame:
        """Load all data from the data directory."""
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
        leader_returns = self.loader.get_returns_series(df, leader)
        follower_returns = self.loader.get_returns_series(df, follower)
        
        if len(leader_returns) < self.config.min_samples or len(follower_returns) < self.config.min_samples:
            logger.warning(f"Insufficient samples for {leader}->{follower}: "
                          f"leader={len(leader_returns)}, follower={len(follower_returns)}, "
                          f"required={self.config.min_samples}")
            return None
        
        # Determine lag range
        if self.config.lag_range_seconds:
            max_lag_periods = self.config.lag_range_seconds[1] // interval_seconds
        else:
            max_lag_periods = self.config.lag_multiplier
        
        # Cross-correlation analysis
        lags, correlations = self.cross_correlation(leader_returns, follower_returns, max_lag_periods)
        
        if len(correlations) == 0:
            return None
        
        # Find optimal lag (positive lag = leader leads)
        positive_lag_mask = lags > 0
        if not any(positive_lag_mask):
            return None
        
        positive_correlations = correlations[positive_lag_mask]
        positive_lags = lags[positive_lag_mask]
        
        optimal_idx = np.argmax(np.abs(positive_correlations))
        optimal_lag = int(positive_lags[optimal_idx])
        correlation_at_optimal = float(positive_correlations[optimal_idx])
        
        # Correlation at zero lag
        zero_lag_idx = np.where(lags == 0)[0]
        correlation_at_zero = float(correlations[zero_lag_idx[0]]) if len(zero_lag_idx) > 0 else 0.0
        
        # Granger causality test
        pvalue, is_significant = self.granger_causality_test(leader_returns, follower_returns)
        
        # Rolling correlation stability
        _, stability = self.rolling_correlation(leader_returns, follower_returns)
        
        # Calculate aligned sample count
        aligned = pd.concat([leader_returns, follower_returns], axis=1, join='inner')
        num_samples = len(aligned)
        
        # Lag consistency: how much better is optimal lag vs zero lag
        lag_correlation_diff = abs(correlation_at_optimal) - abs(correlation_at_zero)
        
        # Confidence calculation
        confidence_score, confidence_level, confidence_factors = self.calculate_confidence(
            correlation_at_optimal, pvalue, stability, num_samples, lag_correlation_diff
        )
        
        # Determine date range
        timestamps = df['timestamp']
        
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
            trading_signal_strength=self._get_signal_strength(confidence_level)
        )
        
        return report

    def analyze_specific_pair(self, leader: str, follower: str) -> Optional[CorrelationReport]:
        """Analyze a specific leader-follower pair."""
        df = self.loader.load_all()
        
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
        df = self.loader.load_all()
        
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
                        'reason': 'Insufficient data'
                    })
                    continue
                
                if report.confidence_score >= self.config.min_confidence:
                    significant_pairs.append({
                        'leader': report.leader_symbol,
                        'follower': report.follower_symbol,
                        'optimal_lag_seconds': report.optimal_lag_seconds,
                        'correlation': report.correlation_at_optimal_lag,
                        'confidence': report.confidence_score,
                        'granger_significant': report.granger_causality_significant,
                        'recommendation': report.recommendation
                    })
                else:
                    no_relationship.append({
                        'leader': leader,
                        'follower': follower,
                        'reason': f"Low confidence ({report.confidence_score:.2f})"
                    })
        
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
  python correlation_tracker.py --analyze --leader BTC --follower ETH --data-dir ./correlation_data
  
  # Discovery mode (find all leading indicator pairs)
  python correlation_tracker.py --analyze --data-dir ./correlation_data --min-confidence 0.6
  
  # Use YAML config file
  python correlation_tracker.py --config correlation_tracker_config.yaml
  
  # Generate default config file
  python correlation_tracker.py --generate-config

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
                         help='Directory containing collected data')
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
    analyzer.add_argument('--output-report', type=str,
                         help='Path to save the analysis report (JSON)')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
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
        config.output_report = args.output_report
        
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
        
        analyzer = CorrelationAnalyzer(config)
        
        # Print warnings
        print("\n" + "="*70)
        print("                    IMPORTANT WARNINGS")
        print("="*70)
        print("• Correlation does NOT imply causation")
        print("• Past leading indicators may NOT remain so in the future")
        print("• Results should be one input among many for trading decisions")
        print("="*70 + "\n")
        
        if config.leader and config.follower:
            # Specific pair analysis
            logger.info(f"Analyzing pair: {config.leader} -> {config.follower}")
            report = analyzer.analyze_specific_pair(config.leader, config.follower)
            
            if report:
                print("\n" + "="*70)
                print(f"CORRELATION REPORT: {report.leader_symbol} → {report.follower_symbol}")
                print("="*70)
                print(f"Data Range: {report.data_range_start} to {report.data_range_end}")
                print(f"Total Samples: {report.total_samples}")
                print("-"*70)
                print(f"Optimal Lag: {report.optimal_lag_seconds} seconds")
                print(f"Correlation at Optimal Lag: {report.correlation_at_optimal_lag:.4f}")
                print(f"Correlation at Zero Lag: {report.correlation_at_zero_lag:.4f}")
                print("-"*70)
                print(f"Granger Causality p-value: {report.granger_causality_pvalue:.4f}")
                print(f"Granger Significant: {'Yes' if report.granger_causality_significant else 'No'}")
                print("-"*70)
                print(f"Confidence Score: {report.confidence_score:.4f}")
                print(f"Confidence Level: {report.confidence_level.upper()}")
                print(f"Stability: {report.correlation_stability:.4f} ({'Stable' if report.stable_relationship else 'Unstable'})")
                print("-"*70)
                print(f"Signal Strength: {report.trading_signal_strength.upper()}")
                print(f"Recommendation: {report.recommendation}")
                print("="*70 + "\n")
                
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
                        print(f"  {pair['leader']} → {pair['follower']}")
                        print(f"    Lag: {pair['optimal_lag_seconds']}s, Corr: {pair['correlation']:.3f}, "
                              f"Conf: {pair['confidence']:.3f}")
                        print(f"    Granger Significant: {'Yes' if pair['granger_significant'] else 'No'}")
                        print(f"    {pair['recommendation']}")
                        print()
                else:
                    print("\nNo significant leading indicator pairs found.")
                
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
