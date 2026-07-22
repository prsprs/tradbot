"""WS-2 (improvement cycle 2): single-instance process lock.

Motivation: the owner accidentally ran 5 concurrent `--live` bot processes.
The ledger lock serialized the money *gate*, but nothing prevented concurrent
live *processes*, which are unsupervisable and amplify exchange rate limits.

This suite specs a per-mode single-instance lock:
  * `executionledger.bot_instance_lock(trading_mode)` -- a non-blocking flock
    on `bot_instance.<mode>.lock`, placed beside the executions file (so it
    follows HISTORY_DIR redirection). On acquire it writes the holder PID; on
    contention it reads the holder PID (informational only -- flock, not the
    PID, is the liveness gate, so a stale PID from a dead process never blocks).
  * `crypto_trading_bot.acquire_instance_lock_or_exit(trading_mode,
    allow_concurrent)` -- the startup guard: live fails closed on contention
    (no override); whatif refuses by default but `--allow-concurrent` proceeds
    with a warning; a clean acquire prints the `Instance lock: acquired(...)`
    banner. Tested against the FUNCTION (SystemExit path), not a real bot
    subprocess.

All file ops go to tmp_path via the same EXECUTIONS_FILE redirect
test_execution_ledger.py uses. The release-on-death test uses a real child
process (spawn) -- flock semantics are per-process, so an in-process check
cannot prove OS release on death.
"""
import multiprocessing
import os
import pathlib
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import executionledger as led
import crypto_trading_bot as bot


@pytest.fixture
def ledger_file(tmp_path, monkeypatch):
    """Redirect the ledger (and therefore the sibling instance-lock files) to
    a scratch dir, exactly as test_execution_ledger.py does."""
    f = tmp_path / 'executions.json'
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(f))
    return f


# ---------------------------------------------------------------------------
# bot_instance_lock: path, acquire, PID recording, per-mode independence
# ---------------------------------------------------------------------------

def test_lock_file_lands_beside_executions_file(ledger_file):
    path = led.bot_instance_lock_path('live')
    assert Path(path).parent == ledger_file.parent
    assert Path(path).name == 'bot_instance.live.lock'


def test_acquire_records_pid_and_creates_file(ledger_file):
    lock, holder = led.bot_instance_lock('live')
    try:
        assert lock is not None
        assert holder is None                     # no contention
        path = led.bot_instance_lock_path('live')
        assert Path(path).exists()
        assert Path(path).read_text().strip() == str(os.getpid())
    finally:
        lock.release()


def test_contention_reports_holder_pid(ledger_file):
    held, _ = led.bot_instance_lock('live')
    try:
        lock2, holder = led.bot_instance_lock('live')
        assert lock2 is None                       # could not acquire
        assert holder == os.getpid()               # PID read from lock file
    finally:
        held.release()


def test_two_modes_hold_simultaneously(ledger_file):
    live, live_holder = led.bot_instance_lock('live')
    whatif, whatif_holder = led.bot_instance_lock('whatif')
    try:
        assert live is not None and live_holder is None
        assert whatif is not None and whatif_holder is None
        # Distinct files, so no contention between the two modes.
        assert led.bot_instance_lock_path('live') != led.bot_instance_lock_path('whatif')
    finally:
        live.release()
        whatif.release()


# ---------------------------------------------------------------------------
# Release on process death (flock is per-process; needs a real child)
# ---------------------------------------------------------------------------

def _child_acquire_and_die(hist_dir, mode, marker_path):
    """Child target (spawn): acquire the instance lock, record whether it got
    it, then return -- process exit releases the flock. Runs OUTSIDE pytest,
    so it re-imports executionledger fresh and must set EXECUTIONS_FILE itself.
    """
    import executionledger as led2
    led2.EXECUTIONS_FILE = str(pathlib.Path(hist_dir) / 'executions.json')
    lock, holder = led2.bot_instance_lock(mode)
    with open(marker_path, 'w') as f:
        f.write('OK' if lock is not None else f'FAIL:{holder}')
    # Return -> process exits -> fh closed -> flock released by the OS.


def test_stale_lock_from_dead_process_does_not_block(ledger_file, tmp_path):
    marker = tmp_path / 'child_marker'
    ctx = multiprocessing.get_context('spawn')
    p = ctx.Process(target=_child_acquire_and_die,
                    args=(str(tmp_path), 'live', str(marker)))
    p.start()
    p.join(timeout=30)
    assert p.exitcode == 0
    assert marker.read_text() == 'OK'              # child really held it
    # The lock file still exists with the (now-dead) child's PID in it, but
    # flock released on death -> the parent acquires cleanly.
    lock, holder = led.bot_instance_lock('live')
    try:
        assert lock is not None, (
            "a stale PID from a dead process must never block acquisition "
            "(flock, not the PID-in-file, is the liveness gate)")
        assert holder is None
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# acquire_instance_lock_or_exit: the startup guard
# ---------------------------------------------------------------------------

def test_guard_clean_acquire_prints_banner(ledger_file, capsys):
    lock = bot.acquire_instance_lock_or_exit('live', allow_concurrent=False)
    try:
        out = capsys.readouterr().out
        path = led.bot_instance_lock_path('live')
        assert 'Instance lock: acquired' in out
        assert path in out                         # banner honesty: real path
        assert lock is not None
    finally:
        lock.release()


def test_guard_live_refuses_on_contention(ledger_file, capsys):
    held, _ = led.bot_instance_lock('live')
    try:
        with pytest.raises(SystemExit) as exc:
            bot.acquire_instance_lock_or_exit('live', allow_concurrent=False)
        assert exc.value.code != 0                 # non-zero exit
        out = capsys.readouterr().out
        assert str(os.getpid()) in out             # holder PID in message
        assert led.bot_instance_lock_path('live') in out   # lock path in message
        assert 'live' in out.lower()
    finally:
        held.release()


def test_guard_live_has_no_concurrent_override(ledger_file):
    """Even with allow_concurrent=True, live must fail closed -- there is no
    override for live (the whole point of the accidental-5-processes fix)."""
    held, _ = led.bot_instance_lock('live')
    try:
        with pytest.raises(SystemExit) as exc:
            bot.acquire_instance_lock_or_exit('live', allow_concurrent=True)
        assert exc.value.code != 0
    finally:
        held.release()


def test_guard_whatif_refuses_by_default(ledger_file, capsys):
    held, _ = led.bot_instance_lock('whatif')
    try:
        with pytest.raises(SystemExit) as exc:
            bot.acquire_instance_lock_or_exit('whatif', allow_concurrent=False)
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert str(os.getpid()) in out
        assert '--allow-concurrent' in out         # tells the operator the escape hatch
    finally:
        held.release()


def test_guard_whatif_allow_concurrent_proceeds_with_warning(ledger_file, capsys):
    held, _ = led.bot_instance_lock('whatif')
    try:
        # Must NOT raise SystemExit -- research/experiment parallelism allowed.
        result = bot.acquire_instance_lock_or_exit('whatif', allow_concurrent=True)
        out = capsys.readouterr().out
        assert 'WARNING' in out or 'warning' in out
        assert '--allow-concurrent' in out or 'concurrent' in out.lower()
        # It proceeds without holding the guard (the other process holds it).
        assert result is None
    finally:
        held.release()


def test_guard_whatif_allow_concurrent_still_acquires_when_free(ledger_file, capsys):
    """--allow-concurrent with NO contender still takes the lock normally
    (the flag only changes behavior on contention)."""
    lock = bot.acquire_instance_lock_or_exit('whatif', allow_concurrent=True)
    try:
        assert lock is not None
        assert 'Instance lock: acquired' in capsys.readouterr().out
    finally:
        lock.release()
