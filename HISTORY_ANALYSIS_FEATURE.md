# History Analysis Feature Design Document

## Overview

This document describes the design for a recommendation history tracking system and a new "analysis" mode that evaluates past trading recommendations against actual price movements. This feature enables performance measurement of individual LLMs and comparison modes, helping identify which configurations produce the most accurate trading signals.

## Goals

1. Persist all trading recommendations with timestamps and context
2. Track price at time of recommendation for later comparison
3. Provide an "analysis" mode that evaluates historical accuracy
4. Generate performance metrics per LLM and per mode
5. Enable data-driven tuning of trading strategies

## Architecture

### 1. Recommendation History Store

A persistent storage layer for recording all recommendations:

- Timestamp of recommendation
- Coin symbol analyzed
- Price at time of recommendation
- Recommendation (BUY/SELL/HOLD)
- LLM(s) that made the recommendation
- Mode used (single, compare, integrate)
- Consensus status (if multi-LLM)
- Optional: Full LLM response text

### 2. Price Snapshot Service

A mechanism to capture and retrieve historical prices:

- Record price at recommendation time (including bid/ask spread)
- Fetch current price for comparison (Coinbase primary, CoinGecko fallback)
- Calculate price change percentage
- Support three time horizons: 24-hour, mid-term (3-6 days), and 7-day

### 3. Analysis Engine

Logic to evaluate recommendation accuracy:

- Compare recommendation to actual price movement
- Score each recommendation as correct/incorrect/neutral
- Aggregate statistics per LLM, mode, and coin
- Generate accuracy reports

## Data Model

### Recommendation Record

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique recommendation ID |
| `timestamp` | datetime | When recommendation was made |
| `coin_symbol` | string | Cryptocurrency symbol |
| `recommendation` | enum | BUY, SELL, or HOLD |
| `price_at_recommendation` | decimal | Price when recommendation made |
| `bid_price` | decimal | Bid price at recommendation time (for future use) |
| `ask_price` | decimal | Ask price at recommendation time (for future use) |
| `llm_source` | string | Which LLM(s) made this recommendation |
| `mode` | string | gemini, claude, openai, grok, perplexity, compare, integrate |
| `consensus` | boolean | Whether all LLMs agreed (multi-LLM modes) |

### Analysis Record

| Field | Type | Description |
|-------|------|-------------|
| `recommendation_id` | string | Links to recommendation |
| `analysis_timestamp` | datetime | When analysis was performed |
| `analysis_window` | string | "24h", "midterm", or "7d" |
| `current_price` | decimal | Price at analysis time |
| `price_change_percent` | decimal | Percentage change since recommendation |
| `outcome` | enum | CORRECT, INCORRECT, UNKNOWN |
| `outcome_display` | string | Formatted output (e.g., "Correct (+2%)") |

## Analysis Mode Behavior

### Mode Activation

Add `analysis` as a valid `LLM_MODE` value:

```
LLM_MODE=analysis
```

### Analysis Process

1. **24-hour window:** Find recommendations made 24-48 hours ago (days 1-2)
2. **Mid-term window:** Find recommendations made 2-7 days ago (48-168 hours)
3. **7-day window:** Find recommendations made 7-8 days ago (168-192 hours)
4. For each recommendation in scope:
   - Fetch current price from Coinbase (fallback: CoinGecko)
   - If price unavailable, mark as UNKNOWN
   - Calculate price change percentage since recommendation
   - Determine outcome based on recommendation type
   - Store analysis result
5. Generate console report
6. Export to CSV files

### Correctness Criteria

| Recommendation | Price Movement | Outcome | Display Example |
|----------------|----------------|---------|-----------------|
| BUY | Price increased | CORRECT | `DOGE, Buy, Correct (+2%)` |
| BUY | Price decreased | INCORRECT | `DOGE, Buy, Incorrect (-3%)` |
| SELL | Price decreased | CORRECT | `DOGE, Sell, Correct (+5%)` |
| SELL | Price increased | INCORRECT | `DOGE, Sell, Incorrect (-2%)` |
| HOLD | Any movement | (no judgment) | `DOGE, Hold, (+3%)` |
| ANY | Price unavailable | UNKNOWN | `DOGE, Buy, Unknown` |

**Note:** For HOLD recommendations, we report the price change but do not judge correctness.

### Report Output

Analysis mode should output:

1. **Per-Recommendation Details**
   - Coin, recommendation, price then vs now, outcome

2. **Per-LLM Statistics**
   - Total recommendations
   - Correct/Incorrect/Neutral counts
   - Accuracy percentage
   - Average return if followed

3. **Per-Mode Statistics**
   - Compare single vs compare vs integrate modes
   - Consensus vs non-consensus accuracy

4. **Overall Summary**
   - Best performing LLM
   - Best performing mode
   - Most accurately predicted coins

## Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `LLM_MODE` | `analysis` | - | Enable analysis mode (exclusive) |
| `HISTORY_DIR` | dirpath | `./history/` | Directory for history JSON files |
| `COINGECKO_API_KEY` | string | - | Optional CoinGecko API key for fallback pricing |

## Storage Structure

### Directory Layout

```
./history/
├── recommendations.json          # All recommendation records
├── analysis_24h_YYYYMMDD.csv     # 24-hour analysis results
├── analysis_midterm_YYYYMMDD.csv # Mid-term (3-6 day) analysis results
└── analysis_7d_YYYYMMDD.csv      # 7-day analysis results
```

### JSON Format (recommendations.json)

```json
{
  "recommendations": [
    {
      "id": "rec_20260410_001",
      "timestamp": "2026-04-10T12:30:00Z",
      "coin_symbol": "DOGE",
      "recommendation": "BUY",
      "price_at_recommendation": 0.1234,
      "bid_price": 0.1233,
      "ask_price": 0.1235,
      "llm_source": "gemini",
      "mode": "integrate",
      "consensus": true
    }
  ]
}
```

### CSV Format (analysis output)

```csv
timestamp,coin,recommendation,rec_price,current_price,change_pct,outcome,outcome_display
2026-04-08T12:30:00Z,DOGE,BUY,0.1234,0.1260,2.1%,CORRECT,"Correct (+2.1%)"
2026-04-08T14:15:00Z,SHIB,SELL,0.00001234,0.00001180,4.4%,CORRECT,"Correct (+4.4%)"
2026-04-08T16:45:00Z,BONK,HOLD,0.00002100,0.00002163,3.0%,,"(+3.0%)"
```

## Integration Points

### Recording Recommendations

Modify the main script to record after each recommendation:

1. After `process_coin_with_comparison` returns
2. Fetch current price and bid/ask spread from Coinbase
3. Create recommendation record with all fields
4. Append to `./history/recommendations.json`

### Running Analysis

When `LLM_MODE=analysis`:

1. Skip normal trading flow entirely (exclusive mode)
2. Load `./history/recommendations.json`
3. **24-hour window:** Find recs from 24-48 hours ago
4. **Mid-term window:** Find recs from 2-7 days ago
5. **7-day window:** Find recs from 7-8 days ago
6. For each recommendation:
   - Fetch current price (Coinbase, fallback CoinGecko)
   - Calculate price change
   - Determine outcome
7. Output console report
8. Export CSV files (`analysis_24h_YYYYMMDD.csv`, `analysis_midterm_YYYYMMDD.csv`, `analysis_7d_YYYYMMDD.csv`)

## Sample Console Output

```
=== TRADING BOT ANALYSIS REPORT ===
Generated: 2026-04-10 14:30:00 UTC

=== 24-HOUR ANALYSIS (recs from 24-48 hrs ago) ===
Recommendations found: 5

DOGE, Buy, Correct (+2.3%)
SHIB, Sell, Correct (+4.1%)
BONK, Hold, (+1.8%)
XRP, Buy, Incorrect (-3.2%)
SOL, Buy, Unknown (price unavailable)

--- 24-HOUR SUMMARY ---
BUY recommendations:  2 correct, 1 incorrect, 1 unknown (66.7% accuracy)
SELL recommendations: 1 correct, 0 incorrect (100.0% accuracy)
HOLD recommendations: 1 total (no judgment)

=== MID-TERM ANALYSIS (recs from 2-7 days ago) ===
Recommendations found: 6

DOGE, Buy, Correct (+5.2%)
SHIB, Sell, Correct (+3.8%)
PEPE, Buy, Incorrect (-2.1%)
ETH, Hold, (+1.5%)
BTC, Buy, Correct (+3.2%)
SOL, Buy, Correct (+4.1%)

--- MID-TERM SUMMARY ---
BUY recommendations:  3 correct, 1 incorrect (75.0% accuracy)
SELL recommendations: 1 correct, 0 incorrect (100.0% accuracy)
HOLD recommendations: 1 total (no judgment)

=== 7-DAY ANALYSIS (recs from 7-8 days ago) ===
Recommendations found: 8

DOGE, Buy, Correct (+12.5%)
SHIB, Buy, Correct (+8.3%)
PEPE, Sell, Incorrect (-15.2%)
ETH, Hold, (+2.1%)
BTC, Buy, Correct (+5.7%)
SOL, Sell, Correct (+7.8%)
BONK, Buy, Incorrect (-4.3%)
XRP, Hold, (-1.2%)

--- 7-DAY SUMMARY ---
BUY recommendations:  3 correct, 1 incorrect (75.0% accuracy)
SELL recommendations: 1 correct, 1 incorrect (50.0% accuracy)
HOLD recommendations: 2 total (no judgment)

=== OVERALL ACCURACY ===
BUY:  5 correct / 7 judged (71.4%)
SELL: 2 correct / 3 judged (66.7%)

CSV files written:
  ./history/analysis_24h_20260410.csv
  ./history/analysis_midterm_20260410.csv
  ./history/analysis_7d_20260410.csv
```

## Design Decisions

### Data Storage

1. **Storage format:** JSON
2. **Retention policy:** Forever (no rolling window)
3. **Store full LLM response text:** No
4. **History file location:** Subdirectory under project directory (`./history/`)

### Analysis Logic

5. **Time horizons:** 24-hour (1-2 days), mid-term (2-7 days), and 7-day (7-8 days) windows for continuous 8-day coverage
6. **Correctness reporting:** Report actual percentage change with outcome
   - Example BUY correct: `DOGE, Buy, Correct (+2%)`
   - Example SELL incorrect: `DOGE, Sell, Incorrect (-5%)`
7. **HOLD handling:** No judgment, just note the result
   - Example: `DOGE, Hold, (+3%)`
8. **Age weighting:** No weighting based on age of recommendation
9. **Delisted/unavailable coins:** Mark as UNKNOWN

### Price Data

10. **Price source:** Coinbase primary, CoinGecko as fallback
11. **Bid/ask spread:** Record for possible future use in reporting correctness
12. **Coins not on price source:** Mark as UNKNOWN

### Operational

13. **Analysis trigger:** On-demand only
14. **Alerts:** No alerts for MVP, but report overall accuracy at end of run (% correct/incorrect for BUY and SELL)
15. **Paper vs live trading:** Not tracked separately - tool runs as "what-if" analysis, useful even with no actual trades
16. **Mode exclusivity:** Analysis mode is exclusive, not combined with trading runs

### Reporting

17. **Output formats:** Console and CSV (CSV for post-processing and external analysis)
18. **External dashboards:** Not for MVP
19. **Report frequency:** Manual operation or external wrapper script (not part of MVP)
20. **Paper/live separation:** No

### Analysis Windows

21. **Time window logic:**
    - **24-hour analysis:** Find recommendations made 24-48 hours ago, compare to current price
    - **7-day analysis:** Find recommendations made 7-8 days ago, compare to current price
    - Each analysis compares one past recommendation to the present price
    - Trust/accuracy analysis comes from CSV analysis outside MVP scope

22. **Confidence intervals:** Not for MVP
23. **Overfitting prevention:** Not considered for MVP (no automated tuning)
24. **Backtesting:** Not for MVP

## Future Enhancements

1. **Automated Parameter Tuning**: Use historical accuracy to automatically adjust thresholds
2. **LLM Weighting**: Weight LLM votes based on historical accuracy
3. **Coin-Specific Models**: Track which LLMs are best for which coins
4. **Time-of-Day Analysis**: Identify optimal trading windows
5. **Visualization Dashboard**: Web UI for exploring historical performance
6. **Export to Spreadsheet**: Automated CSV/Excel export for external analysis
7. **Backtesting Mode**: Test strategies against historical price data
8. **Alert Integration**: Notify when accuracy drops or improves significantly

## Implementation Sketch

This feature consists of two separate components:

1. **Recorder** - Integrated into the trading bot to record recommendations as they occur
2. **Analyzer** - Standalone program (`tradeanalyzer.py`) to analyze historical accuracy

### Component Architecture

```
┌─────────────────────────────────┐
│   geminigroundlin15.py          │
│   (Trading Bot)                 │
│                                 │
│   Uses: historyutil.py          │
│   Writes: ./history/recommendations.json
└─────────────────────────────────┘
              │
              │ (records recommendations)
              ▼
┌─────────────────────────────────┐
│   ./history/                    │
│   └── recommendations.json      │
└─────────────────────────────────┘
              │
              │ (reads history)
              ▼
┌─────────────────────────────────┐
│   tradeanalyzer.py              │
│   (Standalone Analyzer)         │
│                                 │
│   Uses: historyutil.py          │
│         coingeckoutil.py        │
│         coinbaseutil2.py        │
│   Writes: ./history/analysis_*.csv
└─────────────────────────────────┘
```

### New Files

| File | Purpose |
|------|---------|
| `historyutil.py` | Shared utility for recording and loading history |
| `coingeckoutil.py` | CoinGecko fallback price fetcher |
| `tradeanalyzer.py` | **Standalone program** for analyzing recommendation accuracy |

---

## Component 1: Recorder (historyutil.py)

Shared utility used by the trading bot to record recommendations.

```python
import json
import os
from datetime import datetime
from typing import Optional, Dict, List

HISTORY_DIR = os.environ.get('HISTORY_DIR', './history/')
RECOMMENDATIONS_FILE = os.path.join(HISTORY_DIR, 'recommendations.json')

def ensure_history_dir():
    """Create history directory if it doesn't exist."""
    os.makedirs(HISTORY_DIR, exist_ok=True)

def load_recommendations() -> List[Dict]:
    """Load all recommendations from JSON file."""
    if not os.path.exists(RECOMMENDATIONS_FILE):
        return []
    with open(RECOMMENDATIONS_FILE, 'r') as f:
        data = json.load(f)
    return data.get('recommendations', [])

def save_recommendation(rec: Dict):
    """Append a recommendation to the history file."""
    ensure_history_dir()
    recs = load_recommendations()
    recs.append(rec)
    with open(RECOMMENDATIONS_FILE, 'w') as f:
        json.dump({'recommendations': recs}, f, indent=2)

def create_recommendation_record(
    coin_symbol: str,
    recommendation: str,
    price: float,
    bid_price: float,
    ask_price: float,
    llm_source: str,
    mode: str,
    consensus: Optional[bool] = None
) -> Dict:
    """Create a recommendation record with all required fields."""
    return {
        'id': f"rec_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{coin_symbol}",
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'coin_symbol': coin_symbol,
        'recommendation': recommendation,
        'price_at_recommendation': price,
        'bid_price': bid_price,
        'ask_price': ask_price,
        'llm_source': llm_source,
        'mode': mode,
        'consensus': consensus
    }
```

### Integration in geminigroundlin15.py

```python
# At top of file
from historyutil import save_recommendation, create_recommendation_record

# After process_coin_with_comparison returns and before buy_something()
if final_action:
    # Get current price and bid/ask from Coinbase
    product = trader.get_product_details(f"{coin_symbol}-USD")
    if product:
        price = float(product.price)
        bid = float(product.bid) if hasattr(product, 'bid') else price
        ask = float(product.ask) if hasattr(product, 'ask') else price
        
        rec_record = create_recommendation_record(
            coin_symbol=coin_symbol,
            recommendation=final_action,
            price=price,
            bid_price=bid,
            ask_price=ask,
            llm_source=PRIMARY_LLM,
            mode=LLM_MODE,
            consensus=all_agree if LLM_MODE in ['compare', 'integrate'] else None
        )
        save_recommendation(rec_record)
```

---

## Component 2: Analyzer (tradeanalyzer.py)

Standalone program that reads historical recommendations and compares to current prices.

### Usage

```bash
# Run analysis
python tradeanalyzer.py

# Output goes to console and CSV files
```

### tradeanalyzer.py

```python
#!/usr/bin/env python3
"""
Trade Analyzer - Standalone program to analyze recommendation accuracy.

Reads historical recommendations from ./history/recommendations.json
and compares to current prices to determine correctness.

Usage:
    python tradeanalyzer.py
"""

import csv
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

from historyutil import load_recommendations, HISTORY_DIR, ensure_history_dir
from coinbaseutil2 import BlobbyTrader

# Optional: CoinGecko fallback
try:
    from coingeckoutil import get_coingecko_price
    COINGECKO_AVAILABLE = True
except ImportError:
    COINGECKO_AVAILABLE = False


def get_current_price(coin_symbol: str, trader: BlobbyTrader) -> Optional[float]:
    """Get current price from Coinbase, fallback to CoinGecko."""
    # Try Coinbase first
    product = trader.get_product_details(f"{coin_symbol}-USD")
    if product and hasattr(product, 'price'):
        return float(product.price)
    
    # Fallback to CoinGecko
    if COINGECKO_AVAILABLE:
        return get_coingecko_price(coin_symbol)
    
    return None


def get_recommendations_in_window(recs: List[Dict], hours_ago_start: int, hours_ago_end: int) -> List[Dict]:
    """Get recommendations made within a time window.
    
    Args:
        recs: List of recommendation records
        hours_ago_start: Start of window (e.g., 24 means "24 hours ago")
        hours_ago_end: End of window (e.g., 48 means "48 hours ago")
    
    Returns:
        Recommendations made between hours_ago_end and hours_ago_start
    """
    now = datetime.utcnow()
    window_start = now - timedelta(hours=hours_ago_end)
    window_end = now - timedelta(hours=hours_ago_start)
    
    result = []
    for rec in recs:
        rec_time = datetime.fromisoformat(rec['timestamp'].replace('Z', ''))
        if window_start <= rec_time <= window_end:
            result.append(rec)
    return result


def calculate_outcome(recommendation: str, price_change_pct: float) -> Tuple[str, str]:
    """Determine outcome and display string for a recommendation."""
    sign = '+' if price_change_pct >= 0 else ''
    pct_str = f"{sign}{price_change_pct:.1f}%"
    
    if recommendation == 'HOLD':
        return ('', f"({pct_str})")
    elif recommendation == 'BUY':
        outcome = 'CORRECT' if price_change_pct > 0 else 'INCORRECT'
        return (outcome, f"{outcome.capitalize()} ({pct_str})")
    elif recommendation == 'SELL':
        outcome = 'CORRECT' if price_change_pct < 0 else 'INCORRECT'
        return (outcome, f"{outcome.capitalize()} ({pct_str})")
    return ('UNKNOWN', 'Unknown')


def analyze_recommendations(recs: List[Dict], trader: BlobbyTrader) -> List[Dict]:
    """Analyze a list of recommendations against current prices."""
    results = []
    
    for rec in recs:
        coin = rec['coin_symbol']
        rec_price = rec['price_at_recommendation']
        recommendation = rec['recommendation']
        
        current_price = get_current_price(coin, trader)
        
        if current_price is None:
            outcome = 'UNKNOWN'
            outcome_display = 'Unknown (price unavailable)'
            change_pct = 0.0
        else:
            change_pct = ((current_price - rec_price) / rec_price) * 100
            outcome, outcome_display = calculate_outcome(recommendation, change_pct)
        
        results.append({
            'timestamp': rec['timestamp'],
            'coin': coin,
            'recommendation': recommendation,
            'rec_price': rec_price,
            'current_price': current_price,
            'change_pct': f"{change_pct:.1f}%",
            'outcome': outcome,
            'outcome_display': outcome_display
        })
        
        # Print each result
        print(f"{coin}, {recommendation.capitalize()}, {outcome_display}")
    
    return results


def export_to_csv(results: List[Dict], filename: str):
    """Export analysis results to CSV file."""
    ensure_history_dir()
    filepath = os.path.join(HISTORY_DIR, filename)
    fieldnames = ['timestamp', 'coin', 'recommendation', 'rec_price', 
                  'current_price', 'change_pct', 'outcome', 'outcome_display']
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    return filepath


def print_summary(results: List[Dict], window_name: str):
    """Print summary statistics for a set of results."""
    buy_correct = sum(1 for r in results if r['recommendation'] == 'BUY' and r['outcome'] == 'CORRECT')
    buy_incorrect = sum(1 for r in results if r['recommendation'] == 'BUY' and r['outcome'] == 'INCORRECT')
    buy_unknown = sum(1 for r in results if r['recommendation'] == 'BUY' and r['outcome'] == 'UNKNOWN')
    
    sell_correct = sum(1 for r in results if r['recommendation'] == 'SELL' and r['outcome'] == 'CORRECT')
    sell_incorrect = sum(1 for r in results if r['recommendation'] == 'SELL' and r['outcome'] == 'INCORRECT')
    
    hold_total = sum(1 for r in results if r['recommendation'] == 'HOLD')
    
    buy_judged = buy_correct + buy_incorrect
    sell_judged = sell_correct + sell_incorrect
    
    print(f"\n--- {window_name} SUMMARY ---")
    if buy_judged > 0:
        accuracy = 100 * buy_correct / buy_judged
        print(f"BUY recommendations:  {buy_correct} correct, {buy_incorrect} incorrect, {buy_unknown} unknown ({accuracy:.1f}% accuracy)")
    else:
        print("BUY recommendations:  None in window")
    
    if sell_judged > 0:
        accuracy = 100 * sell_correct / sell_judged
        print(f"SELL recommendations: {sell_correct} correct, {sell_incorrect} incorrect ({accuracy:.1f}% accuracy)")
    else:
        print("SELL recommendations: None in window")
    
    if hold_total > 0:
        print(f"HOLD recommendations: {hold_total} total (no judgment)")
    
    return buy_correct, buy_incorrect, sell_correct, sell_incorrect


def main():
    """Main entry point for trade analyzer."""
    print("=== TRADING BOT ANALYSIS REPORT ===")
    print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    # Initialize Coinbase client for price fetching
    try:
        trader = BlobbyTrader()
    except Exception as e:
        print(f"Warning: Could not initialize Coinbase client: {e}")
        print("Price fetching may be limited.")
        trader = None
    
    # Load all recommendations
    all_recs = load_recommendations()
    if not all_recs:
        print("\nNo recommendations found in history.")
        print(f"Expected file: {HISTORY_DIR}recommendations.json")
        return
    
    print(f"\nTotal recommendations in history: {len(all_recs)}")
    
    # Track overall stats
    total_buy_correct = 0
    total_buy_incorrect = 0
    total_sell_correct = 0
    total_sell_incorrect = 0
    
    # 24-hour analysis (recs from 24-48 hours ago)
    print("\n" + "="*50)
    print("=== 24-HOUR ANALYSIS (recs from 24-48 hrs ago) ===")
    recs_24h = get_recommendations_in_window(all_recs, 24, 48)
    print(f"Recommendations found: {len(recs_24h)}\n")
    
    if recs_24h:
        results_24h = analyze_recommendations(recs_24h, trader)
        bc, bi, sc, si = print_summary(results_24h, "24-HOUR")
        total_buy_correct += bc
        total_buy_incorrect += bi
        total_sell_correct += sc
        total_sell_incorrect += si
        
        csv_24h = export_to_csv(results_24h, f"analysis_24h_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    else:
        print("No recommendations in this window.")
        csv_24h = None
    
    # 7-day analysis (recs from 7-8 days ago)
    print("\n" + "="*50)
    print("=== 7-DAY ANALYSIS (recs from 7-8 days ago) ===")
    recs_7d = get_recommendations_in_window(all_recs, 168, 192)  # 7*24=168, 8*24=192
    print(f"Recommendations found: {len(recs_7d)}\n")
    
    if recs_7d:
        results_7d = analyze_recommendations(recs_7d, trader)
        bc, bi, sc, si = print_summary(results_7d, "7-DAY")
        total_buy_correct += bc
        total_buy_incorrect += bi
        total_sell_correct += sc
        total_sell_incorrect += si
        
        csv_7d = export_to_csv(results_7d, f"analysis_7d_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    else:
        print("No recommendations in this window.")
        csv_7d = None
    
    # Overall accuracy
    print("\n" + "="*50)
    print("=== OVERALL ACCURACY ===")
    
    total_buy = total_buy_correct + total_buy_incorrect
    total_sell = total_sell_correct + total_sell_incorrect
    
    if total_buy > 0:
        print(f"BUY:  {total_buy_correct} correct / {total_buy} judged ({100*total_buy_correct/total_buy:.1f}%)")
    if total_sell > 0:
        print(f"SELL: {total_sell_correct} correct / {total_sell} judged ({100*total_sell_correct/total_sell:.1f}%)")
    
    # Report CSV files
    print("\nCSV files written:")
    if csv_24h:
        print(f"  {csv_24h}")
    if csv_7d:
        print(f"  {csv_7d}")


if __name__ == "__main__":
    main()
```

## Dependencies

Additions to `requirements.txt`:

```
pycoingecko>=3.0.0  # CoinGecko fallback pricing
```

## Success Metrics

- Ability to identify best-performing LLM configuration
- Measurable improvement in trading accuracy over time
- Data-driven confidence in recommendation quality
- Reduced losses from following poor recommendations
