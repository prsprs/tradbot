# Leading Indicator Test Guide

This document describes the test suite for the Leading Indicator Performance Tester. Run these tests after making changes to ensure regression safety.

---

## Quick Reference

| Test | Purpose | Requires Wallet | Duration |
|------|---------|-----------------|----------|
| `test_jupiter_swap.py` | Verify Jupiter swap integration | Yes | ~30 sec |
| Dry-run mode | Validate config without trading | No | Instant |
| Paper mode (short) | Test signal detection & paper trades | No | 5-10 min |
| Live mode (test) | Verify live swap execution | Yes | Hours |

---

## Test 1: Jupiter Swap Integration

**Purpose:** Verify wallet loading, balance checks, and Jupiter swap execution work correctly.

**When to run:** After changes to:
- `dex/local_wallet.py`
- `dex/jupiterutil.py`
- Any transaction signing or sending code

**Command:**
```bash
python test_jupiter_swap.py
```

**What it tests:**
1. Wallet key loading (multiple formats)
2. SOL and USDC balance fetching via RPC
3. Jupiter quote API
4. Jupiter swap transaction building
5. Transaction signing with solders
6. Transaction submission to Solana
7. Transaction confirmation

**Expected output:**
```
✓ TEST PASSED - Jupiter swap executed successfully!
```

**Cost:** $1 USDC (swapped to SOL, can be swapped back)

---

## Test 2: Dry-Run Mode

**Purpose:** Validate configuration, preflight checks, and interval calculations without any trading.

**When to run:** After changes to:
- `leading_indicator_tester.py` (argument parsing, config)
- `preflight.py`
- Interval/timing calculations

**Command:**
```bash
python leading_indicator_tester.py \
  --pair BTC:NVDAX \
  --position-size 25 \
  --trading-mode live \
  --dry-run \
  --preflight-recent 24hr
```

**What it tests:**
1. Discovery report loading
2. Preflight validation (volatility analysis)
3. Interval calculations (lag, sample, cooldown)
4. Directional viability checks
5. Configuration summary output

**Expected output:**
- Preflight result (VIABLE / POSSIBLY VIABLE / NOT VIABLE)
- Calculated intervals
- No actual price fetching or trading

**Cost:** None (no API calls to exchanges)

---

## Test 3: Paper Trading (Short Duration)

**Purpose:** Test signal detection, price fetching, and paper trade execution.

**When to run:** After changes to:
- Price monitoring loop
- Signal detection logic
- Trade execution (paper mode)
- Win rate tracking

**Command:**
```bash
python leading_indicator_tester.py \
  --pair BTC:ETH \
  --position-size 100 \
  --trading-mode paper \
  --sample-interval 30 \
  --min-move-pct 0.05 \
  --duration 10m \
  --max-trades 3
```

**What it tests:**
1. Price fetching (CoinGecko/Jupiter)
2. Price change detection
3. Signal generation
4. Paper trade execution
5. Trade logging to JSON
6. Max trades limit
7. Duration limit

**Expected output:**
- Price samples logged
- Paper trades executed (if moves detected)
- Trade log written to `./paper_trades/`

**Cost:** None (paper trades only)

**Note:** Use `--min-move-pct 0.05` to increase chance of triggering trades during short test.

---

## Test 4: Live Trading (Small Position)

**Purpose:** Full end-to-end test of live Jupiter swaps triggered by price signals.

**When to run:** After:
- All other tests pass
- Before deploying significant changes to live trading

**Command:**
```bash
python leading_indicator_tester.py \
  --pair BTC:NVDAX \
  --position-size 25 \
  --max-trades 1 \
  --trading-mode live \
  --preflight-recent 24hr \
  --min-move-pct 0.30
```

**What it tests:**
1. Full preflight validation
2. Wallet initialization
3. Price monitoring loop
4. Live swap execution via Jupiter
5. Transaction confirmation
6. Trade logging

**Expected output:**
```
LIVE TRADE EXECUTED
Action: BUY NVDAX
Price: $X.XX
Tx: ABC123...
```

**Cost:** $25 per trade (configurable via `--position-size`)

**Duration:** Depends on market volatility. Could be hours.

---

## Test 5: Synthetic Data (Offline)

**Purpose:** Test correlation analysis with controlled data (no API calls).

**When to run:** After changes to:
- `correlation_tracker.py`
- Correlation/lag algorithms

**Command:**
```bash
# Generate synthetic test data
python -c "
from correlation_tracker import generate_test_data
generate_test_data('./test_correlation_data/', hours=48)
"

# Run analysis on test data
python correlation_tracker.py \
  --analyze \
  --data-dir ./test_correlation_data/ \
  --output-report ./test_correlation_data/discovery_report.json
```

**What it tests:**
1. Data loading
2. Correlation calculation
3. Lag detection
4. Report generation

**Cost:** None (offline analysis)

---

## Regression Test Sequence

Run these in order after significant changes:

### Quick Smoke Test (2 min)
```bash
# 1. Syntax check
python -c "import leading_indicator_tester; import preflight; print('OK')"

# 2. Dry-run validation
python leading_indicator_tester.py --pair BTC:ETH --dry-run --trading-mode paper

# 3. Jupiter quote (no swap)
python -c "
from dex.jupiterutil import JupiterClient, USDC_MINT, SOL_MINT
j = JupiterClient()
q = j.get_quote(USDC_MINT, SOL_MINT, 1000000)
print(f'Quote OK: {int(q[\"outAmount\"])/1e9:.6f} SOL')
"
```

### Full Integration Test (requires wallet)
```bash
# 1. Jupiter swap test
python test_jupiter_swap.py

# 2. Live mode dry-run
python leading_indicator_tester.py \
  --pair BTC:NVDAX \
  --position-size 25 \
  --trading-mode live \
  --dry-run \
  --preflight-recent 24hr
```

---

## Test Data Locations

| Path | Purpose |
|------|---------|
| `./paper_trades/` | Paper trade logs |
| `./live_trades/` | Live trade logs |
| `./correlation_data/` | Production correlation data |
| `./test_correlation_data/` | Test correlation data (isolated) |

---

## Common Issues

### "No module named 'solders'"
```bash
pip install solders
```

### "No module named 'base58'"
```bash
pip install base58
```

### Wallet key decoding errors
- Ensure you're copying the **private key**, not the public address
- Jupiter wallet: Settings → Security → Show Secret Key
- Phantom: Settings → Security & Privacy → Export Private Key

### "Pair not found in discovery report"
```bash
# Re-run correlation analysis
python correlation_tracker.py --analyze
```

### Rate limiting
- Set `JUPITER_API_KEY` environment variable for better rate limits
- Increase `--sample-interval` to reduce API calls

---

## Adding New Tests

When adding a new test script:

1. Create `test_<feature>.py` in the project root
2. Add a section to this guide describing:
   - Purpose
   - When to run
   - Command
   - Expected output
   - Cost (if any)
3. Update the Quick Reference table

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `JUPITER_API_KEY` | Jupiter API key for better rate limits |
| `COINGECKO_API_KEY` | CoinGecko Pro API key (optional) |
