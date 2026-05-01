# Liquidity Pool Operations Manual

This document describes the programs, environment variables, APIs, and configuration for the LP Arbitrage System.

---

## Programs

### 1. LP Arbitrage Bot (`lp_arbitrage.py`)

The main arbitrage bot that monitors liquidity pool token premium/discount spreads and executes trades when spreads exceed thresholds.

**Usage:**
```bash
python lp_arbitrage.py [OPTIONS]
```

**Command-Line Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--once` | flag | `false` | Run once and exit (for cron jobs) |
| `--daemon` | flag | `false` | Run continuously with sleep interval |
| `--interval` | integer | `300` | Wake-up interval in seconds (daemon mode) |
| `--trading-mode` | `whatif`, `live` | `whatif` | Trading mode: `whatif` simulates, `live` executes |
| `--verbose` | flag | `false` | Log every wake-up snapshot (not just opportunities) |
| `--platform` | `jupiter`, `drift`, `hyperliquid` | `jupiter` | LP platform to use |
| `--buy-threshold` | float | `-0.02` | Buy when spread < threshold (e.g., -2% discount) |
| `--sell-threshold` | float | `0.03` | Sell when spread > threshold (e.g., +3% premium) |
| `--trade-amount` | float | `50` | Fixed trade amount in USD |
| `--max-position` | float | `500` | Maximum position size in USD |
| `--rpc-url` | string | `https://api.mainnet-beta.solana.com` | Solana RPC URL |
| `--history-dir` | path | `./history/lp/` | Directory for history files |
| `--compare-price-sources` | flag | `false` | Compare on-chain and DEX spread methods |
| `--auto-calculate-spread` | flag | `false` | Auto-calculate min viable spread and set thresholds |
| `--profit-margin` | float | `0.005` | Profit margin above min viable spread (0.5%) |

**Configuration Precedence:**
CLI arguments take precedence over environment variables. If neither is set, the default value is used.

**What it does:**
1. Fetches virtual price (NAV) from on-chain Pool account data
2. Fetches market price via Jupiter swap quote
3. Calculates spread: `(market_price - virtual_price) / virtual_price`
4. Determines action based on spread vs thresholds:
   - **DISCOUNT_ARB** when spread < buy_threshold: Buy at market → Redeem at NAV
   - **PREMIUM_ARB** when spread > sell_threshold: Mint at NAV → Sell at market
   - **HOLD** otherwise
5. Records snapshots to history (verbose mode or opportunities)
6. Executes TRUE ARBITRAGE (two-leg trades) or simulates them (whatif mode)

**True Arbitrage Strategy:**
- **PREMIUM_ARB**: Mint JLP at NAV (addLiquidity2) → Sell at market (Jupiter swap)
- **DISCOUNT_ARB**: Buy at market (Jupiter swap) → Redeem at NAV (removeLiquidity2)

This captures the spread IMMEDIATELY rather than betting on mean reversion.

**Output:**
- Console output with prices, spread, and action
- History records saved to `./history/lp/snapshots.json` and `./history/lp/trades.json`
- What-if summary showing simulated trades (whatif mode only)

**Example Output:**
```
[2026-04-30 07:02:47] Wake up #1
  Virtual price: $3.8211 (NAV from on-chain)
  Market price:  $3.8255 (DEX swap price)
  Spread: +0.11% (premium)
  Action: HOLD (spread within thresholds (-2.0% to 3.0%))

# When arbitrage opportunity detected:
[2026-04-30 08:15:22] Wake up #5
  Virtual price: $3.8211 (NAV from on-chain)
  Market price:  $3.9500 (DEX swap price)
  Spread: +3.37% (premium)
  Action: PREMIUM_ARB (spread 3.37% > threshold 3.00% → Mint NAV, Sell market)
  [WHAT-IF] PREMIUM ARBITRAGE:
    Step 1: Mint JLP at NAV ($3.8211)
    Step 2: Sell JLP at market ($3.9500)
    Gross profit: $1.69
    Est. costs: $0.11
    Net profit: $1.58 ✓
```

---

### 2. LP Analyzer (`lp_analyzer.py`)

Standalone program that analyzes historical LP arbitrage performance by examining past snapshots and trades.

**Usage:**
```bash
python lp_analyzer.py [OPTIONS]
```

**Command-Line Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--history-dir` | path | `./history/lp/` | Directory containing history files |
| `--days` | integer | `7` | Number of days to analyze |
| `--platform` | `jupiter`, `drift`, `hyperliquid`, `all` | `all` | Filter by platform |

**What it does:**
1. Loads snapshots and trades from history files
2. Calculates spread statistics (mean, min, max, std dev)
3. Analyzes trade performance and P&L
4. Generates summary report

**Output:**
- Console report with statistics
- Optional CSV export

---

### 3. JLP Virtual Price Lab (`lab/jlp_virtual_price_lab.py`)

Standalone lab program for testing and comparing different virtual price fetching methods.

**Usage:**
```bash
python lab/jlp_virtual_price_lab.py [OPTIONS]
```

**Command-Line Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--method` | `rpc`, `anchorpy`, `typescript`, `mvp`, `all` | `all` | Method(s) to test |
| `--rpc-url` | string | `https://api.mainnet-beta.solana.com` | Solana RPC URL |

**Methods:**
- `rpc`: On-chain Pool account parsing (primary method)
- `mvp`: DEX buy/sell spread method (fallback)
- `anchorpy`: AnchorPy library method (stub)
- `typescript`: TypeScript subprocess wrapper (scaffolding)
- `all`: Run and compare all methods

**Example Output:**
```
[METHOD 1: Solders + RPC Struct Parsing]
--------------------------------------------------
  JLP Supply: 236,642,512.87
  Pool account size: 2000 bytes
  AUM (USD): $904,012,367.72
  Virtual Price: $3.820160

============================================================
  RESULTS SUMMARY
============================================================

[Solders RPC] SUCCESS
  Virtual Price: $3.820160
  AUM (USD):     $904,012,367.72
  JLP Supply:    236,642,512.87
  Latency:       353ms
```

---

## Environment Variables

### Bot Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `whatif` | Trading mode: `whatif` simulates, `live` executes |
| `POLL_INTERVAL_SECONDS` | `300` | Wake-up interval in seconds |
| `BUY_THRESHOLD` | `-0.02` | Buy when spread < threshold |
| `SELL_THRESHOLD` | `0.03` | Sell when spread > threshold |
| `TRADE_AMOUNT_USD` | `50` | Fixed trade amount in USD |
| `MAX_POSITION_USD` | `500` | Maximum position size in USD |
| `LP_PLATFORM` | `jupiter` | LP platform: `jupiter`, `drift`, `hyperliquid` |
| `VERBOSE` | `false` | Log every wake-up snapshot |
| `COMPARE_PRICE_SOURCES` | `false` | Compare on-chain and DEX methods |
| `AUTO_CALCULATE_SPREAD` | `false` | Auto-calculate min viable spread |
| `PROFIT_MARGIN` | `0.005` | Profit margin above min viable spread |

### Solana Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` | Solana RPC endpoint |
| `SOLANA_PRIVATE_KEY` | *(empty)* | Base58-encoded private key (live mode) |

### API Keys

| Variable | Required For | Description |
|----------|--------------|-------------|
| `JUPITER_API_KEY` | Jupiter (optional) | API key for better rate limits |

### File Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `HISTORY_DIR` | `./history/lp/` | Directory for LP history files |

---

## APIs and Services

### 1. Solana RPC API

**Purpose:** Fetch on-chain account data for virtual price calculation

**Authentication:** None required for public RPC; dedicated providers may require API key

**Endpoints used:**
- `getAccountInfo`: Fetch Pool account data
- `getTokenSupply`: Fetch JLP token supply
- `getTokenAccountsByOwner`: Fetch wallet token balances
- `sendTransaction`: Submit signed transactions

**Rate Limits (public RPC):**
- ~100 requests per 10 seconds
- Consider dedicated RPC provider for production (Helius, QuickNode, etc.)

---

### 2. Jupiter Aggregator API

**Purpose:** Fetch swap quotes for market price and execute trades

**Base URL:** `https://api.jup.ag`

**Authentication:** Optional API key via `JUPITER_API_KEY` for better rate limits

**Endpoints used:**
- `GET /quote`: Get swap quote
- `POST /swap`: Get swap transaction

**Example Quote Request:**
```bash
curl "https://api.jup.ag/quote?inputMint=27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=50"
```

---

## Key Addresses

### Jupiter JLP

| Name | Address |
|------|---------|
| JLP Token Mint | `27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4` |
| JLP Pool Account | `5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq` |
| Perpetuals Program | `PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu` |
| USDC Mint | `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` |

---

## Directory Structure

```
tradingbot/
├── lp_arbitrage.py           # Main LP arbitrage bot (true arbitrage)
├── lp_history.py             # LP-specific history utilities
├── lp_analyzer.py            # Historical analysis tool
├── lab/
│   ├── jlp_virtual_price_lab.py  # Virtual price testing lab
│   └── jlp_mint_redeem_lab.py    # Mint/redeem instruction lab
├── dex/
│   ├── jupiterutil.py        # Jupiter API + JLP mint/redeem client
│   └── local_wallet.py       # Solana wallet management
├── history/
│   └── lp/
│       ├── snapshots.json    # Price snapshots (gitignored)
│       └── trades.json       # Trade records (gitignored)
├── LIQUIDITY_POOL_FEATURE.md           # Design document
└── LIQUIDITY_POOL_OPERATIONS_MANUAL.md # This file
```

---

## Quick Start Examples

### Run in What-If Mode (safe testing, no real trades)
```bash
python lp_arbitrage.py --once
```

### Run with verbose logging
```bash
python lp_arbitrage.py --once --verbose
```

### Compare price sources (on-chain vs DEX spread)
```bash
python lp_arbitrage.py --once --compare-price-sources
```

### Run as daemon with 5-minute interval
```bash
python lp_arbitrage.py --daemon --interval=300
```

### Custom thresholds (buy at -1% discount, sell at +2% premium)
```bash
python lp_arbitrage.py --once --buy-threshold=-0.01 --sell-threshold=0.02
```

### Auto-calculate optimal thresholds based on swap costs
```bash
python lp_arbitrage.py --once --auto-calculate-spread
```

### Auto-calculate with custom profit margin (1% above costs)
```bash
python lp_arbitrage.py --once --auto-calculate-spread --profit-margin=0.01
```

### Live trading mode (requires wallet)
```bash
export SOLANA_PRIVATE_KEY=your_base58_private_key
python lp_arbitrage.py --once --trading-mode=live
```

### Using environment variables
```bash
export TRADING_MODE=whatif
export POLL_INTERVAL_SECONDS=600
export BUY_THRESHOLD=-0.015
export SELL_THRESHOLD=0.025
python lp_arbitrage.py --daemon
```

### Test virtual price methods in lab
```bash
python lab/jlp_virtual_price_lab.py --method=all
```

### Analyze historical performance
```bash
python lp_analyzer.py --days=30
```

---

## Price Calculation Methods

### Primary: On-Chain (Default)

Calculates true NAV by parsing the Jupiter Perpetuals Pool account:

```
Virtual Price = Pool AUM (USD) / JLP Token Supply
```

**Pool Account Parsing:**
```python
# Pool struct layout
# Offset 0:   8 bytes  - Anchor discriminator
# Offset 8:   4 bytes  - name string length
# Offset 12:  N bytes  - name string ("Pool")
# Offset 12+N: 4 bytes - custodies vec length
# Offset 16+N: M*32    - custody pubkeys
# Offset 16+N+M*32: 16 bytes - aumUsd (u128)
```

### Fallback: DEX Spread

Uses Jupiter swap quotes when on-chain method fails:

```
Virtual Price ≈ Buy Price (USDC → JLP quote)
Market Price = Sell Price (JLP → USDC quote)
```

### Comparison Mode

Use `--compare-price-sources` to see both methods:

```
  ┌─────────────────────────────────────────────────────┐
  │           PRICE SOURCE COMPARISON                   │
  ├─────────────────────────────────────────────────────┤
  │ ON-CHAIN (Pool AUM / Supply):                       │
  │   AUM:           $904,230,772.39                    │
  │   JLP Supply:    236,642,512.86                     │
  │   Virtual Price: $      3.821083                    │
  ├─────────────────────────────────────────────────────┤
  │ DEX SPREAD (Buy/Sell quotes):                       │
  │   Buy Price:     $      3.825747                    │
  │   Sell Price:    $      3.825469                    │
  │   DEX Spread:           -0.0073%                    │
  ├─────────────────────────────────────────────────────┤
  │ TRUE SPREAD (Market vs NAV):                        │
  │   Market - NAV:         +0.1148%                    │
  └─────────────────────────────────────────────────────┘
```

### Auto-Calculate Spread Mode

Use `--auto-calculate-spread` to dynamically calculate the minimum viable spread based on actual swap costs:

```bash
python lp_arbitrage.py --once --auto-calculate-spread
```

**How it works:**
1. Fetches Jupiter quotes for both directions (buy and sell)
2. Extracts swap fees from `routePlan[].swapInfo.feeAmount`
3. Extracts price impact from `priceImpactPct`
4. Estimates gas costs (~$0.0015 for 2 transactions)
5. Calculates: `min_viable_spread = fees + impact + gas`
6. Sets thresholds: `±(min_viable_spread + profit_margin)`

**Example Output:**
```
  ┌─────────────────────────────────────────────────────┐
  │        MIN VIABLE SPREAD CALCULATION                │
  ├─────────────────────────────────────────────────────┤
  │ Trade amount:        $     50.00                    │
  ├─────────────────────────────────────────────────────┤
  │ Buy fees:                0.1500%                    │
  │ Sell fees:               0.1500%                    │
  │ Buy price impact:        0.0100%                    │
  │ Sell price impact:       0.0100%                    │
  │ Gas (estimated):         0.0030%                    │
  ├─────────────────────────────────────────────────────┤
  │ Total fees:              0.3000%                    │
  │ Total impact:            0.0200%                    │
  │ MIN VIABLE SPREAD:       0.3230%                    │
  ├─────────────────────────────────────────────────────┤
  │ Profit margin:           0.5000%                    │
  │ BUY threshold:          -0.8230%                    │
  │ SELL threshold:         +0.8230%                    │
  └─────────────────────────────────────────────────────┘
```

**Parameters:**
- `--profit-margin`: Additional margin above min viable spread (default: 0.005 = 0.5%)

**Note:** JLP mint/redeem may show low fees because costs are built into the price spread rather than explicit AMM fees.

---

## Troubleshooting

### RPC Rate Limits
```
Error fetching Pool account data
```
**Solution:** Use a dedicated RPC provider (Helius, QuickNode) or reduce polling frequency.

### Jupiter API Rate Limits
```
[JUPITER] No API key (set JUPITER_API_KEY env var for better rate limits)
```
**Solution:** Set `JUPITER_API_KEY` environment variable for higher rate limits.

### On-Chain Parse Failure
```
[WARN] On-chain virtual price failed, using DEX spread fallback
```
**Cause:** Pool account structure may have changed, or RPC returned invalid data.
**Solution:** Check if Jupiter has updated their Pool account layout.

### Wallet Not Loaded (Live Mode)
```
[LIVE] Error: Wallet not loaded
```
**Solution:** Set `SOLANA_PRIVATE_KEY` environment variable with base58-encoded key.

### Insufficient Balance
```
[LIVE] Insufficient USDC: $10.00 < $50.00
```
**Solution:** Reduce `--trade-amount` or fund wallet with more USDC.

### Position Limit Exceeded
```
[LIVE] Would exceed max position: $400.00 + $50.00 > $500.00
```
**Solution:** Increase `--max-position` or wait to sell existing position.

---

## History Recording

### Snapshot Format
```json
{
  "timestamp": "2026-04-30T07:02:47.123456Z",
  "platform": "jupiter",
  "lp_token": "JLP",
  "virtual_price": 3.8211,
  "market_price": 3.8255,
  "spread_pct": 0.1148,
  "spread_direction": "premium",
  "recommendation": "HOLD",
  "trading_mode": "whatif",
  "wake_up_number": 1
}
```

### Trade Format
```json
{
  "timestamp": "2026-04-30T07:02:47.123456Z",
  "platform": "jupiter",
  "lp_token": "JLP",
  "action": "BUY",
  "amount_usd": 50.0,
  "price": 3.8211,
  "spread_pct": -2.15,
  "executed": false,
  "trading_mode": "whatif",
  "tx_signature": null
}
```

---

## Dependencies

Install required packages:
```bash
pip install -r requirements_dex.txt
```

**Required:**
- `httpx>=0.24.0` - HTTP client for RPC and API calls
- `solders>=0.18.0` - Solana primitives

**Optional:**
- `anchorpy>=0.18.0` - Anchor IDL parsing (not currently used)

---

## Risk Disclaimer

**This is experimental software for educational purposes.**

- **Unhedged exposure**: JLP holds BTC, ETH, SOL - price movements affect value
- **Smart contract risk**: Jupiter Perpetuals contracts could have bugs
- **Execution risk**: Slippage and failed transactions can occur
- **No guarantees**: Past spreads do not predict future opportunities

**Always start with `--trading-mode=whatif` and small amounts.**
