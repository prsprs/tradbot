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
```

### Analysis Techniques

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

