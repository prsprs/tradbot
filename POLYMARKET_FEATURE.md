# Polymarket Integration Feature Design Document

## Overview

This document outlines the design for integrating Polymarket prediction market data into the trading bot. The integration will query Polymarket for sentiment and betting activity on cryptocurrencies identified through either LLM discovery or the `ANALYZE_COINS` environment variable.

## Purpose

Polymarket is a decentralized prediction market where users bet on event outcomes. For cryptocurrencies, Polymarket offers markets on price targets, directional movements, and timeframe-based predictions. This data provides:

1. **Crowd sentiment** - Aggregated probability of price movements
2. **Betting volume** - Interest level in specific cryptocurrencies
3. **Whale activity** - Large positions that may signal informed trading

## Polymarket Crypto Markets

### Available Market Types

| Market Type | Example | Signal Value |
|-------------|---------|--------------|
| **Price Target** | "Will BTC hit $100k in April?" | Probability of reaching target |
| **Up/Down** | "Bitcoin up or down this week?" | Directional sentiment |
| **Price Range** | "ETH price range end of month?" | Expected trading range |
| **5-Minute** | Short-term micro predictions | Ultra short-term sentiment |
| **Hit Price** | "Will SOL hit $200?" | Specific level expectations |

### Supported Cryptocurrencies (as of 2026)

- Bitcoin (BTC) - 33+ markets
- Ethereum (ETH) - 21+ markets
- Solana (SOL) - 12+ markets
- XRP - 11+ markets
- Dogecoin (DOGE) - 6+ markets
- BNB - 6+ markets
- Additional meme coins may have markets

## Enhanced Discovery: Smart Money Tracking

### Overview

Instead of relying solely on LLM discovery or manual coin selection, this feature enables **discovery of coins based on successful Polymarket traders' betting activity**. By tracking wallets with high win rates and significant profits, we can identify which cryptocurrencies "smart money" is bullish on.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                   POLYMARKET SMART MONEY DISCOVERY                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 1: Identify Top Traders                                        │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Query Polymarket for wallets with:                            │ │
│  │  • Win rate > 60%                                              │ │
│  │  • Total profit > $50,000                                      │ │
│  │  • Active in last 30 days                                      │ │
│  │  • Minimum 20 resolved bets                                    │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                              ▼                                       │
│  Step 2: Track Their Crypto Bets                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  For each top trader wallet:                                   │ │
│  │  • Get open positions in crypto markets                        │ │
│  │  • Filter for bullish positions (betting on price increase)   │ │
│  │  • Weight by position size and trader win rate                │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                              ▼                                       │
│  Step 3: Aggregate & Rank Coins                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Coins ranked by smart money interest:                         │ │
│  │  1. DOGE - 8 top traders bullish, $2.1M total position        │ │
│  │  2. SOL  - 5 top traders bullish, $1.4M total position        │ │
│  │  3. BONK - 3 top traders bullish, $0.8M total position        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                              ▼                                       │
│  Step 4: Feed to Trading Bot                                         │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Use discovered coins for LLM analysis and trading             │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Environment Variables for Smart Money Discovery

```python
# Enable smart money discovery mode
POLYMARKET_DISCOVERY = os.environ.get('POLYMARKET_DISCOVERY', 'false').lower() == 'true'

# Minimum win rate for "top trader" classification (0.0 - 1.0)
POLYMARKET_MIN_WIN_RATE = float(os.environ.get('POLYMARKET_MIN_WIN_RATE', '0.60'))

# Minimum total profit for "top trader" classification (USD)
POLYMARKET_MIN_PROFIT = float(os.environ.get('POLYMARKET_MIN_PROFIT', '50000'))

# Minimum number of resolved bets for statistical significance
POLYMARKET_MIN_BETS = int(os.environ.get('POLYMARKET_MIN_BETS', '20'))

# Number of top traders to track
POLYMARKET_TOP_TRADERS = int(os.environ.get('POLYMARKET_TOP_TRADERS', '50'))

# Maximum coins to discover from smart money analysis
POLYMARKET_MAX_COINS = int(os.environ.get('POLYMARKET_MAX_COINS', '5'))
```

### Implementation

```python
class PolymarketClient:
    # ... existing methods ...
    
    def get_top_traders(self, min_win_rate: float = 0.6, 
                        min_profit: float = 50000,
                        min_bets: int = 20,
                        limit: int = 50) -> List[Dict]:
        """Identify top performing traders on Polymarket.
        
        Args:
            min_win_rate: Minimum win rate (0.0-1.0)
            min_profit: Minimum total profit in USD
            min_bets: Minimum number of resolved bets
            limit: Maximum number of traders to return
            
        Returns:
            List of trader profiles with wallet, win_rate, profit, bet_count
        """
        # Query leaderboard or analyze trade history
        # This may require Bitquery GraphQL or custom analysis
        pass
    
    def get_trader_crypto_positions(self, wallet_address: str) -> List[Dict]:
        """Get a trader's open positions in crypto markets.
        
        Args:
            wallet_address: The trader's wallet address
            
        Returns:
            List of positions with market, coin, direction, size
        """
        pass
    
    def discover_smart_money_coins(self) -> List[Dict]:
        """Discover coins that top traders are betting on.
        
        Returns:
            List of coins ranked by smart money interest, including:
            - coin_symbol: The cryptocurrency symbol
            - trader_count: Number of top traders with bullish positions
            - total_position: Combined USD value of bullish positions
            - avg_trader_win_rate: Average win rate of bullish traders
            - confidence_score: Weighted score combining all factors
        """
        top_traders = self.get_top_traders(
            min_win_rate=POLYMARKET_MIN_WIN_RATE,
            min_profit=POLYMARKET_MIN_PROFIT,
            min_bets=POLYMARKET_MIN_BETS,
            limit=POLYMARKET_TOP_TRADERS
        )
        
        # Aggregate positions by coin
        coin_interest = {}
        
        for trader in top_traders:
            positions = self.get_trader_crypto_positions(trader['wallet'])
            
            for position in positions:
                if not position['is_bullish']:
                    continue
                    
                coin = position['coin_symbol']
                if coin not in coin_interest:
                    coin_interest[coin] = {
                        'coin_symbol': coin,
                        'trader_count': 0,
                        'total_position': 0,
                        'win_rates': [],
                        'traders': []
                    }
                
                coin_interest[coin]['trader_count'] += 1
                coin_interest[coin]['total_position'] += position['size_usd']
                coin_interest[coin]['win_rates'].append(trader['win_rate'])
                coin_interest[coin]['traders'].append({
                    'wallet': trader['wallet'][:8] + '...',
                    'win_rate': trader['win_rate'],
                    'position_size': position['size_usd']
                })
        
        # Calculate confidence scores and rank
        ranked_coins = []
        for coin, data in coin_interest.items():
            avg_win_rate = sum(data['win_rates']) / len(data['win_rates'])
            
            # Confidence score weights:
            # - Number of traders (more agreement = higher confidence)
            # - Total position size (more money = higher conviction)
            # - Average win rate (better traders = higher signal quality)
            confidence = (
                (data['trader_count'] / POLYMARKET_TOP_TRADERS) * 0.3 +
                min(data['total_position'] / 1000000, 1.0) * 0.4 +
                avg_win_rate * 0.3
            )
            
            ranked_coins.append({
                'coin_symbol': coin,
                'trader_count': data['trader_count'],
                'total_position': data['total_position'],
                'avg_trader_win_rate': avg_win_rate,
                'confidence_score': confidence,
                'traders': data['traders']
            })
        
        # Sort by confidence score and return top N
        ranked_coins.sort(key=lambda x: x['confidence_score'], reverse=True)
        return ranked_coins[:POLYMARKET_MAX_COINS]
```

### Integration with Main Script

```python
# In geminigroundlin15.py

def get_coins_to_analyze() -> List[str]:
    """Determine which coins to analyze based on configuration."""
    
    # Priority 1: Explicit coin list
    if ANALYZE_COINS:
        print(f"Using specified coins: {ANALYZE_COINS}")
        return ANALYZE_COINS
    
    # Priority 2: Polymarket smart money discovery
    if POLYMARKET_DISCOVERY and polymarket_client:
        print("=== POLYMARKET SMART MONEY DISCOVERY ===")
        try:
            smart_money_coins = polymarket_client.discover_smart_money_coins()
            
            if smart_money_coins:
                print(f"Top traders are bullish on:")
                for i, coin in enumerate(smart_money_coins, 1):
                    print(f"  {i}. {coin['coin_symbol']}: "
                          f"{coin['trader_count']} traders, "
                          f"${coin['total_position']:,.0f} total position, "
                          f"{coin['avg_trader_win_rate']:.1%} avg win rate, "
                          f"confidence: {coin['confidence_score']:.2f}")
                
                coins = [c['coin_symbol'] for c in smart_money_coins]
                print(f"Analyzing: {coins}")
                return coins
            else:
                print("No smart money positions found in crypto markets")
        except Exception as e:
            print(f"Smart money discovery failed: {e}")
    
    # Priority 3: LLM discovery (default)
    print("Using LLM discovery mode")
    return None  # Triggers LLM discovery
```

### Usage Examples

```bash
# Discover coins from smart money activity
POLYMARKET_DISCOVERY=true \
  python geminigroundlin15.py

# Smart money discovery with stricter criteria
POLYMARKET_DISCOVERY=true \
  POLYMARKET_MIN_WIN_RATE=0.70 \
  POLYMARKET_MIN_PROFIT=100000 \
  python geminigroundlin15.py

# Combine with multi-LLM analysis
POLYMARKET_DISCOVERY=true \
  LLM_MODE=integrate \
  COMPARE_LLMS=gemini,claude,grok \
  python geminigroundlin15.py

# Smart money discovery + sentiment confirmation
POLYMARKET_DISCOVERY=true \
  USE_POLYMARKET=true \
  REQUIRE_POLYMARKET_BULLISH=true \
  python geminigroundlin15.py
```

### Expected Output

```
=== POLYMARKET SMART MONEY DISCOVERY ===
Analyzing 47 top traders (>60% win rate, >$50k profit)...
Top traders are bullish on:
  1. DOGE: 8 traders, $2,145,000 total position, 68.2% avg win rate, confidence: 0.78
  2. SOL: 5 traders, $1,420,000 total position, 71.5% avg win rate, confidence: 0.65
  3. BONK: 3 traders, $820,000 total position, 64.3% avg win rate, confidence: 0.48
  4. XRP: 3 traders, $650,000 total position, 62.1% avg win rate, confidence: 0.42
  5. SHIB: 2 traders, $410,000 total position, 66.8% avg win rate, confidence: 0.35
Analyzing: ['DOGE', 'SOL', 'BONK', 'XRP', 'SHIB']

--- Analyzing coin 1/5: DOGE ---
[POLYMARKET] DOGE: 72.3% bullish, $1,245,000 volume, 3 markets
[SMART MONEY] 8 top traders bullish, $2.1M positions
[PRIMARY_LLM: gemini] Analyzing DOGE...
...
```

### Top Trader Identification Methods

#### Method 1: Polymarket Leaderboard API
If Polymarket provides a leaderboard API:
```python
GET /leaderboard?sort=profit&min_bets=20
```

#### Method 2: Bitquery Historical Analysis
Query all trades and compute per-wallet statistics:
```graphql
query TopTraders {
  EVM(dataset: archive, network: polygon) {
    PredictionTrades(
      where: { Block: { Date: { after: "2025-01-01" } } }
    ) {
      Trader: Trade { Buyer }
      Count: count
      TotalVolume: sum(of: CollateralAmount)
    }
  }
}
```

#### Method 3: Third-Party Services
- **Polywhaler**: Already tracks whale wallets
- **Nansen-style labeling**: Identify smart money wallets

### Trader Scoring Algorithm

```python
def calculate_trader_score(wallet_stats: Dict) -> float:
    """Calculate a comprehensive trader score.
    
    Factors:
    - Win rate (most important)
    - Total profit (proves sustained success)
    - Number of bets (statistical significance)
    - Recency (recent activity more relevant)
    - Risk-adjusted returns (Sharpe-like ratio)
    """
    win_rate = wallet_stats['wins'] / wallet_stats['total_bets']
    profit = wallet_stats['total_profit']
    bet_count = wallet_stats['total_bets']
    days_since_active = wallet_stats['days_since_last_bet']
    avg_bet_size = wallet_stats['avg_bet_size']
    
    # Win rate score (0-40 points)
    win_score = min(win_rate * 50, 40)
    
    # Profit score (0-30 points, logarithmic)
    profit_score = min(math.log10(max(profit, 1)) * 5, 30)
    
    # Experience score (0-15 points)
    experience_score = min(bet_count / 10, 15)
    
    # Recency score (0-15 points, decays over 90 days)
    recency_score = max(15 - (days_since_active / 6), 0)
    
    return win_score + profit_score + experience_score + recency_score
```

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Trading Bot                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐     ┌──────────────────┐                      │
│  │  LLM Discovery   │     │  ANALYZE_COINS   │                      │
│  │  (meme coins)    │     │  (explicit list) │                      │
│  └────────┬─────────┘     └────────┬─────────┘                      │
│           │                        │                                 │
│           └───────────┬────────────┘                                 │
│                       ▼                                              │
│           ┌───────────────────────┐                                  │
│           │   Coin Symbol List    │                                  │
│           │   [DOGE, SHIB, PEPE]  │                                  │
│           └───────────┬───────────┘                                  │
│                       ▼                                              │
│           ┌───────────────────────┐                                  │
│           │  Polymarket Client    │◄──── polymarketutil.py          │
│           └───────────┬───────────┘                                  │
│                       │                                              │
│                       ▼                                              │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Polymarket Sentiment                         │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │  DOGE: 72% bullish, $1.2M volume, 3 active markets             │ │
│  │  SHIB: 45% bullish, $0.3M volume, 1 active market              │ │
│  │  PEPE: No markets found                                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                       │                                              │
│                       ▼                                              │
│           ┌───────────────────────┐                                  │
│           │  LLM Analysis + Buy   │                                  │
│           │  Decision Logic       │                                  │
│           └───────────────────────┘                                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │   Polymarket API      │
            │   (CLOB / GraphQL)    │
            └───────────────────────┘
```

### New Files

| File | Purpose |
|------|---------|
| `polymarketutil.py` | Polymarket API client wrapper |

### Environment Variables

```python
# Enable/disable Polymarket integration
USE_POLYMARKET = os.environ.get('USE_POLYMARKET', 'false').lower() == 'true'

# Minimum betting volume to consider market relevant (in USD)
POLYMARKET_MIN_VOLUME = float(os.environ.get('POLYMARKET_MIN_VOLUME', '10000'))

# Minimum bullish sentiment to boost buy signal (0.0 - 1.0)
POLYMARKET_BULLISH_THRESHOLD = float(os.environ.get('POLYMARKET_BULLISH_THRESHOLD', '0.6'))

# Require Polymarket confirmation before buying
REQUIRE_POLYMARKET_BULLISH = os.environ.get('REQUIRE_POLYMARKET_BULLISH', 'false').lower() == 'true'
```

## Implementation Design

### polymarketutil.py

```python
import os
import requests
from typing import Optional, Dict, List

class PolymarketClient:
    def __init__(self):
        """Initialize the Polymarket client."""
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"
        # API key may be required for some endpoints
        self.api_key = os.environ.get('POLYMARKET_API_KEY')
    
    def search_crypto_markets(self, coin_symbol: str) -> List[Dict]:
        """Search for prediction markets related to a cryptocurrency.
        
        Args:
            coin_symbol: The cryptocurrency symbol (e.g., 'DOGE', 'BTC')
            
        Returns:
            List of market dictionaries with odds, volume, and metadata
        """
        # Map common symbols to search terms
        symbol_map = {
            'BTC': ['Bitcoin', 'BTC'],
            'ETH': ['Ethereum', 'ETH'],
            'DOGE': ['Dogecoin', 'DOGE'],
            'SHIB': ['Shiba', 'SHIB'],
            'SOL': ['Solana', 'SOL'],
            'XRP': ['XRP', 'Ripple'],
            'PEPE': ['PEPE', 'Pepe'],
            'BONK': ['BONK', 'Bonk'],
            'WIF': ['WIF', 'dogwifhat'],
            'FLOKI': ['FLOKI', 'Floki'],
        }
        
        search_terms = symbol_map.get(coin_symbol.upper(), [coin_symbol])
        markets = []
        
        for term in search_terms:
            # Query Polymarket API for markets
            # Implementation depends on API structure
            pass
        
        return markets
    
    def get_market_odds(self, market_id: str) -> Dict:
        """Get current odds for a specific market.
        
        Returns:
            Dict with 'yes_price', 'no_price', 'volume', 'liquidity'
        """
        pass
    
    def get_bullish_sentiment(self, coin_symbol: str) -> Optional[Dict]:
        """Calculate aggregate bullish sentiment for a coin.
        
        Analyzes all active markets for the coin and returns:
        - Overall bullish probability (weighted by volume)
        - Total betting volume
        - Number of active markets
        - Whale activity indicators
        
        Returns:
            Dict with sentiment metrics or None if no markets found
        """
        markets = self.search_crypto_markets(coin_symbol)
        
        if not markets:
            return None
        
        total_volume = 0
        weighted_bullish = 0
        
        for market in markets:
            # Determine if market is bullish-oriented
            # (e.g., "Will X go up?" vs "Will X go down?")
            volume = market.get('volume', 0)
            bullish_prob = self._extract_bullish_probability(market)
            
            weighted_bullish += bullish_prob * volume
            total_volume += volume
        
        if total_volume == 0:
            return None
        
        return {
            'coin': coin_symbol,
            'bullish_probability': weighted_bullish / total_volume,
            'total_volume': total_volume,
            'market_count': len(markets),
            'markets': markets
        }
    
    def _extract_bullish_probability(self, market: Dict) -> float:
        """Extract bullish probability from market data.
        
        Handles different market types:
        - "Up/Down" markets: Use 'Up' probability
        - "Hit price" markets: If target > current, use 'Yes' probability
        - "Price range" markets: Calculate based on range vs current
        """
        pass
    
    def get_whale_trades(self, coin_symbol: str, min_size: float = 10000) -> List[Dict]:
        """Get recent large trades for coin-related markets.
        
        Args:
            coin_symbol: The cryptocurrency symbol
            min_size: Minimum trade size in USD
            
        Returns:
            List of whale trades with direction, size, and timestamp
        """
        pass
```

### Integration with Main Script

```python
# In geminigroundlin15.py

from polymarketutil import PolymarketClient

# Initialize client if enabled
polymarket_client = None
if USE_POLYMARKET:
    try:
        polymarket_client = PolymarketClient()
        print("Polymarket integration enabled")
    except Exception as e:
        print(f"Failed to initialize Polymarket client: {e}")

def get_polymarket_sentiment(coin_symbol: str) -> Optional[Dict]:
    """Get Polymarket sentiment for a coin."""
    if not polymarket_client:
        return None
    
    try:
        sentiment = polymarket_client.get_bullish_sentiment(coin_symbol)
        if sentiment:
            print(f"  [POLYMARKET] {coin_symbol}: {sentiment['bullish_probability']:.1%} bullish, "
                  f"${sentiment['total_volume']:,.0f} volume, {sentiment['market_count']} markets")
        else:
            print(f"  [POLYMARKET] {coin_symbol}: No active markets found")
        return sentiment
    except Exception as e:
        print(f"  [POLYMARKET] Error getting sentiment for {coin_symbol}: {e}")
        return None

def should_buy_with_polymarket(coin_symbol: str, llm_recommendation: str) -> bool:
    """Determine if we should buy based on LLM + Polymarket signals.
    
    Args:
        coin_symbol: The coin to evaluate
        llm_recommendation: The LLM's recommendation (BUY/SELL/HOLD)
        
    Returns:
        True if we should proceed with buy, False otherwise
    """
    if llm_recommendation != 'BUY':
        return False
    
    if not USE_POLYMARKET:
        return True  # No Polymarket check, trust LLM
    
    sentiment = get_polymarket_sentiment(coin_symbol)
    
    if sentiment is None:
        # No Polymarket data available
        if REQUIRE_POLYMARKET_BULLISH:
            print(f"  [POLYMARKET] No data for {coin_symbol}, skipping buy (REQUIRE_POLYMARKET_BULLISH=true)")
            return False
        return True
    
    # Check volume threshold
    if sentiment['total_volume'] < POLYMARKET_MIN_VOLUME:
        print(f"  [POLYMARKET] Low volume (${sentiment['total_volume']:,.0f}), treating as no data")
        if REQUIRE_POLYMARKET_BULLISH:
            return False
        return True
    
    # Check bullish threshold
    if sentiment['bullish_probability'] >= POLYMARKET_BULLISH_THRESHOLD:
        print(f"  [POLYMARKET] ✓ Bullish confirmation ({sentiment['bullish_probability']:.1%} >= {POLYMARKET_BULLISH_THRESHOLD:.1%})")
        return True
    else:
        print(f"  [POLYMARKET] ✗ Not bullish enough ({sentiment['bullish_probability']:.1%} < {POLYMARKET_BULLISH_THRESHOLD:.1%})")
        if REQUIRE_POLYMARKET_BULLISH:
            return False
        return True  # Still buy if not required
```

### Enhanced LLM Prompts

When Polymarket data is available, include it in the LLM analysis:

```python
def get_enhanced_prompt_with_polymarket(coin_symbol: str, base_prompt: str) -> str:
    """Enhance LLM prompt with Polymarket sentiment data."""
    if not USE_POLYMARKET or not polymarket_client:
        return base_prompt
    
    sentiment = polymarket_client.get_bullish_sentiment(coin_symbol)
    
    if sentiment is None:
        return base_prompt
    
    polymarket_context = f"""

Additionally, consider the following prediction market data from Polymarket:
- Bullish Sentiment: {sentiment['bullish_probability']:.1%} of bettors expect price increase
- Betting Volume: ${sentiment['total_volume']:,.0f} in active crypto markets
- Active Markets: {sentiment['market_count']} prediction markets

This represents real-money bets from market participants on the cryptocurrency's direction.
"""
    
    return base_prompt + polymarket_context
```

## Usage Examples

### Basic Usage
```bash
# Enable Polymarket integration
USE_POLYMARKET=true python geminigroundlin15.py
```

### With Coin Selection
```bash
# Check Polymarket sentiment for specific coins
USE_POLYMARKET=true \
  ANALYZE_COINS=BTC,ETH,DOGE \
  python geminigroundlin15.py
```

### Require Polymarket Confirmation
```bash
# Only buy if Polymarket sentiment is bullish
USE_POLYMARKET=true \
  REQUIRE_POLYMARKET_BULLISH=true \
  POLYMARKET_BULLISH_THRESHOLD=0.65 \
  python geminigroundlin15.py
```

### With Multi-LLM Integration
```bash
# Combine LLM consensus with Polymarket sentiment
USE_POLYMARKET=true \
  LLM_MODE=integrate \
  COMPARE_LLMS=gemini,claude,grok \
  REQUIRE_CONSENSUS=true \
  REQUIRE_POLYMARKET_BULLISH=true \
  python geminigroundlin15.py
```

## Expected Output

```
=== COIN CHOICE MODE ===
Using specified coins: ['DOGE', 'SHIB', 'BONK']

--- Analyzing coin 1/3: DOGE ---
[POLYMARKET] DOGE: 72.3% bullish, $1,245,000 volume, 3 markets
[PRIMARY_LLM: gemini] Analyzing DOGE...
[COMPARISON] gemini: BUY, claude: BUY, grok: BUY | Agree: True
[POLYMARKET] ✓ Bullish confirmation (72.3% >= 60.0%)
Executing buy for DOGE...

--- Analyzing coin 2/3: SHIB ---
[POLYMARKET] SHIB: 48.2% bullish, $320,000 volume, 1 market
[PRIMARY_LLM: gemini] Analyzing SHIB...
[COMPARISON] gemini: BUY, claude: HOLD, grok: BUY | Agree: False
[POLYMARKET] ✗ Not bullish enough (48.2% < 60.0%)
Skipping SHIB (REQUIRE_POLYMARKET_BULLISH=true)

--- Analyzing coin 3/3: BONK ---
[POLYMARKET] BONK: No active markets found
[PRIMARY_LLM: gemini] Analyzing BONK...
[COMPARISON] gemini: BUY, claude: BUY, grok: HOLD | Agree: False
[POLYMARKET] No data for BONK, skipping buy (REQUIRE_POLYMARKET_BULLISH=true)

==================================================
LLM MODE: integrate
PRIMARY LLM: gemini
COIN CHOICE: DOGE, SHIB, BONK (specified)
POLYMARKET: Enabled (threshold: 60%, require: true)
Coins to buy: ['DOGE']
==================================================
```

## API Options

### Option 1: Polymarket CLOB API (Official)

```python
# Direct REST API
base_url = "https://clob.polymarket.com"

# Get markets
GET /markets
GET /markets/{market_id}

# Get orderbook
GET /book?token_id={token_id}

# Get trades
GET /trades?market={market_id}
```

**Pros**: Official, reliable, real-time data
**Cons**: May require API key, limited search

### Option 2: Gamma API (Market Discovery)

```python
# Market search and discovery
base_url = "https://gamma-api.polymarket.com"

# Search markets
GET /markets?tag=crypto
GET /markets?search={query}
```

**Pros**: Better search, categorization
**Cons**: May have rate limits

### Option 3: Bitquery GraphQL (Analytics)

```graphql
query {
  EVM(dataset: realtime, network: polygon) {
    PredictionTrades(
      where: {
        CollateralAmount: { ge: "10000" }
      }
    ) {
      Trade {
        Market
        Amount
        Side
      }
    }
  }
}
```

**Pros**: Whale tracking, historical data
**Cons**: Requires Bitquery subscription

### Option 4: Polywhaler/Third-Party

Use existing whale tracking services via their APIs or scraping.

**Pros**: Pre-built whale detection
**Cons**: Third-party dependency, may be unreliable

## Open Questions

### API & Authentication

1. **Does Polymarket CLOB API require authentication?**
   - Some endpoints may be public, others may require API key
   - Need to verify which endpoints we need and their auth requirements

2. **What are the rate limits for Polymarket APIs?**
   - How many requests per minute/hour?
   - Do we need to implement caching?

3. **Which API is best for our use case?**
   - CLOB API for real-time data?
   - Gamma API for market discovery?
   - Combination of both?

### Market Coverage

4. **Which meme coins have active Polymarket markets?**
   - Major coins (BTC, ETH, SOL) have markets
   - Do smaller meme coins (PEPE, BONK, WIF) have markets?
   - How do we handle coins with no markets?

5. **How frequently are new crypto markets created?**
   - Are markets created dynamically based on trending coins?
   - Or only for established cryptocurrencies?

6. **What is the typical liquidity/volume for crypto markets?**
   - Is $10,000 a reasonable minimum volume threshold?
   - How does volume vary by coin?

### Data Interpretation

7. **How do we interpret different market types?**
   - "Up/Down" markets are straightforward
   - "Hit price" markets require knowing current price
   - "Price range" markets need more complex analysis

8. **How do we aggregate sentiment across multiple markets?**
   - Volume-weighted average?
   - Most recent market only?
   - Time-decay weighting?

9. **Should we consider market resolution timeframe?**
   - Markets expiring in 1 hour vs 1 month
   - Short-term markets more relevant for day trading?

### Whale Detection

10. **Can we identify whale wallets on Polymarket?**
    - Is wallet data public?
    - Can we track specific large traders?

11. **How do we distinguish informed traders from noise?**
    - Historical accuracy of whale bets?
    - Wallet age/history?

### Integration Logic

12. **How should Polymarket sentiment weight against LLM recommendation?**
    - Veto power (REQUIRE_POLYMARKET_BULLISH)?
    - Tiebreaker in LLM disagreement?
    - Confidence booster?

13. **Should Polymarket data be fed to LLMs for analysis?**
    - Include in prompt as additional context?
    - Or keep as separate decision layer?

14. **How do we handle conflicting signals?**
    - LLM says BUY but Polymarket is bearish
    - LLM says HOLD but Polymarket is very bullish

### Technical Implementation

15. **Should we cache Polymarket data?**
    - Markets don't change rapidly
    - Could reduce API calls and latency

16. **How do we handle Polymarket API downtime?**
    - Fallback to LLM-only mode?
    - Retry logic?

17. **Should Polymarket queries run in parallel with LLM calls?**
    - Could reduce total latency
    - Need to handle async properly

### Legal & Compliance

18. **Are there legal considerations for using prediction market data?**
    - Polymarket operates in a regulatory gray area
    - Does using their data have implications?

19. **Should we log/store Polymarket data?**
    - For history analysis feature?
    - Privacy/data retention concerns?

### Smart Money Discovery

20. **How do we access trader wallet performance data?**
    - Does Polymarket expose a leaderboard API?
    - Do we need Bitquery subscription for historical trade analysis?
    - Can Polywhaler API provide this data?

21. **What defines a "top trader" for our purposes?**
    - Is 60% win rate the right threshold?
    - Should profit threshold be absolute ($50k) or relative?
    - How many resolved bets needed for statistical significance?

22. **How do we determine if a position is "bullish" on a coin?**
    - "Up/Down" markets are clear
    - "Hit price $X" requires knowing current price and direction
    - How to handle complex market structures?

23. **How fresh does trader data need to be?**
    - Should we only consider traders active in last 30 days?
    - How often to refresh the top trader list?
    - Real-time position tracking vs periodic snapshots?

24. **How do we handle traders with positions in multiple coins?**
    - Count each position separately?
    - Weight by position size relative to trader's portfolio?

25. **Should we track trader entry/exit timing?**
    - When did top traders enter their positions?
    - Are they adding or reducing positions recently?

26. **How do we validate the smart money signal quality?**
    - Backtest against historical crypto prices?
    - Track accuracy of discovered coins over time?

27. **What if top traders have no crypto positions?**
    - Fallback to LLM discovery?
    - Fallback to general market sentiment?
    - Alert user and skip?

28. **Should we weight recent trades higher than older positions?**
    - Time-decay for position relevance?
    - New positions vs long-held positions?

## Implementation Phases

### Phase 1: Basic Integration
- [ ] Create `polymarketutil.py` with market search
- [ ] Implement `get_bullish_sentiment()` for major coins
- [ ] Add `USE_POLYMARKET` environment variable
- [ ] Basic console output of sentiment data

### Phase 2: Decision Integration
- [ ] Implement `should_buy_with_polymarket()` logic
- [ ] Add threshold configuration variables
- [ ] Integrate with buy decision flow
- [ ] Update summary output

### Phase 3: LLM Enhancement
- [ ] Feed Polymarket data to LLM prompts
- [ ] Add Polymarket context to all LLM utilities
- [ ] Test impact on LLM recommendations

### Phase 4: Smart Money Discovery
- [ ] Implement `get_top_traders()` method
- [ ] Implement `get_trader_crypto_positions()` method
- [ ] Implement `discover_smart_money_coins()` method
- [ ] Add `POLYMARKET_DISCOVERY` environment variable
- [ ] Integrate with coin selection flow (priority over LLM discovery)
- [ ] Add trader scoring algorithm

### Phase 5: Advanced Features
- [ ] Real-time whale trade tracking
- [ ] Historical sentiment analysis
- [ ] Market creation alerts
- [ ] Caching layer
- [ ] Backtest smart money signals

## Dependencies

```
# requirements.txt additions
requests>=2.28.0      # For API calls
# polymarket-py        # Official SDK if available
```

## References

- Polymarket Docs: https://docs.polymarket.com/
- Polymarket Crypto: https://polymarket.com/crypto
- Bitquery API: https://docs.bitquery.io/docs/examples/polymarket-api/
- Polywhaler: https://www.polywhaler.com/
