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

Two OPTIONAL fill-row fields (added 2026-07-19, MP-1/MP-6):

  duplicate_of: <ledger_id>  -- this fill's (truthy) order_id already belongs
      to an earlier ledger row: Coinbase's idempotent duplicate shape (same
      client_order_id resubmitted -> success:true + the ORIGINAL order_id).
      No new money moved, so these rows are EXCLUDED from positions and from
      the daily-cap intent sum. Same-ledger_id order_id reuse is a reconcile
      repair, never marked duplicate. Falsy order_ids ('' / None) are never
      treated as an identity. Duplicate rows are *expected* in ledgers after
      same-client_order_id resubmits -- not corruption.

  fees_estimated: true  -- fees_usd is a 1.2%-of-notional estimate on a
      simulated (whatif) fill. Omitted (not false) on real fills, so live row
      shapes are unchanged. Any future analyzer/SELL-sizing work must consume
      both fields or it will re-introduce double-counting.

What-if runs use the same two-row shape: an intent row with
trading_mode='whatif' and a synthetic fill row {status:'simulated',
avg_fill_price: <current ask>}. The ledger is therefore the uniform record of
both live and what-if buys.

Writes are atomic (temp file + os.replace) because this is the money path and
each append must survive a crash -- a stronger guarantee than historyutil's
in-place rewrite, on purpose.
"""

import fcntl
import glob
import json
import os
import shutil
import threading
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


# ============================================================================
# Cross-process file locking (MP-3, audit 2026-07-19)
# ============================================================================
# The whatif-cadence runbook schedules cron runs against the same HISTORY_DIR
# and runs take minutes, so overlap is realistic. Without a lock, two
# overlapping load->modify->replace writers silently drop the loser's rows --
# including the intent rows the daily cap counts -- and the daily-cap
# check-then-append in maybe_execute_buy is a TOCTOU race (two runs both read
# under-cap, both order). fcntl.flock on a sibling '.lock' file serializes
# both, and the helper is REENTRANT (per thread, depth-counted) so
# maybe_execute_buy can hold the ledger lock across its cap-check ->
# append_intent span without deadlocking when append_intent re-acquires it.
#
# RULE (deadlock avoidance): never hold the ledger lock and the history
# (recommendations) lock at the same time. Current call sites don't --
# record_recommendation runs before gate_and_maybe_buy, never inside it.

class _FileLock:
    """Reentrant (per-thread) exclusive lock backed by fcntl.flock on `path`.

    Reentrancy is depth-counted in a threading.local: the same thread may
    nest `with` blocks freely; the flock is taken on first entry and released
    on last exit. Distinct threads/processes serialize on the OS lock.
    """

    def __init__(self, path: str):
        self._path = path
        self._local = threading.local()

    def __enter__(self):
        depth = getattr(self._local, 'depth', 0)
        if depth == 0:
            os.makedirs(os.path.dirname(self._path) or '.', exist_ok=True)
            fh = open(self._path, 'a+')
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            self._local.fh = fh
        self._local.depth = depth + 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self._local.depth -= 1
        if self._local.depth == 0:
            fh = self._local.fh
            self._local.fh = None
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
        return False


_LOCKS: Dict[str, _FileLock] = {}
_LOCKS_GUARD = threading.Lock()


def file_lock(path: str) -> _FileLock:
    """The process-wide _FileLock for `path` (one instance per path, so
    reentrancy works across call sites that name the same file). Shared with
    historyutil for its own sibling lock file."""
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = _LOCKS[path] = _FileLock(path)
        return lock


def ledger_lock() -> _FileLock:
    """The lock guarding EXECUTIONS_FILE (sibling executions.json.lock).

    Resolved at CALL time (not import time) so tests and HISTORY_DIR
    overrides that repoint EXECUTIONS_FILE get a matching lock file.
    """
    return file_lock(EXECUTIONS_FILE + '.lock')


class LedgerError(Exception):
    """The execution ledger exists but cannot be read (corrupt JSON /
    unreadable file). MP-2 (audit 2026-07-19): this must FAIL CLOSED -- the
    old behavior (return [] and let the next append silently rewrite the
    file) wiped the money record AND reset the daily spend cap to $0.
    Callers on the live buy path must treat this as a refused buy unless
    recovery succeeds (see crypto_trading_bot.maybe_execute_buy)."""


def load_executions() -> List[Dict]:
    """Load all ledger rows.

    Returns [] ONLY when the file does not exist (a normal first run).
    A file that exists but cannot be parsed/read raises LedgerError -- it is
    NEVER silently treated as empty (that fail-open path erased real ledgers
    and reset the cross-run daily cap; MP-2)."""
    if not os.path.exists(EXECUTIONS_FILE):
        return []
    try:
        with open(EXECUTIONS_FILE, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError, OSError, UnicodeDecodeError) as e:
        raise LedgerError(
            f"execution ledger {EXECUTIONS_FILE} is unreadable: {e}") from e
    # Shape validation (review MAJOR 1): valid JSON of the WRONG shape ({},
    # a bare list, a missing/odd 'executions' key) must fail closed too --
    # silently yielding [] here is the same cap-reset fail-open as a decode
    # error, and the manual-repair recovery workflow makes wrong-shape files
    # a realistic input. A legitimately empty ledger is always
    # {'executions': []} (or an absent file), so this is strictly tightening.
    if not isinstance(data, dict) or not isinstance(data.get('executions'), list):
        raise LedgerError(
            f"execution ledger {EXECUTIONS_FILE} has the wrong shape "
            f"(expected an object with an 'executions' list, got "
            f"{type(data).__name__})")
    return data['executions']


def quarantine_corrupt_ledger() -> Optional[str]:
    """Rename the (corrupt) ledger file aside as executions.json.corrupt-<ts>.

    NEVER deletes anything -- the bad file is preserved for manual repair.
    (This is local per-user runtime data, gitignored, never committed.)
    Returns the quarantine path, or None when the file doesn't exist.
    """
    if not os.path.exists(EXECUTIONS_FILE):
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest = f'{EXECUTIONS_FILE}.corrupt-{stamp}'
    while os.path.exists(dest):  # never overwrite an earlier quarantine
        dest = f'{EXECUTIONS_FILE}.corrupt-{stamp}-{uuid.uuid4().hex[:6]}'
    os.rename(EXECUTIONS_FILE, dest)
    return dest


def snapshot_ledger() -> Optional[str]:
    """Run-start snapshot (DI-4): copy executions.json to
    executions.json.bak-<YYYY-MM-DD> (UTC date).

    Idempotent per day (no-op if today's snapshot exists) and skipped when the
    current ledger is itself unreadable (never let a corrupt file shadow an
    older good snapshot as 'newest'). This snapshot is the auto-recovery
    source for MP-2's corrupt-ledger handling. Callers should treat failures
    as non-fatal. Returns the snapshot path or None when skipped/absent.
    """
    if not os.path.exists(EXECUTIONS_FILE):
        return None
    dest = f"{EXECUTIONS_FILE}.bak-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    if os.path.exists(dest):
        return dest
    load_executions()   # raises LedgerError if corrupt -> caller skips snapshot
    shutil.copyfile(EXECUTIONS_FILE, dest)
    return dest


def newest_snapshot() -> Optional[str]:
    """Path of the newest executions.json.bak-* snapshot, or None.

    'Newest' by the date embedded in the name (lexicographic == chronological
    for .bak-YYYY-MM-DD), which is deterministic across copies/restores.
    """
    snaps = sorted(glob.glob(f'{EXECUTIONS_FILE}.bak-*'))
    return snaps[-1] if snaps else None


def restore_from_snapshot() -> Optional[str]:
    """Restore the ledger from the newest .bak- snapshot (MP-2 recovery).

    Copies the snapshot over EXECUTIONS_FILE atomically (tmp + os.replace).
    The snapshot itself is left in place. Returns the snapshot path used, or
    None when no snapshot exists. The caller must re-validate by loading
    (a restored file could itself be bad; that path stays fail-closed).
    """
    snap = newest_snapshot()
    if snap is None:
        return None
    ensure_history_dir()
    directory = os.path.dirname(EXECUTIONS_FILE) or '.'
    tmp = os.path.join(directory, f'.executions.restore.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    shutil.copyfile(snap, tmp)
    os.replace(tmp, EXECUTIONS_FILE)
    return snap


def recovery_command() -> str:
    """The exact copy-paste command to manually restore the ledger from a
    quarantined (or repaired) file. Shown verbatim in the no-snapshot refusal
    message and documented in OPERATIONS_MANUAL.md ('Ledger recovery')."""
    return (f"cp '{EXECUTIONS_FILE}.corrupt-<ts>' '{EXECUTIONS_FILE}'"
            "   # after repairing the JSON in the quarantined file")


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
    """Append a single row and persist. Returns the row for convenience.

    MP-3: the whole load->append->replace runs under the cross-process ledger
    lock so overlapping runs never drop each other's rows. Reentrant: callers
    (maybe_execute_buy) may already hold the lock across a wider span.
    """
    with ledger_lock():
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
    fees_estimated: Optional[bool] = None,
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

    `fees_estimated` (MP-6c): True marks fees_usd as an ESTIMATE (whatif
    simulated fills estimate ~1.2%/side, the measured Coinbase small-notional
    rate) rather than an exchange-reported figure. Omitted (not False) on
    real fills so live rows keep their exact prior shape -- simulated data
    stays visibly simulated, never dressed as real.
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
    if fees_estimated:
        row['fees_estimated'] = True
    # MP-1d: the REAL Coinbase duplicate signal (validated live 2026-07-19,
    # runbook §7) is the returned order_id matching a ledger row -- a
    # duplicate client_order_id resubmit returns success:true with the
    # ORIGINAL order_id, no error text. When the order_id already exists
    # under a DIFFERENT ledger_id (same-ledger_id rows are reconcile-repair
    # corrections, not duplicates), the new row is marked duplicate_of so
    # positions/cap sums count the real order exactly once. Checked and
    # appended under one lock hold so a concurrent writer can't slip between.
    with ledger_lock():
        rows = load_executions()
        # Truthy guard (review MAJOR 2): '' is not a real exchange identity --
        # two ''-order_id rows must NOT mark each other duplicates (that would
        # wrongly free their intents from the daily-cap sum: cap-loosening).
        # Only a truthy order_id on BOTH rows can signal a duplicate.
        if order_id:
            for existing in rows:
                if (existing.get('status') in FILL_STATUSES
                        and existing.get('order_id') == order_id
                        and existing.get('ledger_id') != ledger_id
                        and not existing.get('duplicate_of')):
                    row['duplicate_of'] = existing.get('ledger_id')
                    print(f"[LEDGER] duplicate order_id {order_id}: fill row for "
                          f"{ledger_id} marked duplicate_of {existing.get('ledger_id')} "
                          "(no second real fill; excluded from positions/cap sums)")
                    break
        rows.append(row)
        _save_executions(rows)
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

    MP-1c/d: each distinct real order_id is counted ONCE -- a duplicate
    client_order_id resubmit records a second fill row carrying the SAME
    order_id (and a duplicate_of marker), but only one real fill happened.
    Rows with a falsy order_id (None or '') keep the old per-row behavior --
    '' is not a real exchange identity, so it never dedupes (review MAJOR 2).
    An order_id enters the seen-set only when its row is actually COUNTED
    (passes the intent/mode join), so an orphan or wrong-mode row can never
    shadow a later countable row with the same id (review MINOR 4).
    """
    intents = _intents_by_id(rows)
    pos: Dict[str, float] = {}
    seen_order_ids = set()
    for r in rows:
        if r.get('status') not in _POSITION_STATUSES:
            continue
        if r.get('duplicate_of'):
            continue  # marked duplicate: the original row carries the fill
        oid = r.get('order_id')
        if oid and oid in seen_order_ids:
            continue  # same real order already counted once
        intent = intents.get(r.get('ledger_id'))
        if not intent or intent.get('trading_mode') != trading_mode:
            continue
        if oid:
            seen_order_ids.add(oid)  # counted -> now (and only now) dedupable
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

    MP-1d: an attempt whose fill row was marked duplicate_of moved NO money
    (Coinbase's idempotent dedupe returned the ORIGINAL order, no second
    fill), so its intent is excluded from the cap sum -- the original
    attempt's intent already counted it.
    """
    duplicate_lids = {r.get('ledger_id') for r in rows
                      if r.get('status') in FILL_STATUSES and r.get('duplicate_of')}
    total = 0.0
    for r in rows:
        if r.get('status') != INTENT:
            continue
        if r.get('trading_mode') != trading_mode:
            continue
        if r.get('ledger_id') in duplicate_lids:
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


def spend_today(trading_mode: str = 'live', now: Optional[datetime] = None) -> float:
    """Today's (UTC) committed intended spend for ONE mode, from the ledger.

    MP-6b: parameterized by trading_mode so whatif runs can enforce the same
    daily cap against their own (simulated) intent rows -- the modes never
    share a tally (whatif intents never count against the live cap and vice
    versa).
    """
    now = now or datetime.now(timezone.utc)
    return intended_spend_on_date(load_executions(), now.strftime('%Y-%m-%d'),
                                  trading_mode=trading_mode)


def live_spend_today(now: Optional[datetime] = None) -> float:
    """Today's (UTC) committed LIVE intended spend, summed from the ledger.

    Used by the daily-spend-cap gate before each live buy.
    """
    return spend_today('live', now)


def daily_cap_would_exceed(amount: float, cap: float,
                           now: Optional[datetime] = None,
                           trading_mode: str = 'live') -> bool:
    """True iff committing `amount` today would push `trading_mode` spend
    strictly past `cap` (the exact-cap boundary is ALLOWED, matching
    SpendTracker). Defaults to the live tally (the original contract)."""
    return spend_today(trading_mode, now) + float(amount) > float(cap)
