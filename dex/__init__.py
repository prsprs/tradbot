"""
DEX Trading Module - Solana DEX trading via WalletConnect + Phantom + Jupiter.

This module provides decentralized exchange trading capabilities for the trading bot,
starting with Solana via the Jupiter aggregator.

Components:
- token_cache: Jupiter verified token list caching
- jupiterutil: Jupiter API integration (quotes, swaps, token lookup)
- walletconnect: WalletConnect v2 session management
- trader: SolanaDEXTrader class (main interface)
"""

from .trader import SolanaDEXTrader

__all__ = ['SolanaDEXTrader']
