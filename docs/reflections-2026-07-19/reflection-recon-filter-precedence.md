# Reflection — filter/discovery precedence bug (recon/fix, 2026-07-19)

This was an implementation session on `crypto_trading_bot.py`: fix the
silently-ignored-filters bug, make the banner honest, add tests, update docs.
The fix itself is small (one pure function + a wiring block + two banner gates),
but most of the risk lived in a subtlety the task foresaw: **which of two
plausible resolutions the repo's own provenance machinery actually supports.**
The task told me to decide strict-error-always vs env-override-with-notice
"after reading how `get_config_source()` distinguishes CLI vs env." Reading it
first was the right order — it's a five-line function that scans `sys.argv` with
`arg.startswith(arg_name)` and only falls back to env, so it does cleanly tell a
CLI `--coins` from an `ANALYZE_COINS` env default. That made env-override the
supported choice rather than a guess, and I could reuse `get_config_source`
verbatim in `main()` instead of writing a second argv-sniffer. If I'd started
coding before reading it I'd probably have hand-rolled a parallel `'--chains' in
sys.argv` check and duplicated logic the repo already has.

**What slowed me down most: mapping "where do filters actually apply?"** The bug
report names the two gated paths (filter path ~2855, santiment discovery ~2842),
but to make the banner honest I had to be sure those were the *only* consumers of
`CHAINS`/`CATEGORIES` and that both truly require `USE_COIN_DISCOVERY`. I grepped
every `CHAINS`/`CATEGORIES` reference and traced `run_santiment_discovery`
(line ~2224) to confirm it also passes the filters — so filters apply in *both*
discovery sub-paths but never with explicit coins. Only after that could I
collapse the banner rule to a single honest predicate (`if USE_COIN_DISCOVERY`).
That grep-and-confirm loop was ~40% of my time and it's the part a careless fix
would skip — you could "fix the banner" by gating on `USE_COIN_FILTERING` and
still lie, because filtering-requested ≠ filtering-applies.

**Dead-end / thing I had to stop and reconsider — the DEX auto-CHAINS
interaction.** Live DEX mode auto-sets `CHAINS = ['solana']` (~line 2680 now)
*even with explicit coins*, "for discovery filtering," and prints its own
`[DEX] Auto-filtering to Solana chain`. My banner gate (`if USE_COIN_DISCOVERY`)
therefore *hides* the "Chain Filter: solana" banner line on a live-DEX
explicit-coins run. I went back and forth on this: is that a regression in
visibility? I concluded it's correct — that CHAINS value does not filter the
analyzed coins (explicit coins bypass the filter path entirely), it's a
validation constraint, and the DEX path already announces it separately. But it's
a genuine behavior change worth an owner's eye, and a future agent touching the
banner should know the DEX path deliberately populates `CHAINS` for a
non-filtering reason — so `CHAINS` being truthy does **not** imply "a coin filter
is in effect." That coupling is not obvious from the code near the banner.

**The residual env+env path I could not close within scope, and chose not to.**
The conflict check fires only on *CLI* filter flags (that's what the task
scoped). If a user persists *both* `ANALYZE_COINS` and `CHAINS`/`CATEGORIES` in
`.env` (env + env, nothing on the CLI), no error and no override fires: the
explicit coins win and the env filter is still silently inert. Banner honesty
still holds (the inert filter isn't advertised), so nothing *lies* — but a filter
the user configured does nothing without a peep. Erroring on env+env felt wrong
(it would break every run of a user's steady-state config, and provenance can't
tell "deliberate" from "stale"), so I left it as a documented proceed. I flagged
it in my report and in both docs. If the owner wants it tightened, the honest
options are a one-line `[NOTICE] filters in .env are inert while ANALYZE_COINS is
set` on that path, or moving the whole precedence decision to consider env
filters too — but that's a policy call, not a bug.

**What I wish I'd known before starting:**
1. That `get_config_source` is the *intended* provenance oracle and is
   reusable directly in `main()` — I re-derived that by reading it, but the task
   pointed me there and it paid off. Read it before designing the resolution.
2. That `resolve_analyze_coins_env` (T7) had *already* set
   `os.environ['ANALYZE_COINS']` a few lines above my insertion point (to fix
   trader "meme coin" vs "cryptocurrency" framing). My override branch therefore
   had to `os.environ.pop('ANALYZE_COINS', None)` to undo that, or the traders
   would keep explicit-coin framing while running discovery. Easy to miss — the
   env var is written for a reason unrelated to my change, and nothing near my
   edit hints that entering discovery mode late requires un-setting it.
3. Placement ordering: I inserted the conflict resolution right after
   `USE_COIN_FILTERING` is computed but *before* the discovery-methods block
   (`DISCOVERY_METHODS`, `USE_SANTIMENT_DISCOVERY`). That's deliberate — the
   override just flips `USE_COIN_DISCOVERY`, and discovery methods resolve
   normally afterward, so a `--discovery=santiment` that triggered the override
   still ends up with santiment discovery active. A future edit that moves the
   discovery-methods block earlier could break that assumption.

**Tips for the next agent working this file:**
1. "Filter requested" (`USE_COIN_FILTERING`) and "filter applies" are different
   facts — the second requires `USE_COIN_DISCOVERY`. Never gate operator-facing
   output on the first; it's the exact shape of the bug this session fixed.
2. `CHAINS` being non-empty does not mean a coin filter is active — the DEX live
   path populates it as a validation constraint with explicit coins present.
3. Late mode switches must reconcile `os.environ['ANALYZE_COINS']`, which is set
   early by T7 for trader prompt framing, not just the `ANALYZE_COINS` global.
4. The house test idiom paid off exactly as advertised: extracting a pure
   `resolve_*` helper (here `resolve_coin_selection_conflict`) let me pin the
   whole decision table without driving `main()`, mirroring
   `test_live_lock_dotenv.py`. Don't try to test this end-to-end.
</content>
