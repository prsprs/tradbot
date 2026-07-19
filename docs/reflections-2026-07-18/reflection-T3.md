# T3 (consensus hardening) — implementer's session reflection

Written from session memory only, after T3 landed (pre-Phase-1 state of the repo).

## 1. Friction / near-misses

- **Stale line anchors, as warned.** The spec's pre-T4a line refs (:858, :926, :929, :874) were dead;
  the "search for `record_recommendation(` and `'BUY' in final_action`" hint resolved it in one grep.
  Cheap insurance: specs that cite line numbers should always pair them with a grep anchor.
- **The xfail handoff was bigger than "remove markers."** T4b's tests unpacked the old
  `(action, consensus)` tuple in `run_case` and in all 11 ported parametrized rows. Switching the
  return type to `PanelDecision` meant rewriting the harness and every expectation row, not just
  deleting six `@pytest.mark.xfail` lines. Not a complaint — the tests were the most valuable asset
  I inherited — but "un-xfail" undersold the reconciliation work.
- **Near-miss: candidate export riding on `record_recommendation`.** Recording blocked decisions as
  action `NONE` would have silently started exporting blocked coins to `candidate_coins.csv`
  whenever `--export-candidates` + `export_recommendations='ALL'` is set — a side channel the spec
  never mentioned. Caught it only because I read `record_recommendation` end-to-end before editing.
  Added a `rec_upper != 'NONE'` guard.
- **Near-miss: the downgrade warning firing on innocent runs.** `tiebreaker==primary` is the
  *default* config, so an unconditional `validate_tiebreaker_config` would print a scary money-path
  warning on every bare `--llm-mode=gemini` run where the tiebreaker is irrelevant. Gated it on
  compare/integrate modes.
- **Subtle duplication at trade site 1:** two back-to-back identical
  `if final_action and 'BUY' in final_action:` blocks (append vs execute) had to be merged without
  changing `coinsToBuy` bookkeeping; site 2 had the merged shape already. Easy place to introduce a
  discrepancy between the two sites.
- **Block-reason ordering is a real decision, not cosmetics.** With 1 vote + 2 abstains, both
  `sub_quorum` and `abstain` are true; the check order (sub_quorum first) determines the recorded
  reason, and the un-xfailed `test_two_abstains_is_not_consensus` had to be written against that
  choice. Whoever builds analyzer buckets on `block_reason` should know reasons are not exclusive.

## 2. Guidance quality

- **Best line in the spec:** the (c) truth table plus the explicit "a naive `consensus is True` gate
  would brick single-LLM mode." That is exactly the trap I would have walked into first.
- **Equally good:** "downgrade, don't hard-error" for tiebreaker==primary *with the reason*
  (the shipped default has the misconfiguration). Without that I'd likely have hard-errored and
  broken every default-config run.
- **Wrong/ambiguous:** the (h) field list for history records omitted `majority_action` while the
  prose said "recorded for measurement even when not traded." I persisted it and flagged the call.
  Specs enumerating record fields should be exhaustive — money-path agents shouldn't infer schema.
- **Had to discover myself (next agent shouldn't):**
  - `get_llm_response` returns `(None, None)` for *both* a raised exception and a missing trader
    object — the 'error' abstain reason bottoms out there; error/refusal granularity is T8's ceiling.
  - Integrate Round 2 only re-queries Round-1 *responders*, so an R1 API-error can never cure itself
    in R2. That structural invariant is what makes blocking-before-Round-2 sound, and it is
    documented nowhere.
  - All the consensus globals (`LLM_MODE`, `COMPARE_LLMS`, …) don't exist until `main()` runs;
    T4b's `raising=False` monkeypatch pattern is the only way to test, and it's easy to miss.

## 3. Design doubts (plainly)

- **Stringly-typed abstains.** `'ABSTAIN(error)'` markers inside `votes` keep the record JSON flat,
  but any consumer must parse them. A per-LLM vote struct would be cleaner; felt too heavy before
  T2/T10 define the record's consumers. If T10 finds itself regex-ing `ABSTAIN\((.*)\)`, revisit.
- **Legacy `consensus` property collapses blocked and tiebreaker to `False`.** Old records used the
  tri-state; new consumers must key on `consensus_state`. If the analyzer keeps reading `consensus`,
  blocked decisions will look like mere disagreements.
- **The gate trusts its `llm_mode` argument over `decision.consensus_state`.** I checked the
  mismatch cases (they all fail closed: blocked→action None→False; 'single' under a multi mode hits
  the state checks and is refused), but the redundancy is an invariant someone could "simplify" away.
- **Round-2 fail-fast changes observable behavior** (no R2 prints/API spend when an error-abstain +
  REQUIRE_CONSENSUS guarantees a block). I traded run-log fidelity for cost without owner sign-off.
- **`'BUY' in final_action` substring check survives** (kept per scope). Votes are normalized to
  exact BUY/SELL/HOLD today, so it's safe — but it's the kind of check that goes wrong the day an
  action string grows qualifiers.

## 4. Repo improvements that would have made this faster/safer

1. **Extract the decision core to a pure module-level function.** `decide()` is exactly the pure
   votes+abstains+config → `PanelDecision` resolver this task needed, but I had to build it as a
   closure over `panel`/`coin_symbol`/module globals inside the I/O function. Hoisting it (explicit
   params, no globals) would let every future consensus change be test-first without monkeypatching
   eleven module attributes.
2. **Keep the T4b pattern institutional:** "port current behavior to pytest, then write the next
   task's expectations as xfail *before* touching the code" was the single biggest safety net —
   I could see every semantic change I made as a deliberate red→green flip, not a silent diff.

## 5. Tradbot itself — residual fail-open risks

- **Init-time panel pruning still shrinks the quorum before T3 can see it.** In `main()`, a failed
  client init does `COMPARE_LLMS = [llm for llm in COMPARE_LLMS if llm != 'claude']` (per provider).
  My quorum enforcement covers *call-time* failures, but an LLM dropped at startup is erased from
  the configured panel itself — a 3-panel quietly becomes a legitimate-looking 2-panel with no
  abstain recorded. This is the same class of bug as finding 1.1, one layer up. T6's preflight
  should hard-fail (live) or convert the drop into a standing abstain rather than pruning the list.
- **SELL consensus is still recorded-and-dropped** — the gate only guards BUY sites; nothing new,
  but blocked-decision records may now tempt someone to "wire up" actions generically; the SELL
  path needs T5's position model first.
- **Regression-proofing that should be preserved:** `decision_allows_trade` returns False for any
  unrecognized `consensus_state`, and `process_coin_with_comparison` returns a blocked
  `unknown_llm_mode` decision for any unhandled mode. Both mean *additions* fail closed by default.
  A future refactor that inverts either default (e.g. `return True` fallthrough, or defaulting a new
  mode to the primary's vote) silently reopens everything T3 closed — worth a comment-level tripwire
  or a dedicated test in any future rework.
