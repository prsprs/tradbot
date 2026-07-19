# Session Reflection Synthesis — 2026-07-18 (Phases 0–3)

Seven implementer agents (T3, T5, T8, T9, T10, T11, T12+T13) wrote first-person reflection notes at the end of Phase 3 — the raw notes sit alongside this file. This synthesis extracts the cross-cutting themes and the concrete follow-up queue. Written by the orchestrating agent; the owner (Josh) decides what gets acted on.

**Why this exists:** final reports systematically omit near-misses and design doubts. The reflection pass surfaced three money-path risks that no final report contained (F1, F2, F3 below). Agents' transcripts persist across context compaction and completed agents can be resumed to self-reflect — this should be standard at every phase checkpoint.

## Cross-cutting themes (independently hit by multiple agents)

1. **Spec claims must be verified against actual behavior before acting — especially before deleting.** T11 nearly amputated a live, documented feature because the task's rationale transplanted the main bot's story onto an unrelated tool's same-named flag (the real target was a junk *file* named `--use-fib`). T5 found the spec's "SDK supports client_order_id filtering" claim false. T8 found the "fenced-block fix clears both xfails" claim wrong. The evaluation doc itself was stale on model IDs within a session. Rule: the spec tells you *where to look*; the code tells you *what's true*.

2. **The monolith/globals tax is the top structural cost — five agents hit it independently.** T3 wants the consensus `decide()` closure hoisted to a pure votes→PanelDecision function (testing required monkeypatching eleven globals). T5's riskiest verification step was hand-wiring `buy_something`'s six module globals. T8 says call-time globals hide seams (the primary re-parse coupling silently broke ~9 tests). T9 counted the cost precisely: prompt assembly is duplicated across ~20 sites, so a prompt change costs ~24 edits instead of ~2. T12 shipped a design it dislikes (self-fetching `build_market_block`) purely because the cache lives in the off-limits monolith. → R1 below.

3. **Multi-agent trees need file-ownership invariants, not global test counts.** Both Phase-3 parallel agents burned time on the same false alarm: "444 tests" drifted to 517 mid-session as the other agent's files landed, and each had to prove the delta wasn't its own bug. T10's fix: give each agent an explicit file-ownership list and make "files outside your list unchanged" the invariant.

4. **Test infrastructure gaps that nearly caused silent wrongness:** T12's own autouse network-stub fixture silently neutralized functions other tests targeted (caught by luck). A repo-wide network guard in `tests/conftest.py` turns that whole class into loud failures → F5. T11's delete-then-restore whipsaw happened because "zero callers" and "not intended API" are different facts — a frozen public-surface test for util modules would pin that.

5. **Probe-first keeps winning, and real fixtures beat synthetic ones.** T8: 2 of 3 "native structured output" providers rejected parts of the canonical schema — would have been runtime 400s. T12: the pre-verified gotcha list meant zero wasted discovery calls, and the *real* fixture falsified its sentiment-weighting intuition (TikTok outweighs X in interactions). Corollary from T12: synthetic fixtures ratify your assumptions; real ones test them.

6. **Prompt wording is a live lever on votes.** T9 observed OpenAI echoing the block's demotion phrasing near-verbatim in its vote reasoning, and Gemini's first-ever zero-confabulation run plausibly due to the RULE line (n=1). Every sentence in the market block is a de facto instruction.

7. **The timestamp convention is load-bearing and now entrenched.** History/ledger timestamps are naive-UTC-with-literal-'Z'; parsers depend on it; T11's migration deliberately preserved it (with regression tests) while fixing the one place the naive pattern was a *live bug* (lp_history local-time cutoffs, off by the machine's UTC offset). Going timezone-aware end-to-end is a real future migration with a read-compatibility window — not a hygiene-task side effect → R3.

## Fix candidates (owner decides; suggested model per task)

**P1 — money-path, recommend before unsupervised live runs:**
- **F1 (Fable 5):** `main()` prunes failed-init LLMs out of `COMPARE_LLMS` before consensus sees them — a panelist can vanish with no abstain recorded (the §1.1 bug class one layer up; `--skip-preflight`/whatif paths leave it open). Convert prune → standing abstain. *(T3 reflection)*
- **F2 (Opus 4.8):** Ambiguous create-timeout can leave the ledger saying `failed` while the order actually filled. Attempt client_order_id lookup on *any* create failure; add `reconcile --repair` for orphaned intents and `unconfirmed` fills (nothing re-polls them today). Also: the live acceptance test should deliberately trigger a duplicate order to capture the real rejection shape (`_looks_like_duplicate` is untested string guesswork). *(T5)*
- **F3 (Sonnet 5):** CMC lookup takes `data[0]` for a symbol; CMC symbols collide, so obscure meme tickers can render a *different asset's* stats into the prompt. Switch to ID-based lookup via `coinmarketcaputil.SYMBOL_TO_CMC_ID` (helpers kept for exactly this). *(T12)*

**P2 — correctness/hygiene:**
- **F4 (Opus 4.8):** analyzer judged-state keys on record `id` (uniqueness unenforced → same-second collisions) and freeze-at-first-scoring makes the grading window cadence-dependent. Sound fix: score against price *at maturity* from historical candles. *(T10)*
- **F5 (Sonnet 5):** repo-wide network guard in `tests/conftest.py` (socket block); loud failure on any test touching the network. *(T12)*
- **F6 (Fable 5, measure first):** the fallback parser's concluding-tag rule (prose after last tag ⇒ no parse) may over-abstain grok/perplexity when they append "Sources:" lines — check history for abstain(parse_failure) on otherwise-clean votes before changing semantics. *(T8)*
- **F7 (Sonnet 5):** market-block cache has no TTL (stale if the bot ever loops in-process); vestigial `trends_data` params can double-inject trends alongside the block. *(T9)*
- **F8 (Sonnet 5):** grep-audit for sibling naive-`.timestamp()` bugs in `leading_indicator_tester.py`, `correlation_tracker.py`, `dex/` (the lp_history bug likely has siblings). *(T11)*
- **F9 (Sonnet 5):** extend `llmpreflight` with a 1-vote structured-output probe so server-side schema-contract drift fails at startup, not mid-panel (Claude's `output_config` surface is young). *(T8)*

**Refactor queue (bigger, post-fix):**
- **R1:** split `crypto_trading_bot.py`: pure consensus function (votes→PanelDecision), centralized prompt assembly (~20 sites→1), context objects instead of module globals. Five agents' independent top ask.
- **R2:** LLM stack unification (`llm_utils/` vs `*util.py`).
- **R3:** timezone-aware timestamps end-to-end, with read-compatibility window.
- **R4:** move `recorder.py` (code) out of `history/` (data) — the mixing caused T11's one real error.

**Cheap prompt-lever experiments (from T9's live observation):**
- Add the measured 2.4% round-trip fee floor as a labeled block line ("a trade must clear this").
- Instruct grounded providers (gemini/perplexity) to reconcile search results against the supplied block instead of silently choosing.
- Drop the noisy 0%/100% fib endpoints from the block.
- Decide whether recorded confidence (currently 0.60–0.70, gates nothing) should gate anything.

## Phase 4 addendum (same night — fix queue executed; reflections in reflection-P4-{A,B,C,D}.md)

F1–F9 are resolved (F6 resolved-by-measurement: zero evidence of over-abstain in any corpus; semantics unchanged, distinguishing log added; F8 resolved-by-clean-audit: no sibling naive-timestamp bugs in the three targets). Suite: 521 → 597 passing.

**New lessons from Phase 4 (beyond the themes above):**
- **Removing a fail-open can activate a worse dormant fail-open.** The pre-F1 init crash was the only thing keeping a fallback-to-Gemini vote-substitution branch dead; the fix required guarding the branch, not just removing the prune. Trace every consumer of state you change (P4-A).
- **Tri-state results are the crux of failure handling:** "the lookup threw" and "the lookup found nothing" are opposite facts — collapsing them into one `None` makes fail-safe states unimplementable (P4-B).
- **"Vestigial" is a per-call-site claim:** `trends_data` was dead in the live orchestration path but alive as tested API surface one layer down; the right fix was suppressing double-injection at the one reachable choke point, not deletion (P4-D).
- **Never monkeypatch attributes on real stdlib modules** (e.g. `time.time`) — modules are process-global singletons; patch the importing module's own name binding instead. Cost two killed pytest runs to learn (P4-D).
- **Measure-first can resolve a fix by evidence of absence** — and production history couldn't answer the question at all (pre-T3 records carry no abstain breakdown); per-record parse diagnostics would make this class of question a five-minute query (P4-A).

**Small follow-ups spawned by Phase 4 (not yet tasked):**
- Wire `llmpreflight` schema_probe into bot startup (capability landed unwired — P4-C doesn't own the bot file; second occurrence of the off-limits-monolith workaround shape, strengthening R1).
- `reconcile --repair` is load-bearing but manual — nothing runs it automatically; consider bot-startup or cadence-runbook integration (P4-B).
- Promote `test_market_data.py`'s file-local CMC/SOCIAL stub fixture to repo-wide `tests/conftest.py` — it's a trap for every new test file that touches `build_market_block` (P4-D).
- Owner live-run capture: runbook §7 duplicate-rejection fixture to validate/retire `_looks_like_duplicate` (P4-B).

## Tradbot behavior notes for the owner

- **Expect the new scorecard to look brutal — that's the fix working.** Most old "CORRECT" BUYs regrade as losses under benchmark-relative + fee rules, and the mature history is mostly `unknown`-mode, so early reports carry little signal. The what-if cadence (docs/RUNBOOK_whatif_cadence.md) is the data engine that makes measurement possible.
- Ledger fees materially change verdicts: the one real joined fee (1.2% round-trip) was half the assumed floor — enough to flip marginal WIN/LOSS calls.
- The panel now disagrees *analytically* (same supplied fact, opposite readings) — that is the consensus gate doing its job, not noise.
- Google Trends returned nothing even for BTC in the live E2E run; it may no longer earn its dependency.
- CMC's 24h change agreed with candle-derived within 0.1pp — a free cross-validation signal the prompt could exploit.
- `leading_indicator_tester.py`: 5,600 lines, ~50 flags, zero tests, real order-placement code; three flags were broken; base rates say more are. Treat it as untrusted until tested.

## Session coda (orchestrator, at close)

**Totals:** one day, five phases, 40 → 597 tests (0 failures throughout the final states), ~19 agents (15 implementation, 3 recon, 1 adversarial plan review) + a full reflection harvest, zero contamination of real per-user data across ~15 bot/analyzer runs, zero unauthorized trades or commits.

**Model-tier observations (for future task routing):**
- **Fable** earned its slot on exactly the tasks it got: T3 caught the record-export side-channel, T8 owned a real semantics change honestly, P4-A found that removing a fail-open would have activated a dormant vote-substitution branch — all catches where the failure mode was subtle state coupling, not code volume.
- **Opus** delivered the substantial subsystems (ledger, market data, analyzer, tri-state recovery) with strong judgment-call reporting; its reflections carried the most owner-relevant operational risks.
- **Sonnet** was excellent on well-scoped work and twice refused to execute a stale spec instruction that would have deleted live code (T11's `--use-fib`, P4-D's `trends_data`) — scoped tasks + "verify the claim first" framing made the tier distinction about task shape, not quality.

**What worked well enough to keep as standing practice:** probe-first with real fixtures; xfail-tests-first as agent-to-agent spec; explicit judgment-call reporting; scratch-redirect of all side effects; file-ownership lists in parallel trees; measure-first before semantics changes; reflection harvest at phase ends (agents resumable from transcripts even post-compact); mid-flight amendments to running agents when new information lands (saved the CMC helpers).

**What the next big session should do differently:** establish file-ownership lists at dispatch (they were retrofit mid-session after two false alarms); start with R1 (the monolith tax appeared in five independent reflections and forced the same workaround twice); store per-record parse diagnostics so vote-behavior questions become queries instead of archaeology; and treat "spec says delete X" as a verification task, not an instruction.
