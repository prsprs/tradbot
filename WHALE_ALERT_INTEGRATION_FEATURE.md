# Whale Alert Integration Feature Design Document

## Overview

This document describes the design for integrating whale transaction data from the Whale Alert API into the trading bot. Whale transactions—large cryptocurrency movements by major holders—are often leading indicators for price volatility and can provide valuable context for trading decisions.

## Goals

1. Fetch real-time whale transaction data from Whale Alert API
2. Filter and format transaction data relevant to coins being analyzed
3. Inject whale context into LLM prompts for enhanced trading recommendations
4. Track exchange inflows/outflows as sentiment signals

## Architecture

### 1. WhaleTracker Module (`whaleutil.py`)

A utility module for interacting with the Whale Alert API:

- Initialize client with API credentials from environment variables
- Fetch recent transactions with configurable filters
- Format transaction data for LLM consumption
- Cache results to respect rate limits

### 2. Data Flow

```
Whale Alert API → WhaleTracker → Format for LLM → Inject into Prompts → LLM Analysis
```

### 3. Integration Points

- Modify all LLM utility modules to accept whale context parameter
- Update main script to fetch whale data before coin analysis
- Include whale summary in trading decision output

## Environment Variables

### API Keys

| Variable | Description |
|----------|-------------|
| `WHALE_ALERT_API_KEY` | Whale Alert API key (required for whale features) |

### Configuration

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `ENABLE_WHALE_DATA` | `true`, `false` | `false` | Enable whale transaction integration |
| `WHALE_MIN_VALUE_USD` | Integer | `1000000` | Minimum transaction value to track (USD) |
| `WHALE_LOOKBACK_MINUTES` | Integer | `60` | How far back to fetch transactions |

## API Details

### Whale Alert API

- **Base URL**: `https://api.whale-alert.io/v1`
- **Documentation**: https://developer.whale-alert.io/documentation/
- **Python Package**: `whale-alert` (PyPI)

### Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/transactions` | Fetch recent whale transactions |
| `/status` | Check API status and rate limits |

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique transaction ID |
| `blockchain` | string | Blockchain network (ethereum, bitcoin, etc.) |
| `symbol` | string | Cryptocurrency symbol |
| `amount` | number | Transaction amount in crypto |
| `amount_usd` | number | Transaction value in USD |
| `timestamp` | integer | Unix timestamp |
| `from.owner_type` | string | Source type: `exchange`, `wallet`, `unknown` |
| `from.owner` | string | Source identifier (exchange name or address) |
| `to.owner_type` | string | Destination type |
| `to.owner` | string | Destination identifier |
| `transaction_type` | string | `transfer`, `mint`, `burn` |

### Rate Limits (Free Tier)

- **Requests**: 10 per minute
- **Historical Data**: Last 1 hour only
- **Minimum Value**: $500,000 USD transactions
- **Paid Tiers**: Higher limits, longer history, lower minimum values

## Implementation

### Phase 1: WhaleTracker Module

Create `whaleutil.py`:

```python
import os
import time
import requests

class WhaleTracker:
    def __init__(self):
        """Initialize the Whale Alert client with API credentials."""
        self.api_key = os.environ.get('WHALE_ALERT_API_KEY')
        if not self.api_key:
            raise ValueError("WHALE_ALERT_API_KEY environment variable not set")
        self.base_url = "https://api.whale-alert.io/v1"
        self.min_value = int(os.environ.get('WHALE_MIN_VALUE_USD', 1000000))
        self.lookback_minutes = int(os.environ.get('WHALE_LOOKBACK_MINUTES', 60))
    
    def get_recent_transactions(self, min_value_usd=None, minutes=None):
        """Fetch whale transactions from the last N minutes."""
        min_value = min_value_usd or self.min_value
        lookback = minutes or self.lookback_minutes
        start_time = int(time.time() - (lookback * 60))
        
        try:
            response = requests.get(
                f"{self.base_url}/transactions",
                params={
                    "api_key": self.api_key,
                    "start": start_time,
                    "min_value": min_value
                },
                timeout=10
            )
            response.raise_for_status()
            return response.json().get("transactions", [])
        except Exception as e:
            print(f"Error fetching whale data: {e}")
            return []
    
    def get_transactions_for_coin(self, coin_symbol):
        """Get whale transactions for a specific coin."""
        all_transactions = self.get_recent_transactions()
        return [
            tx for tx in all_transactions 
            if tx.get("symbol", "").upper() == coin_symbol.upper()
        ]
    
    def format_for_llm(self, transactions, max_transactions=10):
        """Format whale transactions as context for LLM prompts."""
        if not transactions:
            return "No significant whale activity detected in the last hour."
        
        # Sort by value descending
        sorted_tx = sorted(
            transactions, 
            key=lambda x: x.get("amount_usd", 0), 
            reverse=True
        )[:max_transactions]
        
        lines = ["Recent whale transactions (last hour):"]
        for tx in sorted_tx:
            amount_millions = tx.get("amount_usd", 0) / 1_000_000
            symbol = tx.get("symbol", "UNKNOWN")
            from_type = tx.get("from", {}).get("owner_type", "unknown")
            to_type = tx.get("to", {}).get("owner_type", "unknown")
            from_owner = tx.get("from", {}).get("owner", "")
            to_owner = tx.get("to", {}).get("owner", "")
            
            # Determine flow direction for sentiment
            flow = ""
            if from_type == "exchange" and to_type == "wallet":
                flow = " [BULLISH: exchange outflow]"
            elif from_type == "wallet" and to_type == "exchange":
                flow = " [BEARISH: exchange inflow]"
            
            lines.append(
                f"- ${amount_millions:.1f}M {symbol}: "
                f"{from_type}{' ('+from_owner+')' if from_owner else ''} → "
                f"{to_type}{' ('+to_owner+')' if to_owner else ''}{flow}"
            )
        
        return "\n".join(lines)
    
    def get_sentiment_summary(self, coin_symbol):
        """Generate a sentiment summary based on whale activity."""
        transactions = self.get_transactions_for_coin(coin_symbol)
        
        if not transactions:
            return {
                "symbol": coin_symbol,
                "transaction_count": 0,
                "total_volume_usd": 0,
                "exchange_inflow": 0,
                "exchange_outflow": 0,
                "sentiment": "neutral",
                "summary": f"No whale activity for {coin_symbol}"
            }
        
        total_volume = sum(tx.get("amount_usd", 0) for tx in transactions)
        exchange_inflow = sum(
            tx.get("amount_usd", 0) for tx in transactions
            if tx.get("to", {}).get("owner_type") == "exchange"
        )
        exchange_outflow = sum(
            tx.get("amount_usd", 0) for tx in transactions
            if tx.get("from", {}).get("owner_type") == "exchange"
        )
        
        # Determine sentiment
        if exchange_outflow > exchange_inflow * 1.5:
            sentiment = "bullish"
        elif exchange_inflow > exchange_outflow * 1.5:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
        
        return {
            "symbol": coin_symbol,
            "transaction_count": len(transactions),
            "total_volume_usd": total_volume,
            "exchange_inflow": exchange_inflow,
            "exchange_outflow": exchange_outflow,
            "sentiment": sentiment,
            "summary": self.format_for_llm(transactions)
        }
```

### Phase 2: LLM Prompt Integration

Modify LLM utility modules to include whale context. Example for `claudeutil.py`:

```python
def send_coin_check_request(self, coin_symbol, whale_context=""):
    """Check if a specific coin should be bought, sold, or held."""
    if coin_symbol is None:
        return None
    
    whale_section = ""
    if whale_context:
        whale_section = f"""

Additionally, consider this recent whale transaction data:

{whale_context}

Large movements TO exchanges often signal selling pressure (bearish).
Large movements FROM exchanges often signal accumulation (bullish).
"""
    
    response = self.client.messages.create(
        model=self.model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the meme coin with symbol {coin_symbol} right now?{whale_section}

Conclude your analysis with <**{coin_symbol}-PRS-BUY/SELL/HOLD**>"""
            }
        ]
    )
    return response.content[0].text
```

### Phase 3: Main Script Integration

Update `geminigroundlin15.py`:

```python
from whaleutil import WhaleTracker

# Initialize whale tracker if enabled
ENABLE_WHALE_DATA = os.environ.get('ENABLE_WHALE_DATA', 'false').lower() == 'true'
whale_tracker = None
if ENABLE_WHALE_DATA:
    try:
        whale_tracker = WhaleTracker()
        print("Whale Alert integration enabled")
    except Exception as e:
        print(f"Warning: Could not initialize Whale Tracker: {e}")

# In process_coin_with_comparison, add whale context:
def process_coin_with_comparison(coin_symbol, use_trend_check=False, gemini_response_text=""):
    whale_context = ""
    if whale_tracker:
        sentiment = whale_tracker.get_sentiment_summary(coin_symbol)
        whale_context = sentiment.get("summary", "")
        if LOG_INTEGRATION_ROUNDS:
            print(f"\n--- Whale Activity for {coin_symbol} ---")
            print(f"Transactions: {sentiment['transaction_count']}")
            print(f"Sentiment: {sentiment['sentiment']}")
            print(whale_context)
    
    # Pass whale_context to LLM calls...
```

## Whale Movement Interpretation

### Bullish Signals

- Large **outflows from exchanges** to private wallets (accumulation)
- Whales moving coins to cold storage
- Decrease in exchange reserves

### Bearish Signals

- Large **inflows to exchanges** (preparation to sell)
- Whales depositing to known exchange addresses
- Increase in exchange reserves

### Neutral Signals

- Wallet-to-wallet transfers
- Exchange-to-exchange transfers
- Balanced inflow/outflow

## Dependencies

Add to `requirements.txt`:

```
requests>=2.28.0
```

Or use the dedicated package:

```
whale-alert>=0.0.6
```

## Error Handling

- Graceful degradation if API is unavailable
- Cache recent results to handle rate limits
- Log warnings but continue analysis without whale data
- Timeout requests to prevent blocking

## Testing Strategy

1. Unit test WhaleTracker with mock API responses
2. Test formatting with various transaction types
3. Verify LLM prompts include whale context correctly
4. Integration test with live API (low request volume)

## Future Enhancements

1. **WebSocket Integration**: Real-time alerts via Whale Alert WebSocket
2. **Historical Analysis**: Track whale patterns over time
3. **Exchange Reserve Tracking**: Monitor total exchange balances
4. **Multi-Chain Support**: Expand beyond major blockchains
5. **Custom Alerts**: Trigger immediate analysis on large movements
6. **Whale Wallet Tracking**: Follow known whale addresses

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| API rate limits | Cache results, batch requests |
| Stale data | Display timestamps, refresh before decisions |
| False signals | Use as one factor among many, require LLM consensus |
| API downtime | Graceful degradation, continue without whale data |
| Cost (paid tiers) | Start with free tier, upgrade based on value |

## Success Metrics

- Correlation between whale signals and subsequent price movements
- Improvement in trading recommendation accuracy
- Reduction in false positive buy signals during whale sell-offs
- User satisfaction with additional context in analysis
