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
- ~~Automated trading signals based on Fibonacci levels~~ → Now Phase 2
- Real-time Fibonacci level monitoring
- Multi-timeframe analysis
- Continuous Fib re-analysis during trading (future enhancement)

---

## Phase 2: Trading Integration (`--use-fib`)

### Overview

When `--use-fib` is specified in `leading_indicator_tester.py`, Fibonacci analysis will be used to filter and validate trade signals from the leading indicator system.

### Trading Rules

**Rule 1: Trend-Direction Filtering**
- Trades are only executed in the direction of the Fibonacci trend
- **Uptrend** (low before high): Only BUY signals are valid
- **Downtrend** (high before low): Only SELL signals are valid

**Rule 2: Buy Signal Validation (Uptrend Only)**
- When the leading indicator triggers a BUY signal:
  - Price must be near the **low point**, OR
  - Price must be near an **effective support level** (a Fib level below current price with proven bounce history)

**Rule 3: Sell Signal Validation (Downtrend Only)**
- When the leading indicator triggers a SELL signal:
  - Price must be near the **high point**, OR
  - Price must be near an **effective resistance level** (a Fib level above current price with proven bounce history)

**Rule 4: Range Invalidation**
- If current price moves **outside** the high-low range used for Fib analysis:
  - The Fib levels are no longer valid
  - Trading must **halt** with a clear message
  - Future enhancement: Re-run Fib analysis with new data and continue

### Signal Flow

```
Leading Indicator Signal
         │
         ▼
   ┌─────────────────┐
   │ Price in Range? │──NO──► HALT: "Fib analysis invalidated"
   └────────┬────────┘
            │ YES
            ▼
   ┌─────────────────┐
   │ Signal matches  │──NO──► SKIP: "Signal against Fib trend"
   │ Fib trend?      │
   └────────┬────────┘
            │ YES
            ▼
   ┌─────────────────┐
   │ Near support/   │──NO──► SKIP: "Not near effective level"
   │ resistance?     │
   └────────┬────────┘
            │ YES
            ▼
      EXECUTE TRADE
```

### CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--use-fib` | Enable Fibonacci-based trade filtering | false |
| `--fib-window` | Time window for Fib analysis | 7d |
| `--fib-tolerance` | % tolerance for "near level" detection | 0.5 |
| `--fib-min-effectiveness` | Min bounce rate to consider level "effective" | 60% |
| `--fib-min-touches` | Min touches for level to be considered | 2 |

### Example Usage

```bash
# Paper trading with Fibonacci filtering
python leading_indicator_tester.py --pair BTC:SOL --use-fib --fib-window 7d

# Live trading with Fib validation
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live \
    --use-fib --fib-tolerance 0.75 --fib-min-effectiveness 50
```

### Resolved Design Decisions

1. **What defines "near" a level?**
   - ✓ Use same tolerance as touch detection (`--fib-tolerance`, default 0.5%)

2. **What constitutes an "effective" level?**
   - ✓ Bounce rate >= `--fib-min-effectiveness` (default 60%) AND touches >= `--fib-min-touches` (default 2)

3. **How should range invalidation work?**
   - ✓ Use touch tolerance for boundary checking (consistent with level detection)
   - Halt immediately when price crosses boundary + tolerance

4. **When to run the Fib analysis?**
   - ✓ On startup: Load from Fib Report Cache (see below)
   - If no cached report exists, run analysis and cache result

5. **Data source for Fib analysis?**
   - ✓ **Fib Report Cache** - persistent JSON storage for analysis results
   - Written by: `fibonacci_analyzer.py` (standalone) or `leading_indicator_tester.py --fibonacci-analysis`
   - Read by: `leading_indicator_tester.py --use-fib`

6. **Interaction with existing `--directional-filter`?**
   - ✓ Independent filters with AND logic
   - If filters conflict (e.g., directional=BUY only, fib=downtrend), warn and halt
   - This is correct behavior - no valid trades possible

7. **Multiple effective levels - which to use?**
   - ✓ Use ANY level within tolerance that meets effectiveness minimum
   - Trade is valid if price is near any qualifying level

### Fib Report Cache

A persistent storage mechanism for Fibonacci analysis results.

**Location:** `./correlation_data/fib_reports/`

**File Format:** `{SYMBOL}_fib_report.json`

**Structure:**
```json
{
  "symbol": "SOL",
  "generated_at": "2026-05-29T19:00:00+00:00",
  "analysis_window": "7d",
  "window_start": "2026-05-22T19:00:00+00:00",
  "window_end": "2026-05-29T19:00:00+00:00",
  "high_price": 185.42,
  "high_timestamp": "2026-05-27T14:30:00+00:00",
  "low_price": 142.18,
  "low_timestamp": "2026-05-22T03:15:00+00:00",
  "trend_direction": "up",
  "levels": {
    "0.0%": {"ratio": 0.0, "price": 185.42, "touches": 1, "bounces": 0, "effectiveness": null},
    "23.6%": {"ratio": 0.236, "price": 175.22, "touches": 4, "bounces": 3, "effectiveness": 75.0},
    ...
  },
  "most_respected_level": "78.6%",
  "overall_effectiveness": 66.7
}
```

**Writers:**
- `fibonacci_analyzer.py` - saves after analysis (with `--save-report` or auto-save)
- `leading_indicator_tester.py --fibonacci-analysis` - saves after analysis

**Readers:**
- `leading_indicator_tester.py --use-fib` - loads on startup
- If cache miss or stale, can run fresh analysis

**Cache Behavior:**
- Reports are keyed by symbol
- New analysis overwrites previous report
- Future: Add `--fib-max-age` to invalidate stale reports

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

## Phase 3: Autonomous Trading (`--auto-select`)

### Overview

The `--auto-select` feature enables fully autonomous trading by automatically:
1. Collecting price data for a configurable period
2. Running correlation and profitability analysis
3. Generating Fibonacci analysis for candidate pairs
4. Selecting the optimal pair and parameters
5. Beginning trading with minimal human intervention

### Goals

- **Zero-touch startup**: Start the system and walk away
- **Data-driven pair selection**: Choose the best pair based on actual market data
- **Adaptive parameters**: Auto-configure lag times, intervals, and filters
- **Integrated Fib analysis**: Use Fib levels to enhance trade timing

### Workflow

The auto-select feature orchestrates existing tools - no new data collection code is needed.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AUTO-SELECT MODE                              │
│         (Orchestrates existing correlation_tracker + tools)          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 1: Data Collection (uses correlation_tracker.py)              │
│ - Runs: correlation_tracker.py --coins X --interval 30 --duration Y │
│ - Uses EXACT same collection logic, no changes                      │
│ - Stores to --data-dir (default: ./correlation_data)                │
│ - OR: --skip-collection to use existing data                        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 2: Correlation Analysis (uses correlation_tracker.py)         │
│ - Runs: correlation_tracker.py --analyze --data-dir X               │
│ - Reads discovery_report.json output                                │
│ - Filters pairs by min_confidence threshold                         │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 3: Profitability Analysis (uses preflight.py)                 │
│ - Runs preflight for each candidate pair                            │
│ - Uses existing PreflightValidator class                            │
│ - Filters out pairs with insufficient volatility                    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 4: Fibonacci Analysis (uses fibonacci_analyzer.py)            │
│ - Runs Fib analysis on follower candidates                          │
│ - Uses existing FibonacciAnalyzer class                             │
│ - Caches reports via save_fib_report()                              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 5: Pair Selection & Scoring                                   │
│ - NEW: AutoSelectScorer class                                       │
│ - Combines scores from correlation, profitability, Fib              │
│ - Ranks and selects top pair(s)                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 6: Trading (uses leading_indicator_tester.py)                 │
│ - Auto-configures from analysis results:                            │
│   • --pair from selection                                           │
│   • Lag time from discovery_report                                  │
│   • --use-fib with cached Fib report                                │
│   • --directional-filter based on profitability                     │
│ - Periodic re-analysis triggers return to Phase 2                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Design Decision: Reuse Existing Code

The auto-select feature is an **orchestrator**, not new functionality:

| Phase | Existing Code | New Code Needed |
|-------|---------------|-----------------|
| Collection | `correlation_tracker.py` collector mode | None - subprocess call |
| Correlation | `correlation_tracker.py` analyzer mode | None - subprocess call |
| Profitability | `preflight.py` / `PreflightValidator` | None - import and call |
| Fibonacci | `fibonacci_analyzer.py` / `FibonacciAnalyzer` | None - import and call |
| Selection | - | `AutoSelectScorer` class (NEW) |
| Trading | `leading_indicator_tester.py` | Integration hooks |

This means:
- Collection interval, rate limiting, error handling → already solved
- Analysis logic, confidence scoring → already solved  
- Fib calculations, caching → already solved
- Only new code: scoring/selection logic and orchestration

### CLI Arguments

Auto-select mode uses **existing CLI parameters** - no new parameter names needed for most functionality.

**Auto-Select Control** (new):

| Argument | Description | Default |
|----------|-------------|---------|
| `--auto-select` | Enable autonomous pair selection mode | false |
| `--skip-collection` | Skip collection phase, use existing data | false |

**Required with `--auto-select`:**

| Argument | Description |
|----------|-------------|
| `--use-fib` | Must be explicitly specified with `--auto-select` |

**Existing Parameters Used Throughout:**

| Parameter | Used In | Default |
|-----------|---------|---------|
| `--coins` | Collection phase | *(required)* |
| `--interval` | Collection phase | 30s |
| `--duration` | Collection + Trading | *(indefinite)* |
| `--data-dir` | All phases | ./correlation_data |
| `--min-samples` | Correlation analysis | 500 |
| `--min-confidence` | Correlation analysis | 0.6 |
| `--trading-mode` | Trading phase | paper |
| `--position-size` | Trading phase | 1000.0 |
| `--use-fib` | **Required** with `--auto-select` | false |
| `--fib-touch-tolerance` | Fib analysis + trading | 0.5 |
| `--fib-min-effectiveness` | Fib analysis + trading | 60 |
| `--directional-filter` | Trading phase (auto-configured) | false |

**Note:** `--auto-select` requires `--use-fib` to be explicitly specified. The system auto-configures `--directional-filter` based on profitability analysis. All other parameters use their existing defaults or user-specified values.

### Example Usage

```bash
# Full autonomous mode - collect 48hr of data, analyze, select, paper trade
python leading_indicator_tester.py --auto-select --use-fib \
    --coins BTC,ETH,SOL,BONK,WIF \
    --interval 30 \
    --duration 48hr \
    --trading-mode paper

# Skip collection, use existing data, custom thresholds
python leading_indicator_tester.py --auto-select --use-fib \
    --skip-collection \
    --min-confidence 0.7 \
    --fib-min-effectiveness 70 \
    --trading-mode paper

# Live autonomous trading with existing data
python leading_indicator_tester.py --auto-select --use-fib \
    --skip-collection \
    --trading-mode live \
    --max-trade-usd 50 \
    --position-size 50
```

**Parameter Flow:**
- Collection: `--coins`, `--interval`, `--duration`
- Analysis: `--min-samples`, `--min-confidence`, `--data-dir`
- Fib: `--fib-window`, `--fib-touch-tolerance`, `--fib-min-effectiveness`
- Trading: `--trading-mode`, `--position-size`

### Pair Ranking (When Multiple Candidates)

If multiple pairs pass eligibility, rank by correlation confidence (highest first):

```
eligible_pairs = [p for p in all_pairs if passes_eligibility(p)]
ranked_pairs = sorted(eligible_pairs, key=lambda p: p.confidence, reverse=True)
```

Display ranked candidates and prompt user to select.

### Safety Mechanisms

1. **Minimum Data Requirements** (via existing parameters)
   - Won't proceed if samples < `--min-samples` (default 500)
   - Won't trade if no pairs meet `--min-confidence` threshold (default 0.6)

2. **Confirmation Prompts** (live mode)
   - Display selected pair and parameters
   - Require confirmation before trading starts
   - Option: `--auto-confirm` to skip (for scheduled jobs)

3. **Circuit Breakers**
   - Max consecutive losses before pause
   - Max daily loss limit
   - Fib range invalidation halts trading

4. **Logging & Monitoring**
   - Log all selection decisions with reasoning
   - Output selection report to file
   - Send alerts on pair changes or trading halts

### Design Decisions (MVP)

1. **Pair Selection & Eligibility**
   - Set minimum requirements for eligibility:
     - Correlation: meets `--min-confidence` threshold
     - Fib effectiveness: meets `--fib-min-effectiveness` threshold
     - Profitability: preflight shows viable direction
   - **No candidates eligible**: Halt with explanation of why each pair failed
   - **Multiple candidates eligible**: Pause, display ranked candidates with scores, prompt user to select a pair
   - **One candidate eligible**: Auto-select and proceed (with confirmation in live mode)

2. **Single Pair Trading**
   - MVP only trades one pair at a time
   - `--auto-top-pairs` deferred to future version

3. **No Re-Analysis for MVP**
   - Analysis runs once at startup
   - User must restart to re-analyze
   - Re-analysis feature deferred to future version

4. **Fib Integration**
   - `--auto-select` always requires `--use-fib` to be explicitly specified
   - Pairs with poor Fib effectiveness are filtered out by eligibility requirements
   - `--collect-duration` deferred - use `--duration` for collection phase, `--skip-collection` for existing data

5. **Paper vs Live: User Decision**
   - No mandatory paper trading period - user decides risk level
   - **Important**: Data validity is time-sensitive. Extended paper trading may cause Fib levels to become stale. If paper testing takes too long, the analysis may no longer reflect current market conditions.
   - Recommendation: Use `--skip-collection` with fresh data, or keep paper testing brief

6. **Monitoring & Shutdown**
   - No cron/systemd integration for MVP
   - Uses existing live trading monitoring mechanisms (same as leading_indicator_tester)
   - **Enhancement**: Add currently-traded pair to periodic status output (alongside HTTP request notifications)
   - Graceful shutdown: same behavior as existing live trading

### Eligibility Parameters (All Existing)

Auto-select uses **existing parameters** as eligibility thresholds - no new parameters needed:

| Parameter | Purpose | Default | Source |
|-----------|---------|---------|--------|
| `--min-confidence` | Min correlation confidence | 0.6 | correlation_tracker.py |
| `--fib-min-effectiveness` | Min Fib bounce rate % | 60 | leading_indicator_tester.py |
| Profitability | Must pass viability check | VIABLE or PARTIALLY_VIABLE | preflight.py |

**Eligibility Logic:**
```
pair_eligible = (
    correlation_confidence >= --min-confidence AND
    fib_effectiveness >= --fib-min-effectiveness AND
    preflight_verdict in [VIABLE, PARTIALLY_VIABLE_UP, PARTIALLY_VIABLE_DOWN]
)
```

**Suggested Defaults** (already implemented):
- `--min-confidence 0.6` - 60% confidence is reasonable starting point
- `--fib-min-effectiveness 60` - 60% bounce rate indicates level is respected
- Profitability viability is binary (costs vs expected returns) - no threshold needed

### Resolved by Design (Using Existing Code)

The following are **already solved** by reusing existing tools and parameters:

**Collection (correlation_tracker.py):**
- ~~Collection strategy~~ → Uses existing collector logic unchanged
- ~~Collection interval~~ → Uses existing `--interval` (default 30s)  
- ~~Rate limit handling~~ → Already implemented in collector
- ~~Error recovery~~ → Already implemented (retries, graceful degradation)
- ~~Coin symbol resolution~~ → Uses existing CoinGecko lookup with auto-search

**Analysis (correlation_tracker.py + preflight.py):**
- ~~Confidence thresholds~~ → Uses existing `--min-confidence` (default 0.6)
- ~~Sample requirements~~ → Uses existing `--min-samples` (default 500)
- ~~Profitability calculation~~ → Uses existing PreflightValidator

**Trading (leading_indicator_tester.py):**
- ~~Position sizing~~ → Uses existing `--position-size` (default 1000.0)
- ~~Trading mode~~ → Uses existing `--trading-mode` (paper/live)
- ~~Fib filtering~~ → Uses existing `--use-fib` and related parameters
- ~~Directional filtering~~ → Uses existing `--directional-filter`

---

## Implementation Plan

### MVP Tasks (COMPLETED)
1. [x] Create `fibonacci_analyzer.py` module
2. [x] Implement `FibonacciLevel` and `FibonacciReport` dataclasses
3. [x] Implement high/low detection (Option A: absolute)
4. [x] Implement level calculation
5. [x] Implement touch/bounce detection
6. [x] Create CLI for standalone usage
7. [x] Add `--fibonacci-analysis` flag to `leading_indicator_tester.py`
8. [x] Generate formatted report output
9. [x] Write unit tests
10. [x] Add CSV OHLCV input support
11. [x] Add multi-symbol analysis with summary table

### Phase 2 Tasks: Trading Integration (COMPLETED)
1. [x] Implement Fib Report Cache
   - [x] Add `save_report()` function
   - [x] Add `load_report()` function
   - [x] Create `./correlation_data/fib_reports/` directory structure
   - [x] Update `fibonacci_analyzer.py` CLI with --save-report and --list-cached
2. [x] Update `leading_indicator_tester.py --fibonacci-analysis` to save to cache
3. [x] Add `--use-fib` flag to `leading_indicator_tester.py`
4. [x] Add Fib-related CLI arguments (`--fib-min-effectiveness`, etc.)
5. [x] Load Fib report from cache on startup when `--use-fib` is specified
6. [x] Implement trend-direction filtering (Rule 1)
7. [x] Implement support/resistance level validation (Rules 2 & 3)
8. [x] Implement range invalidation check (Rule 4)
9. [x] Implement conflict detection with `--directional-filter`
10. [x] Write unit tests for FibTradeFilter class

### Phase 3 Tasks: Auto-Select Mode (MVP)
1. [ ] Add `--auto-select` and `--skip-collection` CLI arguments
2. [ ] Validate `--use-fib` is specified with `--auto-select`
3. [ ] Implement collection phase (subprocess call to correlation_tracker)
4. [ ] Implement correlation analysis phase (subprocess call to correlation_tracker --analyze)
5. [ ] Implement profitability analysis for candidates (call PreflightValidator)
6. [ ] Implement Fib analysis for candidates (call FibonacciAnalyzer + cache)
7. [ ] Implement eligibility filtering (min-confidence, fib-effectiveness, profitability)
8. [ ] Implement candidate display and user selection prompt
9. [ ] Auto-configure --directional-filter based on profitability
10. [ ] Add pair info to periodic status output
11. [ ] Write unit tests
12. [ ] Update operations manual

### Estimated Effort
- MVP (Fib Analyzer): 2-3 days ✓ COMPLETED
- Phase 2 (Trading Integration): 2-3 days ✓ COMPLETED
- Phase 3 (Auto-Select MVP): 2-3 days
- Future: Re-analysis, multi-pair, multi-timeframe

---

## CLI Reference

| Argument | Description | Default |
|----------|-------------|---------|
| `--symbol` | Symbol(s) to analyze (comma-separated). If omitted, analyzes all symbols in data directory. Required when using `--csv`. | None |
| `--window` | Analysis time window (e.g., 24h, 7d). Ignored when using `--csv`. | 7d |
| `--data-dir` | Directory containing price data | ./correlation_data |
| `--csv` | Load from CSV file (OHLCV format) instead of JSONL. File must be in `--data-dir`. | None |
| `--touch-tolerance` | Tolerance % for level touch detection | 0.5 |
| `--confirmation-periods` | Periods to confirm bounce vs breakthrough | 3 |
| `--min-touches` | Minimum touches to report level as significant | 2 |
| `--output-format` | Output format: `text` or `json` | text |
| `--output-file` | Write output to file instead of stdout | None |
| `--summary-only` | Only show summary table (multi-symbol mode) | false |
| `--list-symbols` | List available symbols in data directory | false |
| `--verbose` | Enable verbose logging | false |

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

### Multi-Symbol Summary Output

When analyzing multiple symbols (e.g., `--symbol SOL,BTC,ETH` or no `--symbol`), a summary table is displayed:

```
==========================================================================================
                         FIBONACCI ANALYSIS SUMMARY
==========================================================================================
Symbol    Trend   High        Low         Range%    Touches   Effect%   Best Level  
------------------------------------------------------------------------------------------
SOL       UP      $185.4200   $142.1800   30.4      14        71.4      38.2%       
BTC       UP      $68500.0000 $64200.0000 6.7       20        55.0      61.8%       
ETH       DOWN    $3850.0000  $3200.0000  20.3      18        62.5      50.0%       
------------------------------------------------------------------------------------------
Total symbols analyzed: 3

Top Fibonacci responders (>60% effectiveness, >5 touches):
  • SOL: 71.4% effectiveness at 38.2%
  • ETH: 62.5% effectiveness at 50.0%
==========================================================================================
```

Use `--summary-only` to show only the summary table without individual reports.

---

## References

- [Investopedia: Fibonacci Retracement](https://www.investopedia.com/terms/f/fibonacciretracement.asp)
- [TradingView: Fibonacci Retracement Tool](https://www.tradingview.com/support/solutions/43000502024-fibonacci-retracement/)
