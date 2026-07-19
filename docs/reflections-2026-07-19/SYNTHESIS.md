# Reflection synthesis — IMPROVEMENT_PLAN execution session, 2026-07-19

Sixteen agents worked this session: 4 read-only assumption verifiers, 8 implementation lanes (L1 money-path ×2 stages, L2 satellites, L3 analyzer, L4 infra, L5 preflight, L6 docs, Phase-4 doc-reorg, AGENTS.md prose), 3 adversarial review gates (Fable ×2, Opus ×1), a final whole-diff sweep (Fable), and a supersession-map lane (Opus). Each was asked afterward for a first-person reflection on lessons for future AI contributors and doc gaps. This file is the synthesis; the orchestrator's own reflection is at the end. Outcome context: all plan phases implemented, suite 616→723, every money-path diff review-gated, commit proposal at [docs/COMMIT_PROPOSAL_2026-07-19_improvement_plan.md](../COMMIT_PROPOSAL_2026-07-19_improvement_plan.md).

## Lessons already applied to the repo this session

These came out of the harvest and were written into the living docs immediately (see the AGENTS.md / MODELS.md / OPERATIONS_MANUAL.md / executionledger.py diffs in the same commit set):

1. **`utc_epoch` named as the canonical naive-UTC→epoch conversion** (AGENTS.md timestamp contract) — the DI-1 bug was the *second* recurrence of this class; the conversion contract now has a name and a grep rule.
2. **Env-snapshot convention** (AGENTS.md Environment): `.env` loads in `main()`; module-level env snapshots must be registered in `_refresh_env_snapshots()` + the import-purity test, or the module imported lazily. Found because L1p2 distrusted its own brief's "unaffected" claim — the brief was wrong.
3. **`probe_*.py` naming + pytest.ini rationale** (AGENTS.md) — so neither is reverted as boilerplate.
4. **Fail-closed extended to the type domain + direction-of-change review lens** (AGENTS.md hard-lesson) — both Fable-gate MAJORs (wrong-shape-valid-JSON ledger; `''` order_id as identity) were type-domain gaps, and the one place a bug hid was the one cap-*loosening* change.
5. **Prompt-change workflow** (AGENTS.md): `panelprompts.py` is the single source; regenerating the golden fixture is part of any intentional prompt change; never hand-edit the fixture; never normalize whitespace quirks mid-refactor (they are live prompt bytes).
6. **Ledger locking contract** (AGENTS.md): reentrant flock, call-time path resolution, held across live order placement, the two locks never nested.
7. **Test-authoring traps extended** (AGENTS.md): `monkeypatch.undo()` re-points money-record paths at the real `history/` (a test once printed a real live order_id); patch socket *methods* not the class; `__new__`-construction tests network-touching `pragma: no cover` classes without sockets.
8. **Frozen stamped docs + pre-rename repo-wide grep recipe** (AGENTS.md docs convention).
9. **Provider facts → MODELS.md**: `genai.Client()` raises `ValueError` pre-network when unkeyed (load-bearing for preflight's NOT_CONFIGURED routing); Gemini env-var asymmetry vs `llm_utils`; preflight/panel parity is test-pinned; `timeout=90` on the four SDK clients; the grounding+schema coexistence gap is an accepted, now-documented limitation.
10. **Ledger recovery bounds → OPERATIONS_MANUAL**: repaired files must be `{"executions": [...]}`; a corrupt `.bak-` causes a fail-closed refuse-loop until manually replaced; run-start snapshots mean restore can under-count the daily cap by one day's post-snapshot spend (accepted at $5/$15 scale).
11. **`duplicate_of` / `fees_estimated` row semantics → executionledger docstring** — future analyzer/SELL work must consume them or reintroduce double-counting.
12. **`requirements_dev.txt` in AGENTS.md Environment** — the verify step needs it.

## Process lessons (converged across many agents)

- **Probe, don't read.** Every consequential catch this session came from executing a counterexample, not reading a diff: the two ledger MAJORs (five-line scripts against the real module), the gitignore semantics (`git check-ignore`), golden provenance (regenerating all 35 prompts from `git archive HEAD` to break the tautology risk), the `genai` exception type (`env -u` run), hygiene heuristics (synthetic secrets in a scratch repo). Rule of thumb from the Fable gate: *every fail-closed assertion in a review gets one executable counterexample attempt.*
- **Enumerate mechanically, not from the claim.** The gate AST-scanned the import graph for env snapshots rather than auditing the docstring's own list; verifiers used `git ls-files` over gitignore reasoning and `grep -c` for zero-occurrence claims. When a change says "all X are handled," derive X from the code and diff against the claim.
- **Plan anchors are ~95% right, and that's the dangerous number.** Four verifiers independently concluded: treat cited line numbers as starting offsets, re-derive by construct immediately before editing, and label anchors with their branch (main vs josh numbers differed for every LM-5 site). A plan that is mostly right relaxes reviewers.
- **Distrust your own brief at the seams.** The two best saves were agents contradicting their instructions with evidence: L1p2's import-graph trace (the `load_dotenv` move was *not* side-effect-free) and L6's alias grep (the documented fallback didn't exist yet). The house rule generalizes: the spec tells you where to look; the code tells you what's true — *including when the spec is your own brief.*
- **Shared-tree multi-lane concurrency works, with discipline:** file-ownership lists (section-scoped where needed), verification by `git diff -- <owned files>` never global `git status`, no `git add -A` ever, test-count deltas per-file not absolute, and the orchestrator re-certifies suite-green once after all lanes land. Reviewers should snapshot tree state at start/end — a mismatch is itself a finding.
- **Tests-before-wiring and golden-fixture-first are the safe shapes** for money-path changes and many-call-site refactors respectively. The reconcile-repair/duplicate-marking interaction was caught only because the repair test existed before the dedupe wiring; the 5-file prompt rewire was mechanical only because the fixture was generated from pre-change code and proven against it first.
- **Finding-ID comments at change sites** (`MP-3`, `DI-1`, …) made the final sweep dramatically cheaper — grep the diff for an ID, land on the code claiming to fix it. Keep as a house convention for audit-driven work.
- **The reflection harvest itself earned its cost again**: it surfaced the `monkeypatch.undo` near-miss detail, a factual error in a same-session AGENTS.md addition (the cap figures — fixed), the snapshot under-count bound nobody had stated aloud, and the two-client-stack trap — none of which appeared in any final report.

## Recommended follow-ups (not applied — owner or future session)

Ordered roughly by leverage:

1. **DX-7 has fired**: AGENTS.md is now well past its ~19KB bound (this session's additions included). Split the per-provider gotchas into MODELS.md's appendix (most duplicative content) and leave pointers.
2. **`.env.example` drift test**: assert every env var documented in `.env.example` is read somewhere in `*.py` — would have caught the dead `COINBASE_API_KEY` years earlier and guards the alias notes now.
3. **Env-snapshot completeness as a test**: commit the reviewer's AST-scan as a test asserting `_refresh_env_snapshots()` covers exactly the import graph's module-level env reads — converts a reviewer-enforced invariant into a self-enforcing one.
4. **Live-money entry-point registry**: a short AGENTS.md/OPERATIONS_MANUAL list of every script that can move real funds with its interlock status; review rule: any new script touching wallet keys or swaps ships with the double lock.
5. **Shared `live_lock` helper**: the `[LIVE LOCK]` banner + downgrade logic now exists in three hand-copies; extract before a fourth tool needs it.
6. **Tag glossary**: one-screen map of the greppable comment tags (`T1–T10`, `F1/F2`, `MP-N`, log-tag vocabulary) — the fastest navigation index in the codebase, currently tribal.
7. **Wallet-key handling**: `lp_arbitrage.prompt_for_private_key()` deserves a dedicated security look; OPERATIONS_MANUAL says nothing about expected key-material lifetime/handling.
8. **LM-6 residual**: the bot's inline `genai.Client()` still has no explicit timeout (plan-scoped exclusion).
9. **LG-1 test gap**: the gated primary-text dumps in `main()` are inspection-verified only; pin them when CQ-1 decomposes `main()`.
10. **STATE_VERSION operations note**: after a bump, a one-time "grades shifted / some unscoreable" run is expected — write it near the analyzer runbook so the next operator doesn't revert the fix.
11. **Root-doc long tail**: FIBONACCI_FEATURE.md's "proposed" framing vs shipped code needs a small research pass; ~17 unmoved root docs unverified for staleness; `docs/design/`+`docs/archive/` could use one-paragraph index READMEs distinguishing "never built" from "superseded".
12. **SUPERSEDED.md convention**: future entries should cite commit-anchored positions (`<sha>:file:line`) and follow the LM-5 entry's template (stated in its header).
13. **CI secret-scan caveat**: CI runs tests only; the hygiene script can't run there (inspects the local index) — a pre-commit hook is the natural future backstop.
14. **BIP39 tightening** for the mnemonic heuristic only if it proves noisy in practice.

## Orchestrator reflection

The verify-before-implement pass (4 agents, ~1 hour wall-clock) looked like overhead against an already audit-derived plan, and it still paid: every lane brief carried corrected anchors, and the handful of wrong ones (fees sites, lp_arbitrage gate, README :228, the sonnet-4 doc list) would each have misdirected an edit. The clearest structural win was separating implementation from adversarial review with *different instances* even at equal model strength — Fable-on-Fable review found two real money-path MAJORs precisely because the reviewer's job was type-domain enumeration and probing, not re-reading intent. The clearest orchestration cost was cross-lane dependency tracking landing entirely on me (the alias-before-docs ordering, SUPERSEDED-with-deletion same-commit rule, claudeutil serialization between L5 and L1p2) — the commit proposal encodes those orderings, but a future multi-lane plan should carry an explicit dependency table the way this one carried file-ownership lists. Finally: two agents independently rediscovered facts other lanes had already established (the missing `timeout` binary on macOS, the anchor-drift lesson) — a shared mid-session "lessons so far" channel would have saved that duplication; the fixed cost of this synthesis doc is the batch version of that channel.
