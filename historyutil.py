"""
History Utility - Shared utility for recording and loading recommendation history.

This module provides functions to:
- Create and save recommendation records
- Load historical recommendations
- Manage the history directory structure

Note: this is the LIVE BOT's history writer (used by crypto_trading_bot.py),
distinct from the history/ package (history/recorder.py's HistoryRecorder),
which is llm_compare.py's recorder. See AGENTS.md's "check both stacks" rule.
"""

import json
import os
import uuid
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


def _quarantine_corrupt_recommendations() -> Optional[str]:
    """Rename a corrupt recommendations file aside as
    recommendations.json.corrupt-<ts>. NEVER deletes; returns the quarantine
    path (or None when the file doesn't exist)."""
    if not os.path.exists(RECOMMENDATIONS_FILE):
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest = f'{RECOMMENDATIONS_FILE}.corrupt-{stamp}'
    while os.path.exists(dest):  # never overwrite an earlier quarantine
        dest = f'{RECOMMENDATIONS_FILE}.corrupt-{stamp}-{uuid.uuid4().hex[:6]}'
    os.rename(RECOMMENDATIONS_FILE, dest)
    return dest


def load_recommendations() -> List[Dict]:
    """Load all recommendations from JSON file.

    Returns [] when the file doesn't exist. A file that exists but cannot be
    parsed is QUARANTINED (renamed to recommendations.json.corrupt-<ts>) and
    [] is returned -- recommendations don't gate money, so a corrupt history
    must not stop the run (fail-open-with-quarantine, audit MP-2 companion),
    but the corrupt file is never silently overwritten by the next save.
    Contrast executionledger.load_executions, which FAILS CLOSED (raises
    LedgerError) because the ledger backs the daily spend cap.
    """
    if not os.path.exists(RECOMMENDATIONS_FILE):
        return []
    try:
        with open(RECOMMENDATIONS_FILE, 'r') as f:
            data = json.load(f)
        return data.get('recommendations', [])
    except (json.JSONDecodeError, IOError, OSError, UnicodeDecodeError) as e:
        print(f"[HISTORY ERROR] could not load {RECOMMENDATIONS_FILE}: {e}")
        quarantined = _quarantine_corrupt_recommendations()
        if quarantined:
            print(f"[HISTORY ERROR] corrupt file preserved at {quarantined} "
                  "(nothing deleted); continuing with an empty history.")
        return []


def save_recommendation(rec: Dict):
    """Append a recommendation to the history file.

    Atomic (temp file in the same dir + os.replace, mirroring
    executionledger._save_executions) so a crash mid-write never leaves a
    truncated file -- the previous file or the new one, never a mix (MP-2).

    MP-3: the load->append->replace runs under a cross-process flock on a
    sibling recommendations.json.lock (helper shared from executionledger)
    so overlapping cron runs never drop each other's records. Deadlock rule:
    this lock is never held together with the ledger lock -- no call path
    nests record_recommendation inside maybe_execute_buy or vice versa.

    Args:
        rec: Recommendation record dictionary to save.
    """
    # Imported here (not at module top) to keep the module dependency
    # one-directional and lazy; executionledger imports nothing from us.
    from executionledger import file_lock
    ensure_history_dir()
    with file_lock(RECOMMENDATIONS_FILE + '.lock'):
        recs = load_recommendations()
        recs.append(rec)
        directory = os.path.dirname(RECOMMENDATIONS_FILE) or '.'
        tmp = os.path.join(directory,
                           f'.recommendations.{os.getpid()}.{uuid.uuid4().hex}.tmp')
        with open(tmp, 'w') as f:
            json.dump({'recommendations': recs}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, RECOMMENDATIONS_FILE)


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
        The saved recommendation record (None only when `recommendation` is
        empty). DI-3 (audit 2026-07-19): a failed price fetch NO LONGER drops
        the record -- it is written with price/bid/ask = None. The analyzer
        already classifies missing rec_price honestly (EXPIRED_UNSCORABLE,
        reason no_rec_price), and exactly the interesting runs (blocked
        decisions, discovery tickers not listed on Coinbase) used to leave no
        history at all despite the call sites' "ALWAYS recorded" promise.
        Bid/ask are also never fabricated as copies of the last price anymore:
        real values or None.
    """
    if not recommendation:
        return None

    def _maybe_float(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    price = bid = ask = None
    try:
        product = trader.get_product_details(f"{coin_symbol}-USD")
        if product:
            price = _maybe_float(getattr(product, 'price', None))
            # DI-3: only REAL bid/ask values are stored -- never price copied
            # into bid/ask (the analyzer must see honest spread data or None).
            bid = _maybe_float(getattr(product, 'bid', None))
            ask = _maybe_float(getattr(product, 'ask', None))
        else:
            print(f"[HISTORY] Could not get price for {coin_symbol}; "
                  "recording with price=None (DI-3)")
    except Exception as e:
        print(f"[HISTORY] Error fetching price for {coin_symbol}: {e}; "
              "recording with price=None (DI-3)")

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
    try:
        save_recommendation(rec_record)
    except Exception as e:
        # A history-save failure must never crash the trading run (the old
        # catch-all had this property; keep it), but it is loud and honest:
        # None means NOT saved.
        print(f"[HISTORY ERROR] could not save recommendation for {coin_symbol}: {e}")
        return None
    timestamp_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    price_str = format_price(price) if price is not None else 'price unavailable'
    print(f"[HISTORY] Recorded: {coin_symbol} {recommendation} @ {price_str} at {timestamp_str}")

    # Export to candidate_coins.csv if enabled. Guarded separately: an export
    # failure must never lose (or misreport) the already-saved record.
    try:
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
    except Exception as e:
        print(f"[HISTORY] candidate export failed (record already saved): {e}")

    return rec_record
