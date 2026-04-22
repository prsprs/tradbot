# Coin Categorization Feature - Design Document

## Problem Statement

The trading bot needs to filter coins by category (meme, DeFi, AI, Base ecosystem, Solana ecosystem, etc.) during discovery mode. The Coinbase API provides a list of tradeable coins but **does not include category metadata**. We need an external source for categorization.

---

## Alternatives

### 1. CoinGecko API (Free Tier)

**How it works:** Query `/coins/markets?category=meme-token` to get all coins in a category.

**Pros:**
- Comprehensive category data
- Single API call per category (efficient)
- Industry-standard source

**Cons:**
- Free tier has strict rate limits (~10-30 calls/min)
- Returns 402/429 errors frequently
- Rate limit resets are unclear (24+ hours observed)
- May require waiting between runs

**Cost:** Free (with limitations)

---

### 2. CoinGecko Pro API

**How it works:** Same as free tier but with higher rate limits.

**Pros:**
- Same comprehensive data as free tier
- Higher rate limits (500+ calls/min)
- Priority support

**Cons:**
- Paid service
- Requires API key management

**Cost:** 
- Demo: Free (30 calls/min)
- Analyst: $129/month (500 calls/min)
- Lite: $499/month (1000 calls/min)
- Pro: $999/month (unlimited)

---

### 3. CoinMarketCap API

**How it works:** Query `/cryptocurrency/category` endpoint.

**Pros:**
- Alternative to CoinGecko
- Widely used industry standard
- Good category taxonomy

**Cons:**
- Free tier: 333 credits/day (~33 category calls)
- Category endpoint may require paid tier
- Different category naming conventions

**Cost:**
- Basic: Free (limited)
- Hobbyist: $29/month
- Startup: $79/month
- Standard: $299/month

---

### 4. LunarCrush API (v4)

**How it works:** Social intelligence API with coin categorization and blockchain data.

**Key Endpoint:** `/api4/public/coins/list/v2`
- Returns up to **1000 coins per page** with pagination
- **`filter` parameter** for categories (e.g., `filter=meme-coins`)
- Each coin includes `categories` field (comma-delimited) AND `blockchains` array
- Single API call can return all meme coins!

**Example Response:**
```json
{
  "symbol": "DOGE",
  "name": "Dogecoin",
  "categories": "meme-coins,layer-1,pow",
  "blockchains": [
    {"type": "layer1", "network": "dogecoin", "address": null}
  ],
  "galaxy_score": 65.2,
  "social_volume_24h": 45000,
  "sentiment": 78
}
```

**Available Categories:** See https://lunarcrush.com/categories/cryptocurrencies
- meme-coins, layer-1, layer-2, defi, ai, gaming, etc.

**Pros:**
- ✅ **Single API call for all coins in a category** (exactly what we need!)
- ✅ Returns both category AND blockchain data
- Real-time social sentiment data (Galaxy Score, AltRank)
- Good for meme coin detection (social-driven)
- 1000 coins per page, pagination supported

**Cons:**
- Requires API key (paid)
- Less established than CoinGecko/CMC

**Cost:** 
- Individual: **$5/day or $90/month** (API access included)
- Developer/Enterprise: Contact for pricing

**Rate Limits:** Not explicitly documented, but appears generous

---

### 5. LLM Knowledge-Based Categorization

**How it works:** Pass full Coinbase coin list to LLM with category hint in prompt. LLM uses its training knowledge to identify coins in category.

**Pros:**
- No external API calls (no rate limits)
- LLM knowledge is constantly updated
- Can handle nuanced categorization
- Works offline

**Cons:**
- LLM knowledge cutoff date (may miss new coins)
- Inconsistent categorization across runs
- Adds tokens to prompt (cost)
- May hallucinate categories

**Cost:** Included in LLM API costs

---

### 6. Static Curated List (Local)

**How it works:** Maintain a JSON/Python file with coin categories.

**Pros:**
- No API calls
- Instant lookup
- Full control over categorization

**Cons:**
- Requires manual curation
- Stale quickly (meme coins are dynamic)
- Someone has to maintain it

**Cost:** Free (labor cost for maintenance)

---

### 7. Hybrid: Cached API + Fallback

**How it works:** 
1. Cache CoinGecko category data locally (refresh daily/weekly)
2. Fall back to LLM knowledge for coins not in cache

**Pros:**
- Minimizes API calls
- Handles new coins via LLM
- Best of both worlds

**Cons:**
- Implementation complexity
- Cache staleness issues
- Still requires some API access

**Cost:** Depends on refresh frequency

---

### 8. DexScreener / DexTools API

**How it works:** Query DEX-focused APIs for token metadata.

**Pros:**
- Good for new/trending tokens
- Real-time data
- Often categorizes by chain

**Cons:**
- Less comprehensive category taxonomy
- May not have "meme" category explicitly
- Rate limits vary

**Cost:** Free tier available, paid plans for higher limits

---

### 9. Polymarket Smart Money Discovery (Alternative to Categorization)

**How it works:** Instead of filtering by semantic categories (meme, DeFi), use Polymarket prediction market data to identify coins worth trading based on:
1. Which coins have active prediction markets (market existence = significant interest)
2. Smart money tracking - what top traders (>60% win rate, >$50k profit) are betting on
3. Volume and betting activity as proxy for relevance

**Key Insight:** This is NOT traditional categorization - it's **market-validated coin selection**.

**Polymarket Crypto Coverage (as of 2026):**
| Coin | Markets | Notes |
|------|---------|-------|
| BTC | 33+ | Extensive coverage |
| ETH | 21+ | Extensive coverage |
| SOL | 12+ | Good coverage |
| XRP | 11+ | Good coverage |
| DOGE | 6+ | Meme coin with markets |
| BNB | 6+ | Good coverage |
| SHIB, PEPE, BONK, WIF, FLOKI | Varies | Some meme coins have markets |

**Smart Money Discovery Flow:**
```
1. Query Polymarket for top traders (>60% win rate, >$50k profit)
2. Get their open positions in crypto markets
3. Filter for bullish positions
4. Rank coins by smart money interest
5. Cross-reference with Coinbase tradeable list
6. Result: Market-validated coin list
```

**Pros:**
- ✅ **Market-validated signal** - Real money bets, not semantic labels
- ✅ Free API (no subscription required)
- ✅ Smart money tracking adds alpha beyond categorization
- ✅ Avoids stale category data
- ✅ Coins with markets are inherently "interesting"

**Cons:**
- ❌ Limited coin coverage (only ~50-100 coins have markets)
- ❌ Not a category filter - can't say "give me all meme coins"
- ❌ Requires more complex implementation (trader tracking)
- ❌ Smart money data may require Bitquery subscription for historical analysis

**Hybrid Use Cases:**
1. **Discovery mode alternative:** Instead of "pick meme coins", use "pick coins smart money likes"
2. **Validation layer:** After LunarCrush category filter, validate with Polymarket sentiment
3. **Chain filter combo:** DEXScreener for chain + Polymarket for market interest

**Cost:** 
- Polymarket CLOB API: Free
- Bitquery (for trader analytics): $50-500/month depending on tier

---

### 10. DEXScreener + Coinbase Hybrid (Chain-Based Filtering)

**How it works:** 
1. Get full list of tradeable coins from Coinbase API
2. Query DEXScreener search API for each coin symbol
3. DEXScreener returns `chainId` (e.g., "solana", "ethereum", "base")
4. Filter Coinbase list to only coins on the desired chain

**Example DEXScreener Response:**
```json
{
  "chainId": "solana",
  "baseToken": {
    "symbol": "Bonk",
    "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
  }
}
```

**Pros:**
- **No category API needed** - chain info is readily available
- DEXScreener is free with generous rate limits (300 req/min for search)
- Real-time, accurate chain data
- Simpler scope: chain filtering is more objective than "meme" categorization
- Coinbase API works reliably (tested)

**Cons:**
- Requires one DEXScreener API call per coin symbol (could be ~500+ calls)
- Some coins may exist on multiple chains (need to decide which to use)
- Chain filtering ≠ category filtering (can't filter "meme coins on Solana")
- New coins on Coinbase may not yet be indexed by DEXScreener

**Implementation Options:**

**Option A: Query per symbol (simple)**
```
For each coin in Coinbase list:
    Search DEXScreener for symbol
    If chainId matches target chain → keep
```
- ~500 API calls at startup
- 300 req/min limit → ~2 min to process full list
- Can cache results to avoid repeated calls

**Option B: Batch with local cache**
```
1. First run: Query all symbols, save chainId to local JSON cache
2. Subsequent runs: Use cache, only query new coins
3. Refresh cache periodically (daily/weekly)
```
- Minimal API calls after first run
- Cache file size: ~50KB for 500 coins

**Rate Limits (DEXScreener):**
- Search endpoint: 300 requests/minute
- Token profiles: 60 requests/minute
- No API key required for basic endpoints

**Supported Chains:**
- solana, ethereum, base, arbitrum, polygon, bsc, avalanche, optimism, etc.

**Cost:** Free

---

## Research Findings

### Coinbase API - Blockchain Info

**Finding: Coinbase API does NOT provide blockchain/chain information.**

Tested `get_products()` response - available fields:
- `base_currency_id`, `quote_currency_id`
- `base_name`, `display_name`
- `price`, `volume_24h`
- `product_venue` (always "CBE")
- **No `chain`, `network`, or `blockchain` field**

This confirms we need an external source for chain identification.

### DEXScreener API - Chain Info

**Finding: DEXScreener provides `chainId` for all tokens.**

Tested search endpoint `https://api.dexscreener.com/latest/dex/search?q=BONK`:
- Returns `chainId: "solana"` for each trading pair
- Multiple pairs may exist (different DEXes, quote tokens)
- Primary chain is typically the first/most liquid pair

### DEXScreener API - Bulk Query Limitations

**Finding: No bulk "get all tokens" or "get all tokens by chain" endpoint.**

Tested endpoints:
- `/latest/dex/search?q=SOL` → Returns max **30 pairs**, mixed chains
- `/latest/dex/search?q=chain:solana` → Returns 0 (filter syntax not supported)
- `/token-profiles/latest/v1` → Returns 30 latest token profiles (not all tokens)
- `/token-boosts/top/v1` → Returns 30 boosted tokens only

**Conclusion:** DEXScreener requires per-symbol queries. Cannot get all tokens for a chain in one call.

**Alternative approach:** Query each Coinbase symbol individually via search, extract chainId from response. With 300 req/min rate limit and ~500 Coinbase symbols, full scan takes ~2 minutes. Cache results locally.

### DEXScreener API - Other Categorizations

**Finding: DEXScreener has "Metas" (categories) but token lists are NOT accessible via API.**

The `/metas/trending/v1` endpoint returns category metadata:

```json
{
  "name": "Meme Hall of Fame",
  "slug": "meme-hall-of-fame", 
  "description": "Established memes, enduring communities",
  "tokenCount": 53,
  "marketCap": 4169795015,
  "liquidity": 172124286.64
}
```

**Available Metas (as of testing):**
| Meta Name | Token Count | Description |
|-----------|-------------|-------------|
| Meme Hall of Fame | 53 | Established memes, enduring communities |
| AI | 54 | Artificial intelligence and agents |
| Dog | 28 | Furry friends and funny memes |
| Cat | 17 | pspspspspsp |
| TikTok | 27 | If it trends, it trades |
| Degen | 19 | Chaos, degeneracy and commitment |
| Elon Musk | 24 | All roads lead to Rocketman |
| Trump | 5 | That guy from The Apprentice |
| Chinese | 23 | 救命，我不会说中文! |
| Brainrot | 11 | Historians will struggle with this |
| Character | 12 | Crypto native characters and mascots |
| Internet Animals | 25 | Famous both online and on-chain |
| Knockoff Legends | 21 | Temu version, MS Paint edition |
| Celebrity | 6 | This has never backfired |
| NFT | 4 | JPEGs turned fungible |
| Stonks | 8 | Not financial advice |
| Slang | 6 | How do you do, fellow kids? |
| x402 | 9 | The internet-native payment protocol |

**Limitation:** No API endpoint to get the actual token list for a meta. The `tokenCount` is visible but individual tokens are not exposed.

**Other fields in pair data:**
- `labels`: DEX-specific pool types only (v2, v3, DLMM, CLMM) - **not useful for categorization**
- `dexId`: Which DEX (uniswap, raydium, meteora, etc.)
- No `category`, `tags`, or `meta` fields in search results

**Summary of DEXScreener Categorization Options:**

| Data Point | Available? | API Endpoint | Useful? |
|------------|------------|--------------|---------|
| Chain ID | ✅ Yes | `/latest/dex/search?q=SYMBOL` | ✅ Yes |
| DEX ID | ✅ Yes | `/latest/dex/search?q=SYMBOL` | Maybe (filter by DEX) |
| Pool labels | ✅ Yes | `/latest/dex/search?q=SYMBOL` | ❌ No (just v2/v3/DLMM) |
| Meta categories | ⚠️ Partial | `/metas/trending/v1` | ❌ No (no token list) |
| Token description | ✅ Yes | `/token-profiles/latest/v1` | Maybe (text analysis) |

**Conclusion:** DEXScreener is only useful for **chain-based filtering**. Category/meta data exists but token lists are not exposed via API.

---

## Comparison Matrix

| Approach | Rate Limits | Data Freshness | Cost | Category Filter | Chain Filter | Implementation |
|----------|-------------|----------------|------|-----------------|--------------|----------------|
| CoinGecko Free | Severe | Real-time | Free | ✅ Yes | ❌ No | Easy |
| CoinGecko Pro | High | Real-time | $129+/mo | ✅ Yes | ❌ No | Easy |
| CoinMarketCap | Moderate | Real-time | $29+/mo | ✅ Yes | ❌ No | Easy |
| **LunarCrush** | **Generous** | **Real-time** | **$90/mo** | **✅ Yes** | **✅ Yes** | **Easy** |
| Polymarket | Generous | Real-time | Free | ⚠️ Indirect | ❌ No | Medium |
| LLM Knowledge | None | Cutoff date | Included | ⚠️ Unreliable | ⚠️ Unreliable | Easy |
| Static List | None | Manual | Free | ✅ Yes | ✅ Yes | Easy |
| DEXScreener+Coinbase | Generous | Real-time | Free | ❌ No | ✅ Yes | Medium |

**Winner for category + chain filtering: LunarCrush at $90/month**

**Alternative approach: Polymarket Smart Money** - Not a category filter, but market-validated coin selection based on what successful traders are betting on. Free, but limited coin coverage (~50-100 coins with markets).

---

## Combined Approaches

### Option 1: LunarCrush + Polymarket (Best Signal Quality)

**Cost:** $90/month (LunarCrush) + Free (Polymarket)

**Flow:**
```
1. LunarCrush: Get all meme coins (category filter)
2. LunarCrush: Filter by chain if needed (blockchains array)
3. Cross-reference with Coinbase tradeable list
4. Polymarket: Validate with smart money sentiment
5. Result: Category-filtered, market-validated coin list
```

**Benefits:**
- Category filtering from LunarCrush
- Market validation from Polymarket
- Social sentiment (Galaxy Score) + Prediction market sentiment

### Option 2: DEXScreener + Polymarket (Free Tier)

**Cost:** Free

**Flow:**
```
1. Coinbase: Get all tradeable coins
2. DEXScreener: Filter by chain (per-symbol queries, cached)
3. Polymarket: Filter to coins with active markets OR smart money interest
4. Result: Chain-filtered, market-validated coin list
```

**Benefits:**
- No monthly cost
- Chain filtering works
- Market validation adds quality

**Limitations:**
- No semantic category filter (can't say "meme coins only")
- DEXScreener requires caching (~2 min initial scan)

### Option 3: LunarCrush + DEXScreener + Polymarket (Full Stack)

**Cost:** $90/month

**Flow:**
```
1. LunarCrush: Get meme coins with social metrics
2. DEXScreener: Verify chain for each coin
3. Polymarket: Add prediction market sentiment
4. Cross-reference with Coinbase
5. LLM: Final analysis with all signals
```

**Benefits:**
- Complete data: category + chain + social + prediction markets
- Maximum signal quality
- Redundancy if one API fails

---

## Recommended Implementation

### New Environment Variables

```python
# Blockchain filter - comma-separated list of chains (LunarCrush format)
# Examples: "solana", "ethereum", "base", "polygon", "arbitrum"
CHAINS = os.environ.get('CHAINS', '')  # Empty = no chain filtering

# Category filter - comma-separated list of LunarCrush categories
# Examples: "meme-coins", "defi", "layer-1", "ai", "gaming"
CATEGORIES = os.environ.get('CATEGORIES', '')  # Empty = no category filtering

# Polymarket filter - only analyze coins with active Polymarket prediction markets
POLYMARKET_FILTER = os.environ.get('POLYMARKET_FILTER', 'false').lower() == 'true'
```

### Implementation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COIN FILTERING PIPELINE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Step 1: Get Coinbase Tradeable Coins                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  coinbase_coins = coinbaseutil2.get_tradeable_coins()                  ││
│  │  # Returns: ['BTC', 'ETH', 'SOL', 'DOGE', 'BONK', ...]                 ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                              │                                               │
│                              ▼                                               │
│  Step 2: Apply LunarCrush Filters (if CHAINS or CATEGORIES set)             │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  If CHAINS or CATEGORIES:                                              ││
│  │    lunarcrush_coins = lunarcrushutil.get_coins(                        ││
│  │        chains=CHAINS.split(','),                                       ││
│  │        categories=CATEGORIES.split(',')                                ││
│  │    )                                                                   ││
│  │    filtered = coinbase_coins ∩ lunarcrush_coins                        ││
│  │  Else:                                                                 ││
│  │    filtered = coinbase_coins                                           ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                              │                                               │
│                              ▼                                               │
│  Step 3: Apply Polymarket Filter (if POLYMARKET_FILTER=true)                │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  If POLYMARKET_FILTER:                                                 ││
│  │    polymarket_coins = polymarketutil.get_coins_with_markets()          ││
│  │    filtered = filtered ∩ polymarket_coins                              ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                              │                                               │
│                              ▼                                               │
│  Step 4: Output                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  final_coins = filtered                                                ││
│  │  # Ready for LLM analysis or ANALYZE_COINS override                    ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### lunarcrushutil.py Implementation

```python
import os
import requests
from typing import List, Set, Optional

LUNARCRUSH_API_KEY = os.environ.get('LUNARCRUSH_API_KEY')
BASE_URL = "https://lunarcrush.com/api4/public"

class LunarCrushClient:
    def __init__(self):
        self.api_key = LUNARCRUSH_API_KEY
        if not self.api_key:
            raise ValueError("LUNARCRUSH_API_KEY environment variable required")
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
    
    def get_coins(self, 
                  chains: Optional[List[str]] = None,
                  categories: Optional[List[str]] = None) -> Set[str]:
        """Get coin symbols filtered by chains and/or categories.
        
        Args:
            chains: List of blockchain networks (e.g., ['solana', 'base'])
            categories: List of categories (e.g., ['meme-coins', 'defi'])
            
        Returns:
            Set of coin symbols matching ALL specified filters
        """
        # Build filter parameter for categories
        params = {"limit": 1000}
        if categories:
            # LunarCrush supports filter parameter for categories
            params["filter"] = categories[0]  # Primary category filter
        
        all_coins = []
        cursor = None
        
        while True:
            if cursor:
                params["cursor"] = cursor
            
            response = requests.get(
                f"{BASE_URL}/coins/list/v2",
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            coins = data.get("data", [])
            all_coins.extend(coins)
            
            cursor = data.get("cursor")
            if not cursor or len(coins) == 0:
                break
        
        # Filter results
        result = set()
        for coin in all_coins:
            symbol = coin.get("symbol", "").upper()
            coin_categories = coin.get("categories", "").split(",")
            coin_blockchains = [b.get("network", "").lower() 
                               for b in coin.get("blockchains", [])]
            
            # Check category match (if specified)
            if categories:
                if not any(cat.lower() in [c.lower() for c in coin_categories] 
                          for cat in categories):
                    continue
            
            # Check chain match (if specified)
            if chains:
                if not any(chain.lower() in coin_blockchains 
                          for chain in chains):
                    continue
            
            result.add(symbol)
        
        return result
    
    def get_available_categories(self) -> List[str]:
        """Get list of available category slugs from LunarCrush."""
        response = requests.get(
            f"{BASE_URL}/categories/list/v1",
            headers=self.headers
        )
        response.raise_for_status()
        return [c.get("slug") for c in response.json().get("data", [])]
```

### polymarketutil.py Addition

```python
def get_coins_with_markets(self) -> Set[str]:
    """Get all coin symbols that have active Polymarket prediction markets.
    
    Returns:
        Set of coin symbols (e.g., {'BTC', 'ETH', 'SOL', 'DOGE'})
    """
    # Fetch all active events
    response = requests.get(
        "https://gamma-api.polymarket.com/events",
        params={"active": "true", "closed": "false", "limit": 500}
    )
    response.raise_for_status()
    events = response.json()
    
    # Extract coins from event titles using pattern matching
    coin_patterns = [
        ('BTC', r'bitcoin|\bbtc\b'),
        ('ETH', r'ethereum|\beth\b'),
        ('SOL', r'solana|\bsol\b'),
        ('DOGE', r'dogecoin|\bdoge\b'),
        ('XRP', r'\bxrp\b'),
        ('BNB', r'\bbnb\b'),
        ('ADA', r'cardano|\bada\b'),
        ('SHIB', r'shiba|\bshib\b'),
        ('PEPE', r'\bpepe\b'),
        ('BONK', r'\bbonk\b'),
        ('WIF', r'dogwifhat|\bwif\b'),
        ('FLOKI', r'\bfloki\b'),
        ('TRUMP', r'trump.*token|trump.*coin'),
        # Add more as needed
    ]
    
    coins = set()
    for event in events:
        title = event.get("title", "").lower()
        for symbol, pattern in coin_patterns:
            if re.search(pattern, title):
                coins.add(symbol)
    
    return coins
```

### Usage Examples

```bash
# Solana meme coins only
CHAINS=solana CATEGORIES=meme-coins python geminigroundlin15.py

# Base ecosystem DeFi tokens
CHAINS=base CATEGORIES=defi python geminigroundlin15.py

# Any meme coin with Polymarket interest (market-validated)
CATEGORIES=meme-coins POLYMARKET_FILTER=true python geminigroundlin15.py

# Multi-chain: Solana OR Base meme coins
CHAINS=solana,base CATEGORIES=meme-coins python geminigroundlin15.py

# Only coins people are betting on (no category/chain filter)
POLYMARKET_FILTER=true python geminigroundlin15.py

# Combine all filters: Solana meme coins with Polymarket markets
CHAINS=solana CATEGORIES=meme-coins POLYMARKET_FILTER=true python geminigroundlin15.py
```

### Expected Output

```
=== COIN FILTERING ===
Coinbase tradeable coins: 523
Applying filters:
  CHAINS: solana
  CATEGORIES: meme-coins
  POLYMARKET_FILTER: true
LunarCrush query: chains=['solana'], categories=['meme-coins']
  → 47 coins match chain+category
Polymarket filter: 6 coins have active markets
  → BTC, ETH, SOL, DOGE, BONK, WIF
Final intersection with Coinbase: 4 coins
  → SOL, DOGE, BONK, WIF
Analyzing: ['SOL', 'DOGE', 'BONK', 'WIF']
```

### Filter Logic

| CHAINS | CATEGORIES | POLYMARKET_FILTER | Result |
|--------|------------|-------------------|--------|
| empty | empty | false | All Coinbase coins (no filtering) |
| solana | empty | false | Solana-chain coins on Coinbase |
| empty | meme-coins | false | Meme coins on Coinbase |
| solana | meme-coins | false | Solana meme coins on Coinbase |
| empty | empty | true | Only coins with Polymarket markets |
| solana | meme-coins | true | Solana meme coins WITH Polymarket markets |

### LunarCrush Known Values

**Chains (blockchains array → network field):**
- `solana`, `ethereum`, `base`, `polygon`, `arbitrum`, `avalanche`
- `binance-smart-chain`, `fantom`, `optimism`, `cronos`
- `dogecoin`, `bitcoin`, `litecoin` (native L1s)

**Categories (from /categories/list/v1):**
- `meme-coins`, `defi`, `layer-1`, `layer-2`, `ai`
- `gaming`, `nft`, `exchange-tokens`, `stablecoins`
- `pow`, `pos`, `privacy`, `metaverse`

---

## MVP Decisions

| Decision | Resolution |
|----------|------------|
| **LunarCrush Cost** | Approved (~$90/month) |
| **Caching** | No caching for MVP - real-time queries only |
| **Category Validation** | Accept any string LunarCrush supports - pass through to API |
| **Chain Validation** | Accept any string LunarCrush supports - pass through to API |
| **Parameter Design** | User can specify `CHAINS`, `CATEGORIES`, or both (or neither) |
| **Multi-chain Tokens** | User specifies preferred chain(s) via `CHAINS` parameter |
| **Fallback on Error** | Fail with error (no silent fallback) |
| **DEXScreener** | Not using for MVP |
| **CoinGecko** | Not using for MVP |
| **LLM Categorization** | Not using for MVP |

### Category/Chain Parameter Behavior

Rather than validating category and chain strings against a known list, the MVP will:
1. Pass user-provided strings directly to LunarCrush API
2. If LunarCrush returns an error (invalid category/chain), propagate that error to user
3. User can query LunarCrush `/categories/list/v1` to discover valid values

This approach:
- Avoids maintaining a duplicate list of valid values
- Automatically supports new categories/chains LunarCrush adds
- Gives user immediate feedback if they typo a value

---

## Additional MVP Decisions

| Decision | Resolution |
|----------|------------|
| **Coinbase Multi-Chain** | Moot - Coinbase handles transparently. (SOL-USD is native SOL) |
| **Polymarket Missed Coins** | Accepted risk. Include raw Polymarket event string in output for user verification |
| **Polymarket API Stability** | Accepted risk |
| **Multi-Value Logic** | OR logic - coin matches ANY specified chain/category |
| **Coinbase Filtering Log** | Yes - log which coins were filtered out due to Coinbase unavailability |

### Polymarket Output for Verification

When `POLYMARKET_FILTER=true`, output should include the raw Polymarket event titles that matched each coin:

```
=== POLYMARKET FILTER ===
Matched coins from active markets:
  BTC: "Will Bitcoin hit $100k in May 2025?"
  ETH: "Ethereum price end of April?"
  SOL: "Solana above $200 by June?"
  DOGE: "Dogecoin to $1?"
```

This allows users to verify pattern matching is working correctly (addresses false positive risk).

---

## Current State

- Coinbase API: Working (lists all tradeable coins, no chain info)
- LunarCrush: **Implemented** - requires API key ($90/month or $5/day)
- Polymarket: **Implemented** - free API with keyword matching
- CHAINS parameter: **Implemented**
- CATEGORIES parameter: **Implemented**
- POLYMARKET_FILTER parameter: **Implemented**

---

## Implementation Phases

### Phase 1: LunarCrush Integration
- [ ] Sign up for LunarCrush Individual plan
- [x] Create `lunarcrushutil.py` with `get_coins()` method
- [ ] Verify category and chain slug names
- [x] Add CHAINS and CATEGORIES environment variables
- [x] Integrate with main script coin selection flow

### Phase 2: Polymarket Filter
- [x] Add `get_coins_with_markets()` to `polymarketutil.py`
- [x] Add POLYMARKET_FILTER environment variable
- [x] Integrate as final filter in pipeline

### Phase 3: Testing & Documentation
- [ ] Test all filter combinations
- [ ] Document available categories and chains
- [ ] Add usage examples to README

---

## REVISED APPROACH: Cache-Based LunarCrush Integration

### Problem with Live API Approach

LunarCrush pricing is expensive for continuous use:
- **Daily:** $5/day
- **Monthly:** $90/month (with ARCH30: ~$63/month)
- **Annual:** ~$24/month ($288/year)

For a trading bot that runs multiple times per day, even daily billing adds up quickly.

### Solution: On-Demand Cache Refresh

Instead of live API calls, use a **cached coin database** that is refreshed on-demand:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CACHE-BASED ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  REFRESH SCRIPT (run manually when needed)                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  python refresh_coin_cache.py                                          ││
│  │                                                                        ││
│  │  1. Get all Coinbase tradeable coins                                   ││
│  │  2. For each coin, fetch LunarCrush data:                              ││
│  │     - Categories (meme-coins, defi, layer-1, etc.)                     ││
│  │     - Blockchains (solana, ethereum, base, etc.)                       ││
│  │     - Social metrics (optional: galaxy_score, alt_rank)                ││
│  │  3. Write to coin_cache.json                                           ││
│  │                                                                        ││
│  │  Cost: Only pay for LunarCrush on days you run this script             ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                              │                                               │
│                              ▼                                               │
│  CACHE FILE (coin_cache.json)                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  {                                                                     ││
│  │    "refreshed_at": "2026-04-22T00:30:00Z",                             ││
│  │    "coins": {                                                          ││
│  │      "BTC": {                                                          ││
│  │        "categories": ["layer-1", "pow"],                               ││
│  │        "blockchains": ["bitcoin"],                                     ││
│  │        "galaxy_score": 78.5                                            ││
│  │      },                                                                ││
│  │      "BONK": {                                                         ││
│  │        "categories": ["meme-coins"],                                   ││
│  │        "blockchains": ["solana"],                                      ││
│  │        "galaxy_score": 65.2                                            ││
│  │      },                                                                ││
│  │      ...                                                               ││
│  │    }                                                                   ││
│  │  }                                                                     ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                              │                                               │
│                              ▼                                               │
│  TRADING BOT (reads from cache, no LunarCrush API needed)                   │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │  python geminigroundlin15.py --categories=meme-coins --chains=solana   ││
│  │                                                                        ││
│  │  1. Load coin_cache.json                                               ││
│  │  2. Filter coins by categories/chains from cache                       ││
│  │  3. Cross-reference with live Coinbase availability                    ││
│  │  4. Apply Polymarket filter (if enabled)                               ││
│  │  5. Run LLM analysis                                                   ││
│  │                                                                        ││
│  │  Cost: $0 for LunarCrush (uses cached data)                            ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Cache File Format

**Option A: Simple JSON**
```json
{
  "refreshed_at": "2026-04-22T00:30:00Z",
  "lunarcrush_version": "v4",
  "coins": {
    "BTC": {
      "name": "Bitcoin",
      "categories": ["layer-1", "pow"],
      "blockchains": ["bitcoin"],
      "galaxy_score": 78.5,
      "alt_rank": 1
    },
    "BONK": {
      "name": "Bonk",
      "categories": ["meme-coins"],
      "blockchains": ["solana"],
      "galaxy_score": 65.2,
      "alt_rank": 156
    }
  }
}
```

**Option B: CSV (easier to inspect/edit manually)**
```csv
symbol,name,categories,blockchains,galaxy_score,alt_rank
BTC,Bitcoin,"layer-1,pow",bitcoin,78.5,1
BONK,Bonk,meme-coins,solana,65.2,156
```

### Refresh Script Usage

```bash
# Subscribe to LunarCrush for 1 day ($5)
# Run refresh script
LUNARCRUSH_API_KEY=xxx python refresh_coin_cache.py

# Output:
# Fetching Coinbase coins... 250 found
# Enriching with LunarCrush data... 
#   BTC: layer-1, pow | bitcoin
#   ETH: layer-1, pos, defi | ethereum
#   ...
# Saved to coin_cache.json (250 coins, 2026-04-22T00:30:00Z)

# Cancel LunarCrush subscription (or let daily expire)
# Trading bot runs for free using cached data
```

### Cost Comparison

| Scenario | Live API | Cache Approach |
|----------|----------|----------------|
| Run bot 4x/day for 30 days | $90/month | $5-15/month (refresh 1-3x) |
| Run bot 1x/day for 30 days | $90/month | $5/month (refresh 1x) |
| Run bot during volatile periods only | $90/month | $5/event |

### Implementation Changes

1. **New file: `refresh_coin_cache.py`**
   - Fetches Coinbase coins
   - Enriches each with LunarCrush category/chain data
   - Writes to `coin_cache.json`

2. **Modify: `lunarcrushutil.py`**
   - Add `load_cache()` function
   - Add `filter_from_cache()` function
   - Keep live API functions for refresh script

3. **Modify: `geminigroundlin15.py`**
   - Check for cache file existence
   - Use cache for filtering instead of live API
   - Warn if cache is stale (configurable threshold)

### Open Questions

| # | Question | Options | Impact |
|---|----------|---------|--------|
| 1 | **Cache file format?** | JSON vs CSV | JSON easier to parse, CSV easier to inspect |
| 2 | **Cache file location?** | Same dir as script vs `~/.tradingbot/` vs configurable | Portability vs cleanliness |
| 3 | **Stale cache warning threshold?** | 1 day, 7 days, 30 days, or no warning | User experience vs flexibility |
| 4 | **What if coin not in cache?** | Skip it, include it anyway, or error | New Coinbase listings between refreshes |
| 5 | **Include social metrics in cache?** | Just categories/chains, or also galaxy_score/alt_rank | File size vs future filtering options |
| 6 | **Handle LunarCrush API rate limits?** | Sequential with delay, batch requests, or fail fast | Refresh speed vs reliability |
| 7 | **Polymarket in refresh script too?** | Cache Polymarket data, or always query live (free) | Consistency vs freshness (markets change fast) |
| 8 | **Cache file in git?** | Yes (share categorization), No (ephemeral data) | Collaboration vs repo cleanliness |

### Recommended Defaults (pending your input)

| Question | Recommended Default | Rationale |
|----------|---------------------|-----------|
| Cache format | JSON | Easier to parse, supports nested data |
| Cache location | Project root (`./coin_cache.json`) | Simple, visible |
| Stale warning | 7 days | Balance between freshness and annoyance |
| Missing coin | Include it (no filtering applied) | Don't block new listings |
| Social metrics | Yes (galaxy_score, alt_rank) | Useful for future enhancements |
| Rate limits | Sequential, 100ms delay | Safe default |
| Polymarket | Query live (free) | Markets change too fast to cache |
| Git | Add to .gitignore | Contains API-derived data |

---

## Updated MVP Decisions

| Decision | Original | **Revised** |
|----------|----------|-------------|
| **LunarCrush Cost** | Approved (~$90/month) | **On-demand refresh (~$5-15/month)** |
| **Caching** | No caching for MVP | **Cache required for cost savings** |
| **Fallback on Error** | Fail with error | **Fall back to cache if API fails** |
