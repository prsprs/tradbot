# Crypto Trading Bot

An AI-powered cryptocurrency trading bot that uses multiple LLMs to analyze coins and make buy/sell/hold recommendations. Supports single-LLM mode or multi-LLM comparison and integration for higher-confidence trading signals.

## Features

- **Multi-LLM Support:** Gemini, Claude, OpenAI GPT-4o, Grok, and Perplexity
- **Comparison Mode:** Get recommendations from multiple LLMs and only act on consensus
- **Integration Mode:** LLMs review each other's analysis before making final recommendations
- **Real-time Data:** Uses Google Search grounding and web search for current market information
- **Google Trends:** Incorporates trend data into analysis
- **History Tracking:** Records all recommendations for later accuracy analysis
- **Performance Analytics:** Analyze historical recommendation accuracy by LLM and mode

## Quick Start

### Prerequisites

1. Python 3.9+
2. Coinbase Advanced Trade API credentials
3. At least one LLM API key (Gemini recommended as primary)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/tradbot.git
cd tradbot
pip install google-genai anthropic openai pytrends pandas coinbase-advanced-py requests
```

### Setup Credentials

1. **Coinbase:** Download API key JSON from https://cloud.coinbase.com/access/api and save as `cdp_api_key.json`

2. **LLM API Keys:** Set environment variables for the LLMs you want to use:
   ```bash
   export GOOGLE_API_KEY=...        # For Gemini
   export CLAUDE_API_KEY=...        # For Claude
   export OPENAI_API_KEY=...        # For OpenAI
   export XAI_API_KEY=...           # For Grok
   export PERPLEXITY_API_KEY=...    # For Perplexity
   ```

### Run the Trading Bot

```bash
# Single LLM mode (Gemini)
export LLM_MODE=gemini
python geminigroundlin15.py

# Compare mode (requires consensus)
export LLM_MODE=compare
export COMPARE_LLMS=gemini,claude
python geminigroundlin15.py

# Analyze specific coins
export ANALYZE_COINS=BTC,ETH,DOGE
python geminigroundlin15.py
```

### Run the Analyzer

Analyze the accuracy of past recommendations:

```bash
python tradeanalyzer.py
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODE` | `compare` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `compare`, or `integrate` |
| `PRIMARY_LLM` | `gemini` | LLM for coin discovery |
| `COMPARE_LLMS` | `gemini,claude` | LLMs to use in compare/integrate modes |
| `REQUIRE_CONSENSUS` | `true` | Only act when all LLMs agree |
| `ANALYZE_COINS` | *(empty)* | Specific coins to analyze (max 5), or let LLM discover |

## Programs

| Program | Purpose |
|---------|---------|
| `geminigroundlin15.py` | Main trading bot |
| `tradeanalyzer.py` | Analyze historical recommendation accuracy |

## Project Structure

```
├── geminigroundlin15.py      # Main trading bot
├── tradeanalyzer.py          # Recommendation analyzer
├── coinbaseutil2.py          # Coinbase trading client
├── claudeutil.py             # Claude LLM client
├── openaiutil.py             # OpenAI LLM client
├── grokutil.py               # Grok LLM client
├── perplexityutil.py         # Perplexity LLM client
├── historyutil.py            # History recording utility
├── coingeckoutil.py          # CoinGecko fallback pricing
├── cdp_api_key.json          # Coinbase credentials (gitignored)
├── OPERATIONS_MANUAL.md      # Detailed documentation
└── history/
    ├── recommendations.json  # Recommendation history
    └── analysis_*.csv        # Analysis results
```

## APIs Used

| Service | Purpose | Auth |
|---------|---------|------|
| Google Gemini | Primary LLM with web search | `GOOGLE_API_KEY` |
| Anthropic Claude | Secondary LLM | `CLAUDE_API_KEY` |
| OpenAI | Secondary LLM | `OPENAI_API_KEY` |
| xAI Grok | Secondary LLM with web search | `XAI_API_KEY` |
| Perplexity | Secondary LLM with search | `PERPLEXITY_API_KEY` |
| Coinbase | Trading & price data | `cdp_api_key.json` |
| CoinGecko | Fallback pricing | Optional `COINGECKO_API_KEY` |
| Google Trends | Trend analysis | None required |

## Documentation

See [OPERATIONS_MANUAL.md](OPERATIONS_MANUAL.md) for detailed documentation including:
- Complete environment variable reference
- API configuration details
- Credential file formats
- Regression testing procedures

## License

MIT
