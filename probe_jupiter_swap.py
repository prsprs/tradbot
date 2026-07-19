#!/usr/bin/env python3
"""
Jupiter Swap Test - Verify wallet, balances, and swap execution.

This test program:
1. Loads wallet from interactive prompt
2. Checks SOL and USDC balances
3. Executes a small USDC → SOL swap ($1)
4. Checks balances again to verify

Usage:
    python probe_jupiter_swap.py
"""

import base64
import time
from typing import Optional, Dict, Tuple

import httpx

from dex.local_wallet import LocalWallet, prompt_for_private_key
from dex.jupiterutil import JupiterClient, SOL_MINT, USDC_MINT

# Solana RPC endpoint
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# Test amount: $1 USDC (1,000,000 units with 6 decimals)
TEST_AMOUNT_USD = 1.0
TEST_AMOUNT_USDC = int(TEST_AMOUNT_USD * 1_000_000)


def get_sol_balance(address: str) -> Optional[float]:
    """Get SOL balance for an address.
    
    Returns:
        SOL balance or None on error.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                SOLANA_RPC,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [address]
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "result" in data and "value" in data["result"]:
                lamports = data["result"]["value"]
                return lamports / 1_000_000_000  # Convert to SOL
            else:
                print(f"[BALANCE] Unexpected response: {data}")
                return None
    except Exception as e:
        print(f"[BALANCE] Error getting SOL balance: {e}")
        return None


def get_token_balance(address: str, mint: str) -> Optional[float]:
    """Get SPL token balance for an address.
    
    Args:
        address: Wallet address
        mint: Token mint address
        
    Returns:
        Token balance or None on error.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                SOLANA_RPC,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        address,
                        {"mint": mint},
                        {"encoding": "jsonParsed"}
                    ]
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "result" in data and "value" in data["result"]:
                accounts = data["result"]["value"]
                if accounts:
                    # Sum all token accounts for this mint
                    total = 0.0
                    for account in accounts:
                        info = account["account"]["data"]["parsed"]["info"]
                        amount = float(info["tokenAmount"]["uiAmount"] or 0)
                        total += amount
                    return total
                else:
                    return 0.0  # No token account = 0 balance
            else:
                print(f"[BALANCE] Unexpected response: {data}")
                return None
    except Exception as e:
        print(f"[BALANCE] Error getting token balance: {e}")
        return None


def get_all_token_balances(address: str) -> Optional[list]:
    """Get all SPL token balances for an address.
    
    Returns:
        List of (symbol, mint, balance) tuples or None on error.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                SOLANA_RPC,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        address,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"}
                    ]
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "result" in data and "value" in data["result"]:
                accounts = data["result"]["value"]
                balances = []
                for account in accounts:
                    info = account["account"]["data"]["parsed"]["info"]
                    mint = info["mint"]
                    amount = float(info["tokenAmount"]["uiAmount"] or 0)
                    if amount > 0:
                        balances.append((mint, amount))
                return balances
            else:
                print(f"[BALANCE] Unexpected response: {data}")
                return None
    except Exception as e:
        print(f"[BALANCE] Error getting all token balances: {e}")
        return None


def print_wallet_contents(address: str):
    """Print comprehensive wallet contents."""
    print(f"\n{'='*60}")
    print(f"  WALLET CONTENTS: {address[:12]}...{address[-6:]}")
    print(f"{'='*60}")
    
    # SOL balance
    sol = get_sol_balance(address)
    if sol is not None:
        print(f"  SOL: {sol:.6f}")
    else:
        print(f"  SOL: [error fetching]")
    
    # All SPL tokens
    tokens = get_all_token_balances(address)
    if tokens:
        print(f"\n  SPL Tokens ({len(tokens)}):")
        for mint, amount in sorted(tokens, key=lambda x: -x[1]):
            # Identify well-known tokens
            if mint == USDC_MINT:
                symbol = "USDC"
            elif mint == SOL_MINT:
                symbol = "wSOL"
            else:
                symbol = f"{mint[:8]}..."
            print(f"    {symbol}: {amount:.6f}")
    elif tokens is not None:
        print(f"\n  SPL Tokens: None")
    else:
        print(f"\n  SPL Tokens: [error fetching]")
    
    print(f"{'='*60}\n")


def send_transaction(signed_tx: bytes) -> Optional[str]:
    """Send a signed transaction to Solana.
    
    Returns:
        Transaction signature or None on error.
    """
    try:
        tx_base64 = base64.b64encode(signed_tx).decode('utf-8')
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                SOLANA_RPC,
                json={
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
            )
            response.raise_for_status()
            data = response.json()
            
            if "result" in data:
                return data["result"]
            elif "error" in data:
                print(f"[TX] Error: {data['error']}")
                return None
            else:
                print(f"[TX] Unexpected response: {data}")
                return None
    except Exception as e:
        print(f"[TX] Error sending transaction: {e}")
        return None


def confirm_transaction(signature: str, timeout: int = 60) -> bool:
    """Wait for transaction confirmation.
    
    Returns:
        True if confirmed, False otherwise.
    """
    print(f"[TX] Waiting for confirmation...")
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    SOLANA_RPC,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getSignatureStatuses",
                        "params": [[signature]]
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                if "result" in data and "value" in data["result"]:
                    status = data["result"]["value"][0]
                    if status:
                        if status.get("err"):
                            print(f"[TX] Transaction failed: {status['err']}")
                            return False
                        conf = status.get("confirmationStatus")
                        if conf in ["confirmed", "finalized"]:
                            print(f"[TX] Confirmed! Status: {conf}")
                            return True
        except Exception as e:
            print(f"[TX] Error checking status: {e}")
        
        time.sleep(2)
    
    print(f"[TX] Timeout waiting for confirmation")
    return False


def print_balances(address: str, label: str):
    """Print SOL and USDC balances."""
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    
    sol = get_sol_balance(address)
    usdc = get_token_balance(address, USDC_MINT)
    
    if sol is not None:
        print(f"  SOL:  {sol:.6f}")
    else:
        print(f"  SOL:  [error]")
    
    if usdc is not None:
        print(f"  USDC: {usdc:.6f}")
    else:
        print(f"  USDC: [error]")
    
    print(f"{'='*50}\n")
    
    return sol, usdc


def main():
    print("\n" + "="*60)
    print("         JUPITER SWAP TEST")
    print("="*60)
    print(f"\nThis test will swap ${TEST_AMOUNT_USD:.2f} USDC → SOL")
    print("to verify wallet and Jupiter integration.\n")
    
    # Step 1: Load wallet
    print("STEP 1: Load Wallet")
    print("-" * 40)
    
    key = prompt_for_private_key()
    if not key:
        print("\n[TEST] Cancelled - no key provided")
        return
    
    wallet = LocalWallet(key)
    if not wallet.is_loaded():
        print("\n[TEST] FAILED - Could not load wallet")
        return
    
    address = wallet.get_address()
    print(f"\n[TEST] Wallet loaded: {address}")
    
    # Show wallet contents regardless of address match
    print_wallet_contents(address)
    
    print(f"⚠️  IMPORTANT: Verify this address matches your Phantom wallet!")
    print(f"    Expected: GjZQKarUWi1b1XrZ86Qy8c12jhpweCoqKAbAifCxJZt2")
    print(f"    Got:      {address}")
    
    if address != "GjZQKarUWi1b1XrZ86Qy8c12jhpweCoqKAbAifCxJZt2":
        print(f"\n[TEST] ❌ Address MISMATCH - key decoding produced wrong wallet")
        print("[TEST] The private key bytes don't match your wallet.")
        print("[TEST] This is a Jupiter key format issue we need to debug.")
        # Don't return - show the wallet contents anyway for debugging
    else:
        print(f"\n[TEST] ✓ Address matches!")
    
    confirm = input("\nContinue with swap test? (y/n): ").strip().lower()
    if confirm != 'y':
        print("\n[TEST] Cancelled by user")
        return
    
    # Step 2: Check initial balances
    print("\nSTEP 2: Check Initial Balances")
    print("-" * 40)
    
    sol_before, usdc_before = print_balances(address, "BALANCES BEFORE SWAP")
    
    if usdc_before is None or usdc_before < TEST_AMOUNT_USD:
        print(f"[TEST] FAILED - Insufficient USDC balance")
        print(f"[TEST] Need ${TEST_AMOUNT_USD:.2f}, have ${usdc_before or 0:.2f}")
        return
    
    if sol_before is None or sol_before < 0.01:
        print(f"[TEST] WARNING - Low SOL balance for fees")
        print(f"[TEST] Have {sol_before or 0:.4f} SOL, recommend at least 0.01")
    
    # Step 3: Get quote from Jupiter
    print("\nSTEP 3: Get Jupiter Quote")
    print("-" * 40)
    
    jupiter = JupiterClient(slippage_bps=100)  # 1% slippage
    
    print(f"[QUOTE] Requesting: {TEST_AMOUNT_USD} USDC → SOL")
    quote = jupiter.get_quote(
        input_mint=USDC_MINT,
        output_mint=SOL_MINT,
        amount=TEST_AMOUNT_USDC
    )
    
    if not quote:
        print("[TEST] FAILED - Could not get quote")
        return
    
    out_amount = int(quote.get("outAmount", 0))
    out_sol = out_amount / 1_000_000_000
    price_impact = float(quote.get("priceImpactPct", 0))
    
    print(f"[QUOTE] Output: {out_sol:.6f} SOL")
    print(f"[QUOTE] Price impact: {price_impact:.4f}%")
    print(f"[QUOTE] Route: {quote.get('routePlan', [{}])[0].get('swapInfo', {}).get('label', 'unknown')}")
    
    # Step 4: Get swap transaction
    print("\nSTEP 4: Build Swap Transaction")
    print("-" * 40)
    
    swap_tx = jupiter.get_swap_transaction(
        quote=quote,
        user_public_key=address
    )
    
    if not swap_tx:
        print("[TEST] FAILED - Could not build swap transaction")
        return
    
    print(f"[TX] Got transaction ({len(swap_tx)} chars base64)")
    
    # Step 5: Sign transaction
    print("\nSTEP 5: Sign Transaction")
    print("-" * 40)
    
    tx_bytes = base64.b64decode(swap_tx)
    signed_tx = wallet.sign_transaction(tx_bytes)
    
    if not signed_tx:
        print("[TEST] FAILED - Could not sign transaction")
        return
    
    print(f"[TX] Signed ({len(signed_tx)} bytes)")
    
    # Step 6: Send transaction
    print("\nSTEP 6: Send Transaction")
    print("-" * 40)
    
    signature = send_transaction(signed_tx)
    
    if not signature:
        print("[TEST] FAILED - Could not send transaction")
        return
    
    print(f"[TX] Signature: {signature}")
    print(f"[TX] Explorer: https://solscan.io/tx/{signature}")
    
    # Step 7: Wait for confirmation
    print("\nSTEP 7: Confirm Transaction")
    print("-" * 40)
    
    confirmed = confirm_transaction(signature)
    
    if not confirmed:
        print("[TEST] FAILED - Transaction not confirmed")
        return
    
    # Step 8: Check final balances
    print("\nSTEP 8: Check Final Balances")
    print("-" * 40)
    
    # Wait a moment for balance updates
    time.sleep(2)
    
    sol_after, usdc_after = print_balances(address, "BALANCES AFTER SWAP")
    
    # Summary
    print("\n" + "="*60)
    print("                    TEST SUMMARY")
    print("="*60)
    
    if sol_before is not None and sol_after is not None:
        sol_change = sol_after - sol_before
        print(f"  SOL change:  {sol_change:+.6f}")
    
    if usdc_before is not None and usdc_after is not None:
        usdc_change = usdc_after - usdc_before
        print(f"  USDC change: {usdc_change:+.6f}")
    
    print(f"\n  Transaction: {signature[:20]}...")
    print(f"  Explorer: https://solscan.io/tx/{signature}")
    print("\n" + "="*60)
    print("  ✓ TEST PASSED - Jupiter swap executed successfully!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
