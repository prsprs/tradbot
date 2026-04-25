"""
Jupiter API Utility - Integration with Jupiter aggregator for Solana DEX swaps.

Features:
- Quote fetching with optimal routing
- Swap transaction building
- Price lookups
- Slippage configuration
- API key support (optional, recommended for production)
"""

import base64
import os
from typing import Dict, Optional, Tuple

import httpx

from .token_cache import get_mint_with_fallback, get_token_info, get_tokens, get_well_known_decimals

# Jupiter API endpoints (requires API key)
JUPITER_API_BASE = "https://api.jup.ag"
JUPITER_QUOTE_API = f"{JUPITER_API_BASE}/swap/v1"  # Quote uses v1
JUPITER_SWAP_API = f"{JUPITER_API_BASE}/swap/v2"   # Swap/build uses v2

# API key environment variable
JUPITER_API_KEY_ENV = "JUPITER_API_KEY"

# Default configuration
DEFAULT_SLIPPAGE_BPS = 100  # 1% default slippage
MAX_SLIPPAGE_BPS = 500  # 5% max slippage warning threshold

# SOL mint address (native wrapped SOL)
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Lamports per SOL
LAMPORTS_PER_SOL = 1_000_000_000


class JupiterClient:
    """Client for Jupiter DEX aggregator API."""
    
    def __init__(self, slippage_bps: int = DEFAULT_SLIPPAGE_BPS, api_key: str = None):
        """Initialize Jupiter client.
        
        Args:
            slippage_bps: Default slippage tolerance in basis points (100 = 1%).
            api_key: Jupiter API key. Falls back to JUPITER_API_KEY env var.
        """
        self.slippage_bps = slippage_bps
        self.timeout = 30.0
        self.api_key = api_key or os.environ.get(JUPITER_API_KEY_ENV)
        
        # Build default headers
        self.headers = {}
        if self.api_key:
            self.headers["x-api-key"] = self.api_key
            print(f"[JUPITER] API key configured")
        else:
            print(f"[JUPITER] No API key (set {JUPITER_API_KEY_ENV} env var for better rate limits)")
        
        if slippage_bps > MAX_SLIPPAGE_BPS:
            print(f"[JUPITER] Warning: High slippage setting ({slippage_bps/100}%)")
    
    def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: Optional[int] = None
    ) -> Optional[Dict]:
        """Get a swap quote from Jupiter.
        
        Args:
            input_mint: Input token mint address.
            output_mint: Output token mint address.
            amount: Amount in smallest units (lamports for SOL).
            slippage_bps: Optional slippage override.
        
        Returns:
            Quote response dictionary or None on error.
        """
        slippage = slippage_bps if slippage_bps is not None else self.slippage_bps
        
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                response = client.get(
                    f"{JUPITER_QUOTE_API}/quote",
                    params={
                        "inputMint": input_mint,
                        "outputMint": output_mint,
                        "amount": str(amount),
                        "slippageBps": slippage
                    }
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            print(f"[JUPITER] Quote error: {e}")
            return None
    
    def get_swap_transaction(
        self,
        quote: Dict,
        user_public_key: str,
        wrap_unwrap_sol: bool = True
    ) -> Optional[str]:
        """Get a swap transaction from Jupiter.
        
        Args:
            quote: Quote response from get_quote().
            user_public_key: User's Solana wallet address.
            wrap_unwrap_sol: Whether to automatically wrap/unwrap SOL.
        
        Returns:
            Base64-encoded transaction string or None on error.
        """
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                response = client.post(
                    f"{JUPITER_QUOTE_API}/swap",
                    json={
                        "quoteResponse": quote,
                        "userPublicKey": user_public_key,
                        "wrapAndUnwrapSol": wrap_unwrap_sol
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data.get("swapTransaction")
        except httpx.HTTPError as e:
            print(f"[JUPITER] Swap transaction error: {e}")
            return None
    
    def get_price(self, symbol: str) -> Optional[Tuple[float, float, float]]:
        """Get current price for a token symbol.
        
        Uses a small quote (1 USDC worth) to derive the current price.
        
        Args:
            symbol: Token symbol (e.g., 'BONK', 'WIF').
        
        Returns:
            Tuple of (price, bid, ask) in USD, or None if not found.
            Note: Jupiter doesn't provide bid/ask, so we return price for all three.
        """
        mint = get_mint_with_fallback(symbol)
        if not mint:
            print(f"[JUPITER] Unknown token symbol: {symbol}")
            return None
        
        # Special case: USDC is $1
        if mint == USDC_MINT:
            return (1.0, 1.0, 1.0)
        
        try:
            # Get price by quoting a small swap from USDC to the token
            # Use 1 USDC (1,000,000 units with 6 decimals)
            usdc_amount = 1_000_000
            
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                response = client.get(
                    f"{JUPITER_QUOTE_API}/quote",
                    params={
                        "inputMint": USDC_MINT,
                        "outputMint": mint,
                        "amount": str(usdc_amount),
                        "slippageBps": 50
                    }
                )
                response.raise_for_status()
                quote = response.json()
                
                # Calculate price: 1 USDC / output amount
                out_amount = int(quote.get("outAmount", 0))
                if out_amount == 0:
                    print(f"[JUPITER] Zero output for {symbol}")
                    return None
                
                # Get token decimals (prefer well-known, fallback to token info)
                decimals = get_well_known_decimals(symbol)
                if decimals is None:
                    token_info = get_token_info(symbol)
                    decimals = token_info.get("decimals", 9) if token_info else 9
                
                # Price = 1 USD / (out_amount / 10^decimals)
                token_amount = out_amount / (10 ** decimals)
                price = 1.0 / token_amount if token_amount > 0 else 0
                
                return (price, price, price)
                
        except httpx.HTTPError as e:
            print(f"[JUPITER] Price error for {symbol}: {e}")
            return None
        except Exception as e:
            print(f"[JUPITER] Price calculation error for {symbol}: {e}")
            return None
    
    def get_quote_for_symbol(
        self,
        input_symbol: str,
        output_symbol: str,
        amount: float,
        input_is_sol: bool = True
    ) -> Optional[Dict]:
        """Get a swap quote using token symbols.
        
        Args:
            input_symbol: Input token symbol (e.g., 'SOL').
            output_symbol: Output token symbol (e.g., 'BONK').
            amount: Amount in token units (not lamports).
            input_is_sol: If True, amount is in SOL; otherwise look up decimals.
        
        Returns:
            Quote response with additional parsed fields.
        """
        input_mint = get_mint_with_fallback(input_symbol)
        output_mint = get_mint_with_fallback(output_symbol)
        
        if not input_mint:
            print(f"[JUPITER] Unknown input token: {input_symbol}")
            return None
        if not output_mint:
            print(f"[JUPITER] Unknown output token: {output_symbol}")
            return None
        
        # Convert to smallest units
        if input_is_sol or input_symbol.upper() == "SOL":
            amount_lamports = int(amount * LAMPORTS_PER_SOL)
        else:
            # Look up decimals from token info
            token_info = get_token_info(input_symbol)
            if token_info:
                decimals = token_info.get("decimals", 9)
                amount_lamports = int(amount * (10 ** decimals))
            else:
                # Default to 9 decimals
                amount_lamports = int(amount * LAMPORTS_PER_SOL)
        
        quote = self.get_quote(input_mint, output_mint, amount_lamports)
        
        if quote:
            # Add parsed fields for convenience
            quote["_input_symbol"] = input_symbol.upper()
            quote["_output_symbol"] = output_symbol.upper()
            quote["_input_amount"] = amount
            
            # Parse output amount
            out_amount = int(quote.get("outAmount", 0))
            output_info = get_token_info(output_symbol)
            if output_info:
                out_decimals = output_info.get("decimals", 9)
                quote["_output_amount"] = out_amount / (10 ** out_decimals)
            else:
                quote["_output_amount"] = out_amount / LAMPORTS_PER_SOL
        
        return quote
    
    def format_quote_summary(self, quote: Dict) -> str:
        """Format a quote for display.
        
        Args:
            quote: Quote response with parsed fields.
        
        Returns:
            Human-readable summary string.
        """
        if not quote:
            return "No quote available"
        
        input_sym = quote.get("_input_symbol", "?")
        output_sym = quote.get("_output_symbol", "?")
        input_amt = quote.get("_input_amount", 0)
        output_amt = quote.get("_output_amount", 0)
        
        # Price impact
        price_impact = float(quote.get("priceImpactPct", 0))
        
        # Route info
        route_plan = quote.get("routePlan", [])
        num_hops = len(route_plan)
        
        summary = f"{input_amt} {input_sym} → {output_amt:.6f} {output_sym}"
        summary += f" | Impact: {price_impact:.2f}%"
        summary += f" | Hops: {num_hops}"
        
        return summary


def symbol_to_mint(symbol: str) -> Optional[str]:
    """Convert a token symbol to its mint address.
    
    Args:
        symbol: Token symbol (e.g., 'BONK').
    
    Returns:
        Mint address or None.
    """
    return get_mint_with_fallback(symbol)


def sol_to_lamports(sol: float) -> int:
    """Convert SOL to lamports."""
    return int(sol * LAMPORTS_PER_SOL)


def lamports_to_sol(lamports: int) -> float:
    """Convert lamports to SOL."""
    return lamports / LAMPORTS_PER_SOL
