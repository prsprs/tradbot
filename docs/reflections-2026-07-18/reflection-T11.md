# T11 Reflection — cleanup + repo hygiene (2026-07-18)

Candid working notes from the agent that executed T11. Scratchpad-only; not a repo file.

## 1. Friction / near-misses

**The `--use-fib` spec ambiguity (near-miss #1).** Work item B.1 said "delete the
`--use-fib` flag and its plumbing (superseded — the Fibonacci block is always in the
market data now)." Taken literally, that instruction deletes a *live, documented CLI
feature* of `leading_indicator_tester.py` — `FibTradeFilter`, ~20 call sites, three
manuals' worth of docs — whose Fibonacci logic has nothing to do with `marketdata.py`'s
T9 block. The rationale clause was the tell: "the Fibonacci block is always in the market
data now" is true only of the *main bot's* pipeline, which never had a `--use-fib` flag.
What actually matched the cleanup intent was the tracked 15KB junk FILE literally named
`--use-fib` at repo root (captured stdout of a mis-redirected command), which
EVALUATION_LESSONS_LEARNED describes in exactly those words. I deleted the file, kept the
flag. If I'd pattern-matched on the instruction instead of grepping for what the flag
actually does, I'd have amputated a working feature and the tests wouldn't have caught it
(the tool has no test coverage). Lesson: when a deletion rationale doesn't survive contact
with the code, treat the rationale — not the code — as the suspect.

**The `history/recorder.py` collision (near-miss #2, and I did partially err).** Work item
F said "migrate utcnow() repo-wide"; the DO-NOT-TOUCH list said "anything under history/
... never write/delete." `history/recorder.py` is *code* that happens to live inside the
per-user-*data* directory, so both instructions claimed it. I migrated it first (following
the repo-wide instruction), and only caught the conflict during the final
protected-paths audit — then reverted to byte-identical-to-HEAD. The save was the audit
habit, not foresight. The root cause is a repo smell: `history/` holds both code
(`__init__.py`, `recorder.py`) and never-commit user data. Any path-scoped rule over that
directory is ambiguous for every future agent too.

**Smaller frictions:** (a) B.5 whipsaw — I verified the three CMC helpers dead, deleted
them, then had to restore byte-exactly after the mid-task amendment about symbol-collision
plans. Restoring via `git show HEAD:file` + full-file copy was the only way to guarantee
exactness; Edit-based reconstruction had already drifted on trailing whitespace.
(b) Line numbers in the spec were stale (e.g. "around 4614" vs actual ~4874-shifted
positions) — locating by content was mandatory, as the spec itself warned.

## 2. Guidance quality

**Helped:** AGENTS.md's "verify before and after" block, the explicit venv path, the
side-effect-free-import contract (my cheapest regression tripwire), and "report judgment
calls" — which legitimized deviating from B.1's literal wording instead of silently
complying. The task's CAUTION paragraph on F (isoformat suffix divergence) was exactly
right and shaped the whole migration.

**Wrong/misleading:** Yes, the B.1 rationale was a spec error — it transplanted the T9
main-bot narrative onto an unrelated tool's flag. Also, AGENTS.md rule #3 claims ".gitignore
enforces" the never-commit rule for `live_trades/`, but `.gitignore` had *no*
`live_trades/` entry until I added one. A hard rule that cites nonexistent enforcement is
worse than none: agents will trust it and skip checking.

**Had to discover myself; the next agent shouldn't:** (1) `history/` is mixed code+data —
this belongs in AGENTS.md explicitly. (2) The naive-with-literal-'Z' timestamp convention
is a load-bearing, cross-module contract (`historyutil` writes ↔ `tradeanalyzer.parse_timestamp`
reads ↔ `executionledger` matches on `ts[:10]`) that lived only in one docstring; my new
format-guard tests now pin it, but a one-line AGENTS.md note would help. (3)
`leading_indicator_tester.py`'s dry-run "trades" are print-only stubs — knowing that made
a live smoke test safe; I had to prove it by reading before daring to run.

## 3. Design doubts

**The naive-with-Z convention itself is the debt.** My three migration patterns
(format-only swap; `.replace(tzinfo=None).isoformat()+'Z'`; naive `now` for arithmetic)
preserve it faithfully, but they *entrench* a convention where the timezone lives in a
string suffix and every datetime in the system is secretly naive. `lp_history` proved the
failure mode: one `.timestamp()` call on a naive value and you silently inherit local
time. Yes, the repo should eventually go aware end-to-end — but only as its own migration
with a read-both/write-old compatibility window, because on-disk history spans months and
`parse_timestamp` is naive-only today. Doing it inside T11 would have been reckless.
Lowest-confidence single edit: `lp_arbitrage.run_once`'s return timestamp — I preserved
its no-suffix shape on "isn't parsed anywhere" evidence, which is grep-proof, not
call-graph-proof.

**Also not fully satisfying:** the bypass-leader dry-run does exactly one cycle; a
reasonable alternative reading is "run bounded but respect --duration". I chose the
strictest interpretation (never loop) since dry-run's job is smoke-testing config.

## 4. Repo improvements that would have made T11 faster/safer

1. **Move `recorder.py`/`__init__.py` out of `history/`** (or move user data to
   `history_data/`). Kills the code-vs-data ambiguity permanently — it nearly caused my
   only real mistake.
2. **A frozen "public surface" test or `__all__` for the util modules.** B's
   dead-code verification was grep-archaeology; the B.5 whipsaw happened precisely because
   "no current callers" and "not part of the intended API" are different facts, and the
   repo records only the first.

## 5. Tradbot itself — for the owner

- **Sibling local-time suspects (unaudited):** any naive-datetime `.timestamp()` or
  naive/aware comparison outside the files I touched. `leading_indicator_tester.py`
  mixes `datetime.now(timezone.utc)` (aware) with parsed candle/report times in several
  places I did not audit, and `correlation_tracker.py` + the `dex/` and `lab/` trees were
  outside my F scope entirely. The lp_history bug pattern — write naive, compare via
  `.timestamp()` — is cheap to grep for and worth 30 minutes of someone's time.
- **`leading_indicator_tester.py` has ~50 flags and zero tests.** I fixed the three named
  bugs and verified nothing else. Given `--duration` and `--dry-run` were both silently
  broken in the bypass path, base rates say more flags are broken. Its LiveTrader class
  is real order-placement code living in an untested 5600-line file.
- **The tracked `analysis_*.csv` files are pre-T10 orphans** — no current code writes that
  schema or those filenames. Untracking loses nothing.
- **`trade_errors.json` spans multiple pairs/users** — worth the owner eyeballing before
  untracking, as it's the only live_trades file that aggregates across pairs.
