"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod
from typing import Optional


class LLMClient(ABC):
    """Abstract base class for LLM clients.
    
    All LLM implementations must implement send_request() and send_integrated_request().
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this LLM client."""
        pass
    
    @abstractmethod
    def send_request(self, prompt: str, max_tokens: int = 4096) -> Optional[str]:
        """Send a request to the LLM and return the response text.
        
        Args:
            prompt: The prompt to send to the LLM
            max_tokens: Maximum tokens for the response
            
        Returns:
            The LLM's response text, or None if the request failed
        """
        pass
    
    @abstractmethod
    def send_integrated_request(
        self, 
        prompt: str, 
        own_response: str,
        peer_analyses: str,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Send an integration request where the LLM reflects on peer analyses.
        
        Args:
            prompt: The original user prompt
            own_response: This LLM's original response
            peer_analyses: Formatted string of other LLMs' analyses
            max_tokens: Maximum tokens for the response
            
        Returns:
            The LLM's integrated response text, or None if the request failed
        """
        pass
    
    def is_available(self) -> bool:
        """Check if this LLM client is properly configured and available.
        
        Returns:
            True if the client can be used, False otherwise
        """
        return True
