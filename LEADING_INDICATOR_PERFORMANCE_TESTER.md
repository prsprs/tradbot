# Leading Indicator Performance Tester

## Overview

The Leading Indicator Performance Tester validates the predictive accuracy of discovered leading indicator pairs through paper trading simulations. It monitors leader price movements and executes simulated trades on the follower coin based on the correlation relationship, logging results for performance analysis.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LEADING INDICATOR PERFORMANCE TESTER                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐     ┌──────────────────┐     ┌───────────────────────┐   │
│  │  Discovery   │     │  Performance     │     │  Paper Trade          │   │
│  │  Report JSON │────▶│  Tester          │────▶│  Log File             │   │
│  │              │     │                  │     │                       │   │
│  └──────────────┘     └──────────────────┘     └───────────────────────┘   │
│                               │                                             │
│                               │                                             │
│                               ▼                                             │
│                       ┌──────────────────┐                                  │
│                       │  Price API       │                                  │
│                       │  (CoinGecko)     │                                  │
│                       └──────────────────┘                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Flow

### Step 1: Load Pair Configuration

```
┌─────────────────────────────────────────────────────────────────┐
│                    PAIR LOOKUP                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: --pair BTC:ETH                                          │
│                                                                  │
│  1. Load discovery report JSON                                   │
│  2. Search significant_pairs for matching leader:follower        │
│  3. Extract most recent record (by data_range_end)              │
│  4. Retrieve:                                                    │
│     ├─ optimal_lag_seconds                                      │
│     ├─ correlation (sign determines direction)                  │
│     ├─ confidence                                               │
│     └─ data_range_end (freshness check)                         │
│                                                                  │
│  Failure modes:                                                  │
│  - Pair not found in report                                     │
│  - Report file missing                                          │
│  - Stale data (optional warning threshold)                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step 2: Monitoring Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                    MONITORING LOOP                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────┐                                                    │
│  │  START  │                                                    │
│  └────┬────┘                                                    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────┐                                        │
│  │ Get Leader Price    │◀──────────────────────────┐            │
│  │ (T0)                │                           │            │
│  └─────────┬───────────┘                           │            │
│            │                                        │            │
│            ▼                                        │            │
│  ┌─────────────────────┐                           │            │
│  │ Wait: sample_interval│                          │            │
│  │ (default: 30s)       │                          │            │
│  └─────────┬───────────┘                           │            │
│            │                                        │            │
│            ▼                                        │            │
│  ┌─────────────────────┐                           │            │
│  │ Get Leader Price    │                           │            │
│  │ (T1)                │                           │            │
│  └─────────┬───────────┘                           │            │
│            │                                        │            │
│            ▼                                        │            │
│  ┌─────────────────────┐                           │            │
│  │ Calculate Change    │                           │            │
│  │ RISE / FALL / FLAT  │                           │            │
│  └─────────┬───────────┘                           │            │
│            │                                        │            │
│            ▼                                        │            │
│  ┌─────────────────────┐      ┌────────────────┐   │            │
│  │ Significant Move?   │──NO─▶│ Continue Loop  │───┘            │
│  │ (> threshold %)     │      └────────────────┘                │
│  └─────────┬───────────┘                                        │
│            │ YES                                                 │
│            ▼                                                     │
│  ┌─────────────────────┐                                        │
│  │ Schedule Trade      │                                        │
│  │ (wait lag × 0.8)    │                                        │
│  └─────────┬───────────┘                                        │
│            │                                                     │
│            ▼                                                     │
│  ┌─────────────────────┐                                        │
│  │ Execute Paper Trade │                                        │
│  │ on Follower         │                                        │
│  └─────────────────────┘                                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step 3: Trade Execution Logic

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADE DECISION MATRIX                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Correlation Type: POSITIVE (leader and follower move together) │
│  ┌─────────────────┬─────────────────┐                          │
│  │ Leader Movement │ Follower Action │                          │
│  ├─────────────────┼─────────────────┤                          │
│  │ RISE            │ BUY             │                          │
│  │ FALL            │ SELL            │                          │
│  │ FLAT            │ NO ACTION       │                          │
│  └─────────────────┴─────────────────┘                          │
│                                                                  │
│  Correlation Type: NEGATIVE (inverse relationship)              │
│  ┌─────────────────┬─────────────────┐                          │
│  │ Leader Movement │ Follower Action │                          │
│  ├─────────────────┼─────────────────┤                          │
│  │ RISE            │ SELL            │                          │
│  │ FALL            │ BUY             │                          │
│  │ FLAT            │ NO ACTION       │                          │
│  └─────────────────┴─────────────────┘                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step 4: Trade Timing

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADE TIMING CALCULATION                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Goal: Execute trade close to when follower movement expected   │
│                                                                  │
│  optimal_lag_seconds = 120 (from discovery report)              │
│  execution_pct = 80 (default, configurable)                     │
│                                                                  │
│  Timeline:                                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ T0          T1              T_exec            T_lag        │ │
│  │ │           │               │                 │            │ │
│  │ ▼           ▼               ▼                 ▼            │ │
│  │ ─────────────────────────────────────────────────────────▶ │ │
│  │ Leader     Leader          Execute           Expected     │ │
│  │ Price 1    Price 2         Trade             Follower     │ │
│  │            (detect move)   (lag × 0.8)       Movement     │ │
│  │                            = 96s                          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Wait time = (optimal_lag_seconds × execution_pct / 100)        │
│            - sample_interval (already elapsed)                   │
│                                                                  │
│  Example:                                                        │
│    lag=120s, pct=80, sample_interval=30s                        │
│    wait = (120 × 0.80) - 30 = 66 seconds after detection        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Command-Line Interface

```
python leading_indicator_tester.py [OPTIONS]

Required:
  --pair LEADER:FOLLOWER    Coin pair to test (e.g., BTC:ETH)

Optional:
  --report PATH             Path to discovery report JSON
                            (default: ./correlation_data/discovery_report.json)

Timing Parameters:
  --sample-interval SEC     Interval between leader price checks
                            (default: calculated from lag, or 30s)
  --execution-pct FLOAT     Percentage of lag time before trade execution
                            (default: 80, range: 50-95)
  --trade-frequency SEC     Minimum time between simulated trades
                            (default: lag × 2, prevents over-trading)

Thresholds:
  --min-move-pct FLOAT      Minimum % price change to trigger trade
                            (default: 0.5%)
  --position-size USD       Simulated position size for P&L calculation
                            (default: 1000)

Output:
  --output PATH             Path for paper trade log
                            (default: ./paper_trades/LEADER_FOLLOWER_trades.json)
  --duration DURATION       How long to run (e.g., 24h, 7d)
                            (default: run indefinitely)

Flags:
  --dry-run                 Show configuration without executing
  --verbose                 Detailed logging of each decision
  --auto-interval           Calculate optimal sample interval from lag
```

---

## Interval Calculation

### Auto-Calculated Intervals

When `--auto-interval` is enabled, intervals are derived from the lag:

```
┌─────────────────────────────────────────────────────────────────┐
│                    INTERVAL CALCULATION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  optimal_lag_seconds = 120                                       │
│                                                                  │
│  Recommended intervals:                                          │
│  ┌────────────────────────┬──────────────────────────────────┐  │
│  │ Parameter              │ Calculation                      │  │
│  ├────────────────────────┼──────────────────────────────────┤  │
│  │ sample_interval        │ max(15, lag / 4) = 30s           │  │
│  │ trade_frequency        │ lag × 2 = 240s                   │  │
│  │ execution_wait         │ lag × 0.8 = 96s                  │  │
│  └────────────────────────┴──────────────────────────────────┘  │
│                                                                  │
│  Rationale:                                                      │
│  - sample_interval: Frequent enough to detect moves promptly    │
│  - trade_frequency: Avoid overlapping trade signals             │
│  - execution_wait: Trade before expected follower movement      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Paper Trade Log Format

Compatible with existing trading bot analyzer:

```json
{
  "trades": [
    {
      "id": "pt_20260505_214530_001",
      "timestamp": "2026-05-05T21:45:30Z",
      "type": "paper",
      "pair": "BTC:ETH",
      "action": "BUY",
      "follower": "ETH",
      "follower_price_at_signal": 2450.00,
      "follower_price_at_execution": 2455.00,
      "position_size_usd": 1000.00,
      "quantity": 0.4073,
      "trigger": {
        "leader": "BTC",
        "leader_price_t0": 67000.00,
        "leader_price_t1": 67500.00,
        "leader_change_pct": 0.746,
        "correlation_direction": "positive",
        "expected_follower_direction": "rise"
      },
      "timing": {
        "signal_detected_at": "2026-05-05T21:43:30Z",
        "execution_at": "2026-05-05T21:45:30Z",
        "lag_seconds": 120,
        "execution_pct": 80,
        "wait_seconds": 96
      },
      "outcome": {
        "follower_price_after_lag": 2480.00,
        "actual_follower_change_pct": 1.02,
        "prediction_correct": true,
        "paper_pnl_usd": 10.20,
        "paper_pnl_pct": 1.02
      }
    }
  ],
  "summary": {
    "pair": "BTC:ETH",
    "start_time": "2026-05-05T20:00:00Z",
    "end_time": "2026-05-05T22:00:00Z",
    "total_trades": 5,
    "correct_predictions": 4,
    "accuracy_pct": 80.0,
    "total_paper_pnl_usd": 45.30,
    "total_paper_pnl_pct": 4.53
  }
}
```

---

## Trade Frequency Control

To prevent over-trading and signal overlap:

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADE FREQUENCY LIMITER                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Problem: Multiple signals during lag window                     │
│                                                                  │
│  Timeline with overlapping signals:                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Signal 1    Signal 2    Execute 1   Signal 3   Execute 2  │ │
│  │ │           │           │           │          │          │ │
│  │ ▼           ▼           ▼           ▼          ▼          │ │
│  │ ──────────────────────────────────────────────────────────▶│ │
│  │ t=0s        t=30s       t=96s       t=120s     t=126s     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Solution: --trade-frequency parameter                           │
│                                                                  │
│  Options:                                                        │
│  1. Cooldown: No new trades until previous execution complete   │
│  2. Replace: New signal replaces pending trade                  │
│  3. Queue: Queue signals, execute in order (risk: stale)        │
│  4. Aggregate: Combine signals into single larger trade         │
│                                                                  │
│  Default: Cooldown (safest, prevents compounding errors)        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Performance Metrics

After each trade, calculate and log:

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERFORMANCE TRACKING                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Per-Trade Metrics:                                              │
│  ├─ Prediction accuracy (correct direction?)                    │
│  ├─ Paper P&L (USD and %)                                       │
│  ├─ Timing accuracy (did follower move when expected?)          │
│  └─ Slippage simulation (price at signal vs execution)          │
│                                                                  │
│  Rolling Metrics:                                                │
│  ├─ Win rate (% correct predictions)                            │
│  ├─ Cumulative P&L                                              │
│  ├─ Sharpe ratio (if sufficient trades)                         │
│  ├─ Max drawdown                                                │
│  └─ Average trade duration                                      │
│                                                                  │
│  Comparison to Correlation Confidence:                           │
│  ├─ Does high confidence correlate with accuracy?               │
│  └─ Should min_confidence threshold be adjusted?                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Components

```python
@dataclass
class PairConfig:
    """Configuration loaded from discovery report."""
    leader: str
    follower: str
    optimal_lag_seconds: int
    correlation: float  # Sign indicates direction
    confidence: float
    data_range_end: str

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

@dataclass
class PriceSnapshot:
    """A price observation."""
    symbol: str
    price: float
    timestamp: datetime

@dataclass
class TradeSignal:
    """A detected trading signal."""
    leader_t0: PriceSnapshot
    leader_t1: PriceSnapshot
    change_pct: float
    direction: str  # 'rise' or 'fall'
    follower_action: str  # 'BUY' or 'SELL'
    scheduled_execution: datetime

@dataclass
class PaperTrade:
    """A completed paper trade."""
    signal: TradeSignal
    execution_price: float
    outcome_price: float
    pnl_usd: float
    pnl_pct: float
    prediction_correct: bool
```

---

## Alternatives

### Alternative 1: Batch Backtesting vs Live Simulation

**Current Design:** Live simulation with real-time price fetches

**Alternative:** Batch backtesting using historical data
- Pros: Faster testing, more data points, reproducible
- Cons: Requires historical data, no real-world timing validation

**Recommendation:** Support both modes
- `--mode live` (default): Real-time simulation
- `--mode backtest --start-date X --end-date Y`: Historical analysis

### Alternative 2: Single Pair vs Multi-Pair

**Current Design:** Test one pair at a time

**Alternative:** Test multiple pairs simultaneously
- Pros: Efficient use of API calls, portfolio-level analysis
- Cons: More complex state management, harder to debug

**Recommendation:** Start single-pair, add multi-pair later with `--pairs BTC:ETH,SOL:RAY`

### Alternative 3: Trade Execution Timing

**Current Design:** Execute at lag × 0.8

**Alternatives:**
- **Immediate:** Execute as soon as signal detected (captures more of the move)
- **At lag:** Execute exactly at lag time (matches correlation analysis)
- **Adaptive:** Adjust ratio based on observed timing accuracy

**Recommendation:** Configurable via `--execution-ratio`, default 0.8

### Alternative 4: Position Sizing

**Current Design:** Fixed USD amount per trade

**Alternatives:**
- **Confidence-weighted:** Larger positions for higher confidence pairs
- **Kelly criterion:** Optimal sizing based on win rate
- **Volatility-adjusted:** Smaller positions in volatile markets

**Recommendation:** Start simple, add `--sizing-strategy` parameter later

---

## Design Decisions

### D1: Stale Data Warning Threshold

**Decision:** 24 hours

Warn if discovery report `data_range_end` is older than 24 hours. User can override with `--max-data-age`.

### D2: API Rate Limiting

**Decision:** Calculate required call frequency from lag and warn if above limits.

```
┌─────────────────────────────────────────────────────────────────┐
│                    API RATE CALCULATION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Inputs:                                                         │
│  - optimal_lag_seconds (from discovery report)                  │
│  - sample_interval (derived or user-specified)                  │
│                                                                  │
│  Calculation:                                                    │
│  - sample_interval = max(15, lag / 4)                           │
│  - calls_per_minute = 60 / sample_interval                      │
│  - calls_per_hour = calls_per_minute × 60                       │
│                                                                  │
│  CoinGecko Free Tier Limits:                                    │
│  - ~10-30 calls/minute (varies)                                 │
│  - ~500 calls/day                                               │
│                                                                  │
│  At startup, display:                                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ API Call Estimate:                                         │ │
│  │ ├─ Sample interval: 30s                                    │ │
│  │ ├─ Calls per minute: 2                                     │ │
│  │ ├─ Calls per hour: 120                                     │ │
│  │ ├─ Calls per day: 2880                                     │ │
│  │ └─ WARNING: Exceeds free tier (500/day). Consider:         │ │
│  │    - Increasing --sample-interval                          │ │
│  │    - Using paid API                                        │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### D3: Minimum Move Threshold

**Decision:** Configurable percentage, default 0.5%

Parameter: `--min-move-pct 0.5`

The trade logs will capture actual move sizes, enabling post-analysis to determine optimal threshold per pair.

### D4: Outcome Measurement Timing

**Decision:** Trade execution at configurable percentage of lag time.

**Rationale:** At exact lag time, the follower movement has already occurred (that's what the correlation analysis detected). We want to trade *before* the expected movement.

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXECUTION TIMING STRATEGY                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Parameter: --execution-pct (default: 80%)                      │
│                                                                  │
│  Timeline:                                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ T0            T_exec (80%)           T_lag (100%)          │ │
│  │ │             │                      │                     │ │
│  │ ▼             ▼                      ▼                     │ │
│  │ ──────────────────────────────────────────────────────────▶│ │
│  │ Leader        Execute               Follower               │ │
│  │ moves         paper trade           movement               │ │
│  │               (capture move)        (already happened)     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Outcome measurement:                                            │
│  - Record follower price at T_exec (trade entry)                │
│  - Record follower price at T_lag (expected peak/trough)        │
│  - Calculate if direction prediction was correct                │
│  - Log both prices for later analysis                           │
│                                                                  │
│  MVP: Check price at T_exec and T_lag only (2 calls per trade) │
│  No high-granularity tracking needed.                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### D5: Short Selling Simulation

**Decision:** Fixed position size per trade, assume unlimited balance.

Parameter: `--position-size 1000` (USD per trade)

- For BUY signals: Simulate buying $1000 of follower
- For SELL signals: Simulate selling $1000 of follower (short)
- No balance tracking needed - simulation assumes liquidity
- Matches approach used in other trading bot designs

### D6: Multiple Discovery Reports

**Decision:** Use most recent by `data_range_end` timestamp.

If user needs a specific report, use `--report path/to/report.json`.

### D7: Real-Time Correlation Drift

**Decision:** No real-time warnings. Analyze after the fact.

**Rationale:** The purpose of the tester is to determine correlation accuracy. All trades are paper trades (no risk). The output logs will reveal if correlation degrades over time, which is valuable data for the analyzer.

The reporting format captures per-trade accuracy, enabling post-run analysis:
- Rolling accuracy over time
- Comparison to original confidence score
- Detection of correlation breakdown periods

---

## Dependencies

- `coingeckoutil.py` - Price fetching
- `correlation_tracker.py` - Discovery report format
- `historyutil.py` - Trade log format compatibility
- Standard: `asyncio`, `json`, `dataclasses`, `datetime`

---

## File Structure

```
tradingbot/
├── leading_indicator_tester.py    # Main tester implementation
├── paper_trades/
│   ├── BTC_ETH_trades.json        # Per-pair trade logs
│   ├── SOL_RAY_trades.json
│   └── summary.json               # Cross-pair summary
└── correlation_data/
    └── discovery_report.json      # Input from analyzer
```

---

## Usage Examples

### Basic Test

```bash
# Test BTC→ETH pair using defaults
python leading_indicator_tester.py --pair BTC:ETH
```

### With Custom Timing

```bash
# Faster sampling, earlier execution
python leading_indicator_tester.py --pair BTC:ETH \
    --sample-interval 15 \
    --execution-ratio 0.7 \
    --min-move-pct 0.3
```

### Limited Duration

```bash
# Run for 24 hours then stop
python leading_indicator_tester.py --pair BTC:ETH --duration 24h
```

### Verbose Mode

```bash
# See all decisions
python leading_indicator_tester.py --pair BTC:ETH --verbose
```

### Auto-Calculated Intervals

```bash
# Let tester calculate optimal intervals from lag
python leading_indicator_tester.py --pair BTC:ETH --auto-interval
```
