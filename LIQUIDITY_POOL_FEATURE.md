# Liquidity Pool Arbitrage Feature

## Overview

This document explores the design of a bot that profits from arbitrage opportunities in liquidity pools, specifically targeting the premium/discount spread between a pool token's **market price** and its **virtual (fair) price**. The primary use case is JLP (Jupiter Liquidity Provider) token arbitrage on Solana, though the strategy could generalize to other LP tokens.

**Relationship to Existing Bot:**
- This would likely be a **new Python program** (`lp_arbitrage.py` or similar)
- Could share utilities with the existing trading bot:
  - `dex/jupiterutil.py` - Jupiter API integration
  - `dex/walletconnect.py` - Wallet connection for execution
  - `config.py` - Configuration patterns
  - `claudeutil.py`, `openaiutil.py` - LLM utilities (if using AI for signal analysis)

---

## Alternative Platforms: HyperLiquid and Drift

While Jupiter JLP is the primary focus, two other platforms offer similar LP token arbitrage opportunities with potentially more developer-friendly APIs.

### Platform Comparison

| Feature | Jupiter (JLP) | HyperLiquid (HLP) | Drift (IF Staking) |
|---------|---------------|-------------------|-------------------|
| **Chain** | Solana | HyperLiquid L1 | Solana |
| **LP Token** | JLP | HLP (vault shares) | IF Vault shares |
| **Underlying** | SOL, BTC, ETH, USDC, USDT | USDC only | USDC, SOL |
| **Yield Source** | Perp trading fees (75%) | Market making P&L + fees | Protocol fees (hourly) |
| **Lock-up** | None | 4 days | 13 days to unstake |
| **API Type** | On-chain (Solana RPC) | REST API | Python SDK (`driftpy`) |
| **API Friendliness** | ⭐⭐ (requires IDL parsing) | ⭐⭐⭐⭐ (simple REST) | ⭐⭐⭐⭐⭐ (native Python) |

---

### HyperLiquid (HLP)

**What is HLP?**
The Hyperliquidity Provider (HLP) is a protocol vault that provides liquidity through market-making strategies, performs liquidations, and accrues trading fees. It's fully community-owned.

**API Advantages:**
- Simple REST API at `https://api.hyperliquid.xyz/info`
- Direct endpoints for vault details and user positions
- No complex IDL parsing required

**Key Endpoints:**
```
POST https://api.hyperliquid.xyz/info
{
  "type": "vaultDetails",
  "vaultAddress": "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"  # HLP vault
}

POST https://api.hyperliquid.xyz/info
{
  "type": "userVaultEquities",
  "user": "0x..."
}
```

**Arbitrage Mechanics:**
- HLP share price reflects NAV of vault (similar to virtual price)
- Share price fluctuates based on market-making P&L
- Premium/discount opportunities when vault has large winning/losing streaks
- **Key difference**: HLP is USDC-only, so no underlying asset exposure risk (unlike JLP's SOL/BTC/ETH exposure)

**Considerations:**
- 4-day withdrawal lock-up limits quick arbitrage exits
- HyperLiquid is its own L1, not Solana (different wallet/bridge requirements)
- Less secondary market liquidity than JLP

---

### Drift Protocol (Insurance Fund Staking)

**What is Drift IF Staking?**
Users stake into Insurance Fund Vaults (USDC or SOL) to collateralize the protocol. In return, stakers receive hourly revenue from borrow fees, exchange fees, and liquidation fees.

**API Advantages:**
- **Native Python SDK**: `pip install driftpy`
- Well-documented with examples for LP and insurance fund staking
- Same chain as existing trading bot (Solana)

**Python SDK Example:**
```python
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig

# examples/ folder includes insurance fund staking examples
drift_client = DriftClient(
    connection,
    wallet,
    "mainnet",
    account_subscription=AccountSubscriptionConfig("cached"),
)
await drift_client.subscribe()
```

**Arbitrage Mechanics:**
- IF shares accumulate value hourly from revenue pool
- Share value = Total Staked Amount / Total Insurance Fund
- **Less volatile** than JLP (no trader P&L exposure, just fees)
- Premium/discount when users rush to stake/unstake

**Considerations:**
- 13-day cooldown to unstake (longest of the three)
- Cannot unstake if spot market utilization > 80%
- Lower yield volatility = smaller arbitrage spreads
- More of a "yield farming" play than active arbitrage

---

### Risk-Adjusted Returns: Sharpe Ratio Comparison

The Sharpe ratio—a measure of risk-adjusted return—varies significantly between these protocols due to how much price volatility (the "risk") they pass on to the liquidity provider.

#### Historical Performance (Estimated 2024–2025)

| Metric | HyperLiquid (HLP) | Jupiter (JLP) | Drift (DLP) |
|--------|-------------------|---------------|-------------|
| **Estimated Sharpe Ratio** | ~4.06 | ~2.93 | ~1.5–2.5 (variable) |
| **Annualized Volatility** | ~17.89% | Higher (market-linked) | Moderate to High |
| **Primary Risk Source** | Trader PnL & Market Making | Asset Price Action (SOL/BTC) | Long/Short Imbalance |
| **Yield Stability** | Very High (USDC base) | Variable (price dependent) | Moderate (hedge dependent) |

#### Platform Risk Profiles

**1. HyperLiquid (HLP): The "Stable" Choice**
- **Highest Sharpe ratio** because value is tied to USDC, not volatile tokens
- Share price doesn't drop just because the market crashes
- **Best for bots**: Can focus purely on trading fee spikes without worrying about a 20% SOL drawdown wiping out gains
- Tradeoff: 4-day lock-up limits quick exits

**2. Jupiter (JLP): High Return, High Beta**
- Massive total returns possible (e.g., 116% in early 2024)
- **Lower Sharpe** due to heavy price volatility from ~45% SOL exposure
- **Bot challenge**: Must account for "Delta risk" — even capturing a 0.5% premium can lose money if SOL drops 5% during the trade
- Requires simultaneous SOL shorting to hedge, adding complexity

**3. Drift (DLP): The Balanced Hybrid**
- Functions similarly to JLP but with more granular control
- **Key advantage**: Offers **Hedged JLP (hJLP) vaults** that use Drift's perps to short the underlying SOL/BTC/ETH automatically
- Standard DLP: Stable during sideways markets, vulnerable to directional trends
- **Hedged Vaults**: Delta-neutral position pushes Sharpe higher by eliminating market-direction risk, leaving only fee income and premium/discount arbitrage

---

### Strategic Takeaway for Bot Development

**If your bot's goal is Market-Neutral Arbitrage** (profiting only from price discrepancies):

| Strategy | Best Platform | Why |
|----------|---------------|-----|
| **Simplest to manage** | HyperLiquid (HLP) | Natively USDC-based, no delta hedging needed |
| **Automated hedging** | Drift Hedged JLP (hJLP) | Protocol handles the short positions for you |
| **Largest opportunities** | Jupiter (JLP) | Biggest premiums, but requires complex bot logic for volatility management |

---

### Recommendation by Use Case

| Goal | Best Platform | Rationale |
|------|---------------|-----------|
| **Market-neutral arbitrage** | HyperLiquid | USDC-based, highest Sharpe (~4.06), no delta risk |
| **Automated delta hedging** | Drift hJLP | Protocol manages hedges, simpler bot logic |
| **Quick MVP** | HyperLiquid | Simple REST API + no hedging complexity |
| **Python-native** | Drift | Official `driftpy` SDK with examples |
| **Largest spreads** | Jupiter JLP | Most volatile, AUM caps create premiums |
| **No lock-up** | Jupiter JLP | Instant deposits/withdrawals |
| **Solana ecosystem** | Jupiter or Drift | Reuse existing wallet/RPC infrastructure |

---

### Multi-Platform Strategy (Future)

A more sophisticated bot could monitor all three platforms simultaneously:
1. **Signal aggregation**: Track premium/discount across JLP, HLP, and Drift IF
2. **Capital rotation**: Move capital to platform with best spread
3. **Hedging**: Use one platform to hedge exposure from another
4. **Arbitrage between platforms**: If JLP premium > HLP premium, consider cross-platform plays

---

## ⚠️ Security & Safety Considerations

### The April 2026 Drift Exploit

**On April 1, 2026, Drift Protocol suffered a $285 million exploit**—the largest DeFi hack of 2026 and the second-largest in Solana history. This incident is highly relevant to anyone considering LP arbitrage on these platforms.

#### What Happened

| Phase | Details |
|-------|---------|
| **Social Engineering** | Attackers (linked to DPRK/North Korea) spent 6+ months building relationships with Drift team members, posing as a quantitative trading firm |
| **Trust Building** | Deposited $1M+ into Drift vaults, attended conferences, held strategy discussions |
| **Admin Compromise** | Used Solana's "durable nonces" feature to trick Security Council members into pre-signing transactions that transferred admin control |
| **Fake Collateral** | Created worthless "CVT" token, manipulated its oracle price to ~$1 |
| **Drain** | Deposited 500M CVT as collateral, withdrew $285M in real assets (USDC, SOL, ETH) |

#### Key Lesson
> The attack exploited **human trust and operational security**, not smart contract vulnerabilities. Standard security measures didn't flag the transactions because they used valid admin signatures.

---

### Platform Security Comparison

| Security Aspect | Jupiter (JLP) | HyperLiquid (HLP) | Drift (IF Staking) |
|-----------------|---------------|-------------------|-------------------|
| **Recent Exploits** | None major | None major | $285M (April 2026) |
| **Smart Contract Audits** | Multiple audits | Zellic (bridge) | Ottersec, Asymmetric (post-exploit) |
| **Admin Key Risk** | Multisig | Validator-controlled | Redesigned multisig (post-exploit) |
| **Oracle Risk** | Pyth + internal | Validator oracles | Pyth |
| **Insurance Fund** | None (JLP is the backstop) | HLP absorbs losses | Separate IF (unaffected by exploit) |
| **Chain Maturity** | Solana (established) | HyperLiquid L1 (newer) | Solana (established) |

---

### Drift's Post-Exploit Security Measures

Following the April 2026 exploit, Drift has implemented significant security improvements:

| Measure | Description |
|---------|-------------|
| **Dual Independent Audits** | Full codebase audit by Ottersec; operational security by Asymmetric |
| **New Multisig Structure** | Community-governed, with participation from Solana infrastructure leaders |
| **Dedicated Signing Devices** | All signers must use isolated hardware |
| **Transaction Verification** | Content independently verified outside primary signing interface |
| **Timelocks** | Enforced delays on all critical admin actions |
| **Real-time Alerts** | Anomalous proposals flagged before execution |
| **Durable Nonces Disabled** | The specific mechanism exploited is now disabled |
| **Need-to-Know Signer IDs** | Signer identities kept confidential |

**Recovery Status:**
- Insurance Fund was **unaffected** and remains intact
- Tether contributing up to $127.5M + $20M from other partners
- Recovery token issued to impacted users
- Protocol relaunched with USDT as settlement layer

---

### HyperLiquid Risk Factors

From HyperLiquid's official documentation:

| Risk | Description |
|------|-------------|
| **L1 Risk** | HyperLiquid runs on its own L1, less battle-tested than Ethereum/Solana |
| **Smart Contract Risk** | Bridge contract audited by Zellic, but other components less scrutinized |
| **Oracle Manipulation** | Relies on validator-maintained oracles; mitigated by open interest caps |
| **Liquidity Risk** | Newer protocol, potentially less liquidity in stress scenarios |

**Mitigations:**
- Open interest caps prevent large manipulation attacks
- Orders cannot rest >1% from oracle price
- Bug bounty program active

---

### Jupiter JLP Risk Factors

| Risk | Description |
|------|-------------|
| **No Separate Insurance** | JLP itself is the counterparty; if traders win big, JLP loses |
| **Underlying Asset Exposure** | ~45% SOL, ~10% ETH/BTC exposure means market crashes hit JLP value |
| **AUM Cap Dynamics** | While caps create arbitrage opportunity, they also create scarcity risk |
| **Oracle Dependency** | Relies on Pyth and internal oracles for pricing |

**Mitigations:**
- Proven track record (>1 year operational, $700M+ market cap)
- Part of Jupiter ecosystem (largest Solana DEX)
- Multiple audits completed

---

### Safety Recommendations for Bot Implementation

| Recommendation | Rationale |
|----------------|-----------|
| **Start with small amounts** | Validate strategy before scaling capital |
| **Diversify across platforms** | Don't concentrate all funds in one protocol |
| **Monitor protocol news** | Social engineering attacks take months; stay informed |
| **Set hard position limits** | Cap exposure to any single platform |
| **Implement circuit breakers** | Auto-halt on unusual price movements or API anomalies |
| **Use hardware wallets** | Never store signing keys in hot wallets or bots |
| **Avoid newly launched features** | Wait for battle-testing before using new protocol features |
| **Track TVL changes** | Sudden TVL drops may indicate problems |

---

### Insurance & Recovery Expectations

| Platform | If Exploit Occurs |
|----------|-------------------|
| **Jupiter JLP** | No formal insurance; losses absorbed by JLP holders |
| **HyperLiquid HLP** | Community-owned vault; losses socialized across depositors |
| **Drift IF** | Separate insurance fund; post-exploit showed Tether/partner recovery support |

**Bottom Line:** No DeFi protocol is risk-free. The Drift exploit demonstrates that even well-established protocols with strong teams can be compromised through sophisticated social engineering. Position sizing and diversification are critical.

---

## The Core Strategy: True Arbitrage

### Two Prices, One Opportunity

| Price Type | Definition | Behavior |
|------------|------------|----------|
| **NAV Price** | Total value of underlying assets (SOL, BTC, ETH, USDC, USDT) ÷ total LP token supply | Accessible via mint/redeem at pool |
| **Market Price** | Price on DEXs (e.g., Jupiter Swap) | Fluctuates based on supply/demand |

### True Arbitrage vs Spread Trading

**Previous approach (DEPRECATED):** Buy when discounted, sell when premium appears. This was NOT true arbitrage - it was directional betting on mean reversion with full capital at risk.

**Current approach (TRUE ARBITRAGE):** Capture the spread IMMEDIATELY through two transactions:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TRUE ARBITRAGE STRATEGIES                         │
└─────────────────────────────────────────────────────────────────────────┘

PREMIUM ARBITRAGE (Market > NAV):
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 1: MINT JLP at NAV price (addLiquidity2 instruction)              │
│          └── Deposit USDC → Receive JLP at NAV price                    │
│                                                                          │
│  Step 2: SELL JLP at market price (Jupiter swap)                        │
│          └── Swap JLP → USDC at premium market price                    │
│                                                                          │
│  Profit = (Market Price - NAV Price) × Amount - Fees                    │
└─────────────────────────────────────────────────────────────────────────┘

DISCOUNT ARBITRAGE (Market < NAV):
┌─────────────────────────────────────────────────────────────────────────┐
│  Step 1: BUY JLP at market price (Jupiter swap)                         │
│          └── Swap USDC → JLP at discounted market price                 │
│                                                                          │
│  Step 2: REDEEM JLP at NAV price (removeLiquidity2 instruction)         │
│          └── Burn JLP → Receive USDC at full NAV price                  │
│                                                                          │
│  Profit = (NAV Price - Market Price) × Amount - Fees                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why True Arbitrage is Superior

| Aspect | Spread Trading (Old) | True Arbitrage (New) |
|--------|---------------------|---------------------|
| **Profit capture** | Uncertain (betting on reversion) | Immediate (locked at execution) |
| **Capital at risk** | Full position value | Only during brief execution window |
| **Directional exposure** | Yes (holding JLP) | Minimal (two-leg execution) |
| **Time dependency** | Must wait for spread to close | Instant profit capture |

### Key Triggers

| Event | Expected Effect | Arbitrage Type |
|-------|-----------------|----------------|
| **AUM cap hit** | Cannot mint → premium spikes | PREMIUM ARB (if can mint) |
| **High volatility** | Demand spike → premium | PREMIUM ARB |
| **Market crash** | Panic selling → discount | DISCOUNT ARB |
| **Low APY period** | Low demand → discount | DISCOUNT ARB |

---

## Implementation Options

### Option A: Pure Price Spread Monitoring

**Description:** Monitor virtual vs market price continuously, execute when spread exceeds threshold.

**Pros:**
- Simple logic
- Fast execution
- No external dependencies beyond price feeds

**Cons:**
- May miss context (why is premium high?)
- No predictive capability

**Data Required:**
- Virtual price: JLP pool contract or Jupiter API
- Market price: Jupiter Swap quote API
- Spread threshold: Configurable (e.g., buy at -1%, sell at +8%)

---

### Option B: APY-Correlated Trading

**Description:** Use APY spikes as a leading indicator for premium opportunities.

**Pros:**
- APY spikes often precede premium spikes
- More predictive than pure spread monitoring

**Cons:**
- APY data may lag
- Correlation is not causation

**Signal Logic:**
```
IF apy > APY_HIGH_THRESHOLD (e.g., 30% annualized):
    → Prepare to SELL (premium likely peaking)
    
IF apy < APY_LOW_THRESHOLD (e.g., 10% annualized):
    → Consider BUY (stable period, likely discount/parity)
```

---

### Option C: AUM Cap Watcher

**Description:** Monitor JLP pool's AUM relative to its cap. When cap is hit, anticipate premium spike.

**Pros:**
- Direct causation: cap hit → no minting → scarcity → premium
- Strongest predictive signal

**Cons:**
- Requires real-time AUM monitoring
- Cap changes may not be announced

**Data Required:**
- Current AUM: JLP pool state
- AUM cap: May require scraping or API (if available)
- Historical cap events: For backtesting

---

### Option D: Hybrid Multi-Signal Approach

**Description:** Combine all signals with weighted scoring.

```
┌─────────────────────────────────────────────────────────────────┐
│                    MULTI-SIGNAL SCORING                          │
├─────────────────────────────────────────────────────────────────┤
│  Signal              │ Weight │ Buy Score │ Sell Score          │
├──────────────────────┼────────┼───────────┼─────────────────────┤
│  Price spread        │  40%   │ < -1%     │ > +8%               │
│  APY level           │  25%   │ < 10%     │ > 30%               │
│  AUM vs cap          │  25%   │ < 80%     │ > 98%               │
│  Market volatility   │  10%   │ Low       │ High                │
├──────────────────────┼────────┼───────────┼─────────────────────┤
│  Action threshold    │        │ Score > 70│ Score > 70          │
└─────────────────────────────────────────────────────────────────┘
```

---

### Option E: LLM-Assisted Signal Interpretation

**Description:** Feed market data to an LLM for nuanced interpretation, similar to existing trading bot's approach.

**Pros:**
- Can incorporate news, sentiment, unusual patterns
- Flexible reasoning

**Cons:**
- Latency (not suitable for high-frequency)
- API costs
- May hallucinate signals

**When to Use:**
- For daily/weekly rebalancing decisions
- For interpreting unusual market conditions
- NOT for sub-minute arbitrage execution

---

## Architecture Comparison

| Component | Option A | Option B | Option C | Option D | Option E |
|-----------|----------|----------|----------|----------|----------|
| **Price feed** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **APY tracking** | | ✓ | | ✓ | ✓ |
| **AUM monitoring** | | | ✓ | ✓ | ✓ |
| **LLM integration** | | | | | ✓ |
| **Complexity** | Low | Medium | Medium | High | High |
| **Latency** | <1s | <5s | <5s | <5s | 10-30s |
| **Best for** | Quick MVP | Medium-term | Event-driven | Production | Advisory |

---

## Research Findings: Jupiter API & On-Chain Data

### ✅ ANSWERED: APY/APR Data is Available On-Chain

**There is no dedicated REST API for JLP APY**, but the data is available directly from the on-chain Pool account via Solana RPC.

#### Pool Account Structure

The JLP Pool account at address `5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq` contains a `poolApr` field:

| Field | Type | Description |
|-------|------|-------------|
| `poolApr.feeAprBps` | `u64` | Fee APR in basis points (e.g., 800 = 8% APR) |
| `poolApr.lastUpdated` | `i64` | Unix timestamp of last APR update |
| `poolApr.realizedFeeUsd` | `u64` | Realized fees in USD |

#### Other Available On-Chain Data

| Data Point | Location | How to Access |
|------------|----------|---------------|
| **Virtual Price** | Calculated | `Sum of custody AUM (USD) / Total JLP supply` |
| **Current AUM** | `Pool.aumUsd` | `u128` field on Pool account |
| **AUM Cap** | `Pool.limit.maxAumUsd` | `u128` field in Limit struct |
| **Token Weightages** | Custody accounts | Per-token target vs actual weights |

#### How to Query This Data

**Option 1: Direct Solana RPC with Anchor IDL**
```
# Requires parsing Jupiter Perpetuals IDL
# Reference implementation: github.com/julianfssen/jupiter-perps-anchor-idl-parsing
# Example files:
#   - get-jlp-virtual-price.ts
#   - get-pool-aum.ts
#   - poll-and-stream-oracle-price-updates.ts
```

**Option 2: Use existing TypeScript examples, call from Python**
- The Jupiter team maintains TypeScript examples at `julianfssen/jupiter-perps-anchor-idl-parsing`
- Could wrap in a subprocess or create a small Node.js microservice
- Alternatively, port to Python using `solana-py` + `anchorpy`

#### Key Addresses

| Account | Address |
|---------|---------|
| Pool | `5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq` |
| Program | `PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu` |

#### Implementation Recommendation for MVP

1. **Start with polling**: Query Pool account every 60 seconds via Solana RPC
2. **Parse with anchorpy**: Use Python's `anchorpy` library to decode the Perpetuals IDL
3. **Calculate virtual price**: Aggregate custody AUM / JLP token supply
4. **Compare to market price**: Get market price from Jupiter Swap quote API
5. **Phase 2**: Add WebSocket subscription for real-time updates

---

## Price Fetching Approaches

Two approaches exist for determining the premium/discount spread. The MVP implements the simpler approach, with the more accurate on-chain approach available for future enhancement.

### Approach 1: Buy/Sell Quote Spread (MVP - Implemented)

**Description:** Use the difference between Jupiter swap quotes for buying vs selling JLP as a proxy for premium/discount.

**How it works:**
```
Buy Price  = Quote $100 USDC → JLP, calculate USDC per JLP received
Sell Price = Quote 1 JLP → USDC, get USDC received

Spread = (Sell Price - Buy Price) / Buy Price

Positive spread = Premium (selling gives more than buying costs)
Negative spread = Discount (selling gives less than buying costs)
```

**Pros:**
- Simple to implement - uses existing Jupiter Quote API
- No IDL parsing required
- Reflects actual executable prices including liquidity/slippage
- Works immediately with current infrastructure

**Cons:**
- Measures DEX liquidity spread, not true NAV premium/discount
- Small spreads (~0.01%) may be within normal DEX slippage
- Doesn't capture the theoretical "fair value" of JLP based on underlying assets
- May miss opportunities where NAV diverges but DEX quotes are tight

**Implementation:** `lp_arbitrage.py` - `JLPPriceFetcher.get_buy_price()` and `get_sell_price()`

---

### Approach 2: On-Chain Virtual Price Calculation (Future Enhancement)

**Description:** Calculate the true virtual (NAV) price by reading JLP pool data directly from Solana and comparing to market swap price.

**How it works:**
```
Virtual Price = Total Pool AUM (USD) / Total JLP Token Supply

Market Price  = Jupiter Quote: 1 JLP → USDC

Spread = (Market Price - Virtual Price) / Virtual Price
```

**Data Sources Required:**

| Data Point | Source | Method |
|------------|--------|--------|
| Pool AUM | `Pool.aumUsd` field | Solana RPC `getAccountInfo` |
| JLP Supply | JLP token mint | Solana RPC `getTokenSupply` |
| Custody Values | Per-custody accounts | Sum of custody AUM fields |
| Market Price | Jupiter Quote API | Existing `get_quote()` |

**Implementation Steps:**

1. **Fetch Pool Account Data**
   ```python
   # RPC call to get Pool account
   response = client.post(rpc_url, json={
       "jsonrpc": "2.0",
       "method": "getAccountInfo",
       "params": [
           "5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq",  # JLP Pool
           {"encoding": "base64"}
       ]
   })
   ```

2. **Decode Account Data Using IDL**
   ```python
   from anchorpy import Program, Provider
   
   # Load Jupiter Perpetuals IDL
   idl = Program.fetch_idl("PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu")
   program = Program(idl, "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu", provider)
   
   # Decode pool account
   pool = await program.account["Pool"].fetch(pool_pubkey)
   aum_usd = pool.aum_usd
   ```

3. **Get JLP Token Supply**
   ```python
   response = client.post(rpc_url, json={
       "jsonrpc": "2.0",
       "method": "getTokenSupply",
       "params": ["27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"]  # JLP Mint
   })
   supply = response["result"]["value"]["uiAmount"]
   ```

4. **Calculate Virtual Price**
   ```python
   virtual_price = aum_usd / supply
   ```

**Pros:**
- True NAV-based virtual price
- Captures actual premium/discount vs theoretical fair value
- More accurate arbitrage signals
- Can detect opportunities even when DEX liquidity is tight

**Cons:**
- Requires IDL parsing (complex setup)
- `anchorpy` dependency and Solana RPC integration
- IDL may change with protocol upgrades
- More points of failure (RPC, IDL, parsing)

---

### Approach Comparison

| Aspect | Buy/Sell Spread (MVP) | On-Chain Virtual Price |
|--------|----------------------|------------------------|
| **Complexity** | Low | High |
| **Accuracy** | Proxy measure | True NAV |
| **Dependencies** | Jupiter API only | Solana RPC + anchorpy + IDL |
| **Latency** | ~500ms (2 API calls) | ~1-2s (RPC + parsing) |
| **Failure modes** | API rate limits | RPC errors, IDL changes |
| **Best for** | MVP, quick testing | Production, larger spreads |

---

### Open Questions for On-Chain Approach

1. **IDL Availability**: Where is the current Jupiter Perpetuals IDL hosted? Is it stable or frequently updated?

2. **anchorpy Compatibility**: Does `anchorpy` support the latest Anchor version used by Jupiter Perpetuals? Any known issues?

3. **Custody Account Enumeration**: How do we discover all custody accounts to sum their AUM? Is there a registry or do we hardcode addresses?

4. **AUM Calculation**: Is `Pool.aumUsd` the pre-calculated total, or do we need to sum individual custody values? Are there edge cases (pending deposits, etc.)?

5. **Price Decimals**: What decimal precision does `aumUsd` use? Is it raw or UI-formatted?

6. **Rate Limits**: What are the Solana RPC rate limits for `getAccountInfo`? Do we need a dedicated RPC provider?

7. **Real-time Updates**: Can we use WebSocket subscriptions (`accountSubscribe`) for the Pool account to get push updates instead of polling?

8. **Reference Implementation**: The TypeScript examples at `julianfssen/jupiter-perps-anchor-idl-parsing` - should we port to Python or wrap as a subprocess?

---

### Recommended Path Forward

1. ~~**Current MVP**: Continue using Buy/Sell Spread approach for initial data collection~~
2. ~~**Parallel Research**: Investigate IDL parsing with `anchorpy` in a separate branch~~
3. ~~**Validation**: Once on-chain approach works, run both methods in parallel to compare signals~~
4. ~~**Migration**: Switch to on-chain approach when validated, keep spread approach as fallback~~

**✅ COMPLETED** - On-chain approach is now the default. See implementation below.

---

### On-Chain Integration (IMPLEMENTED)

The on-chain virtual price calculation is now integrated into `lp_arbitrage.py` as the **default method**, with DEX spread as fallback.

#### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    JLPPriceFetcher                              │
├─────────────────────────────────────────────────────────────────┤
│  PRIMARY: On-Chain Method                                       │
│  ┌─────────────────────┐    ┌─────────────────────┐            │
│  │ Solana RPC          │    │ Pool Account Parse  │            │
│  │ getTokenSupply()    │───▶│ aumUsd (u128)       │            │
│  │ getAccountInfo()    │    │ offset: byte 180    │            │
│  └─────────────────────┘    └──────────┬──────────┘            │
│                                        │                        │
│                         Virtual Price = AUM / Supply            │
│                                        │                        │
├─────────────────────────────────────────────────────────────────┤
│  FALLBACK: DEX Spread Method                                    │
│  ┌─────────────────────┐                                        │
│  │ Jupiter Quote API   │                                        │
│  │ USDC → JLP quote    │──▶ Buy price as virtual proxy         │
│  └─────────────────────┘                                        │
├─────────────────────────────────────────────────────────────────┤
│  MARKET PRICE: Always from DEX                                  │
│  ┌─────────────────────┐                                        │
│  │ Jupiter Quote API   │                                        │
│  │ JLP → USDC quote    │──▶ What you actually receive           │
│  └─────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```

#### Pool Struct Parsing

The Jupiter Perpetuals Pool account is parsed using Python `struct` module:

```python
# Pool account layout (simplified)
# Offset 0:   8 bytes  - Anchor discriminator
# Offset 8:   4 bytes  - name string length (u32)
# Offset 12:  N bytes  - name string ("Pool")
# Offset 12+N: 4 bytes - custodies vec length (u32)
# Offset 16+N: M*32    - custody pubkeys (M = num_custodies)
# Offset 16+N+M*32: 16 bytes - aumUsd (u128, little-endian)

def _parse_pool_aum(data: bytes) -> float:
    offset = 8  # Skip discriminator
    
    # Skip name string
    name_len = struct.unpack_from('<I', data, offset)[0]
    offset += 4 + name_len
    
    # Skip custodies vec
    num_custodies = struct.unpack_from('<I', data, offset)[0]
    offset += 4 + (num_custodies * 32)
    
    # Read aumUsd (u128)
    low = struct.unpack_from('<Q', data, offset)[0]
    high = struct.unpack_from('<Q', data, offset + 8)[0]
    aum_raw = low + (high << 64)
    
    return aum_raw / 1_000_000  # 6 decimals
```

#### Comparison Mode

Use `--compare-price-sources` to run both methods and output comparison:

```bash
python lp_arbitrage.py --once --compare-price-sources
```

Output:
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
  │   Market vs Buy: $     -0.000278                    │
  └─────────────────────────────────────────────────────┘
```

#### Key Findings

| Metric | On-Chain | DEX Spread |
|--------|----------|------------|
| Virtual Price | $3.8211 (true NAV) | $3.8257 (buy quote) |
| Market Price | $3.8255 (sell quote) | $3.8255 (sell quote) |
| Spread | +0.11% (true premium) | -0.01% (DEX spread) |

**Insight**: The on-chain method reveals a **+0.11% premium** (market > NAV), while DEX spread shows near-parity. This is because DEX spread measures bid-ask, not NAV divergence.

#### Configuration

| Parameter | Environment Variable | Default |
|-----------|---------------------|---------|
| `--compare-price-sources` | `COMPARE_PRICE_SOURCES` | `false` |
| `--rpc-url` | `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` |
| `--auto-calculate-spread` | `AUTO_CALCULATE_SPREAD` | `false` |
| `--profit-margin` | `PROFIT_MARGIN` | `0.005` |

#### Auto-Calculate Spread (IMPLEMENTED)

The bot can dynamically calculate the minimum viable spread needed to be profitable, based on actual swap costs from Jupiter quotes.

**Usage:**
```bash
python lp_arbitrage.py --once --auto-calculate-spread
python lp_arbitrage.py --once --auto-calculate-spread --profit-margin=0.01
```

**How it works:**

```
┌─────────────────────────────────────────────────────────────────┐
│              MIN VIABLE SPREAD CALCULATION                      │
├─────────────────────────────────────────────────────────────────┤
│  1. Fetch Jupiter quote: USDC → JLP (buy direction)            │
│  2. Fetch Jupiter quote: JLP → USDC (sell direction)           │
│  3. Extract from quotes:                                        │
│     - Swap fees: routePlan[].swapInfo.feeAmount                │
│     - Price impact: priceImpactPct                              │
│  4. Estimate gas: ~$0.0015 (2 transactions × $0.00075)         │
│  5. Calculate:                                                  │
│     min_viable_spread = buy_fees + sell_fees + impact + gas    │
│  6. Set thresholds:                                             │
│     buy_threshold = -(min_viable_spread + profit_margin)       │
│     sell_threshold = +(min_viable_spread + profit_margin)      │
└─────────────────────────────────────────────────────────────────┘
```

**Example output:**
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

**Notes:**
- JLP mint/redeem may show low explicit fees because costs are built into the price spread
- The `--profit-margin` parameter adds a buffer above break-even (default 0.5%)
- Calculation uses the configured `--trade-amount` for accurate fee estimation

#### Failure Handling

1. **On-chain fails**: Falls back to DEX buy price as virtual proxy
2. **Market price fails**: Returns `None`, skips cycle
3. **Both fail**: Logs error, returns `{"error": "price_fetch_failed"}`

#### Lab Program

The standalone lab at `lab/jlp_virtual_price_lab.py` can be used to test methods independently:

```bash
python lab/jlp_virtual_price_lab.py --method=rpc    # On-chain only
python lab/jlp_virtual_price_lab.py --method=mvp    # DEX spread only
python lab/jlp_virtual_price_lab.py --method=all    # Compare all
```

---

## Open Questions

### Data & APIs (Partially Resolved)

1. **How do we get the virtual price?** ✅ RESOLVED
   - Calculate from on-chain data: `Sum of custody AUM / JLP supply`
   - Reference: `get-jlp-virtual-price.ts` in Jupiter examples repo

2. **Is real-time APY available via API?** ✅ RESOLVED
   - Yes, via on-chain `poolApr.feeAprBps` field on Pool account
   - No REST API; must query Solana RPC directly
   - Can subscribe to account changes for real-time updates

3. **How do we detect AUM cap status?** ✅ RESOLVED
   - Compare `Pool.aumUsd` to `Pool.limit.maxAumUsd`
   - Both are on-chain fields, queryable via RPC

### Execution

4. **What are the actual transaction costs?** ✅ RESOLVED
   - Solana gas: ~$0.001-0.01
   - Jupiter swap fees: **Available via Quote API** (see below)
   - Slippage estimate: **Available via Quote API** (`priceImpactPct`)

   **Jupiter Quote API fee fields:**
   ```json
   {
     "priceImpactPct": "0.0001",           // Price impact estimate
     "platformFee": { "amount": "0", "feeBps": 0 },  // Integrator fee (usually 0)
     "routePlan": [{
       "swapInfo": {
         "feeAmount": "1285",              // AMM fee for this hop (in output token units)
         "feeMint": "EPjFWdd5..."          // Token the fee is denominated in
       }
     }]
   }
   ```
   
   **To calculate total cost:** Sum `feeAmount` across all hops + `priceImpactPct` + Solana gas (~0.000005 SOL)

5. **Minimum profitable spread?** ✅ RESOLVED
   - API costs: ~$0/month (public RPC) — see Rate Limits section
   - Swap fees: Query Jupiter Quote API before each trade to get exact cost
   - **Strategy:** Only execute if `spread% > (feeAmount/tradeSize + priceImpactPct + buffer)`
   - Estimate: ~0.3-0.5% total cost for typical trades, so need >1% spread for safety margin

6. **How to handle partial fills and slippage?** ✅ RESOLVED
   
   **Slippage protection varies by platform:**

   | Platform | Entry/Exit Mechanism | Slippage Protection |
   |----------|---------------------|---------------------|
   | **Jupiter (JLP)** | AMM swap (USDC↔JLP) | Set `slippageBps`; tx fails if output < threshold |
   | **HyperLiquid (HLP)** | Direct vault deposit (USDC→shares) | No AMM curve; receive shares at current NAV |
   | **Drift (hJLP)** | Direct vault deposit (USDC→shares) | No AMM curve; oracle-based pricing |

   **Key distinction:**
   - **Jupiter JLP**: You *swap* USDC for JLP tokens via AMM — subject to liquidity curve slippage
   - **HyperLiquid/Drift**: You *deposit* USDC directly into the vault — receive shares at NAV price, no AMM involved
   
   **Note on JLP and impermanent loss:** While *entering/exiting* JLP uses an AMM swap (slippage applies), *holding* JLP is NOT subject to impermanent loss. JLP is a basket of underlying assets (like an index fund), not an AMM LP position. The "impermanent loss" concept from Uniswap-style LPs does not apply — JLP simply reprices based on its underlying asset values.

   **Jupiter-specific protections:**
   ```json
   {
     "dynamicSlippage": { "minBps": 50, "maxBps": 300 }
   }
   ```
   Jupiter auto-calculates optimal slippage based on token pair, volatility, and market conditions.
   
   **For large orders:** Use `priceImpactPct` from quote to decide whether to split into smaller trades.

### Risk Management

7. **Should we hedge underlying asset exposure?** (Decision: Use hedged options)
   - JLP is ~45% SOL, ~10% ETH/BTC; HLP is USDC-only (no hedge needed)
   - A 10% crypto crash wipes out JLP arbitrage gains
   - **Note:** This is direct asset price exposure (like holding an index fund), NOT impermanent loss. JLP reprices immediately based on underlying asset values.
   - Options: perpetual shorts, delta-neutral strategies, use HLP instead, accept the risk
   - **MVP Decision:** Use HLP (USDC-based, no hedging needed) or Drift hJLP (protocol handles hedging automatically)

8. **Position sizing strategy?** ✅ DECIDED
   - **MVP Decision:** Fixed amount per trade (like existing trading bot)
   - Kelly criterion: Phase 2 (requires historical win rate data)
   - Scale with spread size: Phase 2

9. **What's the maximum position we should hold per platform?** ✅ DECIDED
   - **MVP Decision:** No max position limit
   - Summarize current positions at end of each bot run (assumes API available for position query)
   - Liquidity constraints and diversification: Phase 2

### Competition

10. **Are we competing with sophisticated actors?** (Requires testing)
    - Existing vaults (Vectis Navigator) already do this
    - MEV bots may front-run
    - How fast do arbitrage opportunities close?
    - **MVP Decision:** Test at different wake-up and run intervals. Use fast APIs. Log timing data (API latency, decision time) with trade info for later analysis.

11. **Is there enough spread for retail-scale bots?** (TBD — collect our own data)
    - Large players may capture most of the spread
    - History logging now designed — see History Logging section
    - **MVP Decision:** No external historical data source for MVP. Collect our own data by running the bot in what-if mode first.

### Platform-Specific Questions

12. **HyperLiquid: How do we handle the 4-day withdrawal lock-up?** ✅ RESOLVED
    - **Clarified:** Lock-up means you can withdraw 4 days after your most recent deposit. You DO get the price/NAV at the time of deposit — funds are just locked from withdrawal for 4 days.
    - **Impact:** This is acceptable. We still benefit from frequent wake-up intervals to capture good entry prices. The lock-up only affects liquidity, not the trade execution price.
    - Strategy: Frequent monitoring is still viable; just plan for 4-day minimum hold period.

13. **Drift: Should we use it post-exploit?** ✅ DECIDED
    - **Decision:** Will NOT eliminate Drift based on the exploit alone.
    - Rationale: Would only reject if other exchanges had documented mechanisms proven to stop the same breach type. This is hard to verify.
    - Insurance Fund was unaffected—IF staking may be safer than general vaults.
    - Monitor for stability before deploying significant capital.

14. **Which platform for MVP?** ✅ DECIDED (Updated April 2026)
    - **Target:** Drift hJLP (Hedged JLP via Gauntlet) — *temporarily unavailable post-exploit*
    - **Interim:** Jupiter JLP (unhedged) for low-volume beta testing
    - **Rationale:** Collect data and validate strategy with small positions while Drift relaunches
    - **Risk mitigation:** Small position sizes ($50-100), max exposure $500, no hedging
    - See MVP Platform Choice section for full details.

15. **Multi-platform: How to manage cross-chain complexity?** ✅ DECIDED
    - **Interim:** Jupiter JLP only (Solana-based, unhedged)
    - **Future:** Transition to Drift hJLP when available (automated hedging)
    - Design architecture with abstract platform interface for easy platform swaps.
    - HyperLiquid: Phase 2 (requires separate chain infrastructure).

### Scheduling & Operations

16. **Where do we get historical spread data for backtesting?** ✅ DECIDED
    - **MVP Decision:** Collect our own data by running the bot in what-if mode.
    - No external historical data source needed for MVP.
    - Run what-if mode for several weeks before deploying real capital.

17. **History storage granularity?** ✅ DECIDED
    - **Default:** Store only when opportunity detected (balance of size and context)
    - **`--verbose` flag:** Store every wake-up snapshot for detailed analysis
    - Trade executions always logged regardless of mode.

18. **Adaptive polling: MVP or Phase 2?** ✅ DECIDED
    - **MVP Decision:** Fixed interval polling.
    - Adaptive polling deferred to Phase 2.
    - Test different fixed intervals (1 min, 5 min, 15 min) to find optimal balance.

19. **Alerting for what-if mode?** ✅ DECIDED
    - **MVP Decision:** No external alerts (Discord/Telegram).
    - Clear terminal output at end of each run showing:
      - Opportunities detected
      - Actions taken (or simulated in what-if mode)
      - Current position summary
    - Use `lp_analyzer.py` for periodic historical analysis.

---

## MVP Proposal

### Scope: Minimal Viable Arbitrage Bot

**Goal:** Validate the strategy with minimal complexity before building sophisticated features.

### MVP Platform Choice

#### Target: Drift hJLP (Currently Unavailable)

**Drift hJLP remains the preferred long-term choice** for automated hedging, but is **temporarily unavailable** due to the April 2026 exploit. Drift is relaunching with enhanced security measures.

| Consideration | Drift hJLP Advantage |
|---------------|---------------------|
| **Wallet Compatibility** | ✅ Phantom wallet (existing infrastructure) |
| **Blockchain** | ✅ Solana (reuse existing RPC, wallet code) |
| **Delta Hedging** | ✅ Protocol handles automatically via Gauntlet's strategy |
| **JLP Benefits** | ✅ Captures JLP's large spreads and 75% fee share |
| **Risk Mitigation** | ✅ Delta-neutral positioning eliminates asset price exposure |
| **SDK** | ✅ Native Python SDK (`driftpy`) |

**Status:** ⏸️ Waiting for Drift relaunch with enhanced security

---

#### Interim: Jupiter JLP (Unhedged) ✅ ACTIVE FOR BETA

While Drift hJLP is unavailable, we will use **raw Jupiter JLP** for low-volume beta testing:

| Consideration | Jupiter JLP (Interim) |
|---------------|----------------------|
| **Wallet Compatibility** | ✅ Phantom wallet |
| **Blockchain** | ✅ Solana |
| **Delta Hedging** | ⚠️ **NOT IMPLEMENTED** — accept risk for small positions |
| **JLP Benefits** | ✅ Large spreads, 75% fee share, no lock-up |
| **Risk** | ⚠️ Exposed to SOL/ETH/BTC price movements (~45% SOL, ~10% ETH/BTC) |
| **API** | ✅ Jupiter Quote/Swap API + on-chain JLP pool data |

**Risk Mitigation Strategy (No Hedging):**
- **Small position sizes only** — limit exposure to acceptable loss
- **Monitor underlying asset prices** — exit if crypto market drops significantly
- **Collect data** — use what-if mode to validate strategy before scaling
- **Transition to Drift hJLP** — when available, for automated hedging

| Risk Scenario | Impact on $100 JLP Position |
|---------------|----------------------------|
| 10% crypto crash | ~$4.50 loss (45% × 10%) |
| 20% crypto crash | ~$9.00 loss |
| Arbitrage gain (2% spread) | +$2.00 profit |

**Recommendation:** Keep position size under $500 until Drift hJLP is available.

---

### Prerequisites: Jupiter JLP (Interim Beta)

#### 1. Solana Wallet (Phantom)

| Requirement | Details |
|-------------|---------|
| **Phantom Wallet** | Install browser extension or mobile app |
| **SOL Balance** | Minimum ~0.1 SOL for transaction fees |
| **USDC Balance** | Capital for JLP purchases (start with $50-100 for beta) |

**For bot automation, export keypair:**
```bash
# Option A: Use Phantom's exported private key
# Settings → Security & Privacy → Export Private Key

# Option B: Generate dedicated bot wallet
solana-keygen new --outfile ~/.config/solana/lp-bot-keypair.json

# Fund the bot wallet from Phantom
```

#### 2. Jupiter JLP Pool Access

| Item | Details |
|------|---------|
| **JLP Pool Account** | `5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq` |
| **JLP Token Mint** | `27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4` |
| **Lock-up** | None — can buy/sell instantly |
| **Entry/Exit** | Via Jupiter swap (USDC ↔ JLP) |

#### 3. Development Environment

| Requirement | Command |
|-------------|---------|
| **Python 3.10+** | `python --version` |
| **solana-py** | `pip install solana` |
| **anchorpy** | `pip install anchorpy` |
| **httpx** | `pip install httpx` (for Jupiter API) |
| **Solana RPC** | Public: `https://api.mainnet-beta.solana.com` or Helius |

#### 4. Environment Configuration

```bash
# .env file for Jupiter JLP arbitrage bot (interim)

# === Solana & Wallet ===
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_KEYPAIR_PATH=~/.config/solana/lp-bot-keypair.json

# === Jupiter JLP ===
JLP_POOL_ACCOUNT=5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq
JLP_TOKEN_MINT=27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4

# === Trading Parameters (Conservative for unhedged) ===
BUY_THRESHOLD=-0.02             # Buy when market < virtual by 2%
SELL_THRESHOLD=0.03             # Sell when market > virtual by 3%
TRADE_AMOUNT_USD=50             # Small fixed amount (unhedged risk)
MAX_POSITION_USD=500            # Cap total exposure

# === Scheduling ===
POLL_INTERVAL_SECONDS=300       # 5-minute wake-up

# === Modes ===
TRADING_MODE=whatif             # Start in paper trading mode
VERBOSE=false

# === History ===
HISTORY_DIR=./history/lp/
```

---

### Jupiter JLP: How It Works (Interim)

```
┌─────────────────────────────────────────────────────────────────┐
│              JUPITER JLP ARBITRAGE (UNHEDGED)                    │
└─────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────┐
                    │   JLP Pool On-Chain │
                    │  (Virtual Price)    │
                    └──────────┬──────────┘
                               │
      ┌────────────────────────┼────────────────────────┐
      │                        │                        │
      ▼                        ▼                        ▼
┌──────────┐            ┌──────────┐            ┌──────────┐
│   SOL    │            │   ETH    │            │   BTC    │
│   ~45%   │            │   ~5%    │            │   ~5%    │
└──────────┘            └──────────┘            └──────────┘
      │                        │                        │
      └────────────────────────┼────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  USDC/USDT (~45%)   │
                    └─────────────────────┘

  BOT ACTIONS:
  ┌────────────────────────────────────────────────────────────┐
  │  1. Fetch virtual price from JLP pool (on-chain)           │
  │  2. Fetch market price from Jupiter Quote API              │
  │  3. Calculate spread: (market - virtual) / virtual         │
  │  4. If spread < -2%: BUY JLP (discount)                    │
  │  5. If spread > +3%: SELL JLP (premium)                    │
  │  6. Log snapshot and action                                │
  └────────────────────────────────────────────────────────────┘

  ⚠️  NO HEDGING — exposed to underlying asset price movements
```

### Key Jupiter Interactions

```python
# Core API usage pattern for Jupiter JLP (interim)

import httpx
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

# === 1. Fetch JLP Virtual Price (on-chain) ===
JLP_POOL = Pubkey.from_string("5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq")

async def get_jlp_virtual_price(client: AsyncClient) -> float:
    """
    Fetch JLP pool account and calculate virtual price.
    Virtual price = Total AUM / Total JLP Supply
    """
    # Requires parsing the JLP pool IDL to decode account data
    # Pool stores: aum_usd, total_supply
    account = await client.get_account_info(JLP_POOL)
    # ... decode using anchorpy and JLP IDL
    return aum_usd / total_supply

# === 2. Fetch JLP Market Price (Jupiter Quote API) ===
JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JLP_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

async def get_jlp_market_price() -> float:
    """
    Get JLP market price by quoting 1 JLP → USDC swap.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(JUPITER_QUOTE_URL, params={
            "inputMint": JLP_MINT,
            "outputMint": USDC_MINT,
            "amount": str(1_000_000),  # 1 JLP (6 decimals)
            "slippageBps": 50
        })
        quote = resp.json()
        return int(quote["outAmount"]) / 1_000_000  # USDC price

# === 3. Calculate Spread ===
def calculate_spread(market_price: float, virtual_price: float) -> float:
    return (market_price - virtual_price) / virtual_price

# === 4. Execute Swap (via Jupiter) ===
async def buy_jlp(amount_usdc: int):
    """Swap USDC → JLP when discount detected."""
    # 1. Get quote
    # 2. Get swap transaction from Jupiter
    # 3. Sign and send transaction
    pass

async def sell_jlp(amount_jlp: int):
    """Swap JLP → USDC when premium detected."""
    pass
```

---

### Prerequisites: Drift hJLP (Future)

*The following prerequisites will apply when Drift relaunches:*

#### Drift Protocol Account

| Step | Action |
|------|--------|
| **Create Drift Account** | Visit [app.drift.trade](https://app.drift.trade) and connect Phantom |
| **Initialize User** | Complete first deposit to initialize on-chain account |
| **Note Account Address** | Save your Drift user account public key |

**Verify via driftpy:**
```python
# After account creation, verify programmatically
from driftpy.drift_client import DriftClient
# If this succeeds, account exists
drift_client.get_user()
```

#### 3. Drift hJLP Vault Access

| Item | Details |
|------|---------|
| **hJLP Vault Address** | `[To be confirmed - Gauntlet's hJLP vault on Drift]` |
| **Vault Type** | Permissionless (anyone can deposit) |
| **Deposit Token** | USDC (converted to JLP automatically) |
| **Withdrawal** | Request → 13-day cooldown → Complete withdrawal |

**Finding the vault address:**
```bash
# Via Drift Vault CLI
yarn cli list-vaults --filter="hJLP"

# Or via Drift UI: app.drift.trade → Vaults → Search "hJLP"
```

#### 4. Development Environment

| Requirement | Command |
|-------------|---------|
| **Python 3.10+** | `python --version` |
| **driftpy SDK** | `pip install driftpy` |
| **anchorpy** | `pip install anchorpy` (dependency) |
| **solana-py** | `pip install solana` (dependency) |
| **Solana RPC** | Public: `https://api.mainnet-beta.solana.com` or dedicated (Helius, QuickNode) |

**Environment variables to configure:**
```bash
# .env file for LP arbitrage bot
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_KEYPAIR_PATH=~/.config/solana/lp-bot-keypair.json
DRIFT_HJLP_VAULT_ADDRESS=<vault-pubkey>
TRADING_MODE=whatif  # Start in paper trading mode
```

#### 5. API Rate Limits & RPC Considerations

| RPC Provider | Rate Limit | Cost | Notes |
|--------------|------------|------|-------|
| **Public Solana RPC** | ~100 req/sec (shared) | Free | May be throttled during high load |
| **Helius** | 10-100 req/sec | $0-49/mo | Recommended for production |
| **QuickNode** | Custom | $49+/mo | Enterprise option |

**Recommendation:** Start with public RPC for testing; upgrade to Helius free tier for what-if mode data collection.

---

### Drift hJLP: How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    DRIFT hJLP VAULT FLOW                         │
└─────────────────────────────────────────────────────────────────┘

  USER DEPOSITS USDC
         │
         ▼
  ┌──────────────┐
  │  Drift hJLP  │ ◄── Gauntlet-managed vault
  │    Vault     │
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐     ┌──────────────┐
  │  Convert to  │────▶│  Deposit as  │
  │     JLP      │     │  Collateral  │
  └──────────────┘     └──────┬───────┘
                              │
         ┌────────────────────┴────────────────────┐
         │                                         │
         ▼                                         ▼
  ┌──────────────┐                         ┌──────────────┐
  │   Earn JLP   │                         │  Open Hedge  │
  │    Yield     │                         │  Positions   │
  │  (75% fees)  │                         │ (Short SOL,  │
  └──────────────┘                         │  ETH, BTC)   │
                                           └──────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  DELTA-NEUTRAL   │
                    │  Net exposure ≈ 0 │
                    │  Pure yield play  │
                    └──────────────────┘
```

**Key insight:** The bot doesn't need to manage hedging — Gauntlet's strategy handles this automatically. The bot focuses on:
1. Monitoring premium/discount spread
2. Depositing when discount detected
3. Requesting withdrawal when premium detected

### MVP Features

| Feature | Included | Notes |
|---------|----------|-------|
| Price spread monitoring | ✓ | hJLP vault share price vs NAV |
| Deposit/withdraw execution | ✓ | Via `driftpy` SDK |
| Configurable thresholds | ✓ | Buy/sell spread triggers |
| Logging & history | ✓ | Track all trades for analysis |
| Position summary | ✓ | Display current vault holdings at end of run |
| What-if mode | ✓ | Paper trading for data collection |
| Delta hedging | N/A | Handled automatically by Drift hJLP vault |
| APY monitoring | ✗ | Phase 2 |
| Multi-platform | ✗ | Phase 2 (add HyperLiquid, raw JLP) |

### MVP Architecture (Drift hJLP)

```
┌─────────────────────────────────────────────────────────────────┐
│                    MVP COMPONENTS (Drift hJLP)                   │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Price Feed  │────▶│   Strategy   │────▶│  Executor    │
│   (driftpy)  │     │   Engine     │     │   (driftpy)  │
├──────────────┤     ├──────────────┤     ├──────────────┤
│ • Vault NAV  │     │ • Spread     │     │ • Vault      │
│   (on-chain) │     │   calculator │     │   deposit()  │
│ • Share      │     │ • Threshold  │     │ • Vault      │
│   price      │     │   checker    │     │   withdraw() │
│ • Position   │     │ • Decision   │     │ • Tx signing │
│   balance    │     │   logic      │     │   (keypair)  │
└──────────────┘     └──────────────┘     └──────────────┘
        │                   │                     │
        │                   ▼                     │
        │            ┌──────────────┐             │
        │            │   Logger     │             │
        │            ├──────────────┤             │
        │            │ • Snapshots  │             │
        │            │ • Trades     │             │
        │            │ • Timing     │             │
        │            └──────────────┘             │
        │                   │                     │
        └───────────────────┼─────────────────────┘
                            ▼
                   ┌────────────────┐
                   │ Terminal Output │
                   ├────────────────┤
                   │ • Position sum │
                   │ • Opportunities│
                   │ • Actions taken│
                   └────────────────┘
```

### Key driftpy Interactions

```python
# Core SDK usage pattern for MVP

from driftpy.drift_client import DriftClient
from driftpy.accounts import get_vault_account
from anchorpy import Wallet

# 1. Initialize client
drift_client = DriftClient(
    connection,
    wallet,
    env="mainnet"
)
await drift_client.subscribe()

# 2. Get vault data (hJLP)
vault = await get_vault_account(
    drift_client.program, 
    vault_pubkey
)
vault_nav = vault.net_deposits  # Total NAV
vault_shares = vault.total_shares

# 3. Get user position
user_vault_depositor = await get_vault_depositor_account(
    drift_client.program,
    vault_pubkey,
    wallet.public_key
)
user_shares = user_vault_depositor.vault_shares

# 4. Calculate share price vs market
share_price = vault_nav / vault_shares
# Compare to market price from Jupiter/DEX

# 5. Execute deposit (if discount detected)
await drift_client.deposit_into_vault(
    vault_pubkey,
    amount_usdc
)

# 6. Request withdrawal (if premium detected)
await drift_client.request_withdraw_from_vault(
    vault_pubkey,
    shares_to_withdraw
)
```

### MVP Configuration

```bash
# Environment variables for Drift hJLP arbitrage bot

# === Solana & Wallet ===
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_KEYPAIR_PATH=~/.config/solana/lp-bot-keypair.json

# === Drift hJLP Vault ===
DRIFT_HJLP_VAULT_ADDRESS=<vault-pubkey>    # Gauntlet hJLP vault address

# === Trading Parameters ===
BUY_THRESHOLD=-0.01             # Deposit when share price < NAV by 1%
SELL_THRESHOLD=0.02             # Withdraw when share price > NAV by 2%
TRADE_AMOUNT_USD=100            # Fixed amount per trade (MVP decision)
MIN_TRADE_USD=50                # Minimum trade size

# === Scheduling ===
POLL_INTERVAL_SECONDS=300       # Wake-up interval (5 minutes default)

# === Modes ===
TRADING_MODE=whatif             # whatif | live
VERBOSE=false                   # true = log every snapshot; false = only opportunities

# === History ===
HISTORY_DIR=./history/lp/       # Where to store recommendation history
```

### CLI Flags

```bash
# Run modes
python lp_arbitrage.py --once                    # Single run (for cron)
python lp_arbitrage.py --daemon --interval=300   # Continuous with 5-min wake-up

# Trading modes
python lp_arbitrage.py --trading-mode=whatif     # Paper trading (default)
python lp_arbitrage.py --trading-mode=live       # Real execution

# Logging
python lp_arbitrage.py --verbose                 # Log every wake-up snapshot
```

---

## Execution Modes & Scheduling

### Wake-Up Scheduling Model

The bot should support a **parameter-driven wake-up interval** rather than continuous polling. This balances responsiveness with API rate limits and costs.

#### Execution Modes

| Mode | Flag | Description | Use Case |
|------|------|-------------|----------|
| **Once** | `--once` | Run once and exit | Cron jobs, testing |
| **Daemon** | `--daemon` | Continuous loop with sleep interval | Long-running monitoring |
| **Backtest** | `--backtest` | Replay historical data | Strategy validation |

#### Scheduling Configuration

```bash
# Run once (for cron)
python lp_arbitrage.py --once

# Run as daemon with 5-minute wake-up interval
python lp_arbitrage.py --daemon --interval=300

# Environment variable alternative
POLL_INTERVAL_SECONDS=300 python lp_arbitrage.py --daemon
```

#### Daemon Wake-Up Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     DAEMON WAKE-UP CYCLE                         │
└─────────────────────────────────────────────────────────────────┘

     ┌──────────┐
     │  SLEEP   │◀────────────────────────────────────┐
     │ N mins   │                                     │
     └────┬─────┘                                     │
          │ wake up                                   │
          ▼                                           │
     ┌──────────┐                                     │
     │  FETCH   │ Query virtual price, market price  │
     │  DATA    │ Query APY, AUM (if enabled)        │
     └────┬─────┘                                     │
          │                                           │
          ▼                                           │
     ┌──────────┐     No opportunity                  │
     │ EVALUATE │─────────────────────────────────────┤
     │  SPREAD  │                                     │
     └────┬─────┘                                     │
          │ spread > threshold                        │
          ▼                                           │
     ┌──────────┐                                     │
     │  LOG TO  │ Record opportunity to history      │
     │ HISTORY  │                                     │
     └────┬─────┘                                     │
          │                                           │
          ▼                                           │
     ┌──────────┐     TRADING_MODE=whatif             │
     │  TRADE?  │─────────────────────────────────────┤
     │          │     (log only, don't execute)       │
     └────┬─────┘                                     │
          │ TRADING_MODE=live                         │
          ▼                                           │
     ┌──────────┐                                     │
     │ EXECUTE  │ Submit swap transaction             │
     │  TRADE   │                                     │
     └────┬─────┘                                     │
          │                                           │
          └───────────────────────────────────────────┘
```

---

## What-If Mode (Paper Trading)

Following the pattern from the existing trading bot (`WHAT_IF_MODE_FEATURE.md`), the LP arbitrage bot should support a **what-if mode** for safe testing.

### Configuration

```bash
# Command-line (preferred)
python lp_arbitrage.py --trading-mode=whatif

# Environment variable
TRADING_MODE=whatif python lp_arbitrage.py
```

**Precedence:** `--trading-mode` > `TRADING_MODE` env var > default (`live`)

### Behavior by Mode

| Action | `live` | `whatif` |
|--------|--------|----------|
| Fetch prices (virtual, market) | ✓ | ✓ |
| Calculate spread | ✓ | ✓ |
| Record to history | ✓ | ✓ |
| Execute swap transaction | ✓ | ✗ |
| Log "[WHAT-IF] Would trade..." | ✗ | ✓ |
| Track simulated P&L | ✗ | ✓ |

### Console Output (What-If Mode)

```
=== LP ARBITRAGE BOT ===
Platform: Jupiter JLP
Mode: WHAT-IF (no real trades)
Interval: 300 seconds

[2026-04-29 11:45:00] Wake up #1
  Virtual price: $1.2345
  Market price:  $1.2789
  Spread: +3.60% (premium)
  Action: HOLD (below sell threshold of 8%)
  
[2026-04-29 11:50:00] Wake up #2
  Virtual price: $1.2350
  Market price:  $1.3456
  Spread: +8.95% (premium)
  [WHAT-IF] Would execute SELL at $1.3456
  [HISTORY] Recorded: SELL @ $1.3456 (spread: +8.95%)

=== WHAT-IF SUMMARY ===
Total wake-ups: 24
Opportunities detected: 3
Simulated SELL orders: 2
Simulated BUY orders: 1
Simulated P&L: +$47.23 (if trades had executed)
```

---

## History Logging & Analysis

### History File Structure

Following the existing bot's `historyutil.py` pattern, store recommendations in JSON:

```
./history/
├── lp_recommendations.json     # All LP arbitrage recommendations
├── lp_snapshots.json           # Periodic price snapshots (for backtesting)
├── analysis_lp_YYYYMMDD.csv    # Daily analysis reports
└── lp_trades.json              # Actual executed trades (live mode only)
```

### Recommendation Record Schema

```json
{
  "id": "lp_rec_20260429_114500_JLP",
  "timestamp": "2026-04-29T11:45:00.000Z",
  "platform": "jupiter",
  "lp_token": "JLP",
  "virtual_price": 1.2345,
  "market_price": 1.2789,
  "spread_pct": 3.60,
  "spread_direction": "premium",
  "apy_bps": 850,
  "aum_usd": 450000000,
  "aum_cap_pct": 92.5,
  "recommendation": "HOLD",
  "trading_mode": "whatif",
  "position_usd": 0,
  "wake_up_number": 1
}
```

### LP Trade Analyzer

Create `lp_analyzer.py` (similar to `tradeanalyzer.py`) to analyze historical recommendations:

**Features:**
- Load recommendations from `lp_recommendations.json`
- Calculate what P&L would have been if trades executed
- Identify optimal threshold settings from historical data
- Compare actual spread movements to predictions
- Generate reports by time period (24h, 7d, 30d)

**Usage:**
```bash
python lp_analyzer.py                    # Full analysis
python lp_analyzer.py --period=7d        # Last 7 days
python lp_analyzer.py --platform=jupiter # Filter by platform
python lp_analyzer.py --export=csv       # Export to CSV
```

**Sample Output:**
```
=== LP ARBITRAGE ANALYSIS (Last 7 Days) ===

Platform: Jupiter JLP
Total snapshots: 2,016 (5-minute intervals)
Opportunities detected: 47

BUY opportunities (spread < -1%):
  Count: 12
  Avg spread: -2.3%
  If executed: +$234.50 (based on subsequent price movement)

SELL opportunities (spread > +8%):
  Count: 8
  Avg spread: +9.7%
  If executed: +$412.30

Optimal thresholds (backtested):
  Buy at: -1.5% (would capture 95% of profitable entries)
  Sell at: +7.0% (would capture 90% of profitable exits)

Recommendation: Current thresholds are conservative.
Consider lowering sell threshold to +7%.
```

---

## API Rate Limits & Cost Considerations

### Rate Limits by Platform

| Platform | Endpoint | Rate Limit | Cost |
|----------|----------|------------|------|
| **Jupiter (JLP)** | Solana RPC (Pool account) | ~100 req/sec (public RPC) | Free (public) or $50-200/mo (dedicated) |
| **Jupiter** | Quote API | 600 req/min | Free |
| **HyperLiquid** | `api.hyperliquid.xyz/info` | 1200 req/min | Free |
| **Drift** | Solana RPC (via driftpy) | ~100 req/sec | Free (public) or $50-200/mo (dedicated) |

### Recommended Polling Intervals

| Interval | Requests/Hour | Best For | Tradeoffs |
|----------|---------------|----------|-----------|
| **60 sec** | 60 | Active arbitrage, high volatility | Higher API usage, may hit limits |
| **300 sec (5 min)** | 12 | **Recommended for MVP** | Good balance of responsiveness and efficiency |
| **900 sec (15 min)** | 4 | Conservative monitoring | May miss short-lived opportunities |
| **3600 sec (1 hr)** | 1 | Low-frequency, yield-focused | Only for long-term premium plays |

### Cost Analysis

```
┌─────────────────────────────────────────────────────────────────┐
│              MONTHLY API COST ESTIMATE (5-min polling)          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Jupiter JLP (Solana RPC):                                      │
│    Requests: 12/hr × 24hr × 30d = 8,640/month                  │
│    Public RPC: FREE (but may throttle)                          │
│    Dedicated RPC (QuickNode/Helius): $49-99/month              │
│                                                                  │
│  HyperLiquid:                                                   │
│    Requests: 8,640/month                                        │
│    Cost: FREE (well under 1200/min limit)                       │
│                                                                  │
│  Drift:                                                         │
│    Requests: 8,640/month                                        │
│    Cost: Same as Jupiter (Solana RPC)                           │
│                                                                  │
│  ─────────────────────────────────────────────────────────────  │
│  TOTAL ESTIMATED COST:                                          │
│    Budget option: $0/month (public RPCs, accept throttling)     │
│    Reliable option: $50-100/month (dedicated Solana RPC)        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Minimizing API Calls

| Optimization | Description | Savings |
|--------------|-------------|---------|
| **Batch requests** | Fetch Pool + Custody accounts in single RPC call | ~50% |
| **Cache token metadata** | Don't re-fetch static data (addresses, decimals) | ~10% |
| **Conditional polling** | Poll more frequently during high volatility | Variable |
| **WebSocket subscriptions** | Subscribe to account changes instead of polling | ~80% (Phase 2) |

### Interval Configuration

```bash
# Conservative (low API usage)
POLL_INTERVAL_SECONDS=900 python lp_arbitrage.py --daemon

# Balanced (recommended)
POLL_INTERVAL_SECONDS=300 python lp_arbitrage.py --daemon

# Aggressive (for active trading, use dedicated RPC)
POLL_INTERVAL_SECONDS=60 python lp_arbitrage.py --daemon

# Adaptive (poll more during high volatility - Phase 2)
ADAPTIVE_POLLING=true MIN_INTERVAL=60 MAX_INTERVAL=900 python lp_arbitrage.py --daemon
```

---

### MVP Success Metrics

1. **Functionality:** Successfully executes buy/sell based on spread
2. **Profitability:** Positive returns over 30-day test period (paper trading)
3. **Reliability:** <1% missed opportunities due to bot errors
4. **Cost efficiency:** Transaction costs < 20% of gross profit

---

## Potential Shared Utilities

From the existing trading bot codebase:

| Utility | Location | Reusability |
|---------|----------|-------------|
| Jupiter API client | `dex/jupiterutil.py` | High - swap execution |
| WalletConnect | `dex/walletconnect.py` | High - wallet auth |
| Local wallet | `dex/local_wallet.py` | High - programmatic signing |
| Token cache | `dex/token_cache.py` | Medium - token metadata |
| Config patterns | `config.py` | High - env var handling |
| LLM utilities | `claudeutil.py`, etc. | Low (MVP) / Medium (Phase 3) |

---

## Phase Roadmap

### Phase 1: MVP (2-3 weeks)
- [ ] Price feed integration (virtual + market)
- [ ] Basic spread calculation
- [ ] Threshold-based buy/sell logic
- [ ] Jupiter swap execution
- [ ] Trade logging
- [ ] Dry-run mode
- [ ] Paper trading validation

### Phase 2: Enhanced Signals (2-3 weeks)
- [ ] APY tracking and correlation
- [ ] AUM cap monitoring
- [ ] Multi-signal scoring
- [ ] Position sizing logic
- [ ] Basic hedging options

### Phase 3: Production Hardening (2-3 weeks)
- [ ] Multiple data source fallbacks
- [ ] Circuit breakers
- [ ] Alerting (Discord/Telegram)
- [ ] Performance analytics dashboard
- [ ] LLM advisory mode (optional)

### Phase 4: Expansion (ongoing)
- [ ] Support additional LP tokens (Orca, Raydium)
- [ ] Cross-chain opportunities
- [ ] More sophisticated hedging

---

## References

- Jupiter Liquidity Provider: https://jup.ag/perps-earn
- Vectis Navigator Vault: Example of automated JLP strategy
- Existing DEX integration: `dex/` directory in 
