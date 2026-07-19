"""Execution Ledger (T5, plan Phase 1) -- append-only record of ORDER attempts.

Where `historyutil` records *recommendations* (what the panel decided), this
module records *executions* (what the bot actually tried to buy, and what came
back). The two are joined by `run_id` (T2) and by the deterministic
`client_order_id` (coinbaseutil2). EVALUATION_LESSONS_LEARNED_2026-07-18.md
1.6 / 2.5 / 5.5: the live SOL/ETH buys were fire-and-forget -- history stored a
pre-trade *quote* price with no size, fee, order id, or any link to whether the
order filled. This ledger closes that gap.

Storage mirrors historyutil conventions exactly:
  * the same HISTORY_DIR env override (so what-if runs point it at a scratch
    dir and never touch the real record),
  * a single JSON file (`executions.json`) holding a flat list under the
    `executions` key,
  * append-only semantics.

The ledger is a flat list of ROWS, each of one of two shapes distinguished by
`status`:

  INTENT row (status == 'intent'), written BEFORE the order is placed so a
  crash mid-sequence leaves a reconcilable stub:
      {ledger_id, run_id, trading_mode, coin, side, intended_notional_usd,
       client_order_id, timestamp, status='intent'}

  FILL row (status in {'filled','failed','unconfirmed','simulated'}), written
  AFTER the order resolves, carrying the SAME ledger_id:
      {ledger_id, order_id, status, filled_size, avg_fill_price, fees_usd,
       completed_at}

A fill row is joined back to its intent row by `ledger_id` to recover coin /
trading_mode / side (fill rows deliberately don't duplicate those).

What-if runs use the same two-row shape: an intent row with
trading_mode='whatif' and a synthetic fill row {status:'simulated',
avg_fill_price: <current ask>}. The ledger is therefore the uniform record of
both live and what-if buys.

Writes are atomic (temp file + os.replace) because this is the money path and
each append must survive a crash -- a stronger guarantee than historyutil's
in-place rewrite, on purpose.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Same override knob as historyutil -- a run that sets HISTORY_DIR redirects
# BOTH the recommendation history and this ledger to the scratch location.
HISTORY_DIR = os.environ.get('HISTORY_DIR', './history/')
EXECUTIONS_FILE = os.path.join(HISTORY_DIR, 'executions.json')

# Ledger row statuses.
INTENT = 'intent'
# Terminal fill statuses.
FILLED = 'filled'          # confirmed FILLED by get_order
FAILED = 'failed'          # create failed AND we verified no order was placed (CANCELLED/REJECTED/EXPIRED, or lookup found nothing)
UNCONFIRMED = 'unconfirmed'  # order placed but fill never confirmed (poll exhausted while OPEN)
# F2: a create failed AND the client_order_id lookup itself could not confirm
# whether the order was placed -- money MAY have moved. Distinct from a clean
# 'failed' so reconcile --repair can hunt these down; NEVER counted as a
# position (fail-safe: don't claim a holding we're unsure of).
UNVERIFIED_FAILURE = 'unverified_failure'
SIMULATED = 'simulated'    # what-if -- no real order placed
FILL_STATUSES = frozenset({FILLED, FAILED, UNCONFIRMED, UNVERIFIED_FAILURE, SIMULATED})

# The set of statuses that count as an actually-held BUY when deriving
# positions. Only confirmed live fills move the position.
_POSITION_STATUSES = frozenset({FILLED})


def ensure_history_dir():
    """Create the ledger directory if it doesn't exist (mirrors historyutil)."""
    os.makedirs(os.path.dirname(EXECUTIONS_FILE) or '.', exist_ok=True)


def load_executions() -> List[Dict]:
    """Load all ledger rows. Returns [] if the file doesn't exist yet."""
    if not os.path.exists(EXECUTIONS_FILE):
        return []
    try:
        with open(EXECUTIONS_FILE, 'r') as f:
            data = json.load(f)
        return data.get('executions', [])
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load execution ledger: {e}")
        return []


def _save_executions(rows: List[Dict]):
    """Atomically persist the full row list.

    Atomic (temp file in the same dir + os.replace) so a crash never leaves a
    half-written ledger -- either the previous file or the new one is present,
    never a truncated mix. This is the one place the ledger is written.
    """
    ensure_history_dir()
    directory = os.path.dirname(EXECUTIONS_FILE) or '.'
    tmp = os.path.join(directory, f'.executions.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    with open(tmp, 'w') as f:
        json.dump({'executions': rows}, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, EXECUTIONS_FILE)


def _append_row(row: Dict) -> Dict:
    """Append a single row and persist. Returns the row for convenience."""
    rows = load_executions()
    rows.append(row)
    _save_executions(rows)
    return row


def _now_iso() -> str:
    """UTC ISO-8601 with a trailing Z, matching historyutil's format.

    Naive-isoformat + literal 'Z' (not the aware object's own +00:00
    isoformat) to keep the on-disk string format byte-identical to before;
    datetime.now(timezone.utc) is just a non-deprecated source for the value.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'


def new_ledger_id(coin: str = '') -> str:
    """A unique-per-attempt ledger id joining an intent row to its fill row.

    Distinct from client_order_id (which is deterministic per run+coin so a
    retry is idempotent). The ledger id is unique per *attempt* so two runs
    that reuse the same client_order_id still get separate ledger rows.
    """
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    suffix = uuid.uuid4().hex[:8]
    coin_part = f'_{coin}' if coin else ''
    return f'led_{stamp}{coin_part}_{suffix}'


def append_intent(
    run_id: Optional[str],
    trading_mode: str,
    coin: str,
    intended_notional_usd: float,
    client_order_id: str,
    side: str = 'BUY',
    timestamp: Optional[str] = None,
    ledger_id: Optional[str] = None,
) -> str:
    """Write an INTENT row (before the order is placed) and return its ledger_id.

    Called first in the write-order sequence so that a crash between placing
    the order and confirming the fill leaves this stub behind for
    reconciliation (an intent with no matching fill row == "we tried to buy X
    and don't know what happened").
    """
    ledger_id = ledger_id or new_ledger_id(coin)
    row = {
        'ledger_id': ledger_id,
        'run_id': run_id,
        'trading_mode': trading_mode,
        'coin': coin,
        'side': side,
        'intended_notional_usd': float(intended_notional_usd),
        'client_order_id': client_order_id,
        'timestamp': timestamp or _now_iso(),
        'status': INTENT,
    }
    _append_row(row)
    return ledger_id


def record_fill(
    ledger_id: str,
    status: str,
    order_id: Optional[str] = None,
    filled_size: Optional[float] = None,
    avg_fill_price: Optional[float] = None,
    fees_usd: Optional[float] = None,
    completed_at: Optional[str] = None,
    repaired_via: Optional[str] = None,
) -> Dict:
    """Write a FILL row carrying the intent's ledger_id.

    `status` must be one of FILL_STATUSES. Numeric fields are coerced to float
    (or left None). The fill row deliberately does NOT repeat coin /
    trading_mode / side -- those live on the intent row and are recovered by
    joining on ledger_id.

    `repaired_via` (F2): when set (e.g. 'get_order' or 'client_order_id_lookup'),
    this fill row is a reconcile --repair resolution of an earlier
    unconfirmed / unverified / orphaned row. Append-only: the original row is
    NEVER rewritten; the repaired row is a NEW row with the SAME ledger_id and
    this provenance field so the correction is auditable. Omitted entirely on
    the normal write path so those rows keep their exact prior shape.
    """
    if status not in FILL_STATUSES:
        raise ValueError(
            f"invalid fill status {status!r}; must be one of {sorted(FILL_STATUSES)}"
        )
    row = {
        'ledger_id': ledger_id,
        'order_id': order_id,
        'status': status,
        'filled_size': _as_float(filled_size),
        'avg_fill_price': _as_float(avg_fill_price),
        'fees_usd': _as_float(fees_usd),
        'completed_at': completed_at or _now_iso(),
    }
    if repaired_via is not None:
        row['repaired_via'] = repaired_via
    _append_row(row)
    return row


def _as_float(value) -> Optional[float]:
    """Best-effort float coercion that tolerates None and blank strings."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ============================================================================
# Pure derivations (take rows explicitly -> unit-testable without file I/O)
# ============================================================================

def _intents_by_id(rows: List[Dict]) -> Dict[str, Dict]:
    """Index intent rows by ledger_id."""
    return {r['ledger_id']: r for r in rows if r.get('status') == INTENT}


def positions_from_rows(rows: List[Dict], trading_mode: str = 'live') -> Dict[str, float]:
    """Net position size per coin derived from CONFIRMED fills of one mode.

    Joins each confirmed-fill row back to its intent row (by ledger_id) to
    recover coin and side, then nets BUY (+size) against SELL (-size). Only
    fills whose intent carries the requested trading_mode are counted -- what-if
    'simulated' fills never move a live position. SELLs are supported for the
    day a SELL/exit path exists; today only BUYs are written.

    IMPORTANT: this is the bot's *attributed* position -- it is NOT account
    truth. Legacy holdings the bot never bought are invisible here; see
    scripts/reconcile_positions.py.
    """
    intents = _intents_by_id(rows)
    pos: Dict[str, float] = {}
    for r in rows:
        if r.get('status') not in _POSITION_STATUSES:
            continue
        intent = intents.get(r.get('ledger_id'))
        if not intent or intent.get('trading_mode') != trading_mode:
            continue
        coin = intent.get('coin')
        size = _as_float(r.get('filled_size')) or 0.0
        side = (intent.get('side') or 'BUY').upper()
        if side == 'SELL':
            pos[coin] = pos.get(coin, 0.0) - size
        else:
            pos[coin] = pos.get(coin, 0.0) + size
    # Drop dust/zeroed-out coins so the table shows only real holdings.
    return {c: s for c, s in pos.items() if abs(s) > 1e-12}


def latest_fill_by_ledger_id(rows: List[Dict]) -> Dict[str, Dict]:
    """Most-recently-written fill row per ledger_id.

    The ledger is append-only, so a repair pass that appends a corrected fill
    row leaves the last row as the authoritative status. Iterating in file
    order and keeping the last fill per ledger_id yields the current effective
    outcome (this is what makes reconcile --repair idempotent).
    """
    latest: Dict[str, Dict] = {}
    for r in rows:
        if r.get('status') in FILL_STATUSES:
            latest[r.get('ledger_id')] = r
    return latest


def find_repair_targets(rows: List[Dict]) -> List[Dict]:
    """Ledger rows reconcile --repair should try to resolve (pure; F2).

    A LIVE ledger_id needs repair when its most-recent fill row is 'unconfirmed'
    (order placed, fill never confirmed -- nothing re-polls these today) or
    'unverified_failure' (create failed, lookup couldn't confirm placement), OR
    it is an intent with NO fill row at all ('orphan_intent' -- a crash between
    the intent and fill writes). A ledger_id already resolved to a terminal
    fill ('filled'/'failed'/'simulated', including a prior repair row) is
    skipped, so repeated --repair passes are idempotent.

    what-if intents are never targeted (they place no real order). Each target:
        {ledger_id, kind, coin, client_order_id, order_id, side, run_id}
    with kind in {'unconfirmed','unverified_failure','orphan_intent'}.
    """
    intents = _intents_by_id(rows)
    latest = latest_fill_by_ledger_id(rows)
    targets: List[Dict] = []
    for lid, intent in intents.items():
        if (intent.get('trading_mode') or '').lower() != 'live':
            continue  # only live orders can have diverged from the exchange
        fill = latest.get(lid)
        if fill is None:
            kind, order_id = 'orphan_intent', None
        elif fill.get('status') == UNCONFIRMED:
            kind, order_id = 'unconfirmed', fill.get('order_id')
        elif fill.get('status') == UNVERIFIED_FAILURE:
            kind, order_id = 'unverified_failure', fill.get('order_id')
        else:
            continue  # filled / failed / simulated -> already resolved
        targets.append({
            'ledger_id': lid,
            'kind': kind,
            'coin': intent.get('coin'),
            'client_order_id': intent.get('client_order_id'),
            'order_id': order_id,
            'side': intent.get('side') or 'BUY',
            'run_id': intent.get('run_id'),
        })
    return targets


def intended_spend_on_date(rows: List[Dict], date_str: str, trading_mode: str = 'live') -> float:
    """Sum intended_notional_usd across INTENT rows of one mode on one UTC date.

    `date_str` is the 'YYYY-MM-DD' UTC day; an intent row matches when its
    timestamp starts with that date. This is the daily-spend-cap summation --
    isolated as a pure function so the cap logic is unit-testable without
    files, a clock, or the network.
    """
    total = 0.0
    for r in rows:
        if r.get('status') != INTENT:
            continue
        if r.get('trading_mode') != trading_mode:
            continue
        ts = r.get('timestamp') or ''
        if ts[:10] == date_str:
            total += _as_float(r.get('intended_notional_usd')) or 0.0
    return total


# ============================================================================
# File-backed convenience wrappers
# ============================================================================

def positions(trading_mode: str = 'live') -> Dict[str, float]:
    """positions_from_rows over the on-disk ledger."""
    return positions_from_rows(load_executions(), trading_mode=trading_mode)


def live_spend_today(now: Optional[datetime] = None) -> float:
    """Today's (UTC) committed LIVE intended spend, summed from the ledger.

    Used by the daily-spend-cap gate before each live buy. What-if intent rows
    are excluded -- what-if spend is limited by the per-run cap, not the daily
    cap.
    """
    now = now or datetime.now(timezone.utc)
    return intended_spend_on_date(load_executions(), now.strftime('%Y-%m-%d'), trading_mode='live')


def daily_cap_would_exceed(amount: float, cap: float, now: Optional[datetime] = None) -> bool:
    """True iff committing `amount` today would push live spend strictly past
    `cap` (the exact-cap boundary is ALLOWED, matching SpendTracker)."""
    return live_spend_today(now) + float(amount) > float(cap)
