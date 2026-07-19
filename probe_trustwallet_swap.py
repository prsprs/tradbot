#!/usr/bin/env python3
"""Test DEX swap integration.

Supports two modes:
1. Trust Wallet CLI (twak) - if installed and configured
2. Direct private key - prompts for Solana private key

This script tests:
1. Wallet loading and address verification
2. Balance checking
3. Getting a swap quote
4. Optionally executing a small test swap

Usage:
    python probe_trustwallet_swap.py [--pair BASE/QUOTE]

Examples:
    python probe_trustwallet_swap.py                    # Default: SOL/USDC
    python probe_trustwallet_swap.py --pair WTAO/USDC   # Test with WTAO
"""

import sys
import os
import getpass
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dex.local_wallet import LocalWallet
from dex.jupiterutil import JupiterClient
from leading_indicator_tester import LiveTrade
import json
from pathlib import Path
from datetime import datetime, timezone

# Test trade log file
TEST_TRADES_FILE = Path('./live_trades/test_trades.json')

def log_test_trade(trade_data: dict):
    """
    Log a test trade to separate file for tax purposes.
    
    Test trades are marked with type='test' to distinguish them from
    live trading and back-testing data.
    """
    # Ensure directory exists
    TEST_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing trades
    trades = []
    if TEST_TRADES_FILE.exists():
        try:
            with open(TEST_TRADES_FILE, 'r') as f:
                data = json.load(f)
                trades = data.get('trades', [])
        except (json.JSONDecodeError, KeyError):
            trades = []
    
    # Ensure test type is set
    trade_data['type'] = 'test'
    trade_data['logged_at'] = datetime.now(timezone.utc).isoformat()
    
    # Append new trade
    trades.append(trade_data)
    
    # Save
    with open(TEST_TRADES_FILE, 'w') as f:
        json.dump({
            'description': 'Test swap transactions - NOT for back-testing',
            'trades': trades
        }, f, indent=2)
    
    print(f"  📝 Test trade logged to {TEST_TRADES_FILE}")


# Test parameters
TEST_AMOUNT_USD = 3.0  # $3 test swap
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# Global pair config (set by args)
BASE_TOKEN = "SOL"
BASE_MINT = SOL_MINT
QUOTE_TOKEN = "USDC"
QUOTE_MINT = USDC_MINT
BASE_DECIMALS = 9
QUOTE_DECIMALS = 6


def validate_live_trade_dataclass(
    action: str,
    signature: str,
    input_token: str,
    output_token: str,
    input_amount: float,
    output_amount: float,
    amount: float,
    position_size_usd: float,
    price_usd: float,
) -> bool:
    """
    Validate that LiveTrade dataclass works with all expected fields.
    
    This catches field mismatches between test program and live trading code.
    If this fails, the live program would also fail after executing a trade.
    """
    from datetime import datetime, timezone
    import uuid
    
    print("\nSTEP 8: Validate LiveTrade Dataclass")
    print("-" * 40)
    
    try:
        # Create a LiveTrade object exactly as the live program does
        trade = LiveTrade(
            id=f"test_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            type="live",
            pair=f"TEST:{BASE_TOKEN}",
            action=action,
            follower=QUOTE_TOKEN if action == "BUY" else BASE_TOKEN,
            input_token=input_token,
            output_token=output_token,
            input_amount=input_amount,
            output_amount=output_amount,
            amount=amount,
            position_size_usd=position_size_usd,
            price_usd=price_usd,
            slippage_bps=100,
            trigger={"test": True},
            timing={"test": True},
            transaction={
                "signature": signature,
                "status": "confirmed",
            },
        )
        
        # Now validate we can access all fields the live program uses in its print statement
        # This is the exact line that was failing: line 2478 in leading_indicator_tester.py
        test_output = f"Size: ${trade.position_size_usd:.2f} ({trade.amount:.6f} {trade.follower})"
        
        # Additional field access validation
        _ = trade.action
        _ = trade.price_usd
        _ = trade.transaction.get("signature", "")[:16]
        
        print(f"  ✓ LiveTrade dataclass validation PASSED")
        print(f"  Test output: {test_output}")
        return True
        
    except AttributeError as e:
        print(f"  ❌ LiveTrade dataclass validation FAILED")
        print(f"  Missing attribute: {e}")
        print(f"  This would cause the live program to crash after executing a trade!")
        return False
    except Exception as e:
        print(f"  ❌ LiveTrade validation error: {e}")
        return False


def confirm_transaction(signature: str, timeout_seconds: int = 30):
    """Wait for transaction confirmation and return parsed result.
    
    This is the same logic used in the live trading program.
    
    Returns:
        Dict with confirmation status and token balance changes, or None on timeout/error.
    """
    import time
    import requests
    
    rpc_url = SOLANA_RPC
    start_time = time.time()
    
    print(f"  Confirming transaction (timeout: {timeout_seconds}s)...")
    
    while time.time() - start_time < timeout_seconds:
        try:
            # Check transaction status
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0,
                    }
                ]
            }
            
            response = requests.post(rpc_url, json=payload, timeout=10)
            result = response.json()
            
            if "error" in result:
                error_code = result['error'].get('code', 0) if isinstance(result['error'], dict) else 0
                if error_code == 429:
                    print(f"  ⚠️  Rate limited, waiting 5s...")
                    time.sleep(5)
                else:
                    print(f"  ⚠️  Confirmation check error: {result['error']}")
                    time.sleep(3)
                continue
            
            tx_data = result.get("result")
            if tx_data is None:
                # Transaction not yet confirmed
                time.sleep(2)
                continue
            
            # Transaction confirmed - parse token balance changes
            meta = tx_data.get("meta", {})
            if meta.get("err"):
                return {"status": "failed", "error": str(meta["err"])}
            
            # Extract pre/post token balances
            pre_balances = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])
            
            # Calculate balance changes by mint
            balance_changes = {}
            for post in post_balances:
                mint = post.get("mint", "")
                owner = post.get("owner", "")
                post_amount = float(post.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                
                # Find matching pre-balance
                pre_amount = 0.0
                for pre in pre_balances:
                    if pre.get("mint") == mint and pre.get("owner") == owner:
                        pre_amount = float(pre.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
                        break
                
                change = post_amount - pre_amount
                if abs(change) > 0.000001:  # Ignore dust
                    balance_changes[mint] = {
                        "pre": pre_amount,
                        "post": post_amount,
                        "change": change,
                    }
            
            # Also check SOL balance change
            pre_sol = meta.get("preBalances", [0])[0] / 1e9 if meta.get("preBalances") else 0
            post_sol = meta.get("postBalances", [0])[0] / 1e9 if meta.get("postBalances") else 0
            sol_change = post_sol - pre_sol
            
            return {
                "status": "confirmed",
                "slot": tx_data.get("slot"),
                "token_changes": balance_changes,
                "sol_change": sol_change,
                "fee_sol": meta.get("fee", 0) / 1e9,
            }
            
        except Exception as e:
            print(f"  ⚠️  Confirmation polling error: {e}")
            time.sleep(2)
    
    print(f"  ⚠️  Transaction confirmation timeout after {timeout_seconds}s")
    return None


def test_with_private_key():
    """Test using direct private key input (BUY: base → quote)."""
    print("=" * 60)
    print(f"     DEX BUY TEST ({BASE_TOKEN} → {QUOTE_TOKEN})")
    print("=" * 60)
    print(f"\nThis test will verify wallet and Jupiter integration")
    print(f"and optionally execute a ~${TEST_AMOUNT_USD:.2f} {BASE_TOKEN} → {QUOTE_TOKEN} swap.\n")
    
    # Step 1: Get private key
    print("STEP 1: Wallet Authentication")
    print("-" * 40)
    
    private_key = os.environ.get("SOLANA_PRIVATE_KEY")
    if private_key:
        print("Using key from SOLANA_PRIVATE_KEY environment variable")
    else:
        print("Enter your Solana wallet private key (base58 encoded)")
        print("(Input is hidden)")
        private_key = getpass.getpass("Private Key: ")
    
    if not private_key:
        print("\n❌ Private key required")
        return
    
    # Step 2: Load wallet
    print("\nSTEP 2: Load Wallet")
    print("-" * 40)
    
    try:
        wallet = LocalWallet(private_key)
        address = wallet.get_address()
        print(f"✓ Wallet loaded: {address}")
        print(f"\n⚠️  Verify this matches your expected wallet address!")
    except Exception as e:
        print(f"❌ Failed to load wallet: {e}")
        return
    
    # Step 3: Check balances
    print("\nSTEP 3: Check Balances")
    print("-" * 40)
    
    jupiter = JupiterClient()
    import requests
    
    # Get SOL balance via RPC (always needed for fees)
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }, timeout=10)
        data = resp.json()
        sol_balance = data.get("result", {}).get("value", 0) / 1e9
        print(f"  SOL: {sol_balance:.6f}")
    except Exception as e:
        print(f"  SOL: (error: {e})")
        sol_balance = 0
    
    # Get base token balance (for BUY we're selling base token)
    base_balance = 0
    if BASE_TOKEN == "SOL":
        base_balance = sol_balance
    else:
        try:
            resp = requests.post(SOLANA_RPC, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    address,
                    {"mint": BASE_MINT},
                    {"encoding": "jsonParsed"}
                ]
            }, timeout=10)
            data = resp.json()
            accounts = data.get("result", {}).get("value", [])
            if accounts:
                base_balance = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
            print(f"  {BASE_TOKEN}: {base_balance:.6f}")
        except Exception as e:
            print(f"  {BASE_TOKEN}: (error: {e})")
    
    # Get quote token balance
    quote_balance = 0
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": QUOTE_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=10)
        data = resp.json()
        accounts = data.get("result", {}).get("value", [])
        if accounts:
            quote_balance = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
        print(f"  {QUOTE_TOKEN}: {quote_balance:.2f}")
    except Exception as e:
        print(f"  {QUOTE_TOKEN}: (error: {e})")
    
    # Get base token price and calculate amount for test
    price_result = jupiter.get_price(BASE_TOKEN)
    if not price_result:
        print(f"❌ Could not get {BASE_TOKEN} price")
        return
    
    base_price = price_result[0]  # get_price returns (price, bid, ask) tuple
    base_amount_for_test = TEST_AMOUNT_USD / base_price
    base_smallest_units = int(base_amount_for_test * (10 ** BASE_DECIMALS))
    
    print(f"\n  {BASE_TOKEN} price: ${base_price:.4f}")
    print(f"  Test amount: {base_amount_for_test:.6f} {BASE_TOKEN} (~${TEST_AMOUNT_USD:.2f})")
    
    if base_balance < base_amount_for_test:
        print(f"\n⚠️  Insufficient {BASE_TOKEN} for test swap (need ~{base_amount_for_test:.6f})")
    
    # Step 4: Get swap quote
    print(f"\nSTEP 4: Get Swap Quote ({BASE_TOKEN} → {QUOTE_TOKEN})")
    print("-" * 40)
    
    try:
        quote = jupiter.get_quote(BASE_MINT, QUOTE_MINT, base_smallest_units)
        if quote:
            out_amount = int(quote.get("outAmount", 0)) / (10 ** QUOTE_DECIMALS)
            price_impact = float(quote.get("priceImpactPct", 0))
            print(f"Quote: {base_amount_for_test:.6f} {BASE_TOKEN} → {out_amount:.4f} {QUOTE_TOKEN}")
            print(f"Price impact: {price_impact:.4f}%")
        else:
            print("❌ No quote returned")
            return
    except Exception as e:
        print(f"❌ Failed to get quote: {e}")
        return
    
    # Step 5: Execute swap (optional)
    print("\nSTEP 5: Execute Test Swap")
    print("-" * 40)
    print(f"\n⚠️  This will swap {base_amount_for_test:.6f} {BASE_TOKEN} for ~{out_amount:.4f} {QUOTE_TOKEN}")
    print(f"    From wallet: {address}")
    
    confirm = input("\nExecute swap? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nSwap cancelled. Test complete.")
        print("\nSummary:")
        print(f"  ✓ Wallet loaded: {address}")
        print(f"  ✓ {BASE_TOKEN} balance: {base_balance:.6f}")
        print(f"  ✓ {QUOTE_TOKEN} balance: {quote_balance:.2f}")
        print(f"  ✓ {BASE_TOKEN} for swap: {base_amount_for_test:.6f} (~${TEST_AMOUNT_USD:.2f})")
        print(f"  ✓ Quote API: Working")
        print(f"  - Swap execution: Skipped")
        return
    
    print("\nExecuting swap...")
    try:
        import base64
        from solders.transaction import VersionedTransaction
        
        # Get swap transaction from Jupiter
        swap_tx_b64 = jupiter.get_swap_transaction(quote, address)
        if not swap_tx_b64:
            print("❌ Failed to get swap transaction")
            return
        
        print("  Got swap transaction from Jupiter")
        
        # Sign using LocalWallet (same as live program)
        tx_bytes = base64.b64decode(swap_tx_b64)
        signed_tx = wallet.sign_transaction(tx_bytes)
        
        if not signed_tx:
            print("❌ Failed to sign transaction")
            return
        
        print("  Transaction signed")
        
        # Send transaction (same params as live program)
        signed_tx_b64 = base64.b64encode(signed_tx).decode('utf-8')
        
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_tx_b64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 3,
                }
            ]
        }, timeout=30)
        
        result = resp.json()
        if "error" in result:
            print(f"❌ RPC error: {result['error']}")
            return
        
        tx_hash = result.get("result", "")
        
        print(f"\n✓ Swap submitted!")
        print(f"  Transaction: {tx_hash}")
        print(f"  Explorer: https://solscan.io/tx/{tx_hash}")
        
    except Exception as e:
        print(f"\n❌ Swap error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 6: Confirm transaction on-chain
    print("\nSTEP 6: Confirm Transaction")
    print("-" * 40)
    
    confirmation = confirm_transaction(tx_hash, timeout_seconds=30)
    
    if confirmation and confirmation.get("status") == "confirmed":
        print(f"  ✓ Transaction CONFIRMED (slot: {confirmation.get('slot')})")
        print(f"  Fee: {confirmation.get('fee_sol', 0):.6f} SOL")
        
        # Show actual balance changes from the transaction
        token_changes = confirmation.get("token_changes", {})
        sol_change = confirmation.get("sol_change", 0)
        
        print(f"\n  Actual changes from transaction:")
        print(f"    SOL: {sol_change:+.6f}")
        for mint, change_info in token_changes.items():
            change = change_info.get("change", 0)
            # Try to identify the token
            if mint == QUOTE_MINT:
                print(f"    {QUOTE_TOKEN}: {change:+.6f}")
            elif mint == BASE_MINT:
                print(f"    {BASE_TOKEN}: {change:+.6f}")
            else:
                print(f"    {mint[:8]}...: {change:+.6f}")
    elif confirmation and confirmation.get("status") == "failed":
        print(f"  ❌ Transaction FAILED: {confirmation.get('error')}")
    else:
        print(f"  ⚠️  Could not confirm transaction within timeout")
        print(f"      Check explorer: https://solscan.io/tx/{tx_hash}")
    
    # Step 7: Show wallet balances (with stale warning)
    print("\nSTEP 7: Current Wallet Balances")
    print("-" * 40)
    print("⚠️  NOTE: RPC balance queries can be stale for 5+ minutes.")
    print("    The transaction confirmation above is the reliable source.")
    
    try:
        # Get SOL balance via RPC
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }, timeout=10)
        data = resp.json()
        new_sol = data.get("result", {}).get("value", 0) / 1e9
        
        # Get quote token balance
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": QUOTE_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=10)
        data = resp.json()
        accounts = data.get("result", {}).get("value", [])
        if accounts:
            new_quote = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
        else:
            new_quote = 0
        
        if BASE_TOKEN == "SOL":
            print(f"  {BASE_TOKEN}: {new_sol:.6f} (was {base_balance:.6f})")
        else:
            print(f"  SOL: {new_sol:.6f} (was {sol_balance:.6f})")
        print(f"  {QUOTE_TOKEN}: {new_quote:.4f} (was {quote_balance:.4f})")
    except Exception as e:
        print(f"Could not fetch balances: {e}")
    
    # Log test trade for tax purposes (only if confirmed)
    if confirmation and confirmation.get("status") == "confirmed":
        log_test_trade({
            'id': f"test_buy_{tx_hash[:8]}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': 'BUY',
            'pair': f"{BASE_TOKEN}/{QUOTE_TOKEN}",
            'input_token': BASE_TOKEN,
            'output_token': QUOTE_TOKEN,
            'input_amount': base_amount_for_test,
            'output_amount': out_amount,
            'price_usd': base_price,
            'transaction': {
                'signature': tx_hash,
                'status': 'confirmed',
                'slot': confirmation.get('slot'),
                'fee_sol': confirmation.get('fee_sol', 0),
            },
        })
    
    # Validate LiveTrade dataclass (catches field mismatches with live program)
    validate_live_trade_dataclass(
        action="BUY",
        signature=tx_hash,
        input_token=BASE_TOKEN,
        output_token=QUOTE_TOKEN,
        input_amount=base_amount_for_test,
        output_amount=out_amount,
        amount=out_amount,  # Tokens received
        position_size_usd=TEST_AMOUNT_USD,
        price_usd=base_price,
    )
    
    print("\n" + "=" * 60)
    print("BUY TEST COMPLETE")
    print("=" * 60)


def test_sell_with_private_key():
    """Test SELL (quote → base) using direct private key input.
    
    This mirrors the execute_sell logic in the live trading program.
    For SOL/USDC pair: sells USDC to get SOL (reverses BUY).
    """
    print("=" * 60)
    print(f"     DEX SELL TEST ({QUOTE_TOKEN} → {BASE_TOKEN})")
    print("=" * 60)
    print(f"\nThis test will verify the SELL flow works correctly")
    print(f"and optionally execute a ~${TEST_AMOUNT_USD:.2f} {QUOTE_TOKEN} → {BASE_TOKEN} swap.\n")
    
    # Step 1: Get private key
    print("STEP 1: Wallet Authentication")
    print("-" * 40)
    
    private_key = os.environ.get("SOLANA_PRIVATE_KEY")
    mnemonic = os.environ.get("WALLET_MNEMONIC")
    
    if private_key:
        print("Using key from SOLANA_PRIVATE_KEY environment variable")
        key_input = private_key
    elif mnemonic:
        print("Using mnemonic from WALLET_MNEMONIC environment variable")
        key_input = mnemonic
    else:
        print("Enter your Solana wallet private key or 12-word mnemonic")
        print("(Input is hidden)")
        key_input = getpass.getpass("Private Key/Mnemonic: ")
    
    if not key_input:
        print("\n❌ Private key or mnemonic required")
        return
    
    # Step 2: Load wallet
    print("\nSTEP 2: Load Wallet")
    print("-" * 40)
    
    try:
        wallet = LocalWallet(key_input)
        address = wallet.get_address()
        print(f"✓ Wallet loaded: {address}")
        print(f"\n⚠️  Verify this matches your expected wallet address!")
    except Exception as e:
        print(f"❌ Failed to load wallet: {e}")
        return
    
    # Step 3: Check balances
    print("\nSTEP 3: Check Balances")
    print("-" * 40)
    
    jupiter = JupiterClient()
    import requests
    
    # Get SOL balance via RPC (always needed for fees)
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }, timeout=10)
        data = resp.json()
        sol_balance = data.get("result", {}).get("value", 0) / 1e9
        print(f"  SOL: {sol_balance:.6f}")
    except Exception as e:
        print(f"  SOL: (error: {e})")
        sol_balance = 0
    
    # Get quote token balance (what we're selling in SELL test)
    quote_balance = 0
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": QUOTE_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=10)
        data = resp.json()
        accounts = data.get("result", {}).get("value", [])
        if accounts:
            quote_balance = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
        print(f"  {QUOTE_TOKEN}: {quote_balance:.2f}")
    except Exception as e:
        print(f"  {QUOTE_TOKEN}: (error: {e})")
    
    # Get base token balance
    base_balance = 0
    if BASE_TOKEN == "SOL":
        base_balance = sol_balance
    else:
        try:
            resp = requests.post(SOLANA_RPC, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    address,
                    {"mint": BASE_MINT},
                    {"encoding": "jsonParsed"}
                ]
            }, timeout=10)
            data = resp.json()
            accounts = data.get("result", {}).get("value", [])
            if accounts:
                base_balance = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
            print(f"  {BASE_TOKEN}: {base_balance:.6f}")
        except Exception as e:
            print(f"  {BASE_TOKEN}: (error: {e})")
    
    # Get quote token price and calculate amount for test
    price_result = jupiter.get_price(QUOTE_TOKEN)
    if not price_result:
        print(f"❌ Could not get {QUOTE_TOKEN} price")
        return
    
    quote_price = price_result[0]  # get_price returns (price, bid, ask) tuple
    quote_amount_for_test = TEST_AMOUNT_USD / quote_price
    quote_smallest_units = int(quote_amount_for_test * (10 ** QUOTE_DECIMALS))
    
    print(f"\n  {QUOTE_TOKEN} price: ${quote_price:.4f}")
    print(f"  Test amount: {quote_amount_for_test:.6f} {QUOTE_TOKEN} (~${TEST_AMOUNT_USD:.2f})")
    
    if quote_balance < quote_amount_for_test:
        print(f"\n⚠️  Insufficient {QUOTE_TOKEN} for test swap (need ~{quote_amount_for_test:.6f})")
        print(f"    Run a BUY test first to get some {QUOTE_TOKEN}.")
        return
    
    # Step 4: Get swap quote (quote → base)
    print(f"\nSTEP 4: Get Swap Quote ({QUOTE_TOKEN} → {BASE_TOKEN})")
    print("-" * 40)
    
    try:
        quote = jupiter.get_quote(QUOTE_MINT, BASE_MINT, quote_smallest_units)
        if quote:
            out_amount = int(quote.get("outAmount", 0)) / (10 ** BASE_DECIMALS)
            price_impact = float(quote.get("priceImpactPct", 0))
            print(f"Quote: {quote_amount_for_test:.2f} {QUOTE_TOKEN} → {out_amount:.6f} {BASE_TOKEN}")
            print(f"Price impact: {price_impact:.4f}%")
        else:
            print("❌ No quote returned")
            return
    except Exception as e:
        print(f"❌ Failed to get quote: {e}")
        return
    
    # Step 5: Execute swap (optional)
    print("\nSTEP 5: Execute Test SELL")
    print("-" * 40)
    print(f"\n⚠️  This will swap {quote_amount_for_test:.2f} {QUOTE_TOKEN} for ~{out_amount:.6f} {BASE_TOKEN}")
    print(f"    From wallet: {address}")
    
    confirm = input("\nExecute swap? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nSwap cancelled. Test complete.")
        print("\nSummary:")
        print(f"  ✓ Wallet loaded: {address}")
        print(f"  ✓ {BASE_TOKEN} balance: {base_balance:.6f}")
        print(f"  ✓ {QUOTE_TOKEN} balance: {quote_balance:.2f}")
        print(f"  ✓ {QUOTE_TOKEN} for swap: {quote_amount_for_test:.2f}")
        print(f"  ✓ Quote API: Working")
        print(f"  - Swap execution: Skipped")
        return
    
    print("\nExecuting swap...")
    try:
        import base64
        from solders.transaction import VersionedTransaction
        
        # Get swap transaction from Jupiter
        swap_tx_b64 = jupiter.get_swap_transaction(quote, address)
        if not swap_tx_b64:
            print("❌ Failed to get swap transaction")
            return
        
        print("  Got swap transaction from Jupiter")
        
        # Sign the transaction using LocalWallet (same as live program)
        tx_bytes = base64.b64decode(swap_tx_b64)
        signed_tx = wallet.sign_transaction(tx_bytes)
        
        if not signed_tx:
            print("❌ Failed to sign transaction")
            return
        
        print("  Transaction signed")
        
        # Send transaction (same params as live program)
        signed_tx_b64 = base64.b64encode(signed_tx).decode('utf-8')
        
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_tx_b64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 3,
                }
            ]
        }, timeout=30)
        
        result = resp.json()
        if "error" in result:
            print(f"❌ RPC error: {result['error']}")
            return
        
        tx_hash = result.get("result", "")
        
        print(f"\n✓ SELL swap submitted!")
        print(f"  Transaction: {tx_hash}")
        print(f"  Explorer: https://solscan.io/tx/{tx_hash}")
        
    except Exception as e:
        print(f"\n❌ Swap error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 6: Confirm transaction on-chain
    print("\nSTEP 6: Confirm Transaction")
    print("-" * 40)
    
    confirmation = confirm_transaction(tx_hash, timeout_seconds=30)
    
    if confirmation and confirmation.get("status") == "confirmed":
        print(f"  ✓ Transaction CONFIRMED (slot: {confirmation.get('slot')})")
        print(f"  Fee: {confirmation.get('fee_sol', 0):.6f} SOL")
        
        # Show actual balance changes from the transaction
        token_changes = confirmation.get("token_changes", {})
        sol_change = confirmation.get("sol_change", 0)
        
        print(f"\n  Actual changes from transaction:")
        print(f"    SOL: {sol_change:+.6f}")
        for mint, change_info in token_changes.items():
            change = change_info.get("change", 0)
            # Try to identify the token
            if mint == QUOTE_MINT:
                print(f"    {QUOTE_TOKEN}: {change:+.6f}")
            elif mint == BASE_MINT:
                print(f"    {BASE_TOKEN}: {change:+.6f}")
            else:
                print(f"    {mint[:8]}...: {change:+.6f}")
    elif confirmation and confirmation.get("status") == "failed":
        print(f"  ❌ Transaction FAILED: {confirmation.get('error')}")
    else:
        print(f"  ⚠️  Could not confirm transaction within timeout")
        print(f"      Check explorer: https://solscan.io/tx/{tx_hash}")
    
    # Step 7: Show wallet balances (with stale warning)
    print("\nSTEP 7: Current Wallet Balances")
    print("-" * 40)
    print("⚠️  NOTE: RPC balance queries can be stale for 5+ minutes.")
    print("    The transaction confirmation above is the reliable source.")
    
    try:
        # Get SOL balance via RPC
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }, timeout=10)
        data = resp.json()
        new_sol = data.get("result", {}).get("value", 0) / 1e9
        
        # Get quote token balance
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": QUOTE_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=10)
        data = resp.json()
        accounts = data.get("result", {}).get("value", [])
        if accounts:
            new_quote = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
        else:
            new_quote = 0
        
        if BASE_TOKEN == "SOL":
            print(f"  {BASE_TOKEN}: {new_sol:.6f} (was {base_balance:.6f})")
        else:
            print(f"  SOL: {new_sol:.6f} (was {sol_balance:.6f})")
        print(f"  {QUOTE_TOKEN}: {new_quote:.4f} (was {quote_balance:.4f})")
    except Exception as e:
        print(f"Could not fetch balances: {e}")
    
    # Log test trade for tax purposes (only if confirmed)
    if confirmation and confirmation.get("status") == "confirmed":
        log_test_trade({
            'id': f"test_sell_{tx_hash[:8]}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': 'SELL',
            'pair': f"{BASE_TOKEN}/{QUOTE_TOKEN}",
            'input_token': QUOTE_TOKEN,
            'output_token': BASE_TOKEN,
            'input_amount': quote_amount_for_test,
            'output_amount': out_amount,
            'price_usd': quote_price,
            'transaction': {
                'signature': tx_hash,
                'status': 'confirmed',
                'slot': confirmation.get('slot'),
                'fee_sol': confirmation.get('fee_sol', 0),
            },
        })
    
    # Validate LiveTrade dataclass (catches field mismatches with live program)
    validate_live_trade_dataclass(
        action="SELL",
        signature=tx_hash,
        input_token=QUOTE_TOKEN,
        output_token=BASE_TOKEN,
        input_amount=quote_amount_for_test,
        output_amount=out_amount,
        amount=quote_amount_for_test,  # Tokens sold
        position_size_usd=TEST_AMOUNT_USD,
        price_usd=quote_price,
    )
    
    print("\n" + "=" * 60)
    print("SELL TEST COMPLETE")
    print("=" * 60)


def validate_livetrade_only():
    """
    Dry-run validation of LiveTrade dataclass without executing any swap.
    
    This catches field mismatches between test program and live trading code
    without risking any funds.
    """
    print("=" * 60)
    print("     LIVETRADE DATACLASS VALIDATION (DRY RUN)")
    print("=" * 60)
    print("\nThis validates the LiveTrade dataclass matches what the live")
    print("trading program expects, without executing any real swaps.\n")
    
    # Test BUY scenario
    print("Testing BUY scenario...")
    buy_ok = validate_live_trade_dataclass(
        action="BUY",
        signature="DRY_RUN_TEST_SIGNATURE_1234567890",
        input_token="USDC",
        output_token="TEST",
        input_amount=10.0,
        output_amount=100.0,
        amount=100.0,  # Tokens received
        position_size_usd=10.0,
        price_usd=0.10,
    )
    
    # Test SELL scenario
    print("\nTesting SELL scenario...")
    sell_ok = validate_live_trade_dataclass(
        action="SELL",
        signature="DRY_RUN_TEST_SIGNATURE_0987654321",
        input_token="TEST",
        output_token="USDC",
        input_amount=100.0,
        output_amount=10.0,
        amount=100.0,  # Tokens sold
        position_size_usd=10.0,
        price_usd=0.10,
    )
    
    print("\n" + "=" * 60)
    if buy_ok and sell_ok:
        print("✓ ALL VALIDATION PASSED - Safe to run live trading")
    else:
        print("✗ VALIDATION FAILED - DO NOT run live trading until fixed")
    print("=" * 60 + "\n")
    
    return buy_ok and sell_ok


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test DEX swap integration")
    parser.add_argument('--pair', type=str, default='SOL/USDC',
                        help='Trading pair in BASE/QUOTE format (default: SOL/USDC)')
    parser.add_argument('--validate-only', action='store_true',
                        help='Only validate LiveTrade dataclass without executing swaps')
    return parser.parse_args()


def setup_pair_config(pair_str: str) -> bool:
    """Set up global pair config from pair string like 'SOL/USDC' or 'WTAO/USDC'.
    
    Returns True on success, False on failure.
    """
    global BASE_TOKEN, BASE_MINT, QUOTE_TOKEN, QUOTE_MINT, BASE_DECIMALS, QUOTE_DECIMALS
    
    try:
        from dex.token_cache import get_mint_with_fallback, get_well_known_decimals
        
        parts = pair_str.upper().split('/')
        if len(parts) != 2:
            print(f"❌ Invalid pair format: {pair_str}. Use BASE/QUOTE (e.g., SOL/USDC)")
            return False
        
        base, quote = parts
        
        # Look up mint addresses
        base_mint = get_mint_with_fallback(base)
        quote_mint = get_mint_with_fallback(quote)
        
        if not base_mint:
            print(f"❌ Unknown base token: {base}")
            return False
        if not quote_mint:
            print(f"❌ Unknown quote token: {quote}")
            return False
        
        # Get decimals
        base_decimals = get_well_known_decimals(base)
        quote_decimals = get_well_known_decimals(quote)
        
        if base_decimals is None:
            base_decimals = 9  # Default
        if quote_decimals is None:
            quote_decimals = 6  # Default for stablecoins
        
        # Set globals
        BASE_TOKEN = base
        BASE_MINT = base_mint
        QUOTE_TOKEN = quote
        QUOTE_MINT = quote_mint
        BASE_DECIMALS = base_decimals
        QUOTE_DECIMALS = quote_decimals
        
        print(f"[CONFIG] Pair: {BASE_TOKEN}/{QUOTE_TOKEN}")
        print(f"[CONFIG] Base mint: {BASE_MINT[:8]}...{BASE_MINT[-4:]}")
        print(f"[CONFIG] Quote mint: {QUOTE_MINT[:8]}...{QUOTE_MINT[-4:]}")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import token_cache: {e}")
        return False


def main():
    # Parse command line args
    args = parse_args()
    
    # If --validate-only, just run LiveTrade validation without any swaps
    if args.validate_only:
        validate_livetrade_only()
        return
    
    # Set up pair config
    if not setup_pair_config(args.pair):
        return
    
    print()  # Blank line after config
    
    print("Choose test:")
    print(f"  1. BUY test ({BASE_TOKEN} → {QUOTE_TOKEN})")
    print(f"  2. SELL test ({QUOTE_TOKEN} → {BASE_TOKEN})")
    print(f"  3. Validate LiveTrade only (no swap)")
    choice = input("\nChoice (1/2/3): ").strip()
    
    if choice == "2":
        test_sell_with_private_key()
    elif choice == "3":
        validate_livetrade_only()
    else:
        test_with_private_key()


if __name__ == "__main__":
    main()
