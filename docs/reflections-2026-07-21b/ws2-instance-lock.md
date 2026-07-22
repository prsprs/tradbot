# WS-2 reflection — single-instance process lock

First-person, written at hand-off. Scope: prevent concurrent bot processes of
the same trading mode after the owner accidentally ran 5 `--live` bots at once.

## What I built

- `executionledger.bot_instance_lock(trading_mode)` — a **non-blocking**
  `flock(LOCK_EX|LOCK_NB)` on `bot_instance.<mode>.lock`, resolved beside
  `EXECUTIONS_FILE` at call time so `HISTORY_DIR` redirection carries it.
  Returns `(InstanceLock, None)` on acquire (PID written into the file) or
  `(None, holder_pid)` on contention. Plus `bot_instance_lock_path`,
  `_read_lock_pid`, and the `InstanceLock` holder (with `release()`).
- `crypto_trading_bot.acquire_instance_lock_or_exit(trading_mode, allow_concurrent)`
  — the startup guard, wired into `main()` right after trading-mode resolution
  and the downgrade notice, **before** the analyzer summary / snapshot / any
  network. Live contention fails closed (no override); whatif refuses unless
  `--allow-concurrent`. Clean acquire prints `Instance lock: acquired (<path>)`.
- `--allow-concurrent` flag (whatif-only escape hatch), `INSTANCE_LOCK` module
  global to keep the handle alive for process life, INVARIANTS.md §(b) one-liner.

## Judgment calls (owner should eyeball these)

1. **I did not reuse `_FileLock` directly.** The brief said "reuse the flock
   infrastructure", but `_FileLock` is *blocking + reentrant* by design — the
   opposite of what a single-instance guard needs (a contender must be refused,
   not queued). I reused the same `fcntl.flock` primitive and the call-time
   path-resolution pattern, but wrote a dedicated non-blocking acquirer. Reusing
   `_FileLock` verbatim would have hung the second process instead of refusing
   it. Flagging because it's a literal deviation from the brief's wording.
2. **PID is informational only — verified, not just asserted.** On acquire I
   `truncate`+write our PID; on contention I read it purely to name the holder.
   Nothing consults the PID for liveness (no `os.kill(pid, 0)` check). The
   release-on-death test proves flock alone frees the lock, so a stale PID from
   a dead process never blocks. This was the explicit trap in the brief and I
   kept the code honest to it.
3. **Placement: after downgrade resolution, before the analyzer summary.** The
   analyzer startup summary and `snapshot_ledger` are file reads (no network),
   but I still put the lock ahead of them so "outermost, before any I/O against
   shared state" holds literally. `NOTIONAL_USD` etc. validate *after* the lock
   — acceptable since the lock only needs mode + flag, both resolved earlier.
4. **whatif `--allow-concurrent` returns `None` (no lock held).** The other
   process holds the flock; we can't also hold it, so we proceed lock-less by
   design. `INSTANCE_LOCK = None` is therefore a legitimate value, not a bug.
5. **Per-mode files let live+whatif coexist.** Intended and documented inline;
   a whatif research run beside a live run is safe (whatif never writes the live
   money path). If the owner wants a *global* single-instance (one bot, any
   mode), that's a one-line change to a shared lock filename — but I read the
   brief as explicitly wanting per-mode coexistence.

## Near-misses / things I checked

- **Same-process contention actually works in the tests.** flock treats
  separate `open()` fds as independent holders even within one process, so the
  in-test "acquire then call the guard" pattern genuinely exercises the refusal
  path without a subprocess (used real spawn only for release-on-death, where
  per-process semantics matter).
- **spawn child re-imports fresh**, so `EXECUTIONS_FILE` monkeypatch doesn't
  cross the process boundary — the child target sets it from a passed dir. I
  signalled acquisition via a marker file rather than a `multiprocessing.Queue`
  to sidestep any interaction with the conftest socket guard.
- **No env snapshot added**, so `_refresh_env_snapshots` / import-purity are
  untouched (import stays silent; verified).

## Test delta

+11 tests (`tests/test_instance_lock.py`); suite 929 → **940**, all green.
Files touched: `executionledger.py`, `crypto_trading_bot.py`, `docs/INVARIANTS.md`,
`tests/test_instance_lock.py`. No money-gate logic changed — this only adds a
*refusal* before startup, never loosens anything.
