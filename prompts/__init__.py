"""Prompt templates for the multi-LLM advisory system."""

from .templates import (
    get_base_prompt,
    get_integration_prompt,
    get_summarization_prompt,
    get_yes_no_output_instructions,
    get_open_ended_output_instructions,
    get_word_limit_instructions,
)

__all__ = [
    'get_base_prompt',
    'get_integration_prompt',
    'get_summarization_prompt',
    'get_yes_no_output_instructions',
    'get_open_ended_output_instructions',
    'get_word_limit_instructions',
]
