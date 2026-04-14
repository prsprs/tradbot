# Parsing Options for Variable LLM Output

## Problem Statement

The trading bot parses LLM responses to extract coin symbols for Google Trends analysis and subsequent trading decisions. However, LLM outputs are **inconsistent** across different models, contexts, and even within the same response. This leads to:

1. **Extraction failures** - No coin symbol extracted
2. **Invalid extractions** - Text like `"over $490M"` or `"Bonk (BONK)"` sent to Google Trends instead of just `"BONK"`
3. **Partial extractions** - Comma-separated lists treated as single values

## Observed Output Formats

### Numbered Recommendations (1., 2., 3.)

| Format | Example | Desired Output |
|--------|---------|----------------|
| Bold symbol only | `1. **PEPE** - description...` | `PEPE` |
| Bold name with symbol | `1. **dogwifhat (WIF)** - description...` | `WIF` |
| Bold name, symbol in parens | `1. **Bonk (BONK)** - description...` | `BONK` |
| Parenthetical noise | `...volume (over $490M)...` | *Skip* |
| No bold markers | `1. PEPE - description...` | `PEPE` |

### Social Media Section (+++...+++)

| Format | Example | Desired Output |
|--------|---------|----------------|
| Single coin per marker | `+++PEPE+++ +++DOGE+++` | `PEPE`, then `DOGE` |
| Multiple coins, one marker | `+++FARTCOIN, dogwifhat (WIF)+++` | `FARTCOIN`, `WIF` |
| Mixed format | `+++PEPE, BONK+++` | `PEPE`, `BONK` |

### Follow-up Response Format

| Format | Example | Desired Output |
|--------|---------|----------------|
| Standard | `<**PEPE-PRS-BUY**>` | Coin: `PEPE`, Rec: `BUY` |
| With spaces | `<**dogwifhat - PRS - BUY**>` | Coin: `dogwifhat`, Rec: `BUY` |
| Symbol mismatch | `<**Bonk - PRS - BUY**>` | Coin: `Bonk` (needs mapping to `BONK`) |

## Root Causes

1. **Delimiter-based parsing is fragile** - Looking for `(` and `)` catches unrelated parenthetical text
2. **LLMs don't follow strict formats** - Different models use different conventions
3. **Same model varies by context** - Response style changes based on coin name complexity
4. **No normalization** - Extracted text isn't cleaned to a canonical symbol format
5. **No validation** - Extracted text isn't verified as a valid Coinbase symbol

---

## Part A: Input-Side Solutions (Prompt Engineering) - FUTURE CONSIDERATION

> **Note:** The options in this section are documented for future consideration. The current implementation focuses on output-side parsing (Part B) to handle variable LLM responses without requiring prompt changes.

Since we control the prompts sent to LLMs, we can modify them to produce more parseable output. This is often more effective than complex output parsing.

### Option A1: Explicit Format Instructions with Examples

**Description:** Add explicit formatting rules and examples to the prompt.

**Current Prompt (implied):**
```
List your top 3 recommendations...
At the end, list coins showing positive social media trends using +++ markers.
```

**Enhanced Prompt:**
```
List your top 3 recommendations. Format each as:
1. **[SYMBOL]** - description

Use ONLY the Coinbase ticker symbol (e.g., PEPE, DOGE, WIF, BONK).
Do NOT include the full name. Do NOT use "name (SYMBOL)" format.

Example correct format:
1. **PEPE** - Strong momentum with 12% gains...
2. **DOGE** - ETF approval driving volume...
3. **WIF** - Solana ecosystem strength...

At the end, list social trending coins as: +++SYMBOL1+++ +++SYMBOL2+++
Each coin gets its own +++ markers. Do NOT combine multiple coins in one marker.
```

**Pros:**
- Simple change to existing prompts
- Works with all LLMs
- No code changes needed

**Cons:**
- LLMs may still deviate
- Requires prompt updates across multiple LLMs

### Option A2: Symbol-Only Output Line

**Description:** Request a dedicated machine-parseable line with just symbols.

**Prompt Addition:**
```
After your analysis, include a single line starting with "SYMBOLS:" containing only 
the Coinbase ticker symbols, comma-separated, in recommendation order.

Example:
SYMBOLS: PEPE, DOGE, WIF
SOCIAL: PEPE, BONK
```

**Parsing:**
```python
def extract_symbols_line(response_text):
    match = re.search(r'^SYMBOLS:\s*(.+)$', response_text, re.MULTILINE)
    if match:
        return [s.strip().upper() for s in match.group(1).split(',')]
    return None

def extract_social_line(response_text):
    match = re.search(r'^SOCIAL:\s*(.+)$', response_text, re.MULTILINE)
    if match:
        return [s.strip().upper() for s in match.group(1).split(',')]
    return None
```

**Pros:**
- Single line to parse
- Clear separation from prose
- Easy validation (all items should be 2-10 char symbols)

**Cons:**
- LLM may forget to include the line
- Adds slight redundancy to output

### Option A3: Structured Delimiter Protocol

**Description:** Define a strict delimiter protocol that's unambiguous.

**Prompt Addition:**
```
For each recommendation, wrap the symbol in [COIN]...[/COIN] tags:
1. [COIN]PEPE[/COIN] - description...

For social trending, use [SOCIAL]SYMBOL1,SYMBOL2[/SOCIAL]
```

**Parsing:**
```python
def extract_coins_from_tags(text):
    return re.findall(r'\[COIN\]([A-Z]{2,10})\[/COIN\]', text)

def extract_social_from_tags(text):
    match = re.search(r'\[SOCIAL\](.+?)\[/SOCIAL\]', text)
    if match:
        return [s.strip().upper() for s in match.group(1).split(',')]
    return []
```

**Pros:**
- XML-like tags are familiar to LLMs (training data)
- Unambiguous parsing
- Can't confuse with prose content

**Cons:**
- Verbose output
- May look odd to users reading logs

### Option A4: Coinbase Symbol Constraint

**Description:** Explicitly constrain output to Coinbase-listed symbols only.

**Prompt Addition:**
```
IMPORTANT: Use ONLY these Coinbase-listed meme coin symbols:
DOGE, SHIB, PEPE, BONK, WIF, FLOKI, FARTCOIN, TRUMP, BRETT, MOG, POPCAT, NEIRO

Do NOT use full names like "dogwifhat" or "Bonk". Use the exact symbol: WIF, BONK.
```

**Pros:**
- Eliminates name-vs-symbol ambiguity
- LLM knows exactly what to output
- Easy validation (check against list)

**Cons:**
- Must maintain symbol list in prompts
- May miss newly listed coins

### Option A5: Two-Phase Response (Recommended for Input-Side)

**Description:** Request analysis first, then a structured summary.

**Prompt Structure:**
```
Phase 1: Provide your detailed analysis of meme coins...

Phase 2: After your analysis, provide a structured summary block:
---SUMMARY---
REC1: [symbol]
REC2: [symbol]
REC3: [symbol]
SOCIAL: [symbol1], [symbol2]
---END---

Use ONLY Coinbase ticker symbols (PEPE, DOGE, WIF, etc.), not full names.
```

**Parsing:**
```python
def parse_summary_block(text):
    match = re.search(r'---SUMMARY---(.+?)---END---', text, re.DOTALL)
    if not match:
        return None
    
    block = match.group(1)
    result = {}
    
    for i in range(1, 4):
        rec_match = re.search(rf'REC{i}:\s*(\w+)', block)
        if rec_match:
            result[f'rec{i}'] = rec_match.group(1).upper()
    
    social_match = re.search(r'SOCIAL:\s*(.+)', block)
    if social_match:
        result['social'] = [s.strip().upper() for s in social_match.group(1).split(',')]
    
    return result
```

**Pros:**
- Clear separation of human-readable and machine-parseable content
- Easy to validate structure
- Flexible analysis phase
- Works across all LLMs

**Cons:**
- Slightly more complex prompt
- LLM may merge phases or omit summary

---

## Part B: Output-Side Solutions (Parsing Strategies)

### Option 1: Strict Prompt Engineering (Current Approach)

**Description:** Instruct the LLM to output in a specific format and parse that format.

**Pros:**
- Simple implementation
- Works when LLM follows instructions

**Cons:**
- LLMs don't always follow format instructions
- Different LLMs have different compliance rates
- Breaks silently when format varies

**Current Implementation:**
```python
# Look for **SYMBOL** format
extracted = get_text_between_strings(result, "**", "**")
```

### Option 2: Multi-Pattern Extraction with Fallback Chain

**Description:** Try multiple extraction patterns in priority order until one succeeds.

**Pros:**
- Handles format variability
- Graceful degradation

**Cons:**
- More complex logic
- May extract wrong content if patterns overlap

**Example:**
```python
def extract_coin_symbol(text):
    # Try patterns in order of specificity
    patterns = [
        r'\*\*([A-Z]{2,10})\*\*',           # **SYMBOL** (uppercase only)
        r'\*\*\w+\s*\(([A-Z]{2,10})\)\*\*', # **name (SYMBOL)**
        r'\*\*([A-Za-z]+)\*\*',             # **Name** (any case)
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).upper()
    return None
```

### Option 3: Symbol Extraction with Validation

**Description:** Extract candidate text, then validate against known Coinbase symbols.

**Pros:**
- Catches invalid extractions early
- Works regardless of format
- Self-correcting

**Cons:**
- Requires maintaining symbol list
- API call overhead for validation
- May reject new/unlisted coins

**Example:**
```python
KNOWN_SYMBOLS = {'BTC', 'ETH', 'DOGE', 'SHIB', 'PEPE', 'BONK', 'WIF', 'FLOKI', 'FARTCOIN', ...}

def extract_and_validate(text):
    candidates = extract_all_potential_symbols(text)
    for candidate in candidates:
        symbol = normalize_to_symbol(candidate)
        if symbol in KNOWN_SYMBOLS:
            return symbol
        # Or validate via Coinbase API
        if coinbase_product_exists(f"{symbol}-USD"):
            return symbol
    return None
```

### Option 4: Name-to-Symbol Mapping

**Description:** Maintain a mapping of coin names to symbols.

**Pros:**
- Handles `dogwifhat` → `WIF`, `Bonk` → `BONK`
- Deterministic mapping

**Cons:**
- Requires maintaining mapping table
- Misses new coins

**Example:**
```python
NAME_TO_SYMBOL = {
    'dogwifhat': 'WIF',
    'bonk': 'BONK',
    'pepe': 'PEPE',
    'dogecoin': 'DOGE',
    'shiba inu': 'SHIB',
    'floki': 'FLOKI',
    'fartcoin': 'FARTCOIN',
}

def normalize_coin(extracted):
    # Clean and lowercase
    cleaned = extracted.strip().lower()
    
    # Direct match
    if cleaned.upper() in KNOWN_SYMBOLS:
        return cleaned.upper()
    
    # Name mapping
    if cleaned in NAME_TO_SYMBOL:
        return NAME_TO_SYMBOL[cleaned]
    
    # Extract from "name (SYMBOL)" format
    match = re.search(r'\(([A-Z]{2,10})\)', extracted)
    if match:
        return match.group(1)
    
    return None
```

### Option 5: Structured Output (JSON Mode)

**Description:** Request LLM to output structured JSON with explicit fields.

**Pros:**
- Unambiguous parsing
- Self-documenting format
- Easy to extend

**Cons:**
- Not all LLMs support JSON mode
- Larger token usage
- May still have compliance issues

**Example Prompt:**
```
Respond with JSON only:
{
  "recommendations": [
    {"symbol": "PEPE", "action": "BUY", "confidence": 0.8},
    {"symbol": "DOGE", "action": "HOLD", "confidence": 0.6}
  ],
  "social_trending": ["PEPE", "BONK"]
}
```

### Option 6: Hybrid Multi-Stage Pipeline (Recommended)

**Description:** Combine multiple strategies in a pipeline:

1. **Extract** - Use multi-pattern regex extraction
2. **Normalize** - Clean extracted text, apply name mapping
3. **Validate** - Check against known symbols or Coinbase API
4. **Fallback** - If all fails, skip gracefully with logging

**Pros:**
- Robust against format variations
- Self-correcting
- Clear failure modes
- Extensible

**Cons:**
- More complex implementation
- Slightly higher latency

## Recommended Implementation

### Phase 1: Coin Symbol Extractor Module

Create a dedicated module `coinextractor.py`:

```python
import re
from typing import List, Optional, Tuple

# Known Coinbase meme coin symbols (expand as needed)
KNOWN_SYMBOLS = {
    'BTC', 'ETH', 'DOGE', 'SHIB', 'PEPE', 'BONK', 'WIF', 'FLOKI', 
    'FARTCOIN', 'TRUMP', 'BRETT', 'MOG', 'POPCAT', 'NEIRO'
}

# Name to symbol mapping for common variations
NAME_TO_SYMBOL = {
    'dogwifhat': 'WIF',
    'bonk': 'BONK',
    'pepe': 'PEPE',
    'dogecoin': 'DOGE',
    'doge': 'DOGE',
    'shiba inu': 'SHIB',
    'shib': 'SHIB',
    'floki': 'FLOKI',
    'fartcoin': 'FARTCOIN',
    'bitcoin': 'BTC',
    'ethereum': 'ETH',
}

def extract_symbol_from_text(text: str) -> Optional[str]:
    """
    Extract a single coin symbol from text using multiple strategies.
    Returns normalized uppercase symbol or None.
    """
    if not text:
        return None
    
    # Strategy 1: Look for (SYMBOL) pattern - most reliable
    match = re.search(r'\(([A-Z]{2,10})\)', text)
    if match and match.group(1) in KNOWN_SYMBOLS:
        return match.group(1)
    
    # Strategy 2: Clean uppercase word that matches known symbol
    words = re.findall(r'\b([A-Z]{2,10})\b', text)
    for word in words:
        if word in KNOWN_SYMBOLS:
            return word
    
    # Strategy 3: Name mapping (case-insensitive)
    text_lower = text.lower().strip()
    
    # Remove common suffixes/noise
    text_lower = re.sub(r'\s*\([^)]*\)\s*', '', text_lower)  # Remove (...)
    text_lower = text_lower.strip()
    
    if text_lower in NAME_TO_SYMBOL:
        return NAME_TO_SYMBOL[text_lower]
    
    # Strategy 4: Partial name match
    for name, symbol in NAME_TO_SYMBOL.items():
        if name in text_lower or text_lower in name:
            return symbol
    
    # Strategy 5: If text itself looks like a symbol (2-10 uppercase chars)
    if re.match(r'^[A-Z]{2,10}$', text.strip()):
        return text.strip()
    
    return None


def extract_coins_from_social_line(line: str) -> List[str]:
    """
    Extract multiple coin symbols from social media recommendation line.
    Handles: "+++PEPE+++ +++DOGE+++" or "+++FARTCOIN, dogwifhat (WIF)+++"
    """
    coins = []
    
    # Remove +++ markers and split by comma or +++
    cleaned = re.sub(r'\+{3}', ' ', line)
    parts = re.split(r'[,\s]+', cleaned)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        symbol = extract_symbol_from_text(part)
        if symbol and symbol not in coins:
            coins.append(symbol)
    
    return coins


def extract_coin_after_number(text: str, number: int) -> Optional[str]:
    """
    Extract coin symbol after numbered item (e.g., "1. **PEPE** - ...")
    """
    # Find text after the number
    pattern = rf'{number}\.\s*(.+?)(?:\n|$)'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    
    line = match.group(1)[:200]  # Limit to first 200 chars
    
    # Look for **...** pattern first
    bold_match = re.search(r'\*\*(.+?)\*\*', line)
    if bold_match:
        return extract_symbol_from_text(bold_match.group(1))
    
    # Fallback to first word/symbol
    return extract_symbol_from_text(line)
```

### Phase 2: Integration

Replace current extraction logic in `geminigroundlin15.py`:

```python
from coinextractor import extract_coin_after_number, extract_coins_from_social_line

# For numbered recommendations
coin1 = extract_coin_after_number(primary_response_text, 1)
coin2 = extract_coin_after_number(primary_response_text, 2)
coin3 = extract_coin_after_number(primary_response_text, 3)

# For social media section
social_text = get_text_after_delimiter(primary_response_text, "+++")
social_coins = extract_coins_from_social_line(social_text)
```

### Phase 3: Validation (Optional)

Add Coinbase API validation for unknown symbols:

```python
def validate_symbol(symbol: str, trader) -> bool:
    """Check if symbol is tradeable on Coinbase."""
    try:
        product = trader.get_product(f"{symbol}-USD")
        return product is not None and not product.get('is_disabled')
    except:
        return False
```

## Testing Matrix

| Input | Expected Output | Test Case |
|-------|-----------------|-----------|
| `**PEPE**` | `PEPE` | Simple bold symbol |
| `**dogwifhat (WIF)**` | `WIF` | Name with symbol |
| `**Bonk (BONK)**` | `BONK` | Capitalized name |
| `(over $490M)` | `None` | Noise rejection |
| `+++PEPE+++ +++DOGE+++` | `['PEPE', 'DOGE']` | Multiple markers |
| `+++FARTCOIN, dogwifhat (WIF)+++` | `['FARTCOIN', 'WIF']` | Comma-separated |
| `1. **PEPE** - text (over $490M)` | `PEPE` | Number with noise |

## Migration Plan

1. Create `coinextractor.py` module
2. Add unit tests for all observed formats
3. Replace extraction logic in `geminigroundlin15.py`
4. Add debug logging for extraction failures
5. Monitor production logs for new failure patterns
6. Expand `NAME_TO_SYMBOL` and `KNOWN_SYMBOLS` as needed

## Conclusion

### Recommendation: Hybrid Multi-Stage Pipeline (Option B6)

Implement **Option B6 (Hybrid Multi-Stage Pipeline)** via a dedicated `coinextractor.py` module. This provides:

- **Robustness** against LLM format variations
- **Maintainability** through centralized extraction logic
- **Extensibility** for new coins and formats
- **Debuggability** with clear failure modes

### Implementation Priority

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| 1 | Create `coinextractor.py` module | Medium | High |
| 2 | Add name-to-symbol mapping table | Low | High |
| 3 | Replace extraction logic in `geminigroundlin15.py` | Medium | High |
| 4 | Add Coinbase API validation (optional) | Low | Medium |
| 5 | Add unit tests for all observed formats | Low | Medium |

### Key Insight

**No single parsing strategy works for all LLM outputs.** A layered approach that tries multiple extraction strategies and validates results is essential for production reliability.

### Files to Modify

1. **New: `coinextractor.py`** - Centralized extraction with fallback chain
2. **`geminigroundlin15.py`** - Use new extractor module

### Future Consideration

If parsing issues persist after implementing the output-side solution, consider adding prompt engineering (Part A options) to improve LLM output consistency.
