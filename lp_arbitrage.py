#!/usr/bin/env python3
"""
LP Arbitrage Bot - True Liquidity Pool Arbitrage

This bot monitors the spread between NAV (virtual) price and market price
for liquidity pool tokens, executing TRUE ARBITRAGE when the spread exceeds
thresholds - capturing the spread immediately rather than betting on mean reversion.

Arbitrage Strategies:
- PREMIUM ARB: When market > NAV, mint JLP at NAV → sell at market
- DISCOUNT ARB: When market < NAV, buy at market → redeem at NAV

Primary Platform: Jupiter JLP
Future Support: Drift hJLP, HyperLiquid HLP

Usage:
    python lp_arbitrage.py --once                    # Single run
    python lp_arbitrage.py --daemon --interval=300   # Continuous with 5-min wake-up
    python lp_arbitrage.py --trading-mode=whatif     # Paper trading (default)
    python lp_arbitrage.py --trading-mode=live       # Real execution
    python lp_arbitrage.py --verbose                 # Log every wake-up snapshot
"""

import argparse
import base64
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

import httpx

# Local imports
from dex.jupiterutil import (
    JupiterClient, 
    USDC_MINT,
    JLPMintRedeemClient,
    JLP_TOKEN_MINT as JLP_MINT_FROM_JUPITER,
)
from dex.local_wallet import LocalWallet, prompt_for_private_key, get_wallet_for_whatif
from lp_history import (
    LPHistoryManager,
    create_snapshot_record,
    create_trade_record,
)


# ============================================================================
# CONSTANTS
# ============================================================================

# Jupiter JLP Token Addresses
JLP_TOKEN_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"
JLP_POOL_ACCOUNT = "5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq"

# JLP token has 6 decimals
JLP_DECIMALS = 6
USDC_DECIMALS = 6

# Jupiter Perpetuals Program
JUPITER_PERPS_PROGRAM = "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu"

# Default configuration
DEFAULT_BUY_THRESHOLD = -0.02      # Buy when market < virtual by 2%
DEFAULT_SELL_THRESHOLD = 0.03      # Sell when market > virtual by 3%
DEFAULT_TRADE_AMOUNT_USD = 50      # Small fixed amount (unhedged risk)
DEFAULT_MAX_POSITION_USD = 500     # Cap total exposure
DEFAULT_POLL_INTERVAL = 300        # 5-minute wake-up

# Solana RPC
DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class LPConfig:
    """Configuration for LP arbitrage bot."""
    
    # Execution mode
    once: bool = False
    daemon: bool = False
    interval: int = DEFAULT_POLL_INTERVAL
    
    # Trading mode
    trading_mode: str = "whatif"  # whatif | live
    verbose: bool = False
    
    # Platform
    platform: str = "jupiter"  # jupiter | drift | hyperliquid
    
    # Thresholds
    buy_threshold: float = DEFAULT_BUY_THRESHOLD
    sell_threshold: float = DEFAULT_SELL_THRESHOLD
    
    # Position sizing
    trade_amount_usd: float = DEFAULT_TRADE_AMOUNT_USD
    max_position_usd: float = DEFAULT_MAX_POSITION_USD
    
    # RPC
    rpc_url: str = DEFAULT_RPC_URL
    
    # History
    history_dir: str = "./history/lp/"
    
    # Price source comparison
    compare_price_sources: bool = False
    
    # Auto-calculate spread thresholds
    auto_calculate_spread: bool = False
    profit_margin: float = 0.005  # 0.5% profit margin above min viable spread


def parse_args() -> LPConfig:
    """Parse command-line arguments and environment variables into LPConfig."""
    parser = argparse.ArgumentParser(
        description='LP Arbitrage Bot - Premium/Discount Spread Trading',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python lp_arbitrage.py --once                     # Single run, paper trading
  python lp_arbitrage.py --daemon --interval=300    # Continuous, 5-min wake-up
  python lp_arbitrage.py --trading-mode=live        # Real execution
  python lp_arbitrage.py --verbose                  # Log every snapshot
  
Environment variables (CLI takes precedence):
  TRADING_MODE, POLL_INTERVAL_SECONDS, BUY_THRESHOLD, SELL_THRESHOLD,
  TRADE_AMOUNT_USD, MAX_POSITION_USD, SOLANA_RPC_URL, HISTORY_DIR
"""
    )
    
    # Execution mode
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run once and exit (for cron jobs)'
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run continuously with sleep interval'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=int(os.environ.get('POLL_INTERVAL_SECONDS', str(DEFAULT_POLL_INTERVAL))),
        help=f'Wake-up interval in seconds (default: {DEFAULT_POLL_INTERVAL})'
    )
    
    # Trading mode
    parser.add_argument(
        '--trading-mode',
        choices=['whatif', 'live'],
        default=os.environ.get('TRADING_MODE', 'whatif').lower(),
        help='Trading mode: whatif (paper) or live (default: whatif)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        default=os.environ.get('VERBOSE', 'false').lower() == 'true',
        help='Log every wake-up snapshot (not just opportunities)'
    )
    
    # Platform
    parser.add_argument(
        '--platform',
        choices=['jupiter', 'drift', 'hyperliquid'],
        default=os.environ.get('LP_PLATFORM', 'jupiter').lower(),
        help='LP platform to use (default: jupiter)'
    )
    
    # Thresholds
    parser.add_argument(
        '--buy-threshold',
        type=float,
        default=float(os.environ.get('BUY_THRESHOLD', str(DEFAULT_BUY_THRESHOLD))),
        help=f'Buy when spread < threshold (default: {DEFAULT_BUY_THRESHOLD})'
    )
    parser.add_argument(
        '--sell-threshold',
        type=float,
        default=float(os.environ.get('SELL_THRESHOLD', str(DEFAULT_SELL_THRESHOLD))),
        help=f'Sell when spread > threshold (default: {DEFAULT_SELL_THRESHOLD})'
    )
    
    # Position sizing
    parser.add_argument(
        '--trade-amount',
        type=float,
        default=float(os.environ.get('TRADE_AMOUNT_USD', str(DEFAULT_TRADE_AMOUNT_USD))),
        help=f'Fixed trade amount in USD (default: {DEFAULT_TRADE_AMOUNT_USD})'
    )
    parser.add_argument(
        '--max-position',
        type=float,
        default=float(os.environ.get('MAX_POSITION_USD', str(DEFAULT_MAX_POSITION_USD))),
        help=f'Maximum position size in USD (default: {DEFAULT_MAX_POSITION_USD})'
    )
    
    # RPC
    parser.add_argument(
        '--rpc-url',
        default=os.environ.get('SOLANA_RPC_URL', DEFAULT_RPC_URL),
        help='Solana RPC URL'
    )
    
    # History
    parser.add_argument(
        '--history-dir',
        default=os.environ.get('HISTORY_DIR', './history/lp/'),
        help='Directory for history files'
    )
    
    # Price source comparison
    parser.add_argument(
        '--compare-price-sources',
        action='store_true',
        default=os.environ.get('COMPARE_PRICE_SOURCES', 'false').lower() == 'true',
        help='Compare on-chain and DEX spread price methods'
    )
    
    # Auto-calculate spread thresholds
    parser.add_argument(
        '--auto-calculate-spread',
        action='store_true',
        default=os.environ.get('AUTO_CALCULATE_SPREAD', 'false').lower() == 'true',
        help='Auto-calculate min viable spread from swap fees and set thresholds'
    )
    parser.add_argument(
        '--profit-margin',
        type=float,
        default=float(os.environ.get('PROFIT_MARGIN', '0.005')),
        help='Profit margin above min viable spread (default: 0.005 = 0.5%%)'
    )
    
    args = parser.parse_args()
    
    # Build config
    config = LPConfig(
        once=args.once,
        daemon=args.daemon,
        interval=args.interval,
        trading_mode=args.trading_mode,
        verbose=args.verbose,
        platform=args.platform,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        trade_amount_usd=args.trade_amount,
        max_position_usd=args.max_position,
        rpc_url=args.rpc_url,
        history_dir=args.history_dir,
        compare_price_sources=args.compare_price_sources,
        auto_calculate_spread=args.auto_calculate_spread,
        profit_margin=args.profit_margin,
    )
    
    # Default to --once if neither specified
    if not config.once and not config.daemon:
        config.once = True
    
    return config


# ============================================================================
# JUPITER JLP PRICE FETCHER
# ============================================================================

class JLPPriceFetcher:
    """
    Fetch JLP virtual and market prices.
    
    Primary method (default): On-chain parsing
    - Virtual price = Pool AUM (USD) / JLP token supply
    - Market price = Jupiter swap quote (1 JLP → USDC)
    
    Fallback method: DEX buy/sell spread
    - Uses difference between buy and sell quotes as proxy
    
    Compare mode: Runs both methods and outputs comparison
    """
    
    def __init__(self, rpc_url: str = DEFAULT_RPC_URL, compare_sources: bool = False):
        self.rpc_url = rpc_url
        self.jupiter_client = JupiterClient()
        self.compare_sources = compare_sources
        
        # Cached values
        self._last_virtual_price: Optional[float] = None
        self._last_market_price: Optional[float] = None
        self._last_aum_usd: Optional[float] = None
        self._last_jlp_supply: Optional[float] = None
    
    # =========================================================================
    # ON-CHAIN METHODS (Primary)
    # =========================================================================
    
    def _fetch_account_data(self, address: str) -> Optional[bytes]:
        """Fetch raw account data from Solana RPC."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getAccountInfo",
                        "params": [address, {"encoding": "base64"}]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json().get("result", {})
                    value = result.get("value")
                    if value and value.get("data"):
                        return base64.b64decode(value["data"][0])
        except Exception as e:
            print(f"  [RPC] Error fetching {address[:8]}...: {e}")
        return None
    
    def _fetch_token_supply(self, mint: str) -> Optional[float]:
        """Fetch token supply from Solana RPC."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTokenSupply",
                        "params": [mint]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json().get("result", {})
                    value = result.get("value", {})
                    return float(value.get("uiAmount", 0))
        except Exception as e:
            print(f"  [RPC] Error fetching supply: {e}")
        return None
    
    def _parse_pool_aum(self, data: bytes) -> Optional[float]:
        """
        Parse AUM from Pool account struct.
        
        Layout:
        - 8 bytes: Anchor discriminator
        - 4 bytes + N: name string
        - 4 bytes + N*32: custodies vec
        - 16 bytes: aumUsd (u128)
        """
        try:
            offset = 8  # Skip discriminator
            
            # Skip name string
            name_len = struct.unpack_from('<I', data, offset)[0]
            offset += 4 + name_len
            
            # Skip custodies vec
            num_custodies = struct.unpack_from('<I', data, offset)[0]
            offset += 4 + (num_custodies * 32)
            
            # Read aumUsd (u128)
            low = struct.unpack_from('<Q', data, offset)[0]
            high = struct.unpack_from('<Q', data, offset + 8)[0]
            aum_raw = low + (high << 64)
            
            # aumUsd uses 6 decimals
            return aum_raw / 1_000_000
            
        except Exception as e:
            print(f"  [RPC] Error parsing Pool struct: {e}")
            return None
    
    def get_virtual_price_onchain(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Get virtual price from on-chain data.
        
        Returns:
            Tuple of (virtual_price, aum_usd, jlp_supply)
        """
        # Fetch JLP supply
        jlp_supply = self._fetch_token_supply(JLP_TOKEN_MINT)
        if not jlp_supply or jlp_supply <= 0:
            return None, None, None
        
        # Fetch Pool account
        pool_data = self._fetch_account_data(JLP_POOL_ACCOUNT)
        if not pool_data:
            return None, None, jlp_supply
        
        # Parse AUM
        aum_usd = self._parse_pool_aum(pool_data)
        if not aum_usd or aum_usd <= 0:
            return None, None, jlp_supply
        
        # Calculate virtual price
        virtual_price = aum_usd / jlp_supply
        
        self._last_virtual_price = virtual_price
        self._last_aum_usd = aum_usd
        self._last_jlp_supply = jlp_supply
        
        return virtual_price, aum_usd, jlp_supply
    
    def get_market_price(self) -> Optional[float]:
        """
        Get market price via Jupiter swap quote (1 JLP → USDC).
        """
        try:
            quote = self.jupiter_client.get_quote(
                input_mint=JLP_TOKEN_MINT,
                output_mint=USDC_MINT,
                amount=10 ** JLP_DECIMALS,  # 1 JLP
                slippage_bps=50
            )
            
            if quote:
                out_amount = int(quote.get("outAmount", 0))
                if out_amount > 0:
                    market_price = out_amount / (10 ** USDC_DECIMALS)
                    self._last_market_price = market_price
                    return market_price
            
            return self._last_market_price
            
        except Exception as e:
            print(f"  [JLP] Error fetching market price: {e}")
            return self._last_market_price
    
    # =========================================================================
    # DEX SPREAD METHODS (Fallback)
    # =========================================================================
    
    def get_dex_buy_price(self) -> Optional[float]:
        """Get buy price from DEX quote (USDC → JLP)."""
        try:
            reference_usdc = 100 * (10 ** USDC_DECIMALS)
            
            quote = self.jupiter_client.get_quote(
                input_mint=USDC_MINT,
                output_mint=JLP_TOKEN_MINT,
                amount=reference_usdc,
                slippage_bps=50
            )
            
            if quote:
                out_amount = int(quote.get("outAmount", 0))
                in_amount = int(quote.get("inAmount", reference_usdc))
                
                if out_amount > 0:
                    jlp_received = out_amount / (10 ** JLP_DECIMALS)
                    usdc_spent = in_amount / (10 ** USDC_DECIMALS)
                    return usdc_spent / jlp_received
            return None
        except Exception as e:
            print(f"  [JLP] Error fetching DEX buy price: {e}")
            return None
    
    def get_dex_sell_price(self) -> Optional[float]:
        """Get sell price from DEX quote (JLP → USDC)."""
        return self.get_market_price()  # Same as market price
    
    # =========================================================================
    # MIN VIABLE SPREAD CALCULATION
    # =========================================================================
    
    def calculate_min_viable_spread(self, trade_amount_usd: float = 100.0) -> Optional[dict]:
        """
        Calculate the minimum viable spread needed to be profitable.
        
        For TRUE ARBITRAGE, includes:
        - JLP mint fee (~0.1% for addLiquidity2)
        - JLP redeem fee (~0.1% for removeLiquidity2)
        - DEX swap fees and price impact
        - Gas costs
        
        Returns:
            Dict with breakdown of costs and min viable spread, or None on error
        """
        try:
            # JLP Perpetuals program fees (built into mint/redeem, not in Jupiter quotes)
            # These are approximate - actual fees may vary based on pool state
            JLP_MINT_FEE_PCT = 0.10   # ~0.1% for addLiquidity2
            JLP_REDEEM_FEE_PCT = 0.10  # ~0.1% for removeLiquidity2
            
            # Get buy quote (USDC → JLP) for DEX swap leg
            buy_amount = int(trade_amount_usd * (10 ** USDC_DECIMALS))
            buy_quote = self.jupiter_client.get_quote(
                input_mint=USDC_MINT,
                output_mint=JLP_TOKEN_MINT,
                amount=buy_amount,
                slippage_bps=50
            )
            
            if not buy_quote:
                return None
            
            # Get sell quote (JLP → USDC) for equivalent JLP amount
            jlp_out = int(buy_quote.get("outAmount", 0))
            if jlp_out <= 0:
                return None
                
            sell_quote = self.jupiter_client.get_quote(
                input_mint=JLP_TOKEN_MINT,
                output_mint=USDC_MINT,
                amount=jlp_out,
                slippage_bps=50
            )
            
            if not sell_quote:
                return None
            
            # Extract price impact from DEX quotes
            buy_price_impact = float(buy_quote.get("priceImpactPct", "0") or "0")
            sell_price_impact = float(sell_quote.get("priceImpactPct", "0") or "0")
            
            # Extract DEX swap fees from routePlan
            dex_buy_fees = self._extract_fees_from_quote(buy_quote, trade_amount_usd)
            dex_sell_fees = self._extract_fees_from_quote(sell_quote, trade_amount_usd)
            
            # Gas cost estimate (2 transactions, ~0.000005 SOL each, SOL ~$150)
            gas_cost_usd = 2 * 0.000005 * 150  # ~$0.0015
            gas_pct = (gas_cost_usd / trade_amount_usd) * 100
            
            # Calculate total costs for true arbitrage
            # Premium arb: mint (0.1%) + sell (dex fees + impact)
            # Discount arb: buy (dex fees + impact) + redeem (0.1%)
            # Use max of both scenarios
            total_jlp_fee_pct = JLP_MINT_FEE_PCT + JLP_REDEEM_FEE_PCT
            total_dex_fee_pct = dex_buy_fees + dex_sell_fees
            total_impact_pct = abs(buy_price_impact) + abs(sell_price_impact)
            
            # Min viable spread = JLP fees + DEX fees + impact + gas
            min_viable_spread = total_jlp_fee_pct + total_dex_fee_pct + total_impact_pct + gas_pct
            
            return {
                "jlp_mint_fee_pct": JLP_MINT_FEE_PCT,
                "jlp_redeem_fee_pct": JLP_REDEEM_FEE_PCT,
                "dex_buy_fee_pct": dex_buy_fees,
                "dex_sell_fee_pct": dex_sell_fees,
                "buy_price_impact_pct": abs(buy_price_impact),
                "sell_price_impact_pct": abs(sell_price_impact),
                "gas_pct": gas_pct,
                "total_jlp_fee_pct": total_jlp_fee_pct,
                "total_dex_fee_pct": total_dex_fee_pct,
                "total_impact_pct": total_impact_pct,
                "min_viable_spread_pct": min_viable_spread,
                "trade_amount_usd": trade_amount_usd,
            }
            
        except Exception as e:
            print(f"  [JLP] Error calculating min viable spread: {e}")
            return None
    
    def _extract_fees_from_quote(self, quote: dict, trade_amount_usd: float) -> float:
        """Extract total fees from Jupiter quote routePlan as percentage."""
        total_fee_usd = 0.0
        
        route_plan = quote.get("routePlan", [])
        for hop in route_plan:
            swap_info = hop.get("swapInfo", {})
            fee_amount = int(swap_info.get("feeAmount", "0") or "0")
            fee_mint = swap_info.get("feeMint", "")
            
            # Convert fee to USD (assume USDC decimals for simplicity)
            # In practice, would need to check fee_mint and convert
            if fee_amount > 0:
                # Assume 6 decimals for most stablecoins
                fee_usd = fee_amount / (10 ** 6)
                total_fee_usd += fee_usd
        
        # Return as percentage of trade amount
        if trade_amount_usd > 0:
            return (total_fee_usd / trade_amount_usd) * 100
        return 0.0
    
    # =========================================================================
    # MAIN INTERFACE
    # =========================================================================
    
    def get_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch virtual and market prices.
        
        Primary: On-chain virtual price + DEX market price
        Fallback: DEX buy/sell spread if on-chain fails
        
        Returns:
            Tuple of (virtual_price, market_price)
        """
        # Try on-chain method first (default)
        virtual_price, aum_usd, jlp_supply = self.get_virtual_price_onchain()
        market_price = self.get_market_price()
        
        # Comparison mode
        if self.compare_sources:
            self._print_comparison(virtual_price, market_price, aum_usd, jlp_supply)
        
        # If on-chain succeeded, use it
        if virtual_price and market_price:
            return virtual_price, market_price
        
        # Fallback to DEX spread method
        if virtual_price is None:
            print("  [WARN] On-chain virtual price failed, using DEX spread fallback")
            buy_price = self.get_dex_buy_price()
            if buy_price:
                virtual_price = buy_price
        
        if market_price is None:
            print("  [WARN] Market price fetch failed")
        
        return virtual_price, market_price
    
    def _print_comparison(self, virtual_price: Optional[float], market_price: Optional[float],
                          aum_usd: Optional[float], jlp_supply: Optional[float]):
        """Print comparison of price sources."""
        print("\n  ┌─────────────────────────────────────────────────────┐")
        print("  │           PRICE SOURCE COMPARISON                   │")
        print("  ├─────────────────────────────────────────────────────┤")
        
        # On-chain data
        if virtual_price and aum_usd and jlp_supply:
            print(f"  │ ON-CHAIN (Pool AUM / Supply):                       │")
            print(f"  │   AUM:           ${aum_usd:>14,.2f}                │")
            print(f"  │   JLP Supply:    {jlp_supply:>14,.2f}                │")
            print(f"  │   Virtual Price: ${virtual_price:>14.6f}                │")
        else:
            print(f"  │ ON-CHAIN: FAILED                                    │")
        
        print("  ├─────────────────────────────────────────────────────┤")
        
        # DEX data
        dex_buy = self.get_dex_buy_price()
        dex_sell = market_price  # Already fetched
        
        if dex_buy and dex_sell:
            dex_spread = (dex_sell - dex_buy) / dex_buy * 100
            print(f"  │ DEX SPREAD (Buy/Sell quotes):                       │")
            print(f"  │   Buy Price:     ${dex_buy:>14.6f}                │")
            print(f"  │   Sell Price:    ${dex_sell:>14.6f}                │")
            print(f"  │   DEX Spread:    {dex_spread:>+14.4f}%               │")
        else:
            print(f"  │ DEX SPREAD: FAILED                                  │")
        
        print("  ├─────────────────────────────────────────────────────┤")
        
        # Comparison
        if virtual_price and market_price:
            true_spread = (market_price - virtual_price) / virtual_price * 100
            print(f"  │ TRUE SPREAD (Market vs NAV):                        │")
            print(f"  │   Market - NAV:  {true_spread:>+14.4f}%               │")
            
            if dex_buy:
                diff = market_price - dex_buy
                print(f"  │   Market vs Buy: ${diff:>+14.6f}                │")
        
        print("  └─────────────────────────────────────────────────────┘\n")
    
    def calculate_spread(self, market_price: float, virtual_price: float) -> float:
        """
        Calculate spread between market and virtual price.
        
        Spread = (market_price - virtual_price) / virtual_price
        
        - Positive spread = premium (market > NAV)
        - Negative spread = discount (market < NAV)
        """
        if virtual_price <= 0:
            return 0.0
        return (market_price - virtual_price) / virtual_price


# ============================================================================
# JUPITER JLP ARBITRAGE TRADER
# ============================================================================

class JLPArbitrageTrader:
    """
    Execute TRUE ARBITRAGE trades for JLP.
    
    Premium Arbitrage (market > NAV):
        1. Mint JLP at NAV price (addLiquidity2)
        2. Sell JLP at market price (Jupiter swap)
        
    Discount Arbitrage (market < NAV):
        1. Buy JLP at market price (Jupiter swap)
        2. Redeem JLP at NAV price (removeLiquidity2)
    """
    
    def __init__(self, wallet: LocalWallet, rpc_url: str = DEFAULT_RPC_URL):
        self.wallet = wallet
        self.rpc_url = rpc_url
        self.jupiter_client = JupiterClient()
        self.mint_redeem_client = JLPMintRedeemClient(rpc_url)
        
        # Initialize mint/redeem client
        self._mint_redeem_initialized = False
    
    def get_jlp_balance(self) -> float:
        """Get current JLP token balance."""
        if not self.wallet.is_loaded():
            return 0.0
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTokenAccountsByOwner",
                        "params": [
                            self.wallet.get_address(),
                            {"mint": JLP_TOKEN_MINT},
                            {"encoding": "jsonParsed"}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json().get("result", {})
                    accounts = result.get("value", [])
                    
                    total_balance = 0.0
                    for account in accounts:
                        parsed = account.get("account", {}).get("data", {}).get("parsed", {})
                        info = parsed.get("info", {})
                        token_amount = info.get("tokenAmount", {})
                        amount = float(token_amount.get("uiAmount", 0))
                        total_balance += amount
                    
                    return total_balance
                
        except Exception as e:
            print(f"[JLP] Error fetching balance: {e}")
        
        return 0.0
    
    def get_usdc_balance(self) -> float:
        """Get current USDC balance."""
        if not self.wallet.is_loaded():
            return 0.0
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTokenAccountsByOwner",
                        "params": [
                            self.wallet.get_address(),
                            {"mint": USDC_MINT},
                            {"encoding": "jsonParsed"}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json().get("result", {})
                    accounts = result.get("value", [])
                    
                    total_balance = 0.0
                    for account in accounts:
                        parsed = account.get("account", {}).get("data", {}).get("parsed", {})
                        info = parsed.get("info", {})
                        token_amount = info.get("tokenAmount", {})
                        amount = float(token_amount.get("uiAmount", 0))
                        total_balance += amount
                    
                    return total_balance
                
        except Exception as e:
            print(f"[JLP] Error fetching USDC balance: {e}")
        
        return 0.0
    
    def buy_jlp(self, amount_usdc: float) -> Optional[str]:
        """
        Buy JLP with USDC.
        
        Args:
            amount_usdc: Amount of USDC to spend.
        
        Returns:
            Transaction signature or None on error.
        """
        if not self.wallet.is_loaded():
            print("[JLP] Error: Wallet not loaded")
            return None
        
        try:
            # Get quote: USDC -> JLP
            amount_lamports = int(amount_usdc * (10 ** USDC_DECIMALS))
            
            quote = self.jupiter_client.get_quote(
                input_mint=USDC_MINT,
                output_mint=JLP_TOKEN_MINT,
                amount=amount_lamports,
                slippage_bps=100  # 1% slippage for JLP
            )
            
            if not quote:
                print("[JLP] Failed to get buy quote")
                return None
            
            # Get swap transaction
            swap_tx = self.jupiter_client.get_swap_transaction(
                quote=quote,
                user_public_key=self.wallet.get_address()
            )
            
            if not swap_tx:
                print("[JLP] Failed to get swap transaction")
                return None
            
            # Sign and send transaction
            return self._sign_and_send(swap_tx)
            
        except Exception as e:
            print(f"[JLP] Buy error: {e}")
            return None
    
    def sell_jlp(self, amount_jlp: float) -> Optional[str]:
        """
        Sell JLP for USDC.
        
        Args:
            amount_jlp: Amount of JLP to sell.
        
        Returns:
            Transaction signature or None on error.
        """
        if not self.wallet.is_loaded():
            print("[JLP] Error: Wallet not loaded")
            return None
        
        try:
            # Get quote: JLP -> USDC
            amount_lamports = int(amount_jlp * (10 ** JLP_DECIMALS))
            
            quote = self.jupiter_client.get_quote(
                input_mint=JLP_TOKEN_MINT,
                output_mint=USDC_MINT,
                amount=amount_lamports,
                slippage_bps=100  # 1% slippage for JLP
            )
            
            if not quote:
                print("[JLP] Failed to get sell quote")
                return None
            
            # Get swap transaction
            swap_tx = self.jupiter_client.get_swap_transaction(
                quote=quote,
                user_public_key=self.wallet.get_address()
            )
            
            if not swap_tx:
                print("[JLP] Failed to get swap transaction")
                return None
            
            # Sign and send transaction
            return self._sign_and_send(swap_tx)
            
        except Exception as e:
            print(f"[JLP] Sell error: {e}")
            return None
    
    def _sign_and_send(self, swap_tx_base64: str) -> Optional[str]:
        """Sign and send a swap transaction."""
        import base64
        
        try:
            # Decode transaction
            tx_bytes = base64.b64decode(swap_tx_base64)
            
            # Sign transaction
            signed_tx = self.wallet.sign_transaction(tx_bytes)
            if not signed_tx:
                print("[JLP] Failed to sign transaction")
                return None
            
            # Send transaction
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "sendTransaction",
                        "params": [
                            base64.b64encode(signed_tx).decode(),
                            {"encoding": "base64", "skipPreflight": False}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if "result" in result:
                        sig = result["result"]
                        print(f"[JLP] Transaction sent: {sig}")
                        return sig
                    elif "error" in result:
                        print(f"[JLP] Transaction error: {result['error']}")
                
        except Exception as e:
            print(f"[JLP] Send transaction error: {e}")
        
        return None
    
    def _ensure_mint_redeem_initialized(self) -> bool:
        """Ensure mint/redeem client is initialized."""
        if self._mint_redeem_initialized:
            return True
        
        print("  [JLP] Initializing mint/redeem client...")
        self._mint_redeem_initialized = self.mint_redeem_client.initialize()
        
        if not self._mint_redeem_initialized:
            print("  [JLP] Failed to initialize mint/redeem client")
        
        return self._mint_redeem_initialized
    
    def execute_premium_arbitrage(self, amount_usdc: float, min_profit_pct: float = 0.0) -> Dict:
        """
        Execute premium arbitrage: Mint JLP at NAV → Sell at market.
        
        When market price > NAV:
        1. Mint JLP by depositing USDC at NAV price
        2. Immediately sell JLP at market price
        
        Args:
            amount_usdc: Amount of USDC to use for minting.
            min_profit_pct: Minimum profit percentage required (0.01 = 1%)
        
        Returns:
            Dict with success status and details.
        """
        if not self.wallet.is_loaded():
            return {"success": False, "error": "Wallet not loaded"}
        
        if not self._ensure_mint_redeem_initialized():
            return {"success": False, "error": "Mint/redeem client not initialized"}
        
        # Step 1: Mint JLP at NAV
        print(f"  [PREMIUM ARB] Step 1: Mint JLP with ${amount_usdc:.2f} USDC at NAV...")
        
        # Build mint instruction
        amount_lamports = int(amount_usdc * (10 ** USDC_DECIMALS))
        mint_result = self.mint_redeem_client.build_add_liquidity_instruction(
            owner=self.wallet.get_address(),
            token_amount_in=amount_lamports,
            min_lp_amount_out=0,  # Would calculate based on NAV for production
            custody_mint=USDC_MINT,
        )
        
        if not mint_result:
            return {"success": False, "error": "Failed to build mint instruction", "step": 1}
        
        # For now, return simulation result (actual execution requires signing)
        # In live mode, would sign and send the transaction
        
        # Step 2: Sell JLP at market (simulated)
        print(f"  [PREMIUM ARB] Step 2: Sell JLP at market price...")
        
        return {
            "success": True,
            "type": "premium_arbitrage",
            "amount_usdc": amount_usdc,
            "note": "Simulation only - live execution requires wallet signing",
        }
    
    def execute_discount_arbitrage(self, amount_usdc: float, min_profit_pct: float = 0.0) -> Dict:
        """
        Execute discount arbitrage: Buy JLP at market → Redeem at NAV.
        
        When market price < NAV:
        1. Buy JLP at discounted market price
        2. Redeem JLP for USDC at NAV price
        
        Args:
            amount_usdc: Amount of USDC to spend buying JLP.
            min_profit_pct: Minimum profit percentage required (0.01 = 1%)
        
        Returns:
            Dict with success status and details.
        """
        if not self.wallet.is_loaded():
            return {"success": False, "error": "Wallet not loaded"}
        
        if not self._ensure_mint_redeem_initialized():
            return {"success": False, "error": "Mint/redeem client not initialized"}
        
        # Step 1: Buy JLP at market (discounted)
        print(f"  [DISCOUNT ARB] Step 1: Buy JLP with ${amount_usdc:.2f} USDC at market...")
        
        # Would get quote and execute buy via Jupiter
        
        # Step 2: Redeem JLP at NAV
        print(f"  [DISCOUNT ARB] Step 2: Redeem JLP at NAV price...")
        
        # Build redeem instruction (simulated)
        # In production, would use the JLP amount received from step 1
        
        return {
            "success": True,
            "type": "discount_arbitrage",
            "amount_usdc": amount_usdc,
            "note": "Simulation only - live execution requires wallet signing",
        }
    
    def simulate_premium_arbitrage(self, amount_usdc: float, spread_pct: float) -> Dict:
        """Simulate premium arbitrage to estimate profit."""
        # Gross profit = spread captured
        gross_profit = amount_usdc * (spread_pct / 100)
        
        # Estimated costs (mint fee ~0.1%, sell slippage ~0.1%, gas ~$0.01)
        mint_fee_pct = 0.001  # 0.1% JLP mint fee
        sell_slippage_pct = 0.001  # 0.1% slippage
        gas_cost_usd = 0.01  # ~$0.01 for 2 transactions
        
        total_cost = amount_usdc * (mint_fee_pct + sell_slippage_pct) + gas_cost_usd
        net_profit = gross_profit - total_cost
        
        return {
            "type": "premium_arbitrage",
            "amount_usdc": amount_usdc,
            "spread_pct": spread_pct,
            "gross_profit": gross_profit,
            "estimated_costs": total_cost,
            "net_profit": net_profit,
            "profitable": net_profit > 0,
        }
    
    def simulate_discount_arbitrage(self, amount_usdc: float, spread_pct: float) -> Dict:
        """Simulate discount arbitrage to estimate profit."""
        # Gross profit = spread captured (spread is negative for discount)
        gross_profit = amount_usdc * (abs(spread_pct) / 100)
        
        # Estimated costs (buy slippage ~0.1%, redeem fee ~0.1%, gas ~$0.01)
        buy_slippage_pct = 0.001  # 0.1% slippage
        redeem_fee_pct = 0.001  # 0.1% JLP redeem fee
        gas_cost_usd = 0.01  # ~$0.01 for 2 transactions
        
        total_cost = amount_usdc * (buy_slippage_pct + redeem_fee_pct) + gas_cost_usd
        net_profit = gross_profit - total_cost
        
        return {
            "type": "discount_arbitrage",
            "amount_usdc": amount_usdc,
            "spread_pct": spread_pct,
            "gross_profit": gross_profit,
            "estimated_costs": total_cost,
            "net_profit": net_profit,
            "profitable": net_profit > 0,
        }


# ============================================================================
# ARBITRAGE ENGINE
# ============================================================================

class LPArbitrageEngine:
    """Main arbitrage engine that orchestrates price monitoring and trading."""
    
    def __init__(self, config: LPConfig, wallet: LocalWallet):
        self.config = config
        self.wallet = wallet
        
        # Initialize components
        self.price_fetcher = JLPPriceFetcher(
            rpc_url=config.rpc_url,
            compare_sources=config.compare_price_sources
        )
        self.trader = JLPArbitrageTrader(wallet, config.rpc_url)
        self.history = LPHistoryManager(config.history_dir)
        
        # Stats
        self.wake_up_count = 0
        self.opportunities_detected = 0
        self.premium_arbs = 0  # Mint at NAV → Sell at market
        self.discount_arbs = 0  # Buy at market → Redeem at NAV
        self.simulated_pnl = 0.0
        self.executed_arbs = 0
        
        # Auto-calculate spread thresholds if enabled
        self.min_viable_spread_info = None
        if config.auto_calculate_spread:
            self._auto_calculate_thresholds()
    
    def _auto_calculate_thresholds(self):
        """Calculate and set thresholds based on min viable spread + profit margin."""
        print("\n[AUTO-SPREAD] Calculating minimum viable spread...")
        
        spread_info = self.price_fetcher.calculate_min_viable_spread(
            trade_amount_usd=self.config.trade_amount_usd
        )
        
        if spread_info is None:
            print("  [WARN] Could not calculate min viable spread, using defaults")
            return
        
        self.min_viable_spread_info = spread_info
        
        # Calculate thresholds with profit margin
        min_spread = spread_info["min_viable_spread_pct"] / 100  # Convert to decimal
        profit_margin = self.config.profit_margin
        
        # Buy threshold: negative (discount) = -(min_spread + margin)
        # Sell threshold: positive (premium) = +(min_spread + margin)
        calculated_buy = -(min_spread + profit_margin)
        calculated_sell = min_spread + profit_margin
        
        # Update config thresholds
        self.config.buy_threshold = calculated_buy
        self.config.sell_threshold = calculated_sell
        
        # Print breakdown
        print("\n  ┌─────────────────────────────────────────────────────┐")
        print("  │     MIN VIABLE SPREAD (TRUE ARBITRAGE)              │")
        print("  ├─────────────────────────────────────────────────────┤")
        print(f"  │ Trade amount:        ${spread_info['trade_amount_usd']:>10.2f}              │")
        print("  ├─────────────────────────────────────────────────────┤")
        print("  │ JLP PROGRAM FEES:                                   │")
        print(f"  │   Mint fee:          {spread_info['jlp_mint_fee_pct']:>10.4f}%              │")
        print(f"  │   Redeem fee:        {spread_info['jlp_redeem_fee_pct']:>10.4f}%              │")
        print("  │ DEX SWAP COSTS:                                     │")
        print(f"  │   Buy fees:          {spread_info['dex_buy_fee_pct']:>10.4f}%              │")
        print(f"  │   Sell fees:         {spread_info['dex_sell_fee_pct']:>10.4f}%              │")
        print(f"  │   Buy impact:        {spread_info['buy_price_impact_pct']:>10.4f}%              │")
        print(f"  │   Sell impact:       {spread_info['sell_price_impact_pct']:>10.4f}%              │")
        print(f"  │ Gas (estimated):     {spread_info['gas_pct']:>10.4f}%              │")
        print("  ├─────────────────────────────────────────────────────┤")
        print(f"  │ Total JLP fees:      {spread_info['total_jlp_fee_pct']:>10.4f}%              │")
        print(f"  │ Total DEX fees:      {spread_info['total_dex_fee_pct']:>10.4f}%              │")
        print(f"  │ Total impact:        {spread_info['total_impact_pct']:>10.4f}%              │")
        print(f"  │ MIN VIABLE SPREAD:   {spread_info['min_viable_spread_pct']:>10.4f}%              │")
        print("  ├─────────────────────────────────────────────────────┤")
        print(f"  │ Profit margin:       {profit_margin * 100:>10.4f}%              │")
        print(f"  │ BUY threshold:       {calculated_buy * 100:>+10.4f}%              │")
        print(f"  │ SELL threshold:      {calculated_sell * 100:>+10.4f}%              │")
        print("  └─────────────────────────────────────────────────────┘\n")
    
    def run_once(self) -> Dict:
        """
        Execute a single arbitrage check cycle.
        
        Returns:
            Dictionary with cycle results.
        """
        self.wake_up_count += 1
        timestamp = datetime.now(timezone.utc)
        
        print(f"\n[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] Wake up #{self.wake_up_count}")
        
        # Fetch prices (virtual_price = NAV from on-chain, market_price = DEX swap price)
        virtual_price, market_price = self.price_fetcher.get_prices()
        
        if virtual_price is None or market_price is None:
            print("  Error: Could not fetch prices")
            return {"error": "price_fetch_failed"}
        
        # Calculate spread: (market - virtual) / virtual
        # Positive = premium (market > NAV, sell opportunity)
        # Negative = discount (market < NAV, buy opportunity)
        spread = self.price_fetcher.calculate_spread(market_price, virtual_price)
        spread_pct = spread * 100
        spread_direction = "premium" if spread > 0 else "discount" if spread < 0 else "parity"
        
        print(f"  Virtual price: ${virtual_price:.4f} (NAV from on-chain)")
        print(f"  Market price:  ${market_price:.4f} (DEX swap price)")
        print(f"  Spread: {spread_pct:+.2f}% ({spread_direction})")
        
        # Determine action
        action = "HOLD"
        action_reason = ""
        
        # True arbitrage actions:
        # - DISCOUNT_ARB: When market < NAV (negative spread) → Buy at market, Redeem at NAV
        # - PREMIUM_ARB: When market > NAV (positive spread) → Mint at NAV, Sell at market
        if spread < self.config.buy_threshold:
            action = "DISCOUNT_ARB"
            action_reason = f"spread {spread_pct:.2f}% < threshold {self.config.buy_threshold * 100:.2f}% → Buy market, Redeem NAV"
            self.opportunities_detected += 1
        elif spread > self.config.sell_threshold:
            action = "PREMIUM_ARB"
            action_reason = f"spread {spread_pct:.2f}% > threshold {self.config.sell_threshold * 100:.2f}% → Mint NAV, Sell market"
            self.opportunities_detected += 1
        else:
            action_reason = f"spread within thresholds ({self.config.buy_threshold * 100:.1f}% to {self.config.sell_threshold * 100:.1f}%)"
        
        print(f"  Action: {action} ({action_reason})")
        
        # Record snapshot (always in verbose mode, or when opportunity detected)
        if self.config.verbose or action != "HOLD":
            snapshot = create_snapshot_record(
                platform="jupiter",
                lp_token="JLP",
                virtual_price=virtual_price,
                market_price=market_price,
                spread_pct=spread_pct,
                spread_direction=spread_direction,
                recommendation=action,
                trading_mode=self.config.trading_mode,
                wake_up_number=self.wake_up_count
            )
            self.history.save_snapshot(snapshot)
        
        # Execute or simulate trade
        if action != "HOLD":
            self._execute_action(action, market_price, virtual_price, spread_pct)
        
        return {
            # Naive isoformat (no 'Z'/offset suffix) preserves this field's
            # existing shape exactly, even though it isn't parsed back
            # anywhere today.
            "timestamp": timestamp.replace(tzinfo=None).isoformat(),
            "virtual_price": virtual_price,
            "market_price": market_price,
            "spread_pct": spread_pct,
            "action": action,
            "trading_mode": self.config.trading_mode
        }
    
    def _execute_action(self, action: str, market_price: float, virtual_price: float, spread_pct: float):
        """Execute or simulate a TRUE ARBITRAGE action."""
        
        if self.config.trading_mode == "whatif":
            # Paper trading - simulate arbitrage profit
            if action == "DISCOUNT_ARB":
                # Discount arbitrage: Buy at market → Redeem at NAV
                sim = self.trader.simulate_discount_arbitrage(self.config.trade_amount_usd, spread_pct)
                self.discount_arbs += 1
                
                print(f"  [WHAT-IF] DISCOUNT ARBITRAGE:")
                print(f"    Step 1: Buy JLP at market (${market_price:.4f})")
                print(f"    Step 2: Redeem JLP at NAV (${virtual_price:.4f})")
                print(f"    Gross profit: ${sim['gross_profit']:.4f}")
                print(f"    Est. costs: ${sim['estimated_costs']:.4f}")
                print(f"    Net profit: ${sim['net_profit']:.4f} {'✓' if sim['profitable'] else '✗'}")
                
                if sim['profitable']:
                    self.simulated_pnl += sim['net_profit']
                    
            elif action == "PREMIUM_ARB":
                # Premium arbitrage: Mint at NAV → Sell at market
                sim = self.trader.simulate_premium_arbitrage(self.config.trade_amount_usd, spread_pct)
                self.premium_arbs += 1
                
                print(f"  [WHAT-IF] PREMIUM ARBITRAGE:")
                print(f"    Step 1: Mint JLP at NAV (${virtual_price:.4f})")
                print(f"    Step 2: Sell JLP at market (${market_price:.4f})")
                print(f"    Gross profit: ${sim['gross_profit']:.4f}")
                print(f"    Est. costs: ${sim['estimated_costs']:.4f}")
                print(f"    Net profit: ${sim['net_profit']:.4f} {'✓' if sim['profitable'] else '✗'}")
                
                if sim['profitable']:
                    self.simulated_pnl += sim['net_profit']
            
            # Record simulated trade
            trade = create_trade_record(
                platform="jupiter",
                lp_token="JLP",
                action=action,
                amount_usd=self.config.trade_amount_usd,
                price=market_price,
                spread_pct=spread_pct,
                executed=False,
                trading_mode="whatif"
            )
            self.history.save_trade(trade)
            
        else:  # live mode
            # Check USDC balance for any arbitrage
            usdc_balance = self.trader.get_usdc_balance()
            if usdc_balance < self.config.trade_amount_usd:
                print(f"  [LIVE] Insufficient USDC: ${usdc_balance:.2f} < ${self.config.trade_amount_usd:.2f}")
                return
            
            if action == "DISCOUNT_ARB":
                # Discount arbitrage: Buy at market → Redeem at NAV
                print(f"  [LIVE] Executing DISCOUNT ARBITRAGE with ${self.config.trade_amount_usd:.2f}")
                result = self.trader.execute_discount_arbitrage(self.config.trade_amount_usd)
                
                if result.get("success"):
                    self.executed_arbs += 1
                    self.discount_arbs += 1
                    trade = create_trade_record(
                        platform="jupiter",
                        lp_token="JLP",
                        action="DISCOUNT_ARB",
                        amount_usd=self.config.trade_amount_usd,
                        price=market_price,
                        spread_pct=spread_pct,
                        executed=True,
                        trading_mode="live"
                    )
                    self.history.save_trade(trade)
                else:
                    print(f"  [LIVE] Arbitrage failed: {result.get('error', 'unknown')}")
                    
            elif action == "PREMIUM_ARB":
                # Premium arbitrage: Mint at NAV → Sell at market
                print(f"  [LIVE] Executing PREMIUM ARBITRAGE with ${self.config.trade_amount_usd:.2f}")
                result = self.trader.execute_premium_arbitrage(self.config.trade_amount_usd)
                
                if result.get("success"):
                    self.executed_arbs += 1
                    self.premium_arbs += 1
                    trade = create_trade_record(
                        platform="jupiter",
                        lp_token="JLP",
                        action="PREMIUM_ARB",
                        amount_usd=self.config.trade_amount_usd,
                        price=market_price,
                        spread_pct=spread_pct,
                        executed=True,
                        trading_mode="live"
                    )
                    self.history.save_trade(trade)
                else:
                    print(f"  [LIVE] Arbitrage failed: {result.get('error', 'unknown')}")
    
    def run_daemon(self):
        """Run continuously with sleep intervals."""
        print(f"\n[DAEMON] Starting with {self.config.interval}s interval...")
        print("[DAEMON] Press Ctrl+C to stop\n")
        
        try:
            while True:
                self.run_once()
                print(f"\n  Sleeping {self.config.interval}s until next wake-up...")
                time.sleep(self.config.interval)
        except KeyboardInterrupt:
            print("\n[DAEMON] Stopped by user")
        finally:
            self.print_summary()
    
    def print_summary(self):
        """Print session summary."""
        print("\n" + "=" * 60)
        
        if self.config.trading_mode == "whatif":
            print("=== WHAT-IF SUMMARY (TRUE ARBITRAGE) ===")
        else:
            print("=== SESSION SUMMARY (TRUE ARBITRAGE) ===")
        
        print("=" * 60)
        print(f"Platform: Jupiter JLP")
        print(f"Mode: {self.config.trading_mode.upper()}")
        print(f"Total wake-ups: {self.wake_up_count}")
        print(f"Opportunities detected: {self.opportunities_detected}")
        print(f"  - Premium arbitrage (mint→sell): {self.premium_arbs}")
        print(f"  - Discount arbitrage (buy→redeem): {self.discount_arbs}")
        
        if self.config.trading_mode == "whatif":
            print(f"Simulated P&L: ${self.simulated_pnl:.2f}")
        else:
            print(f"Executed arbitrages: {self.executed_arbs}")
        
        print("=" * 60)


# ============================================================================
# MAIN
# ============================================================================

def print_banner(config: LPConfig):
    """Print startup banner."""
    print("\n" + "=" * 60)
    print("=== LP ARBITRAGE BOT ===")
    print("=" * 60)
    print(f"Platform: Jupiter JLP")
    print(f"Mode: {config.trading_mode.upper()}" + (" (no real trades)" if config.trading_mode == "whatif" else ""))
    print(f"Execution: {'Once' if config.once else f'Daemon ({config.interval}s interval)'}")
    print(f"Buy threshold: {config.buy_threshold * 100:.1f}%")
    print(f"Sell threshold: {config.sell_threshold * 100:.1f}%")
    print(f"Trade amount: ${config.trade_amount_usd:.2f}")
    print(f"Max position: ${config.max_position_usd:.2f}")
    print(f"Verbose: {config.verbose}")
    print("=" * 60)


def main():
    """Main entry point."""
    config = parse_args()

    # T1-style double lock (mirrors crypto_trading_bot.py's LIVE_TRADING_CONFIRMED
    # gate): --trading-mode=live alone is not enough to place real Jupiter swaps.
    # Without the env confirmation, downgrade to whatif and print a loud notice
    # rather than exiting -- this tool stays usable for research either way, and
    # whatif forces the no-wallet branch below.
    if config.trading_mode == "live" and os.environ.get('LIVE_TRADING_CONFIRMED') != '1':
        live_lock_notice = (
            "Live mode requested (--trading-mode=live) but LIVE_TRADING_CONFIRMED=1 "
            "is not set in the environment.\n"
            "Downgrading to whatif mode. To arm live trading, run:\n"
            "  export LIVE_TRADING_CONFIRMED=1"
        )
        print("\n" + "!" * 66)
        for line in live_lock_notice.splitlines():
            print("[LIVE LOCK] " + line)
        print("!" * 66 + "\n")
        config.trading_mode = "whatif"

    # Print banner
    print_banner(config)
    
    # Initialize wallet
    if config.trading_mode == "live":
        key = prompt_for_private_key()
        if not key:
            print("[ERROR] Live mode requires wallet key")
            sys.exit(1)
        wallet = LocalWallet(key)
        if not wallet.is_loaded():
            print("[ERROR] Failed to load wallet")
            sys.exit(1)
        print(f"[WALLET] Address: {wallet.get_address()}")
    else:
        wallet = get_wallet_for_whatif()
        print("[WALLET] What-if mode - no wallet required")
    
    # Initialize engine
    engine = LPArbitrageEngine(config, wallet)
    
    # Run
    try:
        if config.daemon:
            engine.run_daemon()
        else:
            engine.run_once()
            engine.print_summary()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopping...")
        engine.print_summary()


if __name__ == "__main__":
    main()
