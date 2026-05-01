"""
Jupiter API Utility - Integration with Jupiter aggregator for Solana DEX swaps.

Features:
- Quote fetching with optimal routing
- Swap transaction building
- Price lookups
- Slippage configuration
- API key support (optional, recommended for production)
- JLP mint/redeem via Jupiter Perpetuals (true arbitrage)
"""

import base64
import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

try:
    from solders.pubkey import Pubkey
    from solders.instruction import Instruction, AccountMeta
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.hash import Hash
    SOLDERS_AVAILABLE = True
except ImportError:
    SOLDERS_AVAILABLE = False

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
            print(f"\n[JUPITER] ========== QUOTE ERROR ==========")
            print(f"[JUPITER] Request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[JUPITER] Status: {e.response.status_code}")
                print(f"[JUPITER] Response: {e.response.text[:500]}")
            print(f"[JUPITER] ======================================\n")
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
            print(f"\n[JUPITER] ========== SWAP TX ERROR ==========")
            print(f"[JUPITER] Request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[JUPITER] Status: {e.response.status_code}")
                print(f"[JUPITER] Response: {e.response.text[:500]}")
            print(f"[JUPITER] ========================================\n")
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
            print(f"\n[JUPITER] ========== PRICE ERROR ==========")
            print(f"[JUPITER] Symbol: {symbol}")
            print(f"[JUPITER] Request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[JUPITER] Status: {e.response.status_code}")
                print(f"[JUPITER] Response: {e.response.text[:500]}")
            print(f"[JUPITER] ======================================\n")
            return None
        except Exception as e:
            print(f"\n[JUPITER] ========== CALCULATION ERROR ==========")
            print(f"[JUPITER] Symbol: {symbol}")
            print(f"[JUPITER] Type: {type(e).__name__}")
            print(f"[JUPITER] Message: {e}")
            print(f"[JUPITER] ============================================\n")
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


# =============================================================================
# JUPITER PERPETUALS - JLP MINT/REDEEM
# =============================================================================

# Jupiter Perpetuals Program
PERPS_PROGRAM_ID = "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu"

# JLP Pool and Token
JLP_POOL_ACCOUNT = "5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq"
JLP_TOKEN_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"

# Token mints
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
WBTC_MINT = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"
WETH_MINT = "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"

# System programs
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"


@dataclass
class CustodyInfo:
    """Parsed custody account information for JLP pool."""
    address: str
    mint: Optional[str] = None
    token_account: Optional[str] = None
    doves_oracle: Optional[str] = None
    pythnet_oracle: Optional[str] = None
    decimals: int = 6
    is_stable: bool = False


def _find_pda(seeds: List[bytes], program_id: str) -> Optional[str]:
    """Find PDA using solders."""
    if not SOLDERS_AVAILABLE:
        return None
    
    program_pubkey = Pubkey.from_string(program_id)
    
    try:
        pda, bump = Pubkey.find_program_address(seeds, program_pubkey)
        return str(pda)
    except Exception:
        return None


def _get_anchor_discriminator(instruction_name: str) -> bytes:
    """Get Anchor instruction discriminator (first 8 bytes of sha256 hash)."""
    preimage = f"global:{instruction_name}"
    return hashlib.sha256(preimage.encode()).digest()[:8]


def _get_associated_token_address(owner: str, mint: str) -> Optional[str]:
    """Get associated token account address."""
    if not SOLDERS_AVAILABLE:
        return None
    
    owner_pubkey = Pubkey.from_string(owner)
    mint_pubkey = Pubkey.from_string(mint)
    
    seeds = [
        bytes(owner_pubkey),
        bytes(Pubkey.from_string(TOKEN_PROGRAM)),
        bytes(mint_pubkey),
    ]
    
    return _find_pda(seeds, ASSOCIATED_TOKEN_PROGRAM)


def _parse_custody_account(rpc_client, custody_address: str) -> Optional[CustodyInfo]:
    """Parse a custody account to extract oracle addresses and other details."""
    if not SOLDERS_AVAILABLE:
        return None
    
    account_info = rpc_client.get_account_info(custody_address)
    if not account_info:
        return None
    
    data = base64.b64decode(account_info["data"][0])
    
    info = CustodyInfo(address=custody_address)
    
    try:
        offset = 8  # Skip discriminator
        offset += 32  # Skip pool pubkey
        
        # Mint pubkey (32 bytes)
        mint_bytes = data[offset:offset+32]
        info.mint = str(Pubkey.from_bytes(mint_bytes))
        offset += 32
        
        # Token account pubkey (32 bytes)
        token_account_bytes = data[offset:offset+32]
        info.token_account = str(Pubkey.from_bytes(token_account_bytes))
        offset += 32
        
        # Decimals (1 byte)
        info.decimals = data[offset]
        offset += 1
        
        # is_stable (1 byte)
        info.is_stable = data[offset] == 1
        offset += 1
        
        # Find oracles by scanning for pubkey patterns
        for scan_offset in [106, 138, 170, 202, 234]:
            if scan_offset + 32 <= len(data):
                try:
                    pubkey_bytes = data[scan_offset:scan_offset+32]
                    pubkey = Pubkey.from_bytes(pubkey_bytes)
                    pubkey_str = str(pubkey)
                    if pubkey_str != "11111111111111111111111111111111":
                        if info.doves_oracle is None:
                            info.doves_oracle = pubkey_str
                        elif info.pythnet_oracle is None:
                            info.pythnet_oracle = pubkey_str
                            break
                except:
                    pass
        
    except Exception:
        pass
    
    return info


class JLPMintRedeemClient:
    """
    Client for minting and redeeming JLP tokens via Jupiter Perpetuals.
    
    This enables true arbitrage by:
    - Minting JLP at NAV price (addLiquidity2)
    - Redeeming JLP at NAV price (removeLiquidity2)
    
    Combined with Jupiter swaps at market price, this allows capturing
    the spread between NAV and market price instantly.
    """
    
    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        self.rpc_url = rpc_url
        self.program_id = PERPS_PROGRAM_ID
        self.timeout = 30.0
        
        # Cached account addresses
        self._perpetuals_pda: Optional[str] = None
        self._transfer_authority: Optional[str] = None
        self._event_authority: Optional[str] = None
        self._pool_custodies: List[str] = []
        self._custody_info: Dict[str, CustodyInfo] = {}
        self._initialized = False
        
        # Initialize PDAs
        self._init_pdas()
    
    def _init_pdas(self):
        """Initialize PDA addresses."""
        self._perpetuals_pda = _find_pda([b"perpetuals"], self.program_id)
        self._transfer_authority = _find_pda([b"transfer_authority"], self.program_id)
        self._event_authority = _find_pda([b"__event_authority"], self.program_id)
    
    def _rpc_call(self, method: str, params: List) -> Dict:
        """Make RPC call."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.rpc_url, json=payload)
            result = response.json()
            if "error" in result:
                raise Exception(f"RPC error: {result['error']}")
            return result.get("result")
    
    def get_account_info(self, pubkey: str) -> Optional[Dict]:
        """Get account info."""
        result = self._rpc_call("getAccountInfo", [pubkey, {"encoding": "base64"}])
        return result.get("value") if result else None
    
    def get_latest_blockhash(self) -> str:
        """Get latest blockhash."""
        result = self._rpc_call("getLatestBlockhash", [{"commitment": "finalized"}])
        return result["value"]["blockhash"]
    
    def simulate_transaction(self, tx_base64: str) -> Dict:
        """Simulate a transaction."""
        result = self._rpc_call("simulateTransaction", [
            tx_base64,
            {"encoding": "base64", "commitment": "processed"}
        ])
        return result
    
    def initialize(self) -> bool:
        """Load pool custodies and custody details from on-chain."""
        if self._initialized:
            return True
        
        # Parse custodies from pool
        pool_info = self.get_account_info(JLP_POOL_ACCOUNT)
        if not pool_info:
            return False
        
        data = base64.b64decode(pool_info["data"][0])
        
        try:
            offset = 8  # Skip discriminator
            name_len = struct.unpack("<I", data[offset:offset+4])[0]
            offset += 4 + name_len
            custodies_len = struct.unpack("<I", data[offset:offset+4])[0]
            offset += 4
            
            for _ in range(custodies_len):
                if offset + 32 > len(data):
                    break
                pubkey_bytes = data[offset:offset+32]
                custody_addr = str(Pubkey.from_bytes(pubkey_bytes))
                self._pool_custodies.append(custody_addr)
                offset += 32
        except Exception:
            return False
        
        # Load custody details
        for custody_addr in self._pool_custodies:
            info = _parse_custody_account(self, custody_addr)
            if info:
                self._custody_info[custody_addr] = info
        
        self._initialized = len(self._custody_info) > 0
        return self._initialized
    
    def get_custody_for_mint(self, mint: str) -> Optional[CustodyInfo]:
        """Find custody info for a given mint address."""
        for custody_addr, info in self._custody_info.items():
            if info.mint == mint:
                return info
        return None
    
    def build_add_liquidity_accounts(
        self,
        owner: str,
        custody_mint: str = USDC_MINT,
    ) -> Optional[List[Tuple[str, bool, bool]]]:
        """Build the list of accounts for addLiquidity2 instruction."""
        if not SOLDERS_AVAILABLE or not self._initialized:
            return None
        
        custody_info = self.get_custody_for_mint(custody_mint)
        if not custody_info:
            return None
        
        user_funding_account = _get_associated_token_address(owner, custody_mint)
        user_lp_account = _get_associated_token_address(owner, JLP_TOKEN_MINT)
        
        if not user_funding_account or not user_lp_account:
            return None
        
        accounts = [
            (owner, True, False),
            (user_funding_account, False, True),
            (user_lp_account, False, True),
            (self._transfer_authority, False, False),
            (self._perpetuals_pda, False, False),
            (JLP_POOL_ACCOUNT, False, True),
            (custody_info.address, False, True),
            (custody_info.doves_oracle, False, False),
            (custody_info.pythnet_oracle, False, False),
            (custody_info.token_account, False, True),
            (JLP_TOKEN_MINT, False, True),
            (TOKEN_PROGRAM, False, False),
            (self._event_authority, False, False),
            (self.program_id, False, False),
        ]
        
        return accounts
    
    def build_remove_liquidity_accounts(
        self,
        owner: str,
        custody_mint: str = USDC_MINT,
    ) -> Optional[List[Tuple[str, bool, bool]]]:
        """Build the list of accounts for removeLiquidity2 instruction."""
        if not SOLDERS_AVAILABLE or not self._initialized:
            return None
        
        custody_info = self.get_custody_for_mint(custody_mint)
        if not custody_info:
            return None
        
        user_receiving_account = _get_associated_token_address(owner, custody_mint)
        user_lp_account = _get_associated_token_address(owner, JLP_TOKEN_MINT)
        
        if not user_receiving_account or not user_lp_account:
            return None
        
        accounts = [
            (owner, True, False),
            (user_receiving_account, False, True),
            (user_lp_account, False, True),
            (self._transfer_authority, False, False),
            (self._perpetuals_pda, False, False),
            (JLP_POOL_ACCOUNT, False, True),
            (custody_info.address, False, True),
            (custody_info.doves_oracle, False, False),
            (custody_info.pythnet_oracle, False, False),
            (custody_info.token_account, False, True),
            (JLP_TOKEN_MINT, False, True),
            (TOKEN_PROGRAM, False, False),
            (self._event_authority, False, False),
            (self.program_id, False, False),
        ]
        
        return accounts
    
    def build_add_liquidity_instruction(
        self,
        owner: str,
        token_amount_in: int,
        min_lp_amount_out: int = 0,
        custody_mint: str = USDC_MINT,
    ) -> Optional[Tuple[bytes, List[Tuple[str, bool, bool]]]]:
        """Build complete addLiquidity2 instruction data and accounts."""
        accounts = self.build_add_liquidity_accounts(owner, custody_mint)
        if not accounts:
            return None
        
        discriminator = _get_anchor_discriminator("addLiquidity2")
        params = struct.pack("<QQ", token_amount_in, min_lp_amount_out) + b'\x00'
        instruction_data = discriminator + params
        
        return instruction_data, accounts
    
    def build_remove_liquidity_instruction(
        self,
        owner: str,
        lp_amount_in: int,
        min_amount_out: int = 0,
        custody_mint: str = USDC_MINT,
    ) -> Optional[Tuple[bytes, List[Tuple[str, bool, bool]]]]:
        """Build complete removeLiquidity2 instruction data and accounts."""
        accounts = self.build_remove_liquidity_accounts(owner, custody_mint)
        if not accounts:
            return None
        
        discriminator = _get_anchor_discriminator("removeLiquidity2")
        params = struct.pack("<QQ", lp_amount_in, min_amount_out)
        instruction_data = discriminator + params
        
        return instruction_data, accounts
    
    def build_transaction(
        self,
        instruction_data: bytes,
        accounts: List[Tuple[str, bool, bool]],
        payer: str,
    ) -> Optional[str]:
        """Build a complete transaction and return base64-encoded bytes."""
        if not SOLDERS_AVAILABLE:
            return None
        
        try:
            blockhash = self.get_latest_blockhash()
            
            account_metas = []
            for pubkey_str, is_signer, is_writable in accounts:
                pubkey = Pubkey.from_string(pubkey_str)
                account_metas.append(AccountMeta(pubkey, is_signer, is_writable))
            
            program_id = Pubkey.from_string(self.program_id)
            instruction = Instruction(program_id, instruction_data, account_metas)
            
            payer_pubkey = Pubkey.from_string(payer)
            recent_blockhash = Hash.from_string(blockhash)
            
            message = Message.new_with_blockhash(
                [instruction],
                payer_pubkey,
                recent_blockhash,
            )
            
            tx = Transaction.new_unsigned(message)
            tx_bytes = bytes(tx)
            tx_base64 = base64.b64encode(tx_bytes).decode()
            
            return tx_base64
            
        except Exception as e:
            print(f"[JLP] Failed to build transaction: {e}")
            return None
    
    def simulate_mint(
        self,
        owner: str,
        token_amount_in: int,
        min_lp_amount_out: int = 0,
        custody_mint: str = USDC_MINT,
    ) -> Dict:
        """Simulate an addLiquidity2 transaction (dry-run, no execution)."""
        result = self.build_add_liquidity_instruction(
            owner, token_amount_in, min_lp_amount_out, custody_mint
        )
        if not result:
            return {"success": False, "error": "Failed to build instruction"}
        
        instruction_data, accounts = result
        tx_base64 = self.build_transaction(instruction_data, accounts, owner)
        if not tx_base64:
            return {"success": False, "error": "Failed to build transaction"}
        
        try:
            sim_result = self.simulate_transaction(tx_base64)
            
            if sim_result.get("err"):
                return {
                    "success": False,
                    "error": str(sim_result["err"]),
                    "logs": sim_result.get("logs", []),
                }
            
            return {
                "success": True,
                "logs": sim_result.get("logs", []),
                "units_consumed": sim_result.get("unitsConsumed", 0),
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def simulate_redeem(
        self,
        owner: str,
        lp_amount_in: int,
        min_amount_out: int = 0,
        custody_mint: str = USDC_MINT,
    ) -> Dict:
        """Simulate a removeLiquidity2 transaction (dry-run, no execution)."""
        result = self.build_remove_liquidity_instruction(
            owner, lp_amount_in, min_amount_out, custody_mint
        )
        if not result:
            return {"success": False, "error": "Failed to build instruction"}
        
        instruction_data, accounts = result
        tx_base64 = self.build_transaction(instruction_data, accounts, owner)
        if not tx_base64:
            return {"success": False, "error": "Failed to build transaction"}
        
        try:
            sim_result = self.simulate_transaction(tx_base64)
            
            if sim_result.get("err"):
                return {
                    "success": False,
                    "error": str(sim_result["err"]),
                    "logs": sim_result.get("logs", []),
                }
            
            return {
                "success": True,
                "logs": sim_result.get("logs", []),
                "units_consumed": sim_result.get("unitsConsumed", 0),
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
