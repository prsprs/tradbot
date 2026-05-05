# Correlation History Tracker Operations Manual

This document describes the programs, environment variables, APIs, and configuration for the Correlation History Tracker (`correlation_tracker.py`).

---

## Program

### Correlation History Tracker (`correlation_tracker.py`)

A tool for collecting intraday cryptocurrency price data and analyzing correlations between coin pairs to identify **leading indicators** - coins whose price movements predictably precede another coin's movement.

**Usage:**
```bash
python correlation_tracker.py [OPTIONS]
```

---

## Modes of Operation

### Collector Mode (Default)

Continuously collect price data for specified coins at regular intervals.

```bash
python correlation_tracker.py --coins BTC,ETH,SOL --interval 30 --output-dir ./correlation_data
```

### Analyzer Mode

Analyze collected data to find leading indicator relationships.

```bash
python correlation_tracker.py --analyze --data-dir ./correlation_data
```

---

## Command-Line Options

### General Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--config` | path | *(empty)* | Path to YAML configuration file |
| `--generate-config` | flag | `false` | Generate a default configuration file |
| `--analyze` | flag | `false` | Run in analyzer mode (vs collector) |

### Collector Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--coins` | comma-separated | *(required)* | Coin symbols to collect (e.g., `BTC,ETH,SOL`) |
| `--interval` | duration string | `30` | Collection interval (e.g., `30`, `30sec`, `5min`, `1hr`) |
| `--output-dir` | path | `./correlation_data` | Output directory for collected data |
| `--duration` | duration string | *(indefinite)* | Collection duration (e.g., `1hr`, `6hr`, `24hr`) |
| `--no-auto-search` | flag | `false` | Disable auto-search for unknown coin symbols |

### Analyzer Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--data-dir` | path | `./correlation_data` | Directory containing collected data |
| `--leader` | symbol | *(empty)* | Leader coin for specific pair analysis |
| `--follower` | symbol | *(empty)* | Follower coin for specific pair analysis |
| `--leader-candidates` | comma-separated | *(all coins)* | Leader candidates for discovery mode |
| `--follower-candidates` | comma-separated | *(all coins)* | Follower candidates for discovery mode |
| `--min-confidence` | 0.0-1.0 | `0.6` | Minimum confidence score for significant pairs |
| `--min-samples` | integer | `500` | Minimum samples required for analysis |
| `--lag-range` | range string | *(auto)* | Lag range to test (e.g., `0-300`, `0-5min`, `1min-1hr`) |
| `--recent` | duration string | *(all data)* | Only analyze recent data (e.g., `14days`, `48hr`) |
| `--start-date` | date | *(empty)* | Start date for analysis (`YYYY-MM-DD`) |
| `--end-date` | date | *(empty)* | End date for analysis (`YYYY-MM-DD`) |
| `--output-report` | path | *(empty)* | Path to save analysis report (JSON) |

### Duration Format

The following duration formats are supported:

| Format | Example | Description |
|--------|---------|-------------|
| Plain number | `30` | Seconds |
| Seconds | `30sec` | 30 seconds |
| Minutes | `5min` | 5 minutes (300 seconds) |
| Hours | `1hr` | 1 hour (3600 seconds) |
| Days | `14days` | 14 days (1,209,600 seconds) |

---

## Collector Mode

### Basic Collection

```bash
# Collect BTC, ETH, SOL prices every 30 seconds
python correlation_tracker.py --coins BTC,ETH,SOL --interval 30

# Collect for a specific duration
python correlation_tracker.py --coins BTC,ETH,SOL --interval 30 --duration 6hr

# Collect with 5-minute intervals
python correlation_tracker.py --coins BTC,ETH,TAO --interval 5min
```

### Auto-Search for Unknown Coins

By default, unknown coin symbols are automatically looked up via CoinGecko API:

```bash
# ONDO will be auto-discovered
python correlation_tracker.py --coins BTC,ONDO --interval 30
```

Output:
```
[COINGECKO] Searching for unknown symbol: ONDO
[COINGECKO] Found: ONDO -> ondo-finance (Ondo)
[COINGECKO] Added to runtime cache: ONDO -> ondo-finance
```

Disable auto-search:
```bash
python correlation_tracker.py --coins BTC,ETH --interval 30 --no-auto-search
```

### Data Storage

Data is stored in JSONL files organized by date and 6-hour time windows:

```
correlation_data/
├── 2026-05-04/
│   ├── prices_00-06.jsonl
│   ├── prices_06-12.jsonl
│   ├── prices_12-18.jsonl
│   └── prices_18-24.jsonl
├── 2026-05-05/
│   ├── prices_00-06.jsonl
│   └── ...
```

### Record Format

Each line in a JSONL file contains:
```json
{
  "symbol": "BTC",
  "timestamp": "2026-05-04T12:30:45.123456+00:00",
  "source": "coingecko",
  "price": 67234.56,
  "price_change_pct": 0.15,
  "collection_latency_ms": 245,
  "record_sequence": 1234
}
```

---

## Analyzer Mode

### Discovery Mode

Find all significant leading indicator pairs in the data:

```bash
python correlation_tracker.py --analyze --data-dir ./correlation_data

# With minimum confidence threshold
python correlation_tracker.py --analyze --min-confidence 0.7

# Filter to specific leader/follower candidates
python correlation_tracker.py --analyze \
    --leader-candidates BTC,ETH \
    --follower-candidates SOL,TAO,RENDER
```

### Specific Pair Analysis

Analyze a specific leader-follower relationship:

```bash
python correlation_tracker.py --analyze \
    --leader BTC \
    --follower ETH \
    --data-dir ./correlation_data

# Save report to file
python correlation_tracker.py --analyze \
    --leader BTC \
    --follower ETH \
    --output-report ./btc_eth_analysis.json
```

### Date Filtering

Analyze only recent data:

```bash
# Last 14 days
python correlation_tracker.py --analyze --recent 14days

# Last 48 hours
python correlation_tracker.py --analyze --recent 48hr

# Specific date range
python correlation_tracker.py --analyze \
    --start-date 2026-04-21 \
    --end-date 2026-05-05
```

### Custom Lag Range

```bash
# Test lags from 0 to 5 minutes
python correlation_tracker.py --analyze \
    --leader BTC \
    --follower ETH \
    --lag-range 0-5min

# Test lags from 1 minute to 1 hour
python correlation_tracker.py --analyze --lag-range 1min-1hr
```

---

## Analysis Methodology

The analyzer applies 5 statistical tests to each pair:

### Test 1: Data Validation
- Checks minimum sample count (default: 500)
- Aligns time series by timestamp
- **Threshold:** ≥500 samples per coin

### Test 2: Cross-Correlation Analysis
- Tests correlation at various time lags
- Finds optimal positive lag (leader precedes follower)
- **Threshold:** |correlation| ≥ 0.3

### Test 3: Granger Causality
- Statistical test for predictive relationship
- Uses F-test (SSR)
- **Threshold:** p-value < 0.05

### Test 4: Rolling Correlation Stability
- Measures consistency over time
- Calculates standard deviation of rolling correlation
- **Threshold:** stability score > 0.70

### Test 5: Confidence Score Calculation

Weighted combination of factors:

| Factor | Weight | Calculation |
|--------|--------|-------------|
| Correlation Strength | 30% | |correlation| |
| Statistical Significance | 25% | 1 - p_value |
| Relationship Stability | 20% | 1 - std_dev |
| Sample Adequacy | 15% | min(1, samples/1000) |
| Lag Consistency | 10% | correlation_improvement |

**Confidence Levels:**

| Score | Level | Actionable? |
|-------|-------|-------------|
| 0.0 - 0.3 | Low | No |
| 0.3 - 0.5 | Medium | With caution |
| 0.5 - 0.7 | High | Yes |
| 0.7 - 1.0 | Very High | Yes |

---

## Output Format

### Console Output

The analyzer outputs detailed test results:

```
================================================================================
                    ANALYSIS SUMMARY REPORT
================================================================================

Pair: BTC → ETH
--------------------------------------------------------------------------------

  TEST 1: Data Validation
  ├─ Leader samples:    1000
  ├─ Follower samples:  1000
  ├─ Minimum required:  500
  └─ RESULT: PASS ✓
     Reason: Sufficient samples available

  TEST 2: Cross-Correlation Analysis
  ├─ Lag range tested:  -10 to 10 periods
  ├─ Correlation at lag=0:      0.6500
  ├─ Correlation at optimal:    0.7200 (at lag=1, 30s)
  ├─ Improvement over zero-lag: +0.0700 (10.8%)
  └─ RESULT: PASS ✓
     Reason: Positive lag correlation found, leader precedes follower

  TEST 3: Granger Causality
  ├─ Test type:         ssr_ftest
  ├─ P-value:           0.0030
  ├─ Significance threshold: 0.05
  └─ RESULT: PASS ✓
     Reason: p=0.0030 < 0.05, statistically significant predictive relationship

  TEST 4: Rolling Correlation Stability
  ├─ Window size:       120 periods
  ├─ Mean correlation:  0.6800
  ├─ Std deviation:     0.1500
  ├─ Stability score:   0.8500
  ├─ Stability threshold: 0.70
  └─ RESULT: PASS ✓
     Reason: Stability 0.85 > 0.70 threshold, correlation is consistent

  TEST 5: Confidence Score Calculation
  ├─ Factor breakdown:
  │   ├─ correlation_strength: 0.7200 × 0.30 = 0.2160
  │   ├─ statistical_significance: 0.9970 × 0.25 = 0.2493
  │   ├─ relationship_stability: 0.8500 × 0.20 = 0.1700
  │   ├─ sample_adequacy: 0.9850 × 0.15 = 0.1478
  │   └─ lag_consistency: 0.0700 × 0.10 = 0.0070
  ├─ Total confidence score: 0.7901
  ├─ Confidence level: VERY_HIGH
  └─ RESULT: PASS ✓
     Reason: Score 0.79 indicates very_high confidence

--------------------------------------------------------------------------------
  FINAL CONCLUSION: BTC is a STRONG leading indicator for ETH
  ├─ Optimal lag: 30 seconds
  ├─ Correlation: 0.7200
  ├─ Confidence: 0.7901 (very_high)
  └─ Recommendation: Strong leading indicator (lag=30s, corr=0.72)
================================================================================
```

### JSON Output

Save detailed results to JSON:

```bash
python correlation_tracker.py --analyze --leader BTC --follower ETH --output-report ./report.json
```

---

## Configuration File

Generate a default configuration file:

```bash
python correlation_tracker.py --generate-config
```

Creates `correlation_tracker_config.yaml`:

```yaml
collector:
  interval_seconds: 30
  output_dir: ./correlation_data
  source: coingecko

analyzer:
  min_confidence: 0.6
  min_samples: 500
  lag_multiplier: 10

coins:
  - BTC
  - ETH
  - SOL
  - TAO
```

Use configuration file:

```bash
python correlation_tracker.py --config correlation_tracker_config.yaml
```

---

## Environment Variables

### API Keys

| Variable | Required | Description |
|----------|----------|-------------|
| `COINGECKO_API_KEY` | No (recommended) | CoinGecko Pro API key for higher rate limits |

### Rate Limiting

Without API key: ~10 requests/minute
With Pro API key: ~500 requests/minute

---

## APIs and Services

### CoinGecko API

**Purpose:** Fetch cryptocurrency price data

**Authentication:** Optional `COINGECKO_API_KEY` for Pro tier

**Endpoints Used:**
- `/simple/price` - Get current prices for multiple coins
- `/search` - Search for coin by symbol (auto-discovery)

**Rate Limits:**
- Free tier: 10-30 calls/minute
- Pro tier: 500+ calls/minute

**Minimum Interval:** 30 seconds recommended (6 seconds between requests)

---

## Directory Structure

```
tradingbot/
├── correlation_tracker.py              # Main entry point
├── correlation_tracker_config.yaml     # Configuration file
├── coingeckoutil.py                    # CoinGecko API utilities
├── correlation_data/                   # Default data directory
│   ├── 2026-05-04/
│   │   ├── prices_00-06.jsonl
│   │   ├── prices_06-12.jsonl
│   │   └── ...
│   └── 2026-05-05/
│       └── ...
├── requirements_correlation_tracker.txt
├── CORRELATION_HISTORY_TRACKER.md      # Design document
└── CORRELATION_HISTORY_OPERATIONS_MANUAL.md
```

---

## Quick Start Examples

### Start collecting data
```bash
python correlation_tracker.py --coins BTC,ETH,SOL,TAO --interval 30 --duration 24hr
```

### Check if BTC leads ETH
```bash
python correlation_tracker.py --analyze --leader BTC --follower ETH
```

### Discover all leading pairs
```bash
python correlation_tracker.py --analyze --min-confidence 0.6
```

### Analyze recent data only
```bash
python correlation_tracker.py --analyze --recent 7days
```

### Save report to file
```bash
python correlation_tracker.py --analyze --leader BTC --follower SOL --output-report ./analysis.json
```

### Use configuration file
```bash
python correlation_tracker.py --config ./my_config.yaml
```

---

## Troubleshooting

### Unknown Coin Symbol
```
[WARNING] Unknown coin symbols (will be skipped): ['XYZ']
```
**Solution:** Enable auto-search (default) or add coin to `coingeckoutil.py` SYMBOL_TO_ID mapping.

### Insufficient Samples
```
[WARNING] Insufficient samples for BTC->ETH: leader=100, follower=100, required=500
```
**Solution:** Collect more data or reduce `--min-samples` threshold.

### Rate Limit Hit
```
[COINGECKO] Request error: 429 Too Many Requests
```
**Solution:** 
- Increase collection interval (minimum 30 seconds)
- Use CoinGecko Pro API key
- Reduce number of coins per request

### No JSONL Files Found
```
[WARNING] No JSONL files found in ./correlation_data
```
**Solution:** Run collector first to generate data files.

---

## Dependencies

Install required packages:
```bash
pip install -r requirements_correlation_tracker.txt
```

**Required:**
- `numpy>=1.21.0`
- `pandas>=1.3.0`
- `requests>=2.25.0`
- `statsmodels>=0.13.0`
- `pyyaml>=6.0`

---

## Important Warnings

⚠️ **Correlation does NOT imply causation**

⚠️ **Past leading indicators may NOT remain so in the future**

⚠️ **Results should be one input among many for trading decisions**

⚠️ **Market conditions change - re-analyze regularly**

---

## Failure Reason Codes

When a pair fails analysis, one of these codes is assigned:

| Code | Description |
|------|-------------|
| `INSUFFICIENT_SAMPLES` | Not enough data points for analysis |
| `WEAK_CORRELATION` | Correlation < 0.3 at all lags |
| `NO_POSITIVE_LAG` | Best correlation at zero or negative lag |
| `GRANGER_NOT_SIGNIFICANT` | p-value ≥ 0.05, no predictive relationship |
| `UNSTABLE_RELATIONSHIP` | Correlation varies too much over time |
| `LOW_CONFIDENCE` | Combined confidence score below threshold |
| `REVERSE_CAUSALITY` | Follower actually leads leader |
