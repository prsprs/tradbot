# Stock Trading Feature Design Document

## Overview

This document outlines the design considerations for extending the trading bot to support stock trading via Coinbase's stock trading platform. Coinbase launched stock trading in 2025, allowing users to trade US equities alongside cryptocurrency.

## Current State

The trading bot currently:
- Uses Coinbase Advanced Trade API via `coinbase-advanced-py` SDK
- Trades cryptocurrency pairs (e.g., `BTC-USD`, `DOGE-USD`)
- Uses LLM prompts optimized for meme coin discovery and analysis
- Assumes 24/7 market availability

## Key Differences: Crypto vs Stocks

| Aspect | Cryptocurrency | Stocks |
|--------|---------------|--------|
| Market Hours | 24/7/365 | 9:30 AM - 4:00 PM ET (weekdays) |
| Settlement | Instant/near-instant | T+1 (next business day) |
| Product ID Format | `BTC-USD`, `DOGE-USD` | `AAPL-USD`, `TSLA-USD` (TBD) |
| Fractional Trading | Yes | Yes (on Coinbase) |
| Volatility Profile | High, unpredictable | Lower, earnings-driven |
| Data Sources | Social media, whale alerts | Earnings, SEC filings, news |
| Regulation | Varies by jurisdiction | SEC regulated |

## API Considerations

### Current API Usage (coinbaseutil2.py)

```python
from coinbase.rest import RESTClient

client.get_product(product_id)      # Get product info
client.market_order_buy(...)        # Place buy order
client.market_order_sell(...)       # Place sell order
```

### Potential API Changes for Stocks

Coinbase may:
1. **Extend existing API** - Same endpoints, different product IDs
2. **Create separate endpoints** - `/api/v3/stocks/...` vs `/api/v3/crypto/...`
3. **Require different SDK** - New package for stock trading

### New Environment Variables

```python
# Asset type selection
ASSET_TYPE = os.environ.get('ASSET_TYPE', 'crypto')  # 'crypto' or 'stock'

# Stock-specific settings
STOCK_SYMBOLS = os.environ.get('STOCK_SYMBOLS', '')  # e.g., 'AAPL,TSLA,NVDA'
RESPECT_MARKET_HOURS = os.environ.get('RESPECT_MARKET_HOURS', 'true')
```

## LLM Query Changes

### Current Crypto Discovery Prompt

```
What 3 cryptocurrency meme coins listed on the coinbase exchange would a 
sophisticated trading bot designed for short-term appreciation recommend 
buying right now? Once you have the top choices, number them and show me 
which of the coins chosen show the most positive social media trends in 
the last 4 hours. Put 3 plus signs around these choices at the end of 
your response.
```

### Proposed Stock Discovery Prompt

```
What 3 stocks listed on US exchanges would a sophisticated trading bot 
designed for short-term appreciation recommend buying right now? Focus on 
stocks with:
- Strong recent momentum
- Positive earnings surprises or upcoming catalysts
- High trading volume relative to average
- Favorable analyst sentiment shifts

Once you have the top choices, number them and show me which of the stocks 
chosen show the most positive news sentiment and social media trends in 
the last 24 hours. Put 3 plus signs around these choices at the end of 
your response.
```

### Current Crypto Trend Check Prompt

```
Based on analysis of recent data from Google Trends, would a sophisticated 
trading bot designed for short-term appreciation recommend buying, selling, 
or holding the meme coin with symbol {coin_symbol} right now?
```

### Proposed Stock Trend Check Prompt

```
Based on analysis of recent news, analyst ratings, and market sentiment, 
would a sophisticated trading bot designed for short-term appreciation 
recommend buying, selling, or holding the stock with symbol {stock_symbol} 
right now?

Consider:
- Recent price action and technical indicators
- Analyst upgrades/downgrades in the past week
- Upcoming earnings or significant events
- Sector momentum and macro factors
- Options flow and institutional activity

Conclude your analysis with a left angle bracket, followed by two asterisks, 
followed by the stock symbol being analyzed, followed by a dash, followed 
by the string PRS, followed by another dash, followed by the recommendation 
expressed as either the keyword BUY, SELL, or HOLD, followed by two 
asterisks, followed by a right angle bracket
```

### Current Coin Check Prompt

```
Would a sophisticated trading bot designed for short-term appreciation 
recommend buying, selling, or holding the meme coin with symbol {coin_symbol} 
right now?
```

### Proposed Stock Check Prompt

```
Would a sophisticated trading bot designed for short-term appreciation 
recommend buying, selling, or holding the stock with symbol {stock_symbol} 
right now?

Analyze:
- Current price relative to 52-week range
- Recent volume patterns
- News catalysts (earnings, product launches, FDA approvals, etc.)
- Technical support/resistance levels
- Short interest and days to cover

Conclude your analysis with a left angle bracket, followed by two asterisks, 
followed by the stock symbol being analyzed, followed by a dash, followed 
by the string PRS, followed by another dash, followed by the recommendation 
expressed as either the keyword BUY, SELL, or HOLD, followed by two 
asterisks, followed by a right angle bracket
```

## Implementation Design

### 1. Asset Type Configuration

```python
# In geminigroundlin15.py
ASSET_TYPE = os.environ.get('ASSET_TYPE', 'crypto').lower()

def get_discovery_prompt():
    if ASSET_TYPE == 'stock':
        return STOCK_DISCOVERY_PROMPT
    return CRYPTO_DISCOVERY_PROMPT

def get_trend_check_prompt(symbol):
    if ASSET_TYPE == 'stock':
        return STOCK_TREND_CHECK_PROMPT.format(stock_symbol=symbol)
    return CRYPTO_TREND_CHECK_PROMPT.format(coin_symbol=symbol)
```

### 2. Market Hours Handling

```python
import datetime
import pytz

def is_market_open():
    """Check if US stock market is currently open."""
    if ASSET_TYPE != 'stock':
        return True  # Crypto is 24/7
    
    eastern = pytz.timezone('US/Eastern')
    now = datetime.datetime.now(eastern)
    
    # Check if weekend
    if now.weekday() >= 5:
        return False
    
    # Check market hours (9:30 AM - 4:00 PM ET)
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return market_open <= now <= market_close

def wait_for_market_open():
    """Wait until market opens if trading stocks outside market hours."""
    if RESPECT_MARKET_HOURS and not is_market_open():
        print("Market is closed. Waiting for market to open...")
        # Calculate time until market opens
        # ... implementation details ...
```

### 3. Product ID Handling

```python
def get_product_id(symbol):
    """Convert symbol to Coinbase product ID format."""
    if ASSET_TYPE == 'stock':
        # Stock format TBD - might be AAPL-USD or STOCK:AAPL
        return f"{symbol}-USD"  # Placeholder
    return f"{symbol}-USD"  # Crypto format
```

### 4. LLM Utility Updates

Each LLM utility file would need updated prompts:

```python
# In claudeutil.py, openaiutil.py, grokutil.py, perplexityutil.py

def send_recommendation_request(self, asset_type='crypto'):
    if asset_type == 'stock':
        prompt = self.stock_discovery_prompt
    else:
        prompt = self.crypto_discovery_prompt
    # ... rest of implementation
```

## Data Sources for Stocks

### Real-Time Data (LLM Web Search)
- Yahoo Finance
- MarketWatch
- Bloomberg
- CNBC
- Seeking Alpha

### Additional Integrations (Future)
- SEC EDGAR filings
- Earnings calendars
- Analyst ratings aggregators
- Options flow data (Unusual Whales, etc.)

## Comparison with Crypto Features

| Feature | Crypto Support | Stock Support (Proposed) |
|---------|---------------|-------------------------|
| LLM Discovery | ✅ | 🔄 New prompts needed |
| Trend Check | ✅ | 🔄 New prompts needed |
| Coin/Stock Check | ✅ | 🔄 New prompts needed |
| Compare Mode | ✅ | ✅ Works as-is |
| Integrate Mode | ✅ | ✅ Works as-is |
| PRIMARY_LLM | ✅ | ✅ Works as-is |
| ANALYZE_COINS/STOCKS | ✅ | 🔄 Rename to ANALYZE_SYMBOLS |
| Whale Alerts | 📋 Designed | ❌ Not applicable |
| History Analysis | 📋 Designed | ✅ Works as-is |
| Market Hours | N/A (24/7) | 🔄 New feature needed |

## Usage Examples

### Stock Discovery Mode
```bash
ASSET_TYPE=stock python geminigroundlin15.py
```

### Analyze Specific Stocks
```bash
ASSET_TYPE=stock ANALYZE_COINS=AAPL,TSLA,NVDA python geminigroundlin15.py
```

### Stock with Multi-LLM Compare
```bash
ASSET_TYPE=stock \
  ANALYZE_COINS=AAPL,MSFT \
  LLM_MODE=compare \
  COMPARE_LLMS=gemini,claude,grok \
  python geminigroundlin15.py
```

### Mixed Mode (Future)
```bash
# Analyze both crypto and stocks in same session
ASSET_TYPE=mixed \
  ANALYZE_CRYPTO=BTC,ETH \
  ANALYZE_STOCKS=AAPL,TSLA \
  python geminigroundlin15.py
```

## Open Questions

### API & Integration

1. **Does Coinbase Advanced Trade API support stocks?**
   - Need to verify if `coinbase-advanced-py` SDK will work for stocks
   - May require SDK update or new package

2. **What is the product ID format for stocks?**
   - Is it `AAPL-USD` like crypto, or a different format?
   - How are different share classes handled (e.g., GOOGL vs GOOG)?

3. **Are there different rate limits for stock vs crypto APIs?**
   - Crypto APIs often have generous limits
   - Stock APIs may have stricter requirements

4. **How does fractional share trading work via API?**
   - Minimum order sizes?
   - Precision requirements?

### Market Hours & Timing

5. **Should the bot queue orders for market open?**
   - Pre-market analysis, execute at open?
   - Or only run during market hours?

6. **How to handle extended hours trading?**
   - Pre-market (4:00 AM - 9:30 AM ET)
   - After-hours (4:00 PM - 8:00 PM ET)
   - Different liquidity and spread considerations

7. **Should analysis happen outside market hours?**
   - Analyze overnight, execute at open?
   - Or real-time analysis during trading hours only?

### LLM Query Optimization

8. **What timeframe should stock analysis focus on?**
   - Day trading (minutes to hours)?
   - Swing trading (days to weeks)?
   - Should this be configurable?

9. **Which data sources are most valuable for LLM stock analysis?**
   - News sentiment vs technical analysis?
   - Earnings data vs analyst ratings?

10. **Should prompts include specific technical indicators?**
    - RSI, MACD, moving averages?
    - Or let LLM decide what's relevant?

### Regulatory & Compliance

11. **Are there pattern day trader (PDT) rule implications?**
    - $25K minimum for frequent trading
    - Should the bot track day trades?

12. **How to handle stock halts and circuit breakers?**
    - Error handling for halted stocks?
    - Automatic retry logic?

13. **Tax reporting differences between crypto and stocks?**
    - Wash sale rules apply to stocks, not crypto
    - Should the bot avoid wash sales?

### Architecture

14. **Should stock and crypto trading be in the same script?**
    - Pros: Unified codebase, shared LLM logic
    - Cons: Complexity, different execution patterns

15. **How to handle symbol conflicts?**
    - What if a crypto and stock have same symbol?
    - Namespace prefixes (CRYPTO:BTC vs STOCK:AAPL)?

16. **Should there be a separate history file for stocks?**
    - `crypto_history.json` vs `stock_history.json`?
    - Or unified `trading_history.json` with asset type field?

## Implementation Phases

### Phase 1: API Verification
- [ ] Confirm Coinbase stock API availability
- [ ] Test product ID format for stocks
- [ ] Verify order placement works for stocks

### Phase 2: Core Implementation
- [ ] Add ASSET_TYPE environment variable
- [ ] Create stock-specific prompt templates
- [ ] Update LLM utility files with stock prompts
- [ ] Implement market hours checking

### Phase 3: Enhanced Features
- [ ] Add pre-market/after-hours support
- [ ] Implement order queuing for market open
- [ ] Add stock-specific data sources

### Phase 4: Testing & Refinement
- [ ] Paper trading with stocks
- [ ] Compare LLM accuracy for stocks vs crypto
- [ ] Optimize prompts based on results
