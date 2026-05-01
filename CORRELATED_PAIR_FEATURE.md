# Correlated Pair Trading Feature

## Overview

This document explores a trading strategy where **one coin acts as a leading indicator** for another, allowing a bot to predict price movements and trade ahead of them. This is distinct from arbitrage (same asset, different venues) and instead exploits **temporal price correlation** between related assets.

**Primary Use Cases:**
1. **Wrapped/Native pairs** (e.g., TAO/wTAO, ETH/WETH, BTC/WBTC)
2. **Ecosystem tokens** (e.g., SOL leading RAY, ORCA)
3. **Correlated assets** (e.g., BTC leading altcoins)

---

## Strategy Types

### Type 1: Wrapped Token Spread Arbitrage (TAO/wTAO Example)

When a native token (TAO on Bittensor) has a wrapped version on another chain (wTAO on Ethereum/Solana), price discrepancies arise due to:

- **Bridge delays**: Wrapping/unwrapping takes time
- **Liquidity fragmentation**: Different liquidity on each chain
- **Market inefficiency**: Not all traders monitor both versions

```
Example:
- TAO (native): $450.00
- wTAO (wrapped): $445.00
- Spread: 1.1%

Strategy: Buy wTAO at $445, knowing it should converge to $450
```

**Key Insight:** The native token price typically **leads** the wrapped token price because:
1. Primary trading happens on native chain
2. Wrapped version arbitrages toward native price
3. Bridge mechanics create lag

### Type 2: Leading Indicator Prediction

One asset's price movement **predicts** another's movement with a time delay.

```
Example:
- BTC rises 2% in 5 minutes
- Historical data shows: when BTC rises >1.5%, SOL follows with 0.8x magnitude
- Prediction: SOL will rise ~1.6% in next 10-30 minutes

Action: Buy SOL immediately after detecting BTC movement
```

### Type 3: Correlation Breakdown Reversion

When historically correlated assets **temporarily diverge**, bet on reversion.

```
Example:
- SOL and ETH historically move with 0.85 correlation
- Today: ETH +5%, SOL -2%
- Divergence: 7% (unusual)

Action: Long SOL, expecting mean reversion
```

---

## Daemon Mode Architecture

### Core Concept

Run the bot as a **background daemon** that continuously monitors price pairs and executes trades when:

1. **Movement threshold exceeded** - Leading coin moves >X%
2. **Spread threshold exceeded** - Price gap between pair >Y%
3. **Both conditions** - Movement + spread for higher confidence

### Configuration

```python
@dataclass
class CorrelatedPairConfig:
    # Token pair
    leading_token: str      # e.g., "TAO" (native)
    lagging_token: str      # e.g., "wTAO" (wrapped)
    
    # Thresholds
    movement_threshold_pct: float = 2.0    # Leading token must move >2%
    spread_threshold_pct: float = 1.0      # Spread must exceed 1%
    
    # Timing
    lookback_window_sec: int = 300         # 5 min window for movement calc
    check_interval_sec: int = 10           # Check every 10 seconds
    
    # Trade parameters
    trade_amount_usd: float = 100.0
    max_slippage_pct: float = 0.5
    
    # Mode
    require_both_conditions: bool = False  # AND vs OR for thresholds
    what_if_mode: bool = True              # Paper trading
```

### Daemon Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    DAEMON MAIN LOOP                         │
├─────────────────────────────────────────────────────────────┤
│  1. Fetch leading token price                               │
│  2. Fetch lagging token price                               │
│  3. Calculate:                                              │
│     - Movement % (leading token vs lookback)                │
│     - Spread % (leading vs lagging)                         │
│  4. Check thresholds:                                       │
│     - movement_pct > movement_threshold?                    │
│     - spread_pct > spread_threshold?                        │
│  5. If conditions met:                                      │
│     - Determine direction (BUY/SELL lagging token)          │
│     - Execute trade (or log in what-if mode)                │
│  6. Sleep for check_interval                                │
│  7. Repeat                                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Trade Logic

### Direction Determination

| Leading Token Movement | Spread Direction | Action on Lagging Token |
|------------------------|------------------|-------------------------|
| +2% (up) | Lagging < Leading | **BUY** lagging (expect catch-up) |
| -2% (down) | Lagging > Leading | **SELL** lagging (expect drop) |
| Flat | Lagging < Leading | **BUY** lagging (spread arb) |
| Flat | Lagging > Leading | **SELL** lagging (spread arb) |

### For Wrapped Token Pairs (TAO/wTAO)

The logic is simpler because **they should be the same price**:

```python
def get_trade_signal(tao_price: float, wtao_price: float, 
                     spread_threshold: float) -> Optional[Signal]:
    spread_pct = (tao_price - wtao_price) / tao_price * 100
    
    if spread_pct > spread_threshold:
        # wTAO is cheaper than TAO - BUY wTAO
        return Signal(
            action="BUY",
            token="wTAO",
            reason=f"wTAO trading at {spread_pct:.2f}% discount to TAO",
            expected_profit_pct=spread_pct
        )
    elif spread_pct < -spread_threshold:
        # wTAO is more expensive than TAO - SELL wTAO
        return Signal(
            action="SELL",
            token="wTAO",
            reason=f"wTAO trading at {-spread_pct:.2f}% premium to TAO",
            expected_profit_pct=-spread_pct
        )
    
    return None  # No opportunity
```

### For Leading Indicator Pairs (BTC → SOL)

More complex - need historical correlation data:

```python
def get_prediction_signal(
    leading_movement_pct: float,
    correlation_factor: float,  # e.g., 0.8 means lagging moves 80% of leading
    movement_threshold: float
) -> Optional[Signal]:
    
    if abs(leading_movement_pct) < movement_threshold:
        return None
    
    predicted_lagging_movement = leading_movement_pct * correlation_factor
    
    if leading_movement_pct > 0:
        return Signal(
            action="BUY",
            reason=f"Leading token +{leading_movement_pct:.2f}%, "
                   f"expecting lagging +{predicted_lagging_movement:.2f}%",
            confidence=calculate_confidence(leading_movement_pct)
        )
    else:
        return Signal(
            action="SELL",
            reason=f"Leading token {leading_movement_pct:.2f}%, "
                   f"expecting lagging {predicted_lagging_movement:.2f}%",
            confidence=calculate_confidence(leading_movement_pct)
        )
```

---

## Implementation: TAO/wTAO Spread Bot

### Price Sources

| Token | Chain | Price Source |
|-------|-------|--------------|
| TAO | Bittensor | Finney DEX, CoinGecko API |
| wTAO (ERC-20) | Ethereum | Uniswap, 1inch |
| wTAO (SPL) | Solana | Jupiter, Raydium |

### Example Implementation

```python
#!/usr/bin/env python3
"""
correlated_pair_bot.py - Daemon for correlated pair trading
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional
import aiohttp

@dataclass
class PairSnapshot:
    timestamp: float
    leading_price: float
    lagging_price: float
    spread_pct: float
    leading_movement_pct: float

class CorrelatedPairBot:
    def __init__(self, config: CorrelatedPairConfig):
        self.config = config
        self.price_history = []
        self.last_trade_time = 0
        self.cooldown_sec = 60  # Min time between trades
        
    async def fetch_tao_price(self) -> float:
        """Fetch native TAO price from CoinGecko."""
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": "bittensor", "vs_currencies": "usd"}
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data["bittensor"]["usd"]
    
    async def fetch_wtao_price(self) -> float:
        """Fetch wTAO price from Jupiter (Solana)."""
        # Use Jupiter quote API for wTAO/USDC
        # Implementation depends on wTAO mint address
        pass
    
    async def run_daemon(self):
        """Main daemon loop."""
        print(f"[DAEMON] Starting correlated pair bot")
        print(f"[DAEMON] Pair: {self.config.leading_token}/{self.config.lagging_token}")
        print(f"[DAEMON] Movement threshold: {self.config.movement_threshold_pct}%")
        print(f"[DAEMON] Spread threshold: {self.config.spread_threshold_pct}%")
        print(f"[DAEMON] What-if mode: {self.config.what_if_mode}")
        
        while True:
            try:
                await self.check_and_trade()
            except Exception as e:
                print(f"[ERROR] {e}")
            
            await asyncio.sleep(self.config.check_interval_sec)
    
    async def check_and_trade(self):
        """Single iteration of check and potentially trade."""
        # Fetch current prices
        leading_price = await self.fetch_tao_price()
        lagging_price = await self.fetch_wtao_price()
        
        # Calculate spread
        spread_pct = (leading_price - lagging_price) / leading_price * 100
        
        # Calculate movement (requires price history)
        movement_pct = self.calculate_movement(leading_price)
        
        # Store snapshot
        snapshot = PairSnapshot(
            timestamp=time.time(),
            leading_price=leading_price,
            lagging_price=lagging_price,
            spread_pct=spread_pct,
            leading_movement_pct=movement_pct
        )
        self.price_history.append(snapshot)
        
        # Check conditions
        movement_triggered = abs(movement_pct) > self.config.movement_threshold_pct
        spread_triggered = abs(spread_pct) > self.config.spread_threshold_pct
        
        should_trade = False
        if self.config.require_both_conditions:
            should_trade = movement_triggered and spread_triggered
        else:
            should_trade = movement_triggered or spread_triggered
        
        # Log status
        status = "🟢" if should_trade else "⚪"
        print(f"{status} Leading: ${leading_price:.2f} | "
              f"Lagging: ${lagging_price:.2f} | "
              f"Spread: {spread_pct:+.2f}% | "
              f"Movement: {movement_pct:+.2f}%")
        
        if should_trade and self.can_trade():
            await self.execute_trade(snapshot)
    
    def calculate_movement(self, current_price: float) -> float:
        """Calculate leading token movement over lookback window."""
        if not self.price_history:
            return 0.0
        
        cutoff_time = time.time() - self.config.lookback_window_sec
        old_snapshots = [s for s in self.price_history if s.timestamp < cutoff_time]
        
        if not old_snapshots:
            return 0.0
        
        old_price = old_snapshots[-1].leading_price
        return (current_price - old_price) / old_price * 100
    
    def can_trade(self) -> bool:
        """Check if cooldown has passed."""
        return time.time() - self.last_trade_time > self.cooldown_sec
    
    async def execute_trade(self, snapshot: PairSnapshot):
        """Execute or simulate trade."""
        direction = "BUY" if snapshot.spread_pct > 0 else "SELL"
        
        if self.config.what_if_mode:
            print(f"[WHAT-IF] Would {direction} {self.config.lagging_token}")
            print(f"[WHAT-IF] Spread: {snapshot.spread_pct:.2f}%")
            print(f"[WHAT-IF] Expected profit: ~{abs(snapshot.spread_pct):.2f}%")
        else:
            # Real execution
            print(f"[TRADE] Executing {direction} {self.config.lagging_token}")
            # ... actual trade execution ...
        
        self.last_trade_time = time.time()
```

---

## CLI Interface

### Command Examples

```bash
# Run daemon for TAO/wTAO with 1% spread threshold
python correlated_pair_bot.py \
    --leading TAO \
    --lagging wTAO \
    --spread-threshold 1.0 \
    --daemon

# Run with movement threshold (leading indicator mode)
python correlated_pair_bot.py \
    --leading BTC \
    --lagging SOL \
    --movement-threshold 2.0 \
    --correlation-factor 0.8 \
    --daemon

# Require BOTH conditions
python correlated_pair_bot.py \
    --leading TAO \
    --lagging wTAO \
    --spread-threshold 1.0 \
    --movement-threshold 1.5 \
    --require-both \
    --daemon

# One-shot check (no daemon)
python correlated_pair_bot.py \
    --leading TAO \
    --lagging wTAO \
    --spread-threshold 1.0

# What-if mode (paper trading)
python correlated_pair_bot.py \
    --leading TAO \
    --lagging wTAO \
    --spread-threshold 0.5 \
    --what-if \
    --daemon
```

### Configuration File

```yaml
# config/correlated_pairs.yaml
pairs:
  - name: "TAO/wTAO Spread"
    leading: "TAO"
    lagging: "wTAO"
    spread_threshold_pct: 1.0
    movement_threshold_pct: 0  # Disabled, use spread only
    require_both: false
    
  - name: "BTC Leading SOL"
    leading: "BTC"
    lagging: "SOL"
    spread_threshold_pct: 0  # Disabled
    movement_threshold_pct: 2.0
    correlation_factor: 0.8
    require_both: false

daemon:
  check_interval_sec: 10
  trade_cooldown_sec: 60
  
trading:
  trade_amount_usd: 100
  max_slippage_pct: 0.5
  what_if_mode: true
```

---

## Risk Considerations

### Wrapped Token Risks (TAO/wTAO)

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Bridge risk** | Bridge could be exploited | Check bridge security, use trusted bridges |
| **Liquidity** | wTAO may have low liquidity | Check slippage before trade |
| **Depeg** | Wrapper contract issue | Monitor peg health |
| **Gas costs** | Cross-chain trades expensive | Account for gas in profit calc |

### Leading Indicator Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Correlation breakdown** | Historical correlation may not hold | Use confidence intervals |
| **Front-running** | Others see same signal | Use faster execution |
| **False signals** | Movement doesn't predict lagging | Require minimum movement |
| **Market regime change** | Correlations shift over time | Recalibrate regularly |

---

## Profit Calculation

### For Spread Arbitrage

```python
def calculate_profit(
    spread_pct: float,
    trade_amount: float,
    swap_fee_pct: float = 0.3,
    gas_cost_usd: float = 0.01
) -> dict:
    gross_profit = trade_amount * (spread_pct / 100)
    swap_fees = trade_amount * (swap_fee_pct / 100) * 2  # Buy + Sell
    net_profit = gross_profit - swap_fees - gas_cost_usd
    
    return {
        "gross_profit": gross_profit,
        "swap_fees": swap_fees,
        "gas_cost": gas_cost_usd,
        "net_profit": net_profit,
        "profitable": net_profit > 0
    }

# Example
calc = calculate_profit(spread_pct=1.5, trade_amount=1000)
# gross_profit: $15.00
# swap_fees: $6.00
# net_profit: $8.99
```

### Minimum Viable Spread

```
Min Spread = (2 × swap_fee_pct) + (gas_cost / trade_amount × 100) + profit_margin

Example:
Min Spread = (2 × 0.3%) + ($0.01 / $1000 × 100) + 0.1%
Min Spread = 0.6% + 0.001% + 0.1%
Min Spread ≈ 0.7%
```

---

## Integration with Existing Bot

### Shared Components

| Component | Reusable? | Notes |
|-----------|-----------|-------|
| `dex/jupiterutil.py` | ✅ Yes | For wTAO swaps on Solana |
| `config.py` | ✅ Yes | Configuration patterns |
| `historyutil.py` | ✅ Yes | Trade logging |
| `coingeckoutil.py` | ✅ Yes | Price fetching |

### New Components Needed

| Component | Purpose |
|-----------|---------|
| `correlated_pair_bot.py` | Main daemon |
| `config/correlated_pairs.yaml` | Pair definitions |
| `correlation_analyzer.py` | Historical correlation analysis |
| `cp_history.py` | Correlated pair trade history |

---

## Monitoring and Alerts

### Daemon Output

```
[2026-05-01 10:30:00] 🟢 TAO: $450.23 | wTAO: $445.12 | Spread: +1.13% | Movement: +0.45%
[2026-05-01 10:30:00] [SIGNAL] Spread threshold exceeded (1.13% > 1.0%)
[2026-05-01 10:30:00] [WHAT-IF] Would BUY wTAO
[2026-05-01 10:30:00] [WHAT-IF] Expected profit: ~1.13% ($11.30 on $1000)

[2026-05-01 10:30:10] ⚪ TAO: $450.50 | wTAO: $446.80 | Spread: +0.82% | Movement: +0.51%
[2026-05-01 10:30:20] ⚪ TAO: $450.45 | wTAO: $448.20 | Spread: +0.50% | Movement: +0.50%
```

### Alert Thresholds

```python
alert_config = {
    "spread_warning": 2.0,   # Alert if spread > 2%
    "spread_critical": 5.0,  # Critical if spread > 5%
    "movement_warning": 5.0, # Alert if movement > 5%
    "depeg_alert": 10.0,     # Major depeg alert
}
```

---

## Historical Analysis Tool

Before running the daemon, analyze historical correlation:

```python
async def analyze_correlation(
    leading: str,
    lagging: str,
    days: int = 30
) -> dict:
    """Analyze historical price correlation between two assets."""
    
    # Fetch historical prices
    leading_prices = await fetch_historical(leading, days)
    lagging_prices = await fetch_historical(lagging, days)
    
    # Calculate correlation
    correlation = np.corrcoef(leading_prices, lagging_prices)[0, 1]
    
    # Calculate lag (how long until lagging follows leading)
    cross_corr = np.correlate(leading_prices, lagging_prices, mode='full')
    lag_minutes = np.argmax(cross_corr) - len(leading_prices)
    
    # Calculate typical spread (for wrapped pairs)
    spreads = (leading_prices - lagging_prices) / leading_prices * 100
    
    return {
        "correlation": correlation,
        "lag_minutes": lag_minutes,
        "mean_spread_pct": np.mean(spreads),
        "std_spread_pct": np.std(spreads),
        "max_spread_pct": np.max(np.abs(spreads)),
        "spread_95_percentile": np.percentile(np.abs(spreads), 95)
    }
```

---

## Recommended Pairs to Monitor

### Wrapped Token Pairs (Spread Arbitrage)

| Native | Wrapped | Chain | Expected Spread |
|--------|---------|-------|-----------------|
| TAO | wTAO | Solana/Ethereum | 0.5-2% |
| BTC | WBTC | Ethereum | 0.1-0.5% |
| ETH | WETH | Various | ~0% (native wrap) |
| SOL | wSOL | Ethereum | 0.2-1% |

### Leading Indicator Pairs

| Leading | Lagging | Correlation | Typical Lag |
|---------|---------|-------------|-------------|
| BTC | ETH | 0.85-0.95 | 1-5 min |
| BTC | SOL | 0.70-0.85 | 5-15 min |
| SOL | RAY | 0.80-0.90 | 1-5 min |
| ETH | LINK | 0.75-0.85 | 5-10 min |

---

## Next Steps

1. **Implement TAO/wTAO spread monitoring** - Start with this pair
2. **Run historical analysis** - Determine typical spreads and thresholds
3. **Deploy in what-if mode** - Paper trade for 1 week
4. **Analyze results** - Calculate theoretical P&L
5. **Consider live execution** - If results are positive

---

## Resources

- **TAO Bridge**: https://bridge.taostats.io/
- **wTAO on Solana**: Check Jupiter for liquidity
- **Correlation Analysis**: Use `pandas` and `numpy` for historical analysis
- **CoinGecko API**: Free tier for price data
