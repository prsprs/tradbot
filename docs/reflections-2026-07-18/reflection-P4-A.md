# Reflection — P4-A (F1 failed-init standing abstain + F6 concluding-tag measurement)

First-person, written immediately after finishing. Fable 5 agent.

## What almost went wrong

- The scariest thing I found wasn't the pruning itself — it was what removing
  the pruning would have EXPOSED: `get_primary_coin_check` silently falls back
  to Gemini when the primary's trader is None. Pre-F1 that branch was dead
  (primary init failure raised in main), but the naive F1 fix — "stop pruning,
  stop raising" — would have activated it: a dead-primary run would have had
  Gemini's JSON resolved *as the primary's vote* and cross-fed under the
  primary's name. A fail-open fix creating a model-substitution bug. I caught
  it only because I traced the primary text's full path before editing. The
  guard in `get_primary_coin_check` plus discarding Round-1 text for a
  failed-init primary in `process_coin_with_comparison` (defense in depth)
  closes it, and `test_primary_failed_init_discards_round1_text` pins it.
- Single-mode init failures produce a `consensus_state='blocked'` decision,
  not 'single', *specifically because* the call sites' record gate skips
  actionless 'single' decisions. That coupling (record gate semantics living
  in a main()-loop conditional, spec'd nowhere) is fragile; I documented it in
  the test name and comment, but it deserves a real seam.
- My first end-to-end verification plan was to break a provider by unsetting
  its key — wrong, because `load_dotenv()` re-supplies it. Setting
  `CLAUDE_API_KEY=''` works (dotenv doesn't override existing env). Worth
  knowing for future fault-injection runs.

## Judgment calls I want reviewed

- I removed the `raise` for single/primary-mode init failures (run continues,
  every coin records a blocked decision). Spec said "recorded as blocked —
  never a silent no-op", which a crash cannot satisfy; but it does mean a
  fully-dead single-LLM run now burns market-data fetches to write N blocked
  records instead of dying at startup. I think that's right (whatif mirrors
  live; preflight still hard-fails live), but it's a behavior change to a
  crash path someone may have relied on.
- I wrapped `genai.Client()` too (was unguarded). Gemini's send helpers all
  catch a dead client, so it degrades to abstains; discovery degrades to a
  clean "DISCOVERY FAILED" exit. Symmetry felt mandatory, but it's beyond the
  letter of the spec.
- Blocked single-mode decisions report legacy `consensus=False` (the property
  maps blocked→False), where a 'single' state would give None. Harmless for
  the analyzer today, but the tri-state legacy flag keeps accreting meanings.

## F6: what the measurement actually taught me

- Zero evidence of over-abstain: 0 of 8 grok/perplexity tagged responses in
  the only raw corpus (lab eval logs) had trailing content after a well-formed
  tag; perplexity puts its citation dump BEFORE the tag. So I changed nothing
  and added the distinguishing log line. The real observed grok failure mode
  is *malformed tags* (`<**Ethereum - PRS - HOLD**>`, `**ETH-PRS-HOLD**` sans
  brackets) — if anyone wants vote recovery, tolerant tag matching with the
  existing symbol binding would pay off far more than trailing-content
  whitelists. I deliberately did not do it: fail-closed outranks recovery,
  and structured-output adoption for grok/perplexity (probes say both support
  it) makes the whole parser moot.
- Production history is measurement-blind here: all 48 records predate T3's
  votes/block_reason fields and abstains were never recorded at all. The T3+
  record shape fixes this going forward; the new log line covers the gap
  until then.

## Guidance quality

- The prompt was excellent — naming the `--skip-preflight`/whatif hole and
  demanding measure-first for F6 prevented both a shallow fix and a
  speculative one. AGENTS.md's "read test_consensus.py first" was the single
  highest-value instruction; the abstain vocabulary and `blocked()` helper
  meant F1 needed no new mechanism at all.
- Gap: neither the prompt nor AGENTS.md mentions that `main()` prunes
  COMPARE_LLMS *and* that `get_primary_*` has fallback-to-Gemini branches —
  the two interact. An architecture note on "who is allowed to mutate the
  panel" would have saved me the most careful hour.

## Repo improvements that would have made this faster/safer

1. Extract the per-coin analyze/record/trade block (duplicated verbatim in
   both main() loops, including my comment edits landing twice) into one
   function with the record gate explicit — the F1 'blocked'-not-'single'
   subtlety would become a unit-testable seam instead of a convention.
2. Store per-LLM raw responses (or at least parse diagnostics) in history
   records. F6 was unmeasurable from production data; one field would have
   made it a five-minute query.

## Tradbot behavior observation

In the live-ish whatif check, Gemini voted BUY on BTC at 0.75 confidence off
the market block. The panel blocked it (sub_quorum, dead claude) — exactly
the designed outcome, and a nice demonstration that the standing abstain
turns "quietly trade on a shrunken panel" into "loudly refuse and record".
