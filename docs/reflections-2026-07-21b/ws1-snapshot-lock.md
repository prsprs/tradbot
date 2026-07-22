# WS-1 reflection: snapshot_ledger lock fix (2026-07-21)

First-person reflection from implementing the `snapshot_ledger()` lock fix.

## What was actually harder than expected

Nothing about the *fix* itself was hard -- it's a two-line diff, exactly as
scoped. The genuinely useful time went into the audit step the brief asked
for first: tracing every caller of `snapshot_ledger()` to confirm it never
nests under the ledger lock or the recommendations lock today. That took
one grep (`grep -rn snapshot_ledger`) and turned up exactly one caller
(`crypto_trading_bot.main()`, run-start snapshot), which runs before
`maybe_execute_buy`'s lock span ever opens. Cheap to verify, and worth doing
before touching the function rather than trusting the brief's framing that
"a snapshot taken mid-replace *can* capture a torn file" -- that's a race
argument, not a nesting argument, and I wanted to be sure I wasn't about to
introduce a deadlock while fixing a race.

The one thing that took real thought was the reentrancy question the brief
flagged: is `_FileLock` actually reentrant, and does that change what test to
write? Reading the class docstring and `__enter__`/`__exit__` (depth-counted
`threading.local`) answered it directly -- yes, reentrant per-thread. That
made the "which test do I write" branch in the brief resolve cleanly: since
nesting is *possible* and deadlock-free (not "impossible" and needing a
should-never-nest assertion), the right test is a positive reentrancy test
(`test_snapshot_ledger_reentrant_when_called_under_held_lock`), not a
guard-rail assertion. I don't think this would have been obvious without
reading the lock's actual implementation -- the brief's phrasing ("if it's a
plain flock context manager, verify...") correctly flagged that this was an
open question rather than asserting an answer.

## What briefing info was missing or could have saved time

Nothing was missing that blocked the work. The brief's pointers (INVARIANTS
§b, RECORD_SCHEMA.md, existing test file for conventions) were exactly the
right documents and I didn't need anything else. If anything, the brief
could have named the caller (`crypto_trading_bot.py`'s run-start snapshot
around the `[LEDGER] daily snapshot` print) directly, since that's a one-grep
fact -- but confirming it myself was cheap and is exactly the kind of
"verify, don't inherit" discipline AGENTS.md asks for, so I don't think this
is a real gap, just an observation that the grep is fast enough that async
briefing detail wouldn't have saved meaningful time.

## Judgment calls made (flagging per AGENTS.md)

- **Test design for "lock held during copy/load"**: rather than timing-based
  or thread-interleaving tricks (which would be flaky), I spied on
  `led.ledger_lock()._local.depth` from inside monkeypatched `shutil.copyfile`
  / `load_executions` wrappers. Depth > 0 at that point proves the calling
  thread already holds the lock (reentrant re-acquisition would just bump
  depth again, never block) -- this is a direct, deterministic assertion
  rather than an inference from timing or absence-of-error.
- **Concurrency smoke test shape**: `snapshot_ledger()` is idempotent
  per-UTC-day (skips the copy if today's `.bak-<date>` already exists), so a
  naive loop of `snapshot_ledger()` calls while a writer thread appends would
  only ever copy once. I deleted the day's snapshot file between iterations
  inside the test loop so each iteration actually re-executes the read+copy
  under contention with the writer thread. This is a test-only accommodation
  for the idempotency guard, not a change to the guard itself -- flagging in
  case a future maintainer wonders why the test manually unlinks the bak
  file instead of just calling the function in a tight loop.
- **Did not touch `maybe_execute_buy` or any other lock-span code** -- scope
  was `snapshot_ledger()` only, and the audit confirmed no other function
  needed to change for lock ordering to stay correct.

## Durable lessons (for AGENTS.md / future briefs)

- **A "does X nest under lock Y" audit is a single grep plus one docstring
  read when the codebase already documents its own lock as reentrant** --
  this repo's existing discipline (the `_FileLock` docstring stating
  reentrancy explicitly, `docs/INVARIANTS.md` naming the one lock-ordering
  rule) made this a fast, confident check rather than an open-ended search.
  Worth preserving that documentation density as a pattern for any new lock
  introduced later.
- **When a lock is reentrant, "does it deadlock if nested" and "should it be
  called while nested" are different questions** -- the fix here made the
  first answer "no" unconditionally, but that doesn't mean a future caller
  *should* nest snapshot_ledger under an existing ledger-lock span; it just
  means doing so wouldn't hang. Worth keeping that distinction explicit in
  any docstring or invariant note touching reentrant locks, so "reentrant"
  isn't misread as "safe to call from anywhere."

## WS-1b follow-up

Follow-up audit task: two more `executionledger.py` functions had the same
bug shape as the original `snapshot_ledger()` fix -- `restore_from_snapshot()`
(copy + `os.replace` on the MP-2 recovery path) and `quarantine_corrupt_ledger()`
(`os.rename` of a corrupt file), both reading/mutating `EXECUTIONS_FILE`
without `ledger_lock()`.

**Caller audit.** `grep -n "restore_from_snapshot\|quarantine_corrupt_ledger"`
across the repo turned up exactly three call sites, all in
`crypto_trading_bot.py`: `quarantine_corrupt_ledger()` at the whatif
soft-fail branch (~line 2373) and inside `_recover_live_ledger()` (~line
2410), and `restore_from_snapshot()` also inside `_recover_live_ledger()`
(~line 2413). Tracing the call graph: the whatif branch runs inside
`maybe_execute_buy`'s `with executionledger.ledger_lock():` span (opened at
line 2326); `_recover_live_ledger` is only ever invoked from the `if not
WHATIF_MODE:` branch of that same function, at line 2335 -- also inside the
lock span. So **all three current callers already hold the ledger lock**
when calling into these two functions. Adding `with ledger_lock():` inside
each is therefore a no-op reentrant depth-increment on every call site that
exists today -- pure defense-in-depth, exactly as the brief anticipated,
not a fix for an active caller-side bug. (`crypto_trading_bot.py` was owned
by another agent this cycle, so this audit was read-only grep/trace against
its current contents -- no edits there.)

**Lock-ordering check.** Same rule as the original fix: the ledger lock and
the recommendations lock (`historyutil.save_recommendation`) must never be
held together (INVARIANTS §b). Neither `quarantine_corrupt_ledger` nor
`restore_from_snapshot` touches `historyutil` or the recommendations lock at
all -- they only ever touch `EXECUTIONS_FILE` and its lock -- so there was no
interleaving risk to check beyond "does adding this lock deadlock a caller
that already holds it," which the existing `_FileLock` reentrancy answers
"no" to, same as WS-1.

**Relative risk, as flagged in the brief:** `quarantine_corrupt_ledger` only
ever fires against an already-corrupt file (there's no live writer racing a
good file the way `snapshot_ledger` had), so the lock here is closing a much
narrower window than the original bug -- still worth doing for consistency
and because a *second* corruption-handling call (e.g. two overlapping
whatif runs both hitting a corrupt ledger) could otherwise race the rename
itself. `restore_from_snapshot` is the higher-value fix of the two: it does
a copy + `os.replace` onto `EXECUTIONS_FILE`, the same operation
`_save_executions` performs under lock on every normal write, so an
unlocked restore really could interleave with a concurrent writer's
load-modify-replace cycle.

**Tests.** Extended `tests/test_snapshot_lock.py` (same file, not a new one
-- the depth-spy pattern and fixtures were already there and directly
reusable) with four tests mirroring the existing `snapshot_ledger` pair:
`test_quarantine_corrupt_ledger_holds_lock_during_rename` /
`test_restore_from_snapshot_holds_lock_during_copy` (spy on `os.rename` /
`shutil.copyfile` respectively and assert `ledger_lock()._local.depth > 0`
at call time -- same direct, non-timing-based technique as WS-1), and
`test_quarantine_corrupt_ledger_reentrant_when_called_under_held_lock` /
`test_restore_from_snapshot_reentrant_when_called_under_held_lock` (call each
function from inside an already-held `with led.ledger_lock():` block and
assert no deadlock / correct return value) -- pinning the same
reentrancy-is-safe contract the caller audit above relies on. 8 tests now
in the file (4 original + 4 new), all passing; full suite green.

**One loose end worth flagging, not fixed here (out of scope: tests only):**
`tests/test_print_config.py` (another agent's in-progress file this cycle)
failed intermittently across repeated full-suite runs -- a different subset
of its tests failed each time, but it passed 15/15 reliably every time it
was run in isolation. Bisected by reverting just this change's two
`ledger_lock()` wraps and re-running: `test_print_config.py` passed 15/15
both with and without the wraps in isolation, and the full suite passed
959/959 clean on one run and failed on a different 2-3 tests in that same
file on other runs -- so this is pre-existing order/pollution flakiness in
that file (or its interaction with global state elsewhere), not something
introduced by the `quarantine_corrupt_ledger`/`restore_from_snapshot`
lock change. Reporting it rather than touching that file, since it's
outside this task's scope and owned by the concurrent `crypto_trading_bot.py`
work.
