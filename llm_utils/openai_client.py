"""OpenAI LLM client implementation."""

import os
from typing import Optional

import openai

from .base import LLMClient


class OpenAIClient(LLMClient):
    """OpenAI GPT LLM client."""
    
    def __init__(self):
        """Initialize the OpenAI client."""
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self.client = openai.OpenAI(api_key=api_key)
        self.model = "gpt-5.5"
    
    @property
    def name(self) -> str:
        return "openai"
    
    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        """Send a request to OpenAI."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[ERROR] OpenAI API error: {e}")
            return None
    
    def send_integrated_request(
        self, 
        prompt: str, 
        own_response: str,
        peer_analyses: str,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Send an integration request to OpenAI."""
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
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": integration_prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[ERROR] OpenAI API error in integration: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if OpenAI client is available."""
        return os.environ.get('OPENAI_API_KEY') is not None
