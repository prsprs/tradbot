# WS-4 reflection: structured per-source `data_quality`

_First-person implementer reflection, 2026-07-21b. Improvement cycle 2, WS-4._

## What shipped

A per-coin `data_quality = {source: {status, detail}}` over five block sources
(`coinbase`, `fibonacci`, `google_trends`, `cmc`, `social`), derived at
market-block assembly time and threaded into (a) `build_run_summary` /
`--json-summary` per coin and (b) the recommendation record as a new optional
field. Symbol anchors:

- `crypto_trading_bot.derive_data_quality` — the pure mapping helper.
- `crypto_trading_bot.DATA_QUALITY_CACHE` / `DATA_QUALITY_SOURCES` — parallel
  per-coin cache + source list.
- `crypto_trading_bot.build_market_block_for_coin` — now fetches CMC/SOCIAL
  itself and passes them into `marketdata.build_market_block`, then derives +
  caches data_quality from the exact same status dicts.
- `crypto_trading_bot._record_provenance` — carries `data_quality` (both
  analysis loops call it, so both get it).
- `crypto_trading_bot.build_run_summary` — new optional `data_quality_by_coin`.
- `historyutil.create_recommendation_record` / `record_recommendation` — new
  optional `data_quality` param, stamped only when not None.
- `tests/test_data_quality.py` (new, 19 tests). `docs/RECORD_SCHEMA.md` updated.

Suite: 959 → 978 (+19), all green. Import purity holds.

## The one real design decision: where to capture CMC/SOCIAL status

The trap I nearly fell into: re-fetching or re-checking CMC/social status in a
second pass to build data_quality. That would have been a *parallel re-check*
that could disagree with what the block actually carried — exactly the
"effect honesty" failure the brief warned about. `marketdata.build_market_block`
self-fetches CMC/social when the caller passes None, so the honest statuses
lived *inside* marketdata, out of reach.

The fix that keeps honesty AND stays out of the off-limits marketdata.py:
`build_market_block_for_coin` now fetches CMC/social explicitly and *passes them
in*. Because build_market_block only self-fetches when the arg is None, passing
them leaves the rendered block byte-identical and adds zero network calls (the
market-data test `test_cmc_and_social_fetched_once_per_coin_across_two_calls`
still sees exactly one fetch each — verified). data_quality is then derived from
those exact dicts plus the same `summary`/`fib`/`reason` that decided the
primary sections. One set of variables, one block, one data_quality.

## Judgment calls the owner should review

1. **`skipped` vs `failed` for CMC/social keys.** A missing API key →
   `skipped` (config-disabled), a 429/HTTP error with a key present → `failed`.
   I derive this from the config variable (`coinmarketcaputil.CMC_API_KEY`,
   `LUNARCRUSH_API_KEY`) rather than string-matching the reason. The motivation
   (429s = failed) fits, and "not configured" reads more like a deliberate
   reduced-source run than a broken one. Debatable: one could argue an unset
   key is still "the data didn't reach the prompt = failed". I chose the
   config-intent reading because the brief explicitly named config-disabled ⇒
   skipped.

2. **`degraded` for three partial-data cases:** fib-failed-but-price-present,
   Google Trends below measurement floor, and CMC symbol-only lookup (the F3
   asset-ambiguity path, which the block itself already flags as an AMBIGUITY
   WARNING). These reach the prompt but at lower confidence — `ok` would
   over-claim, `failed` would under-claim.

3. **`fibonacci` = `skipped` when there are no candles.** With no market data
   the block emits no FIBONACCI line at all, so fib was never attempted. I
   called that `skipped` (with detail pointing at coinbase) rather than
   `failed`, because nothing about fib itself broke.

4. **Google Trends `unavailable` → `failed`.** There's no config gate to
   disable Trends (it's always attempted in `build_market_block_for_coin`), so
   an empty/absent series is a failure to get data, not a skip. Only
   `below_floor` is `degraded`.

5. **Polymarket deliberately excluded.** The brief listed it, but Polymarket is
   a discovery-time coin *filter*, not a per-coin market-block section — it
   never reaches an analysis prompt, so it has no honest per-coin status. I
   documented this in `DATA_QUALITY_SOURCES`' comment and RECORD_SCHEMA rather
   than inventing a status for it.

6. **Cached-vs-fresh for LunarCrush: NOT surfaced.** The brief said do it "if
   cheap". The cache-hit age is printed inside marketdata (`[LUNARCRUSH] cached
   Ns ago`) but is not returned in the status dict, and exposing it would mean
   refactoring marketdata.py (off-limits, and explicitly discouraged). So a
   cache hit and a fresh fetch both read `social: ok`. Left undone on purpose.

## Near-misses / what I checked so I didn't regress

- The existing `test_run_summary.py::test_build_run_summary_shape_and_content`
  asserts coin entries by **exact dict equality**. Adding `data_quality`
  unconditionally would have broken it. Making the field appear only when a
  coin has cached data_quality (and the whole arg default None) keeps every
  pre-WS4 entry byte-identical — same optional-field discipline as the record.
- Byte-identity of the record when `data_quality` is omitted is pinned
  (mirrors the six v2 keys), so the 109 existing records and the analyzer are
  untouched.
- Only `crypto_trading_bot.py` and `historyutil.py` were edited (my exclusive
  files) plus the new test and the schema doc. marketdata.py untouched.
