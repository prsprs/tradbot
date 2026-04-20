"""Grok LLM client implementation."""

import os
from typing import Optional

import openai

from .base import LLMClient


class GrokClient(LLMClient):
    """xAI Grok LLM client."""
    
    def __init__(self):
        """Initialize the Grok client."""
        api_key = os.environ.get('XAI_API_KEY')
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set")
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )
        self.model = "grok-4"
        self.tools = [{"type": "web_search"}]
    
    @property
    def name(self) -> str:
        return "grok"
    
    def _call_responses_api(self, content: str) -> Optional[str]:
        """Call the xAI Responses API with web search enabled."""
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[{"role": "user", "content": content}],
                tools=self.tools
            )
            if hasattr(response, 'output_text'):
                return response.output_text
            elif hasattr(response, 'output') and response.output:
                for item in response.output:
                    if hasattr(item, 'content'):
                        return item.content
            return str(response)
        except Exception as e:
            print(f"[ERROR] Grok API error: {e}")
            return None
    
    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        """Send a request to Grok."""
        return self._call_responses_api(prompt)
    
    def send_integrated_request(
        self, 
        prompt: str, 
        own_response: str,
        peer_analyses: str,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Send an integration request to Grok."""
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

        return self._call_responses_api(integration_prompt)
    
    def is_available(self) -> bool:
        """Check if Grok client is available."""
        return os.environ.get('XAI_API_KEY') is not None
