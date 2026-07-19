#!/bin/sh
# check_staged_hygiene.sh — run after `git add`, before `git commit`.
#
# Verifies the staged changes against this repo's never-commit rules
# (AGENTS.md hard rule #3) and scans the staged diff for secret-shaped
# content. Exit 0 = clean, exit 1 = violations printed to stderr.
#
# Usage:  ./scripts/check_staged_hygiene.sh
#
# This is a guard, not a substitute for reading the diff: it cannot know
# whether a real-world identifier (an order id, a fill price) is an
# intentional fixture or a leak — it flags, a human decides.

set -u
fail=0

staged=$(git diff --cached --name-only --diff-filter=d)
[ -z "$staged" ] && { echo "nothing staged"; exit 0; }

# --- 1. Never-commit paths (per-user data, credentials) ------------------
# history/ exceptions: recorder.py is source, test_expected_output.csv is a
# documented fixture (see AGENTS.md "Environment").
bad_paths=$(printf '%s\n' "$staged" | grep -E \
  '^(\.env$|cdp_api_key.*\.json$|live_trades/|paper_trades/|history/)' \
  | grep -vE '^history/(recorder\.py|test_expected_output\.csv)$')
if [ -n "$bad_paths" ]; then
  echo "NEVER-COMMIT PATHS STAGED:" >&2
  printf '%s\n' "$bad_paths" >&2
  fail=1
fi

# --- 2. Local-only files (owner's working notes, user-specific scripts) --
local_only=$(printf '%s\n' "$staged" | grep -E \
  '^(EVALUATION_LESSONS_LEARNED_2026-07-18\.md$|scripts/backfill_trading_mode)')
if [ -n "$local_only" ]; then
  echo "LOCAL-ONLY FILES STAGED (see docs/SESSION_HANDOFF_2026-07-18.md never-stage list):" >&2
  printf '%s\n' "$local_only" >&2
  fail=1
fi

# --- 3. Secret-shaped content in added lines -----------------------------
# Provider key prefixes, private-key blocks, and long literals assigned to
# key-like names. Tuned to skip the repo's own env-var indirection idioms.
secrets=$(git diff --cached | grep -nE '^\+' | grep -E \
  'sk-[A-Za-z0-9_-]{16}|AIza[A-Za-z0-9_-]{16}|xai-[A-Za-z0-9]{16}|pplx-[A-Za-z0-9]{16}|BEGIN( [A-Z]+)? PRIVATE KEY|(api_?key|api_?secret|token|password)["'"'"']?\s*[:=]\s*["'"'"'][A-Za-z0-9+/_-]{20,}' \
  | grep -viE 'os\.environ|getenv|load_dotenv|your-|fake-|placeholder|example|_ENV\b')
if [ -n "$secrets" ]; then
  echo "SECRET-SHAPED CONTENT IN STAGED DIFF (verify each is fake/placeholder):" >&2
  printf '%s\n' "$secrets" >&2
  fail=1
fi

[ "$fail" -eq 0 ] && echo "staged hygiene: clean ($(printf '%s\n' "$staged" | wc -l | tr -d ' ') files)"
exit "$fail"
