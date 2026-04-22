# Operations Manual

This document describes the programs, environment variables, APIs, and credential configuration for the trading bot system.

---

## Programs

### 1. Trading Bot (`geminigroundlin15.py`)

The main trading bot that analyzes cryptocurrency coins and makes buy/sell/hold recommendations using one or more LLMs.

**Usage:**
```bash
python geminigroundlin15.py [OPTIONS]
```

**Command-Line Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--trading-mode` | `live`, `whatif` | `live` | Trading mode: `live` executes real trades, `whatif` simulates only |
| `--llm-mode` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `compare`, `integrate` | `compare` | LLM mode for recommendations |
| `--primary-llm` | `gemini`, `claude`, `openai`, `grok`, `perplexity` | `gemini` | Primary LLM for discovery |
| `--compare-llms` | comma-separated | `gemini,claude` | LLMs for compare/integrate mode |
| `--coins` | comma-separated | *(empty)* | Specific coins to analyze (max 6), or empty for discovery mode |
| `--discovery` | comma-separated | `llm` | Discovery method(s): `llm`, `santiment`, or both (e.g., `llm,santiment`) |
| `--chains` | comma-separated | *(empty)* | Filter coins by blockchain (e.g., `solana,base`). Requires cache file |
| `--categories` | comma-separated | *(empty)* | Filter coins by category (e.g., `meme-coins,defi`). Requires cache file |
| `--polymarket-filter` | `true`, `false` | `false` | Only analyze coins with active Polymarket prediction markets |
| `--require-consensus` | `true`, `false` | `true` | Require LLM consensus for action |
| `--tiebreaker` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `none` | `gemini` | Tiebreaker LLM when no consensus |
| `--log-rounds` | `true`, `false` | `true` | Log integration round details |

**Configuration Precedence:**
CLI arguments take precedence over environment variables. If neither is set, the default value is used.
The startup banner shows the source of each configuration value (e.g., `[--trading-mode]`, `[TRADING_MODE env]`, or `[default]`).

**What it does:**
1. Discovers coins to analyze (via LLM or specified list)
2. Fetches Google Trends data for each coin
3. Queries LLM(s) for trading recommendations
4. Optionally compares or integrates recommendations from multiple LLMs
5. Records recommendations to history (for later analysis)
6. Executes trades on Coinbase (in `live` mode) or simulates them (in `whatif` mode)

**Output:**
- Console output with LLM responses and recommendations
- Trade executions on Coinbase (live mode only)
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

Standalone program that analyzes historical recommendation accuracy by comparing past recommendations to current prices.

**Usage:**
```bash
python tradeanalyzer.py
```

**What it does:**
1. Loads recommendations from `./history/recommendations.json`
2. Finds recommendations in two time windows:
   - **24-hour window:** Recommendations made 24-48 hours ago
   - **7-day window:** Recommendations made 7-8 days ago
3. Fetches current prices (Coinbase primary, CoinGecko fallback)
4. Calculates accuracy (BUY correct if price went up, SELL correct if price went down)
5. Generates per-LLM and per-mode statistics

**Output:**
- Console report with accuracy statistics
- CSV files: `./history/analysis_24h_YYYYMMDD.csv`, `./history/analysis_7d_YYYYMMDD.csv`

---

## Environment Variables

> **Note:** All configuration environment variables can also be set via command-line arguments.
> CLI arguments take precedence over environment variables. See the Command-Line Options table above.

### Trading Bot Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `live` | Trading mode: `live` executes real trades, `whatif` simulates only |
| `LLM_MODE` | `compare` | Mode of operation: `gemini`, `claude`, `openai`, `grok`, `perplexity`, `compare`, or `integrate` |
| `PRIMARY_LLM` | `gemini` | LLM used for coin discovery and first analysis |
| `COMPARE_LLMS` | `gemini,claude` | Comma-separated list of LLMs to use in compare/integrate modes |
| `REQUIRE_CONSENSUS` | `true` | If `true`, only act when all LLMs agree (compare/integrate modes) |
| `INTEGRATION_TIEBREAKER` | `gemini` | LLM to use as tiebreaker when no consensus: `gemini`, `claude`, `openai`, `grok`, `perplexity`, or `none` |
| `LOG_INTEGRATION_ROUNDS` | `true` | If `true`, log detailed Round 1/2 responses in integrate mode |
| `ANALYZE_COINS` | *(empty)* | Comma-separated list of coins to analyze (max 6). If empty, uses discovery mode |
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

**Model:** `gemini-2.5-pro`

**Features used:** Google Search grounding for real-time market data

---

### 2. Anthropic Claude API

**Purpose:** Secondary LLM for comparison/integration modes

**Authentication:** Environment variable `CLAUDE_API_KEY`

**Library:** `anthropic`

**Model:** `claude-sonnet-4-20250514`

---

### 3. OpenAI API

**Purpose:** Secondary LLM for comparison/integration modes

**Authentication:** Environment variable `OPENAI_API_KEY`

**Library:** `openai`

**Model:** `gpt-4o`

---

### 4. xAI Grok API

**Purpose:** Secondary LLM for comparison/integration modes with web search

**Authentication:** Environment variable `XAI_API_KEY`

**Library:** `openai` (OpenAI-compatible API)

**Base URL:** `https://api.x.ai/v1`

**Model:** `grok-3`

**Features used:** Web search tool for real-time data

---

### 5. Perplexity API

**Purpose:** Secondary LLM for comparison/integration modes with built-in search

**Authentication:** Environment variable `PERPLEXITY_API_KEY`

**Library:** `openai` (OpenAI-compatible API)

**Base URL:** `https://api.perplexity.ai`

**Model:** `sonar-pro`

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
├── geminigroundlin15.py      # Main trading bot
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
    ├── analysis_24h_*.csv    # 24-hour analysis results
    ├── analysis_7d_*.csv     # 7-day analysis results
    └── test_*.json/csv       # Regression test data
```

---

## Quick Start Examples

### Run in What-If Mode (safe testing, no real trades)
```bash
python geminigroundlin15.py --trading-mode=whatif
```

### Run with Gemini only
```bash
python geminigroundlin15.py --llm-mode=gemini
```

### Run with Claude + Gemini comparison
```bash
export CLAUDE_API_KEY=sk-ant-...
python geminigroundlin15.py --llm-mode=compare --compare-llms=gemini,claude
```

### Run with all 5 LLMs in integration mode
```bash
export CLAUDE_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export XAI_API_KEY=xai-...
export PERPLEXITY_API_KEY=pplx-...
python geminigroundlin15.py --llm-mode=integrate --compare-llms=gemini,claude,openai,grok,perplexity
```

### Analyze specific coins instead of discovery
```bash
python geminigroundlin15.py --coins=BTC,ETH,DOGE
```

### Combine options: What-If mode with specific coins
```bash
python geminigroundlin15.py --trading-mode=whatif --coins=PEPE,BONK --llm-mode=compare
```

### Using environment variables (legacy style)
```bash
export TRADING_MODE=whatif
export LLM_MODE=compare
export ANALYZE_COINS=BTC,ETH
python geminigroundlin15.py
```

### Run the analyzer
```bash
python tradeanalyzer.py
```

### Filter by category (e.g., meme coins only)
```bash
# First, ensure cache exists (one-time setup)
LUNARCRUSH_API_KEY=your_key python refresh_coin_cache.py

# Then run with category filter
python geminigroundlin15.py --categories=meme-coins
```

### Filter by blockchain (e.g., Solana coins only)
```bash
python geminigroundlin15.py --chains=solana
```

### Combine category and chain filters
```bash
python geminigroundlin15.py --categories=meme-coins --chains=solana
```

### Filter to coins with active Polymarket prediction markets
```bash
python geminigroundlin15.py --polymarket-filter=true
```

### Combine all filters (meme coins on Solana with Polymarket markets)
```bash
python geminigroundlin15.py --categories=meme-coins --chains=solana --polymarket-filter=true
```

---

## Discovery Mode Options

The trading bot supports multiple discovery methods for finding coins to analyze.

### LLM-only discovery (default)
```bash
python geminigroundlin15.py --discovery=llm
```
Asks the primary LLM to recommend 3 coins to analyze.

### Santiment discovery (volume-based)
```bash
python geminigroundlin15.py --discovery=santiment
```
Finds coins with highest 24h volume change from Santiment API. Auto-refreshes cache at startup.

### Hybrid discovery (both methods)
```bash
python geminigroundlin15.py --discovery=llm,santiment
```
Combines LLM recommendations (3 coins) with Santiment volume movers (3 coins). Deduplicates and caps at 6 coins total.

### Santiment discovery with filters
```bash
python geminigroundlin15.py --discovery=santiment --categories=memecoin --chains=solana
```
Discovers top volume movers within filtered category/chain. Auto-refreshes cache.

---

## Regression Testing

Test data files are provided for regression testing the analyzer:

```bash
# Copy test data to live location
cp history/test_recommendation_data.json history/recommendations.json

# Run analyzer
python tradeanalyzer.py

# Compare output structure against test_expected_output.csv
# Note: Actual prices will vary, so outcome values may differ
```
