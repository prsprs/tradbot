# Synthesis — commit-prep recon session (2026-07-19, evening)

Session goal: independently verify the working tree against the existing commit
proposals before the owner executes them, resolve open hygiene issues, and
harvest reflections. Three recon agents ran in parallel (proposal-docs digest,
code-diff + hygiene verification, docs-reorg parity verification); each was
asked for a first-person reflection afterward. This file distills the durable
insights; the load-bearing ones were promoted into AGENTS.md the same evening
(commit-procedure items 8–10 and the wrong-interpreter note in Environment).

## What the session changed (beyond verification)

- Deleted stray root file `typescript` (447-byte accidental `script(1)`
  capture); added `typescript` to `.gitignore`.
- `git rm --cached history/llm_compare_history.json` (tracked user data the
  new allowlist couldn't retroactively untrack) — the commit-1 step the
  proposal called for, now staged.
- `.gitignore`: added standard Python tooling/packaging ignores
  (`.mypy_cache/`, `.ruff_cache/`, `.coverage*`, `htmlcov/`, `build/`,
  `dist/`, `*.egg-info/`).
- `docs/SUPERSEDED.md` row 17: recorded the two previously undocumented
  no-replacement deletions (`Restore Directional Analysis.md` transcript,
  empty `.windsurf/workflows/g.md`).
- Suite verified fresh: **798 passed** (`./venv/bin/pytest -q`, ~10s) —
  supersedes the 723/790 counts in earlier same-day docs.

## Verification outcomes (all three agents)

- **Proposal docs are trustworthy**: the 10-commit partition matches the tree;
  the one self-flagged violation (`historyutil.py` listed in commits 3 and 8)
  resolves by keeping the file wholly in commit 3.
- **Docs reorg parity is clean**: all 11 moved specs byte-identical or
  additive-banner-only; every deletion now accounted for in SUPERSEDED.md.
- **Hygiene is clean**: no secrets anywhere in diffs or new files; the one
  hygiene-script hit is the documented `your_private_key_here` placeholder.

## Distilled insights for future agents

1. **Wrong interpreter masquerades as codebase illness.** The diff agent
   reported "pytest collection hangs (2-min timeout)" — it had run bare
   `python3 -m pytest` despite having *read* the AGENTS.md instruction to use
   the venv. Two lessons: (a) reading a rule isn't applying it — when an
   environment command fails oddly, re-check the doc you already read;
   (b) never generalize a tooling failure into a claim about the code without
   ruling out invocation error first. (Promoted to AGENTS.md.)
2. **Verify by inversion.** Checking that documented moves happened finds
   nothing; enumerating every `D` and demanding an account for each found the
   two undocumented deletions. The gaps live in what nobody thought worth
   recording. (Promoted to AGENTS.md item 9.)
3. **`.gitignore` is forward-only.** `git ls-files` + `git check-ignore` on
   user-data dirs caught a tracked file a diff-only review structurally could
   not. (Promoted to AGENTS.md item 8.)
4. **Renames here are `D`+`A`/`??` pairs, not `R` records.** Reconstruct
   pairings by convention and always `git show HEAD:old | diff - new` — most
   are byte-identical but some carry one intentional line (a self-referencing
   comment). Read the diff, don't just check the exit status.
5. **Triage-then-inspect scales.** Looping cheap identical/differs checks over
   a file list and only reading the outliers verified an 11-doc reorg in
   minutes. But a keyword-filter summary that returns zero matches means the
   *filter* is wrong, not that nothing changed (MODELS.md was nearly missed
   this way).
6. **The doc web is the asset.** SUPERSEDED ↔ MERGE_PROPOSAL ↔ commit
   proposals cross-reference each other, which made independent verification
   fast. Read order for a committing session: SUPERSEDED → MERGE_PROPOSAL →
   base proposal → addendum, and treat the addendum as the current-state
   override — the base proposal alone stages incorrectly. Weakness to avoid
   repeating: exclusion lists ("not included" files) live only in the base
   proposal; consolidate exclusions wherever the newest addendum is.
7. **Point-in-time numbers rot within a day.** 723 vs 790 vs 798 all appeared
   in same-day docs. Stamp counts with command + date; re-run before staging.
   (Promoted to AGENTS.md item 10.)
8. **Read-only verification agents should report, not remediate.** The parity
   agent surfaced the SUPERSEDED gaps as findings rather than editing; the
   main session applied fixes with full context. That boundary kept three
   parallel agents from colliding in one dirty tree.
9. **`--stat` both halves first.** A −22k-line unstaged diff looks like mass
   deletion until read next to the +11k staged additions (a move). Reading
   unstaged and staged stats together up front prevents the false alarm.

## Deltas to the commit plan produced by this session

Absorbed into existing commits (file-partition preserved; see the note
appended to `docs/COMMIT_PROPOSAL_2026-07-19_showcase_addendum.md`):
- commit 1: `.gitignore` extra ignores, `history/llm_compare_history.json`
  untrack (now staged), AGENTS.md items 8–10 + interpreter note.
- commit 5: SUPERSEDED.md row 17 (rides with the file it already carries).
- commit 10: this synthesis file.
