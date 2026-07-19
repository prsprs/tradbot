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
# history/ exceptions: recorder.py and __init__.py are source, the other
# two are documented fixtures (see AGENTS.md "Environment").
bad_paths=$(printf '%s\n' "$staged" | grep -E \
  '^(\.env$|cdp_api_key.*\.json$|live_trades/|paper_trades/|history/)' \
  | grep -vE '^history/(recorder\.py|__init__\.py|test_expected_output\.csv|test_recommendation_data\.json)$')
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

# --- 4. Wallet-secret heuristics (mnemonics, Solana keys) -----------------
# A directly-spendable wallet secret is worse than an API key: env-var names
# that conventionally hold one (*_MNEMONIC, *_SEED, SOLANA_PRIVATE_KEY), a
# BIP39 mnemonic-phrase heuristic (12+ consecutive lowercase words -- covers
# both 12- and 24-word phrases), and a base58-length heuristic (Solana
# private/secret keys are ~87-88 base58 chars, which excludes 0/O/I/l).
# Advisory, same as section 3: flags for human review, does not block any
# differently than the existing secret check above.
wallet_env_names=$(git diff --cached | grep -nE '^\+' | grep -E \
  '[A-Z][A-Z0-9_]*(_MNEMONIC|_SEED)[A-Z0-9_]*["'"'"']?[[:space:]]*[:=]|SOLANA_PRIVATE_KEY["'"'"']?[[:space:]]*[:=]' \
  | grep -viE 'os\.environ|getenv|load_dotenv|your-|fake-|placeholder|example|_ENV\b')
mnemonic_phrase=$(git diff --cached | grep -nE '^\+' | grep -E \
  '([a-z]{3,8} ){11,}[a-z]{3,8}')
base58_key=$(git diff --cached | grep -nE '^\+' | grep -E \
  '[1-9A-HJ-NP-Za-km-z]{86,88}')
wallet_secrets=$(printf '%s\n%s\n%s\n' "$wallet_env_names" "$mnemonic_phrase" "$base58_key" | grep -v '^$' | sort -u)
if [ -n "$wallet_secrets" ]; then
  echo "WALLET-SECRET-SHAPED CONTENT IN STAGED DIFF (mnemonic/base58/env-var heuristics -- verify each is fake/placeholder):" >&2
  printf '%s\n' "$wallet_secrets" >&2
  fail=1
fi

[ "$fail" -eq 0 ] && echo "staged hygiene: clean ($(printf '%s\n' "$staged" | wc -l | tr -d ' ') files)"
exit "$fail"
