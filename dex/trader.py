"""
Solana DEX Trader - Main trading interface for Solana DEX via Jupiter + WalletConnect.

This class provides a similar interface to BlobbyTrader (CEX) for consistency,
allowing the main trading bot to switch between CEX and DEX modes seamlessly.
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
from .walletconnect import WalletConnectSession, run_async

# Default trade amount in SOL
DEFAULT_TRADE_AMOUNT_SOL = 0.1

# Rate limiting: minimum seconds between trades
MIN_TRADE_INTERVAL = 60


class SolanaDEXTrader:
    """Solana DEX trader using Jupiter aggregator and WalletConnect/Phantom.
    
    This class provides a similar interface to BlobbyTrader for CEX trading,
    making it easy to switch between modes in the main trading bot.
    """
    
    def __init__(
        self,
        slippage_bps: int = 100,
        approval_timeout: int = 300,
        persist_session: bool = False
    ):
        """Initialize the Solana DEX trader.
        
        Args:
            slippage_bps: Slippage tolerance in basis points (100 = 1%).
            approval_timeout: Timeout for user approval in Phantom (seconds).
            persist_session: If True, persist WalletConnect session to file.
        """
        self.jupiter = JupiterClient(slippage_bps=slippage_bps)
        self.wc_session = WalletConnectSession(
            approval_timeout=approval_timeout,
            persist_session=persist_session
        )
        
        self.slippage_bps = slippage_bps
        self.connected = False
        self._last_trade_time = 0
        self._tokens = None
        
        print(f"[DEX] SolanaDEXTrader initialized (slippage: {slippage_bps/100}%)")
    
    def connect_wallet(self) -> Optional[str]:
        """Connect to Phantom wallet via WalletConnect.
        
        Displays QR code / deep link for user to scan with Phantom.
        Blocks until connected or timeout.
        
        Returns:
            Connected wallet address or None on timeout/error.
        """
        address = run_async(self.wc_session.connect())
        if address:
            self.connected = True
        return address
    
    def disconnect_wallet(self):
        """Disconnect from wallet and clean up."""
        run_async(self.wc_session.disconnect())
        self.connected = False
    
    def is_connected(self) -> bool:
        """Check if wallet is connected."""
        return self.connected and self.wc_session.is_connected()
    
    def get_wallet_address(self) -> Optional[str]:
        """Get connected wallet address."""
        return self.wc_session.get_address()
    
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
        
        # Check connection
        if not self.is_connected():
            print("[DEX] Error: Wallet not connected")
            print("[DEX] Call connect_wallet() first")
            return result
        
        # Get swap transaction
        wallet_address = self.get_wallet_address()
        swap_tx = self.jupiter.get_swap_transaction(quote, wallet_address)
        if not swap_tx:
            print("[DEX] Failed to get swap transaction")
            return result
        
        # Send to Phantom for approval
        signature = run_async(self.wc_session.sign_and_send_transaction(swap_tx))
        if signature:
            result["executed"] = True
            result["signature"] = signature
            result["tx_url"] = f"https://solscan.io/tx/{signature}"
            print(f"[DEX] ✓ BUY executed: {signature}")
        else:
            print("[DEX] ✗ Transaction not executed (rejected or error)")
        
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
        
        # Check connection
        if not self.is_connected():
            print("[DEX] Error: Wallet not connected")
            print("[DEX] Call connect_wallet() first")
            return result
        
        # Get swap transaction
        wallet_address = self.get_wallet_address()
        swap_tx = self.jupiter.get_swap_transaction(quote, wallet_address)
        if not swap_tx:
            print("[DEX] Failed to get swap transaction")
            return result
        
        # Send to Phantom for approval
        signature = run_async(self.wc_session.sign_and_send_transaction(swap_tx))
        if signature:
            result["executed"] = True
            result["signature"] = signature
            result["tx_url"] = f"https://solscan.io/tx/{signature}"
            print(f"[DEX] ✓ SELL executed: {signature}")
        else:
            print("[DEX] ✗ Transaction not executed (rejected or error)")
        
        return result
    
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
    approval_timeout: int = 300,
    persist_session: bool = False
) -> SolanaDEXTrader:
    """Factory function to create a DEX trader.
    
    Args:
        slippage: Slippage tolerance as percentage (1.0 = 1%).
        approval_timeout: Timeout for Phantom approval in seconds.
        persist_session: If True, persist WalletConnect session.
    
    Returns:
        Configured SolanaDEXTrader instance.
    """
    slippage_bps = int(slippage * 100)
    return SolanaDEXTrader(
        slippage_bps=slippage_bps,
        approval_timeout=approval_timeout,
        persist_session=persist_session
    )
