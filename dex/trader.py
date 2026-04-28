"""
Solana DEX Trader - Main trading interface for Solana DEX via Jupiter.

This class provides a similar interface to BlobbyTrader (CEX) for consistency,
allowing the main trading bot to switch between CEX and DEX modes seamlessly.

For live trading, uses interactive private key prompt (more secure than env vars).
For what-if mode, no wallet is needed.
"""

import asyncio
import os
from typing import Dict, List, Optional, Tuple

from .jupiterutil import JupiterClient, SOL_MINT, LAMPORTS_PER_SOL, sol_to_lamports
from .token_cache import (
    get_tokens,
    get_mint_with_fallback,
    list_all_tokens,
    refresh_token_cache,
    get_cache_age,
)
from .local_wallet import LocalWallet, get_wallet_interactive, get_wallet_for_whatif

# Default trade amount in SOL
DEFAULT_TRADE_AMOUNT_SOL = 0.1

# Rate limiting: minimum seconds between trades
MIN_TRADE_INTERVAL = 60


class SolanaDEXTrader:
    """Solana DEX trader using Jupiter aggregator and local keypair.
    
    This class provides a similar interface to BlobbyTrader for CEX trading,
    making it easy to switch between modes in the main trading bot.
    
    For live trading, prompts for private key at startup (secure, in-memory only).
    For what-if mode, no wallet is needed.
    """
    
    def __init__(
        self,
        slippage_bps: int = 100,
        live_mode: bool = False
    ):
        """Initialize the Solana DEX trader.
        
        Args:
            slippage_bps: Slippage tolerance in basis points (100 = 1%).
            live_mode: If True, prompt for private key for live trading.
        """
        self.jupiter = JupiterClient(slippage_bps=slippage_bps)
        self.slippage_bps = slippage_bps
        self._last_trade_time = 0
        self._tokens = None
        
        # Initialize wallet based on mode
        if live_mode:
            self.wallet = get_wallet_interactive()
        else:
            self.wallet = get_wallet_for_whatif()
        
        print(f"[DEX] SolanaDEXTrader initialized (slippage: {slippage_bps/100}%)")
    
    def is_connected(self) -> bool:
        """Check if wallet keypair is loaded."""
        return self.wallet.is_loaded()
    
    def get_wallet_address(self) -> Optional[str]:
        """Get wallet address."""
        return self.wallet.get_address()
    
    def test_wallet_connection(self) -> bool:
        """Test wallet connection by checking SOL balance via RPC.
        
        Returns:
            True if connection successful, False otherwise.
        """
        import httpx
        
        if not self.wallet.is_loaded():
            print("[DEX] ✗ No wallet loaded")
            return False
        
        pubkey = self.wallet.get_address()
        if not pubkey:
            print("[DEX] ✗ Could not get wallet address")
            return False
        
        print("[DEX] Testing wallet connection...")
        
        # Truncate pubkey for display (first 4 + last 4 chars)
        pubkey_short = f"{pubkey[:4]}...{pubkey[-4:]}"
        print(f"[DEX] Wallet: {pubkey_short}")
        
        # Get SOL balance via Solana RPC
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [pubkey]
            }
            
            with httpx.Client(timeout=15.0) as client:
                response = client.post(rpc_url, json=payload)
                response.raise_for_status()
                result = response.json()
            
            if "error" in result:
                error = result["error"]
                print(f"[DEX] ✗ RPC error: {error.get('message', 'Unknown error')}")
                return False
            
            lamports = result.get("result", {}).get("value", 0)
            sol_balance = lamports / LAMPORTS_PER_SOL
            
            print(f"[DEX] Balance: {sol_balance:.4f} SOL")
            
            if sol_balance == 0:
                print("[DEX] ⚠️  Wallet has no SOL - trades will fail (need SOL for fees)")
            elif sol_balance < 0.01:
                print("[DEX] ⚠️  Low SOL balance - may not cover transaction fees")
            
            print("[DEX] ✓ Wallet connected successfully")
            return True
            
        except httpx.HTTPError as e:
            print(f"[DEX] ✗ Cannot connect to Solana RPC: {e}")
            return False
        except Exception as e:
            print(f"[DEX] ✗ Wallet test failed: {e}")
            return False
    
    def _ensure_tokens(self):
        """Ensure token list is loaded."""
        if self._tokens is None:
            self._tokens = get_tokens()
    
    def list_all_coins(self) -> List[str]:
        """List all tradeable token symbols from Jupiter verified list.
        
        Returns:
            List of token symbols (e.g., ['BONK', 'WIF', 'POPCAT', ...]).
        """
        return list_all_tokens()
    
    def get_product_details(self, product_id: str) -> Optional[Dict]:
        """Get token details (similar to Coinbase product details).
        
        Args:
            product_id: Product ID in format "SYMBOL-USD" or just "SYMBOL".
        
        Returns:
            Dictionary with price, symbol, and other info, or None.
        """
        # Parse product_id (handle both "BONK-USD" and "BONK" formats)
        symbol = product_id.replace("-USD", "").replace("-SOL", "").upper()
        
        price_data = self.jupiter.get_price(symbol)
        if not price_data:
            return None
        
        price, bid, ask = price_data
        
        # Return object-like dict with attribute access for compatibility
        class ProductDetails:
            def __init__(self, data):
                self.__dict__.update(data)
            def to_dict(self):
                return self.__dict__
        
        return ProductDetails({
            "product_id": f"{symbol}-USD",
            "base_currency_id": symbol,
            "quote_currency_id": "USD",
            "price": price,
            "bid": bid,
            "ask": ask,
            "exchange": "solana-dex"
        })
    
    def get_price(self, symbol: str) -> Optional[Tuple[float, float, float]]:
        """Get current price for a token.
        
        Args:
            symbol: Token symbol (e.g., 'BONK').
        
        Returns:
            Tuple of (price, bid, ask) in USD, or None.
        """
        return self.jupiter.get_price(symbol)
    
    def get_quote(
        self,
        input_symbol: str,
        output_symbol: str,
        amount: float
    ) -> Optional[Dict]:
        """Get a swap quote.
        
        Args:
            input_symbol: Input token symbol (e.g., 'SOL').
            output_symbol: Output token symbol (e.g., 'BONK').
            amount: Amount of input token.
        
        Returns:
            Quote dictionary or None.
        """
        return self.jupiter.get_quote_for_symbol(input_symbol, output_symbol, amount)
    
    def execute_buy(
        self,
        symbol: str,
        amount_sol: float = DEFAULT_TRADE_AMOUNT_SOL,
        whatif: bool = False
    ) -> Optional[Dict]:
        """Execute a buy order (swap SOL for token).
        
        Args:
            symbol: Token symbol to buy (e.g., 'BONK').
            amount_sol: Amount of SOL to spend.
            whatif: If True, get quote only without executing.
        
        Returns:
            Result dictionary with quote and transaction info, or None on error.
        """
        symbol = symbol.upper()
        
        # Can't buy SOL with SOL (circular swap)
        if symbol == "SOL":
            print(f"\n[DEX] Skipping SOL: Cannot buy SOL with SOL (it's the base currency)")
            return None
        
        print(f"\n[DEX] {'Simulating' if whatif else 'Executing'} BUY: {amount_sol} SOL → {symbol}")
        
        # Get quote
        quote = self.jupiter.get_quote_for_symbol("SOL", symbol, amount_sol)
        if not quote:
            print(f"[DEX] Failed to get quote for {symbol}")
            return None
        
        print(f"[DEX] Quote: {self.jupiter.format_quote_summary(quote)}")
        
        result = {
            "action": "BUY",
            "input_symbol": "SOL",
            "output_symbol": symbol,
            "input_amount": amount_sol,
            "output_amount": quote.get("_output_amount", 0),
            "quote": quote,
            "executed": False,
            "whatif": whatif,
            "exchange": "solana-dex"
        }
        
        if whatif:
            print(f"[DEX] What-if mode: Skipping execution")
            return result
        
        # Check wallet is loaded
        if not self.is_connected():
            print("[DEX] Error: Wallet not loaded")
            print("[DEX] Run with --trading-mode=live to enter private key")
            return result
        
        # Get swap transaction
        wallet_address = self.get_wallet_address()
        swap_tx = self.jupiter.get_swap_transaction(quote, wallet_address)
        if not swap_tx:
            print("[DEX] Failed to get swap transaction")
            return result
        
        # Sign and submit transaction
        signature = self._sign_and_submit(swap_tx)
        if signature:
            result["executed"] = True
            result["signature"] = signature
            result["tx_url"] = f"https://solscan.io/tx/{signature}"
            print(f"[DEX] ✓ BUY executed: {signature}")
        else:
            print("[DEX] ✗ Transaction not executed")
        
        return result
    
    def execute_sell(
        self,
        symbol: str,
        amount: float,
        whatif: bool = False
    ) -> Optional[Dict]:
        """Execute a sell order (swap token for SOL).
        
        Args:
            symbol: Token symbol to sell (e.g., 'BONK').
            amount: Amount of token to sell.
            whatif: If True, get quote only without executing.
        
        Returns:
            Result dictionary with quote and transaction info, or None on error.
        """
        symbol = symbol.upper()
        print(f"\n[DEX] {'Simulating' if whatif else 'Executing'} SELL: {amount} {symbol} → SOL")
        
        # Get quote
        quote = self.jupiter.get_quote_for_symbol(symbol, "SOL", amount)
        if not quote:
            print(f"[DEX] Failed to get quote for {symbol}")
            return None
        
        print(f"[DEX] Quote: {self.jupiter.format_quote_summary(quote)}")
        
        result = {
            "action": "SELL",
            "input_symbol": symbol,
            "output_symbol": "SOL",
            "input_amount": amount,
            "output_amount": quote.get("_output_amount", 0),
            "quote": quote,
            "executed": False,
            "whatif": whatif,
            "exchange": "solana-dex"
        }
        
        if whatif:
            print(f"[DEX] What-if mode: Skipping execution")
            return result
        
        # Check wallet is loaded
        if not self.is_connected():
            print("[DEX] Error: Wallet not loaded")
            print("[DEX] Run with --trading-mode=live to enter private key")
            return result
        
        # Get swap transaction
        wallet_address = self.get_wallet_address()
        swap_tx = self.jupiter.get_swap_transaction(quote, wallet_address)
        if not swap_tx:
            print("[DEX] Failed to get swap transaction")
            return result
        
        # Sign and submit transaction
        signature = self._sign_and_submit(swap_tx)
        if signature:
            result["executed"] = True
            result["signature"] = signature
            result["tx_url"] = f"https://solscan.io/tx/{signature}"
            print(f"[DEX] ✓ SELL executed: {signature}")
        else:
            print("[DEX] ✗ Transaction not executed")
        
        return result
    
    def _sign_and_submit(self, swap_tx_base64: str) -> Optional[str]:
        """Sign and submit a swap transaction.
        
        Args:
            swap_tx_base64: Base64-encoded transaction from Jupiter.
        
        Returns:
            Transaction signature or None on error.
        """
        import base64
        
        try:
            # Decode transaction
            tx_bytes = base64.b64decode(swap_tx_base64)
            
            # Sign with local wallet
            signed_tx = self.wallet.sign_transaction(tx_bytes)
            if not signed_tx:
                print("[DEX] Failed to sign transaction")
                return None
            
            # Submit to Solana RPC
            signature = self._submit_transaction(signed_tx)
            return signature
            
        except Exception as e:
            print(f"[DEX] Transaction error: {e}")
            return None
    
    def _submit_transaction(self, signed_tx: bytes) -> Optional[str]:
        """Submit signed transaction to Solana RPC.
        
        Args:
            signed_tx: Signed transaction bytes.
        
        Returns:
            Transaction signature or None on error.
        """
        import base64
        import httpx
        
        # Use public Solana RPC (can be configured via env var)
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        
        try:
            tx_base64 = base64.b64encode(signed_tx).decode('utf-8')
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    tx_base64,
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                        "maxRetries": 3
                    }
                ]
            }
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(rpc_url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if "error" in result:
                    error = result["error"]
                    print(f"\n[DEX] ========== RPC ERROR ==========")
                    print(f"[DEX] Code: {error.get('code', 'N/A')}")
                    print(f"[DEX] Message: {error.get('message', 'Unknown error')}")
                    # Log detailed data if present (contains simulation logs)
                    if "data" in error:
                        data = error["data"]
                        if isinstance(data, dict):
                            if "logs" in data:
                                print(f"[DEX] Simulation logs:")
                                for log in data["logs"][:10]:  # First 10 log lines
                                    print(f"[DEX]   {log}")
                                if len(data.get("logs", [])) > 10:
                                    print(f"[DEX]   ... ({len(data['logs']) - 10} more lines)")
                            if "err" in data:
                                print(f"[DEX] Error detail: {data['err']}")
                        else:
                            print(f"[DEX] Data: {data}")
                    print(f"[DEX] ================================\n")
                    return None
                
                signature = result.get("result")
                if signature:
                    print(f"[DEX] Transaction submitted: {signature[:16]}...")
                    print(f"[DEX] https://solscan.io/tx/{signature}")
                    return signature
                
                return None
                
        except httpx.HTTPError as e:
            print(f"\n[DEX] ========== HTTP ERROR ==========")
            print(f"[DEX] Request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[DEX] Status: {e.response.status_code}")
                print(f"[DEX] Response: {e.response.text[:500]}")
            print(f"[DEX] ==================================\n")
            return None
        except Exception as e:
            print(f"\n[DEX] ========== UNEXPECTED ERROR ==========")
            print(f"[DEX] Type: {type(e).__name__}")
            print(f"[DEX] Message: {e}")
            print(f"[DEX] ========================================\n")
            return None
    
    def market_order_buy(
        self,
        product_id: str,
        quote_size: str,
        whatif: bool = False
    ) -> Optional[Dict]:
        """Place a market buy order (Coinbase-compatible interface).
        
        Args:
            product_id: Product ID (e.g., 'BONK-USD').
            quote_size: Amount in quote currency (USD value as string).
            whatif: If True, simulate only.
        
        Returns:
            Order result dictionary.
        """
        # Parse product_id and convert USD to SOL
        symbol = product_id.replace("-USD", "").replace("-SOL", "").upper()
        
        # Get SOL price to convert USD to SOL
        sol_price = self.jupiter.get_price("SOL")
        if not sol_price:
            print("[DEX] Failed to get SOL price")
            return None
        
        usd_amount = float(quote_size)
        sol_amount = usd_amount / sol_price[0]
        
        print(f"[DEX] Converting ${usd_amount} to {sol_amount:.4f} SOL")
        
        return self.execute_buy(symbol, sol_amount, whatif=whatif)
    
    def market_order_sell(
        self,
        product_id: str,
        base_size: str,
        whatif: bool = False
    ) -> Optional[Dict]:
        """Place a market sell order (Coinbase-compatible interface).
        
        Args:
            product_id: Product ID (e.g., 'BONK-USD').
            base_size: Amount in base currency (token amount as string).
            whatif: If True, simulate only.
        
        Returns:
            Order result dictionary.
        """
        symbol = product_id.replace("-USD", "").replace("-SOL", "").upper()
        amount = float(base_size)
        
        return self.execute_sell(symbol, amount, whatif=whatif)
    
    def refresh_token_list(self, force: bool = False):
        """Refresh the Jupiter token list cache.
        
        Args:
            force: If True, refresh even if cache is fresh.
        """
        self._tokens = refresh_token_cache(force=force)
    
    def get_token_cache_age(self) -> Optional[str]:
        """Get the age of the token cache.
        
        Returns:
            Human-readable cache age or None.
        """
        return get_cache_age()


def create_dex_trader(
    slippage: float = 1.0,
    live_mode: bool = False
) -> SolanaDEXTrader:
    """Factory function to create a DEX trader.
    
    Args:
        slippage: Slippage tolerance as percentage (1.0 = 1%).
        live_mode: If True, prompt for private key for live trading.
    
    Returns:
        Configured SolanaDEXTrader instance.
    """
    slippage_bps = int(slippage * 100)
    return SolanaDEXTrader(
        slippage_bps=slippage_bps,
        live_mode=live_mode
    )
