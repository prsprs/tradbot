"""Claude LLM client implementation."""

import os
from typing import Optional

import anthropic

from .base import LLMClient


class ClaudeClient(LLMClient):
    """Anthropic Claude LLM client."""
    
    def __init__(self):
        """Initialize the Claude client."""
        api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY or CLAUDE_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-opus-4-8"
    
    @property
    def name(self) -> str:
        return "claude"
    
    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        """Send a request to Claude."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return next((b.text for b in message.content if b.type == "text"), "")
        except Exception as e:
            print(f"[ERROR] Claude API error: {e}")
            return None
    
    def send_integrated_request(
        self, 
        prompt: str, 
        own_response: str,
        peer_analyses: str,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Send an integration request to Claude."""
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
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": integration_prompt}
                ]
            )
            return next((b.text for b in message.content if b.type == "text"), "")
        except Exception as e:
            print(f"[ERROR] Claude API error in integration: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if Claude client is available."""
        return (os.environ.get('ANTHROPIC_API_KEY') is not None or 
                os.environ.get('CLAUDE_API_KEY') is not None)
