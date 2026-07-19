# Merge proposal — `josh` → `main` (owner briefing)

**Prepared for Josh. Agents never push or merge — this is a briefing to
execute and time the merge yourself.** Nothing here has been pushed.

`josh` is **25 commits / 174 files / +26k−15k lines** ahead of `origin/main`
(re-verified 2026-07-19 evening after the full backlog landed; `main` has
**zero** divergent commits, so this is a clean fast-forward candidate)
(`github.com/prsprs/tradbot`). `main` — the branch other users run against
their own Coinbase accounts — is a **live-by-default bot with none of the
safety machinery** (no double lock, no fail-closed panel, no execution
ledger, no spend caps). Landing `josh` on `main` is the single
highest-leverage safety action in the whole plan; everything before this
line exists to make the merge safe and understandable.

## 1. The supersession map is complete

`docs/SUPERSEDED.md` now contains the **full capability map** of `main`'s
surface → `josh`, in addition to the pre-existing LM-5 entry. Verification
method for every row: checked **both sides** — `git show origin/main:<file>`
+ `git grep`/counts on `origin/main` for the old behavior, and the **working
tree** (Phase 0–4 changes are still uncommitted, so HEAD alone would be
wrong) for the new behavior. A file-list sweep
(`git ls-tree -r origin/main` vs the working tree) confirmed **every**
main-branch code/config file is still present except one dead duplicate
(`coinbaseutil2nokey.py`, parity verified) and four `test_*`→`probe_*`/`generate_*`
renames. **No live feature was removed.** The only intentionally dropped
capability in the entire diff is the fail-open single-model consensus
fallback (LM-5, owner-approved).

## 2. Behavior changes `main` users must act on

Ordered by how likely they are to bite. Full detail per row in
`docs/SUPERSEDED.md`.

1. **Live-by-default → whatif-by-default + double lock (the big one).**
   A `main` launch command or cron entry that relied on the live default
   will now run in **what-if**. To keep trading live, both are required:

   ```bash
   # OLD (main): traded live by default
   ./venv/bin/python crypto_trading_bot.py --coins=BTC,ETH

   # NEW (josh): must arm both locks, or it downgrades to whatif (with a loud notice)
   LIVE_TRADING_CONFIRMED=1 ./venv/bin/python crypto_trading_bot.py --live --coins=BTC,ETH

   # cron: set the env var in the crontab/environment, add --live to the command
   ```

   `--trading-mode=live` **alone no longer enables live trading** — it counts
   only as a request and is downgraded to whatif if either lock is missing.

2. **Satellite tools need the same interlock.** `leading_indicator_tester.py`
   and `lp_arbitrage.py` could place real Jupiter swaps with no safety gate;
   they now require `LIVE_TRADING_CONFIRMED=1` or they downgrade to
   paper/whatif with a `[LIVE LOCK]` banner.

3. **Requirements floor bumps — reinstall needed.** `josh` adds a top-level
   `requirements.txt` (`main` had none) with floors the code actually needs
   (`coinbase-advanced-py>=1.8,<2`, `anthropic>=0.94.0`, `openai>=1.66.0` —
   `main`'s effective versions crash 2 of 5 panelists). After merging, users
   must run `pip install -r requirements.txt` (and `requirements_dev.txt` to
   run the suite).

4. **Fail-closed everywhere.** Consensus now blocks on any error/refusal/
   parse-failure/missing panelist instead of shrinking the quorum; a corrupt
   `executions.json` is quarantined and auto-restored from a snapshot (or
   refuses the buy with a copy-paste recovery command) instead of being
   silently wiped. These are safer defaults, not workflow changes — but worth
   flagging so a blocked trade reads as intended behavior, not a bug.

5. **Model IDs move to `modelregistry.py`.** Anyone who edited inline model
   strings on `main` must now use `modelregistry.py` or the per-provider env
   overrides (`GEMINI_MODEL`, `CLAUDE_MODEL`, `OPENAI_MODEL`, `GROK_MODEL`,
   `PERPLEXITY_MODEL`).

## 3. Suite status

`./venv/bin/python -m pytest tests/ -q` → **798 passed** (0 failures,
re-verified 2026-07-19 evening at `josh` HEAD after all commits landed;
the 723 figure elsewhere in same-day docs is an earlier point-in-time
count). `import crypto_trading_bot` is
side-effect-free; bare `pytest --collect-only` no longer touches the exchange
(scoped by `pytest.ini`, real-swap scripts renamed `probe_*`).

## 4. Data-history posture — do NOT rewrite

Per-user data that predates the hygiene cleanup already lives in the
**shared remote** git history (`history/recommendations.json`, `live_trades/*`,
`history/llm_compare_history.json`) — every commit that added it is on
`origin/main`, and the only local commit touching those paths *removes*
tracking. This is **intentionally preserved**: **never** rewrite git history
(filter-repo/BFG) to purge it. Forward protection is the `history/*`
gitignore allowlist + `check_staged_hygiene.sh`, not a purge. See AGENTS.md
hard rule #3 (the GV-1 acceptance note) and `docs/SUPERSEDED.md` row 16.
Verified at prep time: those files are still on disk and now git-ignored.

## 5. Open coordination questions (for the owner)

1. **Who runs `main`, and how do they launch?** Each live user needs the
   §2.1 migration (add `--live` + `LIVE_TRADING_CONFIRMED=1`) or their bot
   goes quiet in what-if. Confirm the roster and give them notice before the
   merge.
2. **When to push/merge?** Owner-timed. Suggest doing it between cron windows
   so no one's live run straddles the cutover, and after users have the
   §2 migration in hand.
3. **Does `main`'s README need a transition note?** Recommend a short
   "Breaking change: live now requires `--live` + `LIVE_TRADING_CONFIRMED=1`;
   run `pip install -r requirements.txt`" banner at the top of the merged
   README, pointing at `docs/SUPERSEDED.md`.
4. **LICENSE decision.** There is no `LICENSE` file on either branch; the
   README currently states "private, all rights reserved" (README.md:268).
   Decide whether that line suffices or a formal `LICENSE` file should land
   with the merge.
5. **Merge shape.** `josh` is 25 clean commits ahead with no divergent
   `main` commits; decide fast-forward / merge-commit / (not recommended)
   squash — a merge commit preserves the money-path/infra commit separation
   that the commit plan built.

## 6. Pre-merge checklist (added 2026-07-19 evening, post-landing review)

An independent pre-merge review confirmed the branch is a net improvement
and merge-ready, with these items to settle **before** pushing:

1. **Notify every live `main` user first (blocking).** §2.1 is a silent
   behavior change for them: their cron/launch commands keep "working" but
   stop trading live. Nobody should discover this from a quiet bot. The
   merged README now carries a breaking-change banner at the top, but the
   banner only helps people who look — send the §2 migration directly to
   the user roster before the merge, not after.
2. **Real order details in `docs/ACCEPTANCE_RESULTS_2026-07-19.md` (owner
   decision).** The acceptance record contains a real order id, fill
   qty/price, and fees from the owner's account (its `run_id` also appears
   in `tests/fixtures/coinbase/duplicate_rejection.json`, kept deliberately
   per AGENTS.md). This is the owner's own data, committed knowingly as
   live-acceptance evidence, and it is already in `josh`'s committed
   history — which is never rewritten (GV-1) — so redacting the file now
   would remove nothing from history while destroying the evidentiary
   record. Recommendation: **keep it**, acknowledged here as intentional.
   If the owner prefers not to propagate it to the shared remote at all,
   the only real option is deciding that *before* the first push of these
   commits, since redaction-after-push is cosmetic.
3. **Whitespace: settled.** The two trailing-whitespace lines in
   `crypto_trading_bot.py` are fixed; the remaining `git diff --check`
   noise is entirely frozen lab/CSV session artifacts, which stay as-is
   (stamped records are never retouched).
4. **Deliberately uncommitted leftovers are not merge blockers.** The
   working tree's `EVALUATION_LESSONS_LEARNED_2026-07-18.md` edit (owner's)
   and `scripts/backfill_trading_mode.*` (GV-5, run/track/discard decision
   pending) are intentionally outside the 25 commits — they ride on no one's
   merge and can be decided any time.
5. **At merge time, re-verify fresh** rather than trusting this document's
   numbers: `git rev-list --count main..josh`, the suite count, and a last
   `git status` — same-day counts have already drifted twice (723→790→798).

---

*Prepared 2026-07-19. Supersession map: `docs/SUPERSEDED.md`. Findings:
`docs/audit-2026-07-19/EVAL.md`. Plan: `docs/audit-2026-07-19/IMPROVEMENT_PLAN.md`.*
