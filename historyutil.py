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

import hashlib
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


# === WS3 (schema v2) provenance helpers =====================================

def prompt_hash(prompt: str) -> str:
    """sha256[:16] hex digest of an analysis prompt (WS3 provenance).

    Deliberately mirrors history/recorder.HistoryRecorder._hash_prompt so the
    two history stacks produce identical hashes for identical prompt bytes.
    """
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def market_block_ref(run_id: str) -> str:
    """Relative ref stored on records, pointing at this run's market-block file
    (`market_blocks/<run_id>.json`). Relative so it is portable across the
    per-user/scratch HISTORY_DIR redirections."""
    return os.path.join('market_blocks', f'{run_id}.json')


def market_block_hash(block_text: Optional[str]) -> Optional[str]:
    """WS5: sha256[:16] of the EXACT per-coin market-block string.

    The fingerprint that lets a reader distinguish "same data snapshot, different
    vote" (model instability) from "different snapshot". It hashes the identical
    string that write_market_blocks persists into
    market_blocks/<run_id>.json[coin_symbol] (that sidecar stores
    {coin: block_text} verbatim), so a reader can recompute
    market_block_hash(blocks[coin]) and verify it against the record. Returns
    None for a missing/empty block (nothing was cached for this coin), which
    keeps the record byte-identical to a pre-WS5 record for that coin.
    """
    if not block_text:
        return None
    return hashlib.sha256(block_text.encode()).hexdigest()[:16]


def write_market_blocks(run_id: str, blocks: Dict[str, str]) -> Optional[str]:
    """Persist this run's frozen per-coin market blocks (WS3).

    Writes {coin: block_text} to <HISTORY_DIR>/market_blocks/<run_id>.json and
    returns the relative ref (see market_block_ref). HISTORY_DIR redirection is
    respected exactly like recommendations.json -- the directory is derived from
    RECOMMENDATIONS_FILE at call time, so a scratch/what-if HISTORY_DIR (or a
    test that monkeypatches RECOMMENDATIONS_FILE) lands the file in the same
    redirected tree. Atomic (temp + os.replace) so a crash never leaves a
    truncated file.

    Best-effort by contract: a write failure (or nothing to write) returns None
    with a warning and NEVER raises -- persisting the snapshot must not be able
    to abort a trading run.
    """
    if not blocks:
        return None
    try:
        directory = os.path.join(os.path.dirname(RECOMMENDATIONS_FILE) or '.',
                                 'market_blocks')
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f'{run_id}.json')
        tmp = os.path.join(directory,
                           f'.market_blocks.{os.getpid()}.{uuid.uuid4().hex}.tmp')
        with open(tmp, 'w') as f:
            json.dump(blocks, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return market_block_ref(run_id)
    except Exception as e:
        print(f"[HISTORY WARN] could not write market blocks for run "
              f"{run_id}: {e} (records still reference the path; snapshot "
              "missing for this run)")
        return None


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
    run_id: Optional[str] = None,
    schema_version: Optional[int] = None,
    vote_details: Optional[Dict[str, Dict]] = None,
    prompt_hash: Optional[str] = None,
    models: Optional[Dict[str, str]] = None,
    market_block_ref: Optional[str] = None,
    market_block_present: Optional[bool] = None,
    market_block_hash: Optional[str] = None,
    spread_pct: Optional[float] = None,
    sampling: Optional[Dict[str, object]] = None,
    data_quality: Optional[Dict[str, Dict]] = None
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
        schema_version: WS3 record-schema version (2 for full-decision-record
            writers). Optional; absent on legacy v1 records, which are treated
            as v1 implicitly. All WS3 fields below are optional and default to
            None, so a caller omitting them produces a byte-identical v1 record.
        vote_details: Per-LLM {action, confidence} on ALL records (directional
            and blocked). action is the vote string or None for an abstain;
            confidence is a 0..1 float or None (abstains / legacy parse paths).
        prompt_hash: sha256[:16] of the primary analysis prompt actually sent
            (see prompt_hash()).
        models: Panelist -> resolved model ID (from modelregistry) that actually
            ran, tiebreaker included when used.
        market_block_ref: Relative path to this run's frozen market-block file
            (see market_block_ref()).
        market_block_present: True iff this coin's frozen market block was
            captured in the referenced file.
        market_block_hash: WS5 sha256[:16] of this coin's EXACT market-block
            string (see market_block_hash()) -- the decision fingerprint a
            reader recomputes from the sidecar to verify. Optional; None (e.g.
            no block cached) keeps the byte-identical record shape.
        spread_pct: WS5 derived bid/ask spread as ((ask-bid)/mid*100), or None
            when honest bid AND ask were not both available (never fabricated).
        sampling: WS5 per-provider {llm: sampling} where sampling is the dict of
            sampling params actually sent on that panelist's analysis request
            (e.g. {'temperature': 0}) or the string 'provider-default' when the
            code set nothing. Records what was ACTUALLY sent, never an invented
            value. Optional; omitted keeps the byte-identical record shape.
        data_quality: WS4 (cycle 2) per-source status of the market-data block
            this coin's panel actually reasoned over, as
            {source: {'status': 'ok'|'degraded'|'failed'|'skipped',
            'detail': str}} over coinbase/fibonacci/google_trends/cmc/social.
            Provenance only (no tradeanalyzer reader today); optional, so
            omitting it keeps a byte-identical v1 record.

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

    # WS3 (schema v2) provenance + full decision detail. Each field is written
    # only when supplied; a caller that omits them all reproduces the exact v1
    # record shape, so the analyzer and the 109 existing records are unaffected.
    if schema_version is not None:
        record['schema_version'] = schema_version
    if vote_details is not None:
        record['vote_details'] = {llm: dict(d) for llm, d in vote_details.items()}
    if prompt_hash is not None:
        record['prompt_hash'] = prompt_hash
    if models is not None:
        record['models'] = dict(models)
    if market_block_ref is not None:
        record['market_block_ref'] = market_block_ref
    if market_block_present is not None:
        record['market_block_present'] = market_block_present

    # WS5 (cycle 2): decision fingerprint + honest spread + sampling provenance.
    # Each written only when supplied so an omitting caller reproduces the exact
    # prior record shape (byte-identity preserved, RECORD_SCHEMA evolution rule).
    if market_block_hash is not None:
        record['market_block_hash'] = market_block_hash
    if spread_pct is not None:
        record['spread_pct'] = spread_pct
    if sampling is not None:
        record['sampling'] = {llm: (dict(s) if isinstance(s, dict) else s)
                              for llm, s in sampling.items()}

    # WS4 (cycle 2): per-source data-quality of the market block. Written only
    # when supplied (deep-copied so a later caller mutation can't reach the
    # persisted record); omitting it preserves the exact prior record shape.
    if data_quality is not None:
        record['data_quality'] = {src: dict(d) for src, d in data_quality.items()}

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
    run_id: Optional[str] = None,
    schema_version: Optional[int] = None,
    vote_details: Optional[Dict[str, Dict]] = None,
    prompt_hash: Optional[str] = None,
    models: Optional[Dict[str, str]] = None,
    market_block_ref: Optional[str] = None,
    market_block_present: Optional[bool] = None,
    market_block_hash: Optional[str] = None,
    bid_price: Optional[float] = None,
    ask_price: Optional[float] = None,
    spread_pct: Optional[float] = None,
    sampling: Optional[Dict[str, object]] = None,
    data_quality: Optional[Dict[str, Dict]] = None
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
        schema_version / vote_details / prompt_hash / models /
            market_block_ref / market_block_present: WS3 schema-v2 fields,
            passed through to create_recommendation_record (see there).
        market_block_hash / spread_pct / sampling: WS5 fields, passed through
            to create_recommendation_record (see there).
        bid_price / ask_price: WS5 honest bid/ask captured by the CALLER (the
            two crypto_trading_bot loops fetch real best_bid/best_ask via
            Coinbase get_best_bid_ask -- the get_product payload exposes neither,
            only price/mid_market_price). When supplied they OVERRIDE the
            product-attribute fallback below; None means "caller had nothing,
            fall back to whatever the product exposes" (preserving prior
            behavior for callers that don't pass them).
        data_quality: WS4 per-source market-data status, passed through (see
            create_recommendation_record).

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

    # WS5: the caller (crypto_trading_bot) captures honest best_bid/best_ask via
    # the Coinbase get_best_bid_ask endpoint, which the get_product payload does
    # NOT expose. A caller-supplied value OVERRIDES the product-attribute
    # fallback above; None means the caller had nothing, so keep the fallback.
    if bid_price is not None:
        bid = bid_price
    if ask_price is not None:
        ask = ask_price

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
        run_id=run_id,
        schema_version=schema_version,
        vote_details=vote_details,
        prompt_hash=prompt_hash,
        models=models,
        market_block_ref=market_block_ref,
        market_block_present=market_block_present,
        market_block_hash=market_block_hash,
        spread_pct=spread_pct,
        sampling=sampling,
        data_quality=data_quality
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
