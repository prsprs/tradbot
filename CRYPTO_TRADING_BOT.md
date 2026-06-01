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
python crypto_trading_bot.py

# Compare mode (requires consensus)
export LLM_MODE=compare
export COMPARE_LLMS=gemini,claude
python crypto_trading_bot.py

# Analyze specific coins
export ANALYZE_COINS=BTC,ETH,DOGE
python crypto_trading_bot.py
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
| `crypto_trading_bot.py` | Main trading bot |
| `tradeanalyzer.py` | Analyze historical recommendation accuracy |

## Project Structure

```
├── crypto_trading_bot.py      # Main trading bot
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

---

## Candidate Coins Export Feature (Design)

### Overview

Enable the trading bot's LLM discovery to export discovered coins to the Candidate Coins Datastore (`candidate_coins.csv`), allowing seamless integration with the Leading Indicator Tester's correlation analysis pipeline.

### Current Flow

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ LLM Discovery   │────▶│ Analysis &   │────▶│ Trade           │
│ (find trending  │     │ Recommendation│     │ Execution       │
│  coins)         │     │              │     │ (Coinbase)      │
└─────────────────┘     └──────────────┘     └─────────────────┘
```

### Proposed Flow

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ LLM Discovery   │────▶│ Analysis &   │────▶│ Trade           │
│ (find trending  │     │ Recommendation│     │ Execution       │
│  coins)         │     │              │     │ (Coinbase)      │
└────────┬────────┘     └──────────────┘     └─────────────────┘
         │
         │ --export-candidates
         ▼
┌─────────────────┐     ┌──────────────────────────────────────┐
│ candidate_coins │────▶│ correlation_tracker.py               │
│ .csv            │     │ leading_indicator_tester.py          │
└─────────────────┘     │ --use-candidate-coins                │
                        └──────────────────────────────────────┘
```

### Usage

```bash
# Export discovered coins to candidate_coins.csv
python crypto_trading_bot.py --export-candidates

# Export to a specific directory
python crypto_trading_bot.py --export-candidates --candidate-dir ./correlation_data

# Export only (no trading)
python crypto_trading_bot.py --export-candidates --dry-run

# Then run correlation analysis on discovered coins
python correlation_tracker.py --collect --use-candidate-coins --duration 4hr
python leading_indicator_tester.py --auto-select --use-candidate-coins --use-fib
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPORT_CANDIDATES` | `false` | Export discovered coins to candidate_coins.csv |
| `CANDIDATE_DIR` | `./correlation_data` | Directory for candidate_coins.csv |
| `CANDIDATE_BLOCKCHAIN` | `Solana` | Default blockchain for exported coins |

### CSV Format

Exported coins follow the Candidate Coins Datastore format:

```csv
symbol,blockchain,added_at,updated_at,source
BONK,Solana,2026-06-01T14:30:00Z,,llm_recommendation_gemini
WIF,Solana,2026-06-01T14:32:00Z,,llm_recommendation_claude
PEPE,Solana,2026-06-01T14:35:00Z,,llm_recommendation_compare
```

**Source field values:**
- `llm_recommendation_gemini` - Recommended by Gemini
- `llm_recommendation_claude` - Recommended by Claude
- `llm_recommendation_compare` - Recommended via compare mode
- `llm_recommendation_integrate` - Recommended via integrate mode

### Implementation Approach: Recommendation-Time Export

Export coins when they receive a recommendation, integrating with the existing `historyutil.record_recommendation()` flow. This approach leverages the fact that coins are already vetted through full LLM analysis before receiving a recommendation.

**Integration point:** Modify `record_recommendation()` in `historyutil.py` to optionally write to `candidate_coins.csv` when saving a recommendation.

```python
# In historyutil.py
def record_recommendation(
    coin_symbol: str,
    recommendation: str,
    trader,
    llm_source: str,
    mode: str,
    consensus: Optional[bool] = None,
    discovery_llm: Optional[str] = None,
    exchange: Optional[str] = None,
    export_candidate: bool = False,        # NEW
    candidate_dir: str = './correlation_data',  # NEW
    candidate_blockchain: str = 'Solana'   # NEW
):
    # ... existing recommendation recording ...
    
    if export_candidate:
        from candidate_util import add_candidate_coin
        source = f"llm_recommendation_{mode}"
        add_candidate_coin(coin_symbol, candidate_blockchain, source, candidate_dir)
```

### Alternatives

#### Alternative A: Export All Recommendations (Recommended)
Export any coin that receives a BUY, SELL, or HOLD recommendation.

**Pros:**
- Coins are vetted (went through full analysis)
- Includes coins worthy of monitoring even if not BUY
- Simple: export whenever `record_recommendation()` is called

**Cons:**
- May include SELL recommendations (coins to avoid?)

#### Alternative B: Export BUY Only
Only export coins with BUY recommendations.

**Pros:**
- Higher signal - only coins the LLMs are bullish on
- Smaller candidate list

**Cons:**
- Misses coins that might become BUY later
- Correlation analysis might find value in non-BUY coins

#### Alternative C: Configurable Filter
`EXPORT_RECOMMENDATIONS=BUY,HOLD` or `EXPORT_RECOMMENDATIONS=ALL`

**Pros:**
- User controls what gets exported
- Flexible for different use cases

**Cons:**
- More configuration complexity

### Design Decisions

| Question | Decision |
|----------|----------|
| **Filtering by recommendation** | Configurable via `EXPORT_RECOMMENDATIONS` (default: `ALL`). Options: `BUY`, `BUY,HOLD`, or `ALL` |
| **Integration with ANALYZE_COINS** | Works for both LLM-discovered AND manually specified coins - export at recommendation time |
| **Batch vs streaming** | Streaming - export as each recommendation is recorded |
| **Confidence threshold** | N/A - recommendation itself is the vetting filter (coin passed LLM analysis) |
| **Duplicate handling** | **Upsert** - one record per coin. Preserve original `added_at`, update `updated_at` on re-recommendation |
| **Blockchain detection** | Use `CANDIDATE_BLOCKCHAIN` env var (default: `Solana`). Downstream tools use CoinGecko (chain-agnostic) - blockchain is metadata only |
| **Rate limiting** | No cooldown. Upsert handles duplicates |
| **Notification** | Console log for MVP: `[CANDIDATE] Exported: BONK (Solana)` |

### Upsert Implementation

```python
def upsert_candidate_coin(symbol: str, blockchain: str, source: str,
                          data_dir: str = './correlation_data') -> bool:
    """
    Add or update a candidate coin in the CSV datastore.
    - New coin: creates record with added_at timestamp
    - Existing coin: updates updated_at timestamp and source
    """
    import csv
    from datetime import datetime, timezone
    
    csv_path = Path(data_dir) / 'candidate_coins.csv'
    now = datetime.now(timezone.utc).isoformat()
    symbol = symbol.upper()
    
    # Read existing records
    records = {}
    if csv_path.exists():
        with open(csv_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records[row['symbol'].upper()] = row
    
    # Upsert
    if symbol in records:
        records[symbol]['updated_at'] = now
        records[symbol]['source'] = source
        action = "Updated"
    else:
        records[symbol] = {
            'symbol': symbol,
            'blockchain': blockchain,
            'added_at': now,
            'updated_at': '',
            'source': source
        }
        action = "Added"
    
    # Write all records
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['symbol', 'blockchain', 'added_at', 'updated_at', 'source'])
        writer.writeheader()
        for rec in sorted(records.values(), key=lambda r: r['symbol']):
            writer.writerow(rec)
    
    print(f"[CANDIDATE] {action}: {symbol} ({blockchain}) from {source}")
    return True
```

## License

MIT
