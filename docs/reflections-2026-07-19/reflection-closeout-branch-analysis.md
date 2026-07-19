# Reflection — main-vs-josh branch archaeology (BUY-likelihood analysis), 2026-07-19

I came in expecting to catalog how josh added HOLD-bias; what `git show main:` actually revealed reframed the whole question. Main's BUY gate was literally `'BUY' in final_action` — a substring match — its "unanimous consensus" silently excused any panelist that crashed, and a lone surviving responder traded its own vote. So the honest headline wasn't "josh made trades rarer," it was "main made accidental trades commoner." I only trusted this after reading main's source directly; the docs (EVALUATION_LESSONS_LEARNED, ACCEPTANCE_RESULTS) turned out to be unusually accurate, but verifying them against `git show main:crypto_trading_bot.py` line-by-line was what let me say so with citations instead of faith.

What slowed me down: the sheer size of the crypto_trading_bot.py diff (~2600 lines) made whole-diff reading useless; grepping the diff for mechanism keywords (`LIVE_TRADING_CONFIRMED|cap|abstain|quorum|tiebreaker`) and then reading both branch versions of just the gate functions was 10x faster. Also a small trap: `panelprompts.py` exists in the working tree but has zero git history — an untracked audit-day refactor. Twenty minutes could have been lost attributing prompt changes to it; its own docstring ("byte-identical output, golden tests") ruled it out of the behavioral story.

The most useful analytical move was sorting every BUY-reducing change into SAFETY (locks, caps, fail-closed abstains — don't touch) vs DECISION-QUALITY (prompts, data supply, consensus arithmetic — legitimately tunable). Once sorted, the 25/25 HOLD run explained itself: no gate converted BUYs to HOLDs; the panel genuinely voted HOLD, exactly as it already did on main-era code per the 2026-07-18 session logs.

What I wish I'd had at the start: knowledge that EVALUATION_LESSONS_LEARNED_2026-07-18.md is effectively the design rationale for every josh commit — reading it first would have given me the hypothesis list for free.

Tips for the next archaeologist:
1. Read EVALUATION_LESSONS_LEARNED and ACCEPTANCE_RESULTS *before* the diffs — then verify each claim with `git show main:<file>` rather than trusting either the docs or the commit messages alone.
2. Diff-grep, don't diff-read: `git diff main...josh -- <file> | grep -nE '<mechanism keywords>'`, then read both full branch versions of only the functions that hit.
3. Check `git status --short <file>` for anything surprising you find on disk — this repo's working tree carries a whole executed audit (616→723 tests) that is not in any commit, and docstrings in those untracked files state their own behavioral guarantees.
