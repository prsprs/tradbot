"""LLM utility clients for the multi-LLM advisory system."""

from .base import LLMClient

# Lazy imports - clients are imported on demand to avoid requiring all dependencies
__all__ = [
    'LLMClient',
    'GeminiClient',
    'ClaudeClient',
    'OpenAIClient',
    'GrokClient',
    'PerplexityClient',
]

def __getattr__(name):
    """Lazy import of LLM clients."""
    if name == 'GeminiClient':
        from .gemini_client import GeminiClient
        return GeminiClient
    elif name == 'ClaudeClient':
        from .claude_client import ClaudeClient
        return ClaudeClient
    elif name == 'OpenAIClient':
        from .openai_client import OpenAIClient
        return OpenAIClient
    elif name == 'GrokClient':
        from .grok_client import GrokClient
        return GrokClient
    elif name == 'PerplexityClient':
        from .perplexity_client import PerplexityClient
        return PerplexityClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
