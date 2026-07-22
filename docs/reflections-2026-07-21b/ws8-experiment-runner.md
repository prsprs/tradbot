# WS8 reflection: experiment runner (scripts/run_experiment.py)

First-person implementer notes, written at hand-off per the repo's
reflection-harvest convention (AGENTS.md process lessons).

## What I built

`scripts/run_experiment.py` + `tests/test_experiment_runner.py`. Given a spec
JSON (`{name, base_flags, variants, output_dir}`), it runs each variant
**sequentially** via `./venv/bin/python crypto_trading_bot.py ...`, each
against its own fresh scratch `HISTORY_DIR=<output_dir>/runs/<variant>/`,
forces `--trading-mode=whatif --quiet --json-summary` onto every invocation
(never trusted from the spec), never passes `--allow-concurrent`, captures
`--print-config` output per variant, and writes `<output_dir>/manifest.json`
with a per-coin decision matrix and a `comparable` boolean keyed off
`market_block_hash` equality across variants. Files I own only:
`scripts/run_experiment.py`, `tests/test_experiment_runner.py`. I read but
did not edit provider utils or `crypto_trading_bot.py` (owned by a
concurrent agent).

## Symbol anchors (for a reader with a rotted line-number brief)

- `run_experiment.flags_request_live` / `refuse_if_live` / `refuse_if_output_dir_unsafe`
  / `validate_spec` — the three hard-refusal checks, composed in
  `validate_and_refuse` and run BEFORE any subprocess starts.
- `run_experiment.build_effective_flags` — appends `FORCED_FLAGS`
  (`--trading-mode=whatif`, `--quiet`, `--json-summary`) last (so they win
  under argparse's last-occurrence-wins semantics for non-append options)
  and strips any spec-supplied `--allow-concurrent`.
- `run_experiment._run_bot` — the sole subprocess boundary; tests
  monkeypatch this one function.
- `run_experiment.run_variant` — per-variant orchestration: print-config
  probe, then the real run, then fixture collection.
- `run_experiment._collect_variant_data` — builds per-coin
  (outcome, market_block_hash) from `recommendations.json`, and cross-checks
  the record's stored `market_block_hash` against a fresh recompute from the
  `market_blocks/<run_id>.json` sidecar via `historyutil.market_block_hash`
  (the same hash function `write_market_blocks` uses) — warns loudly on any
  mismatch rather than trusting either source blindly.
- `run_experiment.build_comparison` — the `comparable` boolean: true iff
  every variant's hash for that coin is present AND identical.

## Judgment calls (things the spec didn't fully pin down)

1. **`comparable` is false when a coin wasn't analyzed by every variant**,
   not just when hashes actively disagree. A variant that never touched a
   coin contributes `None` for that coin's hash, and `None != <a real hash>`
   makes the matrix say "not comparable." I chose this over silently
   omitting the variant from that coin's row, because differing coin
   coverage across variants IS a reason the decisions aren't directly
   comparable — hiding it would be exactly the kind of "papering over" the
   spec explicitly forbids for hash drift. The `market_block_hashes` map
   still shows `None` for that variant explicitly, so the gap is visible,
   not just a bare `false`.

2. **A single variant with a coin nobody else touched is "trivially
   comparable"** (a hash set of size 1 counts as "all equal"). This only
   matters for a one-variant experiment or a coin exclusive to one variant;
   there's nothing to disagree with, so I didn't want a false "drift"
   signal.

3. **`--allow-concurrent` is silently stripped, not a hard refusal.** The
   task said "refuse (hard error) if ANY of: live flags / history output_dir
   / missing keys" — `--allow-concurrent` wasn't in that refusal list, only
   in the "NEVER pass" behavior list. So a spec that includes it doesn't
   abort the whole experiment; the flag is just filtered out of what
   actually reaches the subprocess (this is also invisible in practice: each
   variant gets its own isolated `HISTORY_DIR`, so the instance-lock file
   `--allow-concurrent` would matter for never collides between variants
   anyway — the flag is inert for this runner's use case even where it
   isn't stripped).

4. **`--print-config` is captured with the SAME effective flags as the real
   run** (including the forced trio), not a bare subset. This means the
   captured config is the literal config that governed the run right after
   it, not some hypothetical "what if we hadn't forced whatif" version.

5. **Defensive env stripping in `_subprocess_env`**: I pop
   `LIVE_TRADING_CONFIRMED` and force `TRADING_MODE=whatif` in the
   subprocess env even though the upfront refusal already guarantees no
   `--live`/`--trading-mode=live` flag ever reaches the command line. Belt
   and suspenders against an inherited shell env doing something surprising
   — `resolve_trading_mode` requires the `--live` flag too, so this is
   provably redundant given the refusal, but it's cheap and matches the
   "fail closed on the money path" spirit even for tooling that only spawns
   whatif processes.

6. **Missing run summary is not fatal.** If a variant's subprocess exits
   non-zero before writing `run_summaries/<run_id>.json` (or never writes
   one), the manifest records `run_id: null`, `summary_path: null`, and that
   variant simply contributes nothing to the comparison matrix — the
   experiment still completes and reports the other variants. Recorded, not
   silently dropped: the human-readable table still lists the variant's
   `exit_code`.

7. **Outcome label preference**: when a run summary exists, its per-coin
   `outcome` field (the richer WS8 vote-outcome label, e.g.
   `BUY->ordered`) is preferred over the raw `recommendation` string from
   `recommendations.json`; the raw recommendation is only a fallback when no
   summary was written at all.

## Near-misses / things I almost got wrong

- I initially considered recomputing `market_block_hash` only from the
  sidecar and ignoring each record's own stored `market_block_hash` field —
  but the task explicitly says to collect "each record's market_block_hash
  if present," and the two could legitimately diverge (e.g. a record whose
  block was evicted from the cache before the sidecar write, or future code
  drift). Cross-checking both and warning on mismatch, rather than picking
  one source silently, matched the repo's "drift is reported, never papered
  over" philosophy better.
- I almost forgot that `--json-summary` is `nargs='?'` with `const=''` — a
  second bare `--json-summary` cleanly overrides an explicit-path one from
  the spec, which is exactly why appending it last in `FORCED_FLAGS` is
  sufficient and doesn't need any extra dedup logic on my part.
- The test file's first import line was briefly broken (imported
  `run_experiment` before adding `scripts/` to `sys.path`) — caught before
  handoff by actually running the suite, not just eyeballing the diff.

## Test delta

Added `tests/test_experiment_runner.py`: 39 tests, all passing. Full suite
after this change: **1091 passed** (fresh collect at hand-off time; per
AGENTS.md, treat this as this session's own baseline+delta, not a diff
against the 1026 baseline stated in the brief, since a concurrent agent was
editing `crypto_trading_bot.py`/provider utils in the same tree).
`import crypto_trading_bot` remains silent (import-purity check re-run at
hand-off).

## What I did NOT do

No real bot invocation anywhere in the test suite (the `_run_bot` boundary
is always the fake). No parallelism, no statistics beyond hash-equality, no
replay-from-sidecar, no LLM calls of its own — all per the stated
non-goals. I did not edit `crypto_trading_bot.py` or any provider util file.
