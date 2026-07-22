# docs/ index

One-screen map of the documentation. Root-level docs (README.md, AGENTS.md,
OPERATIONS_MANUAL.md, MODELS.md, the *_FEATURE.md reference set) are indexed
from README.md's "Internal Documentation" section; this file maps `docs/`.

## Start here (new contributor — human or AI)

1. `../AGENTS.md` — canonical agent/contributor guidance: environment, house
   rules, commit procedure, architecture map. Read first.
2. `INVARIANTS.md` — the money-path invariants and why they exist.
3. `RECORD_SCHEMA.md` — the history-record schema (v2), field by field.
4. `../OPERATIONS_MANUAL.md` — every flag and env var, operationally.

## Governance & operations (current)

- `MERGE_PROPOSAL_josh_to_main.md` — governs the josh→main merge (incl.
  2026-07-21 addendum). The breaking `--trading-mode` change is documented here.
- `RUNBOOK_whatif_cadence.md`, `RUNBOOK_live_acceptance.md` — operational
  runbooks.
- `SUPERSEDED.md` — capability map of what replaced what (house rule: every
  removal/supersession is recorded here).

## Design specs (`design/`)

Unimplemented proposals are marked 📋 Design Only in README.md's feature
tables; implemented features' specs carry superseded banners where the code
has moved past them. Money-path proposals (e.g. SPREAD_GATE,
EDGE_VS_FEE_GATING, SELL_EXIT_LIFECYCLE, PORTFOLIO_AWARENESS,
PROMPT_CONTRACT_V2) get spec + owner review before any code.

## Historical record (audit trail — kept deliberately)

- `audit-2026-07-19/` — full external audit (verdicts executed).
- `reflections-2026-07-18/`, `-2026-07-19/`, `-2026-07-21/`, `-2026-07-21b/`
  — first-person agent reflections harvested at phase checkpoints (repo norm).
- `IMPROVEMENT_PLAN_2026-07-20.md` — executed 2026-07-21 (banner at top).
- `COMMIT_PROPOSAL_2026-07-21_cascade_followup.md`,
  `COMMIT_PROPOSAL_2026-07-21_cycle2.md`,
  `COMMIT_RECONCILIATION_2026-07-21.md` — how the interleaved cycle-1+2
  changes were partitioned into commits (reconciliation is the executable map;
  the two proposals hold per-change rationale).
- `ACCEPTANCE_RESULTS_2026-07-19.md` — what was proven against real money.
- `archive/` — executed plans/proposals and superseded implementation docs.

## Archive policy

A commit proposal, session handoff, or implementation plan moves to
`docs/archive/` once its work has fully landed and the working tree is clean
(archive, never delete — these are the review trail for money-path changes).
Supersessions of *capabilities* are additionally recorded in `SUPERSEDED.md`.
