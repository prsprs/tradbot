# Live Mode Pre-Flight Validation - Implementation Plan

This document describes the phased implementation of the Live Mode Pre-Flight Validation feature for the Leading Indicator Performance Tester.

**Design Document**: `LEADING_INDICATOR_PERFORMANCE_TESTER.md` (sections: Pre-Flight Validation, Directional Filter)

---

## Overview

When `--trading-mode live` is specified, the system must:
1. Automatically run profitability analysis using `--recent 48hr`
2. Fail fast if pair is not VIABLE (or direction not viable when `--directional-filter=true`)
3. Auto-configure trading interval from profitability analysis
4. Filter signals at runtime based on directional viability (when enabled)

---

## Affected Code Paths

| Area | Files to Check/Modify |
|------|----------------------|
| Profitability analyzer | `correlation_tracker.py` (ProfitabilityAnalyzer class) |
| CLI arguments | `correlation_tracker.py` (parse_args), new file for live mode |
| Discovery report | `correlation_data/discovery_report.json` |
| Jupiter integration | `dex/jupiterutil.py` |
| Wallet management | `dex/local_wallet.py` |
| Design docs | `LEADING_INDICATOR_PERFORMANCE_TESTER.md` |

---

## Phase 1: Extend Profitability Analyzer for Directional Analysis

**Goal**: Add `--directional-filter` support to profitability analysis with two-pass UP/DOWN analysis.

### Tasks

- [ ] **1.1** Add `--directional-filter` CLI argument to `correlation_tracker.py`
  - Default: `false`
  - Type: `store_true`

- [ ] **1.2** Create `DirectionalProfitabilityResult` dataclass
  ```python
  @dataclass
  class DirectionalProfitabilityResult:
      up_viable: bool
      up_recommended_interval: Optional[str]
      up_break_even_pct: Optional[float]
      down_viable: bool
      down_recommended_interval: Optional[str]
      down_break_even_pct: Optional[float]
      combined_verdict: str  # FULLY_VIABLE, PARTIALLY_VIABLE_UP, PARTIALLY_VIABLE_DOWN, NOT_VIABLE
      recommended_interval: str  # Conservative choice
  ```

- [ ] **1.3** Implement `analyze_profitability_directional()` method in `ProfitabilityAnalyzer`
  - Filter price data by leader movement direction (UP vs DOWN)
  - Run existing profitability analysis on each subset
  - Return `DirectionalProfitabilityResult`

- [ ] **1.4** Update `analyze_profitability()` to call directional analysis when flag is set

- [ ] **1.5** Update output formatting for directional results
  - Show UP and DOWN sections separately
  - Show combined verdict

### Testing

```bash
# Test directional profitability analysis
python correlation_tracker.py --analyze --profitability --leader BTC --follower SOL --directional-filter --recent 48hr
```

### Acceptance Criteria

- [ ] `--directional-filter` produces two-pass analysis output
- [ ] Combined verdict correctly reflects UP/DOWN viability
- [ ] Interval selection uses conservative (longer) interval when both viable

---

## Phase 2: Create Pre-Flight Validation Module

**Goal**: Create reusable pre-flight validation that can be called from live trading mode.

### Tasks

- [ ] **2.1** Create `preflight.py` module with `PreflightValidator` class
  ```python
  class PreflightValidator:
      def __init__(self, leader: str, follower: str, 
                   directional_filter: bool = False,
                   recent: str = "48hr"):
          ...
      
      def validate(self) -> PreflightResult:
          """Run profitability analysis and return validation result."""
          ...
      
      def get_recommended_interval_seconds(self) -> int:
          """Convert recommended interval string to seconds."""
          ...
  ```

- [ ] **2.2** Create `PreflightResult` dataclass
  ```python
  @dataclass
  class PreflightResult:
      passed: bool
      verdict: str
      recommended_interval_seconds: int
      up_viable: bool
      down_viable: bool
      error_message: Optional[str]
      details: dict  # Full profitability analysis results
  ```

- [ ] **2.3** Implement interval string to seconds mapping
  ```python
  INTERVAL_MAP = {
      "1 min": 60,
      "5 min": 300,
      "15 min": 900,
      "1 hour": 3600,
      "4 hour": 14400
  }
  ```

- [ ] **2.4** Implement `sample_interval` derivation
  - Formula: `sample_interval = max(15, recommended_interval / 4)`

- [ ] **2.5** Implement fail-fast error message formatting
  - Clear explanation of why pair failed
  - Suggestions for user (paper trade, different pair, wait for volatility)

### Testing

```bash
# Unit test the preflight module
python -c "from preflight import PreflightValidator; v = PreflightValidator('BTC', 'SOL'); print(v.validate())"
```

### Acceptance Criteria

- [ ] `PreflightValidator` can be instantiated and called
- [ ] Returns correct `PreflightResult` with all fields populated
- [ ] Interval mapping is correct
- [ ] Error messages are clear and actionable

---

## Phase 3: Create Leading Indicator Tester Skeleton

**Goal**: Create the main `leading_indicator_tester.py` file with CLI and basic structure.

### Tasks

- [ ] **3.1** Create `leading_indicator_tester.py` with argparse CLI
  - `--pair LEADER:FOLLOWER` (required)
  - `--trading-mode` (choices: paper, live, default: paper)
  - `--position-size` (default: 1000 USD)
  - `--sample-interval` (optional, auto-derived in live mode)
  - `--trade-frequency` (optional, derived as 2x sample_interval)
  - `--min-move-pct` (default: 0.5)
  - `--directional-filter` (default: false)
  - `--dry-run` (for live mode preview)
  - `--duration` (e.g., "4h", "1d")

- [ ] **3.2** Implement pair parsing (split on `:`)

- [ ] **3.3** Implement live mode gate
  - If `--trading-mode live`:
    - Run preflight validation
    - Exit with error if not passed
    - Auto-set intervals from preflight result

- [ ] **3.4** Implement dry-run output for live mode
  - Show what would happen without executing
  - Display preflight results and derived parameters

### Testing

```bash
# Test CLI parsing
python leading_indicator_tester.py --pair BTC:SOL --trading-mode paper --duration 1h

# Test live mode preflight (should fail or pass based on data)
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live --dry-run
```

### Acceptance Criteria

- [ ] CLI parses all arguments correctly
- [ ] Live mode triggers preflight validation
- [ ] Dry-run shows preflight results without trading
- [ ] Intervals are auto-derived from preflight in live mode

---

## Phase 4: Implement Price Monitoring Loop

**Goal**: Implement the core price monitoring and signal detection loop.

### Tasks

- [ ] **4.1** Create `PriceMonitor` class
  - Fetch leader and follower prices at `sample_interval`
  - Calculate price changes between samples
  - Detect significant moves (> `min_move_pct`)

- [ ] **4.2** Implement signal generation
  - Leader UP + positive correlation → BUY signal
  - Leader DOWN + positive correlation → SELL signal
  - (Inverse for negative correlation)

- [ ] **4.3** Implement directional signal filtering
  - When `--directional-filter=true`:
    - Check `up_viable` before generating BUY signals
    - Check `down_viable` before generating SELL signals
    - Log skipped signals with reason

- [ ] **4.4** Implement cooldown/trade frequency logic
  - Track last trade time
  - Skip signals within cooldown window

- [ ] **4.5** Integrate with existing price fetching utilities
  - Use `coingeckoutil.py` for CoinGecko prices
  - Use `dex/jupiterutil.py` for Jupiter prices

### Testing

```bash
# Test price monitoring in paper mode
python leading_indicator_tester.py --pair BTC:SOL --trading-mode paper --duration 10m --sample-interval 30
```

### Acceptance Criteria

- [ ] Prices are fetched at correct intervals
- [ ] Signals are generated on significant moves
- [ ] Directional filtering skips non-viable direction signals
- [ ] Cooldown prevents over-trading

---

## Phase 5: Implement Paper Trading Mode

**Goal**: Complete paper trading with P&L tracking and session summary.

### Tasks

- [ ] **5.1** Create `PaperTrader` class
  - Track simulated positions
  - Calculate paper P&L
  - Record trade history

- [ ] **5.2** Implement trade recording
  - JSON format per design doc
  - Include all trigger and timing data

- [ ] **5.3** Implement session summary output
  - Total trades, wins, accuracy
  - Total paper P&L
  - Per-direction breakdown (if directional filter enabled)

- [ ] **5.4** Implement history file output
  - Save to `history/paper_trades.json`

### Testing

```bash
# Run paper trading session
python leading_indicator_tester.py --pair BTC:SOL --trading-mode paper --duration 1h
```

### Acceptance Criteria

- [ ] Paper trades are recorded correctly
- [ ] P&L calculations are accurate
- [ ] Session summary displays correctly
- [ ] History file is written

---

## Phase 6: Implement Live Trading Mode (USDC)

**Goal**: Implement live trading with Jupiter swaps in USDC mode.

### Tasks

- [ ] **6.1** Create `LiveTrader` class
  - Extends or wraps `PaperTrader` for shared logic
  - Integrates with Jupiter for real swaps

- [ ] **6.2** Implement wallet loading
  - Load from `dex/local_wallet.py`
  - Validate sufficient balance

- [ ] **6.3** Implement Jupiter swap execution
  - BUY: USDC → Follower token
  - SELL: Follower token → USDC
  - Use existing `jupiterutil.py` functions

- [ ] **6.4** Implement position tracking
  - Track actual wallet balances
  - Calculate real P&L

- [ ] **6.5** Implement safety limits
  - Maximum position size check
  - Daily loss limit (optional)

- [ ] **6.6** Implement transaction logging
  - Log all swap attempts and results
  - Record transaction signatures

### Testing

```bash
# Test with dry-run first
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live --dry-run

# Live trading (requires funded wallet)
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live --position-size 50
```

### Acceptance Criteria

- [ ] Preflight validation runs and gates live trading
- [ ] Jupiter swaps execute successfully
- [ ] Positions are tracked correctly
- [ ] Safety limits are enforced
- [ ] Transactions are logged

---

## Phase 7: Implement Swap Mode

**Goal**: Add swap mode as alternative to USDC mode for live trading.

### Tasks

- [ ] **7.1** Add `--swap-mode` CLI argument
  - When true, swap between leader and follower tokens directly
  - Mutually exclusive with USDC mode

- [ ] **7.2** Implement swap mode logic
  - BUY signal: Swap follower → leader (or vice versa based on pair)
  - SELL signal: Swap leader → follower

- [ ] **7.3** Implement USDC-equivalent P&L tracking
  - Calculate what position would be worth in USDC
  - Track over time for reporting

- [ ] **7.4** Ensure partial swap support
  - Use `--position-size-usd` equivalent
  - Don't swap entire holding

### Testing

```bash
# Test swap mode
python leading_indicator_tester.py --pair TAO:WTAO --trading-mode live --swap-mode --dry-run
```

### Acceptance Criteria

- [ ] Swap mode executes direct token swaps
- [ ] Partial swaps respect position size
- [ ] P&L is tracked in USDC equivalent

---

## Implementation Order & Dependencies

```
Phase 1 (Directional Profitability)
    ↓
Phase 2 (Preflight Module)
    ↓
Phase 3 (CLI Skeleton) ←── can start in parallel with Phase 2
    ↓
Phase 4 (Price Monitor)
    ↓
Phase 5 (Paper Trading)
    ↓
Phase 6 (Live USDC Mode)
    ↓
Phase 7 (Swap Mode)
```

---

## Checklist Before Marking Feature Complete

- [ ] All phases implemented
- [ ] Preflight validation gates live trading
- [ ] `--directional-filter` works for both profitability and runtime filtering
- [ ] Paper trading mode fully functional
- [ ] Live USDC mode functional (requires funded wallet to test)
- [ ] Swap mode functional
- [ ] All CLI parameters documented
- [ ] Error messages are clear and actionable
- [ ] Design doc updated with implementation status
- [ ] Manual testing completed

---

## Notes

- **Conservative MVP**: No override options for preflight - must be VIABLE
- **48hr window**: Fixed for MVP, `--preflight-recent` deferred
- **Single mode per session**: Either USDC or swap mode, not both
- **No runtime degradation check**: Deferred to post-MVP
