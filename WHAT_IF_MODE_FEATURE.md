# What-If Mode Feature

## Overview

A "what-if" or "paper trading" mode that allows the trading bot to run its full analysis and recommendation pipeline, record all recommendations to history, but **skip actual trade execution**. This enables:

- Testing LLM recommendation quality without financial risk
- Building recommendation history for analysis before going live
- Debugging and development without affecting real balances
- Comparing different LLM configurations safely

## Goals

1. **Full pipeline execution** - Run all LLM queries, comparisons, and consensus logic
2. **Record all recommendations** - Write to `recommendations.json` as normal
3. **Skip trade execution** - Do not call `buy_something()` or any Coinbase trade APIs
4. **Clear indication** - Log output clearly shows what-if mode is active and its source
5. **Easy toggle** - Command-line argument or environment variable to switch modes

## Current State

The codebase has a hardcoded `doPython=True` variable that controls trade execution, but:
- It's not exposed as a configurable option
- The variable name is confusing (comment says "should be renamed")
- No logging indicates whether trades are real or simulated

## Design

Per the recommendations in `METHODS_OF_SPECIFYING_RUNTIME_OPTIONS.md`, trading mode is an **operational setting** and should support both CLI arguments and environment variables, with CLI taking precedence.

### Configuration Methods

**Command-line argument (preferred for explicitness):**
```bash
python crypto_trading_bot.py --trading-mode=whatif
python crypto_trading_bot.py --trading-mode=live
```

**Environment variable (fallback):**
```bash
export TRADING_MODE=whatif
python crypto_trading_bot.py
```

**Precedence:** CLI argument > Environment variable > Default (`live`)

### Behavior by Mode

| Action | `live` | `whatif` |
|--------|--------|----------|
| LLM queries | ✓ | ✓ |
| Price fetching | ✓ | ✓ |
| Comparison/integration | ✓ | ✓ |
| Record to recommendations.json | ✓ | ✓ |
| Call `buy_something()` | ✓ | ✗ |
| Log "would have bought" | ✗ | ✓ |

### Console Output

When `TRADING_MODE=whatif`:

```
=== TRADING BOT ===
MODE: WHAT-IF (no real trades will be executed)
...

[WHAT-IF] Would execute BUY for PEPE at $0.00000351
[WHAT-IF] Would execute BUY for BONK at $0.00000575
...

=== WHAT-IF SUMMARY ===
Recommendations recorded: 5
Simulated BUY orders: 2
Simulated SELL orders: 0
No actual trades were executed.
```

### Implementation Changes

#### 1. Add Argument Parsing (crypto_trading_bot.py)

```python
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description='Trading Bot')
    parser.add_argument(
        '--trading-mode',
        choices=['live', 'whatif'],
        default=os.environ.get('TRADING_MODE', 'live').lower(),
        help='Trading mode: live executes trades, whatif simulates (default: live, or TRADING_MODE env var)'
    )
    return parser.parse_args()

args = parse_args()
TRADING_MODE = args.trading_mode
WHATIF_MODE = TRADING_MODE == 'whatif'
```

#### 2. Replace `doPython` Variable

Replace the hardcoded `doPython=True` with logic based on `TRADING_MODE`:

```python
# Execute trades only in live mode
execute_trades = TRADING_MODE == 'live'
```

#### 3. Update Trade Execution Points

At each `buy_something()` call site:

```python
if execute_trades:
    if coin_symbol not in coinsToExclude:
        if final_action and 'BUY' in final_action:
            buy_something(coin_symbol)
else:
    if final_action and 'BUY' in final_action:
        print(f"[WHAT-IF] Would execute BUY for {coin_symbol} at ${price}")
```

#### 4. Startup Banner with Source

Show where the configuration came from:

```python
print("=== TRADING BOT ===")
if WHATIF_MODE:
    source = "--trading-mode" if '--trading-mode' in sys.argv else "TRADING_MODE env var" if os.environ.get('TRADING_MODE') else "default"
    print(f"Trading Mode: WHAT-IF (no real trades) [{source}]")
else:
    source = "--trading-mode" if '--trading-mode' in sys.argv else "TRADING_MODE env var" if os.environ.get('TRADING_MODE') else "default"
    print(f"Trading Mode: LIVE (trades will execute) [{source}]")
```

#### 5. Summary at End

Track and report what-if statistics:

```python
if WHATIF_MODE:
    print("\n=== WHAT-IF SUMMARY ===")
    print(f"Recommendations recorded: {len(recommendations_made)}")
    print(f"Simulated BUY orders: {simulated_buys}")
    print(f"Simulated SELL orders: {simulated_sells}")
    print("No actual trades were executed.")
```

### Recommendation Record Enhancement

Optionally record the trading mode in recommendations.json:

```json
{
  "id": "rec_20260413_192754_PEPE",
  "timestamp": "2026-04-13T19:27:54.096701Z",
  "coin_symbol": "PEPE",
  "recommendation": "BUY",
  "price_at_recommendation": 3.57e-06,
  "trading_mode": "whatif",
  ...
}
```

This allows the analyzer to filter or flag what-if recommendations separately.

## Configuration Summary

| Method | Option | Values | Default |
|--------|--------|--------|--------|
| CLI | `--trading-mode` | `live`, `whatif` | `live` |
| Env var | `TRADING_MODE` | `live`, `whatif` | `live` |

**Precedence:** `--trading-mode` > `TRADING_MODE` > `live`

## Validation

### What-If Mode Checklist

- [ ] LLM queries execute normally
- [ ] Prices are fetched correctly
- [ ] Recommendations written to `recommendations.json`
- [ ] `buy_something()` is NOT called
- [ ] Console clearly shows what-if mode
- [ ] Summary shows simulated trade counts

### Live Mode Checklist

- [ ] All existing functionality unchanged
- [ ] Trades execute as before
- [ ] No "what-if" messages in output

## Future Enhancements

1. **Simulated portfolio tracking** - Track a virtual balance and holdings
2. **What-if analysis report** - Show P&L if trades had been executed
3. **Mode in analyzer** - Filter analysis by trading_mode
4. **Alerts** - Notify when what-if recommendations would have been profitable

## Files to Modify

1. `crypto_trading_bot.py` - Add TRADING_MODE logic, update trade execution
2. `historyutil.py` - Optionally add trading_mode to recommendation records
3. `OPERATIONS_MANUAL.md` - Document new environment variable
4. `README.md` - Add what-if mode to quick start

## Implementation Sketch

```python
import argparse
import sys

# Argument parsing with env var fallback
def parse_args():
    parser = argparse.ArgumentParser(description='Trading Bot')
    parser.add_argument(
        '--trading-mode',
        choices=['live', 'whatif'],
        default=os.environ.get('TRADING_MODE', 'live').lower(),
        help='Trading mode (default: live, or TRADING_MODE env var)'
    )
    # Add other operational args here with same pattern
    return parser.parse_args()

args = parse_args()
TRADING_MODE = args.trading_mode
WHATIF_MODE = TRADING_MODE == 'whatif'

# Track what-if statistics
whatif_buys = 0
whatif_sells = 0

# In startup output - show source of config
def get_config_source(arg_name, env_name):
    if any(arg_name in arg for arg in sys.argv):
        return f"{arg_name}"
    elif os.environ.get(env_name):
        return f"{env_name} env var"
    return "default"

print("=== TRADING BOT ===")
mode_source = get_config_source('--trading-mode', 'TRADING_MODE')
if WHATIF_MODE:
    print(f"Trading Mode: WHAT-IF (no real trades) [{mode_source}]")
else:
    print(f"Trading Mode: LIVE (trades will execute) [{mode_source}]")

# At each trade execution point, replace:
#   if doPython:
#       if coin_symbol not in coinsToExclude:
#           if final_action and 'BUY' in final_action:
#               buy_something(coin_symbol)
# With:
if final_action and 'BUY' in final_action:
    if not WHATIF_MODE:
        if coin_symbol not in coinsToExclude:
            buy_something(coin_symbol)
    else:
        whatif_buys += 1
        print(f"[WHAT-IF] Would execute BUY for {coin_symbol}")

# At end of script
if WHATIF_MODE:
    print(f"\n=== WHAT-IF SUMMARY ===")
    print(f"Simulated BUY orders: {whatif_buys}")
    print("No actual trades were executed.")
```
