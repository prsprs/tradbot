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

Directionality:
  --honor-directionality    Only trade in the stronger direction from analysis
                            (default: yes, choices: yes/no)

Performance Monitoring:
  --max-data-age HOURS      Maximum age of discovery report data before warning
                            (default: 24)
  --age-check-interval HRS  Hours between data age checks during run
                            (default: 1.0)
  --min-win-rate FLOAT      Minimum win rate before action (0.0-1.0)
                            (default: 0.5)
  --win-rate-window INT     Number of recent trades to evaluate win rate
                            (default: 10)
  --auto-refresh            Auto re-run analyzer when win rate drops
                            (default: no, choices: yes/no)
```

---

## Multi-Pair Mode

Test multiple pairs simultaneously in paper trading mode. Useful for comparing pair performance under identical market conditions.

### Usage

```bash
python leading_indicator_tester.py --pairs BTC:TAO,ETH:SOL,BTC:BONK \
  --sample-interval 60 \
  --min-move-pct 0.5 \
  --duration 4h
```

### Constraints

| Feature | Multi-Pair Behavior |
|---------|---------------------|
| `--auto-interval` | **Disabled** (must specify `--sample-interval` manually) |
| `--execution-pct` | Single value applies to all pairs |
| `--trade-frequency` | Single value applies to all pairs |
| Live trading | **Supported** via Jupiter DEX (USDC mode) |
| Missing pairs | Skipped with warning |

### Design Decisions

| Aspect | Behavior |
|--------|----------|
| **Cooldown** | Global across all pairs (one trade triggers cooldown for all) |
| **Price fetching** | Batched by source (all CoinGecko symbols together, all Jupiter together) |
| **Directionality** | Per-pair from discovery report |
| **Win rate** | Per-pair tracking (no aggregate) |
| **Output** | Single log file with pair prefix on each entry |

### Summary Output

```
============================================================
MULTI-PAIR SESSION SUMMARY
============================================================
Pair        | Trades | Wins | Win Rate | P&L
------------|--------|------|----------|--------
BTC:TAO     | 3      | 2    | 66.7%    | +$45.20
ETH:SOL     | 0      | -    | -        | $0.00
BTC:BONK    | 5      | 3    | 60.0%    | +$82.15
============================================================
Total       | 8      | 5    | 62.5%    | +$127.35
============================================================
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

## Implementation Details

### I1: Discovery Report Path

**Decision:** Use `./correlation_data/discovery_report.json` as default.

User can override with `--report path/to/report.json`.

### I2: Price API Integration

**Status: RESOLVED**

Use `coingeckoutil.py` for price fetching:

```python
from coingeckoutil import get_coingecko_price

# Get single price
price = get_coingecko_price("BTC")  # Returns float (e.g., 67000.0) or None

# For multiple coins (more efficient, single API call)
from coingeckoutil import get_multiple_prices
prices = get_multiple_prices(["BTC", "ETH"])  # Returns {"BTC": 67000.0, "ETH": 2450.0}
```

**Key constraints:**
- Built-in rate limiting: 6 seconds between requests
- Free tier: ~10 calls/minute, ~500 calls/day
- Returns `None` on error (timeout, API failure, unknown symbol)
- Symbol mapping automatic (BTC, ETH, SOL, TAO, WTAO, etc. already mapped)
- Pro API available via `COINGECKO_API_KEY` env var

**Error handling strategy:**
- If price fetch returns `None`, log warning and skip this sample
- Continue monitoring loop (don't crash on transient errors)
- Track consecutive failures; abort if > 5 in a row (API likely down)

### I3: Graceful Shutdown (Ctrl+C)

**Decision:** Abort current cycle, save partial results.

On SIGINT:
1. Stop monitoring loop immediately
2. Do not wait for pending trade execution
3. Write all completed trades to output file
4. Log "Tester interrupted, partial results saved"

### I4: State Recovery After Crash

**Decision:** Start fresh.

No state persistence between runs. If tester crashes:
- Previous run's output file is preserved (separate file per run or append)
- New run starts from scratch
- User can analyze partial results from crashed run separately

### I5: Console Output

**Decision:** Print only on trades.

During normal operation:
- Startup: Display configuration, API rate estimate, pair info
- Each trade: Print trade details (leader move, action, prices)
- Shutdown: Print summary (total trades, accuracy if measurable)

Use `--verbose` for detailed output (every price check, timing info).

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

---

## Cross-Exchange Arbitrage Investigation

By supporting separate exchanges for leader and follower tokens, this system also serves as a **cross-exchange arbitrage investigation tool**. Since we only trade the follower token, we can:

1. **Track leader prices** from any exchange (CoinGecko for broad coverage)
2. **Track and trade follower** on the actual trading exchange (Jupiter for Solana)

This enables discovering arbitrage opportunities where price movements on one chain/exchange predict movements on another, with the ability to act on those predictions via the follower exchange.

**Example: TAO → WTAO Cross-Chain Correlation**
- TAO (non-Solana) price tracked via CoinGecko
- WTAO (Solana wrapped) price tracked and traded via Jupiter
- If TAO price moves predict WTAO price moves, we can trade WTAO on Jupiter

---

## Alternative Price API: Jupiter

Jupiter's Price API V3 can be used as an alternative to CoinGecko for Solana-native tokens.

### Endpoint

```
GET https://api.jup.ag/price/v3?ids=<mint_addresses>
```

**Headers:** `x-api-key: <your-api-key>` (optional but recommended)

### Response Format

```json
{
  "So11111111111111111111111111111111111111112": {
    "usdPrice": 147.48,
    "blockId": 348004023,
    "decimals": 9,
    "priceChange24h": 1.29
  }
}
```

### Rate Limits

| Tier | Rate Limit | Credits | Cost |
|------|------------|---------|------|
| Keyless | 0.5 RPS (30/min) | Unlimited | Free |
| Free (API key) | Rate-limited | Unlimited | Free |
| Paid tiers | Higher RPS | Included + $1/1M overage | Varies |
| Enterprise | 150+ RPS | Custom | Contact sales |

**Note:** Previous portal users retain their rate limits free until **30 June 2026**.

### Comparison with CoinGecko

| Feature | Jupiter | CoinGecko |
|---------|---------|-----------|
| **Tokens supported** | Solana only | Multi-chain |
| **Identifier** | Mint address | Symbol or ID |
| **Free rate limit** | 30/min keyless | ~10-50/min |
| **Batch queries** | Up to 50 IDs | Up to 250 IDs |
| **Price source** | On-chain liquidity | Aggregated exchanges |
| **Latency** | Lower (direct) | Higher (aggregated) |

### Viability Assessment

**✅ Viable for Solana-native pairs** (TAO, WTAO, SOL, JUP, etc.):
- Lower latency (direct on-chain pricing)
- Free tier sufficient for 14+ minute intervals
- Already have `jupiterutil.py` with price methods

**❌ Not viable for cross-chain pairs** (BTC, ETH):
- Jupiter only supports Solana tokens
- Would need wrapped versions (wBTC, wETH) which may have different price dynamics

### Implementation Notes

Existing `dex/jupiterutil.py` has `get_price()` method that derives price from swap quotes. For direct price lookups, use the Price API V3:

```python
import httpx

def get_jupiter_prices(mint_addresses: list, api_key: str = None) -> dict:
    """Get prices from Jupiter Price API V3."""
    headers = {"x-api-key": api_key} if api_key else {}
    url = f"https://api.jup.ag/price/v3?ids={','.join(mint_addresses)}"
    
    response = httpx.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()
```

### Recommendation

For **Solana-only correlation testing** (e.g., TAO:WTAO), Jupiter is preferred due to:
- Direct on-chain price data
- Lower latency
- Sufficient free tier rate limits

For **cross-chain correlation testing** (e.g., BTC:ETH), continue using CoinGecko.

---

## Exchange API Comparison for Non-Solana Pairs

For pairs not on Solana, we need exchanges that provide both **price data** and **trading capability**.

### Exchange Matrix

| Exchange | Price API Rate Limit | Trading | US Available | Tokens | Cost |
|----------|---------------------|---------|--------------|--------|------|
| **Coinbase** | 10 RPS public, 15 RPS private | ✅ | ✅ | ~250 | Free |
| **Kraken** | 1 req/sec public | ✅ | ✅ | ~200 | Free |
| **Binance** | 1200 weight/min (~300 ticker calls) | ✅ | ❌ (US restricted) | 500+ | Free |
| **Binance.US** | Similar to Binance | ✅ | ✅ | ~80 | Free |
| **OKX** | Per-endpoint limits | ✅ | ⚠️ (limited) | 300+ | Free |
| **Bybit** | Per-endpoint limits | ✅ | ❌ | 400+ | Free |

### Detailed Analysis

#### Coinbase (Recommended for US users)
**Existing integration:** `coinbaseutil2.py`

```
Public endpoints: 10 RPS per IP (burst to 15)
Private endpoints: 15 RPS per profile (burst to 30)
```

**Pros:**
- US-regulated and compliant
- Already integrated in codebase
- Good BTC, ETH, major altcoin coverage
- WebSocket available for real-time

**Cons:**
- Limited altcoin selection (~250 pairs)
- Some newer tokens not listed

**Price endpoint:**
```python
# GET /api/v3/brokerage/products/{product_id}
# Returns: price, bid, ask, volume
```

#### Kraken (Good US alternative)

```
Public: 1 request/second (or less)
Private: Counter-based (starts at 0, +1 per call, -0.5 to -1 per second)
Trading: Points-based per currency pair
```

**Pros:**
- Strong US regulatory standing
- Good security reputation
- Reasonable rate limits for monitoring

**Cons:**
- Smaller selection than Binance
- API slightly more complex

**Price endpoint:**
```
GET https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD
```

#### Binance (Best selection, non-US only)

```
REST: 1200 request weight per minute per IP
Ticker endpoint: weight 4 (can do ~300 calls/min)
WebSocket: No rate limit cost
```

**Pros:**
- Largest token selection (500+)
- Best liquidity
- Excellent documentation
- Free historical data

**Cons:**
- **Not available to US users** (use Binance.US instead)
- Binance.US has much smaller selection (~80 pairs)

**Price endpoint:**
```
GET https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT
```

#### OKX

```
Public REST: IP-based limits
Private REST: User ID-based limits
Trading: 1000 orders per 2 seconds per sub-account
```

**Pros:**
- Large selection
- Good derivatives market
- Competitive fees

**Cons:**
- US availability uncertain/limited
- More complex API structure

### Recommendation by Use Case

| Pair Type | Primary | Fallback |
|-----------|---------|----------|
| **Solana tokens** (TAO, WTAO, SOL) | Jupiter | CoinGecko |
| **Major pairs** (BTC, ETH) | Coinbase | Kraken |
| **Altcoins** (US user) | Coinbase → Kraken | CoinGecko (data only) |
| **Altcoins** (non-US) | Binance | OKX |

### Implementation Priority

1. **Jupiter** - Already have `jupiterutil.py`, add Price API V3 support
2. **Coinbase** - Already have `coinbaseutil2.py`, add price monitoring
3. **Kraken** - New integration for broader US coverage
4. **Binance** - New integration for non-US users with large token needs

### Adding `--exchange` Parameter

Future enhancement to support exchange selection:

```bash
# Use Jupiter for Solana pairs
python leading_indicator_tester.py --pair TAO:WTAO --exchange jupiter

# Use Coinbase for BTC:ETH
python leading_indicator_tester.py --pair BTC:ETH --exchange coinbase

# Auto-detect based on token (default)
python leading_indicator_tester.py --pair BTC:ETH --exchange auto
```

---

## Live Trading Mode (Solana/Jupiter)

Once paper trading validates a correlation strategy, live trading can be enabled to execute real trades on the follower token via Jupiter DEX.

### Pre-Flight Validation (Required for Live Mode)

**Conservative MVP approach**: Live mode requires automatic profitability validation before trading begins. This is enforced by the code with no override option.

#### Validation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LIVE MODE PRE-FLIGHT VALIDATION                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. User specifies: --trading-mode live --pair LEADER:FOLLOWER              │
│                                                                              │
│  2. Auto-run profitability analyzer:                                         │
│     └─ correlation_tracker.py --analyze --profitability                     │
│        --leader LEADER --follower FOLLOWER --recent 48hr                    │
│                                                                              │
│  3. Check verdict:                                                           │
│     ┌─────────────────────────────────────────────────────────────────────┐ │
│     │ VIABLE?                                                             │ │
│     │   ├─ YES → Extract recommended_interval, proceed to trading         │ │
│     │   └─ NO  → FAIL FAST with clear error message, exit immediately     │ │
│     └─────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  4. Configure trading intervals from profitability analysis:                 │
│     └─ sample_interval = derived from recommended_interval                  │
│     └─ trade_frequency = 2 × recommended_interval                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### MVP Constraints (Enforced, No Override)

| Constraint | Value | Rationale |
|------------|-------|-----------|
| **Profitability check** | Always runs | Prevents trading unprofitable pairs |
| **Data window** | 48 hours | Consistent, recent data for validation |
| **Required verdict** | VIABLE only | Conservative; POSSIBLY VIABLE rejected |
| **Interval source** | Auto from analysis | Removes guesswork, uses data-driven intervals |

#### Interval Mapping

| Profitability `recommended_interval` | `sample_interval` | `trade_frequency` |
|--------------------------------------|-------------------|-------------------|
| 1 min | 15 sec | 2 min |
| 5 min | 75 sec | 10 min |
| 15 min | 225 sec (~4 min) | 30 min |
| 1 hour | 15 min | 2 hours |
| 4 hour | 1 hour | 8 hours |

Formula: `sample_interval = max(15, recommended_interval / 4)`

#### Fail-Fast Error Messages

```
ERROR: Live trading rejected - pair TAO:WTAO is NOT VIABLE

Pre-flight profitability analysis (last 48 hours):
  Break-even move required: 1.3%
  Best interval found: 15 min
  Median move at interval: 0.4%
  Verdict: NOT VIABLE - insufficient volatility

To proceed with live trading, the pair must be VIABLE.
Consider:
  - Using paper trading mode to monitor this pair
  - Waiting for higher volatility market conditions
  - Testing a different pair

Exiting.
```

```
ERROR: Live trading rejected - pair BTC:UNKNOWN not found

The pair BTC:UNKNOWN was not found in the discovery report.
Run discovery first: python correlation_tracker.py --analyze

Exiting.
```

#### Future Enhancements (Post-MVP)

- `--preflight-recent` parameter to customize data window (default 48hr)
- `--preflight warn` option to proceed with warning on POSSIBLY VIABLE
- Periodic re-validation during long-running sessions

### Directional Filter (`--directional-filter`)

Optional parameter that enables direction-aware profitability analysis and runtime signal filtering.

#### Behavior Summary

| `--directional-filter` | Profitability Analysis | Runtime Signal Filter |
|------------------------|------------------------|----------------------|
| `false` (default) | Single pass (all samples) | Trade all signals from significant pairs |
| `true` | Two passes (UP/DOWN subsets) | Trade only signals where direction is viable |

#### Two-Pass Profitability Analysis

When `--directional-filter=true`, pre-flight runs profitability analysis twice:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DIRECTIONAL PROFITABILITY ANALYSIS                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PASS 1: UP Direction                                                        │
│  ├─ Filter data: only samples where leader moved UP                         │
│  ├─ Run cost/volatility/correlation analysis on UP subset                   │
│  └─ Verdict: UP-VIABLE or UP-NOT-VIABLE                                     │
│                                                                              │
│  PASS 2: DOWN Direction                                                      │
│  ├─ Filter data: only samples where leader moved DOWN                       │
│  ├─ Run cost/volatility/correlation analysis on DOWN subset                 │
│  └─ Verdict: DOWN-VIABLE or DOWN-NOT-VIABLE                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Directional Pre-Flight Output

```
═══════════════════════════════════════════════════════════════════════
              DIRECTIONAL PROFITABILITY ANALYSIS: BTC → SOL
═══════════════════════════════════════════════════════════════════════

UP DIRECTION (leader rises):
  Samples: 1,247
  Volatility: 45% of moves exceed 0.8% break-even
  Correlation: 0.72 (p=0.003, significant)
  Recommended interval: 1 hour
  Verdict: ✓ UP-VIABLE

DOWN DIRECTION (leader falls):
  Samples: 1,189
  Volatility: 28% of moves exceed 0.8% break-even
  Correlation: 0.31 (p=0.18, not significant)
  Recommended interval: N/A
  Verdict: ✗ DOWN-NOT-VIABLE

═══════════════════════════════════════════════════════════════════════
COMBINED VERDICT: PARTIALLY VIABLE (UP only)
  → Will trade on leader RISE signals only
  → Leader FALL signals will be skipped
═══════════════════════════════════════════════════════════════════════
```

#### Verdict Matrix

| UP-VIABLE | DOWN-VIABLE | Combined Verdict | Behavior |
|-----------|-------------|------------------|----------|
| ✓ | ✓ | **FULLY VIABLE** | Trade both directions |
| ✓ | ✗ | **PARTIALLY VIABLE (UP)** | Trade only on leader rises |
| ✗ | ✓ | **PARTIALLY VIABLE (DOWN)** | Trade only on leader falls |
| ✗ | ✗ | **NOT VIABLE** | Fail pre-flight |

**Note**: PARTIALLY VIABLE is allowed for both USDC and swap modes. In swap mode with only one direction viable, the system will only execute swaps in that direction (continuously buying or selling based on viable direction).

#### Runtime Signal Filtering

When `--directional-filter=true`, signals are filtered at runtime:

```
┌─────────────────────────────────────────────────────────────────┐
│  SIGNAL FILTER                                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Leader moved UP?                                                │
│    ├─ UP-VIABLE = true  → GENERATE BUY SIGNAL                   │
│    └─ UP-VIABLE = false → SKIP (log: "UP direction not viable") │
│                                                                  │
│  Leader moved DOWN?                                              │
│    ├─ DOWN-VIABLE = true  → GENERATE SELL SIGNAL                │
│    └─ DOWN-VIABLE = false → SKIP (log: "DOWN direction not      │
│                                    viable")                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Interval Selection

When both directions are viable with different recommended intervals:
- Use the more conservative (longer) interval
- Example: UP recommends 1hr, DOWN recommends 4hr → use 4hr

When only one direction is viable:
- Use that direction's recommended interval

#### Minimum Samples

Directional analysis requires minimum samples per direction (default: 100, configurable via `--min-samples`). If insufficient samples exist for a direction, that direction is marked NOT-VIABLE.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LIVE TRADING MODE                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐     ┌──────────────────┐     ┌───────────────────┐   │
│  │  Price Monitor   │     │  Trade Signal    │     │  Jupiter Swap     │   │
│  │  (same as paper) │────▶│  Generator       │────▶│  Execution        │   │
│  └──────────────────┘     └──────────────────┘     └───────────────────┘   │
│                                                            │                │
│                                                            ▼                │
│                                                    ┌───────────────────┐   │
│                                                    │  Solana Wallet    │   │
│                                                    │  (Jupiter/Phantom)│   │
│                                                    └───────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Command-Line Interface

```bash
# Paper trading (default, current behavior)
python leading_indicator_tester.py --pair TAO:WTAO --trading-mode paper

# Live trading with Jupiter
python leading_indicator_tester.py --pair TAO:WTAO --trading-mode live

# Live trading with specific position size
python leading_indicator_tester.py --pair TAO:WTAO --trading-mode live --position-size 100

# Dry run to preview live trade parameters
python leading_indicator_tester.py --pair TAO:WTAO --trading-mode live --dry-run
```

### New CLI Parameters

| Parameter | Values | Default | Description |
|-----------|--------|---------|-------------|
| `--trading-mode` | `paper`, `live` | `paper` | Trading mode |
| `--position-size` | USD amount | `100` | Amount per trade in USD |
| `--slippage-bps` | basis points | `50` | Max slippage (0.5% default) |
| `--wallet` | path | `~/.config/solana/id.json` | Solana wallet keypair path |

### Wallet Configuration

#### Option 1: Local Keypair File (Recommended for Automation)

```bash
# Set wallet path
export SOLANA_WALLET_PATH=~/.config/solana/id.json

# Or use CLI
python leading_indicator_tester.py --pair TAO:WTAO --trading-mode live \
    --wallet ~/.config/solana/id.json
```

#### Option 2: Environment Variable (Base58 Private Key)

```bash
export SOLANA_PRIVATE_KEY=<base58-encoded-private-key>
```

#### Option 3: Jupiter Wallet Integration

If using a browser-based Jupiter wallet:

```bash
# Export private key from Jupiter wallet settings
# Save to file or environment variable as above
```

### Trade Execution Flow

```
1. Signal Detected
   └─ Leader moved ≥ min_move_pct in direction X

2. Pre-Trade Checks
   ├─ Wallet balance sufficient?
   ├─ Trade cooldown elapsed?
   ├─ Slippage within bounds?
   └─ Gas fees acceptable?

3. Build Swap Transaction
   ├─ Input: USDC (or SOL)
   ├─ Output: Follower token (e.g., WTAO)
   ├─ Amount: position_size USD
   └─ Slippage: slippage_bps

4. Execute via Jupiter
   ├─ Get quote from Jupiter API
   ├─ Build swap transaction
   ├─ Sign with wallet
   └─ Submit to Solana RPC

5. Log Trade
   ├─ Transaction signature
   ├─ Actual fill price
   ├─ Fees paid
   └─ Slippage realized
```

### Jupiter Integration

Leverages existing `dex/jupiterutil.py` with extensions:

```python
from dex.jupiterutil import JupiterClient
from dex.local_wallet import load_wallet

# Initialize
jupiter = JupiterClient()
wallet = load_wallet()

# Get quote
quote = jupiter.get_quote(
    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    output_mint="taoC6xyv2v8tDLcev4uaGUgV4vdQsWJrGft2kcBRrBY",  # WTAO
    amount=100_000_000,  # 100 USDC (6 decimals)
    slippage_bps=50
)

# Execute swap
result = jupiter.swap(quote, wallet)
print(f"TX: {result.signature}")
```

### Position Management

#### Buy Signal (Leader UP, Positive Correlation)

```
USDC → WTAO
├─ Swap $100 USDC for WTAO
├─ Hold position
└─ Close at outcome check time (or next signal)
```

#### Sell Signal (Leader DOWN, Positive Correlation)

```
WTAO → USDC
├─ Swap WTAO holdings for USDC
└─ Wait for next buy signal
```

#### Position Tracking

```python
@dataclass
class LivePosition:
    token: str                    # e.g., "WTAO"
    entry_price: float           # USD price at entry
    quantity: float              # Token amount held
    entry_time: datetime         # When position opened
    entry_tx: str                # Solana transaction signature
    status: str                  # "open" or "closed"
```

### Safety Features

| Feature | Description |
|---------|-------------|
| **Max Position Size** | Hard cap on single trade (default: $500) |
| **Daily Loss Limit** | Stop trading if daily P&L < -X% (default: -5%) |
| **Cooldown Enforcement** | Minimum time between trades (from correlation lag) |
| **Slippage Protection** | Reject trades with slippage > threshold |
| **Balance Check** | Verify wallet has sufficient funds before trade |
| **Dry Run Mode** | Preview all trades without execution |

### Performance Monitoring & Auto-Refresh

The tester monitors its own success rate and data freshness during operation:

#### Data Staleness Monitoring
- **Periodic age check**: Every `--age-check-interval` hours (default: 1h)
- **Warning**: Logs warning if data exceeds `--max-data-age` hours
- **Purpose**: Alert user that correlation analysis may be outdated

#### Win Rate Monitoring
- **Rolling window**: Tracks last `--win-rate-window` trades (default: 10)
- **Threshold**: `--min-win-rate` (default: 0.5 = 50%)
- **Evaluation**: After each completed trade outcome

#### Breach Behavior

| `--auto-refresh` | On Win Rate Breach |
|------------------|-------------------|
| `no` (default) | Stop with message: "Stopping due to low win rate" |
| `yes` | Run analyzer → Reload config → Reset tracking → Resume |

#### Auto-Refresh Process
1. Run `correlation_tracker.py --analyze` with same parameters
2. Reload pair configuration from updated discovery report
3. Clear win rate history (fresh start with new config)
4. Resume trading with new correlation/lag parameters

#### Post-Trade Pause
After executing a trade, the tester automatically pauses for the remaining lag time before resuming price checks. This handles both scenarios:

| Scenario | Behavior |
|----------|----------|
| `remaining_lag > sample_interval` | Wait remaining_lag (avoid wasteful API calls) |
| `remaining_lag < sample_interval` | Wait remaining_lag (avoid waiting too long for next opportunity) |

```
Long lag:   [sample]---[sample]---[TRADE]-------[remaining_lag]-------[sample]
Short lag:  [sample]---[sample]---[TRADE]--[remaining_lag]--[sample]
```

- **Trigger**: After any trade execution
- **Duration**: `optimal_lag - execution_wait_time` (remaining lag)
- **Benefit**: Optimal timing for both API efficiency and trade opportunities

#### Example: Autonomous Operation
```bash
python leading_indicator_tester.py --pair BTC:NVDAX \
  --min-win-rate 0.45 \
  --win-rate-window 10 \
  --auto-refresh yes \
  --max-data-age 12
```

This will:
- Trade based on BTC→NVDAX correlation
- Monitor win rate over last 10 trades
- If win rate drops below 45%: refresh analyzer data and continue
- Warn if data becomes older than 12 hours

### Configuration Example

```python
@dataclass
class LiveTradingConfig:
    trading_mode: str = "paper"          # "paper" or "live"
    position_size_usd: float = 100.0     # USD per trade
    max_position_usd: float = 500.0      # Max single position
    slippage_bps: int = 50               # 0.5% max slippage
    daily_loss_limit_pct: float = 5.0    # Stop at -5% daily
    wallet_path: Optional[str] = None    # Path to keypair
    rpc_url: str = "https://api.mainnet-beta.solana.com"
```

### Output: Live Trade Log

```json
{
  "trades": [
    {
      "id": "lt_20260506_143022_001",
      "mode": "live",
      "signal": {
        "direction": "BUY",
        "leader_move_pct": 1.25,
        "trigger_time": "2026-05-06T14:30:22Z"
      },
      "execution": {
        "input_token": "USDC",
        "output_token": "WTAO",
        "input_amount": 100.0,
        "output_amount": 0.315,
        "price": 317.46,
        "slippage_bps": 12,
        "fee_sol": 0.000125,
        "tx_signature": "5Kj9...abc",
        "confirmed_at": "2026-05-06T14:30:24Z"
      },
      "outcome": {
        "exit_price": 325.80,
        "exit_amount": 102.63,
        "pnl_usd": 2.63,
        "pnl_pct": 2.63,
        "exit_tx": "7Mn3...xyz"
      }
    }
  ],
  "summary": {
    "total_trades": 8,
    "winning_trades": 5,
    "total_pnl_usd": 42.15,
    "total_fees_sol": 0.001
  }
}
```

### Implementation Phases

#### Phase 1: Foundation (MVP)
- [ ] Add `--trading-mode` CLI parameter
- [ ] Wallet loading from file/env
- [ ] Jupiter quote fetching for position sizing
- [ ] Dry-run mode showing intended trades

#### Phase 2: Execution
- [ ] Jupiter swap execution
- [ ] Transaction confirmation waiting
- [ ] Position tracking (open/close)
- [ ] Trade logging with tx signatures

#### Phase 3: Safety & Polish
- [ ] Daily loss limit enforcement
- [ ] Balance checks before trades
- [ ] Slippage monitoring and alerts
- [ ] Retry logic for failed transactions

### Dependencies

```
# Already in repo
dex/jupiterutil.py      - Jupiter API client
dex/local_wallet.py     - Solana wallet loading
dex/token_cache.py      - Token mint address lookup

# Additional (if needed)
solana-py               - Solana transaction signing
solders                 - Solana primitives
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JUPITER_API_KEY` | Yes | Jupiter API key for quotes |
| `SOLANA_PRIVATE_KEY` | Optional | Base58 private key (alternative to file) |
| `SOLANA_WALLET_PATH` | Optional | Path to keypair JSON file |
| `SOLANA_RPC_URL` | Optional | Custom RPC endpoint |

### Alternatives

#### Trade Execution

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **Jupiter API + local signing** | Full control, no browser needed | Requires private key management | ✅ MVP |
| **WalletConnect** | Hardware wallet support, no key exposure | Requires user interaction per trade | Future enhancement |
| **Jito bundles** | MEV protection, atomic execution | More complex, additional fees | Consider for high-value trades |
| **Helius RPC** | Faster confirmations, better reliability | $50+/month | Production recommendation |

#### Position Sizing

| Strategy | Description | Use Case |
|----------|-------------|----------|
| **Fixed USD** | Same $ amount per trade | Simple, predictable |
| **Kelly Criterion** | Size based on edge and confidence | Optimal growth, higher variance |
| **Volatility-adjusted** | Reduce size in high-vol periods | Risk management |
| **Trailing with profits** | Increase size as account grows | Compound gains |

#### Exit Strategy

| Strategy | Description | Trade-offs |
|----------|-------------|------------|
| **Time-based** | Exit at outcome check time (lag seconds) | Matches paper trading, simple |
| **Take-profit** | Exit when target % reached | Captures gains, may miss larger moves |
| **Stop-loss** | Exit when loss exceeds threshold | Limits downside, may exit prematurely |
| **Trailing stop** | Dynamic stop that follows price up | Locks in gains, complex to tune |
| **Next signal** | Hold until opposite signal | Maximizes position time, higher exposure |

### Open Questions (Live Mode)

1. **Position management across restarts**
   - ~~Should we persist open positions to disk?~~
   - ~~How do we handle a restart with an open position?~~
   - ~~Do we query wallet balance on startup to detect existing positions?~~
   - **MVP Decision**: No persistence. User must manage restarts manually.

2. **Multiple pairs simultaneously**
   - ~~Should live mode support monitoring multiple pairs?~~
   - ~~How do we allocate capital across pairs?~~
   - ~~Do positions in different pairs share the daily loss limit?~~
   - **MVP Decision**: Single pair only.

3. **Quote currency preference**
   - ~~Default to USDC for stability?~~
   - ~~Support SOL as quote for lower fees?~~
   - ~~Allow user to specify preferred quote currency?~~
   - **MVP Decision**: Default to USDC. No SOL quote support initially.

4. **Transaction priority fees**
   - ~~Should we add priority fees for faster confirmation?~~
   - ~~How much priority fee is acceptable?~~
   - ~~Should this be configurable or auto-calculated?~~
   - **MVP Decision**: No priority fees. Use default transaction settings.

5. **Partial fills and failed transactions**
   - ~~How do we handle partial fills from Jupiter?~~
   - ~~Retry logic for failed transactions (network issues)?~~
   - ~~Maximum retry attempts before giving up?~~
   - **MVP Decision**: No retry logic. Log failures and continue.

6. **Tax and reporting considerations**
   - ~~Should we generate trade reports for tax purposes?~~
   - ~~What format (CSV, JSON, specific tax software)?~~
   - ~~Track cost basis for each position?~~
   - **MVP Decision**: Yes. CSV export with cost basis tracking.

7. **Notification system**
   - ~~Send alerts on trade execution (Telegram, Discord)?~~
   - ~~Alert on errors or daily loss limit hit?~~
   - ~~Summary report at end of day?~~
   - **MVP Decision**: No real-time alerts. Daily summary report with ability to generate summary across all historical trades.

8. **Backtesting integration**
   - ~~Can we replay paper trade history as if it were live?~~
   - ~~Estimate actual slippage from historical liquidity?~~
   - ~~Compare paper vs live performance for same signals?~~
   - **MVP Decision**: Slippage estimation report for MVP. Full backtesting deferred.

---

## Swap Mode (Pair-to-Pair Trading)

### Concept

Instead of trading against a quote currency (USDC), swap mode treats the correlated pair as a self-contained trading universe. When a signal suggests one token will outperform the other, swap directly between them.

**Current USDC mode:**
```
BUY TAO signal  → Buy TAO with USDC
SELL TAO signal → Sell TAO for USDC
```

**Proposed swap mode:**
```
BUY TAO signal  → Swap WTAO → TAO  (expecting TAO to outperform WTAO)
SELL TAO signal → Swap TAO → WTAO  (expecting WTAO to outperform TAO)
```

### Motivation

- **No quote currency capital needed** - Always holding ecosystem exposure
- **Relative performance trading** - Profit from correlation divergence, not absolute moves
- **Natural for wrapped pairs** - TAO/WTAO, ETH/WETH, SOL/mSOL
- **Private liquidity pool analogy** - Rebalancing between two correlated assets
- **Lower friction** - Direct swaps often have better liquidity than USDC routes

### CLI Extension

```bash
# Current USDC mode (default)
python leading_indicator_tester.py --leader WTAO --follower TAO

# Swap mode - trade directly between the pair
python leading_indicator_tester.py --leader WTAO --follower TAO --swap

# With live trading
python leading_indicator_tester.py --leader WTAO --follower TAO --swap --trading-mode live
```

### P&L Calculation

In swap mode, P&L is measured in **equivalent units** rather than USDC:

```
Initial: 100 WTAO
Signal: BUY TAO → Swap to 98 TAO (after fees)
Later: SELL TAO → Swap to 102 WTAO (after fees)
P&L: +2 WTAO (+2%)
```

The session summary would show:
- Total P&L in base token (WTAO-equivalent)
- Optional: USDC-equivalent using current prices

### Implementation Considerations

1. **Initial position required** - User must hold one of the pair tokens
2. **Swap fees** - Jupiter ~0.3-0.5% per swap (double for round-trip)
3. **Liquidity depth** - Direct pair pools may have less liquidity than USDC routes
4. **Price tracking** - Monitor both tokens to calculate relative P&L

### Risk Profile by Correlation Sign

The sign of the correlation between the pair tokens fundamentally changes the risk/reward profile of swap mode:

#### Positively Correlated Pairs (e.g., TAO/WTAO, ETH/WETH)

Both tokens tend to move in the same direction (up together, down together).

| Aspect | Implication |
|--------|-------------|
| **Absolute gain potential** | Higher - if both tokens moon, your portfolio value increases regardless of which you hold |
| **Permanent loss risk** | Higher - if both tokens crash (e.g., ecosystem failure), you have no hedge and lose absolute value |
| **Relative gain potential** | Lower - since they move together, relative outperformance opportunities are smaller |
| **Best for** | Capturing small timing differences between tightly coupled assets |

**Risk summary**: You're fully exposed to the ecosystem. Swap mode optimizes *which* token to hold, but cannot protect against systemic decline.

#### Negatively Correlated Pairs (inverse relationship)

Tokens move in opposite directions (one rises when the other falls).

| Aspect | Implication |
|--------|-------------|
| **Absolute gain potential** | Lower - you're always partially "wrong" in absolute terms since one is rising while the other falls |
| **Permanent loss risk** | Lower - natural hedge; when one crashes, the other rises, preserving portfolio value |
| **Relative gain potential** | Higher - large divergences mean significant relative P&L opportunities |
| **Best for** | Risk-managed trading with built-in downside protection |

**Risk summary**: You sacrifice potential absolute gains for reduced permanent loss risk. The strategy becomes more about timing the oscillations between the two.

#### Implications for Swap Mode

- **Positive correlation**: Treat swap mode as an optimization within an already-committed position. You've decided to hold the ecosystem; swap mode helps you hold the better-performing token.
- **Negative correlation**: Swap mode acts more like a hedged strategy. You're trading relative performance while maintaining natural portfolio protection.

Consider adding a `--warn-positive-correlation` flag that alerts users when using swap mode with highly positively correlated pairs (correlation > 0.7) about the concentrated risk.

#### Partial Position Strategy (Hold Both Tokens)

Rather than swapping 100% of holdings, a partial swap strategy maintains exposure to both tokens simultaneously:

```
Initial: 100 WTAO, 0 TAO
BUY TAO signal (50% swap): 50 WTAO, ~49 TAO
SELL TAO signal (50% swap): 75 WTAO, ~24 TAO
```

| Strategy | Positive Correlation | Negative Correlation |
|----------|---------------------|---------------------|
| **100% swaps** | Maximum relative gain, full ecosystem risk | Maximum relative gain, natural hedge |
| **Partial swaps** | Reduced relative gain, slightly diversified | Reduced relative gain, enhanced hedge |

**Benefits of partial positions:**
- Never fully wrong on direction
- Smoother P&L curve (less volatile)
- Always have liquidity in both tokens
- For negative correlation: amplifies the natural hedge effect

**Trade-offs:**
- Lower magnitude of relative gains
- More complex position tracking
- Fee efficiency reduced (smaller swaps, same base fees)

This could be implemented via a `--swap-percentage 50` parameter (default 100 for full swaps).

#### Directionality Requirement

**Critical insight**: Swap mode only works reliably if the correlation holds in *both* directions (UP and DOWN movements of the leader).

Consider a pair where:
- When leader rises → follower rises (correlation holds)
- When leader falls → follower behavior is random (correlation breaks)

In this asymmetric case:
- BUY signals (leader rising) would be reliable
- SELL signals (leader falling) would be unreliable
- The strategy would only work "half the time"

**Why this matters for swap mode specifically:**

In USDC mode, an unreliable SELL signal means you might miss a gain or take an unnecessary loss, but you exit to stable USDC.

In swap mode, an unreliable SELL signal means you swap to the other token based on a false premise. If the correlation doesn't hold on downs, you're now holding a token that may not behave as expected—with no stable exit.

**Integration with Directional Analysis:**

This is exactly what the directional correlation analysis (TEST 6 in `correlation_tracker.py`) measures:

```
TEST 6: Directional Analysis (UP vs DOWN)
├─ UP (rises):   correlation=-0.33, p=0.60 ✗ (not significant)
├─ DOWN (drops): correlation=-0.42, p=0.03 ✓ (significant)
└─ Asymmetry: 0.47 (moderate)
```

**Recommendation for swap mode:**
- Require both `up_significant` AND `down_significant` from directional analysis
- Or at minimum, warn if only one direction is significant
- Consider a `--require-bidirectional` flag (default ON for swap mode)

| Scenario | Swap Mode Suitability |
|----------|----------------------|
| Both UP and DOWN significant | ✅ Ideal for swap mode |
| Only UP significant | ⚠️ Only swap on BUY signals, hold otherwise |
| Only DOWN significant | ⚠️ Only swap on SELL signals, hold otherwise |
| Neither significant | ❌ Do not use swap mode |

### Open Questions (Swap Mode)

1. **Base token selection**
   - ~~Which token is the "base" for P&L calculation?~~
   - ~~Should it be the leader, follower, or user-specified?~~
   - ~~How do we handle the initial position check?~~
   - **MVP Decision**: Calculate P&L based on USDC-equivalent value. Report what gain/loss would occur if entire position (both leader and follower holdings) were sold for USDC at current prices.

2. **Swap routing**
   - ~~Direct pool swap vs multi-hop through USDC?~~
   - ~~Let Jupiter auto-route for best price?~~
   - ~~Should we compare routes and warn if direct is worse?~~
   - **MVP Decision**: Use Jupiter auto-routing for best price. Private LP option evaluated and deferred.
   
   **Private LP Analysis (Evaluated, Not Implementing)**
   
   The concept: Create your own liquidity pool, route trades through it, and recapture fees instead of paying them to third parties.
   
   *Platforms supporting private/concentrated LPs:*
   | Platform | Pool Type | Direct Routing | API Support |
   |----------|-----------|----------------|-------------|
   | Meteora DLMM | Concentrated | ✅ Via SDK | ✅ |
   | Orca Whirlpools | Concentrated | ✅ Via SDK | ✅ |
   | Raydium CLMM | Concentrated | ✅ Via SDK | ✅ |
   
   *Key finding: Pools are always public.* You cannot create an exclusive pool - anyone can swap through it. However, fees paid by all traders (including yourself) go to you as the LP owner.
   
   *Critical limitation: Slippage in small pools.*
   
   | Trade Size | Slippage in $10k Pool | Jupiter Fee |
   |------------|----------------------|-------------|
   | $100 | ~1% ($1) | ~0.3% ($0.30) |
   | $500 | ~5% ($25) | ~0.3% ($1.50) |
   | $1,000 | ~10% ($100) | ~0.3% ($3) |
   
   For a $10k pool, slippage on trades >$200 exceeds Jupiter fees. Private LP only makes economic sense with:
   - Very small trades (<$200), OR
   - Very large pool ($100k+ for $1k trades)
   
   *Additional risks:*
   - **Impermanent loss**: Pool value decreases when token prices diverge (conflicts with correlation trading strategy which profits from divergence)
   - **Operational complexity**: Must bypass Jupiter, use platform-specific SDKs
   - **Non-native tokens**: BTC requires bridging to wBTC (Portal/Wormhole)
   
   *Decision:* Not implementing. Jupiter routing provides better economics at planned trade sizes.

3. **Position sizing in swap mode**
   - ~~Swap entire holding or fixed percentage?~~
   - ~~Should `--position-size-usd` still apply (as equivalent value)?~~
   - ~~Reserve some for fees or go all-in?~~
   - **MVP Decision**: `--position-size-usd` applies in swap mode as equivalent value. Swap the USD-equivalent amount, reserve remainder for fees.

4. **Partial swaps**
   - ~~Support swapping only a percentage of holdings?~~
   - ~~Gradual position building vs single swap?~~
   - ~~Risk management through partial positions?~~
   - **MVP Decision**: Support partial swaps. Swap only `--position-size-usd` equivalent per signal, not entire holding.

5. **Mixed mode**
   - ~~Allow both USDC and swap trades in same session?~~
   - ~~Use swap when direct pool is favorable, USDC otherwise?~~
   - ~~How would P&L reporting work in mixed mode?~~
   - **MVP Decision**: Single mode per session. Choose USDC mode OR swap mode at startup, not both.

6. **Correlation requirements**
   - ~~Should swap mode require minimum correlation threshold?~~
   - ~~Warn if pair correlation is weak (higher divergence risk)?~~
   - ~~Auto-disable if correlation degrades during session?~~
   - **MVP Decision**: Pre-flight validation enforces VIABLE verdict which requires significant correlation. Runtime degradation check deferred to post-MVP. See "Pre-Flight Validation" section.

7. **Wrapped token edge case**
   - ~~For TAO/WTAO, should we consider wrap/unwrap instead of swap?~~
   - ~~Wrap/unwrap has no slippage but may have other constraints~~
   - ~~How do we detect which pairs support direct wrap/unwrap?~~
   - **MVP Decision**: Not implementing wrap/unwrap. Use swap via Jupiter.
   
   **Wrap/Unwrap Feasibility Analysis (Evaluated, Not Implementing)**
   
   *Two types of "wrapped" tokens on Solana:*
   
   | Type | Example | Wrap/Unwrap Mechanism | Latency |
   |------|---------|----------------------|---------|
   | **Native wrap** | SOL → wSOL | SPL Token program (on-chain) | ~1 second |
   | **Bridge wrap** | TAO → WTAO | Wormhole cross-chain bridge | 5-15 minutes |
   
   *TAO/WTAO is a bridge wrap (Wormhole):*
   - WTAO on Solana is TAO bridged from Bittensor via Wormhole
   - Unwrapping requires cross-chain transaction back to Bittensor
   - Process involves: lock/burn → VAA generation by Guardians → mint/release
   - **Latency: 5-15 minutes per operation** (unsuitable for trading)
   
   *Wormhole SDK availability:*
   - TypeScript SDK: `@wormhole-foundation/sdk` (well-documented)
   - Python SDK: Limited, community-maintained
   - Programmatic wrap/unwrap is technically feasible but slow
   
   *Why swap is better for trading:*
   
   | Approach | Latency | Slippage | Complexity |
   |----------|---------|----------|------------|
   | Jupiter swap | ~2 seconds | 0.1-0.5% | Low (existing code) |
   | Wormhole wrap/unwrap | 5-15 minutes | 0% | High (new integration) |
   
   For trading frequency measured in minutes/hours, the 5-15 minute wrap latency makes wrap/unwrap impractical. Jupiter swap is the correct approach despite small slippage cost.
   
   *Exception - native wraps (SOL/wSOL):*
   Could be optimized in future since SPL wrap is instant. Not prioritized for MVP.

8. **Rebalancing frequency**
   - ~~Should there be a minimum time between swaps?~~
   - ~~Cooldown to avoid excessive fee burn on noisy signals?~~
   - ~~How does this interact with the existing cooldown logic?~~
   - **MVP Decision**: Use existing `--trade-frequency` cooldown parameter. Same cooldown applies to swaps as USDC trades.

---

## Profitability Analysis (Implemented)

### Motivation

Before running the performance tester, we need to answer a fundamental question:

> **Is this pair worth trading at all?**

This requires combining three analyses:
1. **Cost analysis** - What % move is needed to break even?
2. **Volatility analysis** - At what interval does the follower move that much?
3. **Correlation analysis** - Does the leader predict the follower at that interval?

### The Three-Part Framework

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. COST: What % move do I need to break even?                      │
│     └─ Depends on: follower liquidity, position size, spread        │
│                                                                      │
│  2. VOLATILITY: At what interval does follower move that much?      │
│     └─ Depends on: historical price data, percentile threshold      │
│                                                                      │
│  3. CORRELATION: Does leader predict follower at that interval?     │
│     └─ Depends on: lag, correlation strength, Granger causality     │
└─────────────────────────────────────────────────────────────────────┘
```

### Trading Overhead Costs (Jupiter/Solana)

#### Fixed Costs Per Trade

| Cost Type | Amount | Notes |
|-----------|--------|-------|
| Solana Transaction Fee | ~0.000005 SOL (~$0.001) | Negligible |
| Jupiter Platform Fee | 0% | No platform fee on swaps |
| Priority Fee (optional) | 0.0001-0.001 SOL | For faster execution |

#### Variable Costs (Significant)

| Cost Type | Typical Range | Notes |
|-----------|---------------|-------|
| Slippage | 0.1% - 1.0% | Depends on liquidity, position size |
| Price Impact | 0.05% - 0.5% | Larger trades = more impact |
| Spread | 0.1% - 0.3% | Bid/ask spread on the pool |

#### Price Impact Explained

Price impact occurs because AMM pools use the constant product formula (`x × y = k`). As you buy tokens, each successive token costs more because you're depleting the pool.

| Your Trade Size vs Pool Liquidity | Price Impact |
|----------------------------------|--------------|
| <0.1% of pool | Negligible |
| 1% of pool | ~0.5% |
| 5% of pool | ~2.5% |
| 10% of pool | ~5%+ |

Jupiter mitigates this by splitting across multiple pools, but impact is unavoidable.

#### Round-Trip Consideration

Since each trade involves BUY then SELL (or vice versa), double the overhead:

```
Round-trip cost ≈ 2 × single-trade overhead
$1,000 position → ~0.4% - 1.0% round-trip overhead
```

#### Special Case: Wrapped Token Pairs (e.g., TAO:WTAO)

Wrapped tokens (like WTAO for TAO) often trade at a premium/discount to the native token due to bridge friction and liquidity isolation. This spread adds to trading costs:

| Pair Type | Typical Break-Even Move |
|-----------|-------------------------|
| Unrelated tokens (BTC:WTAO) | ~0.8% |
| Wrapped pairs (TAO:WTAO) | ~1.3% (includes spread) |

### Pool Liquidity Analysis

Jupiter's Price API returns aggregated liquidity across all pools for a token:

```python
# Example: Check WTAO liquidity
curl "https://api.jup.ag/price/v3?ids={WTAO_MINT}"
# Returns: { "liquidity": 490000, "usdPrice": 326.33, ... }
```

#### Safe Trade Sizes (targeting ~1% price impact)

| Token | Liquidity | Safe Trade Size |
|-------|-----------|-----------------|
| SOL | $753M | ~$7.5M |
| JLP | $11.7M | ~$117K |
| BONK | $4.0M | ~$40K |
| WTAO | $490K | ~$5K |

### Proposed Analysis Output

```
═══════════════════════════════════════════════════════════════════════
                    PROFITABILITY ANALYSIS: BTC → WTAO
═══════════════════════════════════════════════════════════════════════

STEP 1: COST ANALYSIS
  Follower liquidity:     $490,000
  Position size:          $1,000
  Estimated round-trip:   ~0.8%
  Break-even move:        0.8%
  Target profit (0.5%):   1.3%

STEP 2: VOLATILITY ANALYSIS (from collected data)
  ┌──────────────┬────────────┬────────────┬────────────┐
  │ Interval     │ Median Δ%  │ % > 0.8%   │ % > 1.3%   │
  ├──────────────┼────────────┼────────────┼────────────┤
  │ 1 min        │ 0.05%      │ 2%         │ 0.5%       │
  │ 5 min        │ 0.15%      │ 8%         │ 3%         │
  │ 15 min       │ 0.35%      │ 18%        │ 9%         │
  │ 1 hour       │ 0.80%      │ 45%        │ 28%        │  ← VIABLE
  │ 4 hour       │ 1.50%      │ 65%        │ 52%        │  ← BEST
  └──────────────┴────────────┴────────────┴────────────┘
  
  Recommended interval: 1hr+ (45% chance of profitable move)

STEP 3: CORRELATION ANALYSIS (at recommended interval)
  Optimal lag:            42 min (0.7 periods)
  Correlation:            0.72
  Granger p-value:        0.003 (significant)
  Confidence:             0.78 (HIGH)
  
═══════════════════════════════════════════════════════════════════════
VERDICT: VIABLE - Trade 1hr intervals, expect ~45% opportunity rate
═══════════════════════════════════════════════════════════════════════
```

### Implementation (Completed)

Profitability analysis is integrated into `correlation_tracker.py` via the `--profitability` flag.

#### Usage Modes

| Mode | Command | Description |
|------|---------|-------------|
| Single pair | `--profitability --leader BTC --follower WTAO` | Analyze one specific pair |
| Leader filter | `--profitability --leader BTC` | Analyze BTC with all significant followers |
| Follower filter | `--profitability --follower WTAO` | Analyze WTAO with all significant leaders |
| All pairs | `--profitability` | Analyze all significant pairs |

#### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--profitability` | `false` | Enable profitability analysis mode |
| `--position-size` | `1000` | Position size in USD for cost calculations |
| `--target-profit` | `0.5` | Target profit percentage per trade |

#### Examples

```bash
# Single pair analysis
python correlation_tracker.py --analyze --profitability --leader BTC --follower WTAO

# All pairs with custom position size
python correlation_tracker.py --analyze --profitability --position-size 500

# All followers for a specific leader
python correlation_tracker.py --analyze --profitability --leader SOL

# All leaders for a specific follower  
python correlation_tracker.py --analyze --profitability --follower WTAO
```

#### Batch Output

When analyzing multiple pairs, a summary table is displayed:

```
==========================================================================================
                         PROFITABILITY ANALYSIS SUMMARY
==========================================================================================
┌─────────────────────────┬─────────────┬──────────────┬───────────────┬─────────────────────┐
│ Pair                    │ Break-even  │ Best Interval│ Correlation   │ Verdict             │
├─────────────────────────┼─────────────┼──────────────┼───────────────┼─────────────────────┤
│ BTC → SOL               │       0.50% │       4 hour │         0.171 │ ✓ VIABLE            │
│ SOL → WTAO              │       0.70% │       1 hour │        -0.129 │ ✓ VIABLE            │
└─────────────────────────┴─────────────┴──────────────┴───────────────┴─────────────────────┘

Summary: 2 pairs analyzed
  ✓ VIABLE: 2
  ? POSSIBLY VIABLE: 0
  ⚠ VOLATILITY OK, CORRELATION WEAK: 0
  ✗ NOT VIABLE: 0
==========================================================================================
```

#### Verdict Categories

| Verdict | Meaning |
|---------|---------|
| **VIABLE** | Sufficient volatility AND statistically significant correlation |
| **POSSIBLY VIABLE** | Sufficient volatility, correlation exists but Granger not significant |
| **VOLATILITY OK, CORRELATION WEAK** | Sufficient volatility but weak correlation |
| **NOT VIABLE** | Insufficient volatility at all intervals |

### Design Decisions

1. **Data source for volatility analysis**
   - Uses collected correlation data (resampled at multiple intervals)

2. **Multi-interval analysis**
   - Automatically tests 5 intervals: 1min, 5min, 15min, 1hr, 4hr

3. **Liquidity source**
   - Fetches live liquidity from Jupiter Price API V3
   - Falls back to estimates for common tokens if API unavailable

4. **Viability threshold**
   - Median move ≥ break-even OR ≥30% of moves exceed break-even

5. **Batch mode workflow**
   - Runs discovery first to find significant pairs
   - Filters by leader/follower if specified
   - Deduplicates pairs before analysis

---

## Candidate Coins Datastore

### Overview

The Candidate Coins Datastore provides a persistent, human-editable list of coins for the leading indicator tester to analyze. This enables integration with external discovery tools (LLMs, screeners, social sentiment analyzers) that can programmatically add candidate coins for correlation analysis.

### File Format

**Location:** `./correlation_data/candidate_coins.csv`

**Format:** CSV with header row

```csv
symbol,blockchain,added_at,updated_at,source
BTC,Bitcoin,2026-06-01T12:00:00Z,,manual
ETH,Ethereum,2026-06-01T12:00:00Z,,manual
SOL,Solana,2026-06-01T12:00:00Z,,manual
BONK,Solana,2026-06-01T14:30:00Z,,llm_trending
WIF,Solana,2026-06-01T14:30:00Z,2026-06-01T18:00:00Z,whale_alert
TAO,Bittensor,2026-06-01T15:00:00Z,,social_sentiment
PEPE,Solana,2026-06-01T16:00:00Z,,price_screener
```

**Column Definitions:**
| Column | Description | Required |
|--------|-------------|----------|
| `symbol` | Token/coin symbol (e.g., BTC, SOL, BONK) | Yes |
| `blockchain` | Blockchain or asset class (e.g., Solana, Bitcoin, Ethereum, Stock) | Yes |
| `added_at` | ISO 8601 timestamp when coin was added | Yes |
| `updated_at` | ISO 8601 timestamp when coin was last updated (empty if never updated) | No |
| `source` | Origin of the candidate (e.g., manual, llm_trending, whale_alert, social_sentiment) | Yes |

### Usage

```bash
# Use candidate coins instead of --coins parameter
python leading_indicator_tester.py --auto-select --use-candidate-coins

# Combine with other options
python leading_indicator_tester.py --auto-select --use-candidate-coins --skip-collection --min-confidence 0.3

# Override: --coins takes precedence if both specified
python leading_indicator_tester.py --auto-select --coins BTC,SOL --use-candidate-coins  # Uses BTC,SOL only
```

### Parameter

```
--use-candidate-coins    Load coins from candidate_coins.csv instead of --coins parameter
```

### Behavior

1. **Loading:** When `--use-candidate-coins` is true, read `candidate_coins.csv` from `--data-dir`
2. **Filtering:** Extract only coins matching the current trading context (e.g., Solana-only for DEX trading)
3. **Deduplication:** Remove duplicate symbols (case-insensitive)
4. **Fallback:** If file doesn't exist or is empty, warn and require `--coins`

### Integration with External Tools

External tools can append to the CSV:

```python
# Example: LLM-based coin discovery tool
import csv
from datetime import datetime, timezone

def add_candidate_coin(symbol: str, blockchain: str, source: str,
                       csv_path: str = './correlation_data/candidate_coins.csv'):
    """Add a candidate coin to the datastore."""
    added_at = datetime.now(timezone.utc).isoformat()
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([symbol.upper(), blockchain, added_at, '', source])
```

```bash
# Manual addition
echo "RENDER,Solana,$(date -u +%Y-%m-%dT%H:%M:%SZ),,manual" >> ./correlation_data/candidate_coins.csv
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       CANDIDATE COINS INTEGRATION                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  External Sources                    Datastore              System           │
│  ─────────────────                   ─────────              ──────           │
│                                                                              │
│  ┌──────────────┐                                                            │
│  │ LLM Analysis │───┐                                                        │
│  │ (trending)   │   │                                                        │
│  └──────────────┘   │                                                        │
│                     │    ┌─────────────────┐    ┌─────────────────────────┐ │
│  ┌──────────────┐   │    │                 │    │                         │ │
│  │ Social       │───┼───▶│ candidate_coins │───▶│ leading_indicator_      │ │
│  │ Sentiment    │   │    │ .csv            │    │ tester.py               │ │
│  └──────────────┘   │    │                 │    │ --use-candidate-coins   │ │
│                     │    └─────────────────┘    └─────────────────────────┘ │
│  ┌──────────────┐   │           ▲                                           │
│  │ Whale Alert  │───┤           │                                           │
│  │ Integration  │   │           │                                           │
│  └──────────────┘   │    ┌──────┴────────┐                                  │
│                     │    │ Human Manual  │                                  │
│  ┌──────────────┐   │    │ Edits         │                                  │
│  │ Price        │───┘    └───────────────┘                                  │
│  │ Screeners    │                                                            │
│  └──────────────┘                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Design Decisions

1. **Blockchain filtering:** No additional filtering at CSV load time. Existing downstream filtering handles blockchain compatibility. Failures may occur later in the pipeline (e.g., token not tradeable on Jupiter).

2. **Coin validation:** No pre-validation. System relies on existing error handling when coins don't exist or aren't available.

3. **Timestamp/source tracking:** Yes - `added_at`, `updated_at`, and `source` columns included for attribution and potential future pruning.

4. **Automatic cleanup:** No automatic removal. Coins that fail correlation analysis are kept - market conditions change and correlations may emerge later.

5. **Priority/weighting:** Not for MVP. Possible future enhancement.

6. **Conflict with --coins:** `--coins` takes precedence. No merge of sources.

7. **Multi-blockchain pairs:** No special marking. Existing error handling addresses cross-chain issues.

8. **Maximum candidates:** Not for MVP. No limit enforced.

