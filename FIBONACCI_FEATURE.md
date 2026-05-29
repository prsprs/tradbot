# Fibonacci Retracement Analysis Feature

## Overview

This document describes a proposed enhancement to analyze historical price data for Fibonacci retracement levels and evaluate their effectiveness as support/resistance indicators.

---

## Background: Fibonacci Retracements

Fibonacci retracement is a technical analysis tool that uses horizontal lines to indicate potential support and resistance levels. The key levels are derived from the Fibonacci sequence ratios:

| Level | Ratio | Description |
|-------|-------|-------------|
| 0.0%  | 0.000 | The high point |
| 23.6% | 0.236 | Shallow retracement |
| 38.2% | 0.382 | Common retracement |
| 50.0% | 0.500 | Midpoint (not Fibonacci, but commonly used) |
| 61.8% | 0.618 | Golden ratio retracement |
| 78.6% | 0.786 | Deep retracement |
| 100%  | 1.000 | The low point |

**Calculation:**
```
retracement_price = high - (high - low) * ratio
```

For example, if high = $100 and low = $80:
- 23.6% level = $100 - ($20 * 0.236) = $95.28
- 38.2% level = $100 - ($20 * 0.382) = $92.36
- 50.0% level = $100 - ($20 * 0.500) = $90.00
- 61.8% level = $100 - ($20 * 0.618) = $87.64

---

## MVP Scope

### Goal
Analyze historical data to identify Fibonacci retracement levels and report whether these levels acted as support/resistance (indicated by price bounces).

### Output (Reporting Only)
For MVP, the system will generate a report showing:
1. Identified high/low points in the analysis window
2. Calculated Fibonacci levels
3. Count of "touches" or "bounces" at each level
4. Statistical significance of each level as support/resistance

### Non-Goals for MVP
- Automated trading signals based on Fibonacci levels
- Real-time Fibonacci level monitoring
- Multi-timeframe analysis

---

## Architecture

### Subsystem Design

The Fibonacci analyzer should be a **standalone module** that can be used in two modes:

```
┌─────────────────────────────────────────────────────────────────┐
│                    FibonacciAnalyzer                            │
├─────────────────────────────────────────────────────────────────┤
│  Inputs:                                                        │
│    - Price history (list of timestamps + prices)                │
│    - Analysis window (e.g., 24hr, 7d)                          │
│    - Granularity (e.g., 1min, 5min, 1hr)                       │
│    - Tolerance for "touch" detection (e.g., 0.5%)              │
│    - Confirmation periods (N) for bounce validation            │
│    - Minimum touches to report a level as significant          │
│                                                                 │
│  Outputs:                                                       │
│    - FibonacciReport dataclass                                  │
│      - high, low, high_timestamp, low_timestamp                │
│      - levels: Dict[str, FibLevel]                             │
│      - summary statistics                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Usage Modes

**Mode 1: Standalone Analysis (JSONL Data)**
```bash
python fibonacci_analyzer.py --symbol SOL --window 7d \
    --data-dir ./correlation_data \
    --confirmation-periods 3 \
    --touch-tolerance 0.5 \
    --min-touches 2
```

**Mode 2: Standalone Analysis (CSV OHLCV Data)**
```bash
python fibonacci_analyzer.py --symbol BTC --csv btc_ohlcv.csv \
    --data-dir ./correlation_data \
    --confirmation-periods 3 \
    --touch-tolerance 0.5
```

**Mode 3: Multi-Symbol Analysis**
```bash
# Analyze specific symbols
python fibonacci_analyzer.py --symbol SOL,BTC,ETH --window 7d

# Analyze ALL symbols in data directory
python fibonacci_analyzer.py --window 7d --summary-only
```

**Mode 4: Preflight Integration**
```bash
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live \
    --fibonacci-analysis \
    --fib-window 7d \
    --fib-confirmation-periods 5 \
    --fib-min-touches 2
```

### Data Input Formats

**Format 1: JSONL (from correlation_tracker)**
- Located in `--data-dir` subdirectories
- Records with `symbol`, `timestamp`, `price` fields
- Loaded automatically based on `--symbol` and `--window`

**Format 2: CSV OHLCV (external data sources)**
- Standard OHLCV format with columns: timestamp, Open, High, Low, Close, Volume
- Timestamp column auto-detected (first column)
- Uses **Close** prices for Fibonacci analysis
- File located in `--data-dir` directory
- Requires `--symbol` to identify the asset

Example CSV format:
```csv
Etc/UTC,Open,High,Low,Close,Volume
2026-05-29T00:00:00+00:00,73498.3,73785.2,73498.3,73774.4,14287
2026-05-29T00:45:00+00:00,73726.6,73784.8,73449,73524.8,13168
```

---

## Data Structures

```python
@dataclass
class FibonacciLevel:
    ratio: float           # 0.236, 0.382, etc.
    price: float           # Calculated price at this level
    touch_count: int       # Number of times price touched this level
    bounce_count: int      # Number of times price bounced off this level
    breakthrough_count: int # Number of times price broke through
    avg_bounce_magnitude: float  # Average % move after bounce
    
@dataclass
class FibonacciReport:
    symbol: str
    analysis_window: str
    window_start: datetime
    window_end: datetime
    high_price: float
    high_timestamp: datetime
    low_price: float
    low_timestamp: datetime
    trend_direction: str   # 'up' if low before high, 'down' if high before low
    levels: Dict[str, FibonacciLevel]  # keyed by ratio string
    
    # Summary statistics
    most_respected_level: str
    overall_effectiveness: float  # % of touches that resulted in bounces
```

---

## Algorithm

### Step 1: Identify High/Low Points
```python
def find_swing_points(prices: List[PricePoint], window_seconds: int):
    """
    Find the significant high and low within the analysis window.
    
    Options:
    A) Simple: Absolute high and low in window
    B) Advanced: Local maxima/minima with minimum distance
    """
```

### Step 2: Calculate Fibonacci Levels
```python
def calculate_fib_levels(high: float, low: float) -> Dict[str, float]:
    ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    return {
        f"{r*100:.1f}%": high - (high - low) * r 
        for r in ratios
    }
```

### Step 3: Detect Touches and Bounces
```python
def detect_level_interactions(
    prices: List[PricePoint],
    levels: Dict[str, float],
    tolerance_pct: float = 0.5,
    confirmation_periods: int = 3
):
    """
    For each price point, check if it's within tolerance of a Fib level.
    
    A "touch" = price comes within tolerance of level
    A "bounce" = after touch, price stays on same side of level for N periods
    A "breakthrough" = after touch, price moves through level and stays for N periods
    
    Args:
        confirmation_periods: Number of periods price must stay above/below
                              level after touch to confirm bounce vs breakthrough
    """
```

---

## Design Alternatives

### Alternative 1: Swing Point Detection

**Option A: Absolute High/Low**
- Simple: just find max and min in window
- Pros: Deterministic, easy to implement
- Cons: May miss intermediate swing points

**Option B: Local Extrema Detection**
- Find multiple swing highs/lows using peak detection
- Generate multiple Fibonacci grids
- Pros: More comprehensive analysis
- Cons: More complex, potential for conflicting signals

**Recommendation:** Start with Option A for MVP, add Option B later.

### Alternative 2: Touch Detection Tolerance

**Option A: Fixed Percentage**
- e.g., "within 0.5% of level counts as touch"
- Pros: Simple, consistent
- Cons: May not scale well across different price ranges

**Option B: ATR-Based Tolerance**
- Use Average True Range to set dynamic tolerance
- Pros: Adapts to volatility
- Cons: Requires additional data/calculation

**Recommendation:** Option A for MVP with configurable percentage.

### Alternative 3: Bounce Classification

**Option A: Simple Reversal**
- If price moves X% away from level after touch, it's a bounce
- Pros: Simple
- Cons: May count noise as bounces

**Option B: Candlestick Pattern Recognition**
- Look for reversal patterns (hammer, engulfing, etc.)
- Pros: More sophisticated
- Cons: Requires candlestick data, more complex

**Option C: Time-Based Confirmation** ✓
- Price must stay above/below level for N periods
- Pros: Filters noise, more reliable bounce detection
- Cons: Delayed classification

**Recommendation:** Option C - time-based confirmation with configurable N periods parameter. This filters out noise from brief touches that don't represent meaningful support/resistance interaction.

### Alternative 4: Trend Direction Handling

**Option A: Always High-to-Low**
- Calculate retracements from high down to low
- Use for both uptrends and downtrends

**Option B: Trend-Aware**
- In uptrend (low before high): retracement levels are support
- In downtrend (high before low): retracement levels are resistance
- Adjust interpretation accordingly

**Recommendation:** Option B - trend awareness is important for interpretation.

---

## Open Questions

### Data Questions

1. **What granularity of price data is needed?** ✓ RESOLVED
   - **Decision:** Parameter-controlled granularity
   - User specifies desired granularity via CLI parameter

2. **Should we use OHLC candles or just close prices?** ✓ RESOLVED
   - **Decision:** Close prices for MVP
   - Simpler implementation, can extend to OHLC later if needed

3. **How do we handle gaps in data?** ✓ RESOLVED
   - **Decision:** Skip gaps
   - Analysis continues with available data points

### Analysis Questions

4. **What constitutes a "significant" bounce?** ✓ RESOLVED
   - **Decision:** Either time-based OR percentage-based, parameter-controlled
   - User can choose confirmation method via parameters

5. **How do we handle levels that are very close together?** ✓ RESOLVED
   - **Decision:** N/A for MVP
   - MVP uses single set of levels based on total range (lowest to highest)
   - No overlapping level concern with this approach

6. **Should we track re-tests?** ✓ RESOLVED
   - **Decision:** Yes, track re-tests
   - Important for understanding level validity over time

### Integration Questions

7. **How should Fib analysis affect trading decisions?** ⏳ DEFERRED
   - **Decision:** TBD - no trading signals for MVP
   - MVP is reporting-only; trading integration planned for future phase

8. **Which coin's Fibonacci levels matter?** ✓ RESOLVED
   - **Decision:** Follower's levels for MVP
   - Since we're trading the follower, its support/resistance levels are most relevant

9. **Should Fib analysis be run once at startup or continuously?** ✓ RESOLVED
   - **Decision:** Run once at startup
   - Simpler implementation for MVP; levels based on historical window

### Statistical Questions

10. **What's the baseline for "effective" support/resistance?** ✓ RESOLVED
    - **Decision:** A Fib level is "potentially predictive" if:
      - Price descends to within X% of a lower Fib level but does not break below it, OR
      - Price ascends to within Y% of an upper Fib level but does not break above it
    - We are hypothesis-testing Fib levels specifically, not arbitrary price points
    - **Caveat:** Risk that bounce off a Fib level could be coincidental is recognized
    - MVP reports observations; statistical rigor can be added in future phases

11. **How many data points are needed for statistical significance?** ✓ RESOLVED
    - **Decision:** Parameter-controlled minimum touches
    - User specifies `--min-touches N` to filter which levels are reported as significant

---

## Future Enhancements

### Phase 2: Active Monitoring
- Real-time alerts when price approaches Fib levels
- Integration with trade signals

### Phase 3: Multi-Timeframe Analysis
- Analyze multiple windows (1d, 7d, 30d)
- Identify confluent levels across timeframes

### Phase 4: Fibonacci Extensions
- Project levels beyond 100% for target prices
- Useful for profit-taking decisions

### Phase 5: ML Integration
- Train model on which levels are most predictive
- Combine with other technical indicators

---

## Implementation Plan

### MVP Tasks
1. [ ] Create `fibonacci_analyzer.py` module
2. [ ] Implement `FibonacciLevel` and `FibonacciReport` dataclasses
3. [ ] Implement high/low detection (Option A: absolute)
4. [ ] Implement level calculation
5. [ ] Implement touch/bounce detection
6. [ ] Create CLI for standalone usage
7. [ ] Add `--fibonacci-analysis` flag to `leading_indicator_tester.py`
8. [ ] Generate formatted report output
9. [ ] Write unit tests

### Estimated Effort
- MVP: 2-3 days
- Phase 2 (Active Monitoring): 1-2 days
- Phase 3 (Multi-Timeframe): 2-3 days

---

## Example Output (MVP)

```
======================================================================
                    FIBONACCI RETRACEMENT ANALYSIS
======================================================================
Symbol: SOL
Analysis Window: 7 days (2026-05-21 to 2026-05-28)
Trend Direction: UPTREND (low before high)

Price Range:
  High: $185.42 (2026-05-27 14:30 UTC)
  Low:  $142.18 (2026-05-22 03:15 UTC)
  Range: $43.24 (30.4%)

----------------------------------------------------------------------
                         FIBONACCI LEVELS
----------------------------------------------------------------------
Level     Price      Touches  Bounces  Breakthroughs  Effectiveness
----------------------------------------------------------------------
0.0%      $185.42    1        -        -              (High)
23.6%     $175.22    4        3        1              75.0%
38.2%     $168.90    7        5        2              71.4%
50.0%     $163.80    5        2        3              40.0%
61.8%     $158.70    3        2        1              66.7%
78.6%     $151.42    2        2        0              100.0%
100.0%    $142.18    1        -        -              (Low)
----------------------------------------------------------------------

Most Respected Level: 78.6% ($151.42) - 100% bounce rate
Overall Effectiveness: 66.7% (14/21 touches resulted in bounces)

Interpretation:
  • Strong support cluster at 61.8%-78.6% zone ($151-159)
  • 50% level showed weakness (more breakthroughs than bounces)
  • Consider these levels for entry/exit planning
======================================================================
```

---

## References

- [Investopedia: Fibonacci Retracement](https://www.investopedia.com/terms/f/fibonacciretracement.asp)
- [TradingView: Fibonacci Retracement Tool](https://www.tradingview.com/support/solutions/43000502024-fibonacci-retracement/)
