# LLM Comparison Feature Design Document

## Overview

This document describes the design for adding Claude (Anthropic) as a secondary LLM to the trading bot, enabling comparison of cryptocurrency recommendations between Gemini and Claude.

## Goals

1. Send identical prompts to both Gemini and Claude
2. Parse and normalize responses from both LLMs
3. Compare recommendations and identify consensus/disagreement
4. Use consensus as a confidence signal for trading decisions

## Architecture

### New Components

#### 1. ClaudeClient Wrapper (`claudeutil.py`)

A wrapper module mirroring the existing Gemini client pattern:

- Initialize Anthropic client with API credentials from environment variables
- Expose methods matching the existing request functions:
  - `sendRecommendationRequest()`
  - `sendCoinCheckRequest(coin)`
  - `sendTrendCheckRequest(coin)`
- Use the `anthropic` Python SDK (similar to how `google-genai` is used)

#### 2. LLM Response Normalizer

A common interface to normalize responses from different LLMs:

- Extract coin symbols using existing `get_text_between_strings()` function
- Parse recommendation markers (`<**COIN-PRS-BUY**>`) consistently
- Return standardized recommendation objects

#### 3. Comparison Engine

Logic to compare and score recommendations:

- Match coins by symbol across both responses
- Compare BUY/SELL/HOLD recommendations
- Calculate agreement percentage
- Flag disagreements for review

## Environment Variables

Add new environment variables following existing pattern:

| Variable | Description |
|----------|-------------|
| `CLAUDE_API_KEY` | Anthropic API key |
| `GOOGLE_API_KEY` | Existing Gemini API key |
| `COINBASE_API_KEY` | Existing Coinbase API key |
| `COINBASE_API_SECRET` | Existing Coinbase API secret |

## Implementation Approach

### Phase 1: Claude Integration

1. Install `anthropic` package (add to requirements)
2. Create `claudeutil.py` module with:
   - `ClaudeTrader` class (similar pattern to `BlobbyTrader`)
   - API client initialization using `os.environ.get('CLAUDE_API_KEY')`
   - Content generation methods using Claude's `messages.create()` API

### Phase 2: Parallel Query Execution

Modify main script to:

1. Call both `sendRecommendationRequest()` functions (Gemini and Claude)
2. Use existing `pytrends` integration for both responses
3. Store results in parallel data structures

### Phase 3: Response Comparison

Create comparison logic:

```
For each coin recommendation:
    gemini_rec = parse_gemini_response(coin)
    claude_rec = parse_claude_response(coin)
    
    if gemini_rec == claude_rec:
        confidence = HIGH
    else:
        confidence = LOW
        log_disagreement(coin, gemini_rec, claude_rec)
```

### Phase 4: Trading Decision Integration

Modify `buy_something()` calls to consider:

- Only execute trades when both LLMs agree (conservative mode)
- Execute with position sizing based on agreement (proportional mode)
- Log all disagreements for analysis

## Prompt Consistency

Use identical prompts for both LLMs. The existing prompts will work with Claude:

- Initial recommendation request (3 meme coins)
- Coin check request (BUY/SELL/HOLD analysis)
- Trend check request (Google Trends integration)

The structured output format (`<**COIN-PRS-RECOMMENDATION**>`) works across both LLMs.

## Data Flow

```
                    ┌─────────────┐
                    │   Prompt    │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       ┌─────────────┐          ┌─────────────┐
       │   Gemini    │          │   Claude    │
       │  2.5 Pro    │          │  3.5 Sonnet │
       └──────┬──────┘          └──────┬──────┘
              │                         │
              ▼                         ▼
       ┌─────────────┐          ┌─────────────┐
       │   Parse &   │          │   Parse &   │
       │  Normalize  │          │  Normalize  │
       └──────┬──────┘          └──────┬──────┘
              │                         │
              └────────────┬────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Comparison │
                    │   Engine    │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Trading    │
                    │  Decision   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Coinbase   │
                    │   Execute   │
                    └─────────────┘
```

## Configuration Options

Add configuration flags (environment variables or config file):

| Option | Values | Description |
|--------|--------|-------------|
| `LLM_MODE` | `gemini`, `claude`, `compare` | Which LLM(s) to use |
| `REQUIRE_CONSENSUS` | `true`, `false` | Only trade on agreement |
| `LOG_DISAGREEMENTS` | `true`, `false` | Log when LLMs disagree |

## Error Handling

Follow existing patterns:

- Null checks for missing response content (already implemented)
- Try/except blocks around API calls
- Graceful degradation: if one LLM fails, use the other
- Print diagnostic messages for debugging

## Dependencies

Add to project requirements:

- `anthropic` - Anthropic Python SDK
- Existing: `google-genai`, `coinbase-advanced-py`, `pytrends`, `pandas`

## Testing Strategy

1. Unit test each LLM wrapper independently
2. Test response parsing with sample outputs
3. Test comparison logic with known inputs
4. Integration test with live API calls (using small position sizes)

## LLM Integration Mode

### Overview

A new mode called `integrate` where each LLM receives the other's output as additional context for its analysis. This creates a collaborative decision-making process rather than independent parallel analysis.

### How It Differs From Compare Mode

| Aspect | Compare Mode | Integration Mode |
|--------|--------------|------------------|
| Query order | Parallel/independent | Sequential (two rounds) |
| Context sharing | None | Each sees the other's output |
| Decision basis | Agreement between independent analyses | Informed analysis considering peer perspective |
| Goal | Consensus validation | Collaborative refinement |

### Data Flow

```
                         ┌─────────────┐
                         │   Prompt    │
                         └──────┬──────┘
                                │
               ┌────────────────┴────────────────┐
               │                                 │
               ▼                                 ▼
        ┌─────────────┐                   ┌─────────────┐
        │   Gemini    │                   │   Claude    │
        │  Round 1    │                   │  Round 1    │
        └──────┬──────┘                   └──────┬──────┘
               │                                 │
               ▼                                 ▼
        ┌─────────────┐                   ┌─────────────┐
        │  Response A │                   │  Response B │
        └──────┬──────┘                   └──────┬──────┘
               │                                 │
               └────────────┬────────────────────┘
                            │
               ┌────────────┴────────────────────┐
               │                                 │
               ▼                                 ▼
        ┌─────────────┐                   ┌─────────────┐
        │   Gemini    │                   │   Claude    │
        │  Round 2    │                   │  Round 2    │
        │ + Claude's  │                   │ + Gemini's  │
        │  Response B │                   │  Response A │
        └──────┬──────┘                   └──────┬──────┘
               │                                 │
               ▼                                 ▼
        ┌─────────────┐                   ┌─────────────┐
        │ Final Rec A'│                   │ Final Rec B'│
        └──────┬──────┘                   └──────┬──────┘
               │                                 │
               └────────────┬────────────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  Comparison │
                     │  & Decision │
                     └─────────────┘
```

### Integration Prompt Template

Round 2 prompts include the other LLM's analysis:

```
[Original prompt for coin analysis]

Additionally, consider the following analysis from another AI system:

---BEGIN PEER ANALYSIS---
{other_llm_response}
---END PEER ANALYSIS---

After reviewing the peer analysis, provide your final recommendation. 
You may agree, disagree, or refine your position based on this input.
Conclude with: <**COIN-PRS-BUY|SELL|HOLD**>
```

### Implementation Phases

#### Phase 1: Sequential Round 1 Queries
1. Send initial prompt to both Gemini and Claude
2. Collect and store both responses
3. Parse initial recommendations from each

#### Phase 2: Round 2 Cross-Feed
1. Construct Round 2 prompt for Gemini including Claude's Round 1 response
2. Construct Round 2 prompt for Claude including Gemini's Round 1 response
3. Send both Round 2 queries
4. Parse final recommendations

#### Phase 3: Final Decision
1. Compare Round 2 recommendations
2. If agreement: execute with high confidence
3. If disagreement: log the divergence, optionally use configurable tiebreaker

### Configuration

Update `LLM_MODE` to support the new mode:

| LLM_MODE Value | Behavior |
|----------------|----------|
| `gemini` | Gemini only |
| `claude` | Claude only |
| `compare` | Independent parallel queries, compare results |
| `integrate` | Two-round cross-feed, collaborative analysis |

Additional options for integration mode:

| Option | Values | Description |
|--------|--------|-------------|
| `INTEGRATION_TIEBREAKER` | `gemini`, `claude`, `none` | Which LLM wins on disagreement |
| `LOG_INTEGRATION_ROUNDS` | `true`, `false` | Log both round responses |

### Benefits

- **Reduced blind spots**: Each LLM can catch errors in the other's reasoning
- **Richer context**: LLMs can build on each other's insights
- **Transparent disagreement**: When LLMs still disagree after seeing each other's analysis, the disagreement is more meaningful
- **Self-correction**: LLMs may revise flawed initial recommendations

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Echo chamber (LLMs just agree with each other) | Monitor for flip rates and reasoning quality |
| Increased latency (4 API calls vs 2) | Make integration mode optional for time-sensitive trades |
| Higher API costs (2x token usage) | Track costs separately, allow budget limits |
| Prompt injection via peer response | Sanitize LLM outputs before cross-feeding |

### Metrics to Track

- **Flip rate**: How often does an LLM change its recommendation after seeing peer analysis?
- **Convergence rate**: How often do final recommendations agree vs Round 1?
- **Trade outcomes**: Compare PnL for integration mode vs compare mode vs single LLM

## Future Enhancements

- Add more LLMs (OpenAI GPT-4, Llama, etc.)
- Weight recommendations by historical accuracy
- Track and report agreement rates over time
- A/B test trading strategies (single LLM vs consensus)
- **Multi-round integration**: Allow more than 2 rounds of cross-feeding for complex decisions
- **Selective integration**: Only use integration mode when Round 1 shows disagreement

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| API rate limits | Implement retry logic with backoff |
| Increased latency | Parallel API calls using async/await |
| Higher API costs | Make comparison mode optional |
| Response format differences | Robust parsing with fallbacks |

## Success Metrics

- Reduction in losing trades when using consensus
- Improved accuracy compared to single-LLM approach
- Clear visibility into LLM agreement patterns
