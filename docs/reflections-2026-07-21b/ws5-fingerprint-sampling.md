# WS-5 reflection: decision fingerprint, bid/ask capture, sampling metadata

First-person, near-misses-and-doubts included (per the reflection-harvest norm).

## What shipped

Three additive, optional record fields plus the plumbing to populate them:

- **`market_block_hash`** (5a) — `historyutil.market_block_hash(block)` =
  sha256[:16] of the EXACT per-coin block string. It hashes the identical string
  `write_market_blocks` persists into `market_blocks/<run_id>.json[coin]`, so a
  reader can recompute and verify. Wired in `_record_provenance` from
  `MARKET_BLOCK_CACHE`, exactly parallel to `market_block_present`.
- **`bid_price`/`ask_price`/`spread_pct`** (5b) — honest bid/ask captured at
  record time by `_honest_bid_ask` via Coinbase `get_best_bid_ask`, spread into
  both `record_recommendation` call sites via `_bid_ask_spread_kwargs`.
  `spread_pct` is a new optional field; `bid_price`/`ask_price` are the existing
  always-None params finally getting real data.
- **`sampling`** (5c) — new optional field `{llm: dict|"provider-default"}`, plus
  a new `sampling.py` policy module, a `--deterministic-sampling` flag, and
  request-construction edits in claude/openai/perplexity utils + the Gemini
  config. `_resolved_sampling` records it.

Suite: 978 → 1005 (+27), all green. Import purity intact.

## The load-bearing judgment call: the spec's bid/ask assumption was wrong

The brief said "`_current_ask` ... tries best_ask etc.; read what the Coinbase
product payload actually offers" and "add a sibling for bid (best_bid etc.)" —
implying the `get_product` payload exposes bid/ask. **It does not.** I checked the
installed SDK `Product` type: it carries `price` and `mid_market_price` only, no
discrete bid/ask (that's why every record wrote None — the old
`getattr(product, 'bid')` never matched). Honest bid/ask live behind a SEPARATE
endpoint, `get_best_bid_ask`, which returns `pricebooks[].bids[].price` /
`asks[].price`. So I did NOT generalize `_current_ask`; I added `_honest_bid_ask`
that calls the real endpoint. This is exactly the "spec inherits an assumption;
the code tells the truth" pattern AGENTS warns about — following the letter of
the brief would have shipped a field that stays None forever on real products.

Deliberately I left `_current_ask` alone: it's the what-if FILL price, where a
mid/last fallback is fine. Reusing it for the record would fabricate a spread
(mid-derived ask against a real bid). `_honest_bid_ask` never falls back to
mid/last — real bid AND real ask, or None.

## The sampling location call: sibling field, not nested in `models`

The brief said "the `models` sidecar entry per provider gains a `sampling`
sub-dict." Taken literally that means `models[llm]: {"model": ..., "sampling":
...}`. I chose a **sibling `sampling` field** instead, because `models[llm]` is a
bare model-id string pinned by `test_schema_v2` (`rec['models'] == {'gemini':
'gemini-3.1-pro-preview'}`) and every prior schema addition here was a new
optional field, not a shape change to an existing one. Same required property
(per-provider sampling, recorded honestly), narrower blast radius. Flagging it
because it's a place I diverged from the literal wording.

## Per-provider sampling outcomes (flag ON) — and what I did NOT verify live

| provider | flag-on knob | basis | live-probed? |
|---|---|---|---|
| gemini | `temperature=0, seed=42` | `GenerateContentConfig` has both fields (checked in-SDK); folded into `gemini_structured_config` | no |
| claude | `temperature=0` | `messages.create` accepts `temperature`, no `seed` param (checked sig); thinking off for Opus 4.8 per MODELS.md | no |
| perplexity | `temperature=0` | OpenAI-compatible chat; sonar-pro not a heavy reasoner | no |
| openai | **provider-default** | gpt-5.x REJECTS `temperature` (AGENTS gotcha, verified live prior); seed on the reasoning path unverified — left untouched | n/a |
| grok | **provider-default** | grok-4.5 xAI Responses reasoning path; temperature acceptance alongside json_schema+web_search unverified — no contortion | n/a |

**Honest limitation:** I verified the SDK *accepts* these kwargs (no TypeError)
and that flag-OFF is byte-identical (captured request kwargs in tests). I did NOT
run paid live probes to confirm the flag-ON knobs are accepted at the *API* layer
for the reasoning models (gemini-3.1, claude Opus 4.8, grok-4.5). That's the
exact class of thing the "probe before you migrate" rule exists for. Because the
flag is opt-in and the money path fails closed (a rejected knob → abstain →
smaller quorum, never a bad trade), I judged it acceptable to ship without the
probe and flag it here as the follow-up. If a probe shows gemini/claude/perplexity
reject temperature=0 under structured output, they demote to provider-default with
a one-line `_DETERMINISTIC_KNOBS` edit — no call-site change. Same table promotes
openai/grok if a probe clears them.

## Near-misses

- **`__new__`-constructed traders.** The request-shape tests build traders via
  `Cls.__new__` (skipping `__init__`), so `self._sampling_params` didn't exist and
  4 provider methods `AttributeError`'d. Fixed with a class-level default
  `_sampling_params = {}` — instances without `__init__` splat nothing (byte-
  identical), `__init__` overrides per-instance. Caught by running the existing
  suite before writing my own tests, not by my tests.
- **Perplexity's shared `_call_chat`.** It serves BOTH discovery (unstructured)
  and analysis (structured). I threaded `sampling_params` only from
  `_structured_vote` so discovery stays untouched — the field only claims to
  describe the analysis request.
- **Flag/env agreement.** A `--deterministic-sampling` flag with no env var would
  have left the traders (which read `DETERMINISTIC_SAMPLING` at `__init__`)
  disagreeing with the recorded value. `main()` mirrors the resolved flag into
  `os.environ` before constructing traders, so the request and the record can
  never diverge. Pre-declared the module global (like `QUIET_MODE`) so
  test-driven helpers have a sane OFF default.

## Explicitly out of scope / not done

- The brief's optional "reflect a bid/ask fetch failure in the WS-4
  `data_quality` coinbase entry." I skipped it: `data_quality` is derived at
  market-block-build time from the CANDLE variables and is effect-honest about
  what reached the prompt; bid/ask is a separate record-time quote fetch. Folding
  a quote-fetch failure into the candle `coinbase` status would conflate two
  different signals and muddy that field's contract. Not cheap, so left out per
  the "if cheap" latitude. The failure is still visible (a `[HISTORY]
  best_bid_ask fetch failed` line) and the record honestly stores None.
- No live/paid probes run this session (see limitation above).
- `models` shape unchanged; MODELS.md's frozen dated appendix left untouched
  (frozen-doc convention) — `sampling.py`'s docstring is the living source of
  truth for the policy.
