# Multi-LLM Advisory System (llm_compare.py)

A general-purpose tool that leverages multiple LLMs to evaluate questions, make predictions, and provide recommendations through comparison and integration of diverse AI perspectives.

## Quick Start

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

# Yes/No evaluation
python llm_compare.py --prompt "Will interest rates decrease in the next 6 months?" \
    --yes-no-eval \
    --mode integrate
```

## Requirements

Set the following environment variables for the LLMs you want to use:

| LLM | Environment Variable |
|-----|---------------------|
| Gemini | `GOOGLE_API_KEY` |
| Claude | `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Grok | `XAI_API_KEY` |
| Perplexity | `PERPLEXITY_API_KEY` |

Install dependencies:
```bash
pip install -r requirements_llm_compare.txt
```

## Modes of Operation

### Single Mode (default)
Query a single LLM and return its response.

```bash
python llm_compare.py --prompt "Should I learn Rust?" --mode single --primary-llm claude
```

### Compare Mode
Query multiple LLMs independently and report agreement or disagreement.

```bash
python llm_compare.py --prompt "Should I learn Rust or Go?" \
    --choices "Rust,Go" \
    --mode compare \
    --llms "gemini,claude,openai"
```

### Integrate Mode
Multi-round deliberation where LLMs see and respond to peer analyses.

```bash
python llm_compare.py --prompt "Will remote work remain prevalent?" \
    --mode integrate \
    --llms "gemini,claude,openai,grok,perplexity"
```

## Key Features

### Yes/No Evaluation
For questions requiring YES/NO/UNKNOWN answers with confidence levels:

```bash
python llm_compare.py --prompt "Will the Fed cut rates this year?" \
    --yes-no-eval \
    --require-consensus \
    --mode integrate
```

### Reference Files
Include documents as context for analysis:

```bash
python llm_compare.py --prompt "What are the key risks in this proposal?" \
    --reference-files "./docs/proposal.md,./data/financials.csv" \
    --mode compare
```

### Google Trends Integration
Add trend data as context:

```bash
python llm_compare.py --prompt "Is EV demand increasing?" \
    --google-trends-keyword "electric vehicle" \
    --mode compare
```

### Cost Control
Use presets or individual parameters to manage API costs:

```bash
# Use minimal preset (fewer words, simple integration)
python llm_compare.py --prompt "..." --cost-preset minimal

# Or customize individually
python llm_compare.py --prompt "..." \
    --max-response-words 150 \
    --max-reasoning-points 2 \
    --simple-integration
```

### What-If Mode
Estimate costs without making API calls:

```bash
python llm_compare.py --prompt "..." --mode integrate --what-if
```

## Command Line Options

```
--prompt PROMPT           The question or decision to evaluate
--prompt-file PATH        Path to file containing prompt
--reference-files FILES   Comma-separated file paths for context
--choices CHOICES         Comma-separated choices for decisions
--mode {single,compare,integrate}
--primary-llm LLM         Primary LLM (default: gemini)
--llms LLMS               Comma-separated LLMs for compare/integrate
--tiebreaker LLM          Tiebreaker when no consensus
--summarization-llm LLM   LLM for final summary (default: gemini)
--yes-no-eval             Enable Yes/No evaluation mode
--require-consensus       Require consensus for final answer
--simple-integration      Only integrate primary LLM output
--log-rounds              Show full responses from each round
--max-response-words N    Word limit (default: 300)
--max-reasoning-points N  Max bullet points (default: 3)
--summarization-max-words N  Summary word limit (default: 500)
--verbose                 Ignore word limits
--cost-preset {minimal,balanced,detailed}
--google-trends-keyword   Keyword for Google Trends context
--output-format {text,json,markdown}
--history-file PATH       Path to history file
--what-if                 Estimate cost without API calls
```

## Project Structure

```
llm_compare.py          # Main entry point
config.py               # Configuration handling
llm_utils/
├── __init__.py
├── base.py             # Abstract LLM client base class
├── gemini_client.py    # Gemini implementation
├── claude_client.py    # Claude implementation
├── openai_client.py    # OpenAI implementation
├── grok_client.py      # Grok implementation
└── perplexity_client.py # Perplexity implementation
context/
├── __init__.py
└── trends.py           # Google Trends integration
prompts/
├── __init__.py
└── templates.py        # Prompt templates
history/
├── __init__.py
└── recorder.py         # History recording
```

## History Recording

All compare and integrate sessions are saved to `./history/recommendations.json`:

```json
{
  "id": "rec_20260420_123045",
  "timestamp": "2026-04-20T12:30:45.123456Z",
  "prompt": "Should I learn Rust or Go?",
  "mode": "compare",
  "llms_used": ["gemini", "claude", "openai"],
  "final_recommendation": "Go",
  "consensus_reached": true,
  "consensus_count": "2/3"
}
```
