# Reflection — P4-B (F2 order-create recovery + F4 analyzer hardening)

Session date: 2026-07-18. First-person, from doing the work — not a status recap.

## 1. Friction / near-misses

- **The existing duplicate-recovery tests almost dictated the wrong design.** F2's
  spec says a recovered order should "proceed down the success path (get_order poll
  → fill row)". My first instinct was to make `_recover_order` always poll
  get_order. That would have broken the two T5 duplicate tests, whose `FakeClient`
  seeds a FILLED order via `list_orders` with an EMPTY get_order queue (any extra
  poll raises `AssertionError`). Resolution: poll get_order **only when the
  recovered order isn't already terminal**. A FILLED recovery needs no round-trip;
  an OPEN one does. Existing tests stay green, spec is honored. This was the one
  real "which reading is right" fork and I want it on record.
- **The tri-state lookup is the whole point of F2 and it's easy to miss.** The old
  `_lookup_order_by_client_order_id` collapsed "list_orders threw" and "no match
  found" into a single `None`. Those are opposite facts: one means *we can't tell*
  (→ `unverified_failure`), the other means *the order was never placed* (→ clean
  `failed`). Splitting them into `(order, lookup_ok)` is small but load-bearing;
  without it the whole "distinct unverified state" requirement is unimplementable.
- **One intentional test break, called out:** `test_scored_record_frozen_across_reruns`
  asserted `'freeze1' in state` — i.e. that state is keyed on the bare record id.
  That IS the F4 collision bug. I changed it to `ta.state_key(r) in state` and
  added `'freeze1' not in state`. It's the only existing expectation I altered.
- **Moving test baseline, as warned.** Dispatch said 521; the suite was already at
  560 (a concurrent agent's `conftest.py` + test files) before I wrote a line. I
  did not chase the delta — I checked my *owned* files and my *owned* tests. The
  file-ownership invariant (AGENTS.md process lesson) is what made that a non-event
  instead of the time-sink the T10 reflection described.

## 2. Guidance quality

- **Gold:** the T5 and T10 reflections named the exact bugs (ambiguous-timeout →
  ledger `failed` while filled; id-only state key; freeze-at-first-scoring). The
  spec's three-outcome breakdown for F2 (found / empty / lookup-failed) mapped 1:1
  onto code. The candle gotcha ("~300 rows, hourly for young / daily for old") was
  already encoded in `CoinbasePriceProvider.price_at`, so at-maturity scoring for
  live runs needed *zero* new network code — I just call the existing `price_at`
  for the coin too, not only the benchmark.
- **A judgment call the spec left open:** on a *clean* rejection (INSUFFICIENT_FUND)
  where the recovery lookup *also* fails, I flag `unverified_failure` even though
  the error clearly says the order never placed. The spec says "attempt lookup on
  ANY failure; if lookup fails → unverified", so I followed it literally. It's the
  fail-safe direction (reconcile --repair re-looks-up, finds nothing, leaves it),
  just slightly noisier. Flagging it here because it's a real semantic choice.

## 3. Design doubts (plainly)

- **Methodology-consistency vs. throwing away good data.** To avoid "silently
  mixing methodologies", if the benchmark's maturity candle is missing I degrade
  the coin to run-time too — even when the coin's maturity price WAS available.
  That discards a real data point for the sake of a clean, single-methodology
  grade. I think honesty > completeness here, but it's debatable.
- **`unverified_failure` never counts as a position** (like `unconfirmed`). If the
  order actually filled, the position is under-reported until `--repair` runs.
  That's the safe direction, but it means reconcile --repair is now load-bearing
  for position accuracy on the unhappy path — and, like the T5 reflection warned
  about `unconfirmed`, *nothing runs it automatically*. It's a manual/cron step.
- **`--repair`'s idempotency rests on "last fill row per ledger_id wins."** Append
  a `filled` repair row after an `unconfirmed` one and the ledger_id reads as
  resolved. Correct only because at most one FILLED row is ever appended per
  ledger_id (the target-finder skips already-resolved ids). If any future writer
  appends a second FILLED for one ledger_id, `positions_from_rows` double-counts.
- **`_looks_like_duplicate` is now nearly dead** — recovery no longer gates on it;
  it only annotates a log line. I kept it (and the runbook step to validate it)
  rather than delete, because the real rejection shape is still uncaptured. A
  reviewer could reasonably argue for deleting it instead.

## 4. Repo improvements (1–2)

1. **A captured-fixtures dir for Coinbase (`tests/fixtures/coinbase/`).** Every
   execution-path task so far has rebuilt response shapes from doc prose + one
   live capture. F2's whole weak spot is that no real duplicate-rejection exists
   as a fixture. The runbook now tells the owner to save one — that dir should
   exist and be the standing home for it.
2. **A tiny injectable exchange-resolver protocol.** I had to hand-roll a
   `FakeResolver` for the repair tests because `BlobbyTrader` mixes read-only reads
   with order placement. A 2-method read-only interface (`poll_order_status`,
   `find_order_by_client_order_id`) that both the trader and a fake implement made
   repair unit-testable with zero network — worth formalizing repo-wide.

## 5. Tradbot behavior notes (owner)

- **At-maturity scoring will move numbers vs. the T10 run.** The old analyzer
  graded on price *whenever it ran*; now it grades on price at `rec_time + 24h`
  from candles. Records scored under the old cadence stay frozen (migration
  discards the v1 state once, re-scores, re-freezes under v2) — so expect a
  one-time reshuffle of verdicts on the first post-P4-B run, then stability.
- **Watch for `scored_at_run_time` in the new methodology line.** If most scored
  rows show up degraded, the coin candles aren't reachable at the maturity horizon
  (illiquid pairs, or beyond the ~300-candle window) — the score is then only as
  fixed-horizon as the old one, and the flag is telling you so.
- **`unverified_failure` in the ledger = "run `reconcile_positions.py --repair`
  now."** It means a live create failed and we couldn't confirm whether money
  moved. It is deliberately invisible to position math until repaired.
