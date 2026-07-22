"""Tests for the snapshot_ledger() lock-ordering fix (WS-1, improvement cycle 2).

Bug: snapshot_ledger() did load_executions() + shutil.copyfile WITHOUT holding
ledger_lock(), while every mutation path (_append_row, record_fill, and the
maybe_execute_buy span) writes under that lock. A snapshot taken mid-replace
could in principle race a concurrent writer. Fix: wrap the read-and-copy in
`with ledger_lock():` so the snapshot is serialized against every writer the
same way _append_row already is.

Lock-ordering audit (docs/INVARIANTS.md (b)): snapshot_ledger()'s only caller
is crypto_trading_bot.main()'s run-start snapshot (line ~2952), which executes
before any ledger_lock or recommendations-lock span begins -- it never nests
under either lock in the current codebase. The ledger lock itself
(executionledger._FileLock) IS reentrant per-thread (depth-counted in
threading.local), so even a future caller that nests snapshot_ledger() inside
an already-held ledger lock would not deadlock -- test_reentrant below pins
that contract directly rather than relying on "no caller does this today."
"""
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import executionledger as led


@pytest.fixture
def ledger_file(tmp_path, monkeypatch):
    """Redirect the ledger to a scratch file for the duration of a test
    (same convention as tests/test_execution_ledger.py)."""
    f = tmp_path / 'executions.json'
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(f))
    return f


def test_snapshot_ledger_holds_ledger_lock_during_copy(ledger_file, monkeypatch):
    """The copy step must happen while this thread holds ledger_lock() --
    verified directly via the (reentrant, depth-counted) lock's own state
    rather than by timing, which would be flaky."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c1')

    observed = {}
    real_copyfile = led.shutil.copyfile

    def spy_copyfile(src, dst):
        lock = led.ledger_lock()
        # If snapshot_ledger is holding the lock, re-acquiring it here is a
        # reentrant no-op and depth will already be >= 1 BEFORE this `with`
        # even opens -- so read the depth prior to entering our own nested
        # `with` to observe the ambient (caller's) depth.
        observed['depth_before_local_enter'] = getattr(lock._local, 'depth', 0)
        return real_copyfile(src, dst)

    monkeypatch.setattr(led.shutil, 'copyfile', spy_copyfile)
    snap = led.snapshot_ledger()
    assert snap is not None
    assert observed.get('depth_before_local_enter', 0) > 0, (
        "snapshot_ledger's copyfile ran without the ledger lock held")


def test_snapshot_ledger_load_also_under_lock(ledger_file, monkeypatch):
    """The load_executions() read (not just the copyfile) must also happen
    inside the lock span -- otherwise a writer could replace the file between
    the read and the copy."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c1')

    observed = {}
    real_load = led.load_executions

    def spy_load():
        lock = led.ledger_lock()
        observed['depth'] = getattr(lock._local, 'depth', 0)
        return real_load()

    monkeypatch.setattr(led, 'load_executions', spy_load)
    led.snapshot_ledger()
    assert observed.get('depth', 0) > 0, (
        "snapshot_ledger's load_executions() ran without the ledger lock held")


def test_snapshot_ledger_reentrant_when_called_under_held_lock(ledger_file):
    """The ledger lock is reentrant per-thread (executionledger._FileLock
    docstring). No current caller nests snapshot_ledger() inside an
    already-held ledger_lock span (its only caller runs at main() startup,
    before any lock span begins) -- but this pins that nesting is safe
    (no deadlock) now that snapshot_ledger itself takes the lock, in case a
    future caller does nest it."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c1')
    with led.ledger_lock():
        snap = led.snapshot_ledger()
    assert snap is not None and Path(snap).exists()


def test_snapshot_concurrent_with_writer_always_valid_json(ledger_file):
    """Concurrency smoke test: a background thread appends rows continuously
    while the main thread repeatedly snapshots (deleting the idempotent
    same-day snapshot between attempts so each iteration actually re-copies).
    Every snapshot produced must parse as valid JSON with an 'executions'
    list -- a torn/partial read would show up as a JSONDecodeError or a
    wrong-shape payload."""
    stop = threading.Event()
    write_errors = []

    def writer():
        i = 0
        while not stop.is_set():
            try:
                led.append_intent(run_id='writer', trading_mode='whatif', coin='BTC',
                                  intended_notional_usd=1.0,
                                  client_order_id=f'writer-{i}')
            except Exception as e:  # pragma: no cover - failure path, asserted below
                write_errors.append(e)
            i += 1

    # Seed one row so the ledger file exists before snapshotting starts.
    led.append_intent(run_id='seed', trading_mode='whatif', coin='BTC',
                      intended_notional_usd=1.0, client_order_id='seed-0')

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        bak_path = Path(f'{led.EXECUTIONS_FILE}.bak-{today}')
        parsed_count = 0
        for _ in range(50):
            if bak_path.exists():
                bak_path.unlink()
            snap = led.snapshot_ledger()
            if snap is not None:
                data = json.loads(Path(snap).read_text())  # must not raise
                assert isinstance(data, dict)
                assert isinstance(data.get('executions'), list)
                parsed_count += 1
    finally:
        stop.set()
        t.join(timeout=10)

    assert not write_errors
    assert parsed_count > 0


# ============================================================================
# WS-1b follow-up (audit 2026-07-21b): same bug shape found in two more
# lock-free EXECUTIONS_FILE readers/mutators -- quarantine_corrupt_ledger
# (os.rename) and restore_from_snapshot (copy + os.replace). Same depth-spy
# pattern as the snapshot_ledger tests above.
# ============================================================================

def test_quarantine_corrupt_ledger_holds_lock_during_rename(ledger_file, monkeypatch):
    """The os.rename step must happen while this thread holds ledger_lock()."""
    ledger_file.write_text('not valid json')

    observed = {}
    real_rename = led.os.rename

    def spy_rename(src, dst):
        lock = led.ledger_lock()
        observed['depth_before_local_enter'] = getattr(lock._local, 'depth', 0)
        return real_rename(src, dst)

    monkeypatch.setattr(led.os, 'rename', spy_rename)
    dest = led.quarantine_corrupt_ledger()
    assert dest is not None
    assert observed.get('depth_before_local_enter', 0) > 0, (
        "quarantine_corrupt_ledger's os.rename ran without the ledger lock held")


def test_quarantine_corrupt_ledger_reentrant_when_called_under_held_lock(ledger_file):
    """Pins that nesting quarantine_corrupt_ledger() inside an already-held
    ledger_lock span does not deadlock (both current call sites in
    crypto_trading_bot run inside maybe_execute_buy's lock span)."""
    ledger_file.write_text('not valid json')
    with led.ledger_lock():
        dest = led.quarantine_corrupt_ledger()
    assert dest is not None and Path(dest).exists()


def test_restore_from_snapshot_holds_lock_during_copy(ledger_file, monkeypatch):
    """The copy step must happen while this thread holds ledger_lock()."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c1')
    snap = led.snapshot_ledger()
    assert snap is not None

    observed = {}
    real_copyfile = led.shutil.copyfile

    def spy_copyfile(src, dst):
        lock = led.ledger_lock()
        observed['depth_before_local_enter'] = getattr(lock._local, 'depth', 0)
        return real_copyfile(src, dst)

    monkeypatch.setattr(led.shutil, 'copyfile', spy_copyfile)
    restored = led.restore_from_snapshot()
    assert restored == snap
    assert observed.get('depth_before_local_enter', 0) > 0, (
        "restore_from_snapshot's copyfile ran without the ledger lock held")


def test_restore_from_snapshot_reentrant_when_called_under_held_lock(ledger_file):
    """Pins that nesting restore_from_snapshot() inside an already-held
    ledger_lock span does not deadlock (both current call sites in
    crypto_trading_bot._recover_live_ledger run inside maybe_execute_buy's
    lock span)."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c1')
    snap = led.snapshot_ledger()
    assert snap is not None
    with led.ledger_lock():
        restored = led.restore_from_snapshot()
    assert restored == snap
