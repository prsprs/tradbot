#!/usr/bin/env python3
"""
Unit tests for Fibonacci Retracement Analyzer.

Tests:
- Swing point detection (high/low finding)
- Fibonacci level calculation
- Touch/bounce detection
- Report generation
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fibonacci_analyzer import (
    FibonacciAnalyzer,
    FibonacciLevel,
    FibonacciReport,
    PricePoint,
    DataLoader,
    parse_duration,
    format_duration,
    format_report,
    format_summary_table,
    save_fib_report,
    load_fib_report,
    list_cached_reports,
)
from leading_indicator_tester import FibTradeFilter, FibFilterResult


class TestParseDuration(unittest.TestCase):
    """Test duration parsing utility."""
    
    def test_seconds(self):
        self.assertEqual(parse_duration('30'), 30)
        self.assertEqual(parse_duration('30s'), 30)
        self.assertEqual(parse_duration('30sec'), 30)
        self.assertEqual(parse_duration('30secs'), 30)
    
    def test_minutes(self):
        self.assertEqual(parse_duration('5m'), 300)
        self.assertEqual(parse_duration('5min'), 300)
        self.assertEqual(parse_duration('5mins'), 300)
    
    def test_hours(self):
        self.assertEqual(parse_duration('1h'), 3600)
        self.assertEqual(parse_duration('1hr'), 3600)
        self.assertEqual(parse_duration('1hrs'), 3600)
        self.assertEqual(parse_duration('1hour'), 3600)
        self.assertEqual(parse_duration('1hours'), 3600)
        self.assertEqual(parse_duration('24h'), 86400)
    
    def test_days(self):
        self.assertEqual(parse_duration('1d'), 86400)
        self.assertEqual(parse_duration('1day'), 86400)
        self.assertEqual(parse_duration('7days'), 604800)
    
    def test_default_unit(self):
        self.assertEqual(parse_duration('30', default_unit='sec'), 30)
        self.assertEqual(parse_duration('30', default_unit='hr'), 108000)
    
    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            parse_duration('invalid')
        with self.assertRaises(ValueError):
            parse_duration('')


class TestFormatDuration(unittest.TestCase):
    """Test duration formatting utility."""
    
    def test_seconds(self):
        self.assertEqual(format_duration(30), '30s')
    
    def test_minutes(self):
        self.assertEqual(format_duration(60), '1m')
        self.assertEqual(format_duration(90), '1m 30s')
        self.assertEqual(format_duration(300), '5m')
    
    def test_hours(self):
        self.assertEqual(format_duration(3600), '1h')
        self.assertEqual(format_duration(5400), '1h 30m')
    
    def test_days(self):
        self.assertEqual(format_duration(86400), '1d')
        self.assertEqual(format_duration(90000), '1d 1h')
        self.assertEqual(format_duration(604800), '7d')


class TestFibonacciLevel(unittest.TestCase):
    """Test FibonacciLevel dataclass."""
    
    def test_effectiveness_no_touches(self):
        level = FibonacciLevel(ratio=0.5, price=100.0)
        self.assertIsNone(level.effectiveness)
    
    def test_effectiveness_with_touches(self):
        level = FibonacciLevel(ratio=0.5, price=100.0, touch_count=10, bounce_count=7)
        self.assertEqual(level.effectiveness, 70.0)
    
    def test_to_dict(self):
        level = FibonacciLevel(
            ratio=0.618,
            price=87.64,
            touch_count=5,
            bounce_count=3,
            breakthrough_count=2,
            avg_bounce_magnitude=1.5
        )
        d = level.to_dict()
        self.assertEqual(d['ratio'], 0.618)
        self.assertEqual(d['price'], 87.64)
        self.assertEqual(d['touch_count'], 5)
        self.assertEqual(d['effectiveness_pct'], 60.0)


class TestFibonacciAnalyzer(unittest.TestCase):
    """Test FibonacciAnalyzer core functionality."""
    
    def setUp(self):
        """Set up test analyzer."""
        self.analyzer = FibonacciAnalyzer(
            data_dir='./test_data',  # Won't be used in these tests
            touch_tolerance_pct=0.5,
            confirmation_periods=3,
            min_touches=2
        )
    
    def test_calculate_fib_levels(self):
        """Test Fibonacci level calculation."""
        levels = self.analyzer._calculate_fib_levels(high=100.0, low=80.0)
        
        # Check all standard levels are present
        self.assertIn('0.0%', levels)
        self.assertIn('23.6%', levels)
        self.assertIn('38.2%', levels)
        self.assertIn('50.0%', levels)
        self.assertIn('61.8%', levels)
        self.assertIn('78.6%', levels)
        self.assertIn('100.0%', levels)
        
        # Verify calculations: retracement_price = high - (high - low) * ratio
        # Range = 20
        self.assertAlmostEqual(levels['0.0%'].price, 100.0, places=4)
        self.assertAlmostEqual(levels['23.6%'].price, 100 - (20 * 0.236), places=4)  # 95.28
        self.assertAlmostEqual(levels['38.2%'].price, 100 - (20 * 0.382), places=4)  # 92.36
        self.assertAlmostEqual(levels['50.0%'].price, 90.0, places=4)
        self.assertAlmostEqual(levels['61.8%'].price, 100 - (20 * 0.618), places=4)  # 87.64
        self.assertAlmostEqual(levels['78.6%'].price, 100 - (20 * 0.786), places=4)  # 84.28
        self.assertAlmostEqual(levels['100.0%'].price, 80.0, places=4)
    
    def test_find_swing_points(self):
        """Test high/low point detection."""
        prices = [
            PricePoint(timestamp=datetime.now(timezone.utc) - timedelta(hours=5), price=100.0),
            PricePoint(timestamp=datetime.now(timezone.utc) - timedelta(hours=4), price=90.0),
            PricePoint(timestamp=datetime.now(timezone.utc) - timedelta(hours=3), price=80.0),  # Low
            PricePoint(timestamp=datetime.now(timezone.utc) - timedelta(hours=2), price=95.0),
            PricePoint(timestamp=datetime.now(timezone.utc) - timedelta(hours=1), price=120.0),  # High
            PricePoint(timestamp=datetime.now(timezone.utc), price=110.0),
        ]
        
        high, high_idx, low, low_idx = self.analyzer._find_swing_points(prices)
        
        self.assertEqual(high, 120.0)
        self.assertEqual(high_idx, 4)
        self.assertEqual(low, 80.0)
        self.assertEqual(low_idx, 2)
    
    def test_find_swing_points_empty(self):
        """Test swing point detection with empty list."""
        high, high_idx, low, low_idx = self.analyzer._find_swing_points([])
        self.assertIsNone(high)
        self.assertIsNone(low)
    
    def test_analyze_with_price_data(self):
        """Test full analysis with provided price data."""
        # Create price data that clearly bounces off a Fib level
        base_time = datetime.now(timezone.utc) - timedelta(hours=10)
        prices = []
        
        # Create a swing: start at 100, go down to 80, back up
        # Then test touch at 38.2% level (92.36 for high=100, low=80)
        price_sequence = [
            100.0,  # Start
            95.0,
            90.0,
            85.0,
            80.0,   # Low point
            82.0,
            85.0,
            88.0,
            92.0,   # Approaching 38.2% level (~92.36)
            92.3,   # Touch the level
            91.5,   # Bounce back
            90.0,
            91.0,
            92.5,   # Another approach
            92.3,   # Touch again
            91.0,   # Bounce again
            90.5,
            91.0,
        ]
        
        for i, price in enumerate(price_sequence):
            prices.append(PricePoint(
                timestamp=base_time + timedelta(minutes=i * 30),
                price=price
            ))
        
        report = self.analyzer.analyze('TEST', prices=prices)
        
        self.assertIsNotNone(report)
        self.assertEqual(report.symbol, 'TEST')
        self.assertEqual(report.high_price, 100.0)
        self.assertEqual(report.low_price, 80.0)
        self.assertEqual(report.trend_direction, 'down')  # High at index 0 comes before low at index 4
        self.assertEqual(report.data_points_analyzed, len(prices))
    
    def test_analyze_downtrend(self):
        """Test analysis detects downtrend correctly."""
        base_time = datetime.now(timezone.utc) - timedelta(hours=5)
        prices = [
            PricePoint(timestamp=base_time, price=100.0),  # High first
            PricePoint(timestamp=base_time + timedelta(hours=1), price=95.0),
            PricePoint(timestamp=base_time + timedelta(hours=2), price=90.0),
            PricePoint(timestamp=base_time + timedelta(hours=3), price=85.0),
            PricePoint(timestamp=base_time + timedelta(hours=4), price=80.0),  # Low last
        ]
        
        report = self.analyzer.analyze('TEST', prices=prices)
        
        self.assertIsNotNone(report)
        self.assertEqual(report.trend_direction, 'down')  # High came before low


class TestDataLoader(unittest.TestCase):
    """Test DataLoader with synthetic JSONL data."""
    
    def setUp(self):
        """Create temporary directory with test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / 'test_data'
        self.data_dir.mkdir(parents=True)
        
        # Create date subdirectory
        date_dir = self.data_dir / '2026-01-01'
        date_dir.mkdir()
        
        # Create JSONL file with test records
        jsonl_file = date_dir / 'prices_00-06.jsonl'
        
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        records = []
        
        for i in range(10):
            timestamp = base_time + timedelta(minutes=i * 30)
            records.append({
                'symbol': 'TEST',
                'timestamp': timestamp.isoformat(),
                'source': 'test',
                'price': 100.0 + i,  # 100, 101, 102, ...
            })
            records.append({
                'symbol': 'OTHER',
                'timestamp': timestamp.isoformat(),
                'source': 'test',
                'price': 50.0 + i,
            })
        
        with open(jsonl_file, 'w') as f:
            for record in records:
                f.write(json.dumps(record) + '\n')
        
        self.loader = DataLoader(str(self.data_dir))
    
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_load_symbol(self):
        """Test loading data for a specific symbol."""
        df = self.loader.load_symbol('TEST')
        
        self.assertEqual(len(df), 10)
        self.assertEqual(df['price'].iloc[0], 100.0)
        self.assertEqual(df['price'].iloc[9], 109.0)
    
    def test_load_symbol_case_insensitive(self):
        """Test symbol matching is case-insensitive."""
        df = self.loader.load_symbol('test')
        self.assertEqual(len(df), 10)
        
        df = self.loader.load_symbol('Test')
        self.assertEqual(len(df), 10)
    
    def test_load_symbol_not_found(self):
        """Test loading non-existent symbol returns empty DataFrame."""
        df = self.loader.load_symbol('NOTFOUND')
        self.assertTrue(df.empty)
    
    def test_get_available_symbols(self):
        """Test listing available symbols."""
        symbols = self.loader.get_available_symbols()
        self.assertIn('TEST', symbols)
        self.assertIn('OTHER', symbols)
        self.assertEqual(len(symbols), 2)
    
    def test_load_csv(self):
        """Test loading data from CSV file with OHLCV format."""
        # Create a CSV file
        csv_file = self.data_dir / 'test_ohlcv.csv'
        csv_content = """Etc/UTC,Open,High,Low,Close,Volume
2026-05-29T00:00:00+00:00,73498.3,73785.2,73498.3,73774.4,14287
2026-05-29T00:45:00+00:00,73726.6,73784.8,73449,73524.8,13168
2026-05-29T01:30:00+00:00,73496.4,73559.8,73340.2,73549.8,13073
2026-05-29T02:15:00+00:00,73551.5,73574.8,73061.8,73103.2,14485
2026-05-29T03:00:00+00:00,73103.4,73381.8,73103.4,73237.8,10766
"""
        with open(csv_file, 'w') as f:
            f.write(csv_content)
        
        df = self.loader.load_csv('test_ohlcv.csv')
        
        self.assertEqual(len(df), 5)
        self.assertEqual(df['price'].iloc[0], 73774.4)  # First Close price
        self.assertEqual(df['price'].iloc[4], 73237.8)  # Last Close price
        self.assertIn('timestamp', df.columns)
        self.assertIn('price', df.columns)
    
    def test_load_csv_not_found(self):
        """Test loading non-existent CSV returns empty DataFrame."""
        df = self.loader.load_csv('nonexistent.csv')
        self.assertTrue(df.empty)
    
    def test_load_csv_missing_close_column(self):
        """Test loading CSV without Close column returns empty DataFrame."""
        csv_file = self.data_dir / 'no_close.csv'
        csv_content = """Timestamp,Open,High,Low,Volume
2026-05-29T00:00:00+00:00,73498.3,73785.2,73498.3,14287
"""
        with open(csv_file, 'w') as f:
            f.write(csv_content)
        
        df = self.loader.load_csv('no_close.csv')
        self.assertTrue(df.empty)


class TestFormatReport(unittest.TestCase):
    """Test report formatting."""
    
    def test_format_report_basic(self):
        """Test basic report formatting."""
        report = FibonacciReport(
            symbol='SOL',
            analysis_window='7d',
            window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
            window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
            high_price=185.42,
            high_timestamp=datetime(2026, 5, 27, 14, 30, tzinfo=timezone.utc),
            low_price=142.18,
            low_timestamp=datetime(2026, 5, 22, 3, 15, tzinfo=timezone.utc),
            trend_direction='up',
            levels={
                '0.0%': FibonacciLevel(ratio=0.0, price=185.42, touch_count=1),
                '23.6%': FibonacciLevel(ratio=0.236, price=175.22, touch_count=4, bounce_count=3, breakthrough_count=1),
                '38.2%': FibonacciLevel(ratio=0.382, price=168.90, touch_count=7, bounce_count=5, breakthrough_count=2),
                '50.0%': FibonacciLevel(ratio=0.5, price=163.80, touch_count=5, bounce_count=2, breakthrough_count=3),
                '61.8%': FibonacciLevel(ratio=0.618, price=158.70, touch_count=3, bounce_count=2, breakthrough_count=1),
                '78.6%': FibonacciLevel(ratio=0.786, price=151.42, touch_count=2, bounce_count=2, breakthrough_count=0),
                '100.0%': FibonacciLevel(ratio=1.0, price=142.18, touch_count=1),
            },
            most_respected_level='78.6%',
            overall_effectiveness=66.7,
            total_touches=21,
            total_bounces=14,
            data_points_analyzed=2000
        )
        
        output = format_report(report)
        
        # Check key elements are present
        self.assertIn('FIBONACCI RETRACEMENT ANALYSIS', output)
        self.assertIn('SOL', output)
        self.assertIn('UPTREND', output)
        self.assertIn('185.42', output)  # High price
        self.assertIn('142.18', output)  # Low price
        self.assertIn('78.6%', output)   # Most respected level
        self.assertIn('66.7%', output)   # Overall effectiveness


class TestFormatSummaryTable(unittest.TestCase):
    """Test summary table formatting for multiple reports."""
    
    def test_format_summary_table(self):
        """Test summary table generation."""
        reports = [
            FibonacciReport(
                symbol='SOL',
                analysis_window='7d',
                window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
                window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
                high_price=185.42,
                high_timestamp=datetime(2026, 5, 27, tzinfo=timezone.utc),
                low_price=142.18,
                low_timestamp=datetime(2026, 5, 22, tzinfo=timezone.utc),
                trend_direction='up',
                levels={},
                most_respected_level='38.2%',
                overall_effectiveness=71.4,
                total_touches=14,
                total_bounces=10,
            ),
            FibonacciReport(
                symbol='BTC',
                analysis_window='7d',
                window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
                window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
                high_price=68500.0,
                high_timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
                low_price=64200.0,
                low_timestamp=datetime(2026, 5, 23, tzinfo=timezone.utc),
                trend_direction='up',
                levels={},
                most_respected_level='61.8%',
                overall_effectiveness=55.0,
                total_touches=20,
                total_bounces=11,
            ),
        ]
        
        output = format_summary_table(reports)
        
        self.assertIn('FIBONACCI ANALYSIS SUMMARY', output)
        self.assertIn('SOL', output)
        self.assertIn('BTC', output)
        self.assertIn('Total symbols analyzed: 2', output)
        # SOL should be first (higher effectiveness)
        self.assertTrue(output.index('SOL') < output.index('BTC'))


class TestIntegration(unittest.TestCase):
    """Integration tests for complete workflows."""
    
    def test_full_analysis_pipeline(self):
        """Test complete analysis from price data to formatted report."""
        analyzer = FibonacciAnalyzer(
            data_dir='./test_data',
            touch_tolerance_pct=1.0,  # Wider tolerance for test
            confirmation_periods=2,
            min_touches=1
        )
        
        # Create realistic price data
        base_time = datetime.now(timezone.utc) - timedelta(days=7)
        prices = []
        
        # Simulate a price swing from 100 to 80 and back up
        import math
        for i in range(200):
            t = i / 200.0  # 0 to 1
            # Create a wave pattern: down then up
            if t < 0.3:
                price = 100 - (20 * t / 0.3)  # 100 → 80
            elif t < 0.6:
                price = 80 + (30 * (t - 0.3) / 0.3)  # 80 → 110
            else:
                price = 110 - (10 * (t - 0.6) / 0.4)  # 110 → 100
            
            # Add some noise
            price += math.sin(i * 0.3) * 2
            
            prices.append(PricePoint(
                timestamp=base_time + timedelta(hours=i),
                price=price
            ))
        
        report = analyzer.analyze('TEST', prices=prices)
        
        self.assertIsNotNone(report)
        self.assertEqual(report.symbol, 'TEST')
        self.assertEqual(len(report.levels), 7)  # All standard Fib levels
        
        # Verify report can be serialized
        report_dict = report.to_dict()
        self.assertIn('symbol', report_dict)
        self.assertIn('levels', report_dict)
        
        # Verify report can be formatted
        formatted = format_report(report)
        self.assertIsInstance(formatted, str)
        self.assertIn('TEST', formatted)


class TestFibReportCache(unittest.TestCase):
    """Test Fib Report Cache save/load functionality."""
    
    def setUp(self):
        """Create temporary directory for cache tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / 'correlation_data'
        self.data_dir.mkdir(parents=True)
    
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def _create_sample_report(self, symbol='SOL'):
        """Create a sample FibonacciReport for testing."""
        return FibonacciReport(
            symbol=symbol,
            analysis_window='7d',
            window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
            window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
            high_price=185.42,
            high_timestamp=datetime(2026, 5, 27, 14, 30, tzinfo=timezone.utc),
            low_price=142.18,
            low_timestamp=datetime(2026, 5, 22, 3, 15, tzinfo=timezone.utc),
            trend_direction='up',
            levels={
                '0.0%': FibonacciLevel(ratio=0.0, price=185.42, touch_count=1),
                '38.2%': FibonacciLevel(ratio=0.382, price=168.90, touch_count=5, bounce_count=4),
                '61.8%': FibonacciLevel(ratio=0.618, price=158.70, touch_count=3, bounce_count=2),
            },
            most_respected_level='38.2%',
            overall_effectiveness=66.7,
            total_touches=9,
            total_bounces=6,
        )
    
    def test_save_and_load_report(self):
        """Test saving and loading a report."""
        report = self._create_sample_report()
        
        # Save
        save_fib_report(report, str(self.data_dir))
        
        # Verify file exists
        report_path = self.data_dir / 'fib_reports' / 'SOL_fib_report.json'
        self.assertTrue(report_path.exists())
        
        # Load
        loaded = load_fib_report('SOL', str(self.data_dir))
        
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.symbol, 'SOL')
        self.assertEqual(loaded.high_price, 185.42)
        self.assertEqual(loaded.low_price, 142.18)
        self.assertEqual(loaded.trend_direction, 'up')
        self.assertEqual(len(loaded.levels), 3)
        self.assertEqual(loaded.levels['38.2%'].touch_count, 5)
    
    def test_load_nonexistent_report(self):
        """Test loading a report that doesn't exist."""
        loaded = load_fib_report('NOTFOUND', str(self.data_dir))
        self.assertIsNone(loaded)
    
    def test_list_cached_reports(self):
        """Test listing cached reports."""
        # Initially empty
        cached = list_cached_reports(str(self.data_dir))
        self.assertEqual(len(cached), 0)
        
        # Save some reports
        save_fib_report(self._create_sample_report('SOL'), str(self.data_dir))
        save_fib_report(self._create_sample_report('BTC'), str(self.data_dir))
        
        # List should show both
        cached = list_cached_reports(str(self.data_dir))
        self.assertEqual(len(cached), 2)
        self.assertIn('SOL', cached)
        self.assertIn('BTC', cached)
    
    def test_report_round_trip_preserves_data(self):
        """Test that save/load preserves all report data."""
        original = self._create_sample_report()
        
        save_fib_report(original, str(self.data_dir))
        loaded = load_fib_report('SOL', str(self.data_dir))
        
        # Compare key fields
        self.assertEqual(original.symbol, loaded.symbol)
        self.assertEqual(original.analysis_window, loaded.analysis_window)
        self.assertEqual(original.high_price, loaded.high_price)
        self.assertEqual(original.low_price, loaded.low_price)
        self.assertEqual(original.trend_direction, loaded.trend_direction)
        self.assertEqual(original.most_respected_level, loaded.most_respected_level)
        self.assertEqual(original.overall_effectiveness, loaded.overall_effectiveness)
        self.assertEqual(len(original.levels), len(loaded.levels))


class TestFibTradeFilter(unittest.TestCase):
    """Test Fibonacci trade filtering logic."""
    
    def _create_uptrend_report(self):
        """Create an uptrend Fib report (low before high)."""
        return FibonacciReport(
            symbol='SOL',
            analysis_window='7d',
            window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
            window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
            high_price=200.0,
            high_timestamp=datetime(2026, 5, 27, 14, 30, tzinfo=timezone.utc),
            low_price=100.0,
            low_timestamp=datetime(2026, 5, 22, 3, 15, tzinfo=timezone.utc),
            trend_direction='up',  # Low before high = uptrend
            levels={
                '0.0%': FibonacciLevel(ratio=0.0, price=200.0, touch_count=1),
                '38.2%': FibonacciLevel(ratio=0.382, price=161.8, touch_count=5, bounce_count=4),
                '50.0%': FibonacciLevel(ratio=0.5, price=150.0, touch_count=3, bounce_count=1),
                '61.8%': FibonacciLevel(ratio=0.618, price=138.2, touch_count=4, bounce_count=3),
                '100.0%': FibonacciLevel(ratio=1.0, price=100.0, touch_count=1),
            },
            most_respected_level='38.2%',
            overall_effectiveness=66.7,
        )
    
    def _create_downtrend_report(self):
        """Create a downtrend Fib report (high before low)."""
        return FibonacciReport(
            symbol='SOL',
            analysis_window='7d',
            window_start=datetime(2026, 5, 21, tzinfo=timezone.utc),
            window_end=datetime(2026, 5, 28, tzinfo=timezone.utc),
            high_price=200.0,
            high_timestamp=datetime(2026, 5, 22, 3, 15, tzinfo=timezone.utc),  # High comes first
            low_price=100.0,
            low_timestamp=datetime(2026, 5, 27, 14, 30, tzinfo=timezone.utc),  # Low comes after
            trend_direction='down',  # High before low = downtrend
            levels={
                '0.0%': FibonacciLevel(ratio=0.0, price=200.0, touch_count=1),
                '38.2%': FibonacciLevel(ratio=0.382, price=161.8, touch_count=5, bounce_count=4),
                '50.0%': FibonacciLevel(ratio=0.5, price=150.0, touch_count=3, bounce_count=1),
                '61.8%': FibonacciLevel(ratio=0.618, price=138.2, touch_count=4, bounce_count=3),
                '100.0%': FibonacciLevel(ratio=1.0, price=100.0, touch_count=1),
            },
            most_respected_level='38.2%',
            overall_effectiveness=66.7,
        )
    
    def test_uptrend_buy_valid_near_low(self):
        """In uptrend, BUY near the low should be valid."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_uptrend_report(),
            tolerance_pct=1.0,  # 1% tolerance
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Price near the low (100.0) should be valid for BUY
        result = fib_filter.validate_signal('rise', 100.5)
        self.assertTrue(result.can_execute)
        self.assertIn('BUY valid', result.reason)
    
    def test_uptrend_buy_valid_near_support(self):
        """In uptrend, BUY near effective support level should be valid."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_uptrend_report(),
            tolerance_pct=1.0,
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Price near 61.8% level (138.2) which has >60% effectiveness
        result = fib_filter.validate_signal('rise', 138.0)
        self.assertTrue(result.can_execute)
        self.assertIn('BUY valid', result.reason)
    
    def test_uptrend_buy_blocked_not_near_support(self):
        """In uptrend, BUY far from support levels should be blocked."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_uptrend_report(),
            tolerance_pct=0.5,  # Tight tolerance
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Price at 180.0 - far from any effective support level
        result = fib_filter.validate_signal('rise', 180.0)
        self.assertFalse(result.can_execute)
        self.assertIn('BUY blocked', result.reason)
    
    def test_uptrend_sell_blocked(self):
        """In uptrend, SELL signals should be blocked."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_uptrend_report(),
            tolerance_pct=1.0,
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Any SELL should be blocked in uptrend
        result = fib_filter.validate_signal('fall', 150.0)
        self.assertFalse(result.can_execute)
        self.assertIn('SELL blocked', result.reason)
        self.assertIn('not DOWN', result.reason)
    
    def test_downtrend_sell_valid_near_high(self):
        """In downtrend, SELL near the high should be valid."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_downtrend_report(),
            tolerance_pct=1.0,
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Price near the high (200.0) should be valid for SELL
        result = fib_filter.validate_signal('fall', 199.0)
        self.assertTrue(result.can_execute)
        self.assertIn('SELL valid', result.reason)
    
    def test_downtrend_buy_blocked(self):
        """In downtrend, BUY signals should be blocked."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_downtrend_report(),
            tolerance_pct=1.0,
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Any BUY should be blocked in downtrend
        result = fib_filter.validate_signal('rise', 150.0)
        self.assertFalse(result.can_execute)
        self.assertIn('BUY blocked', result.reason)
        self.assertIn('not UP', result.reason)
    
    def test_price_out_of_range_invalidates(self):
        """Price outside Fib range should invalidate analysis."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_uptrend_report(),
            tolerance_pct=0.5,
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Price above high (200.0) + tolerance
        result = fib_filter.validate_signal('rise', 210.0)
        self.assertFalse(result.can_execute)
        self.assertIn('FIB INVALIDATED', result.reason)
        
        # Price below low (100.0) - tolerance
        result = fib_filter.validate_signal('rise', 90.0)
        self.assertFalse(result.can_execute)
        self.assertIn('FIB INVALIDATED', result.reason)
    
    def test_check_price_in_range(self):
        """Test price range checking."""
        fib_filter = FibTradeFilter(
            fib_report=self._create_uptrend_report(),
            tolerance_pct=1.0,  # 1% of range (100) = 1 tolerance
            min_effectiveness=60.0,
            min_touches=2,
        )
        
        # Within range
        in_range, _ = fib_filter.check_price_in_range(150.0)
        self.assertTrue(in_range)
        
        # At the boundaries (with tolerance)
        in_range, _ = fib_filter.check_price_in_range(100.5)
        self.assertTrue(in_range)
        
        in_range, _ = fib_filter.check_price_in_range(200.5)
        self.assertTrue(in_range)


if __name__ == '__main__':
    unittest.main()
