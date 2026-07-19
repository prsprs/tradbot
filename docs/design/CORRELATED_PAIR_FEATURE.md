# Correlated Pair Trading Feature

## Overview

This document explores a trading strategy where **one coin acts as a leading indicator** for another, allowing a bot to predict price movements and trade ahead of them. This is distinct from arbitrage (same asset, different venues) and instead exploits **temporal price correlation** between related assets.

**Primary Use Cases:**
1. **Cross-exchange arbitrage** (Buy wrapped on DEX, sell native on CEX simultaneously)
2. **Single-sided spread trading** (Trade wrapped token expecting convergence)
3. **Ecosystem tokens** (e.g., SOL leading RAY, ORCA) — *deferred for MVP*
4. **Correlated assets** (e.g., BTC leading altcoins) — *deferred for MVP*

---

## Strategy Types

### Type 1: Cross-Exchange Arbitrage (Primary MVP Strategy)

Execute simultaneous trades on **any two exchanges** to capture the spread without directional risk.

#### Supported Exchange Combinations

| Combination | Exchange A | Exchange B | Example Use Case |
|-------------|-----------|-----------|------------------|
| **DEX ↔ CEX** | Jupiter | Coinbase | wTAO/TAO, WBTC/BTC |
| **CEX ↔ CEX** | Coinbase | Binance | BTC price differences |
| **DEX ↔ DEX** | Jupiter | Raydium | Same token, different pools |

#### Exchange Registry

```python
@dataclass
class ExchangeConfig:
    """Configuration for a supported exchange."""
    name: str                    # e.g., "jupiter", "coinbase", "binance"
    exchange_type: str           # "dex" or "cex"
    supported_tokens: list[str]  # Tokens available on this exchange
    api_module: str              # Python module for API calls
    requires_api_key: bool       # Whether API key is needed
    
SUPPORTED_EXCHANGES = {
    # DEXs
    "jupiter": ExchangeConfig(
        name="jupiter",
        exchange_type="dex",
        supported_tokens=["wTAO", "WBTC", "WETH", "SOL", "USDC"],
        api_module="dex.jupiterutil",
        requires_api_key=False
    ),
    "raydium": ExchangeConfig(
        name="raydium",
        exchange_type="dex",
        supported_tokens=["SOL", "RAY", "USDC"],
        api_module="dex.raydiumutil",
        requires_api_key=False
    ),
    # CEXs
    "coinbase": ExchangeConfig(
        name="coinbase",
        exchange_type="cex",
        supported_tokens=["BTC", "ETH", "SOL", "TAO", "USDC"],
        api_module="coinbaseutil2",
        requires_api_key=True
    ),
    "binance": ExchangeConfig(
        name="binance",
        exchange_type="cex",
        supported_tokens=["BTC", "ETH", "SOL", "TAO", "BNB"],
        api_module="binanceutil",
        requires_api_key=True
    ),
}
```

#### Example: DEX ↔ CEX (wTAO/TAO)

```
- wTAO on Jupiter (DEX): $445.00
- TAO on Coinbase (CEX): $450.00
- Spread: 1.1%

Strategy: 
  Leg A: BUY wTAO on Jupiter at $445
  Leg B: SELL TAO on Coinbase at $450
  Profit: ~$5 per TAO (minus fees)
```

#### Example: CEX ↔ CEX (BTC price difference)

```
- BTC on Coinbase: $67,450
- BTC on Binance: $67,520
- Spread: 0.1%

Strategy:
  Leg A: BUY BTC on Coinbase at $67,450
  Leg B: SELL BTC on Binance at $67,520
  Profit: ~$70 per BTC (minus fees)
```

#### Example: DEX ↔ DEX (same token, different liquidity)

```
- SOL on Jupiter (via Orca pool): $148.50
- SOL on Raydium: $149.00
- Spread: 0.34%

Strategy:
  Leg A: BUY SOL on Jupiter at $148.50
  Leg B: SELL SOL on Raydium at $149.00
```

**Key advantage:** No need to keep balances in sync between exchanges. Over time, positions naturally rebalance as the spread reverses direction.

**Why this works:**
- Same asset (or wrapped equivalent) on different venues
- Price MUST converge (arbitrageurs ensure this)
- You profit from temporary inefficiency, not directional movement
- No inventory risk if you trade both directions over time

### Type 2: Single-Sided Spread Trading

When a native token has a wrapped version on another chain, price discrepancies arise due to:

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

**Note:** Single-sided trading has directional risk (you're betting on convergence timing). Cross-exchange arbitrage (Type 1) is preferred when CEX access is available.

**Key Insight:** The native token price typically **leads** the wrapped token price because:
1. Primary trading happens on native chain
2. Wrapped version arbitrages toward native price
3. Bridge mechanics create lag

### Type 3: Leading Indicator Prediction (Deferred)

One asset's price movement **predicts** another's movement with a time delay.

```
Example:
- BTC rises 2% in 5 minutes
- Historical data shows: when BTC rises >1.5%, SOL follows with 0.8x magnitude
- Prediction: SOL will rise ~1.6% in next 10-30 minutes

Action: Buy SOL immediately after detecting BTC movement
```

### Type 4: Correlation Breakdown Reversion (Deferred)

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
class ArbitrageBotConfig:
    # Exchange pair (uses ArbitragePairConfig for token details)
    exchange_a: str              # e.g., "jupiter"
    exchange_b: str              # e.g., "coinbase" (None for single-sided)
    token: str                   # e.g., "TAO" (base token)
    
    # Thresholds
    spread_threshold_pct: float = 1.0      # Spread must exceed 1%
    
    # Timing
    check_interval_sec: int = 10           # Check every 10 seconds
    cooldown_sec: int = 60                 # Cooldown between trades
    
    # Trade parameters
    trade_amount_usd: float = 100.0
    max_slippage_pct: float = 0.5
    
    # Mode
    mode: str = "cross-exchange"           # "cross-exchange" or "single-sided"
    what_if_mode: bool = True              # Paper trading
```

### Daemon Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    DAEMON MAIN LOOP                         │
├─────────────────────────────────────────────────────────────┤
│  1. Fetch price from Exchange A                             │
│  2. Fetch price from Exchange B (if cross-exchange mode)    │
│  3. Calculate spread % between exchanges                    │
│  4. Check threshold:                                        │
│     - spread_pct > spread_threshold?                        │
│  5. If threshold exceeded:                                  │
│     - Build dual-leg signal (BUY on cheaper, SELL on other) │
│     - Execute both legs (or log in what-if mode)            │
│  6. Sleep for check_interval                                │
│  7. Repeat                                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Trade Logic

### Cross-Exchange Arbitrage (Dual-Leg Execution)

For Type 1 strategy, execute **both legs simultaneously** on any two exchanges to lock in the spread:

```python
@dataclass
class DualLegSignal:
    """Signal for cross-exchange arbitrage with two simultaneous trades."""
    # Leg A (first exchange)
    leg_a_action: str        # "BUY" or "SELL"
    leg_a_token: str         # Token symbol on exchange A (e.g., "wTAO")
    leg_a_exchange: str      # Exchange name (e.g., "jupiter", "coinbase")
    leg_a_price: float
    
    # Leg B (second exchange) - opposite action
    leg_b_action: str        # Opposite of leg_a_action
    leg_b_token: str         # Token symbol on exchange B (e.g., "TAO")
    leg_b_exchange: str      # Exchange name
    leg_b_price: float
    
    spread_pct: float
    expected_profit_usd: float
    reason: str

def get_cross_exchange_signal(
    price_a: float,          # Price on exchange A
    price_b: float,          # Price on exchange B
    spread_threshold: float,
    trade_amount_usd: float,
    token_a: str,            # Token symbol on exchange A
    token_b: str,            # Token symbol on exchange B
    exchange_a: str,         # Exchange A name
    exchange_b: str          # Exchange B name
) -> Optional[DualLegSignal]:
    """
    Detect cross-exchange arbitrage opportunity.
    Works with any two exchanges (DEX-DEX, CEX-CEX, or DEX-CEX).
    Returns dual-leg signal for simultaneous execution.
    """
    spread_pct = (price_b - price_a) / price_b * 100
    
    if abs(spread_pct) < spread_threshold:
        return None  # Spread too small
    
    # Calculate expected profit (before fees)
    quantity = trade_amount_usd / min(price_a, price_b)
    gross_profit = abs(price_b - price_a) * quantity
    
    if spread_pct > 0:
        # Price A is cheaper: BUY on A, SELL on B
        return DualLegSignal(
            leg_a_action="BUY",
            leg_a_token=token_a,
            leg_a_exchange=exchange_a,
            leg_a_price=price_a,
            leg_b_action="SELL",
            leg_b_token=token_b,
            leg_b_exchange=exchange_b,
            leg_b_price=price_b,
            spread_pct=spread_pct,
            expected_profit_usd=gross_profit,
            reason=f"{token_a}@{exchange_a} ${price_a:.2f} < {token_b}@{exchange_b} ${price_b:.2f} ({spread_pct:.2f}%)"
        )
    else:
        # Price A is more expensive: SELL on A, BUY on B
        return DualLegSignal(
            leg_a_action="SELL",
            leg_a_token=token_a,
            leg_a_exchange=exchange_a,
            leg_a_price=price_a,
            leg_b_action="BUY",
            leg_b_token=token_b,
            leg_b_exchange=exchange_b,
            leg_b_price=price_b,
            spread_pct=abs(spread_pct),
            expected_profit_usd=gross_profit,
            reason=f"{token_a}@{exchange_a} ${price_a:.2f} > {token_b}@{exchange_b} ${price_b:.2f} ({abs(spread_pct):.2f}%)"
        )
```

### Execution Flow (Cross-Exchange)

```
┌─────────────────────────────────────────────────────────────┐
│              CROSS-EXCHANGE ARBITRAGE FLOW                  │
├─────────────────────────────────────────────────────────────┤
│  1. Fetch price from Exchange A                             │
│  2. Fetch price from Exchange B                             │
│  3. Calculate spread %                                      │
│  4. If spread > threshold:                                  │
│     a. Build transaction/order for Exchange A               │
│     b. Build transaction/order for Exchange B               │
│     c. Execute BOTH legs (parallel or sequential)           │
│     d. Log results                                          │
│  5. Track position per exchange for reporting               │
└─────────────────────────────────────────────────────────────┘
```

### Position Tracking

Since we're trading both directions, track cumulative positions per exchange:

```python
@dataclass
class PositionTracker:
    """Track positions across any two exchanges for rebalancing awareness."""
    exchange_a_name: str
    exchange_b_name: str
    exchange_a_balance: float = 0.0   # Token balance on exchange A
    exchange_b_balance: float = 0.0   # Token balance on exchange B
    
    total_trades: int = 0
    total_profit_usd: float = 0.0
    
    def update_after_trade(self, signal: DualLegSignal, quantity: float):
        if signal.leg_a_action == "BUY":
            self.exchange_a_balance += quantity
            self.exchange_b_balance -= quantity
        else:
            self.exchange_a_balance -= quantity
            self.exchange_b_balance += quantity
        
        self.total_trades += 1
        self.total_profit_usd += signal.expected_profit_usd
    
    def get_imbalance(self) -> float:
        """Returns position imbalance (positive = more on A, negative = more on B)."""
        return self.exchange_a_balance - self.exchange_b_balance
    
    def summary(self) -> str:
        return (f"{self.exchange_a_name}: {self.exchange_a_balance:.4f} | "
                f"{self.exchange_b_name}: {self.exchange_b_balance:.4f} | "
                f"Trades: {self.total_trades} | Profit: ${self.total_profit_usd:.2f}")
```

---

### Single-Sided Spread Trading (Type 2)

For single-sided trading (when second exchange not available), only trade on exchange A:

```python
def get_single_sided_signal(
    price_a: float,          # Price on exchange A (where we trade)
    reference_price: float,  # Reference price (e.g., CoinGecko)
    spread_threshold: float,
    token_a: str,
    exchange_a: str
) -> Optional[Signal]:
    spread_pct = (reference_price - price_a) / reference_price * 100
    
    if spread_pct > spread_threshold:
        # Exchange A is cheaper - BUY
        return Signal(
            action="BUY",
            token=token_a,
            exchange=exchange_a,
            reason=f"{token_a}@{exchange_a} trading at {spread_pct:.2f}% discount",
            expected_profit_pct=spread_pct
        )
    elif spread_pct < -spread_threshold:
        # Exchange A is more expensive - SELL
        return Signal(
            action="SELL",
            token=token_a,
            exchange=exchange_a,
            reason=f"{token_a}@{exchange_a} trading at {-spread_pct:.2f}% premium",
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

## Implementation: Generic Arbitrage Pair Bot

### Arbitrage Pair Registry

The bot supports arbitrary exchange pairs via a configurable registry:

```python
@dataclass
class ExchangeTokenInfo:
    """Token info for a specific exchange."""
    symbol: str              # Token symbol on this exchange (e.g., "wTAO", "TAO")
    exchange: str            # Exchange name (e.g., "jupiter", "coinbase")
    # Exchange-specific identifiers (only one needed per exchange type)
    mint: str = ""           # Solana mint address (for DEX)
    coingecko_id: str = ""   # CoinGecko ID (for price lookup fallback)

@dataclass
class ArbitragePairConfig:
    """Configuration for an arbitrage pair on any two exchanges."""
    name: str                        # Human-readable name
    token_a: ExchangeTokenInfo       # Token info for exchange A
    token_b: ExchangeTokenInfo       # Token info for exchange B
    description: str = ""

# Pre-configured pairs (can be extended via config file)
DEFAULT_PAIRS = {
    # DEX ↔ CEX pairs
    "TAO:jupiter/coinbase": ArbitragePairConfig(
        name="TAO/wTAO",
        token_a=ExchangeTokenInfo(
            symbol="wTAO",
            exchange="jupiter",
            mint="2Sj3mHJsU...",  # wTAO SPL mint
        ),
        token_b=ExchangeTokenInfo(
            symbol="TAO",
            exchange="coinbase",
        ),
        description="wTAO on Jupiter vs TAO on Coinbase"
    ),
    "BTC:jupiter/coinbase": ArbitragePairConfig(
        name="BTC/WBTC",
        token_a=ExchangeTokenInfo(
            symbol="WBTC",
            exchange="jupiter",
            mint="3NZ9JMVBm...",  # WBTC SPL mint
        ),
        token_b=ExchangeTokenInfo(
            symbol="BTC",
            exchange="coinbase",
        ),
        description="WBTC on Jupiter vs BTC on Coinbase"
    ),
    # CEX ↔ CEX pairs
    "BTC:coinbase/binance": ArbitragePairConfig(
        name="BTC cross-CEX",
        token_a=ExchangeTokenInfo(
            symbol="BTC",
            exchange="coinbase",
        ),
        token_b=ExchangeTokenInfo(
            symbol="BTC",
            exchange="binance",
        ),
        description="BTC on Coinbase vs BTC on Binance"
    ),
    # DEX ↔ DEX pairs
    "SOL:jupiter/raydium": ArbitragePairConfig(
        name="SOL cross-DEX",
        token_a=ExchangeTokenInfo(
            symbol="SOL",
            exchange="jupiter",
            mint="So11111111111111111111111111111111111111112",
        ),
        token_b=ExchangeTokenInfo(
            symbol="SOL",
            exchange="raydium",
            mint="So11111111111111111111111111111111111111112",
        ),
        description="SOL on Jupiter vs SOL on Raydium"
    ),
}
```

### Pair Lookup Logic

```python
def get_pair_config(token: str, exchange_a: str, exchange_b: str) -> ArbitragePairConfig:
    """
    Look up or generate pair config.
    First checks DEFAULT_PAIRS, then auto-generates from exchange registry.
    """
    key = f"{token}:{exchange_a}/{exchange_b}"
    if key in DEFAULT_PAIRS:
        return DEFAULT_PAIRS[key]
    
    # Auto-generate from exchange registry
    return ArbitragePairConfig(
        name=f"{token} ({exchange_a}/{exchange_b})",
        token_a=ExchangeTokenInfo(
            symbol=get_token_symbol(token, exchange_a),  # e.g., "wTAO" for jupiter
            exchange=exchange_a,
            mint=get_mint_if_dex(token, exchange_a),
        ),
        token_b=ExchangeTokenInfo(
            symbol=get_token_symbol(token, exchange_b),  # e.g., "TAO" for coinbase
            exchange=exchange_b,
        ),
    )
```

### Example Implementation

```python
#!/usr/bin/env python3
"""
arbitrage_pair_bot.py - Daemon for cross-exchange arbitrage trading
Supports arbitrary exchange pairs via configuration.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict
import aiohttp

@dataclass
class PriceSnapshot:
    timestamp: float
    price_a: float           # Price on exchange A
    price_b: float           # Price on exchange B (0 if single-sided)
    spread_pct: float

class ArbitragePairBot:
    def __init__(self, config: ArbitrageBotConfig, pair_config: ArbitragePairConfig):
        self.config = config
        self.pair_config = pair_config
        self.price_history = []
        self.last_trade_time = 0
        self.position_tracker = PositionTracker(
            exchange_a_name=config.exchange_a,
            exchange_b_name=config.exchange_b or "reference"
        )
        
    async def fetch_price(self, token_info: ExchangeTokenInfo) -> float:
        """Fetch price from any configured exchange."""
        exchange = token_info.exchange
        
        if exchange == "jupiter":
            return await self._fetch_jupiter_price(token_info.mint)
        elif exchange == "raydium":
            return await self._fetch_raydium_price(token_info.mint)
        elif exchange == "coinbase":
            return await self._fetch_coinbase_price(token_info.symbol)
        elif exchange == "binance":
            return await self._fetch_binance_price(token_info.symbol)
        else:
            # Fallback to CoinGecko
            return await self._fetch_coingecko_price(token_info.coingecko_id)
    
    async def _fetch_jupiter_price(self, mint: str) -> float:
        """Fetch token price via Jupiter quote."""
        # Use Jupiter quote API for token/USDC
        pass
    
    async def _fetch_coinbase_price(self, symbol: str) -> float:
        """Fetch from Coinbase using existing coinbaseutil2.py."""
        pass
    
    async def _fetch_coingecko_price(self, coingecko_id: str) -> float:
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": coingecko_id, "vs_currencies": "usd"}
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data[coingecko_id]["usd"]
    
    async def run_daemon(self):
        """Main daemon loop."""
        print(f"[DAEMON] Starting arbitrage pair bot")
        print(f"[DAEMON] Mode: {self.config.mode}")
        print(f"[DAEMON] Exchange A: {self.config.exchange_a}")
        print(f"[DAEMON] Exchange B: {self.config.exchange_b}")
        print(f"[DAEMON] Token: {self.config.token}")
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
        # Fetch current prices from both exchanges
        price_a = await self.fetch_price(self.pair_config.token_a)
        price_b = await self.fetch_price(self.pair_config.token_b)
        
        # Calculate spread
        spread_pct = (price_b - price_a) / price_b * 100
        
        # Store snapshot
        snapshot = PriceSnapshot(
            timestamp=time.time(),
            price_a=price_a,
            price_b=price_b,
            spread_pct=spread_pct
        )
        self.price_history.append(snapshot)
        
        # Check threshold
        spread_triggered = abs(spread_pct) > self.config.spread_threshold_pct
        
        # Log status
        token_a = self.pair_config.token_a.symbol
        token_b = self.pair_config.token_b.symbol
        status = "🟢" if spread_triggered else "⚪"
        print(f"{status} {token_a}@{self.config.exchange_a}: ${price_a:.2f} | "
              f"{token_b}@{self.config.exchange_b}: ${price_b:.2f} | "
              f"Spread: {spread_pct:+.2f}%")
        
        if spread_triggered and self.can_trade():
            await self.execute_trade(snapshot, price_a, price_b)
    
    def can_trade(self) -> bool:
        """Check if cooldown has passed."""
        return time.time() - self.last_trade_time > self.config.cooldown_sec
    
    async def execute_trade(self, snapshot: PriceSnapshot, price_a: float, price_b: float):
        """Execute or simulate dual-leg trade."""
        signal = get_cross_exchange_signal(
            price_a=price_a,
            price_b=price_b,
            spread_threshold=self.config.spread_threshold_pct,
            trade_amount_usd=self.config.trade_amount_usd,
            token_a=self.pair_config.token_a.symbol,
            token_b=self.pair_config.token_b.symbol,
            exchange_a=self.config.exchange_a,
            exchange_b=self.config.exchange_b
        )
        
        if self.config.what_if_mode:
            print(f"[WHAT-IF] {signal.reason}")
            print(f"[WHAT-IF] Leg A: {signal.leg_a_action} {signal.leg_a_token}@{signal.leg_a_exchange}")
            print(f"[WHAT-IF] Leg B: {signal.leg_b_action} {signal.leg_b_token}@{signal.leg_b_exchange}")
            print(f"[WHAT-IF] Expected profit: ${signal.expected_profit_usd:.2f}")
        else:
            # Real execution - execute both legs
            print(f"[TRADE] Executing dual-leg arbitrage")
            # ... actual trade execution on both exchanges ...
        
        self.last_trade_time = time.time()
```

---

## CLI Interface

### Command Examples

```bash
# ═══════════════════════════════════════════════════════════════
# CROSS-EXCHANGE ARBITRAGE (Primary MVP Mode)
# Trade same/equivalent asset on any two exchanges
# ═══════════════════════════════════════════════════════════════

# DEX ↔ CEX: wTAO on Jupiter <-> TAO on Coinbase
python correlated_pair_bot.py \
    --token TAO \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --spread-threshold 1.0 \
    --daemon

# DEX ↔ CEX: WBTC on Jupiter <-> BTC on Coinbase
python correlated_pair_bot.py \
    --token BTC \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --spread-threshold 0.5 \
    --daemon

# CEX ↔ CEX: BTC on Coinbase <-> BTC on Binance
python correlated_pair_bot.py \
    --token BTC \
    --exchange-a coinbase \
    --exchange-b binance \
    --spread-threshold 0.1 \
    --daemon

# DEX ↔ DEX: SOL on Jupiter <-> SOL on Raydium
python correlated_pair_bot.py \
    --token SOL \
    --exchange-a jupiter \
    --exchange-b raydium \
    --spread-threshold 0.3 \
    --daemon

# What-if mode (paper trading both legs)
python correlated_pair_bot.py \
    --token TAO \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --spread-threshold 0.5 \
    --what-if \
    --daemon

# ═══════════════════════════════════════════════════════════════
# SINGLE-SIDED MODE (when second exchange not available)
# Only trade on one exchange, betting on convergence
# ═══════════════════════════════════════════════════════════════

# Single-sided: only trade wTAO on Jupiter
python correlated_pair_bot.py \
    --token TAO \
    --exchange-a jupiter \
    --mode single-sided \
    --spread-threshold 1.0 \
    --daemon

# ═══════════════════════════════════════════════════════════════
# ADDITIONAL OPTIONS
# ═══════════════════════════════════════════════════════════════

# Custom cooldown
python correlated_pair_bot.py \
    --token TAO \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --spread-threshold 1.0 \
    --cooldown 120 \
    --daemon

# One-shot check (no daemon)
python correlated_pair_bot.py \
    --token ETH \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --spread-threshold 0.5

# Specify token symbols explicitly (when they differ)
python correlated_pair_bot.py \
    --token-a wTAO \
    --token-b TAO \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --spread-threshold 1.0 \
    --daemon
```

### CLI Parameters Summary

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--token` | Base token (e.g., TAO, BTC, ETH) - auto-resolves wrapped/native per exchange | Required* |
| `--token-a` | Explicit token symbol on exchange A (e.g., wTAO) | Auto from `--token` |
| `--token-b` | Explicit token symbol on exchange B (e.g., TAO) | Auto from `--token` |
| `--exchange-a` | First exchange (jupiter, raydium, coinbase, binance) | Required |
| `--exchange-b` | Second exchange (for cross-exchange mode) | None |
| `--mode` | Trading mode: `cross-exchange` or `single-sided` | cross-exchange |
| `--spread-threshold` | Minimum spread % to trigger trade | 1.0 |
| `--cooldown` | Seconds between trades | 60 |
| `--what-if` | Paper trading mode | false |
| `--daemon` | Run continuously | false |

\* Either `--token` or both `--token-a` and `--token-b` required.

### Supported Exchanges

| Exchange | Type | Tokens | API Module | API Key Required |
|----------|------|--------|------------|------------------|
| `jupiter` | DEX | wTAO, WBTC, WETH, SOL, USDC, etc. | `dex.jupiterutil` | No |
| `raydium` | DEX | SOL, RAY, USDC, etc. | `dex.raydiumutil` | No |
| `coinbase` | CEX | BTC, ETH, SOL, TAO, USDC, etc. | `coinbaseutil2` | Yes |
| `binance` | CEX | BTC, ETH, SOL, TAO, BNB, etc. | `binanceutil` | Yes |

### Mode Comparison

| Mode | Exchange A | Exchange B | Risk Profile |
|------|------------|------------|--------------|
| `cross-exchange` | Any supported | Any supported | **Low** - positions rebalance over time |
| `single-sided` | Any supported | None | **Medium** - directional exposure until convergence |

### Configuration File

```yaml
# config/arbitrage_pairs.yaml
pairs:
  - name: "TAO Jupiter/Coinbase"
    token: "TAO"
    exchange_a: "jupiter"
    token_a: "wTAO"
    exchange_b: "coinbase"
    token_b: "TAO"
    spread_threshold_pct: 1.0
    
  - name: "BTC Coinbase/Binance"
    token: "BTC"
    exchange_a: "coinbase"
    token_a: "BTC"
    exchange_b: "binance"
    token_b: "BTC"
    spread_threshold_pct: 0.1
    
  - name: "SOL Jupiter/Raydium"
    token: "SOL"
    exchange_a: "jupiter"
    token_a: "SOL"
    exchange_b: "raydium"
    token_b: "SOL"
    spread_threshold_pct: 0.3

daemon:
  check_interval_sec: 10
  cooldown_sec: 60
  
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
[2026-05-01 10:30:00] [DAEMON] Starting arbitrage pair bot
[2026-05-01 10:30:00] [DAEMON] Mode: cross-exchange
[2026-05-01 10:30:00] [DAEMON] Exchange A: jupiter | Exchange B: coinbase
[2026-05-01 10:30:00] [DAEMON] Token: TAO
[2026-05-01 10:30:00] [DAEMON] Spread threshold: 1.0%

[2026-05-01 10:30:01] 🟢 wTAO@jupiter: $445.12 | TAO@coinbase: $450.23 | Spread: +1.13%
[2026-05-01 10:30:01] [WHAT-IF] wTAO@jupiter $445.12 < TAO@coinbase $450.23 (1.13%)
[2026-05-01 10:30:01] [WHAT-IF] Leg A: BUY wTAO@jupiter
[2026-05-01 10:30:01] [WHAT-IF] Leg B: SELL TAO@coinbase
[2026-05-01 10:30:01] [WHAT-IF] Expected profit: $11.30

[2026-05-01 10:30:11] ⚪ wTAO@jupiter: $446.80 | TAO@coinbase: $450.50 | Spread: +0.82%
[2026-05-01 10:30:21] ⚪ wTAO@jupiter: $448.20 | TAO@coinbase: $450.45 | Spread: +0.50%
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

## Open Questions

> **Note:** The suggested implementation in this document assumes the recommendations below are accepted. If different options are chosen, the implementation will need to be adjusted accordingly.

### 1. Which Strategy Type to Implement First?

| Option | Strategy | Complexity | Risk |
|--------|----------|------------|------|
| **A. Cross-exchange arbitrage** | Same/equivalent asset on two exchanges | Low | Low (same asset) |
| **B. Leading indicator** | BTC → SOL, ETH → alts | Medium | Medium (correlation may break) |
| **C. Correlation breakdown** | Mean reversion on divergence | High | High (trend may continue) |
| **D. All three** | Full implementation | High | Varies |

**Recommendation:** Option **A (Cross-exchange arbitrage)** first. It's the lowest risk since both sides represent the same underlying asset. Supports DEX↔CEX (TAO), CEX↔CEX (BTC), and DEX↔DEX (SOL) combinations.

### 2. Threshold Configuration Approach?

| Option | Description | Trade-off |
|--------|-------------|-----------|
| **A. Fixed thresholds** | Hardcoded spread/movement % | Simple, may not adapt |
| **B. Dynamic from history** | Calculate from recent data | Adapts, needs data |
| **C. User-configurable** | CLI/config file parameters | Flexible, requires tuning |
| **D. ML-based** | Learn optimal thresholds | Complex, best long-term |

**Recommendation:** Option **C (User-configurable)** via CLI flags and config file. This matches the existing bot's pattern (see `METHODS_OF_SPECIFYING_RUNTIME_OPTIONS.md`). Start with sensible defaults, allow override.

### 3. Spread Threshold Default?

| Option | Threshold | Rationale |
|--------|-----------|-----------|
| **A. Tight** | >0.5% | More trades, smaller profit |
| **B. Moderate** | >1.0% | Balance frequency/profit |
| **C. Wide** | >2.0% | Rare but larger trades |
| **D. Variable by exchange pair** | Different for DEX↔CEX vs CEX↔CEX | Accounts for exchange fees/liquidity |

**Recommendation:** Option **D (Variable by exchange pair)** with these defaults:
- **DEX ↔ CEX** (e.g., Jupiter/Coinbase): >1.0% (wrapped pairs have larger spreads)
- **CEX ↔ CEX** (e.g., Coinbase/Binance): >0.3% (tighter spreads, lower fees)
- **DEX ↔ DEX** (e.g., Jupiter/Raydium): >0.5% (same chain, moderate spreads)

### 4. Movement Threshold for Leading Indicators?

| Option | Threshold | Window | Rationale |
|--------|-----------|--------|-----------|
| **A. Small/Fast** | >1% in 5 min | Quick response, more noise |
| **B. Medium/Medium** | >2% in 15 min | Balanced signal quality |
| **C. Large/Slow** | >5% in 1 hour | Fewer signals, higher conviction |
| **D. Multi-timeframe** | Check multiple windows | Complex, comprehensive |

**⏸️ DEFERRED FOR MVP:** Leading indicator strategy is not in MVP scope. MVP focuses on wrapped pair spreads only. Revisit this question when implementing leading indicator functionality.

### 5. Condition Logic: AND vs OR?

When using both spread AND movement thresholds:

| Option | Logic | When to use |
|--------|-------|-------------|
| **A. OR (either)** | Trade if spread OR movement exceeds threshold | More trades, lower confidence |
| **B. AND (both)** | Trade only if spread AND movement exceed | Fewer trades, higher confidence |
| **C. Configurable** | User chooses per pair | Flexible |
| **D. Weighted score** | Combined score from both factors | Nuanced, complex |

**⏸️ DEFERRED FOR MVP:** Condition logic is not needed for wrapped pair spreads (MVP scope). Wrapped pairs use spread threshold only. Revisit when implementing leading indicator or correlation breakdown strategies.

### 6. Leg Execution Order?

When executing a dual-leg arbitrage trade:

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| **A. Parallel** | Execute both legs simultaneously | Fastest, locks spread | Complex error handling |
| **B. Sequential (faster first)** | Execute faster exchange first | Simpler | Spread may move |
| **C. Sequential (larger first)** | Execute larger leg first | Reduces risk | May miss opportunity |
| **D. Conditional** | Execute leg B only if leg A succeeds | Safest | May leave partial position |

**Recommendation:** Option **D (Conditional)** as default, with `--parallel-mode` flag to enable Option A.

- **Default (sequential/conditional):** Execute leg A first, only execute leg B if leg A succeeds. Safer, avoids partial fills.
- **Parallel mode:** Execute both legs simultaneously for speed. Use when exchanges are reliable.

```bash
# Default: conditional execution (safer)
python arbitrage_pair_bot.py --token TAO --exchange-a jupiter --exchange-b coinbase

# Parallel mode: simultaneous execution (faster)
python arbitrage_pair_bot.py --token TAO --exchange-a jupiter --exchange-b coinbase --parallel-mode
```

```python
async def execute_dual_leg(signal: DualLegSignal, parallel: bool = False):
    if parallel:
        # Option A: Execute both simultaneously
        results = await asyncio.gather(
            execute_on_exchange(signal.leg_a_exchange, signal.leg_a_action, signal.leg_a_token),
            execute_on_exchange(signal.leg_b_exchange, signal.leg_b_action, signal.leg_b_token),
            return_exceptions=True
        )
        if isinstance(results[0], Exception) or isinstance(results[1], Exception):
            log_partial_execution(results)
    else:
        # Option D: Execute leg A first, then leg B only if A succeeds
        result_a = await execute_on_exchange(signal.leg_a_exchange, signal.leg_a_action, signal.leg_a_token)
        if result_a.success:
            await execute_on_exchange(signal.leg_b_exchange, signal.leg_b_action, signal.leg_b_token)
        else:
            log_failed_execution(result_a)
```

### 7. Daemon Deployment Model?

| Option | Approach | Trade-off |
|--------|----------|-----------|
| **A. Single process** | One Python script | Simple, single point of failure |
| **B. Systemd service** | Linux service management | Auto-restart, logs |
| **C. Docker container** | Containerized deployment | Portable, isolated |
| **D. Cloud function** | AWS Lambda, triggered by timer | Scalable, pay-per-use |

**Recommendation:** Option **A (Single process)** initially, matching the existing bot pattern. Can run in `screen`/`tmux` for persistence. Upgrade to **B (Systemd)** for production deployment on a dedicated server.

### 8. Trade Cooldown Strategy?

After executing a trade, how long before allowing another?

| Option | Cooldown | Rationale |
|--------|----------|-----------|
| **A. Fixed time** | 60 seconds | Simple, prevents overtrading |
| **B. Until spread closes** | Wait for spread < threshold | Trade again when opportunity re-emerges |
| **C. Per-pair cooldown** | Different for each pair | Allows parallel opportunities |
| **D. No cooldown** | Trade on every signal | Maximum activity, risk of losses |

**Recommendation:** Option **A (Fixed time)** with configurable `--cooldown` parameter.

**CLI usage:**
```bash
# Default: 60-second cooldown
python arbitrage_pair_bot.py --token TAO --exchange-a jupiter --exchange-b coinbase

# Custom cooldown (in seconds)
python arbitrage_pair_bot.py --token TAO --exchange-a jupiter --exchange-b coinbase --cooldown 120
```

For MVP, a single global cooldown is sufficient. Per-pair cooldowns can be added later if needed.

### 9. Position Imbalance Limits?

Over time, positions on Exchange A and Exchange B may diverge. When should we alert or pause?

| Option | Limit | Action |
|--------|-------|--------|
| **A. No limit** | Unlimited imbalance | Simple, risky if one exchange has issues |
| **B. Absolute limit** | e.g., 10 tokens max difference | Pause trading when reached |
| **C. Percentage limit** | e.g., 80% of capital on one side | Alert, then pause |
| **D. Time-based rebalance** | Force rebalance after X hours | Predictable, may not be optimal |

**Recommendation:** Option **C (Percentage limit)** with warning thresholds only (no automatic pause).

```python
@dataclass
class ImbalanceConfig:
    warning_pct: float = 70.0     # Alert when 70% on one side
    critical_pct: float = 85.0    # Critical warning when 85% on one side
    
def check_imbalance(tracker: PositionTracker, config: ImbalanceConfig) -> str:
    total = abs(tracker.exchange_a_balance) + abs(tracker.exchange_b_balance)
    if total == 0:
        return "balanced"
    
    max_side = max(abs(tracker.exchange_a_balance), abs(tracker.exchange_b_balance))
    pct = (max_side / total) * 100
    
    if pct >= config.critical_pct:
        return "critical"  # Log critical warning, continue trading
    elif pct >= config.warning_pct:
        return "warning"   # Log warning, continue trading
    return "ok"
```

Warnings are logged but trading continues. User can manually pause if needed.

### 10. Fee Calculation per Exchange?

Different exchanges have different fee structures. How to calculate net profit?

| Exchange | Type | Typical Fee | Notes |
|----------|------|-------------|-------|
| Jupiter | DEX | 0.0-0.3% | Varies by route, includes slippage |
| Raydium | DEX | 0.25% | Fixed pool fee |
| Coinbase | CEX | 0.5-0.6% | Maker/taker, reduces with volume |
| Binance | CEX | 0.1% | Lower with BNB payment |

**Recommendation:** Include fee estimation in profitability check before executing:

```python
@dataclass
class ExchangeFees:
    exchange: str
    fee_pct: float       # Base fee percentage
    gas_estimate_usd: float = 0.0  # For DEX transactions

DEFAULT_FEES = {
    "jupiter": ExchangeFees("jupiter", 0.3, 0.01),
    "raydium": ExchangeFees("raydium", 0.25, 0.01),
    "coinbase": ExchangeFees("coinbase", 0.5, 0.0),
    "binance": ExchangeFees("binance", 0.1, 0.0),
}

def is_profitable(spread_pct: float, exchange_a: str, exchange_b: str, trade_usd: float) -> bool:
    fee_a = DEFAULT_FEES[exchange_a]
    fee_b = DEFAULT_FEES[exchange_b]
    total_fee_pct = fee_a.fee_pct + fee_b.fee_pct
    total_gas = fee_a.gas_estimate_usd + fee_b.gas_estimate_usd
    
    gross_profit = trade_usd * (spread_pct / 100)
    fee_cost = trade_usd * (total_fee_pct / 100) + total_gas
    
    return gross_profit > fee_cost
```

### 11. Token Symbol Mapping?

How to resolve base token (e.g., "TAO") to correct symbol on each exchange?

| Exchange | TAO | BTC | ETH | SOL |
|----------|-----|-----|-----|-----|
| Jupiter | wTAO | WBTC | WETH | SOL |
| Raydium | wTAO | WBTC | WETH | SOL |
| Coinbase | TAO | BTC | ETH | SOL |
| Binance | TAO | BTC | ETH | SOL |

**Recommendation:** Use a token mapping registry:

```python
TOKEN_MAPPING = {
    # base_token -> {exchange -> symbol}
    "TAO": {"jupiter": "wTAO", "raydium": "wTAO", "coinbase": "TAO", "binance": "TAO"},
    "BTC": {"jupiter": "WBTC", "raydium": "WBTC", "coinbase": "BTC", "binance": "BTC"},
    "ETH": {"jupiter": "WETH", "raydium": "WETH", "coinbase": "ETH", "binance": "ETH"},
    "SOL": {"jupiter": "SOL", "raydium": "SOL", "coinbase": "SOL", "binance": "SOL"},
}

def get_token_symbol(base_token: str, exchange: str) -> str:
    """Get the correct token symbol for a given exchange."""
    if base_token in TOKEN_MAPPING and exchange in TOKEN_MAPPING[base_token]:
        return TOKEN_MAPPING[base_token][exchange]
    return base_token  # Default: use base token as-is
```

This allows `--token TAO` to automatically resolve to `wTAO` on Jupiter and `TAO` on Coinbase.

### 12. Historical Spread Data Collection?

| Option | Source | Data Quality | Cost |
|--------|--------|--------------|------|
| **A. CoinGecko historical** | Free API | Daily candles | Free |
| **B. Binance API** | 1-minute candles | Excellent | Free |
| **C. Custom collection** | Build own database over time | Best for our needs | Time/storage |
| **D. Third-party data** | Kaiko, CoinMetrics | Institutional grade | $$$ |

**Recommendation:** Option **C (Custom collection)** for MVP.

Build our own database as the bot runs:
- Log all spread observations from both exchanges with timestamps
- Store price_a (Exchange A) and price_b (Exchange B) for each check
- Calculate and store spread history
- Track which direction spread moved (for pattern analysis)

This provides data specifically tailored to the exchange pairs we trade and accumulates over time for threshold tuning.

---

## Resources

- **TAO Bridge**: https://bridge.taostats.io/
- **wTAO on Solana**: Check Jupiter for liquidity
- **Correlation Analysis**: Use `pandas` and `numpy` for historical analysis
- **CoinGecko API**: Free tier for price data
