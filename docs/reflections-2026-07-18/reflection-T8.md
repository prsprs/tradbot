# T8 (structured-output migration) — session reflection

Written from session memory only, post-handoff. Repo state may have moved since.

## 1. Friction / near-misses

- **Schema dialect fragmentation cost a probe round.** The canonical JSON schema was
  rejected by 2 of 3 "native" providers on first contact: Gemini 400s on
  `additionalProperties` (google-genai passes the dict through and the API complains
  about `additional_properties` at `generation_config.response_schema`), Claude 400s on
  `minimum`/`maximum` for number types. This forced per-provider schema variants
  (`schema_for_gemini/claude` in voteschema.py) and client-side confidence-range
  validation. Had I written code before probing, these would have been runtime 400s on
  the money path.
- **My probe harness ate its own evidence.** Round 1's Perplexity response was
  unterminated JSON; my `record()` helper called `json.loads` inline and the exception
  discarded the raw content — I had to re-probe with parsing guarded to capture the
  actual truncation shape. Lesson: capture raw first, parse defensively second.
- **The second xfail was mislabeled and NOT clearable as specified.** Both xfails carried
  the copy-pasted reason "fenced blocks not stripped", but the unbackticked-citation case
  ("The format would be <**ETH-PRS-BUY**> for a buy, but I won't issue one") has no
  fence to strip. The task said the fenced-block fix clears both. It doesn't. Near-miss:
  the tempting dishonest paths were deleting the test or keyword-matching refusal
  language. I instead added the concluding-tag rule (prose after the last tag ⇒ no
  parse), which required flipping two ported "residual risk" CASES rows to the new
  expectations — a semantics change I had to own explicitly.
- **Hidden test-seam coupling in process_coin_with_comparison.** It re-parses the
  primary's text internally (`extract_recommendation(primary_response_text)`), so making
  gemini structured silently broke ~9 consensus tests that script primary text as
  delimiter tags via `_primary_text`. The stubbed `get_llm_response` fakes survived only
  because I kept the `(text, rec)` tuple contract and smuggled richer outcomes as an
  `Abstain` marker in the rec slot. My first design (a VoteResult return object) would
  have forced rewriting every fake — I backed out before committing to it.
- **Empty-at-cap nearly demanded five layers of new plumbing.** Existing tallies mapped
  falsy response → 'error', but the task requires empty-at-cap → parse_failure. I almost
  threaded a result object through traders → get_llm_response → tallies before realizing
  a two-value text convention (None = API error, "" = responded-with-no-text) encodes it
  with zero signature changes.
- **main() had untested log lines that would have lied.** The "Coin and rec:" debug
  pre-parse would print `None, None` on structured JSON; tests never execute main(), so
  only reading main() end-to-end caught it.

## 2. Guidance quality

- **Helped most: the probe-first mandate.** Highest-value instruction in the prompt —
  see the schema-dialect item above. Also the MODELS.md appendix constraints
  (empty-at-cap trap, max_completion_tokens/no-temperature, Grok soft cap) were all
  accurate; I rediscovered none of them.
- **Wrong:** "clearing the 2 xfails ... via the fenced-block fix" (only one is).
- **Missing:** (a) whether Gemini `response_schema` coexists with the google_search
  tool — the single biggest go/no-go unknown for the default panel; I probed both ways
  (it does coexist). (b) Any warning about the primary-text re-parse seam in the
  consensus tests. (c) That anthropic 0.94.0 already has `output_config` — the prompt
  hedged toward tool-forcing; `inspect.signature(Messages.create)` settled it in
  seconds and the next agent should start there.
- **Now recorded so nobody rediscovers it:** per-provider dialect quirks live in the
  fixtures, voteschema docstrings, and MODELS.md Appendix 2.

## 3. Design doubts (plainly)

- **Concluding-tag rule may over-abstain the fallback providers.** Any letter after the
  last tag kills the parse. I allow `[1][2]`/punctuation, but a Perplexity "Sources:"
  line or trailing disclaimer will abstain a genuine vote. Fail-closed by intent, but if
  grok/perplexity panels ever matter, watch their parse_failure abstain rate.
- **bind_symbol's 15-entry alias map is a guess at coverage.** "Bitcoin BTC" (name and
  ticker juxtaposed, no parens) mismatches; so does any full name outside the map. Fine
  for meme coins where name==ticker; the over-abstain risk concentrates in majors phrased
  unusually. I chose no token-matching on purpose (pairs like "ETH-BTC" must not bind),
  but the boundary is judgment, not evidence.
- **Refusal-before-binding ordering:** abstain=true with a wrong/junk symbol counts as
  'refusal', not 'symbol_mismatch'. Defensible (the model declined; about what is
  secondary) but it shades the abstain-reason stats the analyzer will read.
- **Round-2 cross-feed is now compact JSON, not prose.** Peers see `reasons` arrays
  instead of full narratives. Integrate-mode opinion-shift dynamics have changed and
  nobody measured the before/after. Out of scope, but real.
- **Small liberality:** parse_vote tolerates a ```json fence wrapper on an otherwise
  strict path. Native structured output never emits it; I kept the tolerance as
  defense-in-depth. Reasonable people could strip it.
- **Contract wart:** resolve_structured_vote returns None for no-response but Abstain for
  everything else — the None leg exists purely to preserve the legacy 'error' mapping in
  the tallies. A future refactor should unify on Abstain('error').

## 4. Repo improvements that would have materially helped

1. **Split crypto_trading_bot.py (the standing candidate) — do it.** The vote-resolution
  seam lives inside ~2200 lines of call-time globals; `monkeypatch(..., raising=False)`
  test style means coupling (like the primary re-parse) is invisible until runtime.
  A consensus module with injected provider callables would have halved careful-reading
  time and made the T8 seam a one-line change.
2. **A reusable probe/fixture tool** (`llmprobe.py` beside llmpreflight.py) that runs a
  request spec against a provider and snapshots request+response to
  tests/fixtures/. This is the second session to hand-write throwaway probe scripts;
  mine crashed on its own capture path once. Bonus: shared fake-client test helpers
  (I built Capture/Capture3/SimpleNamespace fakes ad hoc in test_structured_requests).

## 5. Tradbot-specific observations for the owner

- **Schemas make abstaining easy — expect trade volume to drop.** Given an explicit
  `abstain` field, four of five providers took the exit ramp on the bare probe prompt
  (gpt-5.5, gemini, claude, grok all returned abstain=true citing "no real-time data").
  Under REQUIRE_CONSENSUS one refusal blocks the panel. That is fail-closed working as
  designed, but the delimiter era masked refusals as (dangerous) parses; the honest rate
  will look like a regression in activity. T9's real market data should directly reduce
  the refusals — the models literally named missing data as their reason.
- **Perplexity is the outlier both ways:** the only confident non-abstain voter (its
  grounding fires in schema mode), and the only provider observed returning unterminated
  JSON under json_schema mode (at max_tokens=800). If it's ever promoted off the
  fallback path, budget generously and never trust its JSON without a guarded parse.
- **Gemini 3.1 reasoning is not damped by structured output:** 855 thought-tokens to
  produce a two-line JSON. It's the cost outlier per analysis call; the JSON being small
  doesn't mean the call is cheap.
- **Drift risk: Claude's output_config is a young API surface** (landed by SDK 0.94).
  test_structured_requests pins our request shape, so SDK-side change breaks tests — but
  a server-side change shows up only at runtime as parse_failure abstains. Worth
  extending llmpreflight with a 1-vote schema probe for structured panel members so
  contract drift is caught at startup, not mid-panel.
