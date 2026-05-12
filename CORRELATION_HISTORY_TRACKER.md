# Correlation History Tracker

## Overview

A system for collecting intraday price history and analyzing correlations between cryptocurrency pairs to identify **leading indicators** - coins whose price movements predictably precede another coin's movement.

### Motivation

- Commercial platforms (TradingView, etc.) charge for intraday historical data
- Building our own history allows unlimited analysis without API costs
- Custom data collection enables tracking of specific metrics we care about
- Self-collected data can include metadata not available from commercial sources

### System Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CORRELATION HISTORY TRACKER                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐         ┌─────────────────────────────────┐   │
│  │   DATA COLLECTOR    │         │         HISTORY FILES           │   │
│  │                     │         │                                 │   │
│  │  • Polls prices     │────────▶│  • JSON/CSV/Parquet            │   │
│  │  • Every N seconds  │         │  • Per-coin or unified         │   │
│  │  • Multiple coins   │         │  • Timestamped records         │   │
│  │  • Candlestick data │         │  • Rotated by date             │   │
│  └─────────────────────┘         └─────────────────────────────────┘   │
│                                              │                          │
│                                              ▼                          │
│                                  ┌─────────────────────────────────┐   │
│                                  │         ANALYZER                │   │
│                                  │                                 │   │
│                                  │  Mode A: Discovery              │   │
│                                  │  • Scan all pairs               │   │
│                                  │  • Find leading indicators      │   │
│                                  │                                 │   │
│                                  │  Mode B: Specific Pair          │   │
│                                  │  • Check BTC → ETH correlation  │   │
│                                  │  • Confidence score output      │   │
│                                  └─────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Data Collector Program

### Purpose

Continuously collect price and market data for specified coins at regular intervals, storing in a format suitable for correlation analysis.

### CLI Interface

```bash
# Basic usage - collect price data every 30 seconds (MVP)
python correlation_tracker.py \
    --coins BTC,ETH,SOL,TAO,wTAO \
    --interval 30 \
    --output-dir ./correlation_data

# With shorter interval (warning issued but allowed)
python correlation_tracker.py \
    --coins BTC,ETH,SOL \
    --interval 15 \
    --output-dir ./correlation_data
# Warning: Interval <30s may hit CoinGecko rate limits

# Run analyzer on collected data (specific pair)
python correlation_tracker.py \
    --analyze \
    --leader BTC \
    --follower ETH \
    --data-dir ./correlation_data

# Run analyzer in discovery mode (all pairs)
python correlation_tracker.py \
    --analyze \
    --data-dir ./correlation_data \
    --min-confidence 0.6
```

### Configuration File Alternative

```yaml
# correlation_tracker_config.yaml
collector:
  interval_seconds: 30          # Default, warn if <30
  output_dir: ./correlation_data
  source: coingecko             # MVP: CoinGecko only

coins:
  - BTC
  - ETH
  - SOL
  - TAO
  - wTAO
  - RENDER

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
```

### Data Record Schema

Each record collected should contain:

```python
@dataclass
class PriceRecord:
    # Core identifiers
    symbol: str                    # e.g., "BTC"
    timestamp: datetime            # UTC timestamp
    source: str                    # e.g., "coinbase", "jupiter"
    
    # Price data
    price: float                   # Current spot price in USD
    bid_price: float               # Best bid
    ask_price: float               # Best ask
    spread: float                  # ask - bid
    spread_pct: float              # spread / mid_price * 100
    
    # Volume data (optional)
    volume_24h: Optional[float]    # 24h trading volume
    volume_1h: Optional[float]     # 1h trading volume (if available)
    
    # Candlestick data (for the interval)
    open: Optional[float]          # Opening price of interval
    high: Optional[float]          # High during interval
    low: Optional[float]           # Low during interval
    close: Optional[float]         # Closing price (same as price)
    
    # Derived metrics
    price_change_pct: Optional[float]  # Change since last record
    volatility_1h: Optional[float]     # Rolling 1h volatility
    
    # Metadata
    collection_latency_ms: int     # Time to fetch this data
    record_sequence: int           # Sequential record number
```

### Output File Format Options

#### Option A: JSON Lines (JSONL)

```json
{"symbol":"BTC","timestamp":"2026-05-04T11:00:00Z","price":67234.50,"bid":67234.00,"ask":67235.00,"volume_24h":12345678901,"source":"coinbase"}
{"symbol":"ETH","timestamp":"2026-05-04T11:00:00Z","price":3456.78,"bid":3456.50,"ask":3457.00,"volume_24h":5678901234,"source":"coinbase"}
{"symbol":"BTC","timestamp":"2026-05-04T11:00:30Z","price":67240.00,"bid":67239.50,"ask":67240.50,"volume_24h":12345678950,"source":"coinbase"}
```

**Pros:** Human-readable, easy to append, streamable
**Cons:** Larger file size, slower to parse for large datasets

#### Option B: CSV

```csv
symbol,timestamp,price,bid,ask,volume_24h,source
BTC,2026-05-04T11:00:00Z,67234.50,67234.00,67235.00,12345678901,coinbase
ETH,2026-05-04T11:00:00Z,3456.78,3456.50,3457.00,5678901234,coinbase
BTC,2026-05-04T11:00:30Z,67240.00,67239.50,67240.50,12345678950,coinbase
```

**Pros:** Universal compatibility, Excel-friendly, compact
**Cons:** No nested data, type inference issues

#### Option C: Parquet (Recommended for Large Datasets)

Binary columnar format optimized for analytics.

**Pros:** Compressed, fast queries, schema enforcement, excellent for pandas
**Cons:** Not human-readable, requires library to read

#### Option D: SQLite Database

```sql
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    price REAL NOT NULL,
    bid REAL,
    ask REAL,
    volume_24h REAL,
    source TEXT,
    INDEX idx_symbol_timestamp (symbol, timestamp)
);
```

**Pros:** Queryable, ACID guarantees, built-in indexing
**Cons:** Single-writer limitation, file locking

### File Rotation Strategy

```
correlation_data/
├── 2026-05-04/
│   ├── prices_00-06.jsonl
│   ├── prices_06-12.jsonl
│   ├── prices_12-18.jsonl
│   └── prices_18-24.jsonl
├── 2026-05-05/
│   └── prices_00-06.jsonl
└── metadata.json
```

### Error Handling

| Scenario | Behavior |
|----------|----------|
| API timeout | Retry 3x with exponential backoff, log gap |
| API rate limit | Pause collection, resume when allowed |
| Missing coin data | Log warning, continue with available coins |
| Disk full | Alert, pause collection, attempt cleanup |
| Network outage | Buffer in memory (limited), resume when connected |

### Data Quality Markers

```python
@dataclass
class DataQualityInfo:
    gap_detected: bool           # True if previous record missing
    gap_duration_seconds: int    # Duration of gap
    stale_data: bool            # True if data older than expected
    partial_collection: bool    # True if some coins failed
    failed_symbols: List[str]   # Which symbols failed
```

---

## Part 2: Analyzer Program

### Purpose

Analyze collected price history to identify correlations and leading indicators between coin pairs.

### Modes of Operation

#### Mode A: Discovery Mode

Scan all possible pairs in the dataset to find leading indicator relationships.

```bash
# Discover all leading indicator pairs (MVP)
python correlation_tracker.py \
    --analyze \
    --data-dir ./correlation_data \
    --min-confidence 0.6 \
    --output-report ./correlation_report.json

# Discovery with filters
python correlation_tracker.py \
    --analyze \
    --data-dir ./correlation_data \
    --leader-candidates BTC,ETH \
    --follower-candidates SOL,TAO,wTAO \
    --min-samples 500
```

#### Mode B: Specific Pair Mode

Check a specific coin pair for leading indicator relationship.

```bash
# Check if BTC leads ETH
python correlation_tracker.py \
    --analyze \
    --leader BTC \
    --follower ETH \
    --data-dir ./correlation_data \
    --output-report ./btc_eth_correlation.json

# Check with specific lag range
python correlation_tracker.py \
    --analyze \
    --leader BTC \
    --follower SOL \
    --lag-range 0-300 \
    --data-dir ./correlation_data

# Only analyze recent data (last 14 days)
python correlation_tracker.py \
    --analyze \
    --recent 14days \
    --data-dir ./correlation_data

# Analyze specific date range
python correlation_tracker.py \
    --analyze \
    --start-date 2026-04-21 \
    --end-date 2026-05-05 \
    --data-dir ./correlation_data

# Combine recent filter with specific pair
python correlation_tracker.py \
    --analyze \
    --leader BTC \
    --follower ETH \
    --recent 7days
```

#### Date Filtering Options

| Parameter | Format | Description |
|-----------|--------|-------------|
| `--recent` | Duration string | Only analyze data from the last N time period |
| `--start-date` | `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` | Start of date range (UTC) |
| `--end-date` | `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` | End of date range (UTC) |

**Duration formats for `--recent`:**
- `6hr` - last 6 hours
- `48hr` - last 48 hours  
- `7days` - last 7 days
- `14days` - last 14 days

**Precedence:** If both `--recent` and explicit date range are provided, `--recent` takes precedence.

### Analysis Techniques

The analyzer applies multiple statistical techniques in a specific order to identify and validate leading indicator relationships. Each technique contributes to a composite confidence score.

---

### Detailed Analysis Methodology

#### Order of Operations

The analyzer processes each candidate pair through the following pipeline:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LEADING INDICATOR DETECTION PIPELINE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Step 1: DATA VALIDATION                                                    │
│  ├─ Check minimum sample requirement (default: 500 samples)                 │
│  ├─ Align time series by timestamp                                          │
│  └─ If insufficient data → SKIP PAIR                                        │
│                          ↓                                                  │
│  Step 2: CROSS-CORRELATION ANALYSIS                                         │
│  ├─ Calculate correlation at lags from -N to +N periods                     │
│  ├─ Find optimal positive lag (leader leads follower)                       │
│  └─ Record: optimal_lag, correlation_at_optimal, correlation_at_zero        │
│                          ↓                                                  │
│  Step 3: GRANGER CAUSALITY TEST                                             │
│  ├─ Test if leader helps predict follower                                   │
│  ├─ Threshold: p-value < 0.05 for significance                              │
│  └─ Record: p-value, is_significant (boolean)                               │
│                          ↓                                                  │
│  Step 4: ROLLING CORRELATION STABILITY                                      │
│  ├─ Calculate correlation in sliding windows (default: 120 periods)         │
│  ├─ Compute standard deviation of rolling correlation                       │
│  ├─ Stability score = 1 - std_dev                                           │
│  └─ Threshold: stability > 0.7 for "stable relationship"                    │
│                          ↓                                                  │
│  Step 5: CONFIDENCE SCORE CALCULATION                                       │
│  ├─ Weighted combination of all factors (see below)                         │
│  ├─ Classify into confidence levels                                         │
│  └─ Generate recommendation                                                 │
│                          ↓                                                  │
│  Step 6: FILTER BY MINIMUM CONFIDENCE                                       │
│  ├─ Discovery mode: filter pairs by --min-confidence (default: 0.6)         │
│  └─ Output significant pairs in ranked order                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

#### Step 1: Data Validation

**Purpose:** Ensure sufficient data quality before analysis.

| Check | Threshold | Action if Failed |
|-------|-----------|------------------|
| Minimum samples per coin | 500 (configurable via `--min-samples`) | Skip pair with warning |
| Aligned sample count | ≥ 10 samples after timestamp alignment | Return no result |
| Granger test minimum | 3× max_lag samples | Skip Granger test |

---

#### Step 2: Cross-Correlation Analysis

**Purpose:** Find the time lag at which leader movements best predict follower movements.

**Algorithm:**
1. Convert raw prices to percentage returns: `returns = pct_change() × 100`
2. Align leader and follower return series by timestamp (inner join)
3. Normalize both series: `(x - mean) / std`
4. For each lag from `-max_lag` to `+max_lag`:
   - Positive lag: leader leads follower by N periods
   - Negative lag: leader lags behind follower
   - Zero lag: simultaneous movement
5. Calculate Pearson correlation at each lag
6. **Key output:** Find the **positive lag** with highest absolute correlation

**Thresholds and Interpretation:**

| Correlation (absolute) | Interpretation |
|------------------------|----------------|
| 0.0 - 0.3 | Weak/No relationship |
| 0.3 - 0.5 | Moderate relationship |
| 0.5 - 0.7 | Strong relationship |
| 0.7 - 1.0 | Very strong relationship |

**Lag Range Calculation:**
- Default: `max_lag = lag_multiplier × 1` (10 periods at 30s = 5 minutes)
- Or specified via `--lag-range` (e.g., `0-5min`, `1min-1hr`)

---

#### Step 3: Granger Causality Test

**Purpose:** Statistically test whether past values of the leader help predict future values of the follower beyond what the follower's own past values predict.

**Algorithm:**
1. Use statsmodels `grangercausalitytests` function
2. Test lags 1 through `max_lag` (default: 5)
3. Use F-test (SSR F-test) for significance
4. Take minimum p-value across all tested lags

**Hypothesis:**
- **Null hypothesis (H₀):** Leader does NOT Granger-cause follower
- **Alternative (H₁):** Leader DOES Granger-cause follower

**Thresholds:**

| P-value | Interpretation | `granger_causality_significant` |
|---------|----------------|--------------------------------|
| p < 0.05 | Statistically significant | `True` |
| p ≥ 0.05 | Not significant | `False` |

**Important:** Granger causality ≠ true causation. It only indicates predictive relationship.

---

#### Step 4: Rolling Correlation Stability

**Purpose:** Assess whether the correlation relationship is consistent over time or fluctuates.

**Algorithm:**
1. Calculate rolling correlation with window size (default: 120 periods = 1 hour at 30s)
2. Compute standard deviation of the rolling correlation series
3. **Stability score:** `1.0 - min(1.0, std_dev)`

**Thresholds:**

| Stability Score | Interpretation | `stable_relationship` |
|-----------------|----------------|----------------------|
| ≥ 0.7 | Stable - relationship is consistent | `True` |
| < 0.7 | Unstable - relationship varies over time | `False` |

**Why it matters:** A high correlation that fluctuates wildly is less reliable for trading signals.

---

#### Step 5: Confidence Score Calculation

**Purpose:** Combine all factors into a single actionable score.

**Formula:**

```
confidence_score = Σ (factor_i × weight_i)
```

| Factor | Weight | Calculation | Range |
|--------|--------|-------------|-------|
| **Correlation Strength** | 0.30 | `abs(correlation_at_optimal_lag)` | 0.0 - 1.0 |
| **Statistical Significance** | 0.25 | `1.0 - granger_pvalue` | 0.0 - 1.0 |
| **Relationship Stability** | 0.20 | `1.0 - std_dev(rolling_corr)` | 0.0 - 1.0 |
| **Sample Adequacy** | 0.15 | `min(1.0, num_samples / 1000)` | 0.0 - 1.0 |
| **Lag Consistency** | 0.10 | `abs(corr_optimal) - abs(corr_zero)` | 0.0 - 1.0 |

**Weight Rationale:**

| Factor | Rationale |
|--------|-----------|
| **Correlation Strength (30%)** | The core metric. Higher correlation means stronger predictive relationship. Given highest weight as it directly measures how much leader movement predicts follower movement. |
| **Statistical Significance (25%)** | Granger causality tests whether the relationship is statistically real vs. coincidental. High weight because without significance, correlation could be spurious. |
| **Relationship Stability (20%)** | A correlation that fluctuates wildly over time is unreliable for trading. Moderate weight because even strong correlations are useless if they're inconsistent. |
| **Sample Adequacy (15%)** | More data = more reliable conclusions. Lower weight because it's a quality metric rather than a relationship metric. Saturates at 1000 samples. |
| **Lag Consistency (10%)** | Measures if lagged correlation actually improves over zero-lag. Lowest weight because it's a secondary indicator - confirms the "leading" nature but doesn't measure strength. |

**Design Philosophy:**
- **Relationship quality > Data quality** - The top 3 factors (75% total) measure the relationship itself
- **Statistical rigor matters** - Granger significance gets 25% to prevent false positives
- **Stability = tradability** - An unstable correlation can't be reliably traded
- **Diminishing returns on data** - More data helps but caps out (1000 samples is sufficient)
- **Lag improvement is confirmatory** - It validates the "leading" hypothesis but isn't the main signal

**Signal Strength Classification:**

| Confidence Score | Classification |
|-----------------|----------------|
| ≥ 0.70 | **STRONG** |
| 0.50 - 0.69 | **MODERATE** |
| < 0.50 | **WEAK** |

**Confidence Levels:**

| Score Range | Level | Actionable? | Recommendation |
|-------------|-------|-------------|----------------|
| 0.0 - 0.3 | `low` | No | No reliable relationship detected |
| 0.3 - 0.5 | `medium` | With caution | Weak leading indicator, use with caution |
| 0.5 - 0.7 | `high` | Yes | Moderate leading indicator |
| 0.7 - 1.0 | `very_high` | Yes | Strong leading indicator |

---

#### Step 6: Discovery Mode Filtering

**Purpose:** In discovery mode, filter to only significant pairs.

**Default threshold:** `--min-confidence 0.6` (corresponds to "high" confidence level)

**Output ranking:** Pairs sorted by confidence score (descending)

---

#### Step 7: Directional Analysis (UP vs DOWN)

**Purpose:** Analyze correlations separately for upward vs downward leader movements to detect asymmetric behavior.

**Motivation:** Markets often exhibit directional asymmetry:
- Fear (drops) may propagate faster than greed (rallies)
- Correlation strength may differ by direction
- Optimal lag may vary based on whether leader is rising or falling

**Algorithm:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DIRECTIONAL CORRELATION ANALYSIS                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Input: Leader returns series, Follower returns series                      │
│                          ↓                                                  │
│  Step 7a: SPLIT BY DIRECTION                                                │
│  ├─ UP dataset: samples where leader_return > 0                             │
│  ├─ DOWN dataset: samples where leader_return < 0                           │
│  └─ Each dataset includes corresponding follower returns at same timestamps │
│                          ↓                                                  │
│  Step 7b: ANALYZE EACH DIRECTION SEPARATELY                                 │
│  ├─ For UP dataset:                                                         │
│  │   ├─ Cross-correlation at various lags                                   │
│  │   ├─ Find optimal_lag_up                                                 │
│  │   ├─ Calculate correlation_up                                            │
│  │   └─ Granger test → significance_up                                      │
│  │                                                                          │
│  └─ For DOWN dataset:                                                       │
│      ├─ Cross-correlation at various lags                                   │
│      ├─ Find optimal_lag_down                                               │
│      ├─ Calculate correlation_down                                          │
│      └─ Granger test → significance_down                                    │
│                          ↓                                                  │
│  Step 7c: COMPARE DIRECTIONS                                                │
│  ├─ Lag difference: |optimal_lag_up - optimal_lag_down|                     │
│  ├─ Correlation difference: |correlation_up| - |correlation_down|          │
│  ├─ Significance comparison: both significant? one only?                    │
│  └─ Generate directional_asymmetry_score                                    │
│                          ↓                                                  │
│  Step 7d: GENERATE DIRECTIONAL RECOMMENDATIONS                              │
│  ├─ If only DOWN significant → "Trade only on leader drops"                 │
│  ├─ If only UP significant → "Trade only on leader rises"                   │
│  ├─ If DOWN stronger → "Higher confidence on leader drops"                  │
│  └─ If similar → "Symmetric behavior, trade both directions"                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Output Metrics:**

| Metric | Description |
|--------|-------------|
| `correlation_up` | Correlation when leader moves up |
| `correlation_down` | Correlation when leader moves down |
| `optimal_lag_up` | Best lag for upward movements |
| `optimal_lag_down` | Best lag for downward movements |
| `significance_up` | Granger p-value for UP dataset |
| `significance_down` | Granger p-value for DOWN dataset |
| `samples_up` | Number of upward movement samples |
| `samples_down` | Number of downward movement samples |
| `asymmetry_score` | Degree of directional difference (0-1) |

**Asymmetry Score Calculation:**

```
asymmetry_score = (
    0.4 × |correlation_up - correlation_down| +
    0.3 × (lag_difference / max_lag) +
    0.3 × significance_difference
)
```

Where:
- `lag_difference` = normalized difference in optimal lags
- `significance_difference` = 1 if only one direction significant, 0 if both or neither

**Interpretation:**

| Asymmetry Score | Interpretation | Trading Implication |
|-----------------|----------------|---------------------|
| 0.0 - 0.2 | Symmetric | Trade both directions equally |
| 0.2 - 0.5 | Moderate asymmetry | Favor stronger direction |
| 0.5 - 1.0 | Strong asymmetry | Consider single-direction trading |

**Example Output:**

```
Directional Analysis: TAO → WTAO
────────────────────────────────────────────────────────
Direction   | Samples | Correlation | Lag    | Granger p
────────────────────────────────────────────────────────
UP (rises)  |   412   |   -0.12     | 72s    | 0.18
DOWN (falls)|   388   |   -0.24     | 48s    | 0.02 ✓
────────────────────────────────────────────────────────
Asymmetry Score: 0.58 (Strong)

Recommendation: Trade primarily on TAO drops
├─ DOWN direction shows 2x stronger correlation
├─ DOWN direction is statistically significant (p=0.02)
├─ DOWN direction has faster response (48s vs 72s lag)
└─ UP direction is NOT significant (p=0.18)
```

**CLI Extension:**

```bash
# Enable directional analysis (on by default in discovery mode)
python correlation_tracker.py --analyze --directional

# Disable directional analysis for faster runs
python correlation_tracker.py --analyze --no-directional
```

**Minimum Samples per Direction:**

To ensure statistical validity, each direction requires minimum samples:
- Default: `min_directional_samples = 100`
- If either direction has insufficient samples, directional analysis is skipped with warning

---

### Example: Complete Analysis Flow

```
Input: Analyze BTC → ETH with 1000 samples at 30s intervals

Step 1: Data Validation
  ├─ BTC samples: 1000 ✓
  ├─ ETH samples: 1000 ✓
  └─ Aligned samples: 985 ✓

Step 2: Cross-Correlation
  ├─ Test lags: -10 to +10 periods
  ├─ Optimal positive lag: +1 period (30 seconds)
  ├─ Correlation at lag=+1: 0.72
  └─ Correlation at lag=0: 0.65

Step 3: Granger Causality
  ├─ F-test p-value: 0.003
  └─ Significant: YES (p < 0.05)

Step 4: Rolling Stability
  ├─ Window: 120 periods
  ├─ Std dev of rolling corr: 0.15
  └─ Stability score: 0.85 (stable)

Step 5: Confidence Score
  ├─ Correlation strength:     0.72 × 0.30 = 0.216
  ├─ Statistical significance: 0.997 × 0.25 = 0.249
  ├─ Relationship stability:   0.85 × 0.20 = 0.170
  ├─ Sample adequacy:          0.985 × 0.15 = 0.148
  ├─ Lag consistency:          0.07 × 0.10 = 0.007
  └─ TOTAL: 0.79 (very_high)

Result: BTC is a STRONG leading indicator for ETH
        Optimal lag: 30 seconds
        Confidence: 0.79 (very_high)
```

---

### Per-Test Statistics and Reasoning Report

At the end of each analysis run, the system should output a detailed breakdown showing the statistics and reasoning for each test applied to each pair. This provides transparency into why a pair was classified as a leading indicator or not.

#### Console Output Format

```
================================================================================
                         ANALYSIS SUMMARY REPORT
================================================================================

Pair: BTC → ETH
--------------------------------------------------------------------------------

  TEST 1: Data Validation
  ├─ Leader samples:    1000
  ├─ Follower samples:  1000
  ├─ Aligned samples:   985
  ├─ Minimum required:  500
  └─ RESULT: PASS ✓

  TEST 2: Cross-Correlation Analysis
  ├─ Lag range tested:  -10 to +10 periods (-300s to +300s)
  ├─ Correlation at lag=0:      0.65
  ├─ Correlation at optimal:    0.72 (at lag=+1, 30s)
  ├─ Improvement over zero-lag: +0.07 (10.8%)
  └─ RESULT: POSITIVE LAG CORRELATION FOUND ✓
     Reason: Optimal correlation occurs at positive lag, indicating leader precedes follower

  TEST 3: Granger Causality
  ├─ Test type:         F-test (SSR)
  ├─ Lags tested:       1-5
  ├─ Minimum p-value:   0.003 (at lag=2)
  ├─ Significance threshold: 0.05
  └─ RESULT: STATISTICALLY SIGNIFICANT ✓
     Reason: p=0.003 < 0.05, reject null hypothesis that leader does not predict follower

  TEST 4: Rolling Correlation Stability
  ├─ Window size:       120 periods (1 hour)
  ├─ Mean correlation:  0.68
  ├─ Std deviation:     0.15
  ├─ Stability score:   0.85
  ├─ Stability threshold: 0.70
  └─ RESULT: STABLE RELATIONSHIP ✓
     Reason: Stability score 0.85 > 0.70 threshold, correlation is consistent over time

  TEST 5: Confidence Score Calculation
  ├─ Factor breakdown:
  │   ├─ Correlation strength:     0.72 × 0.30 = 0.216
  │   ├─ Statistical significance: 0.997 × 0.25 = 0.249
  │   ├─ Relationship stability:   0.85 × 0.20 = 0.170
  │   ├─ Sample adequacy:          0.985 × 0.15 = 0.148
  │   └─ Lag consistency:          0.07 × 0.10 = 0.007
  ├─ Total confidence score: 0.79
  ├─ Confidence level: VERY_HIGH (0.7-1.0)
  └─ RESULT: HIGH CONFIDENCE LEADING INDICATOR ✓
     Reason: Score 0.79 exceeds 0.70 threshold for very_high confidence

  FINAL CONCLUSION: BTC is a STRONG leading indicator for ETH
  ├─ Optimal lag: 30 seconds
  ├─ Expected behavior: When BTC moves, ETH follows ~30s later with 0.72 correlation
  └─ Trading signal strength: STRONG

--------------------------------------------------------------------------------

Pair: SOL → TAO
--------------------------------------------------------------------------------

  TEST 1: Data Validation
  ├─ Leader samples:    1000
  ├─ Follower samples:  1000
  ├─ Aligned samples:   950
  ├─ Minimum required:  500
  └─ RESULT: PASS ✓

  TEST 2: Cross-Correlation Analysis
  ├─ Lag range tested:  -10 to +10 periods
  ├─ Correlation at lag=0:      0.25
  ├─ Correlation at optimal:    0.28 (at lag=+3, 90s)
  ├─ Improvement over zero-lag: +0.03 (12%)
  └─ RESULT: WEAK CORRELATION ⚠
     Reason: Optimal correlation 0.28 is below 0.30 threshold for meaningful relationship

  TEST 3: Granger Causality
  ├─ Test type:         F-test (SSR)
  ├─ Lags tested:       1-5
  ├─ Minimum p-value:   0.42 (at lag=3)
  ├─ Significance threshold: 0.05
  └─ RESULT: NOT SIGNIFICANT ✗
     Reason: p=0.42 > 0.05, cannot reject null hypothesis

  TEST 4: Rolling Correlation Stability
  ├─ Window size:       120 periods
  ├─ Mean correlation:  0.22
  ├─ Std deviation:     0.35
  ├─ Stability score:   0.65
  ├─ Stability threshold: 0.70
  └─ RESULT: UNSTABLE RELATIONSHIP ✗
     Reason: Stability score 0.65 < 0.70 threshold, correlation varies significantly over time

  TEST 5: Confidence Score Calculation
  ├─ Factor breakdown:
  │   ├─ Correlation strength:     0.28 × 0.30 = 0.084
  │   ├─ Statistical significance: 0.58 × 0.25 = 0.145
  │   ├─ Relationship stability:   0.65 × 0.20 = 0.130
  │   ├─ Sample adequacy:          0.95 × 0.15 = 0.143
  │   └─ Lag consistency:          0.03 × 0.10 = 0.003
  ├─ Total confidence score: 0.51
  ├─ Confidence level: HIGH (0.5-0.7)
  └─ RESULT: MARGINAL - USE WITH CAUTION ⚠
     Reason: Score 0.51 is above minimum but multiple tests showed weak results

  FINAL CONCLUSION: SOL is a WEAK leading indicator for TAO
  ├─ Optimal lag: 90 seconds
  ├─ Issues: Low correlation, Granger test failed, unstable relationship
  └─ Trading signal strength: WEAK - USE WITH CAUTION

================================================================================
                              SUMMARY
================================================================================

Total pairs analyzed: 6
├─ Strong indicators (confidence ≥ 0.7):   1  (BTC → ETH)
├─ Moderate indicators (0.5-0.7):          2  (ETH → SOL, BTC → TAO)
├─ Weak indicators (0.3-0.5):              1  (SOL → TAO)
└─ No relationship (<0.3):                 2  (TAO → BTC, SOL → ETH)

Tests failed breakdown:
├─ Cross-correlation weak:    2 pairs
├─ Granger not significant:   3 pairs
└─ Unstable relationship:     2 pairs

================================================================================
```

#### JSON Report Format

The detailed per-test statistics should also be included in the JSON output report:

```json
{
  "pair_analysis": {
    "leader": "BTC",
    "follower": "ETH",
    "tests": {
      "data_validation": {
        "passed": true,
        "leader_samples": 1000,
        "follower_samples": 1000,
        "aligned_samples": 985,
        "minimum_required": 500,
        "reason": "Sufficient samples available"
      },
      "cross_correlation": {
        "passed": true,
        "lag_range_periods": [-10, 10],
        "correlation_at_zero": 0.65,
        "correlation_at_optimal": 0.72,
        "optimal_lag_periods": 1,
        "optimal_lag_seconds": 30,
        "improvement_over_zero": 0.07,
        "reason": "Positive lag correlation found, leader precedes follower by 30s"
      },
      "granger_causality": {
        "passed": true,
        "test_type": "ssr_ftest",
        "lags_tested": [1, 2, 3, 4, 5],
        "p_values": {"1": 0.012, "2": 0.003, "3": 0.008, "4": 0.015, "5": 0.021},
        "min_p_value": 0.003,
        "min_p_value_lag": 2,
        "significance_threshold": 0.05,
        "reason": "p=0.003 < 0.05, statistically significant predictive relationship"
      },
      "rolling_stability": {
        "passed": true,
        "window_size": 120,
        "mean_correlation": 0.68,
        "std_deviation": 0.15,
        "stability_score": 0.85,
        "stability_threshold": 0.70,
        "reason": "Correlation is consistent over time (stability 0.85 > 0.70)"
      },
      "confidence_calculation": {
        "factors": {
          "correlation_strength": {"value": 0.72, "weight": 0.30, "contribution": 0.216},
          "statistical_significance": {"value": 0.997, "weight": 0.25, "contribution": 0.249},
          "relationship_stability": {"value": 0.85, "weight": 0.20, "contribution": 0.170},
          "sample_adequacy": {"value": 0.985, "weight": 0.15, "contribution": 0.148},
          "lag_consistency": {"value": 0.07, "weight": 0.10, "contribution": 0.007}
        },
        "total_score": 0.79,
        "confidence_level": "very_high",
        "reason": "All factors contribute positively, score 0.79 indicates strong reliability"
      },
      "directional_analysis": {
        "enabled": true,
        "up_direction": {
          "samples": 512,
          "correlation": 0.68,
          "optimal_lag_seconds": 35,
          "granger_p_value": 0.008,
          "significant": true
        },
        "down_direction": {
          "samples": 473,
          "correlation": 0.76,
          "optimal_lag_seconds": 25,
          "granger_p_value": 0.001,
          "significant": true
        },
        "asymmetry_score": 0.24,
        "asymmetry_level": "moderate",
        "stronger_direction": "down",
        "recommendation": "DOWN direction shows stronger correlation (0.76 vs 0.68) and faster lag (25s vs 35s)"
      }
    },
    "conclusion": {
      "is_leading_indicator": true,
      "strength": "strong",
      "optimal_lag_seconds": 30,
      "correlation": 0.72,
      "confidence": 0.79,
      "recommendation": "Strong leading indicator - BTC movements predict ETH ~30s later",
      "caveats": [],
      "directional_recommendation": "Both directions significant; DOWN slightly stronger"
    }
  }
}
```

#### Failure Reason Codes

When a test fails or a pair is rejected, include specific reason codes:

| Code | Reason | Description |
|------|--------|-------------|
| `INSUFFICIENT_SAMPLES` | Data validation failed | Not enough samples for analysis |
| `WEAK_CORRELATION` | Cross-correlation < 0.3 | No meaningful correlation at any lag |
| `GRANGER_NOT_SIGNIFICANT` | p-value ≥ 0.05 | No statistical evidence of prediction |
| `UNSTABLE_RELATIONSHIP` | Stability < 0.70 | Correlation varies too much over time |
| `LOW_CONFIDENCE` | Score < min_confidence | Combined factors too weak |

**Note:** If the optimal correlation is at a negative lag (meaning the specified "follower" actually leads the "leader"), the analyzer automatically swaps the roles and reports the correct direction. This is indicated in the output with "Roles swapped" in the caveats.

---

### Individual Technique Details

#### 1. Cross-Correlation Analysis

Measures correlation between leader's price change and follower's price change at various time lags.

```
Cross-Correlation: BTC → ETH

Lag (seconds)  |  Correlation  |  Significance
─────────────────────────────────────────────
    -60        |     0.12      |     Low
    -30        |     0.25      |     Medium
      0        |     0.85      |     High (simultaneous)
    +30        |     0.72      |     High ← BTC leads by 30s
    +60        |     0.45      |     Medium
    +90        |     0.20      |     Low

Interpretation: BTC price changes correlate most strongly with 
ETH price changes 30 seconds later → BTC is a leading indicator.
```

#### 2. Granger Causality Test

Statistical test to determine if one time series helps predict another.

```
Granger Causality: Does BTC "Granger-cause" SOL?

Null Hypothesis: BTC does NOT help predict SOL
Test Statistic: F = 15.7
P-value: 0.0003

Result: Reject null hypothesis (p < 0.05)
Conclusion: BTC movements help predict SOL movements
```

#### 3. Lead-Lag Analysis

Identify optimal lag where correlation is maximized.

```
Lead-Lag Analysis: BTC → TAO

Optimal lag: 45 seconds
Peak correlation at lag: 0.68
Correlation at lag=0: 0.42

Conclusion: TAO movements lag BTC by ~45 seconds
with moderate-high correlation (0.68)
```

#### 4. Rolling Correlation

Track how correlation changes over time (stability analysis).

```
Rolling Correlation: BTC → ETH (1-hour windows)

Time Window          |  Correlation  |  Stability
──────────────────────────────────────────────────
05-04 00:00-01:00   |     0.82      |   Stable
05-04 01:00-02:00   |     0.79      |   Stable
05-04 02:00-03:00   |     0.45      |   Unstable ← Event?
05-04 03:00-04:00   |     0.81      |   Stable

Average: 0.72    Std Dev: 0.17
```

### Output Report Schema

```python
@dataclass
class CorrelationReport:
    # Metadata
    generated_at: datetime
    data_range: Tuple[datetime, datetime]
    total_samples: int
    
    # Pair analysis
    leader_symbol: str
    follower_symbol: str
    
    # Core metrics
    optimal_lag_seconds: int
    correlation_at_optimal_lag: float
    correlation_at_zero_lag: float
    
    # Statistical tests
    granger_causality_pvalue: float
    granger_causality_significant: bool
    
    # Confidence assessment
    confidence_score: float          # 0.0 to 1.0
    confidence_level: str            # "low", "medium", "high", "very_high"
    confidence_factors: Dict[str, float]
    
    # Stability
    correlation_stability: float     # Std dev of rolling correlation
    stable_relationship: bool
    
    # Actionable insights
    recommendation: str
    trading_signal_strength: str
```

### Confidence Score Calculation

```
┌─────────────────────────────────────────────────────────────────┐
│                  CONFIDENCE SCORE FACTORS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Factor                          Weight    Score                │
│  ─────────────────────────────────────────────────              │
│  Correlation strength            0.30      |correlation|        │
│  Statistical significance        0.25      1 - p_value          │
│  Relationship stability          0.20      1 - std_dev          │
│  Sample size adequacy            0.15      min(1, n/1000)       │
│  Lag consistency                 0.10      lag_consistency      │
│  ─────────────────────────────────────────────────              │
│  TOTAL                           1.00      weighted_sum         │
│                                                                 │
│  Confidence Levels:                                             │
│  • 0.0 - 0.3: Low (not reliable)                               │
│  • 0.3 - 0.5: Medium (use with caution)                        │
│  • 0.5 - 0.7: High (actionable)                                │
│  • 0.7 - 1.0: Very High (strong signal)                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Discovery Mode Output

```json
{
  "discovery_report": {
    "generated_at": "2026-05-04T12:00:00Z",
    "data_range": ["2026-05-01T00:00:00Z", "2026-05-04T12:00:00Z"],
    "coins_analyzed": ["BTC", "ETH", "SOL", "TAO", "RENDER"],
    "pairs_tested": 20,
    "significant_pairs": [
      {
        "leader": "BTC",
        "follower": "ETH",
        "optimal_lag_seconds": 15,
        "correlation": 0.82,
        "confidence": 0.85,
        "recommendation": "Strong leading indicator"
      },
      {
        "leader": "BTC",
        "follower": "SOL",
        "optimal_lag_seconds": 30,
        "correlation": 0.71,
        "confidence": 0.72,
        "recommendation": "Moderate leading indicator"
      },
      {
        "leader": "ETH",
        "follower": "TAO",
        "optimal_lag_seconds": 45,
        "correlation": 0.58,
        "confidence": 0.55,
        "recommendation": "Weak leading indicator, use with caution"
      }
    ],
    "no_significant_relationship": [
      {"leader": "SOL", "follower": "RENDER", "reason": "Low correlation (0.12)"},
      {"leader": "TAO", "follower": "BTC", "reason": "Reverse causality detected"}
    ]
  }
}
```

---

## Part 3: Integration with Trading Bot

### How Correlation Data Feeds Trading Decisions

```
┌─────────────────────────────────────────────────────────────────┐
│              TRADING BOT INTEGRATION                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Collector runs continuously, building history               │
│                      ↓                                          │
│  2. Analyzer runs periodically (hourly/daily)                   │
│     Updates correlation_pairs.json                              │
│                      ↓                                          │
│  3. Trading bot loads correlation data at startup               │
│                      ↓                                          │
│  4. When BTC moves:                                             │
│     - Check: Is BTC a leader for any pairs?                     │
│     - If BTC → SOL with lag=30s, confidence=0.8:                │
│       → Predict SOL will move in ~30s                           │
│       → Prepare trade or alert                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Real-Time Signal Generation

```python
@dataclass
class LeadingIndicatorSignal:
    leader_symbol: str
    leader_price_change_pct: float
    leader_move_timestamp: datetime
    
    follower_symbol: str
    expected_follower_move_pct: float  # Predicted based on correlation
    expected_move_time: datetime       # Now + optimal_lag
    
    confidence: float
    correlation: float
    historical_accuracy: float         # Backtest accuracy
```

---

## Alternative Implementations

### Alternative A: In-Memory Time Series Database

Use a specialized time series database instead of flat files.

| Option | Pros | Cons |
|--------|------|------|
| **InfluxDB** | Purpose-built for time series, fast queries | External dependency, more complex |
| **TimescaleDB** | PostgreSQL extension, SQL queries | Requires PostgreSQL |
| **QuestDB** | Very fast, SQL support | Less mature |
| **Redis TimeSeries** | In-memory speed, simple | RAM-limited |

**Recommendation:** Start with flat files (JSONL/Parquet), migrate to InfluxDB if scale demands.

### Alternative B: Event-Driven Architecture

Instead of polling, use WebSocket streams for real-time data.

```
┌─────────────────────────────────────────────────────────────────┐
│                 EVENT-DRIVEN COLLECTOR                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Coinbase WebSocket ──┐                                         │
│  Binance WebSocket  ──┼──▶ Event Processor ──▶ History File    │
│  Jupiter WebSocket  ──┘         │                               │
│                                 ▼                               │
│                          Aggregator                             │
│                     (OHLCV per interval)                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:** Lower latency, no polling gaps
**Cons:** More complex, WebSocket management, reconnection handling

### Alternative C: Distributed Collection

For high-frequency collection across many coins.

```
┌─────────────────────────────────────────────────────────────────┐
│               DISTRIBUTED COLLECTOR                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Worker 1: BTC, ETH ──┐                                         │
│  Worker 2: SOL, TAO ──┼──▶ Message Queue ──▶ Aggregator        │
│  Worker 3: RENDER   ──┘    (Redis/Kafka)        │               │
│                                                 ▼               │
│                                          Central Storage        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:** Scalable, fault-tolerant, parallelized
**Cons:** Infrastructure overhead, complexity

### Alternative D: Hybrid Storage

Use different storage for different use cases.

| Use Case | Storage | Why |
|----------|---------|-----|
| Recent data (< 24h) | SQLite/Memory | Fast access for live analysis |
| Historical data (> 24h) | Parquet files | Compressed, batch analysis |
| Aggregated data | JSON reports | Human-readable summaries |

### Alternative E: Cloud-Based Collection

Use cloud functions for serverless collection.

```
AWS Lambda / GCP Cloud Functions
     │
     ▼
Triggered every N seconds
     │
     ▼
Fetch prices from APIs
     │
     ▼
Write to S3 / GCS / Cloud Storage
```

**Pros:** No server management, auto-scaling
**Cons:** Cold start latency, API costs, vendor lock-in

---

## Open Questions

### Data Collection

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | **Polling interval?** | A. 10 seconds (high resolution)<br>B. 30 seconds (balanced)<br>C. 60 seconds (low overhead) | **Parameter** - Default 30 seconds. Warn on <30s but don't prevent execution. |
| 2 | **Primary data source?** | A. Coinbase (reliable, limited coins)<br>B. CoinGecko (many coins, rate limited)<br>C. Multiple sources (redundancy) | **B (MVP)** - CoinGecko has broad coverage (e.g., both TAO and wTAO). |
| 3 | **Storage format?** | A. JSONL (simple)<br>B. Parquet (efficient)<br>C. SQLite (queryable)<br>D. Hybrid | **A (MVP)** - JSONL is simplest for automated analysis by our own tool. Single format avoids complexity of hybrid approach. |
| 4 | **How long to retain raw data?** | A. 7 days<br>B. 30 days<br>C. 90 days<br>D. Indefinite | **D (MVP)** - Indefinite retention, manual cleanup for now. |
| 5 | **Should we collect order book depth?** | A. Yes (richer signal)<br>B. No (simpler, smaller files) | **B (MVP)** - No order book depth initially. |

### Analysis

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 6 | **Minimum samples for confidence?** | A. 100<br>B. 500<br>C. 1000<br>D. Dynamic | **B (MVP)** - 500 samples (~4 hours at 30s intervals). |
| 7 | **Lag range to test?** | A. 0-60 seconds<br>B. 0-5 minutes<br>C. 0-15 minutes | **Parameter** - Default should scale with sampling interval (e.g., 10x interval). Configurable. |
| 8 | **How to handle market regime changes?** | A. Ignore (use all data)<br>B. Recency weighting<br>C. Regime detection | **A (MVP)** - Ignore regime changes, use all data for simplicity. |
| 9 | **Should analyzer run continuously?** | A. Yes (real-time updates)<br>B. No (batch, hourly/daily) | **User-invoked** - Analyzer triggered via `--analyze` flag. Run separately (command line or separate thread). User decides when to run. |
| 10 | **Correlation vs causation disclaimer?** | A. Just report numbers<br>B. Include warnings<br>C. Require user acknowledgment | **B** - Include warnings: (1) Correlation ≠ causation; (2) Output is confidence level that coin A is a leading indicator for coin B for the analyzed period; (3) **Past leading indicators may not remain so in the future.** |

### Integration

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 11 | **How to consume correlation data in trading bot?** | A. Load at startup<br>B. Watch for file changes<br>C. API endpoint | **Deferred** - Integration with trading bot deferred until after MVP. |
| 12 | **Should we auto-trade on leading indicator signals?** | A. Yes (full automation)<br>B. No (alerts only)<br>C. Configurable | **Deferred** - Decision deferred until after MVP. Initial goal is to determine if method can find leading indicators at all. |
| 13 | **How to handle conflicting signals?** | A. Strongest signal wins<br>B. Require consensus<br>C. User decides | **Deferred** - MVP goal is discovery of leading indicators, not trading integration. |

### Operational

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 14 | **Alerting on collection failures?** | A. Log only<br>B. Email/SMS<br>C. Configurable | **A (MVP)** - Log only. Analyzer should warn on data gaps (e.g., if analyzing 30s intervals and data is missing, warn user). |
| 15 | **Disk space management?** | A. Manual cleanup<br>B. Auto-rotate and compress<br>C. Cloud storage | **A (MVP)** - Manual cleanup for now. |
| 16 | **Should we deduplicate data?** | A. No (preserve raw)<br>B. Yes (save space) | **A** - Always preserve raw data. No deduplication even in analysis—each interval needs to determine if one coin predicts the other (including no price movement). |

---

## Implementation Roadmap

### Phase 1: MVP (Collector + Full Analyzer)

- [ ] Multi-coin price collection from CoinGecko
- [ ] JSONL output format (single format for simplicity)
- [ ] Configurable interval (default 30s, warn on <30s)
- [ ] `--analyze` flag for analyzer mode
- [ ] Basic cross-correlation analysis
- [ ] Granger causality tests
- [ ] Rolling correlation stability analysis
- [ ] Specific pair mode (`--leader`, `--follower`)
- [ ] Discovery mode (all pairs)
- [ ] Confidence scoring with warnings
- [ ] Data gap detection and warnings
- [ ] Basic error handling and logging

**MVP Goal:** Determine if this method can reliably find leading indicators.

### Phase 2: Post-MVP Enhancements

- [ ] Multiple data sources (Coinbase, etc.)
- [ ] Auto-rotate and compress old data
- [ ] **Non-price feature correlation:** Correlate characteristics of Coin A (e.g., candlestick patterns, volume spikes, volatility) with price movement in Coin B. Examples:
  - Does a large red candle in BTC predict SOL price drop?
  - Does volume spike in ETH predict TAO movement?
  - Does volatility increase in BTC lead to correlated moves in altcoins?

### Phase 3: Trading Bot Integration (Deferred)

- [ ] Integration with trading bot
- [ ] Real-time signal generation
- [ ] Auto-trade decisions
- [ ] Conflicting signal handling
- [ ] Alert system

### Phase 4: Scale + Optimize (Deferred)

- [ ] Parquet archival for long-term storage
- [ ] WebSocket streaming option
- [ ] Performance optimization
- [ ] Dashboard/visualization

---

## Alternative Data Source: CoinGecko Historical API (Evaluated, Deferred)

### Motivation

Collecting sufficient samples for large time interval analysis (e.g., 4-hour intervals) requires days of continuous data collection. CoinGecko's historical API could provide instant access to historical price data without waiting.

### CoinGecko Historical API Endpoints

| Endpoint | Resolution | Max Range | Free Tier |
|----------|------------|-----------|-----------|
| `/coins/{id}/market_chart` | Auto (5min-daily) | 365 days | ✓ |
| `/coins/{id}/market_chart/range` | Auto | Any with timestamps | ✓ |
| `/coins/{id}/ohlc` | 1-4hr candles | 90 days | ✓ |

### Granularity Limitations (Critical)

CoinGecko **auto-adjusts granularity** based on requested range:

| Requested Range | Returned Granularity |
|-----------------|---------------------|
| 1-2 days | 5-minute intervals |
| 2-90 days | Hourly intervals |
| 90+ days | Daily intervals |

**Impact:** Cannot get sub-5-minute data for periods longer than 2 days on free tier.

### Cost Analysis

| Tier | Rate Limit | Granularity | Cost |
|------|------------|-------------|------|
| **Free** | 10-30 req/min | Auto (limited) | $0 |
| **Analyst** | 500 req/min | Better | ~$129/mo |
| **Pro** | 1000 req/min | Best | ~$449/mo |

### Implementation Requirements

1. Add `get_historical_prices()` to `coingeckoutil.py`
2. Add `--source coingecko` CLI flag
3. Resample CoinGecko data to consistent intervals
4. Handle cross-coin timestamp alignment

### Challenges Identified

| Challenge | Description |
|-----------|-------------|
| **Rate limiting** | 6+ seconds between requests on free tier |
| **Granularity** | Can't get 30-sec data for analysis periods >2 days |
| **Timestamp alignment** | Each coin returns different timestamps |
| **Wrapped tokens** | WTAO and similar may lack historical data |
| **Cost** | Pro tier needed for high-frequency analysis |

### Comparison: Local Collection vs CoinGecko

| Aspect | Local Collection | CoinGecko Free | CoinGecko Pro |
|--------|------------------|----------------|---------------|
| Resolution | 30-sec | 5-min (2 days) / hourly | 1-min possible |
| History depth | Unlimited | 365 days | Longer |
| Cost | $0 (compute time) | $0 | ~$129-449/mo |
| Setup time | Days of collection | Instant | Instant |
| Custom coins | Any with price feed | Listed coins only | Listed coins only |

### Decision

**Deferred** - CoinGecko free tier granularity limitations make it unsuitable for sub-hourly analysis. Pro tier cost (~$129/mo) is not justified for current use case.

### Future Alternatives to Evaluate

| Source | Notes |
|--------|-------|
| **Binance API** | 1-minute candles, free, but limited to Binance-listed pairs |
| **CryptoCompare** | Free tier with historical data, evaluate limits |
| **Messari** | Free tier available, check historical endpoints |
| **DeFiLlama** | Free historical TVL/prices for DeFi tokens |
| **Pyth Network** | On-chain price feeds with history |

---

## References

- **Cross-Correlation:** [Wikipedia](https://en.wikipedia.org/wiki/Cross-correlation)
- **Granger Causality:** [Wikipedia](https://en.wikipedia.org/wiki/Granger_causality)
- **Lead-Lag Analysis:** Common technique in quantitative finance
- **Time Series Analysis:** Box-Jenkins methodology

---

## Related Documents

- [`CORRELATED_PAIR_FEATURE.md`](./CORRELATED_PAIR_FEATURE.md) - Cross-exchange arbitrage design
- [`FLASH_LOAN_FEATURE.md`](./FLASH_LOAN_FEATURE.md) - Atomic execution for correlated pairs
- [`HISTORY_ANALYSIS_FEATURE.md`](./HISTORY_ANALYSIS_FEATURE.md) - General history analysis

