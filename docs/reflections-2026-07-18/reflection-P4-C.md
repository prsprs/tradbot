# Reflection — P4-C (F3 CMC id-lookup + F5 network guard + F9 schema preflight + README)

First-person, written immediately after finishing. Fable 5 agent.

## What almost went wrong

- **CMC id-based queries were an unverified assumption.** The spec said "query
  quotes/latest by id" but nothing on record confirmed the response shape
  stays a LIST when you switch from `symbol=` to `id=` params (v1/v2 CMC
  endpoints famously key `data` by id as a *dict* instead). I could easily
  have written the whole parser against an assumed shape and shipped a bug
  that only a real id-based call would catch. Spent one of my two authorized
  CMC calls confirming it live (`id=1` for BTC) before writing a line of
  parsing code — same shape, no branch needed. Cheap insurance; would have
  been an expensive mistake to skip.
- **`coinmarketcaputil.SYMBOL_TO_CMC_ID` is a shared, mutable, module-level
  dict**, and `auto_resolve_symbol` writes discoveries back into it by
  design. My first draft of the "unmapped symbol resolves via the map
  endpoint" test would have permanently added `'ONDO': 21159` to that dict
  for the rest of the pytest process, silently changing later tests'
  assumptions about what's "unmapped." Caught it before running anything by
  reading the T12/T13 reflection's near-miss about a *different* shared-state
  trap first — same failure family, different function. Fixed with a
  monkeypatch-swapped-copy fixture (`isolated_symbol_cache`) so the mutation
  is real for the test but invisible afterward.
- **I almost made the F5 guard silent-degrade instead of loud-fail.** My
  first instinct was to have the blocked socket functions return a fake
  closed-connection error a caller might catch and treat as "network down,
  proceed anyway." That's the T12 near-miss repeated at a lower layer — a
  guard that "succeeds" at hiding a bug instead of surfacing it. Rewrote to
  raise a named `NetworkBlocked` with the test's nodeid in the message.

## Judgment calls I want reviewed

- **F3's disclosure-not-omission choice.** When a symbol can't be resolved to
  an id, I still render the CMC section (symbol-query fallback) with an
  `AMBIGUITY WARNING` appended, rather than omitting the section entirely.
  This matches the repo's existing "absence is always disclosed" pattern, but
  a stricter reading of "never silently trust data[0]" could argue an
  *unverifiable* asset's numbers shouldn't reach the prompt at all, caveat or
  not — a model under time pressure might anchor on the numbers and skim past
  the warning line. I went with disclosure because that's the established
  house style everywhere else in `marketdata.py`; flagging the alternative.
- **F9's schema-probe token budgets are estimates, not measurements.** I gave
  Claude/OpenAI 1024 tokens (vs. production's 4096) and left Gemini uncapped,
  reasoning from the AGENTS.md "reasoning models can eat a small budget"
  gotcha rather than from any empirical ceiling. My one real run passed clean
  for all three (evidence below), but that's one data point, not a proof the
  budget never starves a probe under heavier reasoning load.
- **Abstain counts as probe success, not failure.** `voteschema.parse_vote`
  returning a Vote with `abstain=true` makes the schema probe `ok=True` — I
  read "validates the response parses as a vote" as testing the *contract*,
  not the *content*. A narrower reading ("prove the model can actually vote")
  would disagree. I think mine is right (voteschema.py itself treats abstain
  as first-class, not a failure), but it's a real interpretation choice.

## Guidance quality

- The task handed me the exact prior reflection lines that motivated F3 and
  F5 (T12's "worth revisiting" on id-lookup, its "would have materially
  helped" on a global guard) — turning a design decision into "implement what
  the last agent already scoped" saved real time and avoided re-litigating
  settled ground.
- Small gap: the spec didn't say whether the Gemini schema probe should
  include the `google_search` grounding tool (production's
  `gemini_structured_config` does). I left it out since the schema *contract*
  is what's under test and grounding is a separately-verified concern — but
  this wasn't spelled out either way, so a different agent might reasonably
  have included it.

## Repo improvements that would have materially helped

1. **The off-limits-`crypto_trading_bot.py` constraint keeps forcing the same
   shape of workaround.** T12/13 hit it (self-fetching `build_market_block`
   instead of cache-injected params); I hit it again in F9 (a real
   `schema_probe` capability with nowhere to attach a CLI flag, "wiring comes
   later" by necessity). This is now logged twice in two different modules —
   worth promoting from "standing refactor candidate" to an actually
   scheduled task, e.g. extracting `main()`'s per-coin analyze/preflight
   wiring into a smaller orchestration module editable without touching the
   money-path file.
2. **`coinmarketcaputil._rate_limit()`'s throttle is shared across BOTH the
   map lookup and the quote fetch** with no distinction. F3 means a
   genuinely-new symbol now pays two throttle slots (map + quote) in one
   `fetch_cmc_status` call instead of one. Fine at today's call volume, but
   worth a comment or split-counter if CMC calls ever scale up.

## Tradbot observations

- Live evidence the fix actually works, not just the mocks: the static cache
  resolved BTC→1 for free (no network), and the `/v1/cryptocurrency/map` call
  for `ONDO` (not in the static map) correctly found id 21159 at 0 credits —
  confirms both branches of `_resolve_cmc_id` on real data, not fixtures I
  wrote myself.
- All three schema probes (gemini-3.1-pro-preview, claude-opus-4-8, gpt-5.5)
  passed clean on the one real run, latencies 3.4s–6.8s — no sign of
  structured-output contract drift as of 2026-07-19. A future
  `--schema-preflight` CLI flag would add single-digit seconds to startup,
  not materially slow the bot.
- The network guard's ~2s full-suite runtime didn't move at all with it
  active — strong indirect confirmation the suite really is network-free
  today, not just believed to be (AGENTS.md's own wording softened to
  "believed network-free" before this landed).
