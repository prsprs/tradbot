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

## Resources

- **Meteora Docs**: https://docs.meteora.ag/
- **DLMM TypeScript SDK**: https://www.npmjs.com/package/@meteora-ag/dlmm
- **GitHub**: https://github.com/MeteoraAg
- **Discord**: https://discord.gg/meteora
