# Coin Choice Feature Design Document

## Overview

This feature allows users to specify a list of coins to analyze directly, bypassing the LLM-based discovery phase. This is useful when users want to:
- Analyze specific coins they're interested in
- Re-analyze coins from previous recommendations
- Focus on a watchlist of preferred coins
- Skip the discovery phase to save time and API costs

## Environment Variable

### `ANALYZE_COINS`

A comma-separated list of coin symbols to analyze directly.

| Property | Value |
|----------|-------|
| Name | `ANALYZE_COINS` |
| Type | String (comma-separated) |
| Default | Empty (use LLM discovery) |
| Max Items | 5 |
| Example | `DOGE,SHIB,BONK,PEPE,WIF` |

### Behavior

| `ANALYZE_COINS` Value | Behavior |
|-----------------------|----------|
| Not set / empty | Normal operation: LLM discovers coins |
| Set with 1-5 coins | Skip discovery, analyze specified coins directly |
| Set with >5 coins | Use first 5 coins, warn about truncation |
| Invalid symbols | Attempt analysis, LLM will handle unknown symbols |

## Implementation Design

### 1. Configuration (geminigroundlin15.py)

```python
# Coin choice configuration
ANALYZE_COINS_RAW = os.environ.get('ANALYZE_COINS', '').strip()
ANALYZE_COINS = [c.strip().upper() for c in ANALYZE_COINS_RAW.split(',') if c.strip()][:5]
USE_COIN_DISCOVERY = len(ANALYZE_COINS) == 0
```

### 2. Main Execution Flow

```python
if USE_COIN_DISCOVERY:
    # Existing flow: LLM discovers coins
    primary_response_text = get_primary_recommendation()
    # ... extract coins from response ...
else:
    # New flow: Use specified coins directly
    print(f"Using specified coins: {ANALYZE_COINS}")
    coins_to_analyze = ANALYZE_COINS
    
    for i, coin_symbol in enumerate(coins_to_analyze):
        print(f"\n--- Analyzing coin {i+1}/{len(coins_to_analyze)}: {coin_symbol} ---")
        
        # Run Google Trends check
        googleTrendsRequest(coin_symbol)
        
        # Get analysis from PRIMARY_LLM
        if i == 0:
            # First coin uses trend check (matches current behavior)
            followUpResponseText = get_primary_trend_check(coin_symbol)
        else:
            # Subsequent coins use coin check
            followUpResponseText = get_primary_coin_check(coin_symbol)
        
        print(followUpResponseText)
        
        # Parse recommendation
        followUp_coin = get_text_between_strings(followUpResponseText, "<**", "-PRS-")
        followUp_rec = get_text_between_strings(followUpResponseText, "-PRS-", "**>")
        
        # Apply comparison/integration if enabled
        use_trend = (i == 0)
        final_action = process_coin_with_comparison(coin_symbol, followUpResponseText, use_trend_check=use_trend)
        
        # Execute trade if recommended
        if coin_symbol not in coinsToExclude:
            if final_action and 'BUY' in final_action:
                buy_something(coin_symbol)
```

### 3. Interaction with Other Features

#### LLM_MODE Compatibility

| LLM_MODE | ANALYZE_COINS Behavior |
|----------|------------------------|
| `gemini` | Analyze with Gemini only |
| `claude` | Analyze with Claude only |
| `openai` | Analyze with OpenAI only |
| `grok` | Analyze with Grok only |
| `perplexity` | Analyze with Perplexity only |
| `compare` | Analyze with all COMPARE_LLMS, require consensus |
| `integrate` | Analyze with round 2 cross-feeding |

#### PRIMARY_LLM Compatibility

When `ANALYZE_COINS` is set:
- `PRIMARY_LLM` still determines which LLM performs the initial analysis
- In `compare`/`integrate` modes, other LLMs in `COMPARE_LLMS` still participate

#### coinsToExclude Compatibility

The existing `coinsToExclude` set still applies:
- Coins in `ANALYZE_COINS` that are also in `coinsToExclude` will be analyzed but not traded

## Usage Examples

### Example 1: Analyze Specific Coins with Default Settings
```bash
ANALYZE_COINS=DOGE,SHIB,BONK python geminigroundlin15.py
```
Analyzes 3 coins using Gemini (default PRIMARY_LLM) in compare mode.

### Example 2: Analyze with Grok as Primary
```bash
ANALYZE_COINS=PEPE,WIF PRIMARY_LLM=grok python geminigroundlin15.py
```
Analyzes 2 coins with Grok performing initial analysis.

### Example 3: Single LLM Analysis
```bash
ANALYZE_COINS=DOGE,SHIB LLM_MODE=claude python geminigroundlin15.py
```
Analyzes 2 coins using Claude only.

### Example 4: Full Multi-LLM Integration
```bash
ANALYZE_COINS=DOGE,SHIB,BONK,PEPE,WIF \
  LLM_MODE=integrate \
  PRIMARY_LLM=grok \
  COMPARE_LLMS=grok,gemini,claude,openai \
  python geminigroundlin15.py
```
Analyzes 5 coins with Grok as primary, integrating responses from all 4 LLMs.

## Output Changes

### With Discovery (ANALYZE_COINS not set)
```
--------------ABOVE IS CONTENT OF INITIAL GEMINI RESPONSE----
------WE DOUBLE CHECK THE INITIAL RESPONSE WITH NEW QUERIES
```

### With Specified Coins (ANALYZE_COINS set)
```
=== COIN CHOICE MODE ===
Using specified coins: ['DOGE', 'SHIB', 'BONK']
Skipping LLM discovery phase

--- Analyzing coin 1/3: DOGE ---
[analysis output]

--- Analyzing coin 2/3: SHIB ---
[analysis output]

--- Analyzing coin 3/3: BONK ---
[analysis output]
```

## Summary Output Enhancement

The final summary will include the coin choice configuration:

```
==================================================
LLM MODE: compare
PRIMARY LLM: gemini
COIN CHOICE: DOGE, SHIB, BONK (specified)
COMPARE LLMS: ['gemini', 'claude']
REQUIRE CONSENSUS: True
TIEBREAKER: gemini
Coins to buy: ['DOGE']
==================================================
```

Or when using discovery:
```
COIN CHOICE: LLM Discovery
```

## Validation Rules

1. **Symbol Format**: Symbols are converted to uppercase automatically
2. **Whitespace**: Leading/trailing whitespace is trimmed from each symbol
3. **Empty Values**: Empty strings between commas are ignored
4. **Max Length**: Only first 5 coins are used; excess coins are logged as warning
5. **Duplicates**: Duplicate symbols are analyzed multiple times (no deduplication)

### Validation Examples

| Input | Parsed Result |
|-------|---------------|
| `DOGE,SHIB` | `['DOGE', 'SHIB']` |
| `doge, shib, bonk` | `['DOGE', 'SHIB', 'BONK']` |
| `DOGE,,SHIB` | `['DOGE', 'SHIB']` |
| `A,B,C,D,E,F,G` | `['A', 'B', 'C', 'D', 'E']` (warning logged) |
| ` ` | `[]` (use discovery) |

## Error Handling

| Scenario | Handling |
|----------|----------|
| Invalid coin symbol | LLM attempts analysis; may return "unknown coin" response |
| API error during analysis | Log error, continue to next coin |
| All coins fail | Exit with error summary |

## Implementation Phases

### Phase 1: Basic Implementation
- [ ] Add `ANALYZE_COINS` environment variable parsing
- [ ] Add `USE_COIN_DISCOVERY` flag
- [ ] Implement coin loop for specified coins
- [ ] Update summary output

### Phase 2: Enhanced Features
- [ ] Add coin validation against Coinbase listings
- [ ] Add `--coins` CLI argument as alternative to env var
- [ ] Add support for coin watchlist files

## Open Questions

1. **Should we validate coin symbols against Coinbase before analysis?**
   - Pro: Avoids wasting API calls on invalid symbols
   - Con: Adds API call overhead; symbols may be valid on other exchanges

2. **Should duplicates be deduplicated?**
   - Current design: No deduplication (analyze same coin multiple times)
   - Alternative: Deduplicate and warn

3. **Should we support wildcards or patterns?**
   - Example: `*SHIB*` to match all Shiba-related coins
   - Adds complexity; defer to future enhancement

4. **Should first coin always use trend check vs coin check?**
   - Current design mirrors existing behavior (first = trend, rest = coin)
   - Alternative: All use same check type, configurable via env var
