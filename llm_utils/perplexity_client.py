"""Perplexity LLM client implementation."""

import os
from typing import Optional

import openai

from modelregistry import get_model

from .base import LLMClient


class PerplexityClient(LLMClient):
    """Perplexity AI LLM client with live web search."""

    def __init__(self):
        """Initialize the Perplexity client."""
        api_key = os.environ.get('PERPLEXITY_API_KEY')
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable not set")
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        self.model = get_model('perplexity')
    
    @property
    def name(self) -> str:
        return "perplexity"
    
    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        """Send a request to Perplexity."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[ERROR] Perplexity API error: {e}")
            return None
    
    def send_integrated_request(
        self, 
        prompt: str, 
        own_response: str,
        peer_analyses: str,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Send an integration request to Perplexity."""
        integration_prompt = f"""You previously analyzed this question:

{prompt}

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

Provide your updated analysis with reasoning."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": integration_prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[ERROR] Perplexity API error in integration: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if Perplexity client is available."""
        return os.environ.get('PERPLEXITY_API_KEY') is not None
