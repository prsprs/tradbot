# Reflection — P2 design-docs agent (Fable 5), 2026-07-21

First-person reflection, collected post-authoring per the reflection-harvest practice.

---

Designing against this codebase forced me to treat every recommendation as an *insertion* into an existing contract lattice rather than a clean-sheet choice: the ledger lock's read-to-write span (MP-3), the "caps live in maybe_execute_buy, decision-quality lives in gate_and_maybe_buy" boundary, and the T3 optional-field record pattern each dictated placement decisions I'd otherwise have argued from taste. The most useful discipline was asking, for every new behavior, "which existing function's docstring rationale does this violate?" — that's how the portfolio guards ended up inside the lock while the edge gate stays outside it.

The `intended_spend_on_date` landmine is the pattern I'd call an **implicit-universe assumption**: a summation written when only BUY rows could exist, correct by accident, that silently changes meaning the day a new row species appears. It's not a bug today — it's a bug *conditional on a planned feature*. To find others systematically: enumerate every aggregation over ledger/history rows (sums, counts, positions, dedupe sets) and ask "does this filter on the dimension a roadmap feature is about to diversify (side, mode, version, status)?" A one-hour grep-audit of `for r in rows` sites against the WS6-WS10 feature list would probably surface two or three more.

Least confident — Josh should push back here: (1) the 2% ledger/balance mismatch tolerance is a guess dressed as a constant; I have no fee-in-kind dust data to justify it. (2) Full-exit-only sells are simple but may be wrong for a $100/day book that ever scales. (3) The WS10 promotion floor (200 decisions / 14 days) is round-number reasoning, not power analysis. (4) Cost-basis (vs mark-to-market) exposure has the stated blind spot on appreciated positions — I chose determinism over accuracy and that's a values call, not a derivation.

What would improve future design tasks: a short **invariants doc** — the cap contract, lock ordering, record-shape evolution rules, and the "which sums filter on what" table — currently these live scattered across docstrings, test assertions, and AGENTS.md, and reconstructing them consumed half the design time. Second: the EDGE_VS_FEE template worked well, but a required "what existing aggregations does this feature's new data flow through?" section would have made the cap-sum landmine a checklist find rather than a lucky read.
