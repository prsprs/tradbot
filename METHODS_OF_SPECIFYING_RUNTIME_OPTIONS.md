# Methods of Specifying Runtime Options

## Overview

This document examines the trade-offs between different methods of configuring runtime behavior in command-line applications, specifically for the trading bot system. The goal is to establish a consistent, safe, and user-friendly approach to configuration.

## Methods Compared

1. **Environment Variables**
2. **Command-Line Arguments**
3. **Configuration Files**
4. **Hybrid Approach**

---

## Environment Variables

### How It Works

```bash
export TRADING_MODE=whatif
export LLM_MODE=compare
python crypto_trading_bot.py
```

Or inline:
```bash
TRADING_MODE=whatif LLM_MODE=compare python crypto_trading_bot.py
```

### Advantages

| Advantage | Description |
|-----------|-------------|
| **Persistence** | Set once in `.bashrc` or `.env`, applies to all runs |
| **Security** | Not visible in `ps aux` process listings |
| **Shell history safety** | Secrets don't appear in command history |
| **Docker/CI friendly** | Native support in containerized environments |
| **12-factor app compliance** | Industry standard for configuration |
| **Sourcing from files** | `source .env` loads multiple variables at once |

### Disadvantages

| Disadvantage | Description |
|--------------|-------------|
| **Session stickiness** | Variables persist in terminal session; easy to forget one is set |
| **Invisible state** | Hard to know "what am I running with right now?" |
| **Debugging difficulty** | "Works on my machine" issues when env differs |
| **No built-in help** | User must read documentation to know valid values |
| **No validation** | Typos silently fall back to defaults |
| **Inheritance surprises** | Child processes inherit parent's environment |

### Session Stickiness Problem

This is the most significant issue with environment variables for operational modes:

```bash
# Morning: testing
export TRADING_MODE=whatif
python crypto_trading_bot.py  # Safe, no trades

# Afternoon: forgot to unset, think I'm in live mode
python crypto_trading_bot.py  # Still whatif! Missed real opportunities

# Or worse, the reverse:
export TRADING_MODE=live
# ... hours later, debugging ...
python crypto_trading_bot.py  # Accidentally executed real trades!
```

---

## Command-Line Arguments

### How It Works

```bash
python crypto_trading_bot.py --trading-mode=whatif --llm-mode=compare
```

### Advantages

| Advantage | Description |
|-----------|-------------|
| **Explicit per-run** | Each invocation clearly shows its configuration |
| **Self-documenting** | Shell history shows exactly what was run |
| **Built-in help** | `--help` flag with argparse shows all options |
| **Validation** | Invalid arguments rejected with error message |
| **No inheritance** | Each run starts fresh, no sticky state |
| **Tab completion** | Shell can autocomplete argument names |

### Disadvantages

| Disadvantage | Description |
|--------------|-------------|
| **Verbose commands** | Long command lines with many options |
| **History exposure** | Secrets visible in shell history and `ps aux` |
| **Repetitive** | Must specify same options on every run |
| **Scripting overhead** | Wrapper scripts needed for common configurations |

### Security Problem for Credentials

```bash
# BAD: API key visible in process list and shell history
python crypto_trading_bot.py --api-key=sk-abc123xyz

# Anyone on the system can see this:
$ ps aux | grep python
user  python crypto_trading_bot.py --api-key=sk-abc123xyz
```

---

## Configuration Files

### How It Works

```yaml
# config.yaml
trading_mode: whatif
llm_mode: compare
credentials:
  coinbase_file: ./cdp_api_key.json
```

```bash
python crypto_trading_bot.py --config=config.yaml
```

### Advantages

| Advantage | Description |
|-----------|-------------|
| **Organized** | All settings in one place |
| **Version controllable** | Can commit non-secret configs to git |
| **Multiple profiles** | `config-dev.yaml`, `config-prod.yaml` |
| **Complex structures** | Supports nested configuration |

### Disadvantages

| Disadvantage | Description |
|--------------|-------------|
| **Additional file** | Another artifact to manage |
| **Secret management** | Must gitignore files with secrets |
| **Indirection** | Must open file to see current config |
| **Parsing overhead** | Requires YAML/JSON parsing library |

---

## Hybrid Approach (Recommended)

### Principle

Use the right method for each type of configuration:

| Configuration Type | Recommended Method | Rationale |
|-------------------|-------------------|-----------|
| **Credentials/Secrets** | Environment variables only | Security: not in history or process list |
| **Operational modes** | CLI args (env var fallback) | Explicitness: each run is self-documenting |
| **Rarely-changed settings** | Environment variables | Convenience: set once |

### Precedence Order

When both are specified, CLI arguments take precedence:

```
CLI argument > Environment variable > Default value
```

Example:
```bash
export TRADING_MODE=live
python crypto_trading_bot.py --trading-mode=whatif  # Uses whatif
```

### Implementation Pattern

```python
import argparse
import os

def get_config():
    parser = argparse.ArgumentParser(description='Trading Bot')
    
    # Operational modes: CLI with env fallback
    parser.add_argument(
        '--trading-mode',
        choices=['live', 'whatif'],
        default=os.environ.get('TRADING_MODE', 'live'),
        help='Trading mode (default: live, or TRADING_MODE env var)'
    )
    parser.add_argument(
        '--llm-mode',
        choices=['gemini', 'claude', 'openai', 'grok', 'perplexity', 'compare', 'integrate'],
        default=os.environ.get('LLM_MODE', 'compare'),
        help='LLM mode (default: compare, or LLM_MODE env var)'
    )
    
    # Credentials: env only (not exposed as CLI args)
    # These are read directly from os.environ in the code
    
    return parser.parse_args()
```

### User Experience

**Credentials (env vars only):**
```bash
# Set once in .env or .bashrc
export CLAUDE_API_KEY=sk-ant-xxx
export OPENAI_API_KEY=sk-xxx
export COINBASE_CREDENTIALS_FILE=./cdp_api_key.json
```

**Operational modes (CLI preferred, env fallback):**
```bash
# Explicit per-run (recommended)
python crypto_trading_bot.py --trading-mode=whatif --llm-mode=integrate

# Or use env var for session-wide default
export TRADING_MODE=whatif
python crypto_trading_bot.py  # Uses whatif from env

# CLI overrides env
python crypto_trading_bot.py --trading-mode=live  # Uses live despite env
```

**Help output:**
```
$ python crypto_trading_bot.py --help

usage: crypto_trading_bot.py [-h] [--trading-mode {live,whatif}] 
                            [--llm-mode {gemini,claude,...}]
                            [--coins COINS]

Trading Bot

optional arguments:
  -h, --help            show this help message and exit
  --trading-mode {live,whatif}
                        Trading mode (default: live, or TRADING_MODE env var)
  --llm-mode {gemini,claude,openai,grok,perplexity,compare,integrate}
                        LLM mode (default: compare, or LLM_MODE env var)
  --coins COINS         Comma-separated coins to analyze (or ANALYZE_COINS env var)
```

---

## Recommendations

### 1. Credentials and Secrets

**Use environment variables only.**

- API keys: `CLAUDE_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `PERPLEXITY_API_KEY`
- Credential files: `COINBASE_CREDENTIALS_FILE`
- Never expose these as command-line arguments

### 2. Operational Modes

**Support both CLI arguments and environment variables, with CLI taking precedence.**

| Setting | CLI Argument | Environment Variable | Default |
|---------|--------------|---------------------|---------|
| Trading mode | `--trading-mode` | `TRADING_MODE` | `live` |
| LLM mode | `--llm-mode` | `LLM_MODE` | `compare` |
| Coins to analyze | `--coins` | `ANALYZE_COINS` | (discovery) |
| Require consensus | `--require-consensus` | `REQUIRE_CONSENSUS` | `true` |
| Tiebreaker | `--tiebreaker` | `INTEGRATION_TIEBREAKER` | `gemini` |

### 3. Startup Banner

Always show current configuration at startup to avoid confusion:

```
=== TRADING BOT ===
Trading Mode: WHAT-IF (--trading-mode=whatif)
LLM Mode: integrate (from TRADING_MODE env var)
Coins: PEPE, BONK, SHIB (--coins)
Require Consensus: true (default)
```

### 4. Validation

Validate all inputs at startup and fail fast with clear error messages:

```
Error: Invalid --trading-mode value 'test'. Must be one of: live, whatif
```

---

## Migration Path

To implement this hybrid approach in the existing codebase:

1. Add `argparse` argument parsing
2. Keep existing `os.environ.get()` calls as fallback defaults
3. Update startup banner to show source of each setting
4. Document both methods in `OPERATIONS_MANUAL.md`

---

## Summary

| Configuration Type | Method | Rationale |
|-------------------|--------|-----------|
| Secrets/credentials | Env vars only | Security |
| Operational modes | CLI + env fallback | Explicitness + convenience |
| File paths | Either | User preference |
| Rarely-changed settings | Env vars | Convenience |

The hybrid approach provides:
- **Security** for credentials (env vars hidden from ps/history)
- **Explicitness** for operational modes (CLI shows intent per-run)
- **Convenience** for users who prefer env vars
- **Discoverability** via `--help`
- **Validation** with clear error messages
