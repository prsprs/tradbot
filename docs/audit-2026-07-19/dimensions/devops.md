# DevOps & external integrations

## Summary
For a small real-money MVP, the external-integration code is notably disciplined: the Coinbase order path is idempotent and fails closed on ambiguous errors, and every secondary data provider (CMC, LunarCrush, Santiment) fails closed with explicit "unavailable" disclosure, client-side throttles, and HTTP timeouts. The weak spots are supply-chain and onboarding hygiene rather than runtime robustness: the four requirements files pin only floor versions that are below what the money-path code actually calls (anthropic output_config, OpenAI Responses API) with no lockfile or upper bounds, the README's Coinbase setup is factually wrong, and the history/ secret-hygiene story has a denylist gitignore that already tracks a per-user query log and disagrees with the manual staged-hygiene guard. None of these can cause a mis-trade (the fail-closed invariant holds), but several can silently break a second user's setup or leak one user's data.

## Strengths
- Coinbase order placement is genuinely fail-closed and idempotent: deterministic client_order_id (coinbaseutil2.py:150-162), recovery lookup on ANY create exception before ledgering a failure (coinbaseutil2.py:222-243), and an 'unverified_failure' state for un-confirmable placements so reconcile can repair later (coinbaseutil2.py:254-284).
- Secondary data integrations never inject silent/invented values: CMC and LunarCrush raise on any failure and are rendered as explicit 'DATA UNAVAILABLE'/'AMBIGUITY WARNING' lines (marketdata.py:459-524), with client-side throttles (coinmarketcaputil._rate_limit; marketdata._lunarcrush_throttle at 549-554) and 10s timeouts on every requests.get (marketdata.py:420,575,593; coinmarketcaputil.py:159,233,305,383).
- Core secrets are correctly gitignored end-to-end — .env, cdp_api_key*.json, *.pem, live_trades/ all confirmed via git check-ignore, and the previously-tracked live_trades/*.json files were successfully removed from the index (git ls-files is clean for them).
- The empirically-verified LunarCrush Cloudflare gotcha is correctly implemented: a real browser User-Agent plus Bearer auth (marketdata.py:537-563), matching the AGENTS.md note that Python's default UA gets a 403 that mimics an auth failure.
- Model IDs are centralized in modelregistry.py with per-provider env overrides, so provider rot (grok-4 died in weeks) is a one-file change and cannot be silently hardcoded across the five provider utils.

## Findings

### [HIGH/S] requirements.txt floor pins are below the SDK versions the money-path panelists actually require (anthropic output_config, OpenAI Responses API); no lockfile or upper bounds
**Evidence:** requirements.txt pins `anthropic>=0.18.0`, `openai>=1.0.0`, `pandas>=1.3.0`, `coinbase-advanced-py>=1.2.0` (all floor-only, no upper caps, no lockfile). But claudeutil.py:9-21 passes `output_config={'format':{'type':'json_schema',...}}` on every Claude vote (claudeutil.py:69,108,128,173) and its own comment states this needs 'anthropic>=0.94'; grokutil.py:25 calls `self.client.responses.create(...)` (OpenAI Responses API, added in openai-python 1.66). Installed venv is anthropic==0.94.0 / openai==2.31.0 / pandas==3.0.2 / coinbase-advanced-py==1.8.2 — far above the stated minimums.

**Impact:** A second user (or any rebuilt venv) whose resolver honors the stated minimums gets anthropic 0.18 (no `output_config` kwarg -> Claude panelist raises on every coin check) and openai 1.0 (no `.responses` -> Grok panelist AttributeError). The panel fails closed so this cannot mis-trade, but it silently drops 2 of 5 panelists / aborts runs. Conversely, with no upper bounds and no lockfile, a future breaking major (pandas 4, openai 3, a coinbase-advanced-py 2.x) lands unnoticed on the next `pip install -r requirements.txt` — 'reproducibility for the other users' is not actually guaranteed even though the current latest-resolve happens to work.

**Recommendation:** Raise floors to the tested/required versions (anthropic>=0.94, openai>=1.66) and cap the Coinbase SDK to the tested line (`coinbase-advanced-py>=1.8,<2`). Commit a `requirements.lock` (pip freeze of the working venv) alongside the loose file so every user reproduces the exact tested set; document `pip install -r requirements.lock` as the canonical path in README and AGENTS.md.

### [MEDIUM/S] README Quick Start mis-documents Coinbase setup: `export COINBASE_API_KEY` is a dead variable and the required cdp_api_key.json is never mentioned, so a second user cannot even start a what-if run
**Evidence:** README.md:28 instructs `export COINBASE_API_KEY=...   # Coinbase trading`, but a repo-wide grep shows COINBASE_API_KEY is read nowhere. Coinbase credentials are actually loaded from `cdp_api_key.json` (coinbaseutil2.py:120-137, keys creds['name']/creds['privateKey']), and crypto_trading_bot.py:2264 constructs `BlobbyTrader()` unconditionally in CEX mode — including in what-if — so a missing JSON raises FileNotFoundError at startup. README.md never mentions cdp_api_key.json (grep returns nothing).

**Impact:** A new user following the documented Quick Start exports a variable that does nothing and is never told to place cdp_api_key.json, so even the advertised 'no real trades' what-if run fails immediately with FileNotFoundError. The wrong guidance also sends users hunting for a Coinbase API-key string the bot cannot consume.

**Recommendation:** Replace the COINBASE_API_KEY line in README.md:25-28 with instructions to download the CDP key JSON to `cdp_api_key.json` at repo root (or point COINBASE_CREDENTIALS_FILE at it), and state explicitly that this file is required even for what-if runs. Mirror the wording already in .env.example's COINBASE_CREDENTIALS_FILE note.

### [MEDIUM/S] history/ gitignore is a denylist that misses llm_compare_history.json; that per-user prompt/response log is already git-tracked and re-accumulates under `git add -A`
**Evidence:** .gitignore:37-40 ignores only enumerated history files (recommendations.json, executions.json, analyzer_state.json, *.csv) plus history/lp/. history/recorder.py:13 defaults its store to `./history/llm_compare_history.json`. `git ls-files` shows history/llm_compare_history.json IS tracked (committed in ca355e2) and `git check-ignore` confirms it is NOT ignored; its content is recommendation records with prompt text, prompt_hash, llms_used and responses. history/test_recommendation_data.json is likewise tracked and un-ignored.

**Impact:** Every time any user runs llm_compare.py, their prompts and LLM outputs are written into a git-tracked file, so a routine `git add -A && git commit` publishes one user's private query history to the shared repo. The only backstop is the manual, opt-in scripts/check_staged_hygiene.sh, which is not run automatically.

**Recommendation:** Convert history/ to an allowlist ignore: `history/*` then `!history/__init__.py`, `!history/recorder.py`, `!history/test_expected_output.csv`, and `!history/test_recommendation_data.json` only if it is an intended fixture. Then `git rm --cached history/llm_compare_history.json` so it stops being tracked.

### [LOW/S] check_staged_hygiene.sh and .gitignore encode conflicting allowlists for history/, giving the guard both false positives and a real blind spot
**Evidence:** check_staged_hygiene.sh:23-25 flags every staged `history/` path as NEVER-COMMIT except recorder.py and test_expected_output.csv. But history/__init__.py, history/llm_compare_history.json, and history/test_recommendation_data.json are legitimately tracked (git ls-files), and .gitignore permits committing exactly those. So re-staging the tracked source history/__init__.py trips a false NEVER-COMMIT alarm, while gitignore silently lets the per-user llm_compare_history.json through.

**Impact:** The two guardrails that protect real user data disagree: false alarms on legitimate source train committers to wave the guard through, and the gitignore gap (finding above) is the one that actually matters. Maintenance hazard on money-adjacent hygiene tooling.

**Recommendation:** Derive the script's exception list and the gitignore history/ allowlist from one canonical set: add history/__init__.py (and any intended fixtures) to the script's `grep -vE` exceptions at check_staged_hygiene.sh:25, and tighten .gitignore to the same allowlist per the finding above.

### [LOW/S] Staged-hygiene secret regex cannot catch the DEX wallet secrets the repo reads from env (Solana private key / mnemonic seed) or unprefixed provider keys
**Evidence:** check_staged_hygiene.sh:44-46 matches only sk-/AIza/xai-/pplx- prefixes, PEM 'BEGIN ... PRIVATE KEY' blocks, and `keyword: "long-literal"` assignments. But the repo reads SOLANA_PRIVATE_KEY / WALLET_MNEMONIC (leading_indicator_tester.py:2196; test_trustwallet_swap.py:609-610), TWAK_WALLET_PASSWORD (dex/trustwallet.py:104), and unprefixed API keys LUNARCRUSH_API_KEY / COINMARKETCAP_API_KEY / COINGECKO_API_KEY. A raw base58 Solana secret key, or a 12/24-word mnemonic on its own line, matches none of the patterns. (The script self-describes as advisory, so this is partly already-documented.)

**Impact:** A committed wallet mnemonic or seed — directly spendable, and a cross-user money risk if a shared branch is pushed — would pass the 'staged hygiene: clean' check and give false assurance.

**Recommendation:** Add a mnemonic heuristic (a line of 12 or 24 lowercase words) and a base58/hex-blob detector, plus match assignments to *_MNEMONIC / SOLANA_PRIVATE_KEY / *_SEED variable names; keep the output advisory. Document in AGENTS.md that the guard now covers wallet secrets.

### [LOW/S] .env.example is incomplete versus env vars actually read — undocumented COINGECKO_API_KEY and the entire DEX/wallet secret surface (including spendable keys)
**Evidence:** grep of os.environ shows reads of COINGECKO_API_KEY (coingeckoutil.py:13), JUPITER_API_KEY (leading_indicator_tester.py:347; dex/jupiterutil.py:66,344), SOLANA_RPC_URL, SOLANA_PRIVATE_KEY, WALLET_MNEMONIC (dex/*, leading_indicator_tester.py:2196), TWAK_WALLET_PASSWORD (dex/trustwallet.py:104) — none appear in .env.example. Also coinmarketcaputil.py:18 prefers CMC_API_KEY over the documented COINMARKETCAP_API_KEY, and llm_utils/claude_client.py:18 accepts ANTHROPIC_API_KEY as an undocumented alias of CLAUDE_API_KEY.

**Impact:** A second user enabling the correlation tracker or DEX features has no documented list of the secrets those paths read — including spendable wallet key material — raising the chance of ad-hoc, unsafe handling. Minor for the core CEX path, where those vars are optional/experimental.

**Recommendation:** Add a commented 'Optional: correlation tracker / DEX (experimental)' block to .env.example listing COINGECKO_API_KEY, JUPITER_API_KEY, SOLANA_RPC_URL, with a pointed warning that SOLANA_PRIVATE_KEY / WALLET_MNEMONIC are spendable wallet secrets that must never be committed; note the CMC_API_KEY and ANTHROPIC_API_KEY aliases next to their documented names.

### [LOW/S] LLM panel clients set no explicit request timeout; a hung provider stalls scheduled/what-if runs on ~10-minute SDK defaults
**Evidence:** claudeutil.py:30 (anthropic.Anthropic), openaiutil.py:15 (openai.OpenAI), grokutil.py:12-15, and perplexityutil.py:13-16 all construct provider clients with no `timeout=`, inheriting the SDKs' ~600s defaults. By contrast every HTTP data integration sets one explicitly (marketdata.py:420,575,593 timeout=10; coinmarketcaputil.py:159,233 timeout=10/15; santimentutil.py:56 timeout=60; polymarketutil.py:83 timeout=30).

**Impact:** In the every-6-hours cron cadence (docs/RUNBOOK_whatif_cadence.md:127-186), a stuck provider connection can block a run for up to ~10 minutes per call with no alerting, and overlapping runs if the interval were shortened. It fails closed (no mis-trade), so severity is low.

**Recommendation:** Pass an explicit `timeout=` (e.g. 60-120s) when constructing each of the four provider clients so a hung call surfaces quickly as an abstain/parse-failure rather than stalling the run.

### [INFO/M] No CI and no crash/alerting story for the scheduled cadence — regressions and silent cadence failures reach other users only via manual discipline
**Evidence:** No .github/ directory or CI workflow exists (find over the repo returns none) and no .pre-commit-config.yaml is installed; AGENTS.md 'Verify before and after' documents running pytest by hand. tests/conftest.py blocks network, so pytest is CI-safe. docs/RUNBOOK_whatif_cadence.md:127-186 shows cron/launchd appending to a log with no exit-code check or freshness alert, and explicitly installs nothing.

**Impact:** On a multi-contributor real-money codebase, a money-path regression or a broken dependency resolve (see the requirements finding) is caught only if someone remembers to run the suite; a scheduled what-if run that starts crashing (expired model id, provider 4xx) silently stops feeding the analyzer with no notification. No direct money loss because the cadence is what-if, but the safety net degrades unnoticed.

**Recommendation:** Add a minimal GitHub Actions workflow (or a documented `make check`) that runs `./venv/bin/python -m pytest tests/ -q` plus scripts/check_staged_hygiene.sh on PRs, and wrap the cron/launchd command in a small script that alerts on non-zero exit or stale log. Frame it as test-CI for shared branches, consistent with AGENTS.md keeping the secret-scanner opt-in rather than mandated on others.
