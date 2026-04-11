"""
History Utility - Shared utility for recording and loading recommendation history.

This module provides functions to:
- Create and save recommendation records
- Load historical recommendations
- Manage the history directory structure
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, List

HISTORY_DIR = os.environ.get('HISTORY_DIR', './history/')
RECOMMENDATIONS_FILE = os.path.join(HISTORY_DIR, 'recommendations.json')


def ensure_history_dir():
    """Create history directory if it doesn't exist."""
    os.makedirs(HISTORY_DIR, exist_ok=True)


def load_recommendations() -> List[Dict]:
    """Load all recommendations from JSON file.
    
    Returns:
        List of recommendation records, or empty list if file doesn't exist.
    """
    if not os.path.exists(RECOMMENDATIONS_FILE):
        return []
    try:
        with open(RECOMMENDATIONS_FILE, 'r') as f:
            data = json.load(f)
        return data.get('recommendations', [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load recommendations: {e}")
        return []


def save_recommendation(rec: Dict):
    """Append a recommendation to the history file.
    
    Args:
        rec: Recommendation record dictionary to save.
    """
    ensure_history_dir()
    recs = load_recommendations()
    recs.append(rec)
    with open(RECOMMENDATIONS_FILE, 'w') as f:
        json.dump({'recommendations': recs}, f, indent=2)


def create_recommendation_record(
    coin_symbol: str,
    recommendation: str,
    price: float,
    bid_price: float,
    ask_price: float,
    llm_source: str,
    mode: str,
    consensus: Optional[bool] = None
) -> Dict:
    """Create a recommendation record with all required fields.
    
    Args:
        coin_symbol: Cryptocurrency symbol (e.g., 'DOGE', 'SHIB')
        recommendation: BUY, SELL, or HOLD
        price: Price at time of recommendation
        bid_price: Bid price at recommendation time
        ask_price: Ask price at recommendation time
        llm_source: Which LLM(s) made this recommendation
        mode: gemini, claude, openai, grok, perplexity, compare, or integrate
        consensus: Whether all LLMs agreed (for multi-LLM modes), None for single LLM
    
    Returns:
        Dictionary containing the recommendation record.
    """
    return {
        'id': f"rec_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{coin_symbol}",
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'coin_symbol': coin_symbol,
        'recommendation': recommendation.upper().strip() if recommendation else 'UNKNOWN',
        'price_at_recommendation': price,
        'bid_price': bid_price,
        'ask_price': ask_price,
        'llm_source': llm_source,
        'mode': mode,
        'consensus': consensus
    }


def record_recommendation(
    coin_symbol: str,
    recommendation: str,
    trader,
    llm_source: str,
    mode: str,
    consensus: Optional[bool] = None
) -> Optional[Dict]:
    """Record a recommendation by fetching current price from trader and saving.
    
    This is a convenience function that combines fetching price data and saving.
    
    Args:
        coin_symbol: Cryptocurrency symbol (e.g., 'DOGE', 'SHIB')
        recommendation: BUY, SELL, or HOLD
        trader: BlobbyTrader instance for fetching price data
        llm_source: Which LLM(s) made this recommendation
        mode: gemini, claude, openai, grok, perplexity, compare, or integrate
        consensus: Whether all LLMs agreed (for multi-LLM modes)
    
    Returns:
        The saved recommendation record, or None if price fetch failed.
    """
    if not recommendation:
        return None
    
    try:
        product = trader.get_product_details(f"{coin_symbol}-USD")
        if product:
            price = float(product.price) if hasattr(product, 'price') else 0.0
            # Coinbase product may have quote_increment/price but not bid/ask directly
            # Use price as fallback for bid/ask
            bid = float(product.bid) if hasattr(product, 'bid') and product.bid else price
            ask = float(product.ask) if hasattr(product, 'ask') and product.ask else price
            
            rec_record = create_recommendation_record(
                coin_symbol=coin_symbol,
                recommendation=recommendation,
                price=price,
                bid_price=bid,
                ask_price=ask,
                llm_source=llm_source,
                mode=mode,
                consensus=consensus
            )
            save_recommendation(rec_record)
            print(f"[HISTORY] Recorded: {coin_symbol} {recommendation} @ ${price:.6f}")
            return rec_record
        else:
            print(f"[HISTORY] Could not get price for {coin_symbol}, skipping record")
            return None
    except Exception as e:
        print(f"[HISTORY] Error recording recommendation for {coin_symbol}: {e}")
        return None
