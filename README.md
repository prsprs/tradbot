# Trading Bot Repository Guide

A comprehensive cryptocurrency trading system combining AI-powered analysis, multi-exchange support, correlation-based strategies, and arbitrage detection.

---

## Overview

This repository contains multiple interconnected projects for cryptocurrency trading and analysis:

- **AI-Powered Trading** - Multi-LLM consensus-based trading recommendations
- **Correlation Analysis** - Discover leading indicator relationships between tokens
- **Cross-Exchange Arbitrage** - Exploit price discrepancies across exchanges and chains
- **Liquidity Pool Arbitrage** - Trade LP token premium/discount spreads
- **DEX Integration** - Native Solana trading via Jupiter aggregator

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set API keys
export GOOGLE_API_KEY=...     # Gemini
export CLAUDE_API_KEY=...     # Claude
export COINBASE_API_KEY=...   # Coinbase trading

# Run main trading bot (defaults to what-if / simulation — no real trades)
python crypto_trading_bot.py --llm-mode compare
```

Alternatively, instead of `export`, copy `.env.example` to `.env` and fill in
your keys — the bot loads it automatically at startup. Shell `export`s still
work and take precedence over `.env` values.

### Trading mode & the live-trading double lock

The bot now defaults to **what-if (simulation)** mode. Live trading is
double-locked and requires **both**:

1. the `--live` command-line flag, **and**
2. the environment variable `LIVE_TRADING_CONFIRMED=1`.

```bash
# Live trading (executes REAL orders): BOTH locks required
LIVE_TRADING_CONFIRMED=1 python crypto_trading_bot.py --live --llm-mode compare
```

Any live request that is missing either lock is automatically downgraded to
what-if, and the bot prints a loud notice explaining what was missing. Trade
sizing is also configurable and capped:

- `--notional-usd` (env `TRADE_NOTIONAL_USD`, default `5.00`, hard ceiling
  `100.00`) — USD per buy order (CEX and DEX).
- `--run-spend-cap-usd` (env `RUN_SPEND_CAP_USD`, default `10.00`) — maximum
  cumulative intended spend across all buys in one run; buys that would exceed
  it are refused (what-if spend counts against the cap too).
- `--daily-spend-cap-usd` (env `DAILY_SPEND_CAP_USD`, default `15.00`) —
  maximum cumulative intended **live** spend across all runs in a single UTC
  day, summed from the execution ledger; a live buy that would exceed it is
  refused with `[DAILY CAP]`. What-if spend does not count against this cap.

> **Migration note (breaking change):** `--trading-mode=live` (or
> `TRADING_MODE=live`) **alone no longer enables live trading**. The
> `--trading-mode` flag value is still accepted for compatibility, but live
> now requires the `--live` flag **and** `LIVE_TRADING_CONFIRMED=1`. Scripts
> that previously relied on `--trading-mode=live` will run in what-if until
> updated. The default with no flags is now what-if (previously live).

### What each recommendation is based on

Every coin analysis is grounded in a compact, plainly-labeled data block
built fresh each run and prepended to every panelist's prompt (see
`marketdata.py`):

- **MARKET DATA** (Coinbase OHLCV, primary) — last price, 24h/72h/7d change,
  range, volume trend, and volatility, verifiable by every panelist from the
  same candles.
- **FIBONACCI** — retracement levels computed from that same OHLCV window.
- **CMC** (CoinMarketCap) — rank, market-cap dominance, supply, and
  multi-window % change. Resolved by CoinMarketCap numeric ID rather than
  ticker symbol where possible, so a colliding ticker can't silently return
  a different asset's numbers.
- **SOCIAL** (LunarCrush) — galaxy score, alt rank, an interaction-weighted
  sentiment aggregate, and social volume.
- **GOOGLE TRENDS** — a secondary signal only (search interest, not price);
  it's noisy on low-volume tickers, so it never carries the analysis alone.

Any of the above that can't be fetched is disclosed explicitly (e.g. `CMC
DATA UNAVAILABLE: <reason>`) — never silently omitted, and never invented.

### How the panel decides

Each LLM votes with a schema-enforced JSON object (`symbol`, `action`,
`confidence`, `abstain`, `reasons`) instead of free-text scraped for
keywords, so a model's refusal or hedge can't be misread as a BUY. In
`compare`/`integrate` mode with `--require-consensus=true` (the default), a
trade only happens when every panelist agrees; any parse failure, refusal,
API error, or symbol mismatch counts as an abstain, and the panel **fails
closed** — it never shrinks the quorum or falls back to a single model's
opinion to force a decision.

### Scoring past recommendations

`tradeanalyzer.py` grades recorded whatif/live recommendations against
BTC-relative benchmark returns (never a backtester or simulated P&L — it
only compares a recorded decision to observed prices). See
[docs/RUNBOOK_whatif_cadence.md](docs/RUNBOOK_whatif_cadence.md) for running
the bot on a schedule to accumulate data for it to grade, and
[docs/RUNBOOK_live_acceptance.md](docs/RUNBOOK_live_acceptance.md) for the
owner-executed live acceptance test.

See [OPERATIONS_MANUAL.md](OPERATIONS_MANUAL.md) for detailed configuration.

---

## Projects

| Project | Description | Design Doc | Operations Manual | Status | Main Module | Comments |
|---------|-------------|------------|-------------------|--------|-------------|----------|
| **Crypto Trading Bot** | AI-powered trading using multi-LLM consensus | [CRYPTO_TRADING_BOT.md](CRYPTO_TRADING_BOT.md) | [OPERATIONS_MANUAL.md](OPERATIONS_MANUAL.md) | ✅ Implemented | `crypto_trading_bot.py` | Core system - Gemini, Claude, OpenAI, Grok, Perplexity |
| **LLM Compare** | Multi-LLM comparison and integration framework | [LLMCompareFeature.md](LLMCompareFeature.md) | [LLM_COMPARE_OPERATIONS_MANUAL.md](LLM_COMPARE_OPERATIONS_MANUAL.md) | ✅ Implemented | `llm_compare.py` | General-purpose LLM comparison tool |
| **Correlation Tracker** | Intraday price collection and leading indicator discovery | [CORRELATION_HISTORY_TRACKER.md](CORRELATION_HISTORY_TRACKER.md) | [CORRELATION_HISTORY_OPERATIONS_MANUAL.md](CORRELATION_HISTORY_OPERATIONS_MANUAL.md) | ✅ Implemented | `correlation_tracker.py` | Collect mode + Analyze mode |
| **Leading Indicator Tester** | Paper trading simulation for correlation pairs | [LEADING_INDICATOR_PERFORMANCE_TESTER.md](LEADING_INDICATOR_PERFORMANCE_TESTER.md) | — | ✅ Implemented | `leading_indicator_tester.py` | Cross-exchange arbitrage investigation |
| **DEX Trading** | Solana DEX trading via Jupiter aggregator | [DEX_TRADING_FEATURE.md](DEX_TRADING_FEATURE.md) | — | ✅ Implemented | `dex/jupiterutil.py` | Wallet connect, token swaps, price API |
| **Liquidity Pool Arbitrage** | JLP premium/discount arbitrage on Jupiter | [LIQUIDITY_POOL_FEATURE.md](LIQUIDITY_POOL_FEATURE.md) | [LIQUIDITY_POOL_OPERATIONS_MANUAL.md](LIQUIDITY_POOL_OPERATIONS_MANUAL.md) | ✅ Implemented | `lp_arbitrage.py` | Also supports HyperLiquid, Drift |
| **Correlated Pair Trading** | Cross-exchange arbitrage for wrapped tokens | [CORRELATED_PAIR_FEATURE.md](CORRELATED_PAIR_FEATURE.md) | — | 📋 Design Only | — | TAO/WTAO, BTC/WBTC strategies |
| **Flash Loan Arbitrage** | Atomic arbitrage using flash loans | [FLASH_LOAN_FEATURE.md](FLASH_LOAN_FEATURE.md) | — | 📋 Design Only | — | Zero-capital atomic trades |
| **Meteora Arbitrage** | DLMM bin arbitrage on Meteora | [METEORA_ARBITRAGE_FEATURE.md](METEORA_ARBITRAGE_FEATURE.md) | — | 📋 Design Only | — | Solana concentrated liquidity |

---

## Feature Enhancements

| Feature | Description | Design Doc | Status | Module | Comments |
|---------|-------------|------------|--------|--------|----------|
| **Coin Categorization** | Filter coins by category (meme, DeFi, AI) | [COIN_CATEGORIZATION_FEATURE.md](COIN_CATEGORIZATION_FEATURE.md) | ✅ Implemented | `lunarcrushutil.py` | Uses LunarCrush API |
| **Coin Choice** | Analyze specific coins directly | [COIN_CHOICE_FEATURE.md](COIN_CHOICE_FEATURE.md) | ✅ Implemented | `crypto_trading_bot.py` | `--coins` flag or `ANALYZE_COINS` env |
| **Compare with Bitcoin** | Evaluate altcoin alpha vs BTC | [COMPARE_WITH_BITCOIN_FEATURE.md](COMPARE_WITH_BITCOIN_FEATURE.md) | 📋 Design Only | — | Risk-adjusted comparison |
| **History Analysis** | Track and analyze recommendation accuracy | [HISTORY_ANALYSIS_FEATURE.md](HISTORY_ANALYSIS_FEATURE.md) | ✅ Implemented | `historyutil.py` | Performance metrics by LLM |
| **LunarCrush Integration** | Social intelligence data for coins | [LUNAR_CRUSH_FEATURE.md](LUNAR_CRUSH_FEATURE.md) | ✅ Implemented | `lunarcrushutil.py` | Categories, blockchains, sentiment |
| **Polymarket Integration** | Prediction market sentiment data | [POLYMARKET_FEATURE.md](POLYMARKET_FEATURE.md) | ✅ Implemented | `polymarketutil.py` | Market-validated coin selection |
| **Stock Trading** | Extend bot to Coinbase stock trading | [STOCK_TRADING_FEATURE.md](STOCK_TRADING_FEATURE.md) | 📋 Design Only | — | US equities via Coinbase |
| **Whale Alert** | Large transaction tracking | [WHALE_ALERT_INTEGRATION_FEATURE.md](WHALE_ALERT_INTEGRATION_FEATURE.md) | 📋 Design Only | — | Exchange inflow/outflow signals |
| **What-If Mode** | Paper trading / simulation mode | [WHAT_IF_MODE_FEATURE.md](WHAT_IF_MODE_FEATURE.md) | ✅ Implemented | `crypto_trading_bot.py` | `--trading-mode whatif` |

---

## Internal Documentation

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | **Start here for AI-assisted development** — hard rules, environment, architecture map, API gotchas (any agent: Devin/Windsurf/Codex/Grok/Claude) |
| [MODELS.md](MODELS.md) | LLM model registry, migration history, per-provider request/response shapes |
| [docs/RUNBOOK_whatif_cadence.md](docs/RUNBOOK_whatif_cadence.md) | Scheduled what-if runs that feed `tradeanalyzer.py`'s benchmark-relative scoring |
| [docs/RUNBOOK_live_acceptance.md](docs/RUNBOOK_live_acceptance.md) | Owner-executed live acceptance test (the one supervised real trade) |
| [INSTRUCTIONS_FOR_IMPLEMENTATION.md](INSTRUCTIONS_FOR_IMPLEMENTATION.md) | Guidelines for implementing features |
| [METHODS_OF_SPECIFYING_RUNTIME_OPTIONS.md](METHODS_OF_SPECIFYING_RUNTIME_OPTIONS.md) | CLI vs env var configuration patterns |
| [PARSING_OPTIONS_FOR_VARIABLE_INPUT.md](PARSING_OPTIONS_FOR_VARIABLE_INPUT.md) | Handling variable LLM output formats |
| [GENERAL_PURPOSE_LLM_COMPARE_AND_INTEGRATE_FEATURE.md](GENERAL_PURPOSE_LLM_COMPARE_AND_INTEGRATE_FEATURE.md) | Abstracted multi-LLM framework design |

---

## Directory Structure

```
tradingbot/
├── crypto_trading_bot.py      # Main trading bot
├── llm_compare.py            # General-purpose LLM comparison
├── correlation_tracker.py    # Price collection & correlation analysis
├── leading_indicator_tester.py # Paper trading for correlation pairs
├── lp_arbitrage.py           # Liquidity pool arbitrage
├── lp_analyzer.py            # LP analysis utilities
│
├── dex/                      # DEX integration (Solana/Jupiter)
│   ├── jupiterutil.py        # Jupiter API client
│   ├── token_cache.py        # Token mint address cache
│   ├── local_wallet.py       # Solana wallet management
│   └── walletconnect.py      # WalletConnect integration
│
├── llm_utils/                # LLM client wrappers
│   ├── claude_client.py
│   ├── gemini_client.py
│   ├── openai_client.py
│   ├── grok_client.py
│   └── perplexity_client.py
│
├── history/                  # Recommendation history tracking
├── context/                  # Google Trends integration
├── prompts/                  # LLM prompt templates
├── correlation_data/         # Price history storage
├── paper_trades/             # Paper trading logs
└── lab/                      # Experimental scripts
```

---

## API Integrations

| API | Purpose | Module | Required |
|-----|---------|--------|----------|
| **Coinbase** | CEX trading + OHLCV candles for the market data block | `coinbaseutil2.py`, `marketdata.py` | Always (client is constructed even in what-if mode; real orders need live trading armed — see above) |
| **Jupiter** | Solana DEX | `dex/jupiterutil.py` | For DEX trading |
| **CoinGecko** | Price data | `coingeckoutil.py` | Free tier available |
| **CoinMarketCap** | Rank, dominance, supply, %-change (CMC section of the market data block) | `coinmarketcaputil.py`, `marketdata.py` | Free tier (15k credits/mo) |
| **LunarCrush** | Social data, categories, and the SOCIAL section of the market data block | `lunarcrushutil.py`, `marketdata.py` | Individual plan, $24/month |
| **Polymarket** | Prediction markets | `polymarketutil.py` | Free |
| **Santiment** | On-chain metrics | `santimentutil.py` | Free tier |
| **Google Trends** | Search trends; a secondary signal in `crypto_trading_bot.py`'s market data block (own `pytrends` usage), also used by `llm_compare.py` | `context/trends.py` | Free |

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ Implemented | Feature is coded and functional |
| 📋 Design Only | Design document exists, not yet implemented |
| 🚧 In Progress | Partially implemented |

---

## Getting Started by Use Case

### I want to trade crypto with AI recommendations
→ Start with [OPERATIONS_MANUAL.md](OPERATIONS_MANUAL.md) and `crypto_trading_bot.py`

### I want to find correlated trading pairs
→ See [CORRELATION_HISTORY_TRACKER.md](CORRELATION_HISTORY_TRACKER.md) and run `correlation_tracker.py`

### I want to test a correlation strategy
→ See [LEADING_INDICATOR_PERFORMANCE_TESTER.md](LEADING_INDICATOR_PERFORMANCE_TESTER.md) for paper trading

### I want to trade on Solana DEX
→ See [DEX_TRADING_FEATURE.md](DEX_TRADING_FEATURE.md) and the `dex/` module

### I want to arbitrage LP tokens
→ See [LIQUIDITY_POOL_FEATURE.md](LIQUIDITY_POOL_FEATURE.md) and `lp_arbitrage.py`

### I want to compare multiple LLMs on any question
→ See [README_LLM_COMPARE.md](README_LLM_COMPARE.md) and `llm_compare.py`
