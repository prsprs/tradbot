# RECORD_SCHEMA.md — the recommendation record

The single declaration of "what a recommendation record is" for the **live bot's**
history stack. Verified against the current tree by symbol (line numbers rot here —
cite the symbol, then grep).

There are **two independent history stacks** in this repo (AGENTS.md "check both
stacks"). They share nothing but a hashing convention. Do not conflate them:

| stack | writer | file | reader |
|---|---|---|---|
| **live bot** (this doc, §1–§4) | `historyutil.create_recommendation_record` / `record_recommendation` | `<HISTORY_DIR>/recommendations.json` | `tradeanalyzer` |
| **llm_compare** (§5, separate) | `history/recorder.py` `HistoryRecorder.record` | `<HISTORY_DIR>/llm_compare_history.json` | `HistoryRecorder.get_recent` / `find_by_prompt_hash` only |

`tradeanalyzer.load_records` reads **only** files matching `recommendations*.json`
(`tradeanalyzer.recommendation_files`), so it never touches the llm_compare file.

---

## 1. Live-bot record — field-by-field

Writer: `historyutil.create_recommendation_record`. Every base field below is
**always** written; optional fields are written **only when the argument is not
None** (`if X is not None: record['X'] = ...`), which is what makes an omitted-field
record byte-identical to a legacy v1 record. Readers are `tradeanalyzer` sites
(`score_record.make`, `panel_stats`, `timing_preview`, `provider_attribution`,
`shadow_score`, `confidence_calibration`, `actual_roundtrip_fee_pct`).

**"Written but never read" is called out explicitly** — those fields are provenance
/ display only; nothing in `tradeanalyzer` consumes them today. Precision here is
the point: do not assume a written field is load-bearing downstream.

### v1 base fields (always present)

| field | type | writer detail | reader | semantics / caveats |
|---|---|---|---|---|
| `id` | str | `f"rec_{%Y%m%d_%H%M%S}_{coin}"` | `state_key`, `score_record` (`rec.get('id')`) | **Not unique** — two recs in the same second for the same coin collide. The analyzer never keys on `id` alone; `state_key` hashes `(id, timestamp, coin_symbol, recommendation)`. |
| `timestamp` | str | `now(utc).replace(tzinfo=None).isoformat() + 'Z'` | `parse_timestamp` → `utc_epoch` | **Timestamp contract (load-bearing):** naive-UTC + literal `'Z'`, never an aware `+00:00` offset. `parse_timestamp` strips `'Z'` and parses naive; `utc_epoch` stamps UTC for epoch math. Never `.timestamp()` a stored value (assumes local zone — a real 4h bug). Pinned by `test_timestamp_is_naive_iso_with_trailing_z_not_embedded_offset`. |
| `coin_symbol` | str | verbatim | `score_record` (`coin`), `_is_trading_record` | Presence of this key **and** `price_at_recommendation` is what makes a record a "trading record" (`_is_trading_record`); a record missing either → `NON_TRADING`. |
| `recommendation` | str | `.upper().strip()`; empty → `'UNKNOWN'` | `score_record` (`action`), `panel_stats`, `timing_preview` | `BUY`/`SELL`/`HOLD`/`NONE`/`UNKNOWN`. **`'NONE'` means a blocked panel decision** → `BLOCKED` category, never price-scored. `HOLD` → `NEUTRAL`. Unrecognized non-directional → `EXPIRED_UNSCORABLE`. |
| `price_at_recommendation` | float \| None | real price or **None** (DI-3: failed fetch no longer drops the record) | `score_record` (`rec_price`) | None / ≤0 / non-float → `EXPIRED_UNSCORABLE` reason `no_rec_price`. The key must exist even when the value is None (gates `_is_trading_record`). |
| `bid_price` | float \| None | real bid or None — **never** price copied in (DI-3) | **never read** | Write-only in `tradeanalyzer`. Honest-spread data or None; never fabricated. |
| `ask_price` | float \| None | real ask or None (DI-3) | **never read** | Write-only in `tradeanalyzer`. |
| `llm_source` | str | comma-joined deciding LLM(s), or `'none'` for a blocked decision | `ScoredRecord.llm_source`; `provider_attribution` **legacy fallback only** (records without `vote_details`) | Not necessarily the primary. On v2 records `vote_details` supersedes it for per-provider attribution. |
| `mode` | str | LLM mode (`gemini`…`compare`/`integrate`) | **never read** | Write-only in `tradeanalyzer`. Do not confuse with `trading_mode` — the analyzer's local variable named `mode` reads `trading_mode`, not this field. |
| `consensus` | bool \| None | whether all LLMs agreed (None for single-LLM) | **never read** | Write-only. |
| `discovery_llm` | str \| None | which LLM discovered the coin | **never read** | Write-only. |
| `trading_mode` | str | validated against `VALID_TRADING_MODES` = `{live, whatif, unknown}`; **raises `ValueError`** otherwise | `score_record` (excludes non-live/whatif), `scoring_universe`, `timing_preview`, `positions` join | Default `'unknown'` = "could not verify", never a guess (AGENTS.md "label data honestly"). **`unknown` / missing → `EXCLUDED_UNKNOWN`, dropped from scoring entirely.** New callers should always know their mode. |
| `run_id` | str \| None | process-invocation id (e.g. `run_20260718T195400Z`) | `actual_roundtrip_fee_pct` (join to ledger by `(run_id, coin, side)`) | Joins a record to its execution-ledger fills for the actual-fee lookup. |
| `exchange` | str | written **only if truthy** | `score_record` (`rec.get('exchange')` → price provider), `compute_window_returns` | Optional even in v1. `'solana-dex'` routes pricing to Jupiter. |

### T3 blocked-decision optional fields (written only when supplied)

Populated on panel decisions (directional *and* blocked); legacy callers that omit
them keep the old shape.

| field | type | reader | semantics / caveats |
|---|---|---|---|
| `consensus_state` | str | `panel_stats` (`consensus_state_hist`) | `unanimous` \| `tiebreaker` \| `single` \| `blocked`. |
| `deciding_llms` | list[str] | **never read** | Write-only. LLM(s) whose votes produced the action. |
| `votes` | dict[str,str] | `panel_stats` (per-LLM histogram over blocked rows) | Per-LLM final vote; abstains as `'ABSTAIN(<reason>)'` markers. |
| `block_reason` | str | `score_record` (BLOCKED `reason`), `panel_stats` (`normalize_block_reason`) | Vocabulary is spec'd only by `tests/test_consensus.py` — no enum. `normalize_block_reason` keeps the leading category token. |
| `majority_action` | str | **never read** | Write-only. Measurement only — the most common non-abstain vote; **never** the trade trigger under `REQUIRE_CONSENSUS`. |

### v2 (WS3, schema-v2) optional fields (written only when supplied)

Provenance + full per-provider decision detail. A caller that omits **all** of these
reproduces the exact v1 record shape. Assembled at the call site by
`crypto_trading_bot._record_provenance`.

| field | type | reader | semantics / caveats |
|---|---|---|---|
| `schema_version` | int (`2`) | `score_record` → `ScoredRecord.schema_version` (passthrough; not used for branching) | Absent ⇒ treated as v1 implicitly. WS4 analytics gate on `vote_details` presence, **not** on this field. |
| `vote_details` | dict `{llm: {action, confidence}}` | `score_record` passthrough; **`provider_attribution`, `shadow_score`, `confidence_calibration`, all `policy_*` counterfactuals** | Present on directional **and** blocked panel decisions. `action` = vote string or **None for an abstain**; `confidence` = 0..1 float or **None** (abstain / non-JSON fallback / parse failure). Built by `build_vote_details` over the whole `panel`. **Caveat: some blocked paths carry no `vote_details`** — `no_coin` and `unknown_llm_mode` return a `PanelDecision` with the empty-dict default, so `_record_provenance` writes `vote_details=None` (and hence `models=None`). Presence of `vote_details` is the switch between true per-provider decomposition and the legacy `llm_source` fallback. |
| `prompt_hash` | str (sha256[:16]) | **never read** by `tradeanalyzer` | **Identity, not literal bytes:** hashes the **primary's** default `panelprompts.coin_check_prompt` (gemini/claude/openai byte-shape). grok/perplexity primaries add a preamble, so this is a coin+data+template identity, **not** the exact prompt every provider sent. If per-provider reproducibility is ever needed, this is under-specified (would need per-panelist hashing). |
| `models` | dict `{llm: model_id}` | **never read** by `tradeanalyzer` | `modelregistry`-resolved model IDs for every panelist **in `vote_details`** (`_resolved_models`). **Includes init-failed panelists** — a panelist whose client failed to init still appears in `vote_details` as an abstain, so `models` records the model it *would* have used, not one that ran. Convenient for grouping, arguably dishonest against "label data honestly"; flagged, not blocking. |
| `market_block_ref` | str | **never read** by `tradeanalyzer` | Relative path `market_blocks/<run_id>.json` (`historyutil.market_block_ref`). Relative so it survives HISTORY_DIR redirection. Per-**run** (every coin in a run shares it). |
| `market_block_present` | bool | **never read** by `tradeanalyzer` | Per-**coin**: True iff this coin's frozen block was cached (hence is in the referenced file). Independent of `market_block_ref` (the ref is written even when a given coin's block is absent). |

### WS5 (cycle 2) optional fields (written only when supplied)

Decision fingerprint + honest spread + sampling provenance. Motivation: models
flipped BUY/HOLD on the same coin within minutes; `prompt_hash` + `models`
already pin "same template, same model", so the missing pieces were (a) a hash
of the exact market-data snapshot the panel saw and (b) the sampling params
actually sent. All three follow the optional-field rule (omitted ⇒ byte-identical
v1 record).

| field | type | reader | semantics / caveats |
|---|---|---|---|
| `market_block_hash` | str (sha256[:16]) \| None | **never read** by `tradeanalyzer` | Per-**coin** fingerprint: `historyutil.market_block_hash(block)` = sha256[:16] of the EXACT block string this coin's panel saw — the identical string `write_market_blocks` persists into `market_blocks/<run_id>.json[coin_symbol]`, so a reader can recompute `market_block_hash(blocks[coin])` and **verify** it. None (omitted) when no block was cached for the coin. Distinguishes "same data snapshot, different vote" (model instability) from "different snapshot". Assembled in `_record_provenance` from `MARKET_BLOCK_CACHE`. |
| `spread_pct` | float \| None | **never read** by `tradeanalyzer` | Derived `((ask-bid)/mid*100)` from the honest `bid_price`/`ask_price` (`mid=(bid+ask)/2`), or None when both were not real positive prices — **never fabricated** from one side or a mid/last fallback. Prerequisite data for a future (gated) spread gate; observability only today. Computed by `_spread_pct` at the call site. |
| `sampling` | dict `{llm: dict \| "provider-default"}` | **never read** by `tradeanalyzer` | Per-panelist record of the sampling params ACTUALLY sent on that provider's analysis request — e.g. `{"temperature": 0}` / `{"temperature": 0, "seed": 42}` — or the string `"provider-default"` when the code set nothing. **Honesty over invention:** derived by `_resolved_sampling` from `sampling.record(provider, DETERMINISTIC_SAMPLING)`, the SAME policy table the traders read, so the recorded value equals what the request carried. Under the default (flag off) every entry is `"provider-default"` and every request is byte-identical to pre-WS5. Chosen as a **sibling field** (not nested into `models`) to keep `models`' `{llm: model_id}` shape intact (pinned by `test_schema_v2`). Written deep-copied. |

**Note on `bid_price`/`ask_price` (v1 base fields, above):** WS5 is what finally
populates them with real data. They are captured at record time by the two
`crypto_trading_bot` loops via Coinbase `get_best_bid_ask` (`_honest_bid_ask`) —
the `get_product` payload the record's `price` comes from exposes only
`price`/`mid_market_price`, **no discrete bid/ask** (verified against the SDK
`Product` type), so honest spread data requires that separate read-only endpoint.
`record_recommendation` gained `bid_price`/`ask_price` params that OVERRIDE its
product-attribute fallback when the caller supplies them. Fetch failure / DEX
mode / missing fields ⇒ None (never fabricated), never blocks the decision.

### WS4 (cycle 2) optional field (written only when supplied)

Per-source status of the market-data block the coin's panel actually reasoned
over. Motivation: when Google Trends / LunarCrush 429 (or a source is config-
disabled), the bot degrades gracefully but a record used to carry no trace of
*which* evidence was missing, so different runs reasoned from different subsets
invisibly.

| field | type | reader | semantics / caveats |
|---|---|---|---|
| `data_quality` | dict `{source: {status, detail}}` | **never read** by `tradeanalyzer` | Provenance / display only. Sources: `coinbase`, `fibonacci`, `google_trends`, `cmc`, `social` (Polymarket is a discovery-time coin filter, not a per-coin block section, so it is deliberately absent). `status` ∈ `ok` \| `degraded` \| `failed` \| `skipped`; `detail` is a short free-text string. **Effect honesty (the whole point):** the status reflects what actually reached the prompt — assembled by `crypto_trading_bot.derive_data_quality` from the SAME `summary`/`fib`/`*_status` variables `build_market_block_for_coin` fed into `marketdata.build_market_block`, never an independent re-fetch. `skipped` = disabled by config (DEX mode ⇒ no Coinbase candles; unset `COINMARKETCAP_API_KEY` / `LUNARCRUSH_API_KEY`), distinct from `failed` = attempted-but-nothing-usable (429, empty series). Cached per coin in `DATA_QUALITY_CACHE`; `_record_provenance` writes it (None ⇒ omitted, e.g. a directly-injected block in tests). Also surfaced per-coin in `build_run_summary` / `--json-summary`. Spec'd by `tests/test_data_quality.py`. |

---

## 2. Evolution rules

- **All new fields are optional and default to None.** The writer only stamps a key
  when its argument is not None (`create_recommendation_record`). A caller omitting
  every optional field produces a **byte-identical v1 record** — pinned by
  `tests/test_schema_v2.py::test_v1_record_byte_identical_when_v2_fields_omitted`
  (asserts none of the six v2 keys appear) and, for scoring equivalence,
  `test_v2_record_scores_identically_to_v1` / `test_v1_and_v2_blocked_records_score_identically`.
  The WS4 `data_quality` field follows the same rule — omitted ⇒ absent,
  pinned by `tests/test_data_quality.py::test_record_byte_identical_when_data_quality_omitted`.
  The WS5 fields (`market_block_hash`, `spread_pct`, `sampling`) follow it too —
  pinned by `tests/test_schema_v2.py::test_ws5_fields_absent_when_omitted_byte_identity`.
- **The analyzer tolerates unknown fields** — `score_record` only `rec.get()`s what
  it needs, so adding a field never breaks scoring. But adding a field the analyzer
  should *act* on requires touching `ScoredRecord.make` (see checklist).
- **`trading_mode` is validated at write time** (`VALID_TRADING_MODES`); an invalid
  value raises rather than silently persisting. Pinned by
  `test_invalid_trading_mode_rejected`.
- **Backfill:** `scripts/backfill_trading_mode.py` adds `trading_mode` to legacy
  records that lack it, defaulting to `'unknown'`, preserving every other field
  verbatim, and never overwriting an existing mode (`test_history_integrity.py`).

## 3. Sidecars

- **`market_blocks/<run_id>.json`** — written by `historyutil.write_market_blocks`.
  Shape: a flat `{coin_symbol: block_text}` JSON object. Directory derived from
  **`RECOMMENDATIONS_FILE`** (not the import-time `HISTORY_DIR` snapshot) at call
  time, so HISTORY_DIR redirects and test monkeypatches land it in the same tree.
  Atomic (temp + `os.replace`). **Best-effort by contract:** empty input or any
  write failure returns None and never raises (persisting a snapshot must not abort
  a trading run). Pinned by `test_write_market_blocks_*`.
- **`analyzer_state.json`** (default `<output-dir>/analyzer_state.json`, not
  necessarily under HISTORY_DIR) — the analyzer's **derived** judged-state, not a
  record store. `save_state`/`load_state`, `STATE_VERSION = 4`. Shape:
  `{'version': 4, 'scored': {state_key: {rec_price, current_price, coin_return_pct,
  benchmark_return_pct, fee_floor_pct, fee_source, excess_return_pct, outcome,
  hold_class, methodology, scored_at}}}`. Keyed by the collision-safe `state_key`.
  A file whose `version` ≠ `STATE_VERSION` is **discarded and regenerated** (derived
  data → re-score is safe), which is the migration path — no in-place rewrite.
  Freezing a scored record means re-runs never re-grade against a moved market.
  `hold_class` (WS3, cycle 2) is the derived HOLD counterfactual grade
  (`GOOD_AVOID`/`MISSED_WIN`/`CORRECT_NEUTRAL`/`HOLD_UNSCORABLE`, `None` for
  directional records); it is **purely additive** — a HOLD's `outcome` stays
  `NEUTRAL` and every existing aggregation universe is preserved. v4 bumped from v3
  solely to add it to the frozen shape (a v3 HOLD would thaw with `hold_class=None`).

  **Frozen-field three-site rule (2026-07-21):** every field persisted into
  `analyzer_state` must change in lockstep in three places — the freeze dict in
  `analyze()`, the frozen-reconstruction branch in `score_record`, and it must
  survive a save→load→re-score cycle. The `STATE_VERSION` bump only protects
  against *stale* state, not against a site you forgot — a missed freeze-dict entry
  silently thaws as `None`. Convention: every new frozen field ships with a
  freeze/thaw round-trip test asserting the thawed value equals the fresh-scored
  value (`test_hold_class_survives_freeze_thaw` in
  `tests/test_hold_counterfactual.py` is the template).

## 4. Adding-a-field checklist

1. **Writer:** add the optional param (default None) to *both*
   `create_recommendation_record` **and** `record_recommendation`, and stamp it only
   `if not None` (preserves v1 byte-identity).
2. **Every PanelDecision-bearing call path:** if the value comes from the panel, add
   it to `_record_provenance` (and/or the `PanelDecision` dataclass +
   `build_vote_details`) so *all* return sites carry it — the monolith
   `process_coin_with_comparison` has ~7 distinct `PanelDecision` return sites; grep
   `PanelDecision(` and enumerate by hand.
3. **Analyzer tolerance:** if the analyzer should read it, add it to
   `ScoredRecord` + `score_record.make`; otherwise confirm the analyzer ignores it
   (it will, via `rec.get`). Decide and document read-vs-write-only.
4. **Tests:** extend `tests/test_schema_v2.py` (v1 byte-identity + v2 round-trip
   scoring) and, for validated fields, `tests/test_history_integrity.py`.
5. **This doc:** add the row (type / when present / writer / reader / caveats) and,
   if read-only or write-only, say so.

---

## 5. The SEPARATE llm_compare record (`history/recorder.py`) — do not conflate

Different stack, different file, different reader, **not read by `tradeanalyzer`**.
Writer: `HistoryRecorder.record` → `<HISTORY_DIR>/llm_compare_history.json`
(`{"recommendations": [...]}`). Readers: `get_recent`, `find_by_prompt_hash`.

Record fields (all written every time; None where absent):
`id` (`rec_%Y%m%d_%H%M%S`), `timestamp` (`datetime.utcnow().isoformat() + 'Z'` —
same naive+`Z` shape, via the deprecated `utcnow`), `prompt`, `prompt_hash`,
`mode` (`single`/`compare`/`integrate`), `yes_no_eval`, `choices`, `llms_used`,
`google_trends_keyword`, `reference_files` (list of `{path, filename, size_bytes,
hash}` or None), `round_1_responses`, `round_2_responses`, `final_recommendation`,
`consensus_reached`, `consensus_count`, `flips`, `summary`.

Key differences from the live-bot record:
- **`prompt_hash` here is a real per-prompt-bytes hash** (`_hash_prompt`, sha256[:16]
  of the full prompt) used for dedupe/lookup, and the **full `prompt` is stored**.
  Contrast the live-bot `prompt_hash`, which is a primary-only template *identity*
  and stores no prompt text. The hashing helper is byte-identical between the two
  stacks (`historyutil.prompt_hash` deliberately mirrors `_hash_prompt`), but the
  *inputs* differ.
- **No `trading_mode`, no `run_id`, no market-block sidecar, no execution ledger.**
  This stack never places or simulates a trade.
- Writes are **not** atomic and **not** locked (plain `open('w')` in
  `_save_history`); loads fail *open* to `{"recommendations": []}` on decode error.
  The live-bot stack is atomic + flocked (see INVARIANTS.md).

See **INVARIANTS.md** for the money-path invariants that govern the live-bot stack
(spend caps, lock ordering, the aggregation-universe table).
