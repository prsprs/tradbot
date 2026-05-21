# Leading Indicator Tester Operations Manual

This document describes the operation of the Leading Indicator Performance Tester (`leading_indicator_tester.py`), which validates discovered leading indicator pairs through paper trading simulations or live DEX trading.

> **Prerequisite:** This tool requires pair data from the Correlation History Tracker. See [CORRELATION_HISTORY_OPERATIONS_MANUAL.md](./CORRELATION_HISTORY_OPERATIONS_MANUAL.md) for data collection and analysis.

---

## Program Overview

### Leading Indicator Tester (`leading_indicator_tester.py`)

Monitors leader price movements and executes trades (paper or live) on the follower coin based on the correlation relationship discovered by the analyzer.

**Usage:**
```bash
python leading_indicator_tester.py --pair LEADER:FOLLOWER [OPTIONS]
```

---

## Workflow: From Discovery to Trading

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. COLLECT DATA (correlation_tracker.py)                               │
│     python correlation_tracker.py --coins BTC,ETH,SOL --interval 30     │
│                              ↓                                          │
│  2. ANALYZE CORRELATIONS (correlation_tracker.py)                       │
│     python correlation_tracker.py --analyze --profitability             │
│                              ↓                                          │
│     Creates: ./correlation_data/discovery_report.json                   │
│                              ↓                                          │
│  3. PAPER TRADE (leading_indicator_tester.py)                           │
│     python leading_indicator_tester.py --pair BTC:SOL                   │
│                              ↓                                          │
│  4. LIVE TRADE (leading_indicator_tester.py)                            │
│     python leading_indicator_tester.py --pair BTC:SOL --trading-mode live│
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Modes of Operation

### Paper Trading Mode (Default)

Simulates trades without real funds. Validates pair performance before risking capital.

```bash
python leading_indicator_tester.py --pair BTC:SOL
```

### Live Trading Mode

Executes real swaps on Solana via Jupiter aggregator.

```bash
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live
```

**Requirements for Live Mode:**
- Trust Wallet (or any Solana wallet) with 12-word recovery phrase
- SOL balance for transaction fees (minimum 0.005 SOL)
- USDC balance for buying (or token balance for selling)

**At Runtime:**
- You will be prompted to enter your 12-word mnemonic (input is hidden)
- Or set `SOLANA_PRIVATE_KEY` or `WALLET_MNEMONIC` environment variable
- Key is only held in memory during the session - nothing stored locally

**Supported Key Formats:**
- 12-word mnemonic (Trust Wallet, Phantom, etc.)
- Base58-encoded private key
- JSON array format

---

## Command-Line Options

### Required Arguments

| Option | Description |
|--------|-------------|
| `--pair LEADER:FOLLOWER` | Single pair to test (e.g., `BTC:SOL`) |
| `--pairs L1:F1,L2:F2` | Multiple pairs (paper mode only, requires `--sample-interval`) |

### Discovery Report

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--report` | path | `./correlation_data/discovery_report.json` | Path to discovery report JSON |
| `--max-data-age` | hours | `24` | Maximum age of report data before warning |

### Timing Parameters

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--lag` | seconds | *from report* | Lag time (overrides discovery report value) |
| `--sample-interval` | seconds | *same as lag* | Interval between leader price checks |
| `--execution-pct` | 50-95 | `80` | Execute trade at this % of lag time |
| `--trade-frequency` | seconds | *lag × 2* | Minimum seconds between trades |

### Trading Thresholds

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--min-move-pct` | float | `0.5` | Minimum % price change to trigger trade |
| `--position-size` | USD | `1000` | Position size for trades |
| `--max-trade-usd` | USD | `50` | Maximum trade size (live mode safety limit) |

### Exchange Selection

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--leader-exchange` | coingecko, jupiter, coinbase | `coingecko` | Exchange for leader price data |
| `--follower-exchange` | coingecko, jupiter, coinbase | `jupiter` | Exchange for follower price/trading |

### Live Trading Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--trading-mode` | paper, live | `paper` | Paper (simulated) or live (real swaps) |
| `--wallet-type` | trustwallet, local | `trustwallet` | Wallet backend (trustwallet recommended) |
| `--slippage-bps` | integer | `100` | Slippage tolerance (100 = 1%) |
| `--swap-mode` | flag | `false` | Swap directly between tokens vs USDC |
| `--directional-filter` | flag | `false` | Enable UP/DOWN directional filtering |
| `--preflight-recent` | duration | `48hr` | Data window for preflight analysis |

### Control Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--duration` | duration | *indefinite* | How long to run (e.g., `24h`, `7d`) |
| `--max-trades` | integer | *unlimited* | Stop after N trades |
| `--dry-run` | flag | `false` | Show config without executing |
| `--verbose` | flag | `false` | Detailed logging |

### Win Rate Management

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--min-win-rate` | 0.0-1.0 | *from report, or 0.5* | Minimum win rate before action |
| `--win-rate-window` | integer | `10` | Recent trades to evaluate |
| `--auto-refresh` | yes, no | `no` | Auto re-run analyzer on win rate drop |
| `--honor-directionality` | yes, no | `yes` | Only trade in stronger direction |

---

## Paper Trading

### Basic Paper Trade Test

```bash
# Use defaults from discovery report
python leading_indicator_tester.py --pair BTC:SOL

# Run for specific duration
python leading_indicator_tester.py --pair BTC:SOL --duration 24h

# Verbose output
python leading_indicator_tester.py --pair BTC:SOL --verbose
```

### Custom Parameters

```bash
# Custom timing
python leading_indicator_tester.py --pair BTC:SOL \
    --sample-interval 30 \
    --execution-pct 75 \
    --min-move-pct 0.3

# Custom position size
python leading_indicator_tester.py --pair BTC:SOL --position-size 500
```

### Testing Multiple Pairs

```bash
python leading_indicator_tester.py \
    --pairs BTC:SOL,ETH:BONK,SOL:WIF \
    --sample-interval 60
```

### Paper Trade Output

Trades are logged to `./paper_trades/{LEADER}_{FOLLOWER}_paper.json`:

```json
{
  "trades": [
    {
      "id": "pt_20260519_143022_001",
      "timestamp": "2026-05-19T14:30:22.123456+00:00",
      "type": "paper",
      "pair": "BTC:SOL",
      "action": "BUY",
      "follower": "SOL",
      "trigger": {
        "leader_move_pct": 0.65,
        "direction": "up"
      },
      "timing": {
        "signal_time": "2026-05-19T14:28:00.000000+00:00",
        "execution_delay_seconds": 142
      },
      "outcome": {
        "actual_move_pct": 0.48,
        "win": true,
        "evaluated_at": "2026-05-19T14:35:00.000000+00:00"
      }
    }
  ],
  "summary": {
    "total_trades": 1,
    "wins": 1,
    "losses": 0,
    "win_rate": 1.0
  }
}
```

---

## Live Trading

### Pre-Flight Check

Live mode automatically runs a preflight check before trading:

1. **Correlation Analysis** - Verifies pair relationship is still valid
2. **Volatility Analysis** - Confirms sufficient price movement for profitability
3. **Cost Analysis** - Calculates break-even and target moves
4. **Directional Viability** - Determines if UP/DOWN signals are profitable

```
======================================================================
                    LIVE MODE - PRE-FLIGHT CHECK
======================================================================
Pair: BTC → SOL
  ✓ Correlation: 0.72 (strong)
  ✓ Volatility: Sufficient at 15min+ intervals
  ✓ Break-even: 0.45% (achievable)
  ✓ UP signals: Viable
  ✓ DOWN signals: Viable
======================================================================
```

### Dry Run (Preview)

See what would happen without executing:

```bash
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live --dry-run
```

### Basic Live Trading

```bash
# Minimum command for live trading
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live
```

### Live Trading with Safety Limits

```bash
# Recommended for initial testing
python leading_indicator_tester.py --pair BTC:SOL \
    --trading-mode live \
    --position-size 25 \
    --max-trade-usd 50 \
    --max-trades 5
```

### Directional Filtering

Only trade in directions that passed profitability analysis:

```bash
python leading_indicator_tester.py --pair BTC:SOL \
    --trading-mode live \
    --directional-filter
```

Output:
```
Directional filtering ENABLED:
  UP signals: ✓ Allowed
  DOWN signals: ✗ Blocked
```

### Swap Mode vs USDC Mode

**USDC Mode (Default):**
- BUY signal: USDC → Follower token
- SELL signal: Follower token → USDC

```bash
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live
```

**Swap Mode:**
- BUY signal: Leader → Follower (expect follower to rise)
- SELL signal: Follower → Leader (expect follower to fall)

```bash
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live --swap-mode
```

### Live Trade Output

Trades are logged to `./live_trades/{LEADER}_{FOLLOWER}_live.json`:

```json
{
  "trades": [
    {
      "id": "lt_20260519_143022_001",
      "timestamp": "2026-05-19T14:30:22.123456+00:00",
      "type": "live",
      "pair": "BTC:SOL",
      "action": "BUY",
      "follower": "SOL",
      "input_token": "USDC",
      "output_token": "SOL",
      "input_amount": 50.0,
      "output_amount": 0.345678,
      "output_amount_actual": 0.344567,
      "price_usd": 144.72,
      "slippage_bps": 100,
      "slippage_actual_bps": 32,
      "transaction": {
        "signature": "5abc123...",
        "status": "confirmed",
        "price_impact_pct": 0.02
      }
    }
  ]
}
```

### Error Logging

Failed trades are logged to `./live_trades/trade_errors.json`:

```json
[
  {
    "timestamp": "2026-05-19T14:30:22.123456+00:00",
    "pair": "BTC:SOL",
    "action": "BUY",
    "reason": "Insufficient SOL for transaction fees",
    "details": {
      "sol_balance": 0.002,
      "min_required": 0.005
    }
  }
]
```

---

## Environment Variables

### Wallet Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `SOLANA_PRIVATE_KEY` | No | Private key (avoids interactive prompt) |
| `WALLET_MNEMONIC` | No | 12-word mnemonic (avoids interactive prompt) |
| `SOLANA_RPC_URL` | No | Custom RPC endpoint (default: mainnet-beta) |

### API Keys (Optional)

| Variable | Description |
|----------|-------------|
| `COINGECKO_API_KEY` | CoinGecko Pro API key |

---

## Trading Logic

### Signal Generation

1. **Sample leader price** at configured interval
2. **Compare to previous price** at lag interval ago
3. **If movement exceeds threshold** (default 0.5%), generate signal
4. **Wait execution time** (execution_pct × lag)
5. **Execute trade** on follower

### Execution Timing

```
Leader moves ────────► Signal generated ────────► Trade executed
    T=0                  T=0                      T=(lag × execution_pct)

Example with lag=120s, execution_pct=80%:
- Leader moves at T=0
- Signal generated immediately
- Trade executed at T=96s (120 × 0.80)
```

### Trade Cooldown

After a trade, wait `trade_frequency` seconds before another trade (default: lag × 2).

---

## Safety Features

### Gas Estimation

Before every trade, the system checks SOL balance:

```python
# Minimum 0.005 SOL required for transaction fees
has_sol, sol_balance = self._check_sol_balance(min_sol=0.005)
```

### Trade Size Limits

```bash
--max-trade-usd 50  # Default: $50 maximum per trade
```

### Error Alerting

All trade failures are:
1. Logged to console with `[LIVE] ❌ TRADE FAILED:` prefix
2. Persisted to `./live_trades/trade_errors.json`
3. Include timestamp, reason, and contextual details

### Win Rate Monitoring

```bash
--min-win-rate 0.5      # Stop if win rate drops below 50%
--win-rate-window 10    # Based on last 10 trades
--auto-refresh no       # Stop (vs. re-analyze) on win rate drop
```

---

## Directory Structure

```
tradingbot/
├── leading_indicator_tester.py     # Main entry point
├── preflight.py                    # Pre-flight validation logic
├── correlation_tracker.py          # Data collection & analysis
├── correlation_data/
│   ├── discovery_report.json       # Required: pair analysis results
│   └── 2026-05-19/
│       └── prices_*.jsonl          # Collected price data
├── paper_trades/                   # Paper trade output
│   └── BTC_SOL_paper.json
├── live_trades/                    # Live trade output
│   ├── BTC_SOL_live.json
│   └── trade_errors.json           # Failed trade log
└── dex/                            # DEX trading utilities
    ├── jupiterutil.py              # Jupiter API client
    ├── local_wallet.py             # Wallet management
    └── token_cache.py              # Token mint cache
```

---

## Quick Start Examples

### 1. First-Time Setup

```bash
# Step 1: Collect price data (run for several hours)
python correlation_tracker.py --coins BTC,ETH,SOL,BONK --interval 30 --duration 6hr

# Step 2: Analyze for leading pairs
python correlation_tracker.py --analyze --profitability

# Step 3: Paper trade a discovered pair
python leading_indicator_tester.py --pair BTC:SOL --duration 4h
```

### 2. Paper Trading Session

```bash
# Basic session
python leading_indicator_tester.py --pair BTC:SOL

# With custom parameters
python leading_indicator_tester.py --pair BTC:SOL \
    --sample-interval 60 \
    --min-move-pct 0.3 \
    --position-size 500 \
    --verbose
```

### 3. Live Trading Session

```bash
# Preview first (dry run)
python leading_indicator_tester.py --pair BTC:SOL --trading-mode live --dry-run

# Start with small amounts
python leading_indicator_tester.py --pair BTC:SOL \
    --trading-mode live \
    --position-size 25 \
    --max-trade-usd 50 \
    --directional-filter

# Production run
python leading_indicator_tester.py --pair BTC:SOL \
    --trading-mode live \
    --position-size 100 \
    --duration 24h
```

---

## Troubleshooting

### Pair Not Found in Discovery Report

```
Error: Pair BTC:XYZ not found in discovery report
```

**Solution:** Run analyzer first:
```bash
python correlation_tracker.py --analyze --data-dir ./correlation_data
```

### Pre-Flight Failed

```
✗ PRE-FLIGHT FAILED
Live trading BLOCKED. The pair did not pass viability checks.
```

**Solutions:**
1. Use `--trading-mode paper` to test without real funds
2. Try a different trading pair
3. Run profitability analysis: `python correlation_tracker.py --analyze --profitability`

### Insufficient SOL for Fees

```
[LIVE] ❌ TRADE FAILED: BUY
Reason: Insufficient SOL for transaction fees
  sol_balance: 0.002
  min_required: 0.005
```

**Solution:** Add SOL to your wallet (minimum 0.005 SOL).

### Wallet Not Initialized

```
[LIVE] Failed to initialize live trading
[LIVE] Check wallet and dependencies
```

**Solutions:**
1. Set `WALLET_MNEMONIC` environment variable
2. Ensure recovery phrase is valid (12 or 24 words)
3. Check that `solders` package is installed

### Discovery Report Too Old

```
[WARNING] Discovery report data is 36h old (max: 24h)
```

**Solution:** Re-run analysis with recent data:
```bash
python correlation_tracker.py --analyze --recent 24hr
```

---

## Important Warnings

⚠️ **Live trading uses real funds** - Start with small position sizes

⚠️ **Past performance does not guarantee future results** - Re-analyze regularly

⚠️ **Network fees are real** - Every trade costs SOL for gas

⚠️ **Slippage varies** - Actual output may differ from quoted amount

⚠️ **Market conditions change** - Monitor win rate and adjust

---

## Dependencies

Install required packages:
```bash
pip install -r requirements.txt
```

**Core dependencies:**
- `numpy>=1.21.0`
- `httpx>=0.23.0`
- `solders>=0.18.0` (for live trading)

---

## Related Documentation

- [CORRELATION_HISTORY_OPERATIONS_MANUAL.md](./CORRELATION_HISTORY_OPERATIONS_MANUAL.md) - Data collection and analysis
- [DEX_TRADING_FEATURE.md](./DEX_TRADING_FEATURE.md) - DEX trading architecture and implementation
