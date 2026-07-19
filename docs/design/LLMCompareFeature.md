> **⚠️ SUPERSEDED — see [README_LLM_COMPARE.md](../../README_LLM_COMPARE.md)
> and [LLM_COMPARE_OPERATIONS_MANUAL.md](../../LLM_COMPARE_OPERATIONS_MANUAL.md)
> for current behavior.** This design doc predates the shipped feature: it
> describes a 2-LLM (Gemini/Claude) design, but the current tool runs all
> five providers, and it hardcodes retired/placeholder model IDs. For the
> current model roster and IDs see `modelregistry.py` /
> [MODELS.md](../../MODELS.md), the single source of truth.

# LLM Comparison Feature Design Document

## Overview

This document describes the design for multi-LLM support in the trading bot, enabling comparison of cryptocurrency recommendations across five LLM providers: Google Gemini, Anthropic Claude, OpenAI GPT, xAI Grok, and Perplexity AI.

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
  - `send_recommendation_request()`
  - `send_coin_check_request(coin)`
  - `send_trend_check_request(coin)`
  - `send_integrated_coin_check(coin, peer_analysis)` - Round 2 integration
  - `send_integrated_trend_check(coin, peer_analysis)` - Round 2 integration
- Uses the `anthropic` Python SDK
- Model: see `modelregistry.py` / [MODELS.md](../../MODELS.md) for the current, live model ID (the ID formerly listed here, `claude-sonnet-4-20250514`, is retired — see MODELS.md's migration history)

#### 2. OpenAIClient Wrapper (`openaiutil.py`)

A wrapper module for OpenAI GPT models:

- Initialize OpenAI client with API credentials from environment variables
- Expose methods matching the existing request functions:
  - `send_recommendation_request()`
  - `send_coin_check_request(coin)`
  - `send_trend_check_request(coin)`
  - `send_integrated_coin_check(coin, peer_analysis)` - Round 2 integration
  - `send_integrated_trend_check(coin, peer_analysis)` - Round 2 integration
- Uses the `openai` Python SDK
- Model: `gpt-4o`

#### 3. GrokClient Wrapper (`grokutil.py`)

A wrapper module for xAI Grok models with real-time X (Twitter) data access:

- Initialize via OpenAI-compatible API with xAI base URL
- Real-time social sentiment from X platform
- Expose standard trading request methods
- Uses `openai` SDK with `base_url="https://api.x.ai/v1"`
- Model: `grok-2-latest`

#### 4. PerplexityClient Wrapper (`perplexityutil.py`)

A wrapper module for Perplexity AI with built-in web search:

- Initialize via OpenAI-compatible API with Perplexity base URL
- **Live web search** built into every query - no separate API needed
- Real-time market data and news in responses
- Uses `openai` SDK with `base_url="https://api.perplexity.ai"`
- Model: `sonar-pro`

#### 5. LLM Response Normalizer

A common interface to normalize responses from different LLMs:

- Extract coin symbols using existing `get_text_between_strings()` function
- Parse recommendation markers (`<**COIN-PRS-BUY**>`) consistently
- Return standardized recommendation objects

#### 6. Comparison Engine

Logic to compare and score recommendations:

- Match coins by symbol across both responses
- Compare BUY/SELL/HOLD recommendations
- Calculate agreement percentage
- Flag disagreements for review

## Environment Variables

### API Keys

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google Gemini API key |
| `CLAUDE_API_KEY` | Anthropic Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `XAI_API_KEY` | xAI Grok API key |
| `PERPLEXITY_API_KEY` | Perplexity AI API key |
| `COINBASE_API_KEY` | Coinbase API key |
| `COINBASE_API_SECRET` | Coinbase API secret |

### LLM Configuration

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `LLM_MODE` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `compare`, `integrate` | `compare` | Which mode to use |
| `PRIMARY_LLM` | `gemini`, `claude`, `openai`, `grok`, `perplexity` | `gemini` | LLM for discovery and first analysis (compare/integrate modes) |
| `COMPARE_LLMS` | Comma-separated list | `gemini,claude` | Which LLMs to include in compare/integrate modes |
| `REQUIRE_CONSENSUS` | `true`, `false` | `true` | Only trade when all LLMs agree |
| `INTEGRATION_TIEBREAKER` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `none` | `gemini` | Which LLM wins on disagreement |
| `LOG_INTEGRATION_ROUNDS` | `true`, `false` | `true` | Log detailed round responses |

## Supported Models

| Provider | Model | Wrapper Module | Special Features |
|----------|-------|----------------|------------------|
| Google | `gemini-2.5-pro` | Built into main script | Google Search grounding |
| Anthropic | see `modelregistry.py` / [MODELS.md](../../MODELS.md) (retired: `claude-sonnet-4-20250514`) | `claudeutil.py` | Strong reasoning |
| OpenAI | `gpt-4o` | `openaiutil.py` | Multimodal capabilities |
| xAI | `grok-3` | `grokutil.py` | Real-time X/Twitter data |
| Perplexity | `sonar-pro` | `perplexityutil.py` | Built-in live web search |

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
       │   Gemini    │          │   Claude    │          │   OpenAI    │
       │  2.5 Pro    │          │   Sonnet    │          │   GPT-4o    │
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

## Primary LLM Selection

### Overview

The trading bot uses a **two-stage flow** for coin analysis:

1. **Discovery Stage**: An LLM generates initial coin recommendations
2. **Analysis Stage**: Each coin is analyzed with trend/market data

Currently, Gemini is hardwired as the primary LLM for both stages. This section describes how to make the primary LLM configurable.

### Current Behavior (Hardwired)

```
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 1: DISCOVERY                       │
│                                                             │
│   sendRecommendationRequest() ──► Gemini ──► 3 coin picks  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 2: ANALYSIS                        │
│                                                             │
│   For each coin:                                            │
│     1. Gemini trend/coin check (always runs first)          │
│     2. process_coin_with_comparison() runs other LLMs       │
│     3. Compare/integrate based on LLM_MODE                  │
└─────────────────────────────────────────────────────────────┘
```

This means Gemini is always queried, even when `LLM_MODE=grok` or another single-LLM mode.

### Proposed Behavior (Configurable Primary)

Add a new environment variable `PRIMARY_LLM` to control which LLM handles discovery and first analysis:

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `PRIMARY_LLM` | `gemini`, `claude`, `openai`, `grok`, `perplexity` | `gemini` | LLM for discovery and first analysis |

### Execution Flow with Primary LLM

```
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 1: DISCOVERY                       │
│                                                             │
│   PRIMARY_LLM.send_recommendation_request()                 │
│      │                                                      │
│      ├── If gemini: sendRecommendationRequest()             │
│      ├── If claude: claude_trader.send_recommendation_...   │
│      ├── If openai: openai_trader.send_recommendation_...   │
│      ├── If grok: grok_trader.send_recommendation_...       │
│      └── If perplexity: perplexity_trader.send_recomm...    │
│                                                             │
│   Result: 3 coin picks from PRIMARY_LLM                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    STAGE 2: ANALYSIS                        │
│                                                             │
│   For each coin:                                            │
│     1. PRIMARY_LLM trend/coin check (runs first)            │
│     2. process_coin_with_comparison() handles mode logic:   │
│        - Single mode: return PRIMARY_LLM result             │
│        - Compare/Integrate: query other LLMs in COMPARE_LLMS│
│     3. Final decision based on configured mode              │
└─────────────────────────────────────────────────────────────┘
```

### Mode Interactions

| LLM_MODE | PRIMARY_LLM | Behavior |
|----------|-------------|----------|
| `gemini` | (ignored) | Gemini only |
| `claude` | (ignored) | Claude only |
| `openai` | (ignored) | OpenAI only |
| `grok` | (ignored) | Grok only |
| `perplexity` | (ignored) | Perplexity only |
| `compare` | `grok` | Grok discovers coins, then all COMPARE_LLMS analyze |
| `integrate` | `claude` | Claude discovers coins, then Round 1 + Round 2 integration |

**Note**: In single-LLM modes (`gemini`, `claude`, etc.), the `PRIMARY_LLM` setting is ignored—the mode itself determines which LLM to use exclusively.

### Benefits

1. **Real-time discovery**: Use Grok or Perplexity as primary to leverage their real-time data for initial coin picks
2. **Cost optimization**: Use a cheaper LLM for discovery, premium LLMs for analysis
3. **A/B testing**: Compare performance when different LLMs lead the discovery
4. **Flexibility**: Adapt to API outages by switching primary

### Implementation Notes

1. Each LLM wrapper must implement `send_recommendation_request()` that returns coins in a parseable format
2. The response parsing logic (`get_text_after_delimiter`, `get_text_between_strings`) must work with all LLM response formats
3. Consider standardizing the recommendation output format across all LLMs
4. The primary LLM should always be included in `COMPARE_LLMS` for compare/integrate modes

## Error Handling

Follow existing patterns:

- Null checks for missing response content (already implemented)
- Try/except blocks around API calls
- Graceful degradation: if one LLM fails, use the other
- Print diagnostic messages for debugging

## Dependencies

Project requirements:

- `anthropic` - Anthropic Python SDK
- `openai` - OpenAI Python SDK (also used for Grok and Perplexity via compatible API)
- `google-genai` - Google Generative AI SDK
- `coinbase-advanced-py` - Coinbase trading API
- `pytrends` - Google Trends API
- `pandas` - Data manipulation

**Note:** Grok and Perplexity use the OpenAI SDK with custom base URLs, so no additional packages are required.

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
| `openai` | OpenAI only |
| `grok` | Grok only (with X/Twitter sentiment) |
| `perplexity` | Perplexity only (with live web search) |
| `compare` | Independent queries to LLMs in COMPARE_LLMS, compare results |
| `integrate` | Two-round cross-feed with LLMs in COMPARE_LLMS |

Additional options:

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `COMPARE_LLMS` | Comma-separated | `gemini,claude` | LLMs to use in compare/integrate modes |
| `INTEGRATION_TIEBREAKER` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `none` | `gemini` | Which LLM wins on disagreement |
| `LOG_INTEGRATION_ROUNDS` | `true`, `false` | `true` | Log both round responses |

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

- Add more LLMs (Llama, Mistral, etc.)
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
