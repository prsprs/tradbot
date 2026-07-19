# Reflection — P4-D (F7 market-block TTL + trends double-injection, F8 naive-timestamp audit)

First-person, written immediately after finishing. Claude Sonnet 5 agent.

## What almost went wrong

- **A real near-hang from monkeypatching the wrong `time`.** Writing the TTL
  tests, I did `monkeypatch.setattr(bot.time, 'time', clock)` to freeze the
  clock for `build_market_block_for_coin`. `bot.time` IS the process-global
  `time` module (modules are singletons) — that patch froze `time.time()`
  for the ENTIRE pytest process, including pytest's own internals, and the
  run looked hung (killed manually, twice, chasing the wrong theory each
  time). Fix: `monkeypatch.setattr(bot, 'time', SimpleNamespace(time=clock))`
  — rebind only the *module's own name*, never mutate the real module
  object. I know this rule in the abstract; under time pressure I broke it
  anyway.
- **The second, scarier cause: a real self-inflicted network path.** Even
  after fixing the time patch, a full test class still took 21s instead of
  milliseconds. `marketdata.build_market_block` self-fetches CMC/SOCIAL
  data when `cmc_status`/`social_status` aren't passed —
  `test_market_data.py`'s own docstring warns about exactly this and stubs
  it with an autouse fixture. My new file didn't carry that stub, so every
  call attempted a real fetch; the network guard (F5) blocked the sockets,
  but the provider utils' own retry/backoff (unaffected by my `bot.time`
  patch) turned each blocked call into several real seconds — slow enough
  to be indistinguishable from a hang from outside. Fixed by copying the
  stub fixture verbatim; the warning was sitting in a sibling file's
  docstring the whole time and I still had to hit the wall to internalize
  it.
- **F7b's literal instruction ("remove the vestigial trends_data params")
  would have broken tests in two files I don't own.** `tests/test_framing.py`
  (mine) and `tests/test_market_data.py`/`test_structured_requests.py`
  (not mine) all call `send_trend_check_request`/`send_integrated_trend_check`
  directly with a real `trends_data` value — a genuinely tested T7 feature
  (trends-normalization disclosure), independent of T9's market-block work.
  Deleting the param would have been the exact "prior task nearly deleted a
  live feature on a stale rationale" failure mode AGENTS.md warns about,
  except this time the destructive edit would ALSO have broken another
  agent's in-flight test file. Caught by grepping every call site across
  the whole `tests/` directory before touching anything, not by reading the
  spec sentence twice.

## Judgment calls I want reviewed

- **F7b landed as an orchestration-layer guard, not a parameter deletion.**
  `get_llm_response` now zeroes `trends_data` before forwarding it to a
  provider call whenever a market block is cached (the only place a real
  block AND real trends_data could co-occur), but the provider utils keep
  their `trends_data` parameters — they're live, tested API surface. This
  satisfies "no double-injection path" without the literal "remove the
  params" instruction; I think it's the right read of "keep
  genuinely-used parameters — verify before deleting" one sentence later
  in the same spec, but it's a different-shaped fix than asked for and the
  owner should confirm the trade-off.
- **MARKET_BLOCK_FETCHED_AT is a separate dict, not `(block, ts)` tuples
  inside MARKET_BLOCK_CACHE.** The natural design bundles them; I split
  them because `test_market_data.py` (out of scope) asserts
  `cache['BTC'] == block` and injects raw strings directly into
  `MARKET_BLOCK_CACHE`. Correct given the constraint, but it's a
  file-ownership-shaped workaround rather than the cleanest data
  structure — worth revisiting if that test file's assertions ever change.
- **900s (15 min) TTL default** — inside the spec's "10-15 min" range but
  arbitrary within it; no empirical basis, since the bot doesn't loop
  in-process today (this whole fix is forward-looking hardening for a
  usage pattern that doesn't exist yet).

## Guidance quality

- The T9 reflection handed me both fixes' exact shape before I opened the
  file: "Global cache, no TTL" and "Dual trends paths are a foot-gun" (with
  the double-injection mechanism spelled out) meant I was verifying and
  implementing, not discovering. Materially faster than starting cold.
- "Expect overall test counts to drift... not your bug" was accurate and
  load-bearing — the suite moved from 560 to 580 before I touched anything
  (another agent's work landing), and the ownership-list framing meant I
  didn't burn time proving the delta wasn't mine.
- Gap: nothing in the task or AGENTS.md flagged the CMC/SOCIAL self-fetch
  trap for a *new* test file specifically — it's documented once, locally,
  in `test_market_data.py`'s docstring. A repo-wide conftest.py fixture
  (autouse, not per-file-opt-in) would make this class of near-miss
  structurally impossible instead of tribal knowledge.

## Repo improvements that would have materially helped

1. **Move the CMC/SOCIAL self-fetch stub to `tests/conftest.py` as a
   repo-wide autouse fixture**, the same way F5's network guard is. Every
   new file touching `build_market_block`/`build_market_block_for_coin`
   currently has to know to copy `test_market_data.py`'s local fixture; a
   shared one removes the trap instead of relying on the next agent reading
   the right docstring at the right time.
2. **A one-line AGENTS.md testing convention**: never
   `monkeypatch.setattr(some_module.some_stdlib_module, attr, fake)` — patch
   the importing module's own name instead. Generic Python footgun, not
   tradbot-specific, but it cost real time here and would bite whoever next
   fakes `time`, `random`, or `datetime` the same way.

## Tradbot observations

- F7's audit reinforced a pattern from the SYNTHESIS doc: "vestigial" claims
  need call-site verification, not just intent verification. `trends_data`
  really was dead in the *live* orchestration path (T9 folded it into the
  block) but very much alive as tested API surface one layer down — both
  things are true at once, and only grepping every test file caught it.
- F8 came back clean: `leading_indicator_tester.py` (46 datetime call
  sites), `correlation_tracker.py` (16), and `dex/` (only `token_cache.py`
  touches datetime, already fixed pre-task) all use
  `datetime.now(timezone.utc)` consistently, with no `.timestamp()` calls
  on naive datetimes and no remaining `datetime.utcnow()`. The two
  `fromisoformat` calls in `leading_indicator_tester.py` correctly do the
  `.replace('Z', '+00:00')` dance before arithmetic. A clean audit across
  ~8,500 lines of legacy trading-experiment code is itself a useful data
  point: the lp_history bug pattern didn't spread as far as the F8 task's
  framing worried it might.
