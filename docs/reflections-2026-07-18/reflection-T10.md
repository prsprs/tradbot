# Reflection — T10 (analyzer overhaul + what-if cadence runbook)

Session date: 2026-07-18. Written from direct experience implementing T10; not generic advice.

## 1. FRICTION — what slowed me down or nearly bit me

- **The moving baseline.** The task said "444 tests, 0 xfail" and I confirmed 444 at start.
  At the end the suite collected 517 — my 38 plus ~35 that appeared from concurrent agent
  work in the same working tree (test files like `test_voteschema.py`, `test_market_data.py`
  show as untracked; they were being added while I worked). I burned real time proving the
  extra tests weren't mine: per-file `--co -q` counts, three collection runs for
  determinism, grep for who imports my modules. Near-miss: I almost reported "test count
  doesn't reconcile" as a failure of my own change. Parallel agents sharing one working
  tree makes "N tests before / M after" a weak invariant — a per-agent list of *which
  files* they own would be a stronger contract.
- **`history/test_expected_output.csv` is a trap for this task.** The task said "check
  whether your changes affect its documented flow." They don't just affect it — the fixture
  records predate T2, carry no `trading_mode`, so the new analyzer classifies ALL of them
  `excluded_unknown`. The "expected output" is now expected to be *empty scoring*. If I had
  tried to preserve that CSV's shape I'd have contorted the design; instead I documented it
  as legacy in OPERATIONS_MANUAL.md. The docs pointer ("around lines 475-480") was accurate,
  which helped.
- **`load_dotenv()` at the top of the old `tradeanalyzer.py`** was a module-level side
  effect. The repo's own rule ("import must be side-effect-free") applied to
  `crypto_trading_bot`, but the bot now imports `tradeanalyzer` — if I'd kept the old
  header, importing the bot's main() path would have re-read `.env` mid-run. Caught it on
  the rewrite, but it's exactly the kind of thing a checklist wouldn't flag because the
  rule was scoped to one file.
- **`--now` handling in `cli_main`**: my first version was a one-line conditional
  expression with a precedence bug risk (`A or B if C else B`). I rewrote it as an explicit
  if/else immediately after writing it. Trivial, but it's the closest I came to shipping a
  wrong-behavior line.
- **zsh globbing** ate `grep --include=*.py` (unquoted glob → "no matches found"). Minor,
  but it cost a retry; quote globs in this environment.

## 2. GUIDANCE QUALITY

- **What helped most**: AGENTS.md's "API gotchas" section is genuinely load-bearing — the
  measured 2.4% round-trip fee and "fees ~1.2%/side" line is the empirical basis for the
  fee floor and the ×2 round-trip estimate I used for ledger fees. Also
  `executionledger.py`'s docstring is the best schema doc in the repo; I designed the
  run_id join entirely from it, zero spelunking.
- **What was missing**: nothing tells you the ledger records *only BUY fills today*. That
  fact (found in `positions_from_rows`'s comment) forced the "double the entry fee"
  judgment call. The next agent touching fees should be told: exit fees do not exist in
  the data yet; every round-trip number is an estimate.
- **What I had to discover myself**: Coinbase candles cap at ~300 rows/request, which
  bounds how far back `CoinbasePriceProvider.price_at` can fetch the BTC benchmark price
  (I capped hourly lookback at 12 days, daily at 290). This constraint is in no doc; it
  shapes what "0h to infinity" can actually score with live data. Also: the block_reason
  vocabulary (`abstain(...)`, `sub_quorum: ...`, `disagreement`, `tiebreaker_*`,
  `exception`) lives only in `tests/test_consensus.py` assertions — I reverse-engineered
  `normalize_block_reason` from test greps. That vocabulary should be a constant in the
  bot or documented next to PanelDecision.

## 3. DESIGN DOUBTS — said plainly

- **The sidecar `analyzer_state.json` freeze is the weakest part of my design.** It keys on
  record `id`; ids embed a timestamp+coin and *should* be unique, but nothing enforces it.
  Two records in the same second for the same coin would collide and one would inherit the
  other's frozen verdict. A content-hash key, or a judged flag written into the record
  (which the hard rules barred me from doing to real history), would be sounder.
- **Freezing captures outcome at first scoring, which makes the score horizon
  "whenever the analyzer first ran after 24h"** — not a fixed 24h/7d window. Two identical
  decisions scored 25h and 90h after the fact are graded over different windows. The
  honest fix is scoring against the price *at maturity* (needs historical candles for
  every coin, not just the benchmark). Out of scope, but the current numbers are
  cadence-dependent and the owner should know that.
- **SELL symmetric grading** (benchmark_return − coin_return − fee) is defensible but
  debatable: a SELL of something you hold avoids the exit fee question differently than a
  short would. With no SELL path in the bot today it's untestable against reality.
- **`CoinbasePriceProvider` is deliberately untested** (network). Its candle-cache keys on
  (coin, granularity) but not days — a subtle staleness if someone extends it. I left it
  best-effort-degrade-to-None on purpose, but it's the least-verified code I shipped.

## 4. REPO IMPROVEMENTS that would have made T10 materially faster/safer

1. **A shared synthetic-history fixture builder** (`tests/fixtures/history.py` with
   `make_rec()`, `make_ledger_pair()`). I wrote my own `rec()`/ledger helpers; T2, T3, T5
   and T10 tests all hand-roll near-identical record dicts. One canonical builder would
   also make schema drift (new fields) a one-file change.
2. **Split `crypto_trading_bot.py`.** AGENTS.md already calls it the standing refactor
   candidate; T10 confirms it: even a 15-line, deliberately-minimal edit to a 2500-line
   file that another agent is queued to edit next is the highest-collision-risk moment of
   the whole task. `parse_args` alone moving to its own module would have removed most of
   my edit surface.

## 5. TRADBOT ITSELF — for the owner's attention

- **The real history is thin and mostly unscoreable by the new rules**: at analysis time,
  the mature real records are dominated by `unknown` trading_mode (backfill-era) and the
  scored-live population is single-digit. The whatif cadence isn't optional if you want
  statistics — per my cost table, weeks of 4×/day runs are needed before win-rates mean
  anything. Don't read the first analyzer reports as signal.
- **Benchmark-relative grading will look brutal vs the old analyzer.** The old
  `calculate_outcome` called any BUY with a positive move CORRECT. Under T10 rules a BUY
  must beat BTC *and* 2.4% fees; in a rising market most old "CORRECT" BUYs regrade as
  losses. Expect the accuracy numbers to drop sharply — that's the fix working, not a
  regression, but it will be jarring next to old CSVs.
- **Real ledger fee data matters more than expected**: in my demo the actual fee (1.2%
  round-trip on a real-shaped fill) was half the assumed floor — enough to flip marginal
  decisions between WIN and LOSS. The more live fills exist, the less the 2.4% assumption
  distorts the scorecard; another quiet argument for the ledger being on the money path.
