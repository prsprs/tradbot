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
    python test_trustwallet_swap.py
"""

import sys
import os
import getpass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dex.trustwallet import TrustWalletTrader, check_twak_installation
from dex.local_wallet import LocalWallet
from dex.jupiterutil import JupiterClient


# Test parameters
TEST_AMOUNT_USD = 1.0  # $1 test swap
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"


def test_with_private_key():
    """Test using direct private key input."""
    print("=" * 60)
    print("     DEX SWAP TEST (Direct Private Key)")
    print("=" * 60)
    print(f"\nThis test will verify wallet and Jupiter integration")
    print(f"and optionally execute a ~${TEST_AMOUNT_USD:.2f} SOL → USDC swap.\n")
    
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
    
    # Get SOL balance via RPC
    try:
        import requests
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
    
    # Get USDC balance via RPC (token account)
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": USDC_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=10)
        data = resp.json()
        accounts = data.get("result", {}).get("value", [])
        if accounts:
            usdc_balance = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
        else:
            usdc_balance = 0
        print(f"  USDC: {usdc_balance:.2f}")
    except Exception as e:
        print(f"  USDC: (error: {e})")
        usdc_balance = 0
    
    # Calculate SOL amount for ~$1 swap (using rough price estimate)
    sol_price_usd = 92.0  # Approximate SOL price
    sol_amount_for_test = TEST_AMOUNT_USD / sol_price_usd
    sol_lamports = int(sol_amount_for_test * 1e9)  # Convert to lamports
    
    if sol_balance < sol_amount_for_test:
        print(f"\n⚠️  Insufficient SOL for test swap (need ~{sol_amount_for_test:.6f} SOL)")
    
    # Step 4: Get swap quote
    print("\nSTEP 4: Get Swap Quote")
    print("-" * 40)
    
    try:
        quote = jupiter.get_quote(SOL_MINT, USDC_MINT, sol_lamports)
        if quote:
            out_amount = int(quote.get("outAmount", 0)) / 1e6  # USDC has 6 decimals
            price_impact = float(quote.get("priceImpactPct", 0))
            print(f"Quote: {sol_amount_for_test:.6f} SOL → {out_amount:.2f} USDC")
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
    print(f"\n⚠️  This will swap {sol_amount_for_test:.6f} SOL for ~{out_amount:.2f} USDC")
    print(f"    From wallet: {address}")
    
    confirm = input("\nExecute swap? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nSwap cancelled. Test complete.")
        print("\nSummary:")
        print(f"  ✓ Wallet loaded: {address}")
        print(f"  ✓ SOL balance: {sol_balance:.6f}")
        print(f"  ✓ USDC balance: {usdc_balance:.2f}")
        print(f"  ✓ SOL for swap: {sol_amount_for_test:.6f} (~${TEST_AMOUNT_USD:.2f})")
        print(f"  ✓ Quote API: Working")
        print(f"  - Swap execution: Skipped")
        return
    
    print("\nExecuting swap...")
    try:
        import base64
        import requests
        from solders.transaction import VersionedTransaction
        from solders.signature import Signature
        
        # Get swap transaction from Jupiter
        swap_tx_b64 = jupiter.get_swap_transaction(quote, address)
        if not swap_tx_b64:
            print("❌ Failed to get swap transaction")
            return
        
        print("  Got swap transaction from Jupiter")
        
        # Decode and sign the transaction
        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Sign with our keypair
        keypair = wallet.get_keypair()
        signed_tx = VersionedTransaction(tx.message, [keypair])
        signed_tx_bytes = bytes(signed_tx)
        signed_tx_b64 = base64.b64encode(signed_tx_bytes).decode('utf-8')
        
        print("  Transaction signed")
        
        # Send transaction
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_tx_b64,
                {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}
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
        print(f"  Swapped: {sol_amount_for_test:.6f} SOL → ~{out_amount:.2f} USDC")
        
    except Exception as e:
        print(f"\n❌ Swap error: {e}")
        return
    
    # Step 6: Verify balances
    print("\nSTEP 6: Verify Updated Balances")
    print("-" * 40)
    print("(Wait a few seconds for transaction to confirm)")
    
    import time
    time.sleep(5)
    
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
        
        # Get USDC balance via RPC
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"mint": USDC_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=10)
        data = resp.json()
        accounts = data.get("result", {}).get("value", [])
        if accounts:
            new_usdc = float(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"])
        else:
            new_usdc = 0
        
        print(f"  SOL: {new_sol:.6f} (was {sol_balance:.6f})")
        print(f"  USDC: {new_usdc:.2f} (was {usdc_balance:.2f})")
    except Exception as e:
        print(f"Could not verify balances: {e}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


def setup_twak_credentials():
    """Prompt for and configure Trust Wallet API credentials."""
    import subprocess
    
    # Hardcoded API access key
    DEFAULT_API_KEY = "b7f51d5e838633142969b1bdf336fdb3ba22d5a38220ba551654959ccfc96e08"
    
    print("STEP 0: Configure Trust Wallet API Credentials")
    print("-" * 40)
    print(f"Using API Access Key: {DEFAULT_API_KEY[:8]}...{DEFAULT_API_KEY[-8:]}")
    
    api_key = DEFAULT_API_KEY
    api_secret = getpass.getpass("API Secret (HMAC): ")
    
    if not api_key or not api_secret:
        print("❌ Both API key and secret are required")
        return False
    
    # Run twak init
    try:
        result = subprocess.run(
            ["twak", "init", "--api-key", api_key, "--api-secret", api_secret],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            print("✓ Trust Wallet credentials configured")
            return True
        else:
            print(f"❌ Failed to configure: {result.stderr or result.stdout}")
            return False
    except FileNotFoundError:
        print("❌ twak CLI not found. Install with: sudo npm install -g @trustwallet/cli")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_with_trust_wallet():
    """Test using Trust Wallet CLI."""
    print("=" * 60)
    print("     DEX SWAP TEST (Trust Wallet CLI)")
    print("=" * 60)
    print(f"\nThis test will verify Trust Wallet CLI integration")
    print(f"and optionally execute a ${TEST_AMOUNT_USD:.2f} USDC → SOL swap.\n")
    
    # Get password
    print("STEP 1: Wallet Authentication")
    print("-" * 40)
    
    password = os.environ.get("TWAK_WALLET_PASSWORD")
    if password:
        print("Using password from TWAK_WALLET_PASSWORD environment variable")
    else:
        print("Enter your Trust Wallet password")
        password = getpass.getpass("Password: ")
    
    if not password:
        print("\n❌ Password required")
        return
    
    trader = TrustWalletTrader(password=password)
    
    # Get address
    print("\nSTEP 2: Get Wallet Address")
    print("-" * 40)
    
    try:
        address = trader.get_address("solana")
        print(f"✓ Wallet address: {address}")
    except Exception as e:
        print(f"❌ Failed to get address: {e}")
        return
    
    # Get balances
    print("\nSTEP 3: Check Balances")
    print("-" * 40)
    
    try:
        balances = trader.get_balance("solana")
        if balances:
            for token, amount in balances.items():
                print(f"  {token}: {amount}")
        else:
            print("  (no balances returned)")
    except Exception as e:
        print(f"❌ Failed to get balances: {e}")
    
    # Get quote
    print("\nSTEP 4: Get Swap Quote")
    print("-" * 40)
    
    try:
        quote = trader.get_swap_quote("solana", "USDC", "SOL", TEST_AMOUNT_USD)
        print(f"Quote: {TEST_AMOUNT_USD} USDC → {quote.output_amount:.6f} SOL")
        print(f"Price impact: {quote.price_impact:.2%}")
    except Exception as e:
        print(f"❌ Failed to get quote: {e}")
        return
    
    # Execute swap
    print("\nSTEP 5: Execute Test Swap")
    print("-" * 40)
    print(f"\n⚠️  This will swap ${TEST_AMOUNT_USD:.2f} USDC for SOL")
    
    confirm = input("\nExecute swap? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("\nSwap cancelled.")
        return
    
    try:
        result = trader.execute_swap("solana", "USDC", "SOL", TEST_AMOUNT_USD)
        if result.success:
            print(f"\n✓ Swap successful!")
            print(f"  Transaction: {result.tx_hash}")
            print(f"  Explorer: https://solscan.io/tx/{result.tx_hash}")
        else:
            print(f"\n❌ Swap failed: {result.error}")
    except Exception as e:
        print(f"\n❌ Swap error: {e}")


def create_or_import_wallet():
    """Create a Trust Wallet (import not supported by twak CLI)."""
    import subprocess
    
    print("\nNo wallet found in TWAK.")
    print("\nNote: TWAK doesn't support importing recovery phrases.")
    print("Options:")
    print("  1. Create NEW wallet (you'll need to fund it)")
    print("  2. Skip - use direct private key mode instead")
    choice = input("\nChoice (1/2): ").strip()
    
    if choice == "2":
        print("\nRestart and choose option 2 (Direct private key)")
        return False
    
    print("\nSTEP: Create Trust Wallet")
    print("-" * 40)
    print("This will create a new encrypted HD wallet.")
    print("You'll set a password to protect it.\n")
    
    try:
        result = subprocess.run(
            ["twak", "wallet", "create"],
            timeout=120
        )
        if result.returncode == 0:
            print("\n✓ Wallet created successfully!")
            # Show the new address
            print("\nGetting your new Solana address...")
            addr_result = subprocess.run(
                ["twak", "wallet", "address", "--chain", "solana"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if addr_result.returncode == 0:
                print(f"Address: {addr_result.stdout.strip()}")
                print("\n⚠️  Fund this address with SOL + USDC before trading!")
            return True
        else:
            print("\n❌ Wallet creation failed")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def main():
    # Check if Trust Wallet CLI is available
    is_ready, message = check_twak_installation()
    
    print("Choose mode:")
    print("  1. Trust Wallet CLI (setup/configure)")
    print("  2. Direct private key")
    choice = input("\nChoice (1/2): ").strip()
    
    if choice == "1":
        if not is_ready:
            print(f"\n{message}\n")
            
            # Check if it's a missing wallet vs missing credentials
            if "no wallet exists" in message.lower():
                if not create_or_import_wallet():
                    return
            elif "not configured" in message.lower():
                if not setup_twak_credentials():
                    return
                # After configuring, check if wallet exists
                is_ready2, msg2 = check_twak_installation()
                if "no wallet exists" in msg2.lower():
                    if not create_or_import_wallet():
                        return
            else:
                # Generic setup
                if not setup_twak_credentials():
                    return
        test_with_trust_wallet()
    else:
        test_with_private_key()


if __name__ == "__main__":
    main()
