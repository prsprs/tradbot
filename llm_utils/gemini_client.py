"""Gemini LLM client implementation."""

import os
from typing import Optional

from google import genai
from google.genai import types

from modelregistry import get_model

from .base import LLMClient


class GeminiClient(LLMClient):
    """Google Gemini LLM client."""

    def __init__(self):
        """Initialize the Gemini client."""
        api_key = os.environ.get('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")
        self.client = genai.Client()
        self.model = get_model('gemini')
        self.config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    
    @property
    def name(self) -> str:
        return "gemini"
    
    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        """Send a request to Gemini."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self.config,
            )
            return response.text if response else None
        except Exception as e:
            print(f"[ERROR] Gemini API error: {e}")
            return None
    
    def send_integrated_request(
        self, 
        prompt: str, 
        own_response: str,
        peer_analyses: str,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Send an integration request to Gemini."""
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
            response = self.client.models.generate_content(
                model=self.model,
                contents=integration_prompt,
                config=self.config,
            )
            return response.text if response else None
        except Exception as e:
            print(f"[ERROR] Gemini API error in integration: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if Gemini client is available."""
        return os.environ.get('GOOGLE_API_KEY') is not None
