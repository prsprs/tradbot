# Synthesis — 2026-07-21 reflections (Cascade-audit implementation session)

Sources: four implementing-agent reflections (ws1-ws2-p0-fixes.md, ws3-schema-v2.md,
ws8-ws9-ux-config.md, p2-design-docs.md) + ORCHESTRATOR.md. Session scope: verify external Cascade
evaluation → docs/IMPROVEMENT_PLAN_2026-07-20.md → implement WS1-WS5/WS8-WS9 + P2 design docs
(798 → 891 tests). Commit map: docs/COMMIT_PROPOSAL_2026-07-21_cascade_followup.md.

## Durable lessons (promoted to AGENTS.md this session)

1. **Brief with symbol anchors, not line numbers; never hand an agent a stale test-count baseline.**
   (WS1 agent: every cited line was wrong within a day on this always-dirty tree.)
2. **Effect-honesty is banner-honesty's missing twin.** A flag whose banner says "Enabled" needs its
   effect reachable in every mode combination — the Polymarket bypass existed because
   `filter_coins_by_polymarket` had one caller behind a three-condition gate and nothing asserted
   reachability. Test the effect per mode, not just the banner line.
3. **Module-level `logging.basicConfig` is an import side effect** — fibonacci_analyzer.py
   reconfigured the root logger for the whole bot via marketdata's import; correlation_tracker.py
   carries the identical pattern. Same class as the env-snapshot/import-purity rules.
4. **Implicit-universe aggregations:** any sum/count/dedupe written when only one row species existed
   (e.g. `intended_spend_on_date` filters no `side` because only BUY rows exist today) silently
   changes meaning when a roadmap feature diversifies that dimension. Audit aggregations against the
   feature roadmap; a first-SELL-writer must ship the side filter in the same change.
5. **Mark claims in briefs as verified vs inherited.** The WS8 agent's logging root-cause happened
   because the brief flagged one audit finding as possibly wrong; unflagged inherited errors get
   silently believed. Corollary for audits: stamp findings VERIFIED-BY-ME vs INHERITED.

## Actions taken this session (beyond the plan's workstreams)

- AGENTS.md updated with the five lessons above (concise bullets in the process-lessons and
  environment sections).
- Dispatched follow-up agents for the two mechanical improvements the reflections converged on:
  logging hygiene (guard module-level basicConfig in fibonacci_analyzer.py + correlation_tracker.py;
  import-purity test asserting no root-handler mutation) and documentation distillation
  (docs/RECORD_SCHEMA.md — the v1/v2 record field inventory the WS3 agent had to reconstruct from
  three files; docs/INVARIANTS.md — cap contract, lock ordering, record-evolution rules, and an
  aggregation table, which consumed half the design agent's time to reconstruct).

## Owner follow-up queue (decisions/review, not yet acted on)

1. **WS3 judgment calls** (flagged in its report + reflection): (a) `prompt_hash` is a
   coin+data+template identity, not per-provider prompt bytes — decide if per-panelist hashing is
   needed for reproducibility; (b) `models` includes init-failed panelists — decide whether to drop
   them (label-honesty argument) or keep (grouping convenience).
2. **Integrate-mode confidence merge** (`{**r1, **r2}` in build_vote_details) — WS3 agent requests
   reviewer re-check of the Round-1-carry vs Round-2-override semantics.
3. **Design-doc constants to push back on** (design agent's own least-confident list): 2%
   ledger/balance mismatch tolerance; full-exit-only sells; 200-decision/14-day WS10 promotion floor;
   cost-basis exposure blind spot on appreciated positions.
4. **Effect-honesty test sweep**: extend the WS1 idea repo-wide — for each banner "Enabled" line,
   a test that the gated effect fires in every discovery/mode combination that prints it.
5. **Implicit-universe grep-audit**: one-hour sweep of `for r in rows`-style aggregations in
   executionledger.py/historyutil.py/tradeanalyzer.py against the WS6-WS10 roadmap dimensions
   (side, mode, schema_version, status).

## Meta

The reflection harvest again surfaced material absent from every completion report (second
basicConfig instance, the near-miss on threading confidence through `resolve_vote`, the
RECORD_SCHEMA gap, four design push-back points). Practice confirmed; keep it.
