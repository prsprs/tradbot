# ADDENDUM to COMMIT_PROPOSAL_2026-07-19_improvement_plan — showcase/UX session changes

Written 2026-07-19 (second session this date), per the AGENTS.md commit
procedure ("put addenda in the doc itself and read them before staging").
The improvement-plan proposal's file partition still stands; this addendum
maps the ADDITIONAL changes from the showcase/log-review session onto it.
Rule applied: a file lives wholly in one commit, so files already assigned
by the base proposal ABSORB today's deltas — their commit messages should
gain the bracketed additions below. Net state after both sessions:
**790 tests passing** (audit ended at 723), imports clean.

## Today's logical changes (what happened)

1. **Correlation tracker verbose-report crash fix** — shared
   `print_test_result_detail` helper (was two duplicated inline printers;
   crashed on skipped Granger p_value=None; skipped tests showed false
   PASS). Discovery report now survives to disk, unblocking
   leading_indicator_tester.
2. **llm_compare .env + fail-fast** — loads .env in main() (TS-3 pattern,
   import graph verified snapshot-free); zero-initialized-LLM runs exit
   non-zero without writing a history record.
3. **Operator visibility** — startup banner AND run summary show
   `Daily spend cap: $X ($Y spent today [UTC])` (reuses
   executionledger.live_spend_today, lock-free read); run summary gains
   per-coin `Votes:` line (HOLD / SELL / BUY->ordered / BUY->gate-blocked /
   BLOCKED).
4. **Live-lock hardening** — LIVE_TRADING_CONFIRMED supplied via .env is
   stripped and loudly ignored (strip_dotenv_live_confirmation); the env
   half of the double lock is shell-only by construction now.
5. **Panel response logging** — full panelist text goes to
   `<HISTORY_DIR>/panel_responses/<run_id>.log` (gated by the existing
   --log-rounds/LOG_INTEGRATION_ROUNDS); console gets concise [PANEL]
   lines + one [PANEL LOG] pointer; --show-responses/SHOW_PANEL_RESPONSES
   restores inline dumps.
6. **Structured votes for grok + perplexity** — native json_schema output
   adopted for both (live re-probe 2026-07-19 verified Grok schema +
   web_search coexist — the 2026-07-18 blocker was an unverified
   assumption); delimiter-tag parsing survives only as a
   schema-param-rejection fallback; golden prompt fixture regenerated
   (intentional prompt change: delimiter → schema instruction).
7. **Docs/config** — .env.example: spend-cap section ($25/$50/$100
   recommended scale), LIVE_TRADING_CONFIRMED warning + tradbot-live
   alias, panel-choice guidance; OPERATIONS_MANUAL --coins max 6→5 fix +
   extras-install note; README extras note; runbook cap notes; AGENTS.md
   new Environment/test-trap/process lessons; MODELS.md structured-output
   status; plus a post-session docs-consistency sweep (see its own report
   in the session records).

## File → commit mapping

**Files already in the base proposal (absorb today's deltas; append to
their commit messages):**
- `crypto_trading_bot.py` — [+ daily-cap banner/summary line, Votes:
  summary line, dotenv live-lock strip, panel-response log routing,
  structured-vote path routing]
- `voteschema.py` — [+ grok_text_format, perplexity_response_format,
  vote-path tagging, schema_param_rejected]
- `grokutil.py`, `perplexityutil.py` — [+ structured-first vote calls with
  tag fallback]
- `panelprompts.py` (untracked/new in base proposal) — [+ drift-note:
  all five providers on schema_instruction]
- `llm_compare.py` — [+ load_dotenv in main, zero-LLM fail-fast]
- `correlation_tracker.py` — [+ shared report printer, skipped-test
  rendering]
- `tests/test_structured_requests.py`, `tests/test_panel_prompts.py`,
  `tests/fixtures/panel_prompts/golden_prompts.json`,
  `tests/fixtures/structured_output/grok.json` / `perplexity.json` —
  [+ adoption tests, regenerated golden, re-probe fixture deltas]
- Doc files (`README.md`, `OPERATIONS_MANUAL.md`, `AGENTS.md`,
  `MODELS.md`, `LLM_COMPARE_OPERATIONS_MANUAL.md`, `.env.example`,
  `docs/RUNBOOK_live_acceptance.md`) — [+ today's additions listed in §7]

**New files from this session (assign to the commit carrying their
subject file):**
- `tests/test_correlation_verbose_report.py` → with correlation_tracker.py
- `tests/test_llm_compare_env.py` → with llm_compare.py
- `tests/test_daily_cap_banner.py`, `tests/test_run_summary.py`,
  `tests/test_live_lock_dotenv.py`, `tests/test_panel_response_log.py`
  → with crypto_trading_bot.py
- `docs/reflections-2026-07-19/SYNTHESIS-showcase-session.md` and
  `docs/reflections-2026-07-19/reflection-*.md` (6 agent reflections)
  → with the session-records/docs commit
- `docs/COMMIT_PROPOSAL_2026-07-19_showcase_addendum.md` (this file)
  → with the session-records/docs commit

**Money-path callout (per AGENTS.md):** items 3, 4, and 6 above touch the
money path (cap display reads the ledger; live-lock arming semantics;
vote parsing feeding consensus). All are fail-closed-preserving: 4 narrows
how live can arm; 6 converts spurious abstains into real votes but never
loosens abstain semantics (garbage/truncation still abstains, never
falls back to tag-parsing the same payload). Direction-of-change note:
item 6 makes BUY verdicts more *reachable* (fewer manufactured abstains) —
flagged deliberately as the one loosening-direction change; review focus
belongs there.

**Owner config note (not committed):** the owner's `.env` was revised to
the $25/$50/$100 cap scale with the trio panel — mirrored in
`.env.example` so the repo documents the same recommended setup.

---

## Second addendum — commit-prep recon session (2026-07-19, evening)

Independent verification pass before execution (three parallel recon agents:
proposal digest, code-diff + hygiene, docs-reorg parity). Verdict: the plan
matches the tree; hygiene clean; docs parity clean. Fresh suite count:
**798 passed** (`./venv/bin/pytest -q`) — supersedes 723/790 above.

Deltas absorbed (file-partition preserved; each file stays in its one commit):

- **commit 1 (hygiene/infra)** additionally carries: `.gitignore` new ignores
  (Python tooling caches, `build/`/`dist/`/`*.egg-info/`, `typescript`
  script-capture guard); the already-staged
  `git rm --cached history/llm_compare_history.json`; AGENTS.md additions
  (commit-procedure items 8–10, wrong-interpreter note). Stray root file
  `typescript` was deleted from disk (untracked junk, never committed).
- **commit 5** additionally carries SUPERSEDED.md **row 17** (records the two
  no-replacement deletions: the 407 KB transcript and empty `g.md`).
- **commit 8** clarification resolved: `historyutil.py` stays wholly in
  **commit 3**; commit 8 gets no copy of it.
- **session-records commit (10)** additionally carries
  `docs/reflections-2026-07-19/SYNTHESIS-commit-prep-recon.md`.

Exclusions restated (they appear only in the base proposal — do not stage):
`EVALUATION_LESSONS_LEARNED_2026-07-18.md` (owner's uncommitted edit),
`scripts/backfill_trading_mode.py` + `scripts/backfill_trading_mode_mapping.md`
(owner decision pending).
