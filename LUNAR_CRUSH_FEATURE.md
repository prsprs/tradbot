# LunarCrush Integration Feature - Design Document

## Overview

LunarCrush provides social intelligence data for cryptocurrencies, tracking social media activity across Twitter/X, Reddit, YouTube, TikTok, and other platforms. This document explores how to integrate LunarCrush to enhance the trading bot's capabilities.

**Cost:** $24/month (Individual plan with API access)

---

## Use Cases

### 1. Coin Categorization & Filtering (Primary Use Case)

**Problem:** Coinbase API doesn't provide category (meme, DeFi, AI) or blockchain data. CoinGecko rate limits make it unusable.

**LunarCrush Solution:**
```
GET /api4/public/coins/list/v2?filter=meme-coins&limit=1000
```

Returns all coins matching category with:
- `symbol`, `name`
- `categories` (comma-delimited: "meme-coins,layer-1,pow")
- `blockchains` array with network info

**New Environment Variables:**
```python
# Filter by blockchain (LunarCrush network names)
CHAINS = os.environ.get('CHAINS', '')  # e.g., "solana,base"

# Filter by category (LunarCrush category slugs)
CATEGORIES = os.environ.get('CATEGORIES', '')  # e.g., "meme-coins,defi"
```

**Implementation Flow:**
```
1. Coinbase: Get all tradeable coins
2. LunarCrush: Query /coins/list/v2 with category filter
3. Filter results by chain if CHAINS specified
4. Intersect with Coinbase list
5. Return filtered coins for analysis
```

**Usage Examples:**
```bash
# Solana meme coins
CHAINS=solana CATEGORIES=meme-coins python crypto_trading_bot.py

# Base DeFi tokens
CHAINS=base CATEGORIES=defi python crypto_trading_bot.py

# Multi-chain meme coins
CHAINS=solana,base,ethereum CATEGORIES=meme-coins python crypto_trading_bot.py
```

**Benefit:** Single API call replaces 500+ per-symbol queries

See `COIN_CATEGORIZATION_FEATURE.md` for full implementation details.

---

### 2. Social Sentiment Enhancement for LLM Prompts

**Problem:** LLMs rely on training data cutoff and web search, which may miss real-time social trends.

**LunarCrush Solution:** Inject live social metrics into LLM prompts.

**Key Metrics:**
| Metric | Description | Use Case |
|--------|-------------|----------|
| `galaxy_score` | Proprietary 0-100 score combining price + social | Overall health indicator |
| `alt_rank` | Relative performance vs all assets | Identify outperformers |
| `sentiment` | % positive posts (0-100) | Bullish/bearish gauge |
| `social_volume_24h` | Total posts mentioning coin | Trending detection |
| `interactions_24h` | Likes, shares, comments | Engagement level |
| `social_dominance` | % of total crypto social volume | Market attention share |

**Example Prompt Enhancement:**
```
Current social metrics for PEPE:
- Galaxy Score: 72/100 (up from 65 yesterday)
- Sentiment: 81% positive
- Social Volume: 45,000 posts (24h)
- Alt Rank: #12 (was #45 yesterday)

Based on these social signals and your analysis...
```

**Benefit:** LLM has concrete, real-time social data instead of guessing

---

### 3. Pre-Filter Candidates by Social Momentum

**Problem:** Discovery mode asks LLM to pick from all meme coins. Many have no social activity.

**LunarCrush Solution:** Pre-filter to coins with active social engagement.

**Approach:**
```python
# Get meme coins sorted by social volume
coins = lunarcrush.get_coins(filter="meme-coins", sort="social_volume_24h", limit=50)

# Only consider coins with meaningful social activity
active_coins = [c for c in coins if c['social_volume_24h'] > 1000]
```

**Benefit:** LLM only evaluates socially active coins, improving signal quality

---

### 4. Trending Detection & Alerts

**Problem:** Meme coins can spike on social trends before price moves.

**LunarCrush Solution:** Monitor for social volume spikes.

**Key Indicators:**
- `galaxy_score` increase > 10 points in 24h
- `alt_rank` improvement > 20 positions
- `social_volume_24h` increase > 200%
- `sentiment` shift from negative to positive

**Implementation Options:**
- Poll `/coins/list/v2` periodically (hourly)
- Compare current vs cached metrics
- Alert on significant changes

---

### 5. Influencer Activity Tracking

**Problem:** Meme coins often move on influencer posts (Elon Musk, etc.)

**LunarCrush Solution:**
```
GET /api4/public/coin/:symbol/influencers/v1
GET /api4/public/creator/:network/:id/v1
```

Returns top influencers discussing a coin and their recent activity.

**Use Case:** Weight coins higher if major influencers recently posted about them

---

### 6. Validate LLM Recommendations

**Problem:** LLM might recommend coins that are socially dead.

**LunarCrush Solution:** After LLM picks coins, validate with social data.

**Validation Checks:**
- Does coin have `social_volume_24h` > threshold?
- Is `sentiment` positive (> 50%)?
- Is `galaxy_score` above baseline?

**Action:** Warn or skip coins failing validation

---

## Integration Approaches

### Approach A: Lightweight - Category & Chain Filter Only (Recommended Start)

**Scope:** Use LunarCrush for coin categorization with CHAINS and CATEGORIES parameters

**Implementation:**
1. Add `LUNARCRUSH_API_KEY` environment variable
2. Create `lunarcrushutil.py` with `get_coins(chains, categories)` method
3. Add `CHAINS` and `CATEGORIES` environment variables
4. Integrate into coin selection pipeline (after Coinbase, before Polymarket filter)
5. No changes to LLM prompts

**Environment Variables:**
```python
LUNARCRUSH_API_KEY = os.environ.get('LUNARCRUSH_API_KEY')
CHAINS = os.environ.get('CHAINS', '')  # e.g., "solana,base"
CATEGORIES = os.environ.get('CATEGORIES', '')  # e.g., "meme-coins"
```

**Effort:** Low (1-2 hours)
**Value:** Solves immediate categorization problem with flexible filtering

---

### Approach B: Moderate - Social Context in Prompts

**Scope:** Category filter + inject social metrics into LLM prompts

**Implementation:**
1. Everything in Approach A
2. Add `get_social_metrics(symbols)` function
3. Modify `sendRecommendationRequest()` to include social data
4. Update prompt template with social context section

**Example Prompt Addition:**
```
Here are the current social metrics for the candidate coins:
DOGE: Galaxy=65, Sentiment=72%, Volume=120K posts
PEPE: Galaxy=78, Sentiment=85%, Volume=89K posts
SHIB: Galaxy=45, Sentiment=51%, Volume=34K posts
```

**Effort:** Medium (3-4 hours)
**Value:** LLM makes more informed decisions

---

### Approach C: Full - Social Intelligence Layer

**Scope:** Deep integration with pre-filtering, validation, and trending alerts

**Implementation:**
1. Everything in Approach A and B
2. Pre-filter discovery candidates by social activity
3. Post-validate LLM recommendations
4. Add `--min-social-volume` and `--min-galaxy-score` arguments
5. Optional: Trending alert mode

**Effort:** High (6-8 hours)
**Value:** Maximum signal quality, reduced bad recommendations

---

### Approach D: Standalone Social Scorer

**Scope:** Run LunarCrush as separate scoring pass

**Implementation:**
1. After LLM consensus, query LunarCrush for social data
2. Display social metrics alongside recommendation
3. User decides whether to act based on combined info

**Example Output:**
```
=== CONSENSUS REACHED ===
Recommended: PEPE

Social Intelligence (LunarCrush):
  Galaxy Score: 78/100 ⬆️ (+13 from yesterday)
  Sentiment: 85% positive
  Social Volume: 89,000 posts (24h)
  Alt Rank: #8 (improved 22 positions)
  
Proceed with trade? [y/n]
```

**Effort:** Low-Medium (2-3 hours)
**Value:** Informative without changing decision logic

---

## Data Caching Strategy

**LunarCrush data refresh rates:**
- Price/market data: Real-time
- Social metrics: Updated every few seconds
- Categories: Stable (cache for days)

**Recommended Caching:**
| Data Type | Cache Duration | Refresh Trigger |
|-----------|---------------|-----------------|
| Category list | 24 hours | Startup or daily |
| Coin list (category) | 1 hour | Per discovery run |
| Social metrics | 5 minutes | Per coin check |
| Influencer data | 1 hour | On demand |

**Cache Storage:** JSON file or in-memory dict (no database needed)

---

## API Endpoints Reference

### Core Endpoints

| Endpoint | Description | Rate Limit |
|----------|-------------|------------|
| `/coins/list/v2` | All coins with metrics, filterable | Generous |
| `/coin/:symbol/v1` | Single coin detail | Generous |
| `/coin/:symbol/time-series/v1` | Historical metrics | Generous |
| `/categories/list/v1` | Available categories | Generous |

### Social Endpoints

| Endpoint | Description |
|----------|-------------|
| `/coin/:symbol/influencers/v1` | Top influencers for coin |
| `/coin/:symbol/posts/v1` | Recent social posts |
| `/creators/list/v1` | Trending creators |

### Example Requests

**Get meme coins:**
```bash
curl -H "Authorization: Bearer $API_KEY" \
  "https://lunarcrush.com/api4/public/coins/list/v2?filter=meme-coins&limit=100"
```

**Get single coin metrics:**
```bash
curl -H "Authorization: Bearer $API_KEY" \
  "https://lunarcrush.com/api4/public/coin/PEPE/v1"
```

---

## Open Questions

### Technical

1. **Rate limits:** What are the exact rate limits for the $24/month plan? Documentation is unclear.

2. **Coin coverage:** Does LunarCrush track all Coinbase-listed coins? Need to verify overlap.

3. **Category accuracy:** How does LunarCrush categorize coins? Is "meme-coins" comprehensive?

4. **API stability:** How reliable is the API? What's the uptime SLA?

5. **Data latency:** How quickly does social data update after a viral post?

### Product

6. **Decision weight:** How much should social metrics influence buy/sell decisions vs price/technical analysis?

7. **Threshold tuning:** What `galaxy_score` or `social_volume` thresholds indicate a good opportunity?

8. **False positives:** Can social pumps be manipulation (bots, paid shills)? How to detect?

9. **Correlation:** Does high social activity actually predict price movement for meme coins?

### Business

10. **ROI:** Does $24/month pay for itself in better trade decisions?

11. **Alternatives:** Should we also evaluate Santiment, The TIE, or other social analytics?

12. **Free tier:** Is there a free tier or trial to test before committing?

---

## Recommended Implementation Path

### Phase 1: Validate & Prototype (Week 1)
1. Sign up for LunarCrush ($24/month or trial if available)
2. Test API manually - verify meme-coins category matches expectations
3. Check overlap with Coinbase coin list
4. Implement basic `lunarcrushutil.py` with `get_coins_by_category()`

### Phase 2: Category Integration (Week 1-2)
1. Replace CoinGecko calls with LunarCrush
2. Add `--coin-category` argument using LunarCrush data
3. Test discovery mode with category filter

### Phase 3: Social Enhancement (Week 2-3)
1. Add social metrics to LLM prompts (Approach B)
2. A/B test: Compare recommendations with/without social context
3. Tune based on results

### Phase 4: Advanced Features (Future)
1. Pre-filtering by social activity
2. Post-validation of recommendations
3. Trending alerts
4. Historical backtesting with social data

---

## Current State

- LunarCrush API: Not integrated (requires $24/month subscription)
- API Key: Not obtained
- `CHAINS` parameter: Designed, not implemented
- `CATEGORIES` parameter: Designed, not implemented
- `POLYMARKET_FILTER` parameter: Designed, not implemented (see `POLYMARKET_FEATURE.md`)
- Social data in prompts: None

**Next Step:** Sign up for LunarCrush Individual plan and implement `lunarcrushutil.py`

---

## Appendix: Sample API Response

**GET /coins/list/v2?filter=meme-coins&limit=3**

```json
{
  "config": {
    "sort": "market_cap_rank",
    "filter": "meme-coins",
    "limit": 3,
    "total_rows": 342
  },
  "data": [
    {
      "id": 2,
      "symbol": "DOGE",
      "name": "Dogecoin",
      "price": 0.1523,
      "market_cap": 22145678901,
      "market_cap_rank": 8,
      "galaxy_score": 65.2,
      "alt_rank": 45,
      "sentiment": 72,
      "social_volume_24h": 120543,
      "interactions_24h": 45678901,
      "social_dominance": 8.5,
      "categories": "meme-coins,layer-1,pow",
      "blockchains": [
        {"type": "layer1", "network": "dogecoin", "address": null}
      ]
    },
    {
      "id": 456,
      "symbol": "SHIB",
      "name": "Shiba Inu",
      "price": 0.00001234,
      "market_cap": 7234567890,
      "market_cap_rank": 15,
      "galaxy_score": 58.1,
      "alt_rank": 67,
      "sentiment": 68,
      "social_volume_24h": 89234,
      "interactions_24h": 23456789,
      "social_dominance": 4.2,
      "categories": "meme-coins,ethereum-ecosystem",
      "blockchains": [
        {"type": "token", "network": "ethereum", "address": "0x95ad..."}
      ]
    },
    {
      "id": 789,
      "symbol": "PEPE",
      "name": "Pepe",
      "price": 0.00000892,
      "market_cap": 3456789012,
      "market_cap_rank": 23,
      "galaxy_score": 78.4,
      "alt_rank": 12,
      "sentiment": 85,
      "social_volume_24h": 156789,
      "interactions_24h": 67890123,
      "social_dominance": 6.8,
      "categories": "meme-coins,ethereum-ecosystem",
      "blockchains": [
        {"type": "token", "network": "ethereum", "address": "0x6982..."}
      ]
    }
  ]
}
```
