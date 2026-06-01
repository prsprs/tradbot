# General Purpose LLM Compare and Integrate Feature

## Overview

This document describes the design for a general-purpose Python program that leverages multiple LLMs to evaluate questions, make predictions, and provide recommendations through comparison and integration of diverse AI perspectives. The architecture is derived from the crypto trading bot but abstracted for broad applicability.

The core insight: **Different LLMs have different training data, reasoning approaches, and biases. By systematically comparing and integrating their outputs, we can achieve more robust, well-reasoned conclusions than any single LLM provides alone.**

## Use Cases

### Decision Support
- "Should I accept Job Offer A or Job Offer B?"
- "Would it be wise to buy an electric vehicle given current and possible future negative influences on the EV industry?"
- "Should our company adopt Kubernetes or stay with traditional VM deployment?"

### Predictions
- "Will the current US president be re-elected?"
- "Will interest rates decrease in the next 6 months?"
- "Will Company X's stock price increase after their earnings report?"

### Analysis
- "What are the primary risks of investing in commercial real estate in 2026?"
- "Is remote work likely to remain prevalent or will office mandates return?"

### Recommendations
- "Which programming language should I learn next: Rust, Go, or Zig?"
- "What is the best approach to reduce technical debt in a legacy codebase?"

## Architecture

### Core Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                               │
│  - Prompt/Question                                               │
│  - Mode (compare/integrate)                                      │
│  - LLMs to use                                                   │
│  - Optional: Google Trends keyword, choices list                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CONTEXT GATHERING (Optional)                  │
│  - Google Trends data (if GOOGLE_TRENDS_KEYWORD set)            │
│  - Web search results (future enhancement)                       │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ROUND 1: INDEPENDENT ANALYSIS                │
│  Each LLM receives:                                              │
│  - The user's prompt                                             │
│  - Any gathered context (trends, search results)                 │
│  - Instructions for structured output                            │
│  Each LLM responds independently (no cross-contamination)        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │   MODE = 'compare'?   │
                    └───────────┬───────────┘
                          │           │
                         YES          NO (integrate)
                          │           │
                          ▼           ▼
┌─────────────────────────────┐  ┌─────────────────────────────────┐
│      COMPARE MODE           │  │        INTEGRATE MODE            │
│  - Collect all responses    │  │  Round 2: Cross-Pollination      │
│  - Check for agreement      │  │  - Each LLM sees peer analyses   │
│  - Report consensus or      │  │  - Each may revise position      │
│    differences              │  │  - Track "flips" in opinion      │
│  - Use PRIMARY_LLM if no    │  │  Round 2 Complete:               │
│    consensus                │  │  - Check for consensus           │
└─────────────────────────────┘  │  - Use TIEBREAKER if needed      │
                                 └─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        OUTPUT & RECORDING                        │
│  - Display final recommendation with reasoning                   │
│  - Record to recommendations.json                                │
│  - Include all LLM responses for audit                           │
└─────────────────────────────────────────────────────────────────┘
```

## Parameter Classification

### Relevant Parameters (Carry Over)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MODE` | Operating mode: `single`, `compare`, `integrate` | `single` |
| `PRIMARY_LLM` | Primary LLM for single mode or tiebreaker | `gemini` |
| `COMPARE_LLMS` | Comma-separated list of LLMs to use | `gemini,claude,openai,grok,perplexity` |
| `INTEGRATION_TIEBREAKER` | Which LLM breaks ties in integrate mode | `gemini` |
| `LOG_INTEGRATION_ROUNDS` | Log full responses from each round | `false` |

### New Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `PROMPT` | The question or decision to evaluate | *required* |
| `PROMPT_FILE` | Path to file containing prompt (alternative to PROMPT) | `None` |
| `REFERENCE_FILES` | Comma-separated list of file paths to include as context | `None` |
| `YES_NO_EVAL` | If "YES", prompt must be a Yes/No question with structured YES/NO/UNKNOWN output | `NO` |
| `REQUIRE_CONSENSUS` | For YES_NO_EVAL=YES: require LLM consensus for final answer | `false` |
| `SIMPLE_INTEGRATION` | If "YES", only integrate primary LLM output (cost reduction) | `NO` |
| `SUMMARIZATION_LLM` | LLM to use for final summarization phase | `gemini` |
| `GOOGLE_TRENDS_KEYWORD` | Keyword for Google Trends context | `None` |
| `OUTPUT_FORMAT` | Output format: `text`, `json`, `markdown` | `text` |
| `HISTORY_FILE` | Path to recommendations history file | `./history/recommendations.json` |

### Cost Control Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MAX_RESPONSE_WORDS` | Request LLMs limit responses to this word count | `300` |
| `ROUND_TWO_OUTPUT_LIMIT` | Word limit specifically for Round 2 integration responses | `200` |
| `MAX_REASONING_POINTS` | Maximum reasoning bullet points to request | `3` |
| `SUMMARIZATION_MAX_WORDS` | Word limit for final summarization | `500` |
| `VERBOSE_MODE` | If "YES", ignore word limits for detailed output | `NO` |
| `WHAT_IF_MODE` | If "YES", estimate cost without making LLM calls | `NO` |

### Deprecated Parameters (Crypto-Specific)

| Parameter | Reason Not Relevant |
|-----------|---------------------|
| `ANALYZE_COINS` | Specific to cryptocurrency trading |
| `USE_COIN_DISCOVERY` | Specific to cryptocurrency trading |
| `EXECUTE_TRADES` | No trades to execute in general purpose |
| Coinbase API credentials | No trading integration |

### API Credentials (Required)

| Credential | LLM | Environment Variable |
|------------|-----|---------------------|
| Google Gemini | Gemini | `GOOGLE_API_KEY` |
| Anthropic | Claude | `ANTHROPIC_API_KEY` |
| OpenAI | GPT-4 | `OPENAI_API_KEY` |
| xAI | Grok | `XAI_API_KEY` |
| Perplexity | Perplexity | `PERPLEXITY_API_KEY` |

## Modes of Operation

### Single Mode

Query a single LLM and return its response.

```bash
PROMPT="Will remote work remain prevalent?" MODE=single PRIMARY_LLM=claude python llm_compare.py
```

### Compare Mode

Query multiple LLMs independently, report agreement or disagreement.

```bash
PROMPT="Should I learn Rust or Go?" CHOICES="Rust,Go" MODE=compare python llm_compare.py
```

**Output:**
```
=== LLM COMPARISON ===
Prompt: Should I learn Rust or Go?

Gemini: Go
  Reasoning: Go's simplicity and strong ecosystem for cloud services...

Claude: Rust
  Reasoning: Rust's memory safety guarantees and growing adoption...

OpenAI: Go
  Reasoning: Go's gentler learning curve and immediate productivity...

Grok: Rust
  Reasoning: Rust's performance characteristics and systems-level capabilities...

Perplexity: Go
  Reasoning: Based on current job market trends and developer surveys...

[COMPARISON] Gemini: Go, Claude: Rust, OpenAI: Go, Grok: Rust, Perplexity: Go
[RESULT] Majority recommends: Go (3/5)
```

### Integrate Mode

Multi-round deliberation where LLMs see and respond to peer analyses.

```bash
PROMPT="Will the current US president be re-elected?" MODE=integrate python llm_compare.py
```

**Output:**
```
=== LLM INTEGRATION ===
Prompt: Will the current US president be re-elected?

--- Round 1 (Independent Analysis) ---
Gemini: LIKELY (65% confidence)
Claude: UNCERTAIN (50% confidence)
OpenAI: LIKELY (60% confidence)
Grok: UNLIKELY (45% confidence)
Perplexity: LIKELY (58% confidence)

[INTEGRATE] Round 1 - Gemini: LIKELY, Claude: UNCERTAIN, OpenAI: LIKELY, Grok: UNLIKELY, Perplexity: LIKELY

--- Round 2 (After Peer Review) ---
Gemini: LIKELY (62% confidence)
Claude: LIKELY (55% confidence)  [FLIP from UNCERTAIN]
OpenAI: LIKELY (58% confidence)
Grok: UNCERTAIN (50% confidence)  [FLIP from UNLIKELY]
Perplexity: LIKELY (60% confidence)

[INTEGRATE] Round 2 - Gemini: LIKELY, Claude: LIKELY, OpenAI: LIKELY, Grok: UNCERTAIN, Perplexity: LIKELY

[INTEGRATE FINAL] Consensus reached: LIKELY (4/5 agree)
```

## Yes/No Evaluation Mode

The `YES_NO_EVAL` parameter simplifies output parsing and enables meaningful consensus detection by constraining prompts to Yes/No questions.

### When YES_NO_EVAL=YES

**Requirements:**
- Prompt must be phrased as a Yes/No question
- LLMs respond with: `YES`, `NO`, or `UNKNOWN`
- Optional confidence level (0-100)
- `REQUIRE_CONSENSUS` parameter is meaningful

**Structured Output:**
```
<ANSWER>YES|NO|UNKNOWN</ANSWER>
<CONFIDENCE>0-100</CONFIDENCE>
<REASONING>Brief explanation (max {MAX_RESPONSE_WORDS} words)</REASONING>
```

**Example:**
```bash
PROMPT="Will interest rates decrease in the next 6 months?" \
YES_NO_EVAL=YES \
REQUIRE_CONSENSUS=true \
MODE=integrate \
python llm_compare.py
```

**Output:**
```
=== YES/NO EVALUATION ===
Question: Will interest rates decrease in the next 6 months?

--- Round 1 ---
Gemini: YES (72% confidence)
Claude: YES (65% confidence)
OpenAI: UNKNOWN (50% confidence)
Grok: YES (68% confidence)
Perplexity: YES (70% confidence)

[CONSENSUS] YES (4/5 agree, 1 UNKNOWN)
[AVERAGE CONFIDENCE] 68.8%

--- Summarization ---
[Summary produced by SUMMARIZATION_LLM]
```

### When YES_NO_EVAL=NO (Default)

**Behavior:**
- Free-form responses and recommendations
- No structured answer extraction
- Integration phase focuses on reflection rather than consensus
- LLMs asked to "reflect on peers' perspectives" rather than "revise your answer"

**Integration Prompt (YES_NO_EVAL=NO):**
```
You previously provided this analysis:
{own_response}

Other AI systems offered these perspectives:
{peer_analyses}

Please reflect on these perspectives in light of the original question. 
Highlight areas of agreement, note important points you may have missed, 
and address any counterarguments. You do not need to change your position.
```

### Confidence Levels

When `YES_NO_EVAL=YES`, confidence levels enable richer analysis:

| Confidence Range | Interpretation |
|------------------|----------------|
| 80-100% | High confidence, strong evidence |
| 60-79% | Moderate confidence, reasonable evidence |
| 40-59% | Low confidence, mixed signals (may respond UNKNOWN) |
| 0-39% | Very low confidence, insufficient information |

**Weighted Consensus Option:**
```python
# Future enhancement: weight answers by confidence
def weighted_consensus(responses):
    yes_weight = sum(r['confidence'] for r in responses if r['answer'] == 'YES')
    no_weight = sum(r['confidence'] for r in responses if r['answer'] == 'NO')
    return 'YES' if yes_weight > no_weight else 'NO'
```

## Simple Integration Mode

The `SIMPLE_INTEGRATION` flag reduces API costs by limiting the cross-pollination phase.

### Standard Integration (SIMPLE_INTEGRATION=NO)

```
Round 1: All LLMs analyze independently (N calls)
Round 2: All LLMs see ALL peer analyses and reflect (N calls)
Summarization: One LLM summarizes everything (1 call)
Total: 2N + 1 calls
```

### Simple Integration (SIMPLE_INTEGRATION=YES)

```
Round 1: PRIMARY_LLM analyzes independently (1 call)
Round 2: Other LLMs reflect on PRIMARY_LLM's output only (N-1 calls)
Summarization: SUMMARIZATION_LLM summarizes everything (1 call)
Total: N + 1 calls
```

**Cost Comparison (5 LLMs):**
| Mode | API Calls | Relative Cost |
|------|-----------|---------------|
| Standard Integration | 11 | 100% |
| Simple Integration | 6 | 55% |

**Example:**
```bash
PROMPT="Should our company migrate to microservices?" \
SIMPLE_INTEGRATION=YES \
PRIMARY_LLM=claude \
MODE=integrate \
python llm_compare.py
```

**Flow:**
```
1. Claude analyzes the question (PRIMARY_LLM)
2. Gemini, OpenAI, Grok, Perplexity each reflect on Claude's analysis
3. SUMMARIZATION_LLM produces final summary
```

## Summarization Phase

Every integration session concludes with a summarization phase where the `SUMMARIZATION_LLM` produces a concise synthesis.

### Summarization Prompt

```python
SUMMARIZATION_PROMPT = """
You are tasked with summarizing a multi-AI analysis session.

ORIGINAL QUESTION:
{user_prompt}

{yes_no_section}

LLM RESPONSES:
{all_responses}

Please produce a concise summary (maximum {SUMMARIZATION_MAX_WORDS} words) that:
1. States the overall conclusion or majority position
2. Highlights 2-3 major themes from the analyses
3. Notes significant points of disagreement
4. Identifies any important caveats or uncertainties

Format your response as:

## Conclusion
[One sentence stating the overall finding]

## Key Themes
- [Theme 1]
- [Theme 2]
- [Theme 3 if applicable]

## Areas of Disagreement
[Brief description of where LLMs differed, if any]

## Caveats
[Important limitations or uncertainties noted]
"""
```

### Summarization Output Example

```
=== SUMMARIZATION (by Gemini) ===

## Conclusion
The majority of analyses recommend investing in index funds over individual NVIDIA stock, 
citing diversification benefits and stretched valuations.

## Key Themes
- **Valuation concerns**: Multiple LLMs noted NVIDIA's current price implies 
  near-perfect execution, leaving little margin for error.
- **Diversification benefits**: Index funds provide AI exposure while reducing 
  single-stock concentration risk.
- **Timing uncertainty**: While NVIDIA's fundamentals are strong, short-term 
  price movements are difficult to predict.

## Areas of Disagreement
OpenAI and Perplexity maintained that NVIDIA's AI infrastructure moat justifies 
premium valuation, while Claude and Grok emphasized risk-adjusted returns.

## Caveats
All analyses are based on current market conditions; geopolitical events or 
earnings surprises could significantly alter the calculus.
```

## Cost Control

### Word Limit Enforcement

To manage token usage and API costs, word limits are injected into prompts:

```python
def get_word_limit_instructions(config):
    if config.VERBOSE_MODE:
        return ""
    
    return f"""
IMPORTANT: Keep your response concise.
- Maximum {config.MAX_RESPONSE_WORDS} words for your analysis
- Maximum {config.MAX_REASONING_POINTS} key reasoning points
- Focus on the most important factors only
"""
```

### Prompt Templates with Cost Control

**Round 1 Prompt (with word limits):**
```
{base_prompt}

IMPORTANT: Keep your response concise.
- Maximum 300 words for your analysis
- Maximum 3 key reasoning points
- Focus on the most important factors only

{output_format_instructions}
```

**Integration Prompt (with word limits):**
```
{integration_prompt}

IMPORTANT: Keep your reflection concise.
- Maximum 200 words
- Focus only on significant new insights from peer analyses
- Do not repeat your original reasoning
```

### Cost Estimation

Before executing, estimate and optionally display costs:

```python
def estimate_cost(config):
    """Estimate API costs based on configuration."""
    
    # Rough token estimates per call
    input_tokens_per_call = 500 + (config.MAX_RESPONSE_WORDS * 1.5)  # prompt + context
    output_tokens_per_call = config.MAX_RESPONSE_WORDS * 1.5
    
    if config.SIMPLE_INTEGRATION:
        num_calls = len(config.COMPARE_LLMS) + 1
    else:
        num_calls = (len(config.COMPARE_LLMS) * 2) + 1
    
    # Add summarization
    num_calls += 1
    summarization_input = num_calls * config.MAX_RESPONSE_WORDS * 1.5
    
    total_input_tokens = (input_tokens_per_call * num_calls) + summarization_input
    total_output_tokens = output_tokens_per_call * num_calls + (config.SUMMARIZATION_MAX_WORDS * 1.5)
    
    # Cost varies by provider - rough average
    estimated_cost = (total_input_tokens * 0.00001) + (total_output_tokens * 0.00003)
    
    return {
        'num_calls': num_calls,
        'estimated_input_tokens': int(total_input_tokens),
        'estimated_output_tokens': int(total_output_tokens),
        'estimated_cost_usd': round(estimated_cost, 4)
    }
```

### Cost Control Presets

```python
COST_PRESETS = {
    'minimal': {
        'MAX_RESPONSE_WORDS': 150,
        'MAX_REASONING_POINTS': 2,
        'SUMMARIZATION_MAX_WORDS': 250,
        'SIMPLE_INTEGRATION': 'YES'
    },
    'balanced': {
        'MAX_RESPONSE_WORDS': 300,
        'MAX_REASONING_POINTS': 3,
        'SUMMARIZATION_MAX_WORDS': 500,
        'SIMPLE_INTEGRATION': 'NO'
    },
    'detailed': {
        'MAX_RESPONSE_WORDS': 600,
        'MAX_REASONING_POINTS': 5,
        'SUMMARIZATION_MAX_WORDS': 1000,
        'SIMPLE_INTEGRATION': 'NO'
    }
}

# Usage
COST_PRESET=minimal python llm_compare.py --prompt "..."
```

## Prompt Engineering

### Base Prompt Template

```python
BASE_PROMPT = """
You are participating in a multi-AI analysis system. Your role is to provide 
an independent, well-reasoned response to the following question.

{context_section}

QUESTION:
{user_prompt}

{choices_section}

Please provide:
1. Your recommendation or prediction
2. Your confidence level (if applicable)
3. Key reasoning points (2-3 bullet points)

{output_format_instructions}
"""
```

### Integration Round 2 Template

```python
INTEGRATION_PROMPT = """
You previously analyzed this question:

{user_prompt}

Your initial response was:
{own_response}

Other AI systems provided these analyses:

---BEGIN PEER ANALYSES---
{peer_analyses}
---END PEER ANALYSES---

After reviewing your peers' perspectives, you may:
- Maintain your original position with additional reasoning
- Revise your position based on compelling arguments
- Acknowledge uncertainty if perspectives are balanced

Provide your updated recommendation with reasoning.
"""
```

### Structured Output Instructions

For decision questions with explicit choices:
```
Conclude your response with your choice in this format:
<CHOICE>your_choice</CHOICE>
```

For prediction questions:
```
Conclude your response with your prediction:
<PREDICTION>LIKELY|UNLIKELY|UNCERTAIN</PREDICTION>
<CONFIDENCE>0-100</CONFIDENCE>
```

For open-ended recommendations:
```
Conclude with a one-line summary:
<SUMMARY>Your key recommendation in one sentence</SUMMARY>
```

## Google Trends Integration

When `GOOGLE_TRENDS_KEYWORD` is provided, fetch trending data and include in context.

```python
def get_trends_context(keyword):
    """Fetch Google Trends data for context."""
    pytrends.build_payload([keyword], timeframe='now 7-d')
    interest_df = pytrends.interest_over_time()
    
    if not interest_df.empty:
        recent_values = interest_df[keyword].tail(10).tolist()
        avg_interest = interest_df[keyword].mean()
        trend_direction = "increasing" if recent_values[-1] > avg_interest else "decreasing"
        
        return f"""
---BEGIN GOOGLE TRENDS DATA---
Keyword: {keyword}
Recent interest trend: {trend_direction}
Average interest (7-day): {avg_interest:.1f}
Recent data points: {recent_values}
---END GOOGLE TRENDS DATA---
"""
    return None
```

**Usage:**
```bash
PROMPT="Is interest in electric vehicles increasing or decreasing?" \
GOOGLE_TRENDS_KEYWORD="electric vehicle" \
MODE=compare \
python llm_compare.py
```

## Reference Files Integration

When `REFERENCE_FILES` is provided, the contents of specified files are included as context for the LLMs to reference when answering the prompt. This enables analysis of documents, code, data, or any text-based content.

### Supported File Types

| Type | Extensions | Handling |
|------|------------|----------|
| Text | `.txt`, `.md`, `.csv` | Read as-is |
| Code | `.py`, `.js`, `.java`, `.go`, etc. | Read with syntax context |
| JSON | `.json` | Pretty-printed |
| YAML | `.yaml`, `.yml` | Read as-is |

### File Context Template

```python
def get_file_context(file_paths):
    """Read and format reference files for LLM context."""
    context_parts = []
    
    for path in file_paths:
        if not os.path.exists(path):
            print(f"Warning: Reference file not found: {path}")
            continue
            
        filename = os.path.basename(path)
        extension = os.path.splitext(path)[1]
        
        with open(path, 'r') as f:
            content = f.read()
        
        # Truncate very large files
        if len(content) > MAX_FILE_CONTEXT_SIZE:
            content = content[:MAX_FILE_CONTEXT_SIZE] + "\n... [truncated]"
        
        context_parts.append(f"""
---BEGIN REFERENCE FILE: {filename}---
{content}
---END REFERENCE FILE: {filename}---
""")
    
    return "\n".join(context_parts)
```

### Configuration

```python
# Maximum characters per reference file (to manage context window)
MAX_FILE_CONTEXT_SIZE = 50000  # ~12k tokens

# Maximum total reference file content
MAX_TOTAL_REFERENCE_SIZE = 150000  # ~37k tokens
```

### Usage Examples

**Analyze a document:**
```bash
python llm_compare.py \
    --prompt "What are the key risks identified in this proposal?" \
    --reference-files "./docs/project_proposal.md" \
    --mode compare
```

**Compare code implementations:**
```bash
python llm_compare.py \
    --prompt "Which implementation is more maintainable and why?" \
    --reference-files "./v1/handler.py,./v2/handler.py" \
    --choices "v1,v2" \
    --mode integrate
```

**Analyze data with context:**
```bash
python llm_compare.py \
    --prompt "Based on this sales data, should we expand to the European market?" \
    --reference-files "./data/sales_2025.csv,./docs/market_analysis.md" \
    --choices "Yes,No,Need more data" \
    --mode integrate
```

**Review a contract:**
```bash
python llm_compare.py \
    --prompt "Are there any concerning clauses in this contract that I should negotiate?" \
    --reference-files "./contracts/vendor_agreement.txt" \
    --mode compare
```

### Prompt Integration

When reference files are provided, they are inserted into the prompt context:

```python
BASE_PROMPT_WITH_FILES = """
You are participating in a multi-AI analysis system. Your role is to provide 
an independent, well-reasoned response to the following question.

The following reference files have been provided for context:

{file_context}

{additional_context}

QUESTION:
{user_prompt}

{choices_section}

Please provide:
1. Your recommendation or prediction
2. Your confidence level (if applicable)
3. Key reasoning points (2-3 bullet points)
4. Specific references to the provided files where relevant

{output_format_instructions}
"""
```

### History Recording with Files

When reference files are used, the recommendation record includes file metadata:

```json
{
  "id": "rec_20260419_163045",
  "prompt": "What are the key risks in this proposal?",
  "reference_files": [
    {
      "path": "./docs/project_proposal.md",
      "filename": "project_proposal.md",
      "size_bytes": 15420,
      "hash": "sha256:a1b2c3..."
    }
  ],
  "reference_files_truncated": false,
  ...
}
```

**Note:** File contents are not stored in the history to avoid bloat; only metadata is recorded. The file hash enables verification that the same file version was used.

## History Recording

### recommendations.json Schema

```json
{
  "recommendations": [
    {
      "id": "rec_20260419_153045",
      "timestamp": "2026-04-19T15:30:45.123456Z",
      "prompt": "Should I learn Rust or Go?",
      "prompt_hash": "a1b2c3d4...",
      "choices": ["Rust", "Go"],
      "mode": "compare",
      "llms_used": ["gemini", "claude", "openai", "grok", "perplexity"],
      "google_trends_keyword": null,
      "round_1_responses": {
        "gemini": {
          "choice": "Go",
          "confidence": null,
          "reasoning_summary": "Go's simplicity and cloud ecosystem"
        },
        "claude": {
          "choice": "Rust",
          "confidence": null,
          "reasoning_summary": "Memory safety and growing adoption"
        }
      },
      "round_2_responses": null,
      "final_recommendation": "Go",
      "consensus_reached": false,
      "consensus_count": "3/5",
      "flips": []
    },
    {
      "id": "rec_20260419_160012",
      "timestamp": "2026-04-19T16:00:12.789012Z",
      "prompt": "Will the current US president be re-elected?",
      "prompt_hash": "e5f6g7h8...",
      "choices": null,
      "mode": "integrate",
      "llms_used": ["gemini", "claude", "openai", "grok", "perplexity"],
      "google_trends_keyword": "presidential election",
      "round_1_responses": {
        "gemini": {"choice": "LIKELY", "confidence": 65},
        "claude": {"choice": "UNCERTAIN", "confidence": 50}
      },
      "round_2_responses": {
        "gemini": {"choice": "LIKELY", "confidence": 62},
        "claude": {"choice": "LIKELY", "confidence": 55}
      },
      "final_recommendation": "LIKELY",
      "consensus_reached": true,
      "consensus_count": "4/5",
      "flips": [
        {"llm": "claude", "from": "UNCERTAIN", "to": "LIKELY"},
        {"llm": "grok", "from": "UNLIKELY", "to": "UNCERTAIN"}
      ]
    }
  ]
}
```

## CLI Interface

### Basic Usage

```bash
# Simple single-LLM query
python llm_compare.py --prompt "What is the best approach to learn machine learning?"

# Compare mode with choices
python llm_compare.py --prompt "Which cloud provider should I use?" \
    --choices "AWS,GCP,Azure" \
    --mode compare

# Integrate mode with Google Trends
python llm_compare.py --prompt "Is cryptocurrency adoption increasing?" \
    --mode integrate \
    --google-trends-keyword "bitcoin"

# Read prompt from file
python llm_compare.py --prompt-file ./prompts/investment_question.txt \
    --mode integrate
```

### Command Line Arguments

```
usage: llm_compare.py [-h] [--prompt PROMPT] [--prompt-file PROMPT_FILE]
                      [--reference-files FILES] [--choices CHOICES]
                      [--mode {single,compare,integrate}]
                      [--primary-llm {gemini,claude,openai,grok,perplexity}]
                      [--llms LLMS] [--yes-no-eval] [--require-consensus]
                      [--simple-integration] [--summarization-llm LLM]
                      [--max-response-words N] [--max-reasoning-points N]
                      [--summarization-max-words N] [--verbose]
                      [--cost-preset {minimal,balanced,detailed}]
                      [--google-trends-keyword KEYWORD]
                      [--output-format {text,json,markdown}]
                      [--history-file PATH] [--log-rounds]

Multi-LLM Advisory System

optional arguments:
  -h, --help            show this help message and exit
  --prompt PROMPT       The question or decision to evaluate
  --prompt-file PATH    Path to file containing prompt
  --reference-files FILES
                        Comma-separated list of file paths to include as context
  --choices CHOICES     Comma-separated list of choices
  --mode MODE           Operating mode: single, compare, integrate
  --primary-llm LLM     Primary LLM for single mode or tiebreaker
  --llms LLMS           Comma-separated list of LLMs to use
  --yes-no-eval         Enable Yes/No evaluation mode (YES/NO/UNKNOWN answers)
  --require-consensus   Require LLM consensus for final answer (YES_NO_EVAL only)
  --simple-integration  Only integrate primary LLM output (reduces cost)
  --summarization-llm LLM
                        LLM to use for final summarization (default: gemini)
  --max-response-words N
                        Word limit for LLM responses (default: 300)
  --max-reasoning-points N
                        Max reasoning bullet points (default: 3)
  --summarization-max-words N
                        Word limit for final summary (default: 500)
  --verbose             Ignore word limits for detailed output
  --cost-preset PRESET  Use predefined cost settings: minimal, balanced, detailed
  --google-trends-keyword KEYWORD
                        Keyword for Google Trends context
  --output-format FMT   Output format: text, json, markdown
  --history-file PATH   Path to recommendations history file
  --log-rounds          Log full responses from each round
```

## Project Structure

```
llm-compare/
├── llm_compare.py          # Main entry point
├── config.py               # Configuration and environment handling
├── llm_utils/
│   ├── __init__.py
│   ├── base.py             # Abstract base class for LLM clients
│   ├── gemini_client.py    # Gemini API wrapper
│   ├── claude_client.py    # Claude API wrapper
│   ├── openai_client.py    # OpenAI API wrapper
│   ├── grok_client.py      # Grok API wrapper
│   └── perplexity_client.py # Perplexity API wrapper
├── context/
│   ├── __init__.py
│   ├── trends.py           # Google Trends integration
│   └── web_search.py       # Future: web search integration
├── prompts/
│   ├── base_prompt.py      # Prompt templates
│   └── integration_prompt.py
├── history/
│   ├── __init__.py
│   ├── recorder.py         # History recording utilities
│   └── recommendations.json # Stored recommendations
├── requirements.txt
└── README.md
```

## MVP Scope

### Included in MVP

- Single, Compare, and Integrate modes
- Support for Gemini, Claude, OpenAI, Grok, Perplexity
- Google Trends integration (optional)
- Command-line interface
- recommendations.json recording
- Text and JSON output formats

### Deferred to Future Versions

- Web search context integration
- Recommendation analyzer (evaluate past predictions)
- Web UI
- Scheduled/recurring queries
- Custom prompt templates
- Confidence calibration
- Cost tracking per query

## Design Decisions

The following decisions were made for MVP scope:

### Architectural Decisions

1. **Prompt Complexity**: 
   - **Decision**: If `YES_NO_EVAL=YES`, prompt must contain a clearly identified single yes/no question. If `YES_NO_EVAL=NO`, anything goes—reflection prompts, decision tree analysis, open-ended exploration, etc.

2. **Context Window Management**: 
   - **Decision**: Yes, implement output limits via parameters like `ROUND_TWO_OUTPUT_LIMIT` to control response sizes and prevent context overflow.

3. **Partial Failures**: 
   - **Decision**: Yes, proceed with remaining LLMs if one fails.

4. **Rate Limiting**: 
   - **Decision**: Parallel queries not supported in MVP. Sequential processing avoids rate limit complexity.

### Output Decisions

5. **Confidence Calibration**: 
   - **Decision**: Not for MVP. Calibration tendencies may change, and measuring them reliably is complex.

6. **Disagreement Handling**: 
   - **Decision**: Yes, weight decisions by confidence level when confidence is available.

7. **Reasoning Extraction**: 
   - **Decision**: The `YES_NO_EVAL` parameter simplifies this. For YES_NO_EVAL=YES, structured output is required. User chooses LLMs based on their abilities. *Side note: This tool could be used to evaluate different LLMs' abilities in structured output.*

8. **Output Verification**: 
   - **Decision**: Defer to post-MVP.

### History & Analysis Decisions

9. **Prediction Tracking**: 
   - **Decision**: For MVP, only track recommendations in JSON for yes/no questions. This simplifies the analysis process.

10. **Prompt Deduplication**: 
    - **Decision**: Not for MVP.

11. **Privacy**: 
    - **Decision**: Not for MVP.

### Integration Decisions

12. **Google Trends Relevance**: 
    - **Decision**: User or LLM receiving the data decides relevance. If `SIMPLE_INTEGRATION=YES`, only send Google Trends data to the initial/primary LLM.

13. **Additional Context Sources**: 
    - **Decision**: TBD. Given the wide-open field for prompt content, this requires further analysis. Usage patterns and user feedback will inform future direction.

14. **Real-Time Data**: 
    - **Decision**: Yes, LLMs will respond appropriately to what they can and cannot provide based on their capabilities.

### Usability Decisions

15. **Interactive Mode**: 
    - **Decision**: Not for MVP.

16. **Batch Processing**: 
    - **Decision**: Not for MVP.

17. **Caching**: 
    - **Decision**: No. LLM responses may change on repeated queries, so caching could return stale/inconsistent results.

18. **Cost Estimation (What-If Mode)**: 
    - **Decision**: Yes, add `WHAT_IF_MODE` parameter. When enabled, evaluate and display the cost of processing with given parameters without actually making LLM calls. Analogous to trading bot's what-if mode (don't actually buy).

## Migration Path from Trading Bot

### Code Reuse

| Trading Bot Component | General Purpose Equivalent |
|----------------------|---------------------------|
| `crypto_trading_bot.py` (LLM calls) | `llm_utils/*.py` |
| `process_coin_with_comparison()` | `process_prompt_with_comparison()` |
| `get_llm_response()` | `get_llm_response()` (abstracted) |
| `googleTrendsRequest()` | `context/trends.py` |
| `historyutil.py` | `history/recorder.py` |
| LLM utility files (`claudeutil.py`, etc.) | `llm_utils/*.py` |

### Abstraction Strategy

1. **Extract LLM Client Interface**
   - Create abstract base class `LLMClient`
   - Each LLM utility implements common interface
   - Methods: `send_request()`, `send_integrated_request()`

2. **Generalize Prompt Handling**
   - Replace coin-specific prompts with template system
   - Support user-provided prompts with structured output instructions

3. **Decouple from Trading Logic**
   - Remove Coinbase integration
   - Remove coin validation
   - Remove trade execution

## Example Session

```
$ python llm_compare.py \
    --prompt "Given current market conditions and the rise of AI, should I invest in NVIDIA stock, diversified index funds, or hold cash?" \
    --choices "NVIDIA,Index Funds,Cash" \
    --mode integrate \
    --google-trends-keyword "NVIDIA stock"

=== LLM ADVISOR ===
Prompt: Given current market conditions and the rise of AI, should I invest 
        in NVIDIA stock, diversified index funds, or hold cash?
Choices: NVIDIA, Index Funds, Cash
Mode: integrate
Google Trends: NVIDIA stock (interest: increasing, avg: 78.3)

--- Round 1 (Independent Analysis) ---

Gemini: Index Funds
  - NVIDIA has had exceptional run, valuation stretched
  - Index funds provide AI exposure with diversification
  - Confidence: 70%

Claude: Index Funds  
  - Single stock concentration risk significant
  - Broad market participation in AI theme
  - Confidence: 75%

OpenAI: NVIDIA
  - AI infrastructure buildout still early
  - NVIDIA's moat in CUDA ecosystem strong
  - Confidence: 60%

Grok: Index Funds
  - Risk-adjusted returns favor diversification
  - NVIDIA priced for perfection
  - Confidence: 65%

Perplexity: NVIDIA
  - Recent earnings beat expectations
  - Data center demand accelerating
  - Confidence: 55%

[INTEGRATE] Round 1 - Gemini: Index Funds, Claude: Index Funds, OpenAI: NVIDIA, 
                       Grok: Index Funds, Perplexity: NVIDIA

--- Round 2 (After Peer Review) ---

Gemini: Index Funds (68%)
Claude: Index Funds (72%)
OpenAI: Index Funds (58%)  [FLIP from NVIDIA]
  - Reconsidering: diversification argument compelling given valuation
Grok: Index Funds (68%)
Perplexity: NVIDIA (52%)
  - Maintaining: near-term catalysts outweigh diversification benefits

[INTEGRATE] Round 2 - Gemini: Index Funds, Claude: Index Funds, OpenAI: Index Funds,
                       Grok: Index Funds, Perplexity: NVIDIA

[FINAL] Consensus reached: Index Funds (4/5 agree)

Recommendation saved to ./history/recommendations.json
```

## References

- Trading bot architecture (`crypto_trading_bot.py`)
- LLM utility patterns (`claudeutil.py`, `grokutil.py`, etc.)
- History recording patterns (`historyutil.py`)
- Multi-LLM integration logic (compare/integrate modes)
