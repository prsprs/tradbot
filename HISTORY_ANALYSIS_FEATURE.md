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

- Record price at recommendation time
- Fetch current price for comparison
- Calculate price change percentage
- Support multiple time horizons (1h, 4h, 24h, 7d)

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
| `llm_source` | string | Which LLM(s) made this recommendation |
| `mode` | string | gemini, claude, openai, grok, perplexity, compare, integrate |
| `consensus` | boolean | Whether all LLMs agreed (multi-LLM modes) |
| `confidence` | string | Optional confidence indicator |
| `response_text` | text | Optional full LLM response |
| `evaluated` | boolean | Whether this has been analyzed |

### Analysis Record

| Field | Type | Description |
|-------|------|-------------|
| `recommendation_id` | string | Links to recommendation |
| `analysis_timestamp` | datetime | When analysis was performed |
| `current_price` | decimal | Price at analysis time |
| `price_change_percent` | decimal | Percentage change since recommendation |
| `time_elapsed` | interval | Time since recommendation |
| `outcome` | enum | CORRECT, INCORRECT, NEUTRAL |
| `notes` | text | Optional analysis notes |

## Analysis Mode Behavior

### Mode Activation

Add `analysis` as a valid `LLM_MODE` value:

```
LLM_MODE=analysis
```

### Analysis Process

1. Load all unevaluated recommendations from history
2. For each recommendation:
   - Fetch current price from Coinbase API
   - Calculate price change since recommendation
   - Determine if recommendation was correct
   - Store analysis result
3. Generate summary report

### Correctness Criteria

| Recommendation | Price Movement | Outcome |
|----------------|----------------|---------|
| BUY | Price increased ≥ X% | CORRECT |
| BUY | Price decreased ≥ Y% | INCORRECT |
| BUY | Price within ±Z% | NEUTRAL |
| SELL | Price decreased ≥ X% | CORRECT |
| SELL | Price increased ≥ Y% | INCORRECT |
| SELL | Price within ±Z% | NEUTRAL |
| HOLD | Price within ±W% | CORRECT |
| HOLD | Price moved ≥ W% either direction | INCORRECT |

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
| `LLM_MODE` | `analysis` | - | Enable analysis mode |
| `HISTORY_FILE` | filepath | `recommendation_history.json` | Where to store history |
| `ANALYSIS_THRESHOLD_BUY` | percentage | `2.0` | Min % gain for BUY to be correct |
| `ANALYSIS_THRESHOLD_SELL` | percentage | `2.0` | Min % drop for SELL to be correct |
| `ANALYSIS_NEUTRAL_BAND` | percentage | `1.0` | Range considered neutral |
| `ANALYSIS_LOOKBACK_HOURS` | integer | `24` | How far back to analyze |

## Storage Options

### Option A: JSON File

Simple flat file storage:
- Easy to implement
- Human readable
- No dependencies
- Limited query capability

### Option B: SQLite Database

Embedded relational database:
- Structured queries
- Better for large history
- Single file, no server
- Requires schema management

### Option C: CSV File

Spreadsheet-compatible format:
- Easy to export/analyze externally
- Append-only writes
- Can open in Excel/Sheets
- Limited querying

## Integration Points

### Recording Recommendations

Modify the main script to record after each recommendation:

1. After `process_coin_with_comparison` returns
2. Fetch current price from Coinbase
3. Create recommendation record
4. Append to history store

### Running Analysis

When `LLM_MODE=analysis`:

1. Skip normal recommendation flow
2. Load history store
3. Run analysis engine
4. Output report
5. Mark records as evaluated

## Sample Report Format

```
=== TRADING BOT ANALYSIS REPORT ===
Generated: 2026-04-04 11:30:00 UTC
Analysis Period: Last 24 hours
Recommendations Analyzed: 47

--- PER-LLM ACCURACY ---
| LLM        | Total | Correct | Incorrect | Neutral | Accuracy |
|------------|-------|---------|-----------|---------|----------|
| Gemini     | 12    | 8       | 2         | 2       | 80.0%    |
| Claude     | 12    | 7       | 3         | 2       | 70.0%    |
| OpenAI     | 8     | 5       | 2         | 1       | 71.4%    |
| Grok       | 8     | 6       | 1         | 1       | 85.7%    |
| Perplexity | 7     | 4       | 2         | 1       | 66.7%    |

--- PER-MODE ACCURACY ---
| Mode      | Total | Correct | Accuracy | Avg Return |
|-----------|-------|---------|----------|------------|
| Single    | 20    | 13      | 65.0%    | +1.2%      |
| Compare   | 15    | 11      | 73.3%    | +2.1%      |
| Integrate | 12    | 10      | 83.3%    | +3.4%      |

--- CONSENSUS ANALYSIS ---
| Consensus | Total | Correct | Accuracy |
|-----------|-------|---------|----------|
| Yes       | 18    | 15      | 83.3%    |
| No        | 9     | 4       | 44.4%    |

--- BEST PERFORMERS ---
Most Accurate LLM: Grok (85.7%)
Most Accurate Mode: Integrate (83.3%)
Best Coin Predictions: DOGE (90%), SHIB (85%)

--- RECOMMENDATIONS ---
- Consider weighting Grok recommendations higher
- Integrate mode outperforms single LLM queries
- Consensus recommendations are significantly more reliable
- Avoid trading when LLMs disagree (44% accuracy)
```

## Open Questions

### Data Storage

1. **Which storage format should we use?** JSON is simplest but SQLite offers better querying. What's the expected volume of recommendations?

2. **How long should we retain history?** Forever? Rolling window? Configurable?

3. **Should we store full LLM response text?** Useful for debugging but increases storage significantly.

4. **Where should the history file live?** Project directory? User home? Configurable path?

### Analysis Logic

5. **What time horizons matter most?** Should we evaluate at 1h, 4h, 24h, 7d? All of them?

6. **What percentage thresholds define "correct"?** Is 2% gain enough to call a BUY correct? Should this vary by coin volatility?

7. **How do we handle HOLD recommendations?** What price range counts as "correctly held"?

8. **Should we weight recent recommendations more heavily?** Or treat all history equally?

9. **How do we account for coins that were delisted or unavailable?** Skip them? Mark as unknown?

### Price Data

10. **Which price source should we use?** Coinbase API? CoinGecko? Multiple sources?

11. **Should we record bid/ask spread or just mid price?** Spread affects real trading accuracy.

12. **How do we handle coins not available on our price source?** Some meme coins may not be listed everywhere.

### Operational

13. **Should analysis run automatically after each session?** Or only on-demand?

14. **Should we generate alerts when accuracy drops below a threshold?**

15. **How do we handle recommendations that led to actual trades vs. skipped ones?** Track separately?

16. **Should analysis mode be mutually exclusive with trading?** Or can we analyze while also generating new recommendations?

### Reporting

17. **What output formats do we need?** Console, JSON, CSV, HTML?

18. **Should we integrate with external dashboards or monitoring tools?**

19. **How often should we regenerate the analysis report?**

20. **Should we track and report on "paper trading" vs. "live trading" separately?**

### Statistical Rigor

21. **What's the minimum sample size before we trust accuracy numbers?** 10 recommendations? 50? 100?

22. **Should we calculate confidence intervals on accuracy metrics?**

23. **How do we avoid overfitting if we tune thresholds based on historical performance?**

24. **Should we implement backtesting against older price data?**

## Future Enhancements

1. **Automated Parameter Tuning**: Use historical accuracy to automatically adjust thresholds
2. **LLM Weighting**: Weight LLM votes based on historical accuracy
3. **Coin-Specific Models**: Track which LLMs are best for which coins
4. **Time-of-Day Analysis**: Identify optimal trading windows
5. **Visualization Dashboard**: Web UI for exploring historical performance
6. **Export to Spreadsheet**: Automated CSV/Excel export for external analysis
7. **Backtesting Mode**: Test strategies against historical price data
8. **Alert Integration**: Notify when accuracy drops or improves significantly

## Dependencies

Potential additions to `requirements.txt`:

- Database driver (if using SQLite beyond stdlib)
- Price API client (if not using existing Coinbase integration)
- Reporting/charting library (optional)

## Success Metrics

- Ability to identify best-performing LLM configuration
- Measurable improvement in trading accuracy over time
- Data-driven confidence in recommendation quality
- Reduced losses from following poor recommendations
