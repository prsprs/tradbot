"""Configuration management for the multi-LLM advisory system."""

import argparse
import os
from dataclasses import dataclass, field
from typing import List, Optional


COST_PRESETS = {
    'minimal': {
        'MAX_RESPONSE_WORDS': 150,
        'MAX_REASONING_POINTS': 2,
        'SUMMARIZATION_MAX_WORDS': 250,
        'SIMPLE_INTEGRATION': True,
        'ROUND_TWO_OUTPUT_LIMIT': 100,
    },
    'balanced': {
        'MAX_RESPONSE_WORDS': 300,
        'MAX_REASONING_POINTS': 3,
        'SUMMARIZATION_MAX_WORDS': 500,
        'SIMPLE_INTEGRATION': False,
        'ROUND_TWO_OUTPUT_LIMIT': 200,
    },
    'detailed': {
        'MAX_RESPONSE_WORDS': 600,
        'MAX_REASONING_POINTS': 5,
        'SUMMARIZATION_MAX_WORDS': 1000,
        'SIMPLE_INTEGRATION': False,
        'ROUND_TWO_OUTPUT_LIMIT': 400,
    }
}

AVAILABLE_LLMS = ['gemini', 'claude', 'openai', 'grok', 'perplexity']


@dataclass
class Config:
    """Configuration for the multi-LLM advisory system."""
    
    # Core parameters
    prompt: str = ""
    prompt_file: Optional[str] = None
    reference_files: List[str] = field(default_factory=list)
    choices: List[str] = field(default_factory=list)
    mode: str = "single"  # single, compare, integrate
    
    # LLM selection
    primary_llm: str = "gemini"
    compare_llms: List[str] = field(default_factory=lambda: ['gemini', 'claude', 'openai', 'grok', 'perplexity'])
    integration_tiebreaker: str = "gemini"
    summarization_llm: str = "gemini"
    
    # Yes/No evaluation
    yes_no_eval: bool = False
    require_consensus: bool = False
    
    # Integration options
    simple_integration: bool = False
    log_integration_rounds: bool = False
    show_reasoning: bool = True
    
    # Cost control
    max_response_words: int = 300
    round_two_output_limit: int = 200
    max_reasoning_points: int = 3
    summarization_max_words: int = 500
    verbose_mode: bool = False
    what_if_mode: bool = False
    
    # Context
    google_trends_keyword: Optional[str] = None
    
    # Output
    output_format: str = "text"  # text, json, markdown
    history_file: str = "./history/recommendations.json"
    
    # File context limits
    max_file_context_size: int = 50000
    max_total_reference_size: int = 150000


def parse_args() -> Config:
    """Parse command-line arguments and environment variables into Config."""
    parser = argparse.ArgumentParser(
        description='Multi-LLM Advisory System - Compare and integrate LLM perspectives',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python llm_compare.py --prompt "Should I learn Rust or Go?" --choices "Rust,Go" --mode compare
  python llm_compare.py --prompt "Will interest rates decrease?" --yes-no-eval --mode integrate
  python llm_compare.py --prompt-file ./questions/decision.txt --mode integrate
  
Environment variables can also be used (CLI takes precedence):
  PROMPT, MODE, PRIMARY_LLM, COMPARE_LLMS, GOOGLE_TRENDS_KEYWORD, etc.
"""
    )
    
    # Prompt input
    parser.add_argument(
        '--prompt',
        default=os.environ.get('PROMPT', ''),
        help='The question or decision to evaluate'
    )
    parser.add_argument(
        '--prompt-file',
        default=os.environ.get('PROMPT_FILE'),
        help='Path to file containing prompt'
    )
    parser.add_argument(
        '--reference-files',
        default=os.environ.get('REFERENCE_FILES', ''),
        help='Comma-separated list of file paths to include as context'
    )
    parser.add_argument(
        '--choices',
        default=os.environ.get('CHOICES', ''),
        help='Comma-separated list of choices for decision questions'
    )
    
    # Mode selection
    parser.add_argument(
        '--mode',
        choices=['single', 'compare', 'integrate'],
        default=os.environ.get('MODE', 'single').lower(),
        help='Operating mode: single, compare, integrate (default: single)'
    )
    
    # LLM selection
    parser.add_argument(
        '--primary-llm',
        choices=AVAILABLE_LLMS,
        default=os.environ.get('PRIMARY_LLM', 'gemini').lower(),
        help='Primary LLM for single mode or tiebreaker (default: gemini)'
    )
    parser.add_argument(
        '--llms',
        default=os.environ.get('COMPARE_LLMS', 'gemini,claude,openai,grok,perplexity'),
        help='Comma-separated list of LLMs to use in compare/integrate mode'
    )
    parser.add_argument(
        '--tiebreaker',
        choices=AVAILABLE_LLMS + ['none'],
        default=os.environ.get('INTEGRATION_TIEBREAKER', 'gemini').lower(),
        help='Tiebreaker LLM when no consensus (default: gemini)'
    )
    parser.add_argument(
        '--summarization-llm',
        choices=AVAILABLE_LLMS,
        default=os.environ.get('SUMMARIZATION_LLM', 'gemini').lower(),
        help='LLM to use for final summarization (default: gemini)'
    )
    
    # Yes/No evaluation
    parser.add_argument(
        '--yes-no-eval',
        action='store_true',
        default=os.environ.get('YES_NO_EVAL', 'NO').upper() == 'YES',
        help='Enable Yes/No evaluation mode (YES/NO/UNKNOWN answers)'
    )
    parser.add_argument(
        '--require-consensus',
        action='store_true',
        default=os.environ.get('REQUIRE_CONSENSUS', 'false').lower() == 'true',
        help='Require LLM consensus for final answer'
    )
    
    # Integration options
    parser.add_argument(
        '--simple-integration',
        action='store_true',
        default=os.environ.get('SIMPLE_INTEGRATION', 'NO').upper() == 'YES',
        help='Only integrate primary LLM output (reduces cost)'
    )
    parser.add_argument(
        '--log-rounds',
        action='store_true',
        default=os.environ.get('LOG_INTEGRATION_ROUNDS', 'false').lower() == 'true',
        help='Log full responses from each round'
    )
    parser.add_argument(
        '--show-reasoning',
        action='store_true',
        default=os.environ.get('SHOW_REASONING', 'true').lower() == 'true',
        help='Display reasoning from each LLM response (default: true)'
    )
    parser.add_argument(
        '--no-reasoning',
        action='store_true',
        help='Hide reasoning from LLM responses'
    )
    
    # Cost control
    parser.add_argument(
        '--max-response-words',
        type=int,
        default=int(os.environ.get('MAX_RESPONSE_WORDS', '300')),
        help='Word limit for LLM responses (default: 300)'
    )
    parser.add_argument(
        '--round-two-limit',
        type=int,
        default=int(os.environ.get('ROUND_TWO_OUTPUT_LIMIT', '200')),
        help='Word limit for Round 2 integration responses (default: 200)'
    )
    parser.add_argument(
        '--max-reasoning-points',
        type=int,
        default=int(os.environ.get('MAX_REASONING_POINTS', '3')),
        help='Max reasoning bullet points (default: 3)'
    )
    parser.add_argument(
        '--summarization-max-words',
        type=int,
        default=int(os.environ.get('SUMMARIZATION_MAX_WORDS', '500')),
        help='Word limit for final summary (default: 500)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        default=os.environ.get('VERBOSE_MODE', 'NO').upper() == 'YES',
        help='Ignore word limits for detailed output'
    )
    parser.add_argument(
        '--what-if',
        action='store_true',
        default=os.environ.get('WHAT_IF_MODE', 'NO').upper() == 'YES',
        help='Estimate cost without making LLM calls'
    )
    parser.add_argument(
        '--cost-preset',
        choices=['minimal', 'balanced', 'detailed'],
        default=os.environ.get('COST_PRESET'),
        help='Use predefined cost settings'
    )
    
    # Context
    parser.add_argument(
        '--google-trends-keyword',
        default=os.environ.get('GOOGLE_TRENDS_KEYWORD'),
        help='Keyword for Google Trends context'
    )
    
    # Output
    parser.add_argument(
        '--output-format',
        choices=['text', 'json', 'markdown'],
        default=os.environ.get('OUTPUT_FORMAT', 'text').lower(),
        help='Output format: text, json, markdown (default: text)'
    )
    parser.add_argument(
        '--history-file',
        default=os.environ.get('HISTORY_FILE', './history/recommendations.json'),
        help='Path to recommendations history file'
    )
    
    args = parser.parse_args()
    
    # Build config from args
    config = Config()
    
    # Apply cost preset first if specified
    if args.cost_preset and args.cost_preset in COST_PRESETS:
        preset = COST_PRESETS[args.cost_preset]
        config.max_response_words = preset['MAX_RESPONSE_WORDS']
        config.max_reasoning_points = preset['MAX_REASONING_POINTS']
        config.summarization_max_words = preset['SUMMARIZATION_MAX_WORDS']
        config.simple_integration = preset['SIMPLE_INTEGRATION']
        config.round_two_output_limit = preset['ROUND_TWO_OUTPUT_LIMIT']
    
    # Load prompt from file if specified
    if args.prompt_file:
        config.prompt_file = args.prompt_file
        try:
            with open(args.prompt_file, 'r') as f:
                config.prompt = f.read().strip()
        except Exception as e:
            raise ValueError(f"Could not read prompt file: {e}")
    else:
        config.prompt = args.prompt
    
    # Parse reference files
    if args.reference_files:
        config.reference_files = [f.strip() for f in args.reference_files.split(',') if f.strip()]
    
    # Parse choices
    if args.choices:
        config.choices = [c.strip() for c in args.choices.split(',') if c.strip()]
    
    # Parse LLMs list
    config.compare_llms = [llm.strip().lower() for llm in args.llms.split(',') if llm.strip()]
    
    # Copy remaining args
    config.mode = args.mode
    config.primary_llm = args.primary_llm
    config.integration_tiebreaker = args.tiebreaker
    config.summarization_llm = args.summarization_llm
    config.yes_no_eval = args.yes_no_eval
    config.require_consensus = args.require_consensus
    config.simple_integration = args.simple_integration if not args.cost_preset else config.simple_integration
    config.log_integration_rounds = args.log_rounds
    config.show_reasoning = args.show_reasoning and not args.no_reasoning
    config.verbose_mode = args.verbose
    config.what_if_mode = args.what_if
    config.google_trends_keyword = args.google_trends_keyword
    config.output_format = args.output_format
    config.history_file = args.history_file
    
    # Override cost params only if not using preset or explicitly set
    if not args.cost_preset:
        config.max_response_words = args.max_response_words
        config.round_two_output_limit = args.round_two_limit
        config.max_reasoning_points = args.max_reasoning_points
        config.summarization_max_words = args.summarization_max_words
    
    return config


def estimate_cost(config: Config) -> dict:
    """Estimate API costs based on configuration."""
    
    # Rough token estimates per call
    input_tokens_per_call = 500 + (config.max_response_words * 1.5)
    output_tokens_per_call = config.max_response_words * 1.5
    
    num_llms = len(config.compare_llms)
    
    if config.mode == 'single':
        num_calls = 1
    elif config.mode == 'compare':
        num_calls = num_llms
    elif config.mode == 'integrate':
        if config.simple_integration:
            num_calls = num_llms + 1  # 1 primary + (N-1) reflections + 1 summarization
        else:
            num_calls = (num_llms * 2) + 1  # Round 1 + Round 2 + summarization
    else:
        num_calls = 1
    
    # Summarization call (for integrate mode)
    summarization_input = 0
    summarization_output = 0
    if config.mode == 'integrate':
        summarization_input = num_calls * config.max_response_words * 1.5
        summarization_output = config.summarization_max_words * 1.5
    
    total_input_tokens = int((input_tokens_per_call * num_calls) + summarization_input)
    total_output_tokens = int((output_tokens_per_call * num_calls) + summarization_output)
    
    # Cost varies by provider - rough average
    estimated_cost = (total_input_tokens * 0.00001) + (total_output_tokens * 0.00003)
    
    return {
        'mode': config.mode,
        'num_llms': num_llms,
        'num_calls': num_calls,
        'simple_integration': config.simple_integration,
        'estimated_input_tokens': total_input_tokens,
        'estimated_output_tokens': total_output_tokens,
        'estimated_cost_usd': round(estimated_cost, 4)
    }


def validate_config(config: Config) -> List[str]:
    """Validate configuration and return list of errors."""
    errors = []
    
    if not config.prompt:
        errors.append("No prompt provided. Use --prompt or --prompt-file")
    
    if config.mode in ['compare', 'integrate'] and len(config.compare_llms) < 2:
        errors.append(f"Compare/integrate mode requires at least 2 LLMs, got {len(config.compare_llms)}")
    
    for llm in config.compare_llms:
        if llm not in AVAILABLE_LLMS:
            errors.append(f"Unknown LLM: {llm}. Available: {AVAILABLE_LLMS}")
    
    if config.primary_llm not in AVAILABLE_LLMS:
        errors.append(f"Unknown primary LLM: {config.primary_llm}")
    
    if config.integration_tiebreaker not in AVAILABLE_LLMS + ['none']:
        errors.append(f"Unknown tiebreaker LLM: {config.integration_tiebreaker}")
    
    for ref_file in config.reference_files:
        if not os.path.exists(ref_file):
            errors.append(f"Reference file not found: {ref_file}")
    
    return errors
