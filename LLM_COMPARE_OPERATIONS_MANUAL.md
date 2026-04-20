# LLM Compare Operations Manual

This document describes the programs, environment variables, APIs, and configuration for the Multi-LLM Advisory System (`llm_compare.py`).

---

## Program

### Multi-LLM Advisory System (`llm_compare.py`)

A general-purpose tool that leverages multiple LLMs to evaluate questions, make predictions, and provide recommendations through comparison and integration of diverse AI perspectives.

**Usage:**
```bash
python llm_compare.py [OPTIONS]
```

**Command-Line Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--prompt` | string | *(required)* | The question or decision to evaluate |
| `--prompt-file` | path | *(empty)* | Path to file containing prompt (alternative to `--prompt`) |
| `--mode` | `single`, `compare`, `integrate` | `single` | Operating mode |
| `--primary-llm` | `gemini`, `claude`, `openai`, `grok`, `perplexity` | `gemini` | Primary LLM for single mode |
| `--llms` | comma-separated | `gemini,claude,openai,grok,perplexity` | LLMs for compare/integrate mode |
| `--tiebreaker` | `gemini`, `claude`, `openai`, `grok`, `perplexity`, `none` | `gemini` | Tiebreaker LLM when no consensus |
| `--summarization-llm` | `gemini`, `claude`, `openai`, `grok`, `perplexity` | `gemini` | LLM for final summarization |
| `--choices` | comma-separated | *(empty)* | Constrained choices for decision questions |
| `--yes-no-eval` | flag | `false` | Enable Yes/No/Unknown evaluation mode |
| `--require-consensus` | flag | `false` | Require LLM consensus for final answer |
| `--reference-files` | comma-separated paths | *(empty)* | Files to include as context |
| `--google-trends-keyword` | string | *(empty)* | Keyword for Google Trends context |
| `--simple-integration` | flag | `false` | Only integrate primary LLM output (reduces cost) |
| `--log-rounds` | flag | `false` | Log full responses from each round |
| `--show-reasoning` | flag | `true` | Display reasoning from each LLM |
| `--no-reasoning` | flag | `false` | Hide reasoning from output |
| `--max-response-words` | integer | `300` | Word limit for LLM responses |
| `--round-two-limit` | integer | `200` | Word limit for Round 2 integration |
| `--max-reasoning-points` | integer | `3` | Max reasoning bullet points |
| `--summarization-max-words` | integer | `500` | Word limit for final summary |
| `--verbose` | flag | `false` | Ignore word limits |
| `--cost-preset` | `minimal`, `balanced`, `detailed` | *(none)* | Predefined cost settings |
| `--what-if` | flag | `false` | Estimate cost without making LLM calls |
| `--output-format` | `text`, `json`, `markdown` | `text` | Output format |
| `--history-file` | path | `./history/recommendations.json` | Path to history file |

**Configuration Precedence:**
CLI arguments take precedence over environment variables. If neither is set, the default value is used.

---

## Modes of Operation

### Single Mode
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

**Round 1:** Each LLM provides independent analysis
**Round 2:** Each LLM reviews peer analyses and may revise position
**Summarization:** Final synthesis of all perspectives

```bash
python llm_compare.py --prompt "Will remote work remain prevalent?" \
    --mode integrate \
    --llms "gemini,claude,openai,grok,perplexity"
```

---

## Special Features

### Yes/No Evaluation Mode
For questions requiring structured YES/NO/UNKNOWN answers with confidence levels:

```bash
python llm_compare.py --prompt "Will the Fed cut rates this year?" \
    --yes-no-eval \
    --mode integrate
```

**Output format:**
- `<ANSWER>YES|NO|UNKNOWN</ANSWER>`
- `<CONFIDENCE>0-100</CONFIDENCE>`
- `<REASONING>Explanation</REASONING>`

### Choices Mode
Constrain LLMs to specific options:

```bash
python llm_compare.py --prompt "Which cloud provider should I use?" \
    --choices "AWS,GCP,Azure" \
    --mode compare
```

### Reference Files
Include documents as context for analysis:

```bash
python llm_compare.py --prompt "What are the key risks in this proposal?" \
    --reference-files "./docs/proposal.md,./data/financials.csv" \
    --mode compare
```

**Limits:**
- Max 50,000 characters per file
- Max 150,000 characters total across all files

### Google Trends Integration
Add trend data as context (requires `pytrends` package):

```bash
python llm_compare.py --prompt "Is EV demand increasing?" \
    --google-trends-keyword "electric vehicle" \
    --mode compare
```

---

## Cost Control

### Cost Presets

| Preset | Response Words | Reasoning Points | Summary Words | Simple Integration |
|--------|---------------|------------------|---------------|-------------------|
| `minimal` | 150 | 2 | 250 | Yes |
| `balanced` | 300 | 3 | 500 | No |
| `detailed` | 600 | 5 | 1000 | No |

```bash
python llm_compare.py --prompt "..." --cost-preset minimal
```

### What-If Mode
Estimate costs without making API calls:

```bash
python llm_compare.py --prompt "..." --mode integrate --what-if
```

**Output:**
```
=== WHAT-IF MODE (Cost Estimation) ===
Mode: integrate
LLMs: 5
Estimated API calls: 11
Simple integration: False
Estimated input tokens: 15,400
Estimated output tokens: 5,700
Estimated cost: $0.3250

No LLM calls made.
```

### Simple Integration
Reduce costs by only having other LLMs review the primary LLM's analysis:

```bash
python llm_compare.py --prompt "..." --mode integrate --simple-integration
```

---

## Environment Variables

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMPT` | *(empty)* | The question or decision to evaluate |
| `PROMPT_FILE` | *(empty)* | Path to file containing prompt |
| `MODE` | `single` | Operating mode: `single`, `compare`, `integrate` |
| `PRIMARY_LLM` | `gemini` | Primary LLM for single mode |
| `COMPARE_LLMS` | `gemini,claude,openai,grok,perplexity` | LLMs for compare/integrate |
| `INTEGRATION_TIEBREAKER` | `gemini` | Tiebreaker LLM when no consensus |
| `SUMMARIZATION_LLM` | `gemini` | LLM for final summarization |
| `CHOICES` | *(empty)* | Comma-separated choices |
| `YES_NO_EVAL` | `NO` | Set to `YES` for Yes/No evaluation mode |
| `REQUIRE_CONSENSUS` | `false` | Require LLM consensus |
| `REFERENCE_FILES` | *(empty)* | Comma-separated file paths |
| `GOOGLE_TRENDS_KEYWORD` | *(empty)* | Keyword for trends context |
| `SIMPLE_INTEGRATION` | `NO` | Set to `YES` for simple integration |
| `LOG_INTEGRATION_ROUNDS` | `false` | Log full round responses |
| `SHOW_REASONING` | `true` | Display reasoning |
| `MAX_RESPONSE_WORDS` | `300` | Word limit for responses |
| `ROUND_TWO_OUTPUT_LIMIT` | `200` | Word limit for Round 2 |
| `MAX_REASONING_POINTS` | `3` | Max reasoning bullet points |
| `SUMMARIZATION_MAX_WORDS` | `500` | Word limit for summary |
| `VERBOSE_MODE` | `NO` | Ignore word limits |
| `WHAT_IF_MODE` | `NO` | Cost estimation only |
| `OUTPUT_FORMAT` | `text` | Output format: `text`, `json`, `markdown` |
| `HISTORY_FILE` | `./history/recommendations.json` | History file path |

### API Keys

| Variable | Required For | Description |
|----------|--------------|-------------|
| `GOOGLE_API_KEY` | Gemini | Google AI API key |
| `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` | Claude | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI | OpenAI API key |
| `XAI_API_KEY` | Grok | xAI API key for Grok |
| `PERPLEXITY_API_KEY` | Perplexity | Perplexity API key |

---

## APIs and Services

### 1. Google Gemini API

**Purpose:** Primary LLM with real-time web search (grounding)

**Authentication:** Environment variable `GOOGLE_API_KEY`

**Library:** `google-genai`

**Model:** `gemini-2.5-pro`

**Features:** Google Search grounding for real-time data

---

### 2. Anthropic Claude API

**Purpose:** LLM for analysis and integration

**Authentication:** Environment variable `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY`

**Library:** `anthropic`

**Model:** `claude-sonnet-4-20250514`

---

### 3. OpenAI API

**Purpose:** LLM for analysis and integration

**Authentication:** Environment variable `OPENAI_API_KEY`

**Library:** `openai`

**Model:** `gpt-4o`

---

### 4. xAI Grok API

**Purpose:** LLM for analysis with web search

**Authentication:** Environment variable `XAI_API_KEY`

**Library:** `openai` (OpenAI-compatible API)

**Base URL:** `https://api.x.ai/v1`

**Model:** `grok-4`

**Features:** Web search tool for real-time data

---

### 5. Perplexity API

**Purpose:** LLM with built-in search capabilities

**Authentication:** Environment variable `PERPLEXITY_API_KEY`

**Library:** `openai` (OpenAI-compatible API)

**Base URL:** `https://api.perplexity.ai`

**Model:** `sonar-pro`

---

### 6. Google Trends API

**Purpose:** Fetch trend data for context

**Authentication:** None required

**Library:** `pytrends` (optional)

---

## Directory Structure

```
tradingbot/
├── llm_compare.py              # Main entry point
├── config.py                   # Configuration handling
├── llm_utils/
│   ├── __init__.py
│   ├── base.py                 # Abstract LLM client base class
│   ├── gemini_client.py        # Gemini implementation
│   ├── claude_client.py        # Claude implementation
│   ├── openai_client.py        # OpenAI implementation
│   ├── grok_client.py          # Grok implementation
│   └── perplexity_client.py    # Perplexity implementation
├── context/
│   ├── __init__.py
│   └── trends.py               # Google Trends integration
├── prompts/
│   ├── __init__.py
│   └── templates.py            # Prompt templates
├── history/
│   ├── __init__.py
│   ├── recorder.py             # History recording
│   └── recommendations.json    # Stored recommendations (gitignored)
├── requirements_llm_compare.txt
├── README_LLM_COMPARE.md
└── LLM_COMPARE_OPERATIONS_MANUAL.md
```

---

## History Recording

All compare and integrate sessions are automatically saved to the history file.

**Record format:**
```json
{
  "id": "rec_20260420_123045",
  "timestamp": "2026-04-20T12:30:45.123456Z",
  "prompt": "Should I learn Rust or Go?",
  "prompt_hash": "a1b2c3d4e5f6g7h8",
  "mode": "compare",
  "yes_no_eval": false,
  "choices": ["Rust", "Go"],
  "llms_used": ["gemini", "claude", "openai"],
  "round_1_responses": {
    "gemini": {"choice": "Go", "confidence": 75},
    "claude": {"choice": "Rust", "confidence": 60},
    "openai": {"choice": "Go", "confidence": 70}
  },
  "final_recommendation": "Go",
  "consensus_reached": true,
  "consensus_count": "2/3",
  "flips": []
}
```

---

## Quick Start Examples

### Simple question (single mode)
```bash
python llm_compare.py --prompt "What is the best way to learn machine learning?"
```

### Decision with choices (compare mode)
```bash
python llm_compare.py --prompt "Which language should I learn?" \
    --choices "Rust,Go,Python" \
    --mode compare \
    --llms "claude,openai"
```

### Yes/No prediction (integrate mode)
```bash
python llm_compare.py --prompt "Will AI replace most programming jobs by 2030?" \
    --yes-no-eval \
    --mode integrate
```

### With reference files
```bash
python llm_compare.py --prompt "Summarize the key points of this document" \
    --reference-files "./report.pdf" \
    --mode single
```

### Cost-conscious integration
```bash
python llm_compare.py --prompt "What is the future of renewable energy?" \
    --mode integrate \
    --cost-preset minimal \
    --simple-integration
```

### JSON output for scripting
```bash
python llm_compare.py --prompt "Is now a good time to buy a house?" \
    --yes-no-eval \
    --mode compare \
    --output-format json
```

### Using environment variables
```bash
export PROMPT="Should I invest in index funds?"
export MODE=integrate
export COMPARE_LLMS=gemini,claude,openai
python llm_compare.py
```

---

## Troubleshooting

### Missing API Key
```
Could not initialize claude: ANTHROPIC_API_KEY or CLAUDE_API_KEY environment variable not set
```
**Solution:** Set the required API key environment variable.

### Grok Model Error
```
Error code: 400 - the model grok-3 is not supported when using server-side tools
```
**Solution:** The system uses `grok-4` which supports server-side tools. Ensure you're using the latest version.

### pytrends Not Installed
```
Warning: pytrends not installed. Install with: pip install pytrends
```
**Solution:** Install pytrends if you need Google Trends integration: `pip install pytrends`

### No Consensus
When LLMs disagree and no consensus is reached, the tiebreaker LLM's answer is used (unless `--tiebreaker none` is set).

---

## Dependencies

Install required packages:
```bash
pip install -r requirements_llm_compare.txt
```

**Required:**
- `google-genai>=1.0.0`
- `anthropic>=0.18.0`
- `openai>=1.0.0`

**Optional:**
- `pytrends>=4.9.0` (for Google Trends integration)
