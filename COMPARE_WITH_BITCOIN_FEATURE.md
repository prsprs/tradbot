# COMPARE_WITH_BITCOIN Feature Design Document

## Overview

Many altcoins exhibit high correlation with Bitcoin's price movements—rising when Bitcoin rises and falling when Bitcoin falls. This raises a fundamental question: **Is the potential upside of a given altcoin sufficient to justify the additional risk compared to simply investing in Bitcoin?**

This feature introduces a `COMPARE_WITH_BITCOIN` analysis mode that evaluates whether an altcoin recommendation warrants action, or whether the safer choice would be to allocate the same capital to Bitcoin.

## Problem Statement

### The Correlation Challenge

- **Beta Relationship**: Most altcoins have a beta > 1 relative to Bitcoin, meaning they amplify Bitcoin's movements (both up and down)
- **Asymmetric Risk**: Altcoins carry additional risks (project failure, regulatory targeting, liquidity issues) that Bitcoin does not
- **Opportunity Cost**: Capital invested in an underperforming altcoin could have been invested in Bitcoin
- **False Signals**: A "BUY" recommendation on an altcoin during a Bitcoin bull run may simply reflect market-wide momentum rather than altcoin-specific alpha

### Current Gap

The trading bot currently evaluates altcoins in isolation. A recommendation to BUY PEPE doesn't consider whether:
1. Bitcoin itself might be the better investment
2. The altcoin's expected return justifies its additional risk
3. The altcoin is merely riding Bitcoin's coattails

## Proposed Solution

### Feature Modes

```
COMPARE_WITH_BITCOIN=off       # Default: no comparison (current behavior)
COMPARE_WITH_BITCOIN=advisory  # Add BTC comparison to output, but don't change recommendations
COMPARE_WITH_BITCOIN=gated     # Only recommend altcoin if it passes BTC comparison threshold
COMPARE_WITH_BITCOIN=hybrid    # Recommend BTC allocation percentage alongside altcoin
```

### Analysis Methods

#### Method 1: Risk-Adjusted Return Comparison

Compare expected returns using a risk-adjusted metric.

**Approach:**
```
Altcoin Sharpe-like Ratio = (Expected Altcoin Return - Risk-Free Rate) / Altcoin Volatility
Bitcoin Sharpe-like Ratio = (Expected Bitcoin Return - Risk-Free Rate) / Bitcoin Volatility

Recommendation: Altcoin only if Altcoin_Ratio > Bitcoin_Ratio * THRESHOLD
```

**Pros:**
- Accounts for volatility differences
- Standard financial metric

**Cons:**
- Requires historical volatility calculation
- "Expected return" is speculative
- Short-term volatility may not reflect true risk

#### Method 2: Beta-Adjusted Alpha Analysis

Determine if the altcoin provides alpha (excess return) beyond its Bitcoin beta exposure.

**Approach:**
```
1. Calculate altcoin's beta to Bitcoin over rolling window
2. Compute expected return if altcoin simply tracked BTC: Beta * BTC_Return
3. Estimate altcoin's actual expected return from LLM analysis
4. Alpha = Actual_Expected_Return - Beta_Expected_Return

Recommendation: Altcoin only if Alpha > ALPHA_THRESHOLD
```

**Pros:**
- Directly measures value-add over Bitcoin exposure
- Academically grounded (CAPM-like)

**Cons:**
- Beta is unstable over short periods
- LLM "expected return" is qualitative, not quantitative

#### Method 3: Correlation-Gated Recommendations

Only recommend altcoins when their price action is decoupling from Bitcoin.

**Approach:**
```
1. Calculate rolling correlation between altcoin and Bitcoin (e.g., 24h, 7d)
2. If correlation > 0.9: Recommend Bitcoin instead (altcoin is just tracking BTC)
3. If correlation < 0.7: Allow altcoin recommendation (showing independent movement)
4. Between 0.7-0.9: Apply additional scrutiny
```

**Pros:**
- Simple to implement
- Captures regime changes (altcoin seasons vs. BTC dominance)

**Cons:**
- Correlation is backward-looking
- May miss early breakouts

#### Method 4: Relative Strength Analysis

Compare the altcoin's performance relative to Bitcoin over multiple timeframes.

**Approach:**
```
RS_24h = Altcoin_Change_24h / BTC_Change_24h
RS_7d = Altcoin_Change_7d / BTC_Change_7d
RS_30d = Altcoin_Change_30d / BTC_Change_30d

Composite_RS = weighted_average(RS_24h, RS_7d, RS_30d)

Recommendation: Altcoin only if Composite_RS > 1.0 + OUTPERFORMANCE_THRESHOLD
```

**Pros:**
- Intuitive: "Is the altcoin beating Bitcoin?"
- Multiple timeframes reduce noise

**Cons:**
- Past outperformance doesn't guarantee future
- Ignores absolute returns (both could be negative)

#### Method 5: LLM-Based Comparative Analysis

Ask LLMs to directly compare the altcoin opportunity against Bitcoin.

**Approach:**
```
Prompt: "Given the current market conditions and analysis of {ALTCOIN}, would a 
sophisticated investor be better served investing in {ALTCOIN} or allocating the 
same capital to Bitcoin? Consider:
- Risk-adjusted returns
- Correlation dynamics
- Project-specific catalysts vs. macro Bitcoin drivers
- Liquidity and execution risk

Provide your recommendation as: PREFER_ALTCOIN, PREFER_BITCOIN, or NEUTRAL"
```

**Pros:**
- Leverages LLM's synthesis capabilities
- Can incorporate qualitative factors
- Integrates naturally with existing multi-LLM architecture

**Cons:**
- LLM may not have accurate price/correlation data
- Adds latency and cost
- Requires careful prompt engineering

#### Method 6: Kelly Criterion Comparison

Use Kelly Criterion to determine optimal position sizing, then compare.

**Approach:**
```
Kelly_Altcoin = (Win_Prob_Altcoin * Win_Size - Loss_Prob_Altcoin * Loss_Size) / Win_Size
Kelly_Bitcoin = (Win_Prob_BTC * Win_Size - Loss_Prob_BTC * Loss_Size) / Win_Size

Recommendation: Altcoin only if Kelly_Altcoin > Kelly_Bitcoin
```

**Pros:**
- Mathematically optimal for bankroll growth
- Incorporates both probability and magnitude

**Cons:**
- Requires probability estimates (from historical accuracy?)
- Assumes repeated betting (may not apply to single trades)

#### Method 7: Parallel Analysis with Head-to-Head Comparison (Recommended)

Analyze Bitcoin using the exact same LLM pipeline as altcoins, then feed both analyses to LLMs for a direct head-to-head comparison. **Only triggered when the altcoin receives a BUY recommendation.**

**Approach:**
```
Phase 1: Standard Altcoin Analysis (existing flow)
  - Run altcoin through full LLM pipeline
  - If recommendation != BUY: Skip BTC comparison, proceed as normal
  - If recommendation == BUY: Continue to Phase 2

Phase 2: Bitcoin Analysis (parallel pipeline)
  - Run BTC through identical LLM queries used for altcoin
  - Use same prompts: trend check, Google Trends data, etc.
  - Collect BTC recommendation and full analysis text

Phase 3: Head-to-Head Comparison
  - Feed LLMs both the altcoin analysis AND the Bitcoin analysis
  - Prompt: "Given these two analyses, would you recommend buying {ALTCOIN} 
    over BTC? Consider the risk/reward of each."
  - Collect: PREFER_ALTCOIN, PREFER_BTC, or EQUIVALENT
  
Phase 4: Final Decision
  - If PREFER_ALTCOIN: Execute altcoin BUY
  - If PREFER_BTC: Block altcoin, optionally execute BTC BUY
  - If EQUIVALENT: Use tiebreaker logic or user preference
```

**Example Prompt (Phase 3):**
```
You previously analyzed two investment opportunities. Here are your findings:

---BEGIN ALTCOIN ANALYSIS ({ALTCOIN})---
{altcoin_analysis_text}
Recommendation: BUY
---END ALTCOIN ANALYSIS---

---BEGIN BITCOIN ANALYSIS---
{bitcoin_analysis_text}
Recommendation: {btc_recommendation}
---END BITCOIN ANALYSIS---

Given these analyses, if you could only choose one investment right now, 
would you recommend buying {ALTCOIN} or Bitcoin?

Consider:
- Expected short-term appreciation potential
- Risk levels (altcoin-specific risks vs. Bitcoin's relative stability)
- Current market conditions affecting each asset
- Whether {ALTCOIN}'s potential upside justifies its additional risk

Respond with: PREFER_ALTCOIN, PREFER_BTC, or EQUIVALENT

Then explain your reasoning briefly.
```

**Integration with Multi-LLM Modes:**
```
Compare Mode:
  - Each LLM does head-to-head comparison independently
  - Final decision based on majority preference

Integrate Mode:
  - Round 1: All LLMs analyze altcoin AND Bitcoin independently
  - Round 2: All LLMs see peer analyses for BOTH assets
  - Round 3: Head-to-head comparison with full context
```

**Pros:**
- Uses existing, proven LLM analysis pipeline
- Apples-to-apples comparison (same methodology for both assets)
- LLMs have full context from actual analysis, not just summary metrics
- Only adds overhead for BUY recommendations (most actionable case)
- Leverages multi-LLM consensus for the comparison decision
- Can reuse Bitcoin analysis across multiple altcoin comparisons in same session

**Cons:**
- Doubles LLM API calls for BUY recommendations
- Adds latency (Bitcoin analysis + comparison phase)
- Bitcoin analysis may be redundant if already bullish/bearish market
- Requires caching strategy for Bitcoin analysis reuse

**Optimization: Bitcoin Analysis Caching:**
```python
# Cache Bitcoin analysis for reuse within session
BTC_ANALYSIS_CACHE_TTL = 300  # 5 minutes

def get_bitcoin_analysis(use_trend_check=True):
    if cache.is_valid('btc_analysis'):
        return cache.get('btc_analysis')
    
    # Run full pipeline on BTC
    btc_analysis = run_llm_pipeline('BTC', use_trend_check)
    cache.set('btc_analysis', btc_analysis, ttl=BTC_ANALYSIS_CACHE_TTL)
    return btc_analysis
```

## Implementation Architecture

### New Configuration Options

```python
# Environment variables
COMPARE_WITH_BITCOIN = os.environ.get('COMPARE_WITH_BITCOIN', 'off')
BTC_COMPARISON_METHOD = os.environ.get('BTC_COMPARISON_METHOD', 'relative_strength')
BTC_OUTPERFORMANCE_THRESHOLD = float(os.environ.get('BTC_OUTPERFORMANCE_THRESHOLD', '0.1'))  # 10%
BTC_CORRELATION_CEILING = float(os.environ.get('BTC_CORRELATION_CEILING', '0.85'))
```

### New Data Requirements

| Data Point | Source | Update Frequency |
|------------|--------|------------------|
| Bitcoin current price | Coinbase/CoinGecko | Real-time |
| Bitcoin 24h/7d/30d change | CoinGecko API | Per-analysis |
| Altcoin-BTC correlation | Calculated from price history | Daily |
| Altcoin beta to BTC | Calculated from returns | Weekly |
| BTC dominance % | CoinGecko/CoinMarketCap | Per-analysis |

### Output Format

**Advisory Mode Example:**
```
[RECOMMENDATION] PEPE: BUY
[BTC COMPARISON] 
  - PEPE 24h change: +5.2% vs BTC +2.1% (RS: 2.48)
  - PEPE-BTC correlation (7d): 0.82
  - Analysis: PEPE showing relative strength, outperforming BTC by 3.1%
  - Advisory: Altcoin opportunity appears justified
```

**Gated Mode Example:**
```
[RECOMMENDATION] SHIB: BUY → BLOCKED (BTC preferred)
[BTC COMPARISON]
  - SHIB 24h change: +1.8% vs BTC +2.1% (RS: 0.86)
  - SHIB-BTC correlation (7d): 0.94
  - Analysis: SHIB underperforming BTC with high correlation
  - Action: Consider BTC allocation instead
```

**Hybrid Mode Example:**
```
[RECOMMENDATION] DOGE: BUY
[BTC COMPARISON]
  - Suggested allocation: 60% DOGE, 40% BTC
  - Rationale: DOGE shows moderate alpha but elevated correlation
```

## Data Flow

```
┌─────────────────┐
│ Altcoin Analysis│
│ (existing flow) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│ BTC Comparison  │────▶│ Fetch BTC Data   │
│ Gate            │     │ - Current price  │
└────────┬────────┘     │ - Historical     │
         │              │ - Correlation    │
         │              └──────────────────┘
         ▼
┌─────────────────┐
│ Apply Comparison│
│ Method(s)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Final Output    │
│ with BTC context│
└─────────────────┘
```

## Recording and Analysis

### Extended Recommendation Record

```json
{
  "id": "rec_20260417_123456_PEPE",
  "coin_symbol": "PEPE",
  "recommendation": "BUY",
  "btc_comparison": {
    "btc_price_at_rec": 72500.00,
    "altcoin_btc_correlation_7d": 0.78,
    "relative_strength_24h": 1.85,
    "comparison_result": "PREFER_ALTCOIN",
    "was_gated": false
  }
}
```

### Trade Analyzer Enhancements

Compare altcoin performance vs. what would have happened with Bitcoin:

```
=== BTC COMPARISON ANALYSIS ===
Recommendations where altcoin outperformed BTC: 12/20 (60%)
Average altcoin return: +4.2%
Average BTC return (same period): +2.8%
Alpha generated: +1.4%

Recommendations where BTC would have been better: 8/20 (40%)
Average opportunity cost: -1.8%
```

## Open Questions

### Fundamental Questions

1. **Time Horizon Mismatch**: The bot optimizes for short-term appreciation, but altcoin alpha may only materialize over longer periods. How do we reconcile this?

2. **BTC as Benchmark vs. BTC as Alternative**: Should we treat Bitcoin as a benchmark (comparing returns) or as a mutually exclusive alternative (choose one)?

3. **Risk Tolerance**: Should the comparison account for user-defined risk tolerance? A risk-averse user might prefer BTC even with lower expected returns.

4. **Market Regime Detection**: Altcoin outperformance is highly regime-dependent (alt season vs. BTC dominance). Should we detect and adapt to regimes?

### Technical Questions

5. **Correlation Window**: What's the optimal lookback period for correlation calculation? Too short = noisy, too long = stale.

6. **Multiple Comparisons**: If analyzing multiple altcoins, should we compare each to BTC independently, or rank all options including BTC?

7. **Execution Timing**: If we recommend BTC over an altcoin, should we execute a BTC buy, or simply abstain?

8. **Stablecoin Alternative**: Should we also compare against holding stablecoins (USDC) during uncertain conditions?

### Integration Questions

9. **LLM Prompt Integration**: Should BTC comparison data be fed to LLMs as context, or kept as a separate post-processing step?

10. **Consensus Impact**: In integrate mode, if some LLMs prefer BTC and others prefer the altcoin, how do we resolve?

11. **Discovery Mode**: Should BTC comparison affect which coins are discovered, or only the final recommendation?

### Validation Questions

12. **Backtesting**: How do we backtest this feature given we don't have historical "what if BTC" data in recommendations.json?

13. **Success Metrics**: What metric defines success? Beating BTC? Positive absolute returns? Risk-adjusted returns?

14. **Threshold Tuning**: How do we determine optimal thresholds (correlation ceiling, outperformance minimum) without overfitting?

## Implementation Phases

### Phase 1: Data Collection
- Add BTC price tracking to recommendations
- Calculate and store correlation metrics
- No behavioral changes

### Phase 2: Advisory Mode
- Implement relative strength analysis
- Add BTC comparison output
- Recommendations unchanged

### Phase 3: Gated Mode
- Implement recommendation blocking based on BTC comparison
- Add configuration options
- Track blocked recommendations

### Phase 4: LLM Integration
- Add comparative prompts
- Integrate BTC context into multi-LLM flow
- Hybrid allocation recommendations

## Related Features

- **HISTORY_ANALYSIS_FEATURE.md**: Trade analyzer could track BTC comparison accuracy
- **POLYMARKET_FEATURE.md**: Market sentiment on BTC dominance could inform comparison
- **WHALE_ALERT_INTEGRATION_FEATURE.md**: Large BTC movements could trigger comparison mode

## References

- Bitcoin Dominance Index
- Altcoin Season Index
- CAPM (Capital Asset Pricing Model)
- Kelly Criterion for position sizing
- Relative Strength Index (RSI) concepts applied to cross-asset comparison
