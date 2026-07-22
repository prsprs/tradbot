# Synthesis — improvement cycle 2 reflections (2026-07-21, evening)

Distilled from per-agent reflection files in this directory plus direct introspection
round-trips with all cycle agents. Items marked **→ AGENTS.md** or **→ INVARIANTS.md**
were promoted to those docs this cycle; the rest are recorded here for the owner.

## Durable lessons promoted to repo guidance

1. **Read-that-persists needs the ledger lock** (WS-1). The locking contract was phrased
   around writers; `snapshot_ledger` was a reader-that-persists and fell outside the
   framing until audited. Generalized rule: any function that reads EXECUTIONS_FILE to
   persist a copy or derivative (snapshot, backup, export, restore) must hold
   `ledger_lock()` around read+persist, same as writes. **→ AGENTS.md**

2. **Lock-primitive selection guide** (WS-2). `_FileLock`/`ledger_lock` is blocking +
   reentrant — for writers that should queue. A guard that must REFUSE a second holder
   (single-instance) needs non-blocking `flock(LOCK_NB)` — do not adapt `_FileLock`.
   flock frees on process death; a PID written to a lock file is informational only,
   never a liveness gate. Also load-bearing and previously undocumented: two `open()`s
   of the same lock file in ONE process genuinely contend under flock — this is what
   makes single-process contention tests honest. **→ AGENTS.md / INVARIANTS §b**

3. **The conftest network guard blocks more than the network** (WS-7). It patches
   `socket.socket.connect`/`create_connection`/`getaddrinfo` globally, which breaks
   `multiprocessing.Manager()` (local Unix socket) as a side effect. Use plain files or
   pipes for inter-process test coordination. Invisible from the module under test;
   only discoverable by reading conftest.py. **→ AGENTS.md (test-authoring traps)**

4. **Never `git stash` on a shared tree; use `git worktree`** (WS-7, from its own
   near-miss). The existing stash ban lacked a stated alternative for the legitimate
   need ("run tests against a clean tree to prove a failure predates my edits"), so an
   agent reached for stash anyway. Positive alternative now documented:
   `git worktree add <dir> <rev>` or `git show <rev>:<file>`. **→ AGENTS.md**

5. **Frozen-state fields live in three sites** (WS-3). Every field persisted into
   analyzer_state must change in lockstep in: the freeze dict in `analyze()`, the
   frozen-reconstruction branch in `score_record`, and survive save→load→re-score.
   The STATE_VERSION bump only protects against stale state, not a forgotten site.
   Convention: every new frozen field gets a freeze/thaw round-trip test
   (`test_hold_class_survives_freeze_thaw` is the template). **→ RECORD_SCHEMA.md**

6. **Gate-placement decision rule, stated once** (docs agent). The rule was correctly
   applied in three design docs but canonical nowhere: does the check read-then-write
   the ledger (TOCTOU)? → `maybe_execute_buy`, under the lock. Decision-quality only?
   → `gate_and_maybe_buy`, lock-free. **→ INVARIANTS §c**

7. **Brief with REQUIRED properties, not mechanisms** (WS-2). "Reuse `_FileLock`" cost
   a deviation negotiation; "REQUIRED: non-blocking refusal, released on death;
   SUGGESTED starting point: _FileLock (verify fit)" would have cost nothing. Adopted
   mid-cycle for WS-5c/WS-9 with visibly smoother results. Mark unverified spec
   assumptions as such — two briefs this cycle asserted code facts that were wrong
   (grade() band constant; product-payload bid/ask). **→ AGENTS.md (briefing section)**

8. **Mid-cycle full-suite runs on a shared tree are advisory only.** Parallel agents
   observed each other's in-flight test files failing and burned effort on attribution.
   Only phase-boundary suite runs on a quiescent tree are evidence. **→ AGENTS.md**

## Owner follow-up queue (not actioned, needs decisions)

1. **Legacy per-provider attribution wart now extends to HOLD quality** (WS-3): v1
   records attribute to the comma-joined pseudo-provider ('gemini,claude'); per-provider
   HOLD quality is only truly per-provider on v2 records. Same owner decision as the
   existing attribution wart.
2. **live+whatif same-HISTORY_DIR coexistence** (WS-2): per-mode instance locks allow
   it; benign today only because cap tallies are mode-filtered. Deserves a conscious
   decision if any future feature makes whatif rows affect live accounting.
3. **main() startup ordering is an untested contract** (WS-2): dotenv → parse → resolve
   mode → instance lock → snapshot → clients. Nothing pins "lock before network." A
   lightweight ordering guard/test is a candidate for next cycle.
4. **openai/grok deterministic-sampling knobs** (WS-5): left provider-default to avoid
   400s on reasoning models; a one-line promotion in `_DETERMINISTIC_KNOBS` once a paid
   probe clears them.
5. **LunarCrush cached-vs-fresh not surfaced in data_quality** (WS-4/WS-7 seam): cache
   age isn't in the status dict; exposing it needs a small marketdata refactor. Cache
   hits currently read `social: ok`.
6. **Design-doc template gap** (docs agent): the house has shapes for greenfield and
   modification specs but not for deliberately-premature designs gated on a data
   prerequisite; SPREAD_GATE_FEATURE.md is the first example of that third shape.
7. **`rec_price` type inconsistency on unscorable HOLDs** (WS-3): float on the scorable
   path, raw value on the unscorable path. Harmless today; flagged.
8. **From the adversarial review (all NOTE-level, none gating):** instance lock is
   defeatable by deleting the lock file mid-run (inherent flock-on-path; one line for
   OPERATIONS_MANUAL); LunarCrush topic cache keys embed an unsanitized remote `name`
   (sanitize the slug); `cached_call` holds its flock through the fetch (~1 min worst
   case per key — bounded, prompt-feeding only); bid/ask vs `spread_pct` mild field
   asymmetry when the honest fetch fails but product attrs exist.

## Review + verification outcomes

- **Adversarial money-path review (Fable 5): no blockers; SAFE TO PROPOSE FOR COMMIT.**
  The decision→order span is byte-level unchanged except comments; live arming is
  strengthened (instance lock), not weakened; all new record fields optional with
  passing byte-identity pins.
- Its one SHOULD-FIX — env-supplied `DISCOVERY_UNIVERSE` bypassing argparse `choices`
  validation (banner claims a universe the prompt silently ignores) — was **fixed the
  same evening**: `parse_args` now fails closed on an invalid universe value, with two
  new tests (`test_discovery_universe_invalid_env_fails_closed`,
  `test_discovery_universe_env_case_insensitive`). Suite 1091 → 1093.
- **Verification pass: 10/10 checks PASS**, including three consecutive 1091-green
  full suites (no flakiness reproduced), a real end-to-end whatif run (Gemini, BTC)
  with the stored `market_block_hash` matching an independent recomputation, honest
  bid/ask/spread captured, deterministic sampling recorded, and zero writes to the
  repo's real `history/`.

## Cycle metrics

- Suite: 893 → 1093 (+200 tests), green at every phase boundary, import purity intact.
- 11 implementation/docs agents + 2 review/verification agents; zero file conflicts.
- 2 follow-up workstreams (WS-1b, WS-9b) originated from agent introspection, not from
  the original plan — the introspection round-trip paid for itself in code, not prose.
