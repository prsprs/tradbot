# Operations Manual

This document describes the programs, environment variables, APIs, and credential configuration for the trading bot system.

---

## Programs

### 1. Trading Bot (`crypto_trading_bot.py`)

The main trading bot that analyzes cryptocurrency coins and makes buy/sell/hold recommendations using one or more LLMs.

**Usage:**
```bash
python crypto_trading_bot.py [OPTIONS]
```

**Command-Line Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--trading-mode` | `live`, `whatif` | `whatif` | Trading mode. `whatif` simulates only. Selecting `live` alone does NOT trade: real orders additionally require the `--live` flag AND `LIVE_TRADING_CONFIRMED=1` in the environment (double interlock); otherwise the run downgrades to what-if with a loud `[LIVE LOCK]` banner |
| `--llm-mode` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `compare`, `integrate` | `compare` | LLM mode for recommendations |
| `--primary-llm` | `gemini`, `claude`, `openai`, `grok`, `perplexity` | `gemini` | Primary LLM for discovery |
| `--compare-llms` | comma-separated | `gemini,claude` | LLMs for compare/integrate mode |
| `--coins` | comma-separated | *(empty)* | Specific coins to analyze (max 5), or empty for discovery mode |
| `--discovery` | comma-separated | `llm` | Discovery method(s): `llm`, `santiment`, or both (e.g., `llm,santiment`) |
| `--chains` | comma-separated | *(empty)* | Filter coins by blockchain (e.g., `solana,base`). Requires cache file |
| `--categories` | comma-separated | *(empty)* | Filter coins by category (e.g., `meme-coins,defi`). Requires cache file |
| `--polymarket-filter` | `true`, `false` | `false` | Only analyze coins with active Polymarket prediction markets |
| `--require-consensus` | `true`, `false` | `true` | Require LLM consensus for action |
| `--tiebreaker` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `none` | `gemini` | Tiebreaker LLM when no consensus |
| `--log-rounds` | `true`, `false` | `true` | Capture the full panelist responses to a per-run log file at `<HISTORY_DIR>/panel_responses/<run_id>.log` (env: `LOG_INTEGRATION_ROUNDS`). The console shows concise `[PANEL]` lines plus one `[PANEL LOG]` pointer to that file; set `false` to skip the capture entirely |
| `--show-responses` | flag | *(off)* | Also echo the full panelist responses inline on the console (the legacy behavior), in addition to writing the `panel_responses/` log. Env: `SHOW_PANEL_RESPONSES=true` |

**Configuration Precedence:**
CLI arguments take precedence over environment variables. If neither is set, the default value is used.
The startup banner shows the source of each configuration value (e.g., `[--trading-mode]`, `[TRADING_MODE env]`, or `[default]`).

**What it does:**
1. Discovers coins to analyze (via LLM or specified list)
2. Builds a market-data block per coin (Coinbase OHLCV + Fibonacci primary; CMC, LunarCrush social, and Google Trends as labeled secondaries) and injects it into every analysis prompt
3. Queries LLM(s) for structured trading votes
4. Optionally compares or integrates recommendations from multiple LLMs (fail-closed consensus)
5. Records recommendations to history with `trading_mode` and `run_id` (for later analysis)
6. Executes trades on Coinbase (only when the live double interlock is fully armed) or simulates them (`whatif`)

**Output:**
- Console output with concise per-panelist `[PANEL]` lines and recommendations. Full panelist responses are **not** printed inline by default; they go to `<HISTORY_DIR>/panel_responses/<run_id>.log` (gated by `--log-rounds`/`LOG_INTEGRATION_ROUNDS`), and the console prints one `[PANEL LOG]` pointer to that file. Use `--show-responses` / `SHOW_PANEL_RESPONSES=true` to restore the inline essays.
- A startup banner and end-of-run summary line: `Daily spend cap: $X ($Y spent today [UTC])` (shown regardless of the vote, since a HOLD/SELL short-circuits the buy path).
- A per-coin `Votes:` line in the run summary, e.g. `Votes: BTC HOLD | ETH BUY->ordered | SOL BUY->gate-blocked | ...` (labels: `HOLD`, `SELL`, `BUY->ordered`, `BUY->gate-blocked`, `BLOCKED`).
- Trade executions on Coinbase (fully armed live mode only), with fill confirmation recorded to the execution ledger (`history/executions.json`)
- History records saved to `./history/recommendations.json`
- What-if summary showing simulated trades (whatif mode only)

---

### 2. Coin Cache Refresh (`refresh_coin_cache.py`)

On-demand script that fetches Coinbase-tradeable coins and enriches them with category and blockchain data. Creates a local cache file used by the trading bot for filtering.

**Usage:**
```bash
# Using Santiment (free, recommended)
python refresh_coin_cache.py --source=santiment

# Using LunarCrush (requires paid Builder plan)
LUNARCRUSH_API_KEY=your_key python refresh_coin_cache.py --source=lunarcrush
```

**What it does:**
1. Fetches all tradeable coins from Coinbase
2. For each coin, fetches category and blockchain data from selected source
3. Creates a backup of any existing cache (`coin_cache.backup.json`)
4. Writes enriched data to `coin_cache.json`
5. Prints summary of categories and blockchains found

**Output:**
- `coin_cache.json` - Main cache file used by trading bot
- `coin_cache.backup.json` - Backup of previous cache (for recovery)

**Data Sources:**
- **Santiment** (default): Free API, single bulk GraphQL query. Recommended.
- **LunarCrush**: Requires paid Builder plan ($300+/month). Legacy option.

**Note:** When using `--discovery=santiment` or `--discovery=llm,santiment`, the trading bot automatically refreshes the cache at startup to ensure fresh volume metrics.

**Example Output:**
```
==================================================
COIN CACHE REFRESH
==================================================

Fetching Coinbase tradeable coins...
  Found 250 coins on Coinbase
Fetching LunarCrush coin data...
  Page 1: 1000 coins (total: 1000)
  Page 2: 500 coins (total: 1500)
  Total LunarCrush coins: 1500

Building cache...
  Matched in LunarCrush: 220
  Not in LunarCrush: 30
Backed up existing cache to ./coin_cache.backup.json
Saved to ./coin_cache.json

==================================================
CACHE SUMMARY
==================================================
Refreshed: 2026-04-22T04:30:00+00:00
Total coins: 250
Matched with LunarCrush: 220

Top categories:
  meme-coins: 45
  defi: 38
  layer-1: 25
  ...
==================================================

Cache refresh complete!
```

---

### 3. Trade Analyzer (`tradeanalyzer.py`)

Standalone program that scores past recommendations **benchmark-relative**: each matured recommendation's coin return is compared against a BTC buy-and-hold benchmark over the same window, minus the measured fee floor (~2.4% round trip), split by `trading_mode` (live vs what-if; `unknown` records are excluded, never guessed).

**Usage:**
```bash
python tradeanalyzer.py
```

**What it does:**
1. Loads recommendations from `./history/recommendations.json`
2. Selects records that have reached scoring maturity (score-at-maturity windows)
3. Fetches coin and BTC benchmark prices (Coinbase primary, CoinGecko fallback)
4. Scores each recommendation by excess return vs the fee-adjusted BTC benchmark (not raw price direction)
5. Generates per-LLM and per-mode (live/whatif) statistics; `unknown`-mode records are counted and excluded

**Output:**
- Console report with accuracy statistics
- CSV files, split by mode: `./history/analysis_live_YYYYMMDD.csv`, `./history/analysis_whatif_YYYYMMDD.csv` (benchmark-relative columns; see the analyzer section below)

**What today's evidence does / does not show:** a successful live acceptance
run (order placed, filled, ledgered, reconciled) validates the **execution
path** — it says nothing about whether the panel's calls are actually good.
Only run this analyzer's output as the source of truth for strategy
performance, never "it placed a real trade and nothing broke" — as of
2026-07-19 only 6 mature directional records exist, nowhere near enough
sample to conclude anything. Also account for the fee floor when reading
results: round-trip fees run ≈1.2% of notional per side (≈$0.059 observed on
a $5 live fill), so at small notional a recommendation needs **more than
≈2.4% edge round-trip** before it counts as a real win rather than noise
below the fee floor.

---

## Environment Variables

> **Note:** All configuration environment variables can also be set via command-line arguments.
> CLI arguments take precedence over environment variables. See the Command-Line Options table above.

### Trading Bot Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `whatif` | Trading mode. Live trading also requires `--live` and `LIVE_TRADING_CONFIRMED=1` (see the double interlock note in the options table above) |
| `LLM_MODE` | `compare` | Mode of operation: `gemini`, `claude`, `openai`, `grok`, `perplexity`, `compare`, or `integrate` |
| `PRIMARY_LLM` | `gemini` | LLM used for coin discovery and first analysis |
| `COMPARE_LLMS` | `gemini,claude` | Comma-separated list of LLMs to use in compare/integrate modes |
| `REQUIRE_CONSENSUS` | `true` | If `true`, only act when all LLMs agree (compare/integrate modes) |
| `INTEGRATION_TIEBREAKER` | `gemini` | LLM to use as tiebreaker when no consensus: `gemini`, `claude`, `openai`, `grok`, `perplexity`, or `none` |
| `LOG_INTEGRATION_ROUNDS` | `true` | If `true`, capture full panelist responses to `<HISTORY_DIR>/panel_responses/<run_id>.log` (console shows concise `[PANEL]` lines + a `[PANEL LOG]` pointer). Same as `--log-rounds` |
| `SHOW_PANEL_RESPONSES` | `false` | If `true`, also echo the full panelist responses inline on the console (legacy behavior). Same as `--show-responses` |
| `ANALYZE_COINS` | *(empty)* | Comma-separated list of coins to analyze (max 5). If empty, uses discovery mode |
| `DISCOVERY` | `llm` | Discovery method(s): `llm`, `santiment`, or both comma-separated |
| `CHAINS` | *(empty)* | Filter by blockchain networks (e.g., `solana,base`). Requires cache file |
| `CATEGORIES` | *(empty)* | Filter by categories (e.g., `meme-coins,defi`). Requires cache file |
| `POLYMARKET_FILTER` | `false` | If `true`, only analyze coins with active Polymarket prediction markets |

### API Keys

| Variable | Required For | Description |
|----------|--------------|-------------|
| `CLAUDE_API_KEY` | Claude | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI | OpenAI API key |
| `XAI_API_KEY` | Grok | xAI API key for Grok |
| `PERPLEXITY_API_KEY` | Perplexity | Perplexity API key |
| `GOOGLE_API_KEY` | Gemini | Google AI API key (or use application default credentials) |

### File Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `COINBASE_CREDENTIALS_FILE` | `cdp_api_key.json` | Path to Coinbase CDP credentials JSON file |
| `HISTORY_DIR` | `./history/` | Directory for recommendation history and analysis CSV files |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `COINGECKO_API_KEY` | *(empty)* | Optional CoinGecko Pro API key (free tier works without it) |
| `LUNARCRUSH_API_KEY` | *(empty)* | LunarCrush API key (only needed when running `refresh_coin_cache.py`) |

---

## APIs and Services

### 1. Google Gemini API

**Purpose:** Primary LLM for coin discovery and analysis with real-time web search (grounding)

**Authentication:** 
- Environment variable `GOOGLE_API_KEY`, or
- Application Default Credentials (ADC) via `gcloud auth application-default login`

**Library:** `google-genai`

**Model:** see `modelregistry.py` / `MODELS.md` (env override: `GEMINI_MODEL`)

**Features used:** Google Search grounding for real-time market data

---

### 2. Anthropic Claude API

**Purpose:** Secondary LLM for comparison/integration modes

**Authentication:** Environment variable `CLAUDE_API_KEY`

**Library:** `anthropic`

**Model:** see `modelregistry.py` / `MODELS.md` (env override: `CLAUDE_MODEL`)

---

### 3. OpenAI API

**Purpose:** Secondary LLM for comparison/integration modes

**Authentication:** Environment variable `OPENAI_API_KEY`

**Library:** `openai`

**Model:** see `modelregistry.py` / `MODELS.md` (env override: `OPENAI_MODEL`)

---

### 4. xAI Grok API

**Purpose:** Secondary LLM for comparison/integration modes with web search

**Authentication:** Environment variable `XAI_API_KEY`

**Library:** `openai` (OpenAI-compatible API)

**Base URL:** `https://api.x.ai/v1`

**Model:** see `modelregistry.py` / `MODELS.md` (env override: `GROK_MODEL`)

**Features used:** Web search tool for real-time data

---

### 5. Perplexity API

**Purpose:** Secondary LLM for comparison/integration modes with built-in search

**Authentication:** Environment variable `PERPLEXITY_API_KEY`

**Library:** `openai` (OpenAI-compatible API)

**Base URL:** `https://api.perplexity.ai`

**Model:** see `modelregistry.py` / `MODELS.md` (env override: `PERPLEXITY_MODEL`)

---

### 6. Coinbase Advanced Trade API

**Purpose:** Trading execution and price data

**Authentication:** JSON credentials file (default: `cdp_api_key.json`)

**Library:** `coinbase-advanced-py` (REST client)

**Credentials file format:**
```json
{
  "name": "organizations/{org_id}/apiKeys/{key_id}",
  "privateKey": "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
}
```

**How to obtain:**
1. Go to https://cloud.coinbase.com/access/api
2. Create a new API key with trading permissions
3. Download the JSON file and save as `cdp_api_key.json`

---

### 7. CoinGecko API (Fallback)

**Purpose:** Fallback price data when Coinbase doesn't have a coin

**Authentication:** 
- Free tier: No API key required (rate limited to 10-50 calls/minute)
- Pro tier: Set `COINGECKO_API_KEY` environment variable

**Library:** `requests` (direct HTTP calls)

---

### 8. Google Trends API

**Purpose:** Fetch trend data for coins to inform trading decisions

**Authentication:** None required

**Library:** `pytrends`

---

## Credential Files

### `cdp_api_key.json` (Coinbase)

Location: Project root (or path specified by `COINBASE_CREDENTIALS_FILE`)

**Format:**
```json
{
  "name": "organizations/{org_id}/apiKeys/{key_id}",
  "privateKey": "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
}
```

**Security:** This file is gitignored and should never be committed to version control.

---

## Directory Structure

```
tradingbot/
├── crypto_trading_bot.py      # Main trading bot
├── refresh_coin_cache.py     # LunarCrush cache refresh tool
├── tradeanalyzer.py          # Recommendation analyzer
├── historyutil.py            # History recording utility
├── lunarcrushutil.py         # LunarCrush cache utilities
├── polymarketutil.py         # Polymarket filtering utilities
├── coingeckoutil.py          # CoinGecko fallback pricing
├── coinbaseutil2.py          # Coinbase trading client
├── claudeutil.py             # Claude LLM client
├── openaiutil.py             # OpenAI LLM client
├── grokutil.py               # Grok LLM client
├── perplexityutil.py         # Perplexity LLM client
├── cdp_api_key.json          # Coinbase credentials (gitignored)
├── coin_cache.json           # LunarCrush coin data cache (gitignored)
├── coin_cache.backup.json    # Backup of previous cache (gitignored)
└── history/
    ├── recommendations.json  # Accumulated recommendation history
    ├── analysis_live_*.csv   # analyzer results, live-mode records
    ├── analysis_whatif_*.csv # analyzer results, what-if records
    └── test_*.json/csv       # Regression test data
```

---

## Ledger recovery

The execution ledger (`history/executions.json`) is the money record: it backs
the cross-run daily spend cap. Two kinds of sibling files appear next to it at
runtime (both per-user local data, gitignored, never committed):

- **`executions.json.bak-<YYYY-MM-DD>`** — an automatic run-start snapshot,
  written once per UTC day by the bot. This is the auto-recovery source.
- **`executions.json.corrupt-<ts>`** — a quarantined corrupt ledger. When the
  ledger file exists but cannot be parsed, the bot *renames* it aside (nothing
  is ever deleted) so it can be inspected/repaired.

**Automatic behavior on a corrupt ledger** (tagged `[LEDGER ERROR]` in logs):

- **Live mode:** the corrupt file is quarantined and the ledger is
  auto-restored from the newest `.bak-` snapshot — the snapshot carries the
  real spend data, so the daily cap keeps working and trading continues. If
  **no** snapshot exists, the buy is **refused** (fail-closed: an empty ledger
  would silently reset the daily cap to $0) and the log prints the exact
  recovery command.
- **What-if mode:** quarantine-and-continue with a fresh ledger (no money is
  gated; the learning-loop stream keeps flowing).
- **`scripts/reconcile_positions.py`** refuses to run (non-zero exit) against
  a corrupt ledger and prints the same guidance.

**Manual recovery** (when there was no snapshot, or to prefer the quarantined
data): repair the JSON in the quarantined file, then copy it back:

```bash
cp 'history/executions.json.corrupt-<ts>' 'history/executions.json'
# or restore a snapshot instead:
cp 'history/executions.json.bak-<date>' 'history/executions.json'
```

A hand-repaired file must have the exact shape `{"executions": [...]}` —
anything else (an empty `{}`, a bare list) is treated as corrupt again and
re-quarantined. Two known bounds of the design, on record:

- If the newest `.bak-` snapshot is itself corrupt, every run quarantines it,
  refuses the buy, and prints guidance — fail-closed but repetitive until you
  replace or delete-by-renaming the bad snapshot manually.
- The snapshot is taken at *run start*, so an auto-restore loses any rows
  written later the same day — the daily cap can be **under**-counted by up to
  one day's post-snapshot spend after a recovery. Accepted at $5/$15 cap
  scale; revisit if caps grow.

The corrupt-history case for `recommendations.json` is softer: it is
quarantined the same way (`recommendations.json.corrupt-<ts>`, tagged
`[HISTORY ERROR]`) but the run continues — recommendations don't gate money.

---

## Quick Start Examples

### Run in What-If Mode (safe testing, no real trades)
```bash
python crypto_trading_bot.py --trading-mode=whatif
```

### Run with Gemini only
```bash
python crypto_trading_bot.py --llm-mode=gemini
```

### Run with Claude + Gemini comparison
```bash
export CLAUDE_API_KEY=sk-ant-...
python crypto_trading_bot.py --llm-mode=compare --compare-llms=gemini,claude
```

### Run with all 5 LLMs in integration mode
```bash
export CLAUDE_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export XAI_API_KEY=xai-...
export PERPLEXITY_API_KEY=pplx-...
python crypto_trading_bot.py --llm-mode=integrate --compare-llms=gemini,claude,openai,grok,perplexity
```

### Analyze specific coins instead of discovery
```bash
python crypto_trading_bot.py --coins=BTC,ETH,DOGE
```

### Combine options: What-If mode with specific coins
```bash
python crypto_trading_bot.py --trading-mode=whatif --coins=PEPE,BONK --llm-mode=compare
```

### Using environment variables (legacy style)
```bash
export TRADING_MODE=whatif
export LLM_MODE=compare
export ANALYZE_COINS=BTC,ETH
python crypto_trading_bot.py
```

### Run the analyzer
```bash
python tradeanalyzer.py
```

> **The `ANALYZE_COINS` trap (filters vs explicit coins).** Filters
> (`--chains`, `--categories`, `--polymarket-filter`) and discovery
> (`--discovery`) only take effect in **discovery mode** — i.e. when NO explicit
> coins are set. Explicit coins force *coin choice mode*, which does not apply
> any filter or discovery flag. Because `ANALYZE_COINS` in `.env` counts as
> explicit coins, a persistent `ANALYZE_COINS=BTC,ETH,...` would otherwise make
> filters silently do nothing. The bot now refuses to run silently in this case:
> - `ANALYZE_COINS` set in `.env` **+** filter/discovery flags on the CLI →
>   the bot prints `[CONFIG] ... ignoring ANALYZE_COINS env (...)` and proceeds
>   in discovery/filter mode (CLI intent wins).
> - `--coins=...` **and** a filter/discovery flag **both on the CLI** →
>   the bot exits with `[CONFIG ERROR]` (ambiguous — one side would be
>   discarded). Drop the filter flags, or pass `--coins=` (empty) to filter.
>
> To run a filtered/discovery pass while `ANALYZE_COINS` is set in `.env`, just
> pass the filter flags on the CLI (they override the env coins), or unset
> `ANALYZE_COINS`. The startup banner now prints filter lines only when they are
> actually in effect.

### Filter by category (e.g., meme coins only)
```bash
# First, ensure cache exists (one-time setup)
LUNARCRUSH_API_KEY=your_key python refresh_coin_cache.py

# Then run with category filter (works from a clean env, or overrides
# ANALYZE_COINS if it is set in .env)
python crypto_trading_bot.py --categories=meme-coins
```

### Filter by blockchain (e.g., Solana coins only)
```bash
python crypto_trading_bot.py --chains=solana
```

### Combine category and chain filters
```bash
python crypto_trading_bot.py --categories=meme-coins --chains=solana
```

### Filter to coins with active Polymarket prediction markets
```bash
python crypto_trading_bot.py --polymarket-filter=true
```

### Combine all filters (meme coins on Solana with Polymarket markets)
```bash
python crypto_trading_bot.py --categories=meme-coins --chains=solana --polymarket-filter=true
```

---

## Discovery Mode Options

The trading bot supports multiple discovery methods for finding coins to analyze.

### LLM-only discovery (default)
```bash
python crypto_trading_bot.py --discovery=llm
```
Asks the primary LLM to recommend 3 coins to analyze.

### Santiment discovery (volume-based)
```bash
python crypto_trading_bot.py --discovery=santiment
```
Finds coins with highest 24h volume change from Santiment API. Auto-refreshes cache at startup.

### Hybrid discovery (both methods)
```bash
python crypto_trading_bot.py --discovery=llm,santiment
```
Combines LLM recommendations (3 coins) with Santiment volume movers (3 coins). Deduplicates and caps at 6 coins total.

### Santiment discovery with filters
```bash
python crypto_trading_bot.py --discovery=santiment --categories=memecoin --chains=solana
```
Discovers top volume movers within filtered category/chain. Auto-refreshes cache.

---

## Regression Testing

The analyzer's behavior is pinned by `tests/test_analyzer.py` (synthetic
fixtures in `tmp_path`, no network, no real history) — run
`./venv/bin/python -m pytest tests/test_analyzer.py -q`. That is the canonical
regression check.

The legacy demo files `history/test_recommendation_data.json` and
`history/test_expected_output.csv` predate the T10 overhaul and predate the
`trading_mode` field (T2). They are kept for reference only:

- Their records carry **no `trading_mode`**, so the current analyzer classifies
  them all as `excluded_unknown` (excluded from scoring, reported in a count
  line) — the fixture now exercises the unknown-exclusion path, not scoring.
- `test_expected_output.csv` describes the **old** CSV columns. The overhauled
  analyzer writes per-mode files (`analysis_live_YYYYMMDD.csv`,
  `analysis_whatif_YYYYMMDD.csv`) with benchmark-relative columns
  (`coin_return_pct`, `benchmark_return_pct`, `fee_floor_pct`, `fee_source`,
  `excess_return_pct`, `outcome`, `category`, ...) — it does not reproduce the
  old file.

To exercise real benchmark-relative scoring by hand, run the analyzer against a
history whose records carry `trading_mode` `live`/`whatif` (e.g. one produced by
a what-if cadence — see `docs/RUNBOOK_whatif_cadence.md`):

```bash
HISTORY_DIR=/tmp/tradbot_scratch python tradeanalyzer.py --help   # see all flags
HISTORY_DIR=/tmp/tradbot_scratch python tradeanalyzer.py          # full scoring
HISTORY_DIR=/tmp/tradbot_scratch python tradeanalyzer.py --offline  # structural, no network
```

---

## DEX Trading (Solana via Jupiter)

The trading bot supports decentralized exchange (DEX) trading on Solana using the Jupiter aggregator and Phantom wallet via WalletConnect.

### Overview

DEX mode allows trading Solana-native tokens (BONK, WIF, POPCAT, etc.) that aren't available on Coinbase. It uses:
- **Jupiter**: DEX aggregator for optimal swap routing and price quotes
- **WalletConnect**: Industry-standard protocol for connecting to Phantom wallet
- **Phantom**: Popular Solana wallet for transaction signing

### Setup Requirements

#### 1. Install DEX Dependencies

```bash
pip install -r requirements_dex.txt
```

This installs:
- `httpx` - HTTP client for Jupiter API
- `pywalletconnect` - WalletConnect v2 client

#### 2. Get Jupiter API Key

1. Go to https://developers.jup.ag/portal
2. Sign up for free tier (or paid for higher rate limits)
3. Create an API key
4. Set environment variable:

```bash
export JUPITER_API_KEY="your-jupiter-api-key"
```

#### 3. Export Private Key from Phantom (for live trades)

For live trading, you'll be prompted to enter your private key at startup:

1. Open Phantom wallet (browser extension or mobile app)
2. Go to Settings → Security & Privacy → Export Private Key
3. Enter your password to confirm
4. Copy the private key (base58 format)

**Security:** The key is entered via hidden prompt (`getpass`) and stored in memory only - never written to disk, environment, or shell history.

**Note:** Private key is only needed for live trades. Price fetching and what-if mode work with just the Jupiter API key.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JUPITER_API_KEY` | Yes | Jupiter API key for quotes and prices |
| `SOLANA_RPC_URL` | No | Custom Solana RPC endpoint (default: mainnet-beta) |
| `DEX_MODE` | No | Set to `true` to enable DEX mode (alternative to `--dex` flag) |
| `DEX_SLIPPAGE` | No | Slippage tolerance as percentage (default: `1.0` = 1%) |
| `DEX_CACHE_DIR` | No | Directory for token cache (default: `./dex_cache/`) |

### Command-Line Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--dex` | flag | `false` | Enable DEX mode (Solana via Jupiter + Phantom) |
| `--slippage` | float | `1.0` | DEX slippage tolerance as percentage |

### Chain Restriction

DEX mode only supports **Solana** chain:

| Mode | Behavior |
|------|----------|
| `--dex --trading-mode=live` | Auto-sets `--chains=solana`. Errors if non-Solana chains specified. |
| `--dex --trading-mode=whatif` | Allows any chain (for research). Warns about non-tradeable chains. |

### Usage Examples

#### Test DEX price fetching (no wallet needed)

```bash
export JUPITER_API_KEY="your-key"
python -c "from dex.jupiterutil import JupiterClient; j = JupiterClient(); print(j.get_price('BONK'))"
```

#### Run in DEX what-if mode (no wallet needed)

```bash
export JUPITER_API_KEY="your-key"
python crypto_trading_bot.py --dex --trading-mode=whatif --coins=BONK,WIF
```

#### Run in DEX live mode (requires private key)

```bash
export JUPITER_API_KEY="your-key"
python crypto_trading_bot.py --dex --trading-mode=live --coins=BONK
```

When running in live mode:
1. You'll be prompted to enter your Solana private key (hidden input)
2. Export key from Phantom: Settings → Security & Privacy → Export Private Key
3. Paste the key when prompted (input is hidden for security)
4. Trades execute automatically after LLM recommendations

#### Adjust slippage tolerance

```bash
python crypto_trading_bot.py --dex --slippage=2.0 --coins=BONK
```

### Supported Tokens

The following well-known Solana tokens are pre-configured:

| Symbol | Name | Decimals |
|--------|------|----------|
| SOL | Solana | 9 |
| USDC | USD Coin | 6 |
| USDT | Tether | 6 |
| BONK | Bonk | 5 |
| WIF | dogwifhat | 6 |
| POPCAT | Popcat | 9 |
| PEPE | Pepe | 9 |
| FLOKI | Floki | 9 |

Other tokens are resolved via Jupiter's token search API.

### Trade Analyzer with DEX

The trade analyzer (`tradeanalyzer.py`) automatically:
- Detects DEX recommendations by the `exchange` field
- Fetches current prices from Jupiter for Solana tokens
- Reports per-exchange statistics (CEX vs DEX accuracy)

```bash
export JUPITER_API_KEY="your-key"
python tradeanalyzer.py
```

Example output includes:
```
--- PER-EXCHANGE STATISTICS ---
cex: 45/60 correct (75.0%), 5 unknown, 10 hold
solana-dex: 8/12 correct (66.7%), 2 unknown, 3 hold
```

### Module Structure

```
dex/
├── __init__.py        # Module exports (SolanaDEXTrader)
├── token_cache.py     # Jupiter token list caching
├── jupiterutil.py     # Jupiter API client (quotes, prices, swaps)
├── walletconnect.py   # WalletConnect session management
└── trader.py          # SolanaDEXTrader class
```

### API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `https://api.jup.ag/tokens/v2/search` | Token search and metadata |
| `https://api.jup.ag/tokens/v2/tag?query=verified` | Verified token list |
| `https://api.jup.ag/swap/v1/quote` | Get swap quotes |
| `https://api.jup.ag/swap/v2/build` | Build swap transactions |

### Troubleshooting

**"Jupiter API key required"**
- Set `JUPITER_API_KEY` environment variable

**"WalletConnect project ID required"**
- Set `WALLETCONNECT_PROJECT_ID` environment variable (only needed for live trades)

**404 errors from Jupiter**
- Verify API key is valid at https://developers.jup.ag/portal
- Check you're using the correct endpoint versions (v1 for quotes, v2 for tokens)

**Token not found**
- Ensure the token symbol is correct (case-insensitive)
- Verify the token exists on Jupiter: `curl -s "https://api.jup.ag/tokens/v2/search?query=SYMBOL" --header "x-api-key: YOUR_KEY"`

**Wallet connection timeout**
- Ensure Phantom app is open and on the same network
- Try regenerating the WalletConnect URI

### Security Considerations

- **Never share your Jupiter API key** - it's tied to your rate limits
- **Never share your WalletConnect project ID** - it identifies your app
- **Review all transactions in Phantom** before signing
- **Start with what-if mode** to verify recommendations before live trading
- **Use small amounts initially** when testing live DEX trades

---

## Candidate Coins Pipeline

The system supports an integrated pipeline for discovering, validating, and analyzing coins across three tools:

```
┌──────────────────────────┐
│  1. CRYPTO TRADING BOT   │
│  crypto_trading_bot.py   │
│                          │
│  • LLM discovers coins   │
│  • Analyzes with multi-  │
│    LLM consensus         │
│  • Makes BUY/SELL/HOLD   │
│    recommendations       │
│                          │
│  --export-candidates     │
└───────────┬──────────────┘
            │ Writes recommended
            │ coins to CSV
            ▼
┌──────────────────────────┐
│  candidate_coins.csv     │
│                          │
│  symbol,blockchain,      │
│  added_at,updated_at,    │
│  source                  │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  2. CORRELATION TRACKER  │
│  correlation_tracker.py  │
│                          │
│  • Collects price data   │
│    every 30 seconds      │
│  • Builds correlation    │
│    history               │
│  • Discovers leading     │
│    indicator pairs       │
│                          │
│  --use-candidate-coins   │
└───────────┬──────────────┘
            │ Produces correlation
            │ data files
            ▼
┌──────────────────────────┐
│  correlation_data/       │
│  ├── BTC_prices.csv      │
│  ├── SOL_prices.csv      │
│  ├── BONK_prices.csv     │
│  └── ...                 │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  3. LEADING INDICATOR    │
│     TESTER               │
│  leading_indicator_      │
│  tester.py               │
│                          │
│  • Paper trades using    │
│    correlation signals   │
│  • Tests profitability   │
│  • Validates strategies  │
│                          │
│  --use-candidate-coins   │
└──────────────────────────┘
```

### Important: Leading Indicators Must Be Added Manually

The trading bot discovers **follower coins** (coins to potentially trade based on LLM analysis), but **leading indicators** (like BTC or ETH that predict follower movements) must be manually added to `candidate_coins.csv`.

```bash
# Add common leading indicators manually
python -c "from candidate_util import upsert_candidate_coin; upsert_candidate_coin('BTC', 'Bitcoin', 'manual_leader')"
python -c "from candidate_util import upsert_candidate_coin; upsert_candidate_coin('ETH', 'Ethereum', 'manual_leader')"
python -c "from candidate_util import upsert_candidate_coin; upsert_candidate_coin('SOL', 'Solana', 'manual_leader')"
```

The correlation tracker will then analyze relationships between these leaders and the LLM-discovered followers.

### Step 1: Discover and Export Candidate Coins

Run the trading bot with `--export-candidates` to write LLM-recommended coins to `candidate_coins.csv`:

```bash
# Discover coins and export all recommendations
python crypto_trading_bot.py --trading-mode=whatif --export-candidates

# Export only BUY recommendations
python crypto_trading_bot.py --trading-mode=whatif --export-candidates --export-recommendations=BUY

# Specify blockchain for exported coins
python crypto_trading_bot.py --trading-mode=whatif --export-candidates --candidate-blockchain=Solana

# With specific coins (useful for seeding the candidate list)
python crypto_trading_bot.py --trading-mode=whatif --coins=BONK,WIF,PEPE --export-candidates
```

**Configuration:**

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--export-candidates` | `EXPORT_CANDIDATES` | `false` | Enable candidate export |
| `--candidate-dir` | `CANDIDATE_DIR` | `./correlation_data` | Directory for CSV |
| `--candidate-blockchain` | `CANDIDATE_BLOCKCHAIN` | `Solana` | Blockchain for coins |
| `--export-recommendations` | `EXPORT_RECOMMENDATIONS` | `ALL` | Filter: `ALL`, `BUY`, or `BUY,HOLD` |

### Step 2: Collect Correlation Data

> **Install the tracker's dependencies first:**
> `pip install -r requirements_correlation_tracker.txt`. They are not part of
> the main `requirements.txt`. In particular, without `statsmodels` the
> Granger causality test is skipped (analysis still runs, with a caveat in
> the report).

Run the correlation tracker to collect price data for candidate coins:

```bash
# Collect data for 4 hours
python correlation_tracker.py --collect --use-candidate-coins --duration 4hr

# Collect with custom interval (5 minutes)
python correlation_tracker.py --collect --use-candidate-coins --duration 4hr --interval 5min

# Run indefinitely (Ctrl+C to stop)
python correlation_tracker.py --collect --use-candidate-coins
```

**What it does:**
- Reads coin symbols from `candidate_coins.csv`
- Fetches prices from CoinGecko every `--interval` seconds
- Writes timestamped price data to `correlation_data/<SYMBOL>_prices.csv`

### Step 3: Analyze Correlations

Discover leading indicator relationships:

```bash
# Analyze all candidate coins for correlations
python correlation_tracker.py --analyze --use-candidate-coins

# Discovery mode - find best leader/follower pairs
python correlation_tracker.py --discover --use-candidate-coins --min-confidence 0.6

# Analyze specific pair
python correlation_tracker.py --analyze --leader BTC --follower BONK
```

### Step 4: Test Profitability

Run paper trading simulations using discovered correlations:

```bash
# Auto-select best pairs from candidate coins
python leading_indicator_tester.py --auto-select --use-candidate-coins --use-fib

# With specific confidence thresholds
python leading_indicator_tester.py --auto-select --use-candidate-coins --use-fib \
    --min-confidence 0.5 --min-correlation 0.3

# Skip data collection, analyze existing data
python leading_indicator_tester.py --auto-select --use-candidate-coins --use-fib --skip-collection
```

### Full Pipeline Example

```bash
# Day 1: Seed candidate list from LLM discovery
python crypto_trading_bot.py --trading-mode=whatif --export-candidates --export-recommendations=BUY

# Day 1-3: Collect price data (run for several days)
python correlation_tracker.py --collect --use-candidate-coins --duration 72hr

# Day 3: Analyze correlations
python correlation_tracker.py --discover --use-candidate-coins --min-confidence 0.5

# Day 3: Test trading strategy
python leading_indicator_tester.py --auto-select --use-candidate-coins --use-fib

# Ongoing: Add new coins as LLM discovers them
python crypto_trading_bot.py --trading-mode=whatif --export-candidates
```

### CSV File Format

The `candidate_coins.csv` file uses upsert semantics (one record per coin):

```csv
symbol,blockchain,added_at,updated_at,source
BONK,Solana,2026-06-01T14:30:00Z,,llm_recommendation_gemini
WIF,Solana,2026-06-01T14:32:00Z,2026-06-02T10:15:00Z,llm_recommendation_compare
PEPE,Solana,2026-06-01T14:35:00Z,,llm_recommendation_claude
```

- **symbol**: Coin ticker (uppercase)
- **blockchain**: Chain name (metadata, not used for filtering yet)
- **added_at**: First recommendation timestamp
- **updated_at**: Most recent re-recommendation (empty if never updated)
- **source**: Origin of the recommendation (e.g., `llm_recommendation_gemini`)

### Manual Candidate Management

You can also manually edit `candidate_coins.csv`:

```bash
# Add a coin manually
echo "MYTOKEN,Solana,2026-06-01T12:00:00Z,,manual" >> correlation_data/candidate_coins.csv

# View current candidates
cat correlation_data/candidate_coins.csv

# Or use Python
python -c "from candidate_util import upsert_candidate_coin; upsert_candidate_coin('MYTOKEN', 'Solana', 'manual')"
```
