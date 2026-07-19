"""
History Utility - Shared utility for recording and loading recommendation history.

This module provides functions to:
- Create and save recommendation records
- Load historical recommendations
- Manage the history directory structure
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, List

HISTORY_DIR = os.environ.get('HISTORY_DIR', './history/')
RECOMMENDATIONS_FILE = os.path.join(HISTORY_DIR, 'recommendations.json')

# T2 (history integrity): the set of valid trading_mode values a record may
# carry. 'unknown' covers records where the mode genuinely cannot be
# determined (e.g. curated-backfilled pre-history), not a default to be used
# casually by new callers -- new callers should always know their mode.
VALID_TRADING_MODES = {'live', 'whatif', 'unknown'}


def format_price(price: float, symbol: str = '$') -> str:
    """Format a price for display, using scientific notation for very small values."""
    if price is None or price == 0:
        return f"{symbol}0.00"
    abs_price = abs(price)
    if abs_price < 0.0001:
        return f"{symbol}{price:.2e}"
    elif abs_price < 0.01:
        return f"{symbol}{price:.6f}"
    elif abs_price < 1000:
        return f"{symbol}{price:.4f}"
    else:
        return f"{symbol}{price:.2f}"


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
    consensus: Optional[bool] = None,
    discovery_llm: Optional[str] = None,
    exchange: Optional[str] = None,
    consensus_state: Optional[str] = None,
    deciding_llms: Optional[List[str]] = None,
    votes: Optional[Dict[str, str]] = None,
    block_reason: Optional[str] = None,
    majority_action: Optional[str] = None,
    trading_mode: str = 'unknown',
    run_id: Optional[str] = None
) -> Dict:
    """Create a recommendation record with all required fields.

    T3 (consensus hardening): blocked panel decisions are recorded with
    recommendation 'NONE' plus the panel-decision fields below, so the
    analyzer can measure panel behavior. All new fields are optional and
    default to None — records written before T3 remain loadable unchanged.

    T2 (history integrity): every record now carries trading_mode (so
    what-if experiments stop contaminating the scored live record, doc
    5.3.5) and run_id (so records from the same process invocation can be
    joined later, e.g. by T5's execution ledger). Both are optional on
    *read* — records written before T2 simply lack these keys.

    Args:
        coin_symbol: Cryptocurrency symbol (e.g., 'DOGE', 'SHIB')
        recommendation: BUY, SELL, HOLD, or NONE (blocked panel decision)
        price: Price at time of recommendation
        bid_price: Bid price at recommendation time
        ask_price: Ask price at recommendation time
        llm_source: The actual deciding LLM(s) (comma-joined), or 'none' for a
            blocked decision — not necessarily the primary LLM
        mode: gemini, claude, openai, grok, perplexity, compare, or integrate
        consensus: Whether all LLMs agreed (for multi-LLM modes), None for single LLM
        discovery_llm: Which LLM discovered this coin (None if coin was specified via ANALYZE_COINS)
        exchange: Exchange used for trading (cex, solana-dex), None defaults to cex
        consensus_state: 'unanimous' | 'tiebreaker' | 'single' | 'blocked'
        deciding_llms: List of LLM(s) whose votes produced the action
        votes: Per-LLM final votes, abstains as 'ABSTAIN(<reason>)' markers
        block_reason: Why a blocked decision was blocked
        majority_action: Most common non-abstain vote (measurement only)
        trading_mode: 'live' | 'whatif' | 'unknown' (default 'unknown').
            Validated against VALID_TRADING_MODES; raises ValueError otherwise.
        run_id: Identifier shared by every record written by one process
            invocation (e.g. 'run_20260718T195400Z'), or None.

    Returns:
        Dictionary containing the recommendation record.

    Raises:
        ValueError: if trading_mode is not one of VALID_TRADING_MODES.
    """
    if trading_mode not in VALID_TRADING_MODES:
        raise ValueError(
            f"invalid trading_mode {trading_mode!r}; must be one of "
            f"{sorted(VALID_TRADING_MODES)}"
        )

    _now = datetime.now(timezone.utc)
    record = {
        'id': f"rec_{_now.strftime('%Y%m%d_%H%M%S')}_{coin_symbol}",
        # Naive-isoformat + literal 'Z' preserves the existing on-disk history
        # format exactly (tradeanalyzer.parse_timestamp strips 'Z' and parses
        # naive); datetime.now(timezone.utc) is just a non-deprecated source.
        'timestamp': _now.replace(tzinfo=None).isoformat() + 'Z',
        'coin_symbol': coin_symbol,
        'recommendation': recommendation.upper().strip() if recommendation else 'UNKNOWN',
        'price_at_recommendation': price,
        'bid_price': bid_price,
        'ask_price': ask_price,
        'llm_source': llm_source,
        'mode': mode,
        'consensus': consensus,
        'discovery_llm': discovery_llm,
        'trading_mode': trading_mode,
        'run_id': run_id
    }

    # Add exchange field if specified (for DEX mode compatibility)
    if exchange:
        record['exchange'] = exchange

    # T3 panel-decision fields (only written when supplied; legacy callers
    # that omit them keep producing the old record shape)
    if consensus_state is not None:
        record['consensus_state'] = consensus_state
    if deciding_llms is not None:
        record['deciding_llms'] = list(deciding_llms)
    if votes is not None:
        record['votes'] = dict(votes)
    if block_reason is not None:
        record['block_reason'] = block_reason
    if majority_action is not None:
        record['majority_action'] = majority_action

    return record


def record_recommendation(
    coin_symbol: str,
    recommendation: str,
    trader,
    llm_source: str,
    mode: str,
    consensus: Optional[bool] = None,
    discovery_llm: Optional[str] = None,
    exchange: Optional[str] = None,
    export_candidate: bool = False,
    candidate_dir: str = './correlation_data',
    candidate_blockchain: str = 'Solana',
    export_recommendations: str = 'ALL',
    consensus_state: Optional[str] = None,
    deciding_llms: Optional[List[str]] = None,
    votes: Optional[Dict[str, str]] = None,
    block_reason: Optional[str] = None,
    majority_action: Optional[str] = None,
    trading_mode: str = 'unknown',
    run_id: Optional[str] = None
) -> Optional[Dict]:
    """Record a recommendation by fetching current price from trader and saving.

    This is a convenience function that combines fetching price data and saving.
    Optionally exports the coin to candidate_coins.csv for correlation analysis.

    Args:
        coin_symbol: Cryptocurrency symbol (e.g., 'DOGE', 'SHIB')
        recommendation: BUY, SELL, HOLD, or NONE (blocked panel decision, T3)
        trader: BlobbyTrader or SolanaDEXTrader instance for fetching price data
        llm_source: The actual deciding LLM(s), or 'none' for a blocked decision
        mode: gemini, claude, openai, grok, perplexity, compare, or integrate
        consensus: Whether all LLMs agreed (for multi-LLM modes)
        discovery_llm: Which LLM discovered this coin (None if coin was specified via ANALYZE_COINS)
        exchange: Exchange used for trading (cex, solana-dex), None defaults to cex
        export_candidate: If True, also write coin to candidate_coins.csv
        candidate_dir: Directory for candidate_coins.csv (default: ./correlation_data)
        candidate_blockchain: Blockchain to record for the coin (default: Solana)
        export_recommendations: Which recommendations to export: 'ALL', 'BUY', or 'BUY,HOLD'
        consensus_state / deciding_llms / votes / block_reason / majority_action:
            T3 panel-decision fields, passed through to the record (see
            create_recommendation_record)
        trading_mode: 'live' | 'whatif' | 'unknown' (T2), passed through to
            create_recommendation_record.
        run_id: Process-run identifier (T2), passed through.

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
                consensus=consensus,
                discovery_llm=discovery_llm,
                exchange=exchange,
                consensus_state=consensus_state,
                deciding_llms=deciding_llms,
                votes=votes,
                block_reason=block_reason,
                majority_action=majority_action,
                trading_mode=trading_mode,
                run_id=run_id
            )
            save_recommendation(rec_record)
            timestamp_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            print(f"[HISTORY] Recorded: {coin_symbol} {recommendation} @ {format_price(price)} at {timestamp_str}")
            
            # Export to candidate_coins.csv if enabled
            if export_candidate:
                rec_upper = recommendation.upper().strip()
                export_list = [r.strip().upper() for r in export_recommendations.split(',')]
                # Blocked decisions (NONE) are history-only; never export them
                # as candidate coins
                should_export = rec_upper != 'NONE' and (('ALL' in export_list) or (rec_upper in export_list))
                
                if should_export:
                    from candidate_util import upsert_candidate_coin
                    source = f"llm_recommendation_{mode}"
                    upsert_candidate_coin(
                        symbol=coin_symbol,
                        blockchain=candidate_blockchain,
                        source=source,
                        data_dir=candidate_dir
                    )
            
            return rec_record
        else:
            print(f"[HISTORY] Could not get price for {coin_symbol}, skipping record")
            return None
    except Exception as e:
        print(f"[HISTORY] Error recording recommendation for {coin_symbol}: {e}")
        return None
