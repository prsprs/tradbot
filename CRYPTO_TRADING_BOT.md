pl# Crypto Trading Bot

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

---

## Custom Fibonacci Range Override (Design)

### Overview

Allow users to manually specify a Fibonacci price range via `--fib-range low:high`, overriding the auto-calculated low/high from historical price data. This is useful when:

- The auto-calculated range is stale or based on insufficient data
- User has domain knowledge about expected price bounds
- Testing specific price scenarios
- Working with tokens that have limited historical data

### Usage

```bash
# Override Fib range with custom low:high values
python leading_indicator_tester.py --auto-select --use-fib --fib-range 0.02:0.025

# Combine with other Fib options
python leading_indicator_tester.py --leader BTC --follower PERP --use-fib \
    --fib-range 0.018:0.024 --fib-min-effectiveness 20

# Use with live trading
python leading_indicator_tester.py --auto-select --use-fib --fib-range 0.02:0.025 \
    --trading-mode live --max-trade-usd 10
```

### CLI Arguments

| Argument | Format | Description |
|----------|--------|-------------|
| `--fib-range` | `low:high` | Override Fib price range (e.g., `0.02:0.025`). Both values required, colon-separated. |

### Behavior

1. **When `--fib-range` is specified:**
   - Skip auto-calculation of low/high from historical data
   - Use provided values directly for Fib level calculations
   - Fib levels (23.6%, 38.2%, 50%, 61.8%, 78.6%) calculated from custom range
   - Trend direction still auto-detected OR can be overridden separately

2. **Validation:**
   - `low` must be less than `high`
   - Both values must be positive numbers
   - Error message if format is invalid: `Invalid --fib-range format. Use: low:high (e.g., 0.02:0.025)`

3. **Display:**
   - Show `[CUSTOM]` indicator when range is overridden:
     ```
     Fib report loaded for PERP:
       Trend direction: DOWN
       Price range: $0.0200 - $0.0250 [CUSTOM]
       Window: N/A (custom range)
     ```

### Implementation Notes

**In `fibonacci_analyzer.py`:**
- Add optional `price_range_override: Tuple[float, float]` parameter to `FibonacciAnalyzer.analyze()`
- When override provided, skip historical low/high calculation
- Set `analysis_window` to `"custom"` in report

**In `leading_indicator_tester.py`:**
- Parse `--fib-range` argument: split on `:`, validate, convert to floats
- Pass override to Fib analyzer if specified
- Update display to show `[CUSTOM]` indicator

### Example Output

```
======================================================================
                    FIBONACCI TRADE FILTERING
======================================================================

Fib report loaded for PERP:
  Trend direction: DOWN
  Price range: $0.0200 - $0.0250 [CUSTOM]
  Window: N/A (custom range)
  Effective levels: 5

  Effective Fib levels (>=20.0% bounce rate):
    • 23.6%: $0.0238 (N/A - custom range)
    • 38.2%: $0.0231 (N/A - custom range)
    • 50.0%: $0.0225 (N/A - custom range)
    • 61.8%: $0.0219 (N/A - custom range)
    • 78.6%: $0.0211 (N/A - custom range)

  Trade direction: SELL only

  Note: Using custom Fib range - effectiveness data unavailable
```

### Interaction with Exchange Fallback

When `--fib-range` is specified, the Fib range sanity check for symbol collision detection uses the custom range:

```
[RANGE CHECK] PERP on jupiter: $3.3400 outside Fib range $0.0200-$0.0250
  May be symbol collision (different token) - trying coingecko...
[FALLBACK] PERP: used coingecko (previous exchange(s) out of expected range)
```

This ensures the custom range serves as both trading bounds AND price source validation.

---

## Standalone Fibonacci Trading Mode (Design)

### Overview

Enable trading a single coin using **only Fibonacci analysis** for buy/sell signals, without requiring a leading indicator correlation. The bot would monitor the coin's price relative to Fib levels and execute trades based on support/resistance bounces.

### Motivation

The current leading indicator system requires:
1. Finding a correlated leader/follower pair
2. Monitoring leader price movements
3. Predicting follower movements based on leader

This works well for correlated pairs but excludes:
- Coins with no strong correlation to any leader
- Coins where Fib levels alone provide sufficient signal
- Simpler trading strategies with fewer dependencies
- Users who want to trade a specific coin without searching for correlations

### Use Cases

1. **LLM-Discovered Coins**: Bot discovers PEPE as a trending coin → trade using Fib levels only
2. **User-Specified Coin**: User knows they want to trade WIF → apply Fib strategy without correlation search
3. **Quick Setup**: Trade immediately with `--fib-range` without waiting for correlation data collection
4. **Fib-Only Strategy**: Some traders prefer pure technical analysis over correlation-based strategies

### Proposed Signal Logic

Without a leading indicator, buy/sell signals would be based on:

```
BUY Signal:
  - Price approaches or bounces from a support Fib level (23.6%, 38.2%, etc.)
  - Price is trending up from the level
  - Optional: Volume confirmation

SELL Signal:
  - Price approaches or bounces from a resistance Fib level
  - Price is trending down from the level
  - Optional: Position in profit by X%

HOLD:
  - Price is between levels, no clear bounce
  - Wait for clearer signal
```

### Design Alternatives

#### Alternative A: New Standalone Script (`fib_trader.py`)

Create a dedicated Fibonacci trading script separate from `leading_indicator_tester.py`.

```bash
python fib_trader.py --coin PEPE --use-fib --fib-range 0.000001:0.000002 \
    --trading-mode live --max-trade-usd 10
```

**Pros:**
- Clean separation of concerns
- Simpler codebase for each strategy
- No impact on existing leading indicator logic

**Cons:**
- Code duplication (trading execution, wallet integration, Fib analysis)
- Two tools to maintain
- User confusion about which tool to use

#### Alternative B: Add `--bypass-leader` to Leading Indicator Tester (IMPLEMENTED)

Add a flag to `leading_indicator_tester.py` that skips leader correlation but preserves all Fib logic including trend direction enforcement.

```bash
python leading_indicator_tester.py --bypass-leader \
    --follower-coin PEPE --use-fib --fib-range 0.000001:0.000002 \
    --trading-mode live --max-trade-usd 10
```

**Pros:**
- Reuses existing infrastructure (wallet, trading, Fib analysis)
- Single tool for both strategies
- Smaller code footprint

**Cons:**
- Complicates leading_indicator_tester.py (now handles two modes)
- Name becomes misleading ("leading indicator" when no leader exists)
- Signal generation logic becomes branched

#### Alternative C: Add Fib Trading to `crypto_trading_bot.py`

Integrate Fib trading into the main trading bot, which already handles coin discovery.

```bash
# Discover coins via LLM, trade using Fib
python crypto_trading_bot.py --trading-strategy fib --use-fib

# Specify coin directly
python crypto_trading_bot.py --analyze-coins PEPE --trading-strategy fib \
    --fib-range 0.000001:0.000002
```

**Pros:**
- Leverages LLM discovery pipeline
- Natural fit for "discover and trade" workflow
- Single entry point for all trading strategies

**Cons:**
- crypto_trading_bot.py focused on LLM analysis, not technical trading
- Would require significant refactoring
- Mixes two different trading philosophies

#### Alternative D: Rename & Generalize Leading Indicator Tester

Rename `leading_indicator_tester.py` to `correlation_trader.py` or `signal_trader.py` and support multiple signal sources:

```bash
# Correlation-based (current behavior)
python signal_trader.py --signal-mode correlation --pair BTC:PEPE --use-fib

# Fib-only mode
python signal_trader.py --signal-mode fib-only --follower-coin PEPE \
    --fib-range 0.000001:0.000002

# Auto-discover with Fib-only
python signal_trader.py --signal-mode fib-only --auto-select --use-candidate-coins
```

**Pros:**
- Clean abstraction (signal source is configurable)
- Extensible to future signal modes (e.g., RSI, MACD)
- Honest naming

**Cons:**
- Breaking change (rename)
- More complex architecture
- May be over-engineering for the current need

### Signal Generation Comparison

| Aspect | Leader-Based (Current) | Fib-Only (Proposed) |
|--------|------------------------|---------------------|
| **BUY trigger** | Leader price rises → expect follower to follow | Price bounces from support Fib level |
| **SELL trigger** | Leader price falls → expect follower to follow | Price bounces from resistance Fib level |
| **Timing** | Based on lag from leader | Based on price reaching Fib level |
| **Confidence source** | Correlation strength | Fib level effectiveness (bounce rate) |
| **Data requirement** | Historical correlation data | Historical price data (for Fib calculation) |

### Open Questions

1. **Signal Timing**: Without a leader to watch, what triggers a price check?
   - Fixed interval (e.g., every 30s)?
   - Event-driven (WebSocket price feed)?
   - Same as current `--sample-interval`?

2. **Entry/Exit Logic**: How to determine optimal entry after a bounce?
   - Enter immediately on touch of Fib level?
   - Wait for confirmation (N candles above level)?
   - Use momentum indicators?

3. **Position Management**: How to handle multiple Fib levels?
   - Scale in at each support level?
   - Single position at strongest level?
   - Dynamic position sizing based on level effectiveness?

4. **Auto-Select Compatibility**: Can `--auto-select` work with Fib-only mode?
   - What criteria would replace correlation strength?
   - Filter by Fib effectiveness alone?
   - Combine with LLM recommendation confidence?

5. **Risk Management**: Without leader divergence warnings, what guards against losses?
   - Stop-loss at next Fib level down?
   - Time-based exit (hold max N hours)?
   - Maximum drawdown percentage?

6. **Trend Direction**: How to determine if we should BUY bounces or SELL bounces?
   - Auto-detect from recent price action?
   - Require user to specify `--direction up|down`?
   - Use LLM sentiment analysis?

7. **Tool Choice**: Should this be in leading_indicator_tester.py or a new tool?
   - Simpler: Add `--bypass-leader-logic` flag
   - Cleaner: New dedicated `fib_trader.py`
   - Which aligns better with project goals?

### Implementation Status

**Alternative B (`--bypass-leader`) has been implemented.**

**Usage:**
```bash
python leading_indicator_tester.py --bypass-leader \
    --follower-coin PEPE --use-fib --fib-range 0.000001:0.000002 \
    --sample-interval 30 --trading-mode paper
```

**Current Behavior:**
- Skips correlation/leader analysis phases entirely
- Uses Fib levels as signal source based on coin's own price action
- **Enforces trend direction**: uptrend = BUY only, downtrend = SELL only
- Checks price at `--sample-interval` frequency (default: 30s)
- In uptrend: BUY signals on bounce from support levels
- In downtrend: SELL signals on rejection at resistance levels
- Signal cooldown: 3× sample interval to prevent noise
- Paper mode logs signals; live trading execution pending

---

## License

MIT
