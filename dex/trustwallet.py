"""Trust Wallet Agent SDK integration for DEX trading.

Uses the Trust Wallet CLI (twak) for secure wallet operations and swaps.
Keys are stored encrypted locally, never exposed to the trading bot.

Setup:
    1. npm install -g @trustwallet/cli
    2. twak init --api-key YOUR_KEY --api-secret YOUR_SECRET
    3. Either:
       - twak wallet create              # Create new HD wallet
       - twak wallet import              # Import existing wallet via mnemonic
    4. Fund wallet with SOL + tokens (if new)

Import Existing Wallet:
    twak wallet import --mnemonic "your twelve word recovery phrase"
    
    This encrypts the wallet locally with a password you provide.
    The original wallet (e.g., Trust Wallet mobile app) remains unchanged.

Usage:
    trader = TrustWalletTrader()
    trader.set_password("your_password")  # or use TWAK_WALLET_PASSWORD env
    
    balance = trader.get_balance("solana")
    quote = trader.get_swap_quote("solana", "USDC", "SOL", 10.0)
    result = trader.execute_swap("solana", "USDC", "SOL", 10.0)
"""

from __future__ import annotations

import subprocess
import json
import os
import shutil
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass


@dataclass
class SwapQuote:
    """Swap quote from Trust Wallet."""
    input_token: str
    output_token: str
    input_amount: float
    output_amount: float
    price_impact: float
    route: str
    raw: Dict[str, Any]


@dataclass 
class SwapResult:
    """Result of an executed swap."""
    success: bool
    tx_hash: Optional[str]
    input_token: str
    output_token: str
    input_amount: float
    output_amount: Optional[float]
    error: Optional[str]
    raw: Dict[str, Any]


class TrustWalletTrader:
    """Trade via Trust Wallet Agent SDK CLI.
    
    This class wraps the `twak` CLI tool to provide secure DEX trading
    without exposing private keys to the Python process.
    """
    
    def __init__(self, password: Optional[str] = None):
        """Initialize Trust Wallet trader.
        
        Args:
            password: Wallet password. If not provided, uses TWAK_WALLET_PASSWORD env.
        """
        self._password = password
        self._address_cache: Dict[str, str] = {}
        self._twak_path = self._find_twak()
    
    def _find_twak(self) -> str:
        """Find twak CLI executable."""
        # Check if twak is in PATH
        twak = shutil.which("twak")
        if twak:
            return twak
        
        # Check common npm global locations
        npm_paths = [
            os.path.expanduser("~/.npm-global/bin/twak"),
            "/usr/local/bin/twak",
            os.path.expanduser("~/node_modules/.bin/twak"),
        ]
        for path in npm_paths:
            if os.path.exists(path):
                return path
        
        # Fall back to npx
        return "npx"
    
    @property
    def password(self) -> Optional[str]:
        """Get wallet password from instance or environment."""
        return self._password or os.environ.get("TWAK_WALLET_PASSWORD")
    
    def set_password(self, password: str):
        """Set wallet password for this session."""
        self._password = password
    
    def is_configured(self) -> bool:
        """Check if Trust Wallet CLI is configured."""
        try:
            result = self._run_twak(["--version"], needs_password=False)
            return True
        except Exception:
            return False
    
    def _run_twak(self, args: list, needs_password: bool = False, 
                  timeout: int = 60) -> Dict[str, Any]:
        """Run twak CLI command and return JSON output.
        
        Args:
            args: Command arguments (without 'twak' prefix)
            needs_password: Whether this command requires wallet password
            timeout: Command timeout in seconds
            
        Returns:
            Parsed JSON response from twak
            
        Raises:
            RuntimeError: If command fails or twak is not installed
        """
        # Build command
        if self._twak_path == "npx":
            cmd = ["npx", "@trustwallet/cli"] + args
        else:
            cmd = [self._twak_path] + args
        
        # Add JSON output flag if not already present
        if "--json" not in args:
            cmd.append("--json")
        
        # Add password if needed via environment variable (not command line for security)
        env = os.environ.copy()
        if needs_password:
            pwd = self.password
            if not pwd:
                raise RuntimeError(
                    "Wallet password required. Set via set_password() or "
                    "TWAK_WALLET_PASSWORD environment variable."
                )
            env["TWAK_WALLET_PASSWORD"] = pwd
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"twak command timed out after {timeout}s")
        except FileNotFoundError:
            raise RuntimeError(
                "Trust Wallet CLI (twak) not found. Install with:\n"
                "  npm install -g @trustwallet/cli"
            )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"twak command failed: {error_msg}")
        
        # Parse JSON output
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Some commands return plain text
            return {"output": result.stdout.strip()}
    
    def get_address(self, chain: str = "solana") -> str:
        """Get wallet address for specified chain.
        
        Args:
            chain: Blockchain name (solana, ethereum, base, etc.)
            
        Returns:
            Wallet address for the chain
        """
        if chain in self._address_cache:
            return self._address_cache[chain]
        
        result = self._run_twak(
            ["wallet", "address", "--chain", chain],
            needs_password=True
        )
        
        address = result.get("address") or result.get("output", "").strip()
        self._address_cache[chain] = address
        return address
    
    def get_balance(self, chain: str = "solana") -> Dict[str, float]:
        """Get wallet balances for specified chain.
        
        Args:
            chain: Blockchain name
            
        Returns:
            Dict mapping token symbols to balances
        """
        result = self._run_twak(
            ["balance", "--chain", chain],
            needs_password=True
        )
        
        # Parse balance response - format may vary
        if isinstance(result, dict):
            # Remove non-balance keys
            balances = {k: v for k, v in result.items() 
                       if isinstance(v, (int, float)) and k not in ("success", "error")}
            return balances
        return {}
    
    def get_swap_quote(self, chain: str, from_token: str, 
                       to_token: str, amount: float) -> SwapQuote:
        """Get swap quote without executing.
        
        Args:
            chain: Blockchain name
            from_token: Input token symbol (e.g., "USDC")
            to_token: Output token symbol (e.g., "SOL")
            amount: Amount of input token
            
        Returns:
            SwapQuote with expected output and price impact
        """
        result = self._run_twak([
            "swap", "quote",
            "--chain", chain,
            "--from", from_token,
            "--to", to_token,
            "--amount", str(amount)
        ], needs_password=False)
        
        return SwapQuote(
            input_token=from_token,
            output_token=to_token,
            input_amount=amount,
            output_amount=float(result.get("outputAmount", 0)),
            price_impact=float(result.get("priceImpact", 0)),
            route=result.get("route", ""),
            raw=result
        )
    
    def execute_swap(self, chain: str, from_token: str,
                     to_token: str, amount: float,
                     slippage_bps: int = 100) -> SwapResult:
        """Execute a swap transaction.
        
        Args:
            chain: Blockchain name
            from_token: Input token symbol
            to_token: Output token symbol
            amount: Amount of input token
            slippage_bps: Slippage tolerance in basis points (100 = 1%)
            
        Returns:
            SwapResult with transaction hash or error
        """
        try:
            result = self._run_twak([
                "swap", "execute",
                "--chain", chain,
                "--from", from_token,
                "--to", to_token,
                "--amount", str(amount),
                "--slippage", str(slippage_bps)
            ], needs_password=True, timeout=120)
            
            return SwapResult(
                success=True,
                tx_hash=result.get("txHash") or result.get("signature"),
                input_token=from_token,
                output_token=to_token,
                input_amount=amount,
                output_amount=float(result.get("outputAmount", 0)),
                error=None,
                raw=result
            )
        except Exception as e:
            return SwapResult(
                success=False,
                tx_hash=None,
                input_token=from_token,
                output_token=to_token,
                input_amount=amount,
                output_amount=None,
                error=str(e),
                raw={}
            )
    
    def get_price(self, token: str) -> Optional[float]:
        """Get current USD price for a token.
        
        Args:
            token: Token symbol (e.g., "SOL", "ETH")
            
        Returns:
            USD price or None if unavailable
        """
        try:
            result = self._run_twak(
                ["price", token],
                needs_password=False
            )
            return float(result.get("price", 0))
        except Exception:
            return None
    
    def list_supported_chains(self) -> list:
        """List supported blockchain networks."""
        try:
            result = self._run_twak(
                ["chains"],
                needs_password=False
            )
            return result.get("chains", [])
        except Exception:
            # Return known supported chains as fallback
            return ["solana", "ethereum", "base", "polygon", "arbitrum", "optimism"]


def check_twak_installation() -> tuple[bool, str]:
    """Check if Trust Wallet CLI is properly installed and configured.
    
    Returns:
        (is_ready, message) tuple
    """
    trader = TrustWalletTrader()
    
    # Check if twak is installed
    if not trader.is_configured():
        return False, (
            "Trust Wallet CLI (twak) is not installed.\n"
            "Install with: npm install -g @trustwallet/cli"
        )
    
    # Check if credentials are configured
    creds_path = os.path.expanduser("~/.twak/credentials.json")
    if not os.path.exists(creds_path):
        return False, (
            "Trust Wallet CLI is installed but not configured.\n"
            "1. Get API keys at https://portal.trustwallet.com\n"
            "2. Run: twak init --api-key YOUR_KEY --api-secret YOUR_SECRET"
        )
    
    # Check if wallet exists
    wallet_path = os.path.expanduser("~/.twak/wallet.json")
    if not os.path.exists(wallet_path):
        return False, (
            "Trust Wallet CLI is configured but no wallet exists.\n"
            "Create new:  twak wallet create\n"
            "Or import:   twak wallet import --mnemonic \"your recovery phrase\""
        )
    
    return True, "Trust Wallet CLI is ready"
