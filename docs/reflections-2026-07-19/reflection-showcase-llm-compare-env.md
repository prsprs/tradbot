# llm_compare.py .env + zero-LLM-availability fix — session reflection (2026-07-19)

The single biggest surprise: python-dotenv's default `find_dotenv()` resolves its search
root from the **calling frame's file path**, not `os.getcwd()`. Once I added `load_dotenv()`
to `llm_compare.py`'s `main()`, `env -i PATH=$PATH HOME=$HOME ./venv/bin/python llm_compare.py`
did NOT simulate "no keys" the way I expected — it still found and loaded the repo's real
`.env` (walking up from `llm_compare.py`'s own directory) and fired off two real, paid Gemini
+ Claude calls before I noticed. Small/cents, within the pre-authorized budget, but not the
scenario I meant to exercise. I ended up temporarily `mv`ing `.env` out of the repo (md5-verified
before/after, restored immediately) to actually get a clean "zero keys" run. Next agent: if you
need to prove "no `.env`" behavior for a script that lives in the repo root, clearing env vars
alone is not enough — you need to either move the real `.env` (verify+restore!) or monkeypatch
`load_dotenv` in-process.

Second near-miss, self-inflicted: I ran `git stash` (no `-u`) mid-session just to get a "clean"
baseline test run, forgetting the repo currently has a large pile of pre-existing uncommitted
changes (per the initial `git status`) *and* untracked files paired with tracked ones (e.g. a
tracked `correlation_tracker.py` with a matching untracked test file). The stash reverted the
tracked file but left the untracked test importing a function that no longer existed post-revert
— a scary-looking `ImportError` / collection failure that had nothing to do with my change. `git
stash pop` fixed it immediately, but it cost a few minutes of confusion. Lesson: never `git
stash` in a repo with this much pending state unless you actually need to; `git stash -u`  or
just running tests without stashing would have been safer.

The repo is genuinely being edited concurrently by other agents/the owner while you work — my
baseline pytest count drifted from 726 → 733 → 739 passed across the session with no changes
from me, because a new test file (`tests/test_daily_cap_banner.py`) landed mid-session. Don't
panic-diff when the total test count doesn't match a stated baseline; re-run `--ignore` on your
own new file to isolate what you actually changed.

One thing that saved real time: AGENTS.md's "Env-snapshot convention" section and
`tests/test_import_purity.py` (crypto_trading_bot's TS-3 pattern + `_refresh_env_snapshots`)
gave me the exact template to follow and, critically, let me quickly rule out needing an
equivalent refresh function for `llm_compare.py` — a five-minute grep of every module in its
import graph confirmed all `os.environ` reads happen inside function bodies/`__init__`, never at
import time, so a plain `load_dotenv()` call sufficed. If I hadn't checked and just assumed
parity with the bot, I'd have either over-built an unnecessary refresh function or (worse) missed
one that was actually needed. Tip for the next agent: always grep the actual import graph before
assuming a "mirror the bot's pattern" instruction transfers 1:1 — the two entry points
(`crypto_trading_bot.py` vs `llm_compare.py`) have different import graphs and the pattern only
partially applies.
