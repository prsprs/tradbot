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

# Run main trading bot
python crypto_trading_bot.py --trading-mode whatif --llm-mode compare
```

Alternatively, instead of `export`, copy `.env.example` to `.env` and fill in
your keys — the bot loads it automatically at startup. Shell `export`s still
work and take precedence over `.env` values.

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
| **Coinbase** | CEX trading | `coinbaseutil2.py` | For live trading |
| **Jupiter** | Solana DEX | `dex/jupiterutil.py` | For DEX trading |
| **CoinGecko** | Price data | `coingeckoutil.py` | Free tier available |
| **LunarCrush** | Social data, categories | `lunarcrushutil.py` | $24/month |
| **Polymarket** | Prediction markets | `polymarketutil.py` | Free |
| **Santiment** | On-chain metrics | `santimentutil.py` | Free tier |
| **Google Trends** | Search trends | `context/trends.py` | Free |

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
