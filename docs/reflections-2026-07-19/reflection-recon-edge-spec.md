# Reflection — edge-vs-fee gating spec (recon/design, 2026-07-19)

This was a docs-only task (write one design spec, touch no code), so the risk
profile was inverted from an implementation session: the danger wasn't breaking
the money path, it was writing a spec that *reads* plausible but is wrong about
the code, which a future implementer would then trust. Most of my time went into
reading the actual gate chain rather than the prose, and that was the right
split. The spec-writing itself was fast once I'd traced the real control flow.

**The single most load-bearing discovery — and it slowed me down when I hit it:**
`resolve_structured_vote` returns *only* `vote.action` as a bare string. I had
assumed, from the schema and from `PanelDecision.votes` being a dict, that
confidence/reasons/etc. survived into the decision. They don't —
`PanelDecision.votes` is `{llm: action-string}`, and everything else the vote
carried (confidence, reasons, and any future edge field) is discarded at the
`resolve_structured_vote` seam before it ever reaches the decision object. This
completely reframed candidate (b): the spec can't just "read the confidence
that's already there" — *nothing* structured survives past that function.
Consuming any per-vote quantity for a gate means plumbing the `Vote` object
through to a new `PanelDecision` field. A future spec-writer or implementer
proposing anything that reasons over confidence, expected move, or per-panelist
metadata needs to know this up front: **the vote's rich fields are thrown away
at resolve time; only the action string propagates.** I'd have saved 20 minutes
if AGENTS.md's architecture map noted that the panel decision is action-only.

**Dead-end I started down:** my first instinct was to place the gate inside
`maybe_execute_buy` next to the exclusion-list check, because that's where the
other "should we really buy this" checks live. Reading the function's docstring
carefully stopped me: it holds the reentrant ledger lock across its whole span
and is explicitly the *spend-cap* stage. Putting a lock-free, ledger-free edge
check there would widen the lock hold for no reason and muddy a contract the
AGENTS.md locking section is emphatic about. Moving it up into
`gate_and_maybe_buy` (after consensus, before the cap stage) was clearly right
once I'd read *why* the current boundaries are where they are. Lesson that
generalizes: in this repo the gate boundaries are load-bearing and documented —
read the docstring's *rationale*, not just its behavior, before inserting.

**What I wish I'd known before starting:** (1) the `resolve_structured_vote`
discard, above. (2) That block-reason strings have no enum — `test_consensus.py`
assertions *are* the spec, so any new reason code is a test edit, not a constant
definition. I found this in AGENTS.md but only after drafting; it belongs in
the reader's head before they design reason codes. (3) The measured fee figure
(1.2%/side) lives in three conceptual places — the AGENTS.md gotchas, the
`executionledger` docstrings (`fees_estimated`), and now my spec's default — and
there's no single named constant. I flagged the sync risk in the spec but a
future implementer should consider making it one referenced constant.

**On the docs/design template convention:** the existing specs
(`CORRELATED_PAIR_FEATURE.md` etc.) are much more code-heavy and exploratory
(full dataclasses, CLI tables, "Open Questions" with option matrices) than what
this task needed — those describe greenfield subsystems, whereas an edge gate is
a small surgical insertion into an existing, well-tested path. I deliberately
wrote a tighter, more surgical spec (gate-placement diagram, honest
candidate-rejection arguments, explicit non-goals, test plan mapped to existing
test files) and kept the "Open questions for Josh" ending to match the house
convention. I think that's the right call, but it's worth noting the template
isn't one-size: a modification-spec and a new-subsystem-spec want different
shapes, and the docs-layout convention in AGENTS.md doesn't say so.

**Tips for the next agent:**
1. Before specifying anything that consumes a per-panelist signal, confirm
   whether that signal survives `resolve_structured_vote` — most don't.
2. Insert new gates in `gate_and_maybe_buy` (the shared, tested wiring), not in
   `maybe_execute_buy` (the lock-holding cap stage). Read the docstring
   rationale for both before choosing.
3. New block-reason codes are asserted into existence in `test_consensus.py`;
   there's no enum to import. Design the vocabulary against that test.
4. A schema change (new vote field) is simultaneously a schema change AND a
   prompt change: it ripples into per-provider schema variants
   (`schema_for_gemini`/`schema_for_claude` strip different keys), the golden
   prompt fixtures, and client-side bound enforcement in `parse_vote`. Budget
   for all four surfaces, not just the schema dict.
