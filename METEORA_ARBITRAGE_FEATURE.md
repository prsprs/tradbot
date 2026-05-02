# Meteora Arbitrage Feature

## Overview

This document explores arbitrage opportunities on **Meteora**, Solana's dynamic liquidity protocol. Unlike Jupiter's JLP (a single LP token representing a perps liquidity pool), Meteora offers multiple AMM types with different arbitrage mechanics.

**Key Difference from JLP:**
- JLP arbitrage = premium/discount between market price and NAV of a single LP token
- Meteora arbitrage = price discrepancies across bins, pools, and external markets

---

## Meteora Product Suite

| Product | Type | Arbitrage Potential |
|---------|------|---------------------|
| **DLMM** | Dynamic Liquidity Market Maker | ⭐⭐⭐⭐ High - bin price mismatches |
| **DAMM v2** | Concentrated Liquidity AMM | ⭐⭐⭐ Medium - price range arbitrage |
| **DAMM v1** | Traditional AMM | ⭐⭐ Low - standard DEX arbitrage |
| **Dynamic Vault** | Yield aggregator | ⭐ Low - yield optimization, not arb |
| **DBC** | Dynamic Bonding Curve | ⭐⭐⭐ Medium - launch token arbitrage |

---

## DLMM: Primary Arbitrage Target

### What is DLMM?

DLMM (Dynamic Liquidity Market Maker) organizes liquidity into **discrete price bins**. Each bin:
- Has a fixed price (no slippage within the bin)
- Contains liquidity from LPs who chose that price range
- Earns fees when trades execute through it

This bin structure creates unique arbitrage opportunities not available in traditional AMMs.

### DLMM Fee Structure

| Fee Component | Description | Typical Range |
|---------------|-------------|---------------|
| **Base Fee** | Fixed fee per pool | 0.01% - 2% |
| **Variable Fee** | Dynamic based on volatility | 0% - 10%+ |
| **Protocol Fee** | Meteora's cut | 5% of total (20% for launch pools) |

**Key Formula:**
```
Total Fee = Base Fee + Variable Fee
Variable Fee = f(volatility_accumulator, bin_step, control_parameter)
```

The variable fee **increases during high volatility** to protect LPs from toxic arbitrage flow.

---

## Arbitrage Strategy 1: Bin Price Mismatch

### The Opportunity

When a DLMM pool's **active bin price** diverges from the **true market price** (e.g., Jupiter aggregate price), arbitrage exists.

```
Example:
- Jupiter SOL/USDC price: $150.00
- Meteora DLMM active bin: $149.50
- Spread: 0.33%

Action: Buy SOL on Meteora at $149.50, sell on Jupiter at $150.00
```

### Why This Happens

1. **Low liquidity pools** - Price doesn't update frequently
2. **New pools** - Initial price set incorrectly by creator
3. **Volatile markets** - Bins lag behind rapid price moves
4. **Whale trades** - Large trades push price through multiple bins

### Implementation Approach

```python
# Pseudocode for DLMM bin arbitrage

async def check_dlmm_arbitrage(pool_address: str):
    # 1. Get DLMM pool state
    dlmm = await DLMM.create(connection, pool_address)
    active_bin = dlmm.get_active_bin()
    dlmm_price = active_bin.price
    
    # 2. Get reference price (Jupiter)
    jupiter_price = await get_jupiter_price(token_mint)
    
    # 3. Calculate spread
    spread_pct = (jupiter_price - dlmm_price) / jupiter_price * 100
    
    # 4. Check if profitable after fees
    base_fee = pool.base_fee_bps / 10000
    variable_fee = calculate_variable_fee(pool)
    total_fee = base_fee + variable_fee
    
    if abs(spread_pct) > total_fee + MIN_PROFIT_MARGIN:
        return ArbitrageOpportunity(
            direction="BUY" if spread_pct > 0 else "SELL",
            spread=spread_pct,
            estimated_profit=spread_pct - total_fee
        )
```

### Challenges

| Challenge | Impact | Mitigation |
|-----------|--------|------------|
| **Dynamic fees spike during arb** | Fees increase as you trade | Account for fee increase in profit calc |
| **Multi-bin swaps** | Large trades cross bins, changing price | Simulate full swap path |
| **MEV competition** | Other bots front-run | Use Jito bundles |
| **Low liquidity** | Can't execute meaningful size | Filter pools by TVL |

---

## Arbitrage Strategy 2: Cross-Pool Arbitrage

### The Opportunity

Meteora hosts **multiple pools for the same token pair** with different configurations. Price can diverge between them.

```
Example:
- SOL/USDC DLMM Pool A (1bps bin step): $150.00
- SOL/USDC DLMM Pool B (10bps bin step): $149.80
- Spread: 0.13%

Action: Buy from Pool B, sell to Pool A (or route through Jupiter)
```

### Why This Happens

1. Different bin steps = different price granularity
2. Different base fees = different LP behavior
3. Different liquidity depths = different price impact
4. Launch pools vs established pools

### Implementation Approach

```python
async def check_cross_pool_arbitrage(token_pair: tuple):
    # Get all Meteora pools for this pair
    pools = await get_all_meteora_pools(token_pair)
    
    prices = []
    for pool in pools:
        price = await get_pool_price(pool)
        fees = await get_pool_fees(pool)
        prices.append({
            'pool': pool,
            'price': price,
            'fees': fees,
            'liquidity': pool.tvl
        })
    
    # Find best buy and sell pools
    sorted_by_price = sorted(prices, key=lambda x: x['price'])
    buy_pool = sorted_by_price[0]  # Lowest price
    sell_pool = sorted_by_price[-1]  # Highest price
    
    spread = (sell_pool['price'] - buy_pool['price']) / buy_pool['price']
    total_fees = buy_pool['fees'] + sell_pool['fees']
    
    if spread > total_fees + MIN_PROFIT:
        return CrossPoolArbitrage(buy_pool, sell_pool, spread)
```

---

## Arbitrage Strategy 3: Pool Imbalance Arbitrage

### The Opportunity

When a DLMM pool's price is **out of sync with the market**, Meteora provides a "Sync with Jupiter's price" feature. Bots can capture this before manual sync.

### Warning from Meteora Docs

> "LPs can first use the 'Sync with Jupiter's price' button to sync the pool price with Jupiter price before adding liquidity, to avoid the risk of loss due to arbitrage trades."

This explicitly acknowledges arbitrage opportunities exist when pools are out of sync.

### Detection

```python
async def find_imbalanced_pools():
    """Find DLMM pools where price differs significantly from Jupiter."""
    all_pools = await fetch_all_dlmm_pools()
    
    opportunities = []
    for pool in all_pools:
        dlmm_price = pool.active_bin_price
        jupiter_price = await get_jupiter_price(pool.token_mint)
        
        deviation = abs(dlmm_price - jupiter_price) / jupiter_price
        
        if deviation > 0.005:  # 0.5% threshold
            opportunities.append({
                'pool': pool.address,
                'dlmm_price': dlmm_price,
                'jupiter_price': jupiter_price,
                'deviation_pct': deviation * 100,
                'tvl': pool.tvl
            })
    
    return sorted(opportunities, key=lambda x: x['deviation_pct'], reverse=True)
```

---

## Arbitrage Strategy 4: DBC Launch Token Arbitrage

### The Opportunity

DBC (Dynamic Bonding Curve) pools are used for **token launches**. The bonding curve price can diverge from secondary market prices.

```
Example:
- New token launches on Meteora DBC at $0.10
- Token listed on Jupiter/Raydium at $0.12
- Spread: 20%

Action: Buy from DBC, sell on secondary market
```

### Key Differences from JLP

| Aspect | JLP Arbitrage | DBC Arbitrage |
|--------|---------------|---------------|
| **Asset** | Single LP token | New launch tokens |
| **Price mechanism** | NAV vs market | Bonding curve vs market |
| **Duration** | Ongoing | Limited (until curve completes) |
| **Risk** | Low (established token) | High (new token volatility) |
| **Competition** | Moderate | Extreme (snipers, MEV) |

### Challenges

- **Anti-sniper mechanisms**: Meteora has anti-sniper suite
- **High fees**: Launch pools have 20% protocol fee
- **Rug risk**: New tokens may be scams
- **Speed competition**: Need Jito/priority fees

---

## Fee Comparison: Meteora vs Jupiter JLP

| Aspect | Jupiter JLP | Meteora DLMM |
|--------|-------------|--------------|
| **Mint/Deposit Fee** | ~0.1% | 0% (no LP token) |
| **Redeem/Withdraw Fee** | ~0.1% | 0% (no LP token) |
| **Swap Fee** | N/A (not a swap) | 0.01% - 10%+ (dynamic) |
| **Protocol Fee** | 25% of fees | 5-20% of swap fee |
| **Lock-up** | None | None |
| **Instant Execution** | ✅ Yes | ✅ Yes |

### Key Insight

**Meteora has NO mint/redeem fees** because you're not buying an LP token - you're swapping directly. This is fundamentally different from JLP arbitrage.

| JLP Approach | Meteora Approach |
|--------------|------------------|
| Mint JLP at NAV | Swap Token A → Token B |
| Sell JLP on market | (Already have Token B) |
| Profit = market premium | Profit = price discrepancy |

---

## Technical Integration

### TypeScript SDK (Official)

```bash
npm install @meteora-ag/dlmm @coral-xyz/anchor @solana/web3.js
```

```typescript
import DLMM from '@meteora-ag/dlmm';
import { Connection, PublicKey } from '@solana/web3.js';

const connection = new Connection('https://api.mainnet-beta.solana.com');
const poolAddress = new PublicKey('POOL_ADDRESS');

// Create DLMM instance
const dlmm = await DLMM.create(connection, poolAddress);

// Get active bin (current price)
const activeBin = await dlmm.getActiveBin();
console.log('Active bin price:', activeBin.price);

// Get swap quote
const quote = await dlmm.swapQuote(
  inputAmount,
  inputMint,
  slippageBps,
  { shouldIncludePartialFill: true }
);
```

### Python Integration (via Solana RPC)

No official Python SDK exists. Options:

1. **Wrap TypeScript SDK** with subprocess calls
2. **Direct RPC calls** to parse pool accounts
3. **Use Jupiter API** (routes through Meteora pools automatically)

```python
# Option 3: Use Jupiter to access Meteora liquidity
from jupiterutil import JupiterClient

jupiter = JupiterClient()

# Jupiter automatically routes through best pools including Meteora
quote = jupiter.get_quote(
    input_mint=USDC_MINT,
    output_mint=SOL_MINT,
    amount=1000_000_000  # 1000 USDC
)

# Check if route uses Meteora
for hop in quote['routePlan']:
    if 'Meteora' in hop['swapInfo'].get('label', ''):
        print(f"Route uses Meteora: {hop}")
```

---

## Comparison: JLP vs Meteora Arbitrage

| Dimension | JLP True Arbitrage | Meteora DLMM Arbitrage |
|-----------|-------------------|------------------------|
| **Mechanism** | Mint at NAV, sell at premium | Swap at bin price, sell elsewhere |
| **Fees** | 0.2% round-trip | Variable (0.01% - 10%+) |
| **Frequency** | Rare (need large spreads) | More frequent (many pools) |
| **Competition** | Moderate | High (DEX arb is crowded) |
| **Complexity** | Medium | High (bin mechanics) |
| **Capital efficiency** | High | Medium (need to find opportunities) |
| **MEV risk** | Low | High |
| **Best for** | Large spread events | Active monitoring, fast execution |

---

## Recommended Implementation Approach

### Phase 1: Monitoring Only

1. **Build pool scanner** - Fetch all DLMM pools
2. **Track price deviations** - Compare active bin price to Jupiter
3. **Log opportunities** - Record spread, TVL, fees
4. **Analyze patterns** - Identify which pools have frequent deviations

### Phase 2: Simulation

1. **Paper trade** - Simulate arb executions
2. **Track slippage** - Compare expected vs actual (simulated) fills
3. **Fee modeling** - Understand dynamic fee behavior
4. **Profitability analysis** - Calculate net profit after all costs

### Phase 3: Execution (If Viable)

1. **Start small** - Low capital, high frequency
2. **Use Jito** - Priority fee bundles to avoid front-running
3. **Monitor competition** - If consistently front-run, may not be viable
4. **Scale cautiously** - DEX arb is highly competitive

---

## Execution Design

This section provides the full implementation design for live trading. The `--execute` flag enables real trades; `--what-if` (default) logs opportunities without trading.

### CLI Interface

```bash
# Monitoring only (default)
python meteora_arb.py --what-if

# Live execution
python meteora_arb.py --execute

# With parameters
python meteora_arb.py --execute \
    --min-spread 0.5 \
    --max-trade-size 100 \
    --pools SOL/USDC,BONK/SOL \
    --interval 10 \
    --use-jito
```

### Configuration Options

| Flag | Default | Description |
|------|---------|-------------|
| `--what-if` | ✓ | Log opportunities only, no trades |
| `--execute` | | Enable live trading |
| `--min-spread` | 0.5 | Minimum spread % to trigger trade |
| `--max-trade-size` | 50 | Max trade size in USD |
| `--pools` | all | Comma-separated pool pairs to monitor |
| `--interval` | 10 | Seconds between checks |
| `--use-jito` | false | Submit via Jito bundles for MEV protection |
| `--jito-tip` | 0.001 | Jito tip in SOL |
| `--cooldown` | 60 | Seconds between trades on same pool |

### Core Architecture

```python
# meteora_arb.py

import asyncio
from dataclasses import dataclass
from typing import Optional
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair

@dataclass
class ArbOpportunity:
    pool_address: str
    pair: str
    meteora_price: float
    jupiter_price: float
    spread_pct: float
    direction: str  # "buy_meteora" or "sell_meteora"
    estimated_profit_usd: float
    fees_usd: float
    net_profit_usd: float
    timestamp: float

@dataclass
class TradeResult:
    success: bool
    tx_signature: Optional[str]
    input_amount: float
    output_amount: float
    actual_spread: float
    fees_paid: float
    error: Optional[str]

class MeteoraArbBot:
    def __init__(self, config: dict):
        self.config = config
        self.execute_mode = config.get('execute', False)
        self.min_spread = config.get('min_spread', 0.5)
        self.max_trade_size = config.get('max_trade_size', 50)
        self.use_jito = config.get('use_jito', False)
        self.cooldowns: dict[str, float] = {}
        
        # Wallet setup (only loaded if execute mode)
        self.wallet: Optional[Keypair] = None
        if self.execute_mode:
            self.wallet = self._load_wallet()
        
        # RPC clients
        self.rpc = AsyncClient(config.get('rpc_url', 'https://api.mainnet-beta.solana.com'))
        self.jito_rpc = AsyncClient('https://mainnet.block-engine.jito.wtf/api/v1') if self.use_jito else None
    
    def _load_wallet(self) -> Keypair:
        """Load wallet from environment or file."""
        import os
        from base58 import b58decode
        
        private_key = os.environ.get('SOLANA_PRIVATE_KEY')
        if not private_key:
            raise ValueError("SOLANA_PRIVATE_KEY environment variable required for --execute mode")
        
        return Keypair.from_bytes(b58decode(private_key))
    
    async def run(self):
        """Main loop."""
        print(f"Starting Meteora Arb Bot")
        print(f"  Mode: {'EXECUTE' if self.execute_mode else 'WHAT-IF'}")
        print(f"  Min spread: {self.min_spread}%")
        print(f"  Max trade: ${self.max_trade_size}")
        print(f"  Jito: {'enabled' if self.use_jito else 'disabled'}")
        
        while True:
            try:
                opportunities = await self.scan_opportunities()
                
                for opp in opportunities:
                    if opp.spread_pct >= self.min_spread:
                        if self._check_cooldown(opp.pool_address):
                            await self.handle_opportunity(opp)
                
                await asyncio.sleep(self.config.get('interval', 10))
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(5)
    
    def _check_cooldown(self, pool: str) -> bool:
        """Check if pool is past cooldown period."""
        import time
        last_trade = self.cooldowns.get(pool, 0)
        cooldown = self.config.get('cooldown', 60)
        return time.time() - last_trade > cooldown
    
    async def scan_opportunities(self) -> list[ArbOpportunity]:
        """Scan configured pools for arbitrage opportunities."""
        opportunities = []
        
        for pool in self.config.get('pools', []):
            try:
                opp = await self._check_pool(pool)
                if opp:
                    opportunities.append(opp)
            except Exception as e:
                print(f"Error checking pool {pool}: {e}")
        
        return opportunities
    
    async def _check_pool(self, pool_config: dict) -> Optional[ArbOpportunity]:
        """Check single pool for arbitrage opportunity."""
        import time
        
        # Get Meteora DLMM price (via active bin)
        meteora_price = await self._get_meteora_price(pool_config['address'])
        
        # Get Jupiter aggregated price
        jupiter_price = await self._get_jupiter_price(
            pool_config['base_mint'],
            pool_config['quote_mint']
        )
        
        if not meteora_price or not jupiter_price:
            return None
        
        # Calculate spread
        spread_pct = ((jupiter_price - meteora_price) / meteora_price) * 100
        
        # Determine direction
        if spread_pct > 0:
            direction = "buy_meteora"  # Meteora cheaper, buy there
        else:
            direction = "sell_meteora"  # Meteora more expensive, sell there
            spread_pct = abs(spread_pct)
        
        # Estimate profit (simplified)
        trade_size = min(self.max_trade_size, pool_config.get('max_size', 100))
        gross_profit = trade_size * (spread_pct / 100)
        
        # Estimate fees
        base_fee_pct = pool_config.get('base_fee', 0.25)
        estimated_fees = trade_size * (base_fee_pct / 100) * 2  # Round trip
        
        net_profit = gross_profit - estimated_fees
        
        return ArbOpportunity(
            pool_address=pool_config['address'],
            pair=pool_config['pair'],
            meteora_price=meteora_price,
            jupiter_price=jupiter_price,
            spread_pct=spread_pct,
            direction=direction,
            estimated_profit_usd=gross_profit,
            fees_usd=estimated_fees,
            net_profit_usd=net_profit,
            timestamp=time.time()
        )
    
    async def _get_meteora_price(self, pool_address: str) -> Optional[float]:
        """Get current price from Meteora DLMM active bin."""
        # Implementation would use Meteora SDK or RPC parsing
        # Placeholder for actual implementation
        pass
    
    async def _get_jupiter_price(self, base_mint: str, quote_mint: str) -> Optional[float]:
        """Get price from Jupiter API."""
        import aiohttp
        
        url = f"https://price.jup.ag/v6/price?ids={base_mint}&vsToken={quote_mint}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', {}).get(base_mint, {}).get('price')
        return None
    
    async def handle_opportunity(self, opp: ArbOpportunity):
        """Handle detected arbitrage opportunity."""
        import time
        
        print(f"\n{'='*60}")
        print(f"OPPORTUNITY DETECTED: {opp.pair}")
        print(f"  Meteora price: ${opp.meteora_price:.6f}")
        print(f"  Jupiter price: ${opp.jupiter_price:.6f}")
        print(f"  Spread: {opp.spread_pct:.3f}%")
        print(f"  Direction: {opp.direction}")
        print(f"  Est. profit: ${opp.net_profit_usd:.4f}")
        
        if not self.execute_mode:
            print(f"  [WHAT-IF MODE] Would execute trade")
            self._log_opportunity(opp)
            return
        
        # Execute trade
        print(f"  [EXECUTING...]")
        result = await self.execute_trade(opp)
        
        if result.success:
            print(f"  ✓ Trade successful: {result.tx_signature}")
            print(f"    Input: {result.input_amount}")
            print(f"    Output: {result.output_amount}")
            print(f"    Actual spread: {result.actual_spread:.3f}%")
            self.cooldowns[opp.pool_address] = time.time()
        else:
            print(f"  ✗ Trade failed: {result.error}")
        
        self._log_trade(opp, result)
    
    async def execute_trade(self, opp: ArbOpportunity) -> TradeResult:
        """Execute the arbitrage trade."""
        try:
            # Build swap transaction
            swap_tx = await self._build_swap_transaction(opp)
            
            if self.use_jito:
                # Submit via Jito bundle for MEV protection
                result = await self._submit_jito_bundle(swap_tx)
            else:
                # Standard submission
                result = await self._submit_transaction(swap_tx)
            
            return result
            
        except Exception as e:
            return TradeResult(
                success=False,
                tx_signature=None,
                input_amount=0,
                output_amount=0,
                actual_spread=0,
                fees_paid=0,
                error=str(e)
            )
    
    async def _build_swap_transaction(self, opp: ArbOpportunity):
        """Build swap transaction using Jupiter API."""
        import aiohttp
        
        # Use Jupiter swap API for routing
        # This handles finding best route through Meteora or other DEXs
        
        trade_size_lamports = int(self.max_trade_size * 1e6)  # USDC decimals
        
        quote_url = "https://quote-api.jup.ag/v6/quote"
        params = {
            "inputMint": opp.pool_config['quote_mint'],  # USDC
            "outputMint": opp.pool_config['base_mint'],  # Target token
            "amount": trade_size_lamports,
            "slippageBps": 50,  # 0.5% slippage
        }
        
        async with aiohttp.ClientSession() as session:
            # Get quote
            async with session.get(quote_url, params=params) as resp:
                quote = await resp.json()
            
            # Get swap transaction
            swap_url = "https://quote-api.jup.ag/v6/swap"
            swap_payload = {
                "quoteResponse": quote,
                "userPublicKey": str(self.wallet.pubkey()),
                "wrapAndUnwrapSol": True,
                "prioritizationFeeLamports": "auto"
            }
            
            async with session.post(swap_url, json=swap_payload) as resp:
                swap_data = await resp.json()
                return swap_data['swapTransaction']
    
    async def _submit_transaction(self, tx_base64: str) -> TradeResult:
        """Submit transaction via standard RPC."""
        from solders.transaction import VersionedTransaction
        import base64
        
        tx_bytes = base64.b64decode(tx_base64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Sign transaction
        tx.sign([self.wallet])
        
        # Send
        result = await self.rpc.send_transaction(tx)
        
        if result.value:
            return TradeResult(
                success=True,
                tx_signature=str(result.value),
                input_amount=self.max_trade_size,
                output_amount=0,  # Would parse from result
                actual_spread=0,  # Would calculate
                fees_paid=0,
                error=None
            )
        else:
            return TradeResult(
                success=False,
                tx_signature=None,
                input_amount=0,
                output_amount=0,
                actual_spread=0,
                fees_paid=0,
                error="Transaction failed"
            )
    
    async def _submit_jito_bundle(self, tx_base64: str) -> TradeResult:
        """Submit transaction via Jito bundle for MEV protection."""
        import aiohttp
        from solders.transaction import VersionedTransaction
        import base64
        
        tx_bytes = base64.b64decode(tx_base64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Sign transaction
        tx.sign([self.wallet])
        
        # Build Jito bundle
        bundle = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [[base64.b64encode(bytes(tx)).decode()]]
        }
        
        jito_url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(jito_url, json=bundle) as resp:
                result = await resp.json()
                
                if 'result' in result:
                    return TradeResult(
                        success=True,
                        tx_signature=result['result'],
                        input_amount=self.max_trade_size,
                        output_amount=0,
                        actual_spread=0,
                        fees_paid=self.config.get('jito_tip', 0.001),
                        error=None
                    )
                else:
                    return TradeResult(
                        success=False,
                        tx_signature=None,
                        input_amount=0,
                        output_amount=0,
                        actual_spread=0,
                        fees_paid=0,
                        error=result.get('error', 'Jito bundle failed')
                    )
    
    def _log_opportunity(self, opp: ArbOpportunity):
        """Log opportunity to file for analysis."""
        import json
        
        with open('meteora_opportunities.jsonl', 'a') as f:
            f.write(json.dumps({
                'timestamp': opp.timestamp,
                'pool': opp.pool_address,
                'pair': opp.pair,
                'meteora_price': opp.meteora_price,
                'jupiter_price': opp.jupiter_price,
                'spread_pct': opp.spread_pct,
                'direction': opp.direction,
                'estimated_profit': opp.net_profit_usd,
                'executed': False
            }) + '\n')
    
    def _log_trade(self, opp: ArbOpportunity, result: TradeResult):
        """Log executed trade to file."""
        import json
        
        with open('meteora_trades.jsonl', 'a') as f:
            f.write(json.dumps({
                'timestamp': opp.timestamp,
                'pool': opp.pool_address,
                'pair': opp.pair,
                'spread_pct': opp.spread_pct,
                'direction': opp.direction,
                'success': result.success,
                'tx_signature': result.tx_signature,
                'input_amount': result.input_amount,
                'output_amount': result.output_amount,
                'actual_spread': result.actual_spread,
                'fees_paid': result.fees_paid,
                'error': result.error
            }) + '\n')


# Entry point
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Meteora DLMM Arbitrage Bot')
    parser.add_argument('--execute', action='store_true', help='Enable live trading')
    parser.add_argument('--what-if', action='store_true', default=True, help='Log only, no trades')
    parser.add_argument('--min-spread', type=float, default=0.5, help='Min spread %% to trade')
    parser.add_argument('--max-trade-size', type=float, default=50, help='Max trade size USD')
    parser.add_argument('--pools', type=str, help='Comma-separated pool pairs')
    parser.add_argument('--interval', type=int, default=10, help='Seconds between scans')
    parser.add_argument('--use-jito', action='store_true', help='Use Jito bundles')
    parser.add_argument('--jito-tip', type=float, default=0.001, help='Jito tip in SOL')
    parser.add_argument('--cooldown', type=int, default=60, help='Cooldown seconds per pool')
    
    args = parser.parse_args()
    
    config = {
        'execute': args.execute,
        'min_spread': args.min_spread,
        'max_trade_size': args.max_trade_size,
        'interval': args.interval,
        'use_jito': args.use_jito,
        'jito_tip': args.jito_tip,
        'cooldown': args.cooldown,
        'pools': [
            # Default pools - would be loaded from config
            {
                'address': 'POOL_ADDRESS_HERE',
                'pair': 'SOL/USDC',
                'base_mint': 'So11111111111111111111111111111111111111112',
                'quote_mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                'base_fee': 0.25
            }
        ]
    }
    
    bot = MeteoraArbBot(config)
    asyncio.run(bot.run())
```

### Wallet Integration

The bot requires a Solana wallet for execution mode:

```bash
# Set wallet private key (base58 encoded)
export SOLANA_PRIVATE_KEY="your_private_key_here"

# Or use a keyfile
export SOLANA_KEYPAIR_PATH="/path/to/keypair.json"
```

**Security notes:**
- Never commit private keys to git
- Use environment variables or secure vaults
- Consider using a dedicated trading wallet with limited funds

### Integration with Existing Dex Module

The bot leverages existing utilities:

```python
# Use existing Jupiter integration
from dex.jupiterutil import get_quote, execute_swap

# Use existing wallet connection
from dex.local_wallet import load_wallet

# Use existing token cache
from dex.token_cache import get_token_info
```

### Output Files

| File | Purpose |
|------|---------|
| `meteora_opportunities.jsonl` | All detected opportunities (what-if + execute) |
| `meteora_trades.jsonl` | Executed trades with results |
| `meteora_errors.log` | Error log for debugging |

### Sample Output

```
Starting Meteora Arb Bot
  Mode: WHAT-IF
  Min spread: 0.5%
  Max trade: $50
  Jito: disabled

============================================================
OPPORTUNITY DETECTED: SOL/USDC
  Meteora price: $148.234500
  Jupiter price: $149.012300
  Spread: 0.525%
  Direction: buy_meteora
  Est. profit: $0.1312
  [WHAT-IF MODE] Would execute trade

============================================================
OPPORTUNITY DETECTED: BONK/SOL
  Meteora price: $0.000024
  Jupiter price: $0.000024
  Spread: 0.127%
  Direction: buy_meteora
  [BELOW THRESHOLD] Spread 0.127% < min 0.5%
```

### Strategy Comparison Mode (What-If)

In what-if mode, the bot can simultaneously evaluate multiple arbitrage strategies to determine which performs best before committing to implementation.

```bash
# Compare all strategies
python meteora_arb.py --what-if --compare-strategies

# Compare specific strategies
python meteora_arb.py --what-if --compare-strategies bin-mismatch,cross-pool,imbalance
```

#### Strategies Evaluated

| Strategy ID | Description | What It Detects |
|-------------|-------------|-----------------|
| `bin-mismatch` | Bin Price Mismatch | Meteora active bin price vs Jupiter aggregated price |
| `cross-pool` | Cross-Pool Arbitrage | Price differences between Meteora pools for same pair |
| `imbalance` | Pool Imbalance | Pools with skewed token ratios creating discount |
| `dbc` | DBC Launch Token | New token launches with MEV opportunity (high risk) |

#### Comparison Output

```
================================================================================
STRATEGY COMPARISON REPORT (7 days: 2026-04-24 to 2026-05-01)
================================================================================

STRATEGY: bin-mismatch
  Opportunities detected: 142
  Above 0.3% threshold: 23
  Above 0.5% threshold: 8
  Above 1.0% threshold: 2
  Theoretical profit (0.5% threshold): $12.47
  Avg opportunity duration: 45 seconds
  Competition score: HIGH (frequent same-block arbs)

STRATEGY: cross-pool
  Opportunities detected: 31
  Above 0.3% threshold: 12
  Above 0.5% threshold: 5
  Above 1.0% threshold: 1
  Theoretical profit (0.5% threshold): $8.23
  Avg opportunity duration: 2.3 minutes
  Competition score: MEDIUM (less frequent arbs)

STRATEGY: imbalance
  Opportunities detected: 7
  Above 0.3% threshold: 4
  Above 0.5% threshold: 3
  Above 1.0% threshold: 2
  Theoretical profit (0.5% threshold): $18.92
  Avg opportunity duration: 12 minutes
  Competition score: LOW (rare but larger)

STRATEGY: dbc
  Opportunities detected: 89
  Profitable (simulated): 12 (13%)
  Rugged/failed: 77 (87%)
  Theoretical profit: -$234.50 (HIGH LOSS)
  Competition score: EXTREME
  ⚠️ NOT RECOMMENDED

================================================================================
RECOMMENDATION: imbalance
  Reason: Best risk-adjusted returns, lowest competition
  Alternative: bin-mismatch if higher frequency preferred
================================================================================
```

#### Comparison Metrics

Each strategy is evaluated on:

| Metric | Description |
|--------|-------------|
| **Opportunity count** | How often the condition triggers |
| **Threshold distribution** | Spread sizes (0.3%, 0.5%, 1.0%+) |
| **Theoretical profit (no Jito)** | Simulated P&L with swap fees only |
| **Theoretical profit (with Jito)** | Simulated P&L including Jito tip (~0.001 SOL/tx) |
| **Duration** | How long opportunities persist |
| **Competition score** | Based on on-chain arb activity in same pools |
| **Jito necessity** | Whether MEV protection is required for this strategy |
| **Success rate** | For DBC: % that don't rug/fail |

#### Jito Applicability by Strategy

Not all strategies benefit equally from Jito MEV protection:

| Strategy | Jito Needed? | Rationale |
|----------|--------------|-----------|
| `bin-mismatch` | **YES - Critical** | Short duration (45s avg), high competition, frequently front-run |
| `cross-pool` | **YES - Recommended** | Medium duration, moderate competition |
| `imbalance` | **Optional** | Long duration (12+ min), low competition, less time-sensitive |
| `dbc` | **YES - Critical** | Extreme MEV competition, milliseconds matter |

#### Fee Calculation in What-If Mode

The what-if analysis calculates profit under both scenarios:

```python
# Fee components
swap_fee_pct = pool_config.get('base_fee', 0.25)  # Dynamic, can spike
jito_tip_sol = 0.001  # ~$0.15 at $150 SOL
sol_price_usd = await get_sol_price()
jito_tip_usd = jito_tip_sol * sol_price_usd

# Per-opportunity calculation
gross_profit = trade_size * (spread_pct / 100)
swap_fees = trade_size * (swap_fee_pct / 100) * 2  # Round trip

# Two profit scenarios
net_profit_no_jito = gross_profit - swap_fees
net_profit_with_jito = gross_profit - swap_fees - jito_tip_usd

# Strategy-specific recommendation
if strategy in ['bin-mismatch', 'dbc']:
    # Use Jito profit as realistic expectation
    realistic_profit = net_profit_with_jito
elif strategy == 'cross-pool':
    # Average of both (sometimes need Jito, sometimes not)
    realistic_profit = (net_profit_no_jito + net_profit_with_jito) / 2
else:  # imbalance
    # Jito optional, use non-Jito as baseline
    realistic_profit = net_profit_no_jito
```

#### Updated Comparison Output

```
STRATEGY: bin-mismatch
  Opportunities detected: 142
  Above 0.5% threshold: 8
  Theoretical profit (no Jito): $12.47
  Theoretical profit (with Jito): $11.27  ← Use this (Jito critical)
  Jito cost impact: -$1.20 (8 trades × $0.15)
  Jito necessity: CRITICAL
  
STRATEGY: imbalance
  Opportunities detected: 7
  Above 0.5% threshold: 3
  Theoretical profit (no Jito): $18.92  ← Use this (Jito optional)
  Theoretical profit (with Jito): $18.47
  Jito cost impact: -$0.45 (3 trades × $0.15)
  Jito necessity: OPTIONAL
```

This ensures the comparison reflects realistic execution costs per strategy.

#### Strategy Comparison Data Structure

```python
@dataclass
class StrategyComparison:
    strategy_id: str
    period_start: datetime
    period_end: datetime
    opportunities: list[ArbOpportunity]
    
    @property
    def count_above_threshold(self, threshold: float) -> int:
        return len([o for o in self.opportunities if o.spread_pct >= threshold])
    
    @property
    def theoretical_profit(self, threshold: float) -> float:
        viable = [o for o in self.opportunities if o.spread_pct >= threshold]
        return sum(o.net_profit_usd for o in viable)
    
    @property
    def avg_duration_seconds(self) -> float:
        # Calculate from consecutive scans where opportunity persisted
        pass
    
    @property
    def competition_score(self) -> str:
        # Analyze on-chain data for competing arb transactions
        pass

def generate_comparison_report(comparisons: list[StrategyComparison]) -> str:
    """Generate human-readable comparison report."""
    # Rank strategies by risk-adjusted return
    ranked = sorted(comparisons, key=lambda c: c.sharpe_ratio, reverse=True)
    
    report = []
    for comp in ranked:
        report.append(f"""
STRATEGY: {comp.strategy_id}
  Opportunities detected: {len(comp.opportunities)}
  Above 0.3% threshold: {comp.count_above_threshold(0.3)}
  Above 0.5% threshold: {comp.count_above_threshold(0.5)}
  Above 1.0% threshold: {comp.count_above_threshold(1.0)}
  Theoretical profit (0.5% threshold): ${comp.theoretical_profit(0.5):.2f}
  Avg opportunity duration: {comp.avg_duration_seconds:.0f} seconds
  Competition score: {comp.competition_score}
""")
    
    # Add recommendation
    best = ranked[0]
    report.append(f"""
RECOMMENDATION: {best.strategy_id}
  Reason: Best risk-adjusted returns
""")
    
    return '\n'.join(report)
```

#### Output Files (Comparison Mode)

| File | Purpose |
|------|---------|
| `meteora_comparison.json` | Full comparison data for all strategies |
| `meteora_comparison_report.txt` | Human-readable summary |
| `meteora_opportunities_{strategy}.jsonl` | Per-strategy opportunity logs |

This comparison mode allows data-driven strategy selection rather than guessing which approach will work best.

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **MEV/Front-running** | High | Jito bundles, private RPCs |
| **Dynamic fee spikes** | Medium | Model fee behavior, set limits |
| **Low liquidity** | Medium | Filter by TVL, simulate slippage |
| **Smart contract risk** | Low | Meteora is audited, established |
| **Competition** | High | Unique strategies, speed |
| **Rug pulls (DBC)** | High | Avoid new tokens, stick to established |

---

## Conclusion

### Meteora vs JLP for Arbitrage

| Factor | Winner | Why |
|--------|--------|-----|
| **Lower base fees** | Meteora | No mint/redeem fees |
| **More opportunities** | Meteora | Multiple pools, bin mechanics |
| **Less competition** | JLP | DEX arb is saturated |
| **Simpler execution** | JLP | Single mint/sell vs multi-hop |
| **Higher per-trade profit** | JLP | Larger spreads when they occur |
| **Python-friendly** | JLP | TypeScript SDK only for Meteora |

### Recommendation

**For this trading bot:**

1. **Continue JLP arbitrage** as primary strategy (rare but profitable events)
2. **Add Meteora monitoring** to track opportunity frequency
3. **Consider Meteora execution** only if monitoring shows consistent >0.3% spreads
4. **Avoid DBC** unless willing to accept high risk and build anti-MEV infrastructure

### Next Steps

- [ ] Build Meteora pool scanner (list all DLMM pools)
- [ ] Track price deviations vs Jupiter over 1 week
- [ ] Analyze fee dynamics (when do variable fees spike?)
- [ ] Decide if execution is worth pursuing based on data

---

## Open Questions

> **Note:** The suggested implementation in this document assumes the recommendations below are accepted. If different options are chosen, the implementation will need to be adjusted accordingly.

### Applicability Legend

| Tag | Meaning |
|-----|---------|
| 🔍 **MONITORING** | Applies to what-if/monitoring mode |
| ⚡ **EXECUTION** | Applies to live trading mode |
| 📊 **ALL STRATEGIES** | Applies regardless of strategy choice |
| 🎯 **STRATEGY-SPECIFIC** | Answer depends on which strategy is chosen |

---

### 1. Which Arbitrage Strategy to Pursue?

📊 **Applies to:** ALL MODES — This is the foundational decision that affects all subsequent questions.

| Option | Pros | Cons |
|--------|------|------|
| **A. Bin Price Mismatch** | Most frequent opportunities | High MEV competition, speed critical |
| **B. Cross-Pool Arbitrage** | Less competitive, speed tolerant | More complex routing |
| **C. Pool Imbalance** | Clear profit when found, speed tolerant | Rare occurrences |
| **D. DBC Launch Token** | Highest potential profit | Highest risk (rugs, MEV), extreme speed required |

**Recommendation:** Start with **B (Cross-Pool)** and **C (Pool Imbalance)** as MVP strategies. These are speed-tolerant, allowing meaningful paper trading and gradual execution testing. Use what-if mode with `--compare-strategies` to collect data on **A (Bin Price Mismatch)** for future consideration.

**Downstream impact:** This choice affects questions 3, 4, 5, and 6. Strategy selection determines SDK requirements, threshold settings, and execution approach.

---

### 2. SDK Integration Approach?

📊 **Applies to:** ALL MODES, ALL STRATEGIES

| Option | Description | Trade-off |
|--------|-------------|-----------|
| **A. TypeScript subprocess** | Call `@meteora-ag/dlmm` from Python | Cross-language complexity, full SDK access |
| **B. Direct RPC parsing** | Parse DLMM accounts via Solana RPC | Native Python, requires reverse-engineering account layout |
| **C. Build Python SDK wrapper** | Create Python bindings for Meteora | High upfront effort, fully reusable, native integration |

#### Why Jupiter-Only Is Not An Option

Jupiter routing was considered but is **insufficient for all four strategies**:

**What Jupiter API provides:**
- Best aggregated quote across all DEXes
- `routePlan` with `ammKey` showing which pool was used
- `mostReliableAmmsQuoteReport` with alternative AMM quotes
- Price impact percentage

**What Jupiter API does NOT provide (required for arbitrage):**
- Meteora active bin ID or bin-specific price (needed for bin-mismatch)
- Individual pool prices when multiple Meteora pools exist (needed for cross-pool)
- Pool reserve balances (needed for imbalance)
- Dynamic fee rates (only aggregated into quote)
- Enumeration of all Meteora pools for a token pair
- Real-time new pool notifications (needed for DBC)

Jupiter can only answer "what is the best aggregated price right now" but cannot compare Meteora-specific pricing against other sources—which is the core of arbitrage detection.

#### SDK Requirement by Strategy

| Strategy | Required Data | Minimum Requirement |
|----------|--------------|---------------------|
| `bin-mismatch` | Active bin price vs external price | Any of A, B, or C |
| `cross-pool` | Prices from multiple pools for same pair | Any of A, B, or C |
| `imbalance` | Token reserves in pools | Any of A, B, or C |
| `dbc` | New pool detection, fast pricing | A or C + Meteora API |

#### Option Comparison

##### Option A: TypeScript Subprocess

| Aspect | Assessment |
|--------|------------|
| **Pros** | Full access to official `@meteora-ag/dlmm` SDK; always up-to-date with Meteora changes; transaction building included |
| **Cons** | Subprocess overhead (~100-500ms per call); Node.js dependency; cross-language error handling; harder to debug |
| **Best for** | Rapid prototyping; when Meteora updates frequently; when transaction building needed |
| **Latency** | Higher (subprocess spawn + JS runtime) |

```python
# Python calls TypeScript via subprocess
import subprocess
import json

def get_meteora_active_bin(pool_address: str) -> dict:
    result = subprocess.run(
        ['npx', 'ts-node', 'meteora_helper.ts', 'getActiveBin', pool_address],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)
```

```typescript
// meteora_helper.ts
import DLMM from '@meteora-ag/dlmm';
const pool = await DLMM.create(connection, new PublicKey(poolAddress));
const activeBin = await pool.getActiveBin();
console.log(JSON.stringify({ binId: activeBin.binId, price: activeBin.pricePerToken }));
```

##### Option B: Direct RPC Parsing

| Aspect | Assessment |
|--------|------------|
| **Pros** | Native Python; no external dependencies; lowest latency; full control |
| **Cons** | Must reverse-engineer Meteora account layouts; breaks if Meteora changes on-chain structure; no official documentation for account parsing |
| **Best for** | Speed-critical strategies; long-term production use with maintenance commitment |
| **Latency** | Lowest (direct RPC calls) |

```python
# Parse DLMM account data directly via Solana RPC
from solana.rpc.api import Client
import struct
import base64

def get_active_bin_via_rpc(pool_address: str) -> dict:
    client = Client("https://api.mainnet-beta.solana.com")
    account_info = client.get_account_info(pool_address)
    # Parse DLMM account structure (requires understanding Meteora's account layout)
    # Active bin ID is at byte offset 8, bin step at offset 12, etc.
    data = base64.b64decode(account_info['result']['value']['data'][0])
    active_bin_id = struct.unpack('<i', data[8:12])[0]
    bin_step = struct.unpack('<H', data[12:14])[0]
    # Calculate price from bin ID and step
    price = (1 + bin_step / 10000) ** active_bin_id
    return {'binId': active_bin_id, 'price': price}
```

##### Option C: Python SDK Wrapper

| Aspect | Assessment |
|--------|------------|
| **Pros** | Native Python integration; reusable across projects; can optimize for specific use cases; type safety with dataclasses |
| **Cons** | High upfront development (2-4 weeks); must track Meteora SDK changes; testing burden |
| **Best for** | Long-term investment; multiple Meteora-based strategies; team scaling |
| **Latency** | Low (direct RPC, optimized) |

**What a Python SDK wrapper would include:**

```python
# meteora_sdk.py - Python wrapper for Meteora DLMM
from dataclasses import dataclass
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

@dataclass
class BinLiquidity:
    bin_id: int
    price_per_token: float
    x_amount: int
    y_amount: int

@dataclass
class DLMMPool:
    address: Pubkey
    token_x_mint: Pubkey
    token_y_mint: Pubkey
    bin_step: int
    active_bin_id: int
    base_fee_bps: int
    
    @classmethod
    async def create(cls, client: AsyncClient, address: Pubkey) -> 'DLMMPool':
        """Load pool state from on-chain account."""
        account = await client.get_account_info(address)
        # Parse account data into DLMMPool fields
        return cls._parse_account(address, account.value.data)
    
    async def get_active_bin(self) -> BinLiquidity:
        """Get current active bin with price and liquidity."""
        pass
    
    async def get_bins_around_active(self, left: int, right: int) -> list[BinLiquidity]:
        """Get bins surrounding the active bin."""
        pass
    
    def get_dynamic_fee(self) -> float:
        """Calculate current dynamic fee based on volatility."""
        pass
    
    def swap_quote(self, amount_in: int, swap_for_y: bool) -> tuple[int, float]:
        """Calculate swap output and fee locally."""
        pass

async def get_all_pools_for_pair(client: AsyncClient, token_a: Pubkey, token_b: Pubkey) -> list[DLMMPool]:
    """Find all DLMM pools for a token pair (needed for cross-pool strategy)."""
    pass
```

**Does Python SDK wrapper address all requirements?**

| Requirement | Addressed? | Notes |
|-------------|------------|-------|
| Active bin price | ✅ Yes | Parse from account data |
| Bin liquidity distribution | ✅ Yes | Parse bin arrays |
| Dynamic fee calculation | ✅ Yes | Replicate fee formula |
| Pool enumeration | ✅ Yes | Query by program + filters |
| Swap quote (local) | ✅ Yes | Replicate swap math |
| Transaction building | ⚠️ Partial | Can build instructions, but complex |
| New pool detection | ✅ Yes | WebSocket subscription to program |

**Transaction building caveat:** Building swap transactions requires constructing Solana instructions with correct account ordering. This is the most complex part—consider using TypeScript subprocess just for transaction building while using Python for monitoring/analysis.

#### Recommendation

| Strategy | Recommended Approach | Rationale |
|----------|---------------------|-----------|
| `cross-pool` | **B or C** | Speed-tolerant; RPC parsing or wrapper viable |
| `imbalance` | **B or C** | Speed-tolerant; RPC parsing or wrapper viable |
| `bin-mismatch` | **A or C** | Speed-critical; need optimized path |
| `dbc` | **A** | Extreme speed; official SDK likely fastest |

**Default recommendation for MVP:** Option **B (Direct RPC parsing)** for the speed-tolerant strategies (cross-pool, imbalance). This keeps everything in Python, avoids subprocess overhead, and is sufficient for strategies where 100-200ms latency doesn't matter.

Consider **Option C (Python SDK wrapper)** if planning long-term investment in multiple Meteora strategies.

**Mode-specific notes:**
- 🔍 **Monitoring/What-If:** Options B or C are sufficient
- ⚡ **Execution:** May need Option A for transaction building, or hybrid approach

---

### 3. Minimum Spread Threshold?

🎯 **Applies to:** ALL MODES — But optimal threshold varies by strategy

| Option | Threshold | Rationale |
|--------|-----------|-----------|
| **A. Conservative** | >0.5% | Account for dynamic fee spikes |
| **B. Moderate** | >0.3% | Balance frequency vs profitability |
| **C. Aggressive** | >0.1% | More trades, lower profit per trade |
| **D. Dynamic** | Variable based on current pool fees | Adapts to conditions, more complex |

**Recommendation by strategy:**

| Strategy | Recommended Threshold | Rationale |
|----------|----------------------|-----------|
| `bin-mismatch` | **A (>0.5%)** | High competition erodes thin margins |
| `cross-pool` | **B (>0.3%)** | Less competition allows tighter spreads |
| `imbalance` | **B (>0.3%)** | Rare but larger opportunities |
| `dbc` | **C (>0.1%)** | Speed matters more than spread size |

**Default recommendation:** Option **A (Conservative, >0.5%)** to start.

---

### 4. MEV Protection Strategy?

🎯 **Applies to:** ⚡ EXECUTION MODE ONLY — Not relevant for monitoring

| Option | Description | Cost |
|--------|-------------|------|
| **A. Jito bundles** | Submit via Jito for MEV protection | ~0.001 SOL tip per tx |
| **B. Private RPC** | Use private/hidden RPC endpoints | Monthly subscription |
| **C. Speed optimization** | Fastest possible execution | Dev time, no guarantee |
| **D. Accept front-running** | Price in MEV losses | Lower effective profit |

**Recommendation by strategy:**

| Strategy | Recommended MEV Protection | Rationale |
|----------|---------------------------|-----------|
| `bin-mismatch` | **A (Jito) — Critical** | 45s avg duration, high competition |
| `cross-pool` | **D (Accept)** | Speed-tolerant; add Jito later if MEV losses observed |
| `imbalance` | **D (Accept)** | 12+ min duration; Jito unlikely to help |
| `dbc` | **A (Jito) — Critical** | Milliseconds matter |

**For MVP (cross-pool + imbalance):** Option **D (Accept front-running)** is recommended. These strategies have longer opportunity windows where MEV competition is lower. Monitor actual execution results—if front-running losses exceed ~$0.15/trade (Jito tip cost), consider adding Jito integration as a future enhancement.

**For monitoring/what-if mode:** Option **D** — no execution means no MEV risk. Jito fees are still calculated in what-if output for accurate profit estimation.

---

### 5. Pool Selection Criteria?

🎯 **Applies to:** ALL MODES — But scope varies by strategy

| Option | Criteria | Trade-off |
|--------|----------|-----------|
| **A. TVL-based** | Only pools with >$100K TVL | Fewer pools, better liquidity |
| **B. Volume-based** | Only pools with >$50K daily volume | Active pools, more competition |
| **C. Token whitelist** | Only specific tokens (SOL, USDC, etc.) | Predictable, may miss opportunities |
| **D. All pools** | Monitor everything | High API load, noisy data |

**Recommendation by strategy:**

| Strategy | Recommended Pool Selection | Rationale |
|----------|---------------------------|-----------|
| `bin-mismatch` | **C (Whitelist)** | Focus on liquid pairs where spreads persist |
| `cross-pool` | **A (TVL-based)** | Need multiple pools for same pair |
| `imbalance` | **A (TVL-based)** | Imbalances occur in larger pools |
| `dbc` | **D (All pools)** | New launches = new pools |

**Default recommendation:** Option **C (Token whitelist)** with major pairs.

---

### 6. Execution vs Monitoring Priority?

📊 **Applies to:** INITIAL SETUP — Determines which mode to start in and scope of MVP

| Option | Approach | When to choose |
|--------|----------|----------------|
| **A. Monitoring only** | 2-4 weeks of data collection, no execution code | Validate opportunity exists before any execution investment |
| **B. Paper trading** | Simulate trades in real-time without execution | Test strategy logic without risk |
| **C. Small live trades** | Execute with minimal capital ($10-50) | Learn real execution dynamics |
| **D. Full deployment** | Production execution immediately | High confidence in strategy |
| **E. MVP with speed-tolerant strategies** | Full implementation (monitoring + paper + execution) for cross-pool and imbalance only | Practical end-to-end validation; paper trading is meaningful for these strategies |

#### What Each Mode Actually Tests

| Mode | Tests Opportunity Detection? | Tests Profitability Math? | Tests Execution Speed? | Tests MEV Competition? |
|------|------------------------------|--------------------------|------------------------|------------------------|
| **A. Monitoring** | ✅ Yes | ✅ Theoretical | ❌ No | ❌ No |
| **B. Paper trading** | ✅ Yes | ✅ With simulated slippage | ⚠️ Partial (tx build time) | ❌ No |
| **C. Small live trades** | ✅ Yes | ✅ Actual | ✅ Yes | ✅ Yes |
| **D. Full deployment** | ✅ Yes | ✅ Actual | ✅ Yes | ✅ Yes |
| **E. MVP (speed-tolerant)** | ✅ Yes | ✅ Full validation path | ✅ Yes (for these strategies) | ⚠️ Less critical |

#### Paper Trading Limitations

**What paper trading CAN do:**
- Call Jupiter `POST /swap` to build a transaction (but not submit it)
- Call Solana `simulateTransaction` to verify the tx would succeed
- Measure transaction build time
- Get slippage estimates based on current liquidity

**What paper trading CANNOT do:**
- Compete for block inclusion against other bots
- Test actual network latency to validators
- Verify you'd beat MEV bots to the opportunity
- Capture state changes between quote and real execution

**⚠️ Critical insight:** For speed-sensitive strategies (`bin-mismatch`, `dbc`), paper trading answers *"would this trade be profitable if I were the only bot?"* but NOT *"can I actually capture this profit in competition?"*

However, for **speed-tolerant strategies** (`cross-pool`, `imbalance`), paper trading IS meaningful because:
- Opportunities persist for minutes, not seconds
- MEV competition is lower
- Execution timing is not the primary success factor
- Slippage simulation reflects realistic outcomes

#### Option E: MVP with Speed-Tolerant Strategies (Recommended)

Implement full monitoring → paper trading → execution pipeline for **cross-pool** and **imbalance** strategies only:

| Phase | Deliverable | Duration |
|-------|-------------|----------|
| **Phase 1: Monitoring** | Detect opportunities, log theoretical profits | 1-2 weeks |
| **Phase 2: Paper Trading** | Build transactions, simulate execution, validate routing | 1 week |
| **Phase 3: Beta Execution** | Small live trades ($10-50), measure actual vs theoretical | 1-2 weeks |
| **Phase 4: Production** | Scale up if beta validates profitability | Ongoing |

**Why this works for cross-pool and imbalance:**

| Factor | Cross-Pool | Imbalance | Bin-Mismatch | DBC |
|--------|------------|-----------|--------------|-----|
| Opportunity duration | 2-5 min | 10-30 min | 30-60 sec | milliseconds |
| MEV competition | Medium | Low | High | Extreme |
| Paper trading useful? | ✅ Yes | ✅ Yes | ❌ No | ❌ No |
| Spread size | 0.3-1% | 0.5-2% | 0.1-0.5% | Variable |
| Execution timing critical? | No | No | Yes | Extreme |

**MVP scope for Option E:**

```
MVP Implementation Scope
========================

Included:
- TypeScript subprocess OR RPC parsing for Meteora data
- Cross-pool arbitrage detection and execution
- Pool imbalance detection and execution  
- What-if mode with --compare-strategies
- Paper trading with transaction simulation
- Small-capital live execution
- Logging: opportunities, simulations, trades

Excluded from MVP:
- Bin-mismatch strategy (requires speed optimization first)
- DBC strategy (too high risk, extreme MEV)
- Jito bundle integration (not critical for speed-tolerant strategies)
- Python SDK wrapper (use simpler approach for MVP)
```

#### Strategy-Specific Recommendations

| Strategy | Speed Critical? | Include in MVP? | Recommended Path |
|----------|----------------|-----------------|------------------|
| `cross-pool` | **NO** | ✅ Yes | A → B → C (full pipeline) |
| `imbalance` | **NO** | ✅ Yes | A → B → C (full pipeline) |
| `bin-mismatch` | **YES** | ❌ No (monitoring only) | Collect data in what-if mode |
| `dbc` | **EXTREME** | ❌ No | Too risky, defer |

**Recommendation:** Option **E (MVP with speed-tolerant strategies)**

This approach:
1. Delivers end-to-end working system for strategies where paper trading is meaningful
2. Validates the full pipeline with real (small) capital
3. Collects data on bin-mismatch via what-if mode for future decision
4. Avoids investing in execution code for strategies where speed determines success

---

## Resources

- **Meteora Docs**: https://docs.meteora.ag/
- **DLMM TypeScript SDK**: https://www.npmjs.com/package/@meteora-ag/dlmm
- **GitHub**: https://github.com/MeteoraAg
- **Discord**: https://discord.gg/meteora
