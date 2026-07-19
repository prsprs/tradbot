# Live Acceptance Results — 2026-07-19 (UTC)

Owner-executed acceptance session (Josh at the terminal, AI navigating), per
`RUNBOOK_live_acceptance.md`. This file records what was **proven against real
money**, what was learned, and what remains before the bot is showcased to
other users.

## Verified live (real account, real orders)

| Capability | Evidence |
|---|---|
| Full test suite | 599 passed, 0 failures at this point in the session (was 597; +2 from §7 fixture tests; final count after same-day reasons-hygiene fix: 616) |
| `import crypto_trading_bot` side-effect-free | silent |
| What-if E2E (single LLM, scratch history) | HOLD recorded, no trade, real `history/` untouched |
| Live double lock arms | LIVE banner with `[--live + LIVE_TRADING_CONFIRMED=1]` |
| Live double lock **fails safe** | Deliberate missing env var → loud `[LIVE LOCK]` banner, downgrade to what-if, warning repeated in run banner |
| Preflight, all 5 panelists + schema probe | gemini / claude / openai / grok / perplexity all OK (needs `load_dotenv()` when called standalone — see gotchas) |
| **Real order placed and filled** | ETH BUY, `run_20260719T025131Z`, order `00fc688f-2cf6-427d-9495-096098cb8a2f`, 0.00264045 ETH @ $1870.89, fees $0.0593 (~1.2% — matches the measured fee model) |
| Ledger intent-before-order, fill row after | both rows present, joined by `run_id` |
| Daily spend cap (same-run) | LINK BUY vote refused with `[DAILY CAP]` after ETH committed the $5 |
| Position reconciliation | bot attributed exactly the ledger fill; 17 legacy coins flagged `bot-unknown`; ETH `drift` = benign legacy+bot-same-coin case |
| **Duplicate `client_order_id` idempotency** | resubmit returned `success:true` with the ORIGINAL order_id, no error, no second fill — see runbook §7 addendum + `tests/fixtures/coinbase/duplicate_rejection.json` |
| Panel consensus (what-if) | compare mode, 3 panelists, structured votes with symbol binding, unanimous HOLDs handled correctly |

## Issues found (open unless noted)

1. **Parsed `reasons` arrays can contain LLM self-correction junk** (traced;
   lower severity than first thought). Claude emitted malformed JSON mid-stream
   then self-corrected; debris strings (`","`, `"]}...__ERROR__ retrying:{"`, a
   stray literal `"abstain"`) were syntactically valid JSON string elements
   inside `reasons`, and `voteschema.parse_vote` (voteschema.py:226-231)
   validates only container/element *types*, not content. **History is NOT
   affected** — `resolve_structured_vote` returns only the action string, and
   history records store per-LLM action strings, never reasons; the junk
   surfaces only on stdout/logs. Typed vote fields are validated independently
   and were correct. **FIXED same day:** `parse_vote` now decodes only the
   first complete JSON object (`raw_decode`) and content-filters reasons
   (drops empties, artifact markers, control chars, unbalanced braces, pure
   punctuation, bare schema-keyword echoes; caps count=12/length=500), and
   fails closed with `reasons content corrupt` when a majority of entries are
   debris. Covered by content-level cases in `tests/test_voteschema.py` and a
   full-blob regression in `tests/test_structured_requests.py`
   (`test_malformed_stream_regression_2026_07_19`). Suite: 616.
2. **Run-summary `Blocked by spend cap` tally omits daily-cap refusals** — the
   LINK refusal printed `[DAILY CAP]` but the summary showed `0`. Cosmetic but
   misleading in exactly the runs where users most need the summary.
3. **Reconcile `drift` flag can't distinguish directions.** Legacy holdings +
   bot buy in the same coin (benign, account > ledger) reads the same as the
   dangerous case (account < ledger, i.e. missing funds). Consider an
   `account>=bot` vs `SHORTFALL` split.
4. **Standalone `llmpreflight` reports every model "not configured"** unless
   the caller runs `load_dotenv()` first (the bot does it in `main()`). Either
   document it or have `llmpreflight` load dotenv itself.

## Remaining showcase items — second pass (same night)

- [x] **Live + panel combined** — run live-armed in compare mode: Gemini voted
      BUY on BTC, Claude+OpenAI voted HOLD → `[BLOCKED] BTC: disagreement: no
      unanimous consensus`, recorded as `NONE`, **no order**. The fail-closed
      consensus gate blocked a real live BUY on real money — stronger evidence
      than any planned test. Second coin: unanimous HOLD handled normally.
- [x] **Fresh-user startup** — empty `HISTORY_DIR`: clean zero-record analyzer
      summary, normal run, no tracebacks (simulates a new user's empty
      ledger/history without a fresh clone).
- [x] **Analyzer full report** — correct record accounting (every record in
      exactly one category, sum verified), pending-not-scored for <24h
      records, panel-behavior histogram correctly shows the live disagreement
      block. *Scoring* output still needs 24h maturity + the what-if cadence.
- [x] **Reconcile stability** — identical output across runs; ETH drift
      unchanged (benign legacy+bot case).
- [x] **Hygiene gap found & fixed by the pre-commit grep**: the analyzer
      writes `history/analyzer_state.json` (per-user data) and `.gitignore`
      did not cover it — pattern added.
- [x] **Discovery mode** — `--discovery llm` (what-if): LLM discovery returned
      3 coins, each analyzed with the full market block and structured vote,
      symbol binding ok, tiny-price coin (PEPE @ $2.74e-06) recorded cleanly.
      Note: `--discovery` takes a *method* (`llm`/`santiment`), not a count;
      a bad value errors cleanly with the valid options.
- [~] **Daily-cap cross-run refusal** — attempted; all votes were HOLD so the
      cap was never challenged. Same-run refusal is proven; cross-run summing
      is exercised by the same ledger query and remains untested only for
      lack of a BUY vote.
- [ ] **SELL path** — does not exist yet (SELL votes are recorded and dropped);
      users must know exits are manual.
- [x] Execute the **7-commit plan** in `SESSION_HANDOFF_2026-07-18.md` (this
      session's new files join commit 1) so users clone tested code.
      *(DONE 2026-07-19: commits `4640c3b..3ec83e2` on `josh`, per-commit
      owner approval, suite 616 green before and after.)*

## Testing lessons for future humans running sessions like this

- **Test the lock by breaking it on purpose.** The most valuable free test was
  running live with the env var deliberately missing and watching it fail safe.
  Do this before every acceptance, not just once.
- **A HOLD is a passing result.** Quiet, consolidating markets produce
  unanimous HOLDs; that validates the gate, not nothing. Don't force trades to
  "see something happen" — widen the coin list and let a real BUY come.
- **One multi-coin run beats N single-coin runs** for acceptance: the run that
  finally traded also validated the daily cap in the same pass, because a
  second BUY vote arrived after the budget was spent.
- **Read the raw LLM responses, not just the parsed verdicts.** The reasons
  junk was invisible in every structured field and every test; it only showed
  in the streamed raw text. Keep `--log-rounds=true` on during acceptance.
- **When a predicted API shape is testable cheaply, test it** — the §7
  duplicate probe cost $0 (idempotent) and falsified the documented
  expectation. Fixtures beat folklore.
- **Caps are also test instruments.** Setting run/daily caps to exactly one
  notional turns "hope it doesn't overspend" into a bounded experiment.
- **Check UTC, not local time.** Daily caps and history dates roll at UTC
  midnight; a 10pm local session straddles two budget days.

## Session provenance

Runbook: `RUNBOOK_live_acceptance.md` (incl. §7 addendum). Prior context:
`SESSION_HANDOFF_2026-07-18.md`, `docs/reflections-2026-07-18/SYNTHESIS.md`.
