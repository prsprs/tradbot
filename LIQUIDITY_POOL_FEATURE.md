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

## The Core Strategy: Premium/Discount Arbitrage

### Two Prices, One Opportunity

| Price Type | Definition | Behavior |
|------------|------------|----------|
| **Virtual Price** | Total value of underlying assets (SOL, BTC, ETH, USDC, USDT) ÷ total LP token supply | Grows steadily as fees reinvest |
| **Market Price** | Price on DEXs (e.g., Jupiter Swap) | Fluctuates based on supply/demand |

### Profit Mechanics

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     PREMIUM/DISCOUNT ARBITRAGE CYCLE                     │
└─────────────────────────────────────────────────────────────────────────┘

     Market Price
          │
    ┌─────┴─────┐
    │  PREMIUM  │ ◄─── SELL HERE (market > virtual)
    │   +5-15%  │      Triggered by: AUM cap hit, FOMO, high volatility
    ├───────────┤
    │  VIRTUAL  │ ◄─── Fair value baseline
    │   PRICE   │
    ├───────────┤
    │ DISCOUNT  │ ◄─── BUY HERE (market < virtual or near parity)
    │   -2-5%   │      Triggered by: Market calm, panic selling, low demand
    └───────────┘
```

### Key Triggers

| Event | Expected Effect | Bot Action |
|-------|-----------------|------------|
| **AUM cap hit** | Cannot mint new JLP → scarcity → premium spikes | SELL |
| **High volatility** | More trading fees → higher APY → demand spike | Prepare to SELL |
| **Market crash** | Panic selling of JLP → discount | BUY (with caution) |
| **Low APY period** | Stable, low demand → prices near virtual | BUY |
| **AUM cap lifted** | New minting available → premium collapses | Avoid buying at premium |

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

14. **Which platform for MVP?** (TBD — pending further evaluation)
    - HyperLiquid: Simplest API, highest Sharpe, but different chain (not Solana)
    - Drift hJLP: Python SDK, automated hedging, but recent exploit history
    - Jupiter: Most liquid, but requires IDL parsing and manual hedging
    - See MVP Platform Choice section for detailed comparison.

15. **Multi-platform: How to manage cross-chain complexity?** ✅ DECIDED
    - **MVP Decision:** Start with HyperLiquid only (if chosen), but design architecture for easy introduction of other platforms.
    - Abstract wallet/bridge logic so adding Solana-based platforms (Drift, Jupiter) is straightforward in Phase 2.
    - Multi-platform diversification: Phase 2.

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

Based on Sharpe ratio analysis, **three MVP paths** are viable depending on risk tolerance:

| MVP Option | Platform | Sharpe | Complexity | Delta Hedging | Lock-up |
|------------|----------|--------|------------|---------------|---------|
| **Option A: Simplest** | HyperLiquid (HLP) | ~4.06 | Low | Not needed (USDC-based) | 4 days |
| **Option B: Solana-native** | Drift hJLP | ~2.5+ | Medium | Automated by protocol | 13 days |
| **Option C: Largest spreads** | Jupiter (JLP) | ~2.93 | High | Must build yourself | None |

**Recommendation:** Start with **Option A (HyperLiquid)** for MVP because:
- Highest risk-adjusted return (Sharpe ~4.06)
- No delta hedging complexity — bot focuses purely on premium/discount
- Simple REST API (no IDL parsing)
- 4-day lock-up is acceptable for initial testing

**If Solana-native is required:** Use **Option B (Drift hJLP)** — the protocol handles hedging automatically, simplifying bot logic despite the longer lock-up.

**Defer Option C (Jupiter JLP)** until Phase 2 when hedging logic can be properly implemented.

### MVP Features

| Feature | Included | Notes |
|---------|----------|-------|
| Price spread monitoring | ✓ | Core functionality |
| Basic buy/sell execution | ✓ | Via platform API (HLP REST or Drift SDK) |
| Configurable thresholds | ✓ | Buy/sell spread triggers |
| Logging & history | ✓ | Track all trades for analysis |
| Delta hedging | ✗ | Not needed for HLP; automated for Drift hJLP |
| APY monitoring | ✗ | Phase 2 |
| AUM cap detection | ✗ | Phase 2 (Jupiter-specific) |
| Multi-platform | ✗ | Phase 3 |

### MVP Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MVP COMPONENTS                            │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Price Feed  │────▶│   Strategy   │────▶│  Executor    │
│              │     │   Engine     │     │              │
├──────────────┤     ├──────────────┤     ├──────────────┤
│ • Virtual    │     │ • Spread     │     │ • Jupiter    │
│   price API  │     │   calculator │     │   swap API   │
│ • Market     │     │ • Threshold  │     │ • Wallet     │
│   price API  │     │   checker    │     │   (WC/local) │
│              │     │ • Position   │     │ • Tx signing │
│              │     │   tracker    │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   Logger     │
                     ├──────────────┤
                     │ • Trade log  │
                     │ • P&L track  │
                     │ • Alerts     │
                     └──────────────┘
```

### MVP Configuration

```
# Proposed environment variables (or config file)

LP_TOKEN=JLP                    # Which LP token to trade
BUY_THRESHOLD=-0.01             # Buy when market < virtual by 1%
SELL_THRESHOLD=0.08             # Sell when market > virtual by 8%
MAX_POSITION_USD=1000           # Maximum USD value to hold
MIN_TRADE_USD=50                # Minimum trade size
POLL_INTERVAL_SECONDS=300       # How often to check prices (see rate limit section)
TRADING_MODE=whatif             # whatif or live
HISTORY_DIR=./history/          # Where to store recommendation history
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
- Existing DEX integration: `dex/` directory in this repo
