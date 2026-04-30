#!/usr/bin/env python3
"""
JLP Virtual Price Lab - Standalone Testing Program

This lab evaluates different approaches for fetching the true virtual (NAV) price
of JLP tokens from on-chain data. It tests:

1. Direct Solana RPC + manual binary parsing
2. Python anchorpy library (if available)
3. Subprocess wrapper around TypeScript reference implementation

Run this independently from the main bot to validate approaches before integration.

Usage:
    python lab/jlp_virtual_price_lab.py --method=rpc
    python lab/jlp_virtual_price_lab.py --method=anchorpy
    python lab/jlp_virtual_price_lab.py --method=typescript
    python lab/jlp_virtual_price_lab.py --all

Requirements:
    - httpx (for RPC calls)
    - anchorpy (optional, for method 2)
    - Node.js + npm (optional, for method 3)
"""

import argparse
import base64
import json
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

import httpx

# =============================================================================
# CONSTANTS
# =============================================================================

# JLP Pool and Token addresses
JLP_POOL_ACCOUNT = "5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq"
JLP_TOKEN_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"
PERPETUALS_PROGRAM = "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu"

# Default Solana RPC
DEFAULT_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# TypeScript reference implementation
TS_REPO_URL = "https://github.com/julianfssen/jupiter-perps-anchor-idl-parsing"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class LabResult:
    """Result from a lab test method."""
    method: str
    success: bool
    virtual_price: Optional[float] = None
    aum_usd: Optional[float] = None
    jlp_supply: Optional[float] = None
    latency_ms: float = 0
    error: Optional[str] = None
    raw_data: Optional[Dict] = None
    
    def __str__(self):
        if self.success:
            lines = [f"[{self.method}] SUCCESS"]
            if self.virtual_price is not None:
                lines.append(f"  Virtual Price: ${self.virtual_price:.6f}")
            if self.aum_usd is not None:
                lines.append(f"  AUM (USD):     ${self.aum_usd:,.2f}")
            if self.jlp_supply is not None:
                lines.append(f"  JLP Supply:    {self.jlp_supply:,.2f}")
            lines.append(f"  Latency:       {self.latency_ms:.0f}ms")
            if self.raw_data:
                lines.append(f"  Extra data:    {self.raw_data}")
            return "\n".join(lines)
        else:
            return f"[{self.method}] FAILED: {self.error}"


# =============================================================================
# METHOD 1: Direct Solana RPC + Manual Parsing
# =============================================================================

class SoldersRPCMethod:
    """
    Fetch JLP data using solders + httpx for RPC calls.
    
    Pool struct layout (from Jupiter docs):
    - 8 bytes: Anchor discriminator
    - 4 bytes + N bytes: name (string with length prefix)
    - 4 bytes + N*32 bytes: custodies (Vec<PublicKey>)
    - 16 bytes: aumUsd (u128)
    - ... more fields (limit, fees, poolApr)
    
    We parse the struct step by step to find aumUsd.
    """
    
    def __init__(self, rpc_url: str = DEFAULT_RPC_URL):
        self.rpc_url = rpc_url
    
    def fetch_account_data(self, address: str) -> Optional[bytes]:
        """Fetch raw account data from Solana RPC."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getAccountInfo",
                        "params": [
                            address,
                            {"encoding": "base64"}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json().get("result", {})
                    value = result.get("value")
                    
                    if value and value.get("data"):
                        data_b64 = value["data"][0]
                        return base64.b64decode(data_b64)
                        
        except Exception as e:
            print(f"  [RPC] Error fetching {address}: {e}")
        
        return None
    
    def fetch_token_supply(self, mint: str) -> Optional[float]:
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
            print(f"  [RPC] Error fetching supply for {mint}: {e}")
        
        return None
    
    def parse_pool_struct(self, data: bytes) -> dict:
        """
        Parse the Pool account struct to extract aumUsd.
        
        Layout:
        - 8 bytes: Anchor discriminator
        - 4 bytes: name string length (u32)
        - N bytes: name string
        - 4 bytes: custodies vec length (u32)
        - N*32 bytes: custody pubkeys
        - 16 bytes: aumUsd (u128)
        """
        result = {
            "discriminator": None,
            "name": None,
            "num_custodies": None,
            "aum_usd_raw": None,
            "aum_usd": None,
            "aum_offset": None,
        }
        
        offset = 0
        
        # 1. Discriminator (8 bytes)
        if len(data) < 8:
            return result
        result["discriminator"] = data[0:8].hex()
        offset = 8
        
        # 2. Name string (4 byte length + string)
        if len(data) < offset + 4:
            return result
        name_len = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        
        if len(data) < offset + name_len:
            return result
        result["name"] = data[offset:offset + name_len].decode('utf-8', errors='ignore')
        offset += name_len
        
        # 3. Custodies vec (4 byte length + pubkeys)
        if len(data) < offset + 4:
            return result
        num_custodies = struct.unpack_from('<I', data, offset)[0]
        result["num_custodies"] = num_custodies
        offset += 4
        
        # Skip custody pubkeys (32 bytes each)
        custody_bytes = num_custodies * 32
        if len(data) < offset + custody_bytes:
            return result
        offset += custody_bytes
        
        # 4. aumUsd (u128 = 16 bytes)
        result["aum_offset"] = offset
        if len(data) < offset + 16:
            return result
        
        low = struct.unpack_from('<Q', data, offset)[0]
        high = struct.unpack_from('<Q', data, offset + 8)[0]
        aum_raw = low + (high << 64)
        result["aum_usd_raw"] = aum_raw
        
        # aumUsd uses 6 decimals (USDC decimals)
        result["aum_usd"] = aum_raw / 1_000_000
        
        return result
    
    def run(self) -> LabResult:
        """Execute the solders RPC method."""
        start = time.time()
        
        print("\n[METHOD 1: Solders + RPC Struct Parsing]")
        print("-" * 50)
        
        # Step 1: Fetch JLP token supply
        print("  Fetching JLP token supply...")
        jlp_supply = self.fetch_token_supply(JLP_TOKEN_MINT)
        
        if jlp_supply is None:
            return LabResult(
                method="Solders RPC",
                success=False,
                error="Failed to fetch JLP token supply",
                latency_ms=(time.time() - start) * 1000
            )
        
        print(f"  JLP Supply: {jlp_supply:,.2f}")
        
        # Step 2: Fetch Pool account data
        print("  Fetching Pool account data...")
        pool_data = self.fetch_account_data(JLP_POOL_ACCOUNT)
        
        if pool_data is None:
            return LabResult(
                method="Solders RPC",
                success=False,
                error="Failed to fetch Pool account data",
                latency_ms=(time.time() - start) * 1000
            )
        
        print(f"  Pool account size: {len(pool_data)} bytes")
        
        # Step 3: Parse Pool struct
        print("  Parsing Pool struct...")
        parsed = self.parse_pool_struct(pool_data)
        
        print(f"  Discriminator: {parsed.get('discriminator', 'N/A')}")
        print(f"  Pool name: {parsed.get('name', 'N/A')}")
        print(f"  Num custodies: {parsed.get('num_custodies', 'N/A')}")
        print(f"  AUM offset: {parsed.get('aum_offset', 'N/A')}")
        
        aum_usd = parsed.get("aum_usd")
        
        if aum_usd is None or aum_usd <= 0:
            return LabResult(
                method="Solders RPC",
                success=False,
                error="Could not parse aumUsd from Pool struct",
                latency_ms=(time.time() - start) * 1000,
                raw_data=parsed
            )
        
        print(f"  AUM (USD): ${aum_usd:,.2f}")
        
        # Step 4: Calculate virtual price
        virtual_price = aum_usd / jlp_supply
        
        print(f"  Virtual Price: ${virtual_price:.6f}")
        
        return LabResult(
            method="Solders RPC",
            success=True,
            virtual_price=virtual_price,
            aum_usd=aum_usd,
            jlp_supply=jlp_supply,
            latency_ms=(time.time() - start) * 1000,
            raw_data={"aum_offset": parsed.get("aum_offset"), "pool_name": parsed.get("name")}
        )


# =============================================================================
# METHOD 2: Python anchorpy Library
# =============================================================================

class AnchorpyMethod:
    """
    Fetch JLP data using the anchorpy library for IDL-based deserialization.
    
    This is the "proper" Python approach but requires:
    - anchorpy installed
    - Jupiter Perpetuals IDL available
    - Async handling
    """
    
    def __init__(self, rpc_url: str = DEFAULT_RPC_URL):
        self.rpc_url = rpc_url
    
    def check_dependencies(self) -> Tuple[bool, str]:
        """Check if anchorpy is installed and usable."""
        try:
            import anchorpy
            return True, f"anchorpy {anchorpy.__version__}"
        except ImportError:
            return False, "anchorpy not installed (pip install anchorpy)"
        except Exception as e:
            return False, f"anchorpy import error: {e}"
    
    def run(self) -> LabResult:
        """Execute the anchorpy method."""
        start = time.time()
        
        print("\n[METHOD 2: Python anchorpy]")
        print("-" * 50)
        
        # Check dependencies
        available, msg = self.check_dependencies()
        print(f"  Dependency check: {msg}")
        
        if not available:
            return LabResult(
                method="anchorpy",
                success=False,
                error=msg,
                latency_ms=(time.time() - start) * 1000
            )
        
        # Attempt to use anchorpy
        try:
            from anchorpy import Program, Provider, Idl
            from solders.pubkey import Pubkey
            from solana.rpc.async_api import AsyncClient
            import asyncio
            
            async def fetch_with_anchorpy():
                print("  Connecting to Solana RPC...")
                client = AsyncClient(self.rpc_url)
                
                # Try to fetch the IDL from on-chain
                print("  Fetching IDL from on-chain...")
                program_id = Pubkey.from_string(PERPETUALS_PROGRAM)
                
                try:
                    idl = await Program.fetch_idl(program_id, provider=Provider.local())
                    print(f"  IDL fetched: {len(idl.accounts)} accounts defined")
                except Exception as e:
                    print(f"  IDL fetch failed: {e}")
                    print("  NOTE: IDL may not be stored on-chain. Need to load from file.")
                    raise Exception("IDL not available on-chain - need local IDL file")
                
                # If we got here, we have the IDL
                # Create program instance and fetch Pool account
                # ... (implementation would continue here)
                
                await client.close()
                return None, None, None
            
            # Run the async function
            aum_usd, jlp_supply, virtual_price = asyncio.run(fetch_with_anchorpy())
            
            if virtual_price is None:
                return LabResult(
                    method="anchorpy",
                    success=False,
                    error="Could not fetch data via anchorpy",
                    latency_ms=(time.time() - start) * 1000
                )
            
            return LabResult(
                method="anchorpy",
                success=True,
                virtual_price=virtual_price,
                aum_usd=aum_usd,
                jlp_supply=jlp_supply,
                latency_ms=(time.time() - start) * 1000
            )
            
        except Exception as e:
            return LabResult(
                method="anchorpy",
                success=False,
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )


# =============================================================================
# METHOD 3: TypeScript Subprocess Wrapper
# =============================================================================

class TypeScriptMethod:
    """
    Fetch JLP data by wrapping the TypeScript reference implementation.
    
    This approach:
    - Uses the official Jupiter examples (known to work)
    - Runs TypeScript via subprocess
    - Requires Node.js + npm installed
    """
    
    TS_DIR = "lab/ts-jlp-price"
    
    def __init__(self, rpc_url: str = DEFAULT_RPC_URL):
        self.rpc_url = rpc_url
    
    def check_nodejs(self) -> Tuple[bool, str]:
        """Check if Node.js is available."""
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, f"Node.js {result.stdout.strip()}"
            return False, "Node.js not working"
        except FileNotFoundError:
            return False, "Node.js not installed"
        except Exception as e:
            return False, f"Node.js check error: {e}"
    
    def setup_ts_project(self) -> bool:
        """Set up the TypeScript project for fetching JLP price."""
        ts_dir = self.TS_DIR
        
        # Create directory
        os.makedirs(ts_dir, exist_ok=True)
        
        # Create package.json
        package_json = {
            "name": "jlp-price-fetcher",
            "version": "1.0.0",
            "type": "module",
            "scripts": {
                "fetch": "npx ts-node --esm fetch-jlp-price.ts"
            },
            "dependencies": {
                "@coral-xyz/anchor": "^0.29.0",
                "@solana/web3.js": "^1.87.0",
                "typescript": "^5.0.0",
                "ts-node": "^10.9.0"
            }
        }
        
        with open(f"{ts_dir}/package.json", "w") as f:
            json.dump(package_json, f, indent=2)
        
        # Create the TypeScript fetcher script
        ts_script = '''
import { Connection, PublicKey } from "@solana/web3.js";

const JLP_POOL = "5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq";
const JLP_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4";

async function main() {
    const rpcUrl = process.env.SOLANA_RPC_URL || "https://api.mainnet-beta.solana.com";
    const connection = new Connection(rpcUrl);
    
    // Fetch JLP token supply
    const mintPubkey = new PublicKey(JLP_MINT);
    const supplyInfo = await connection.getTokenSupply(mintPubkey);
    const jlpSupply = parseFloat(supplyInfo.value.uiAmountString || "0");
    
    // Fetch Pool account
    const poolPubkey = new PublicKey(JLP_POOL);
    const poolAccount = await connection.getAccountInfo(poolPubkey);
    
    if (!poolAccount) {
        console.error("Failed to fetch Pool account");
        process.exit(1);
    }
    
    // NOTE: Full implementation would use Jupiter Perpetuals IDL to decode
    // For now, output what we have
    console.log(JSON.stringify({
        jlpSupply,
        poolDataSize: poolAccount.data.length,
        note: "Full IDL parsing not implemented in this minimal example"
    }));
}

main().catch(console.error);
'''
        
        with open(f"{ts_dir}/fetch-jlp-price.ts", "w") as f:
            f.write(ts_script)
        
        return True
    
    def run(self) -> LabResult:
        """Execute the TypeScript subprocess method."""
        start = time.time()
        
        print("\n[METHOD 3: TypeScript Subprocess]")
        print("-" * 50)
        
        # Check Node.js
        available, msg = self.check_nodejs()
        print(f"  Node.js check: {msg}")
        
        if not available:
            return LabResult(
                method="TypeScript",
                success=False,
                error=msg,
                latency_ms=(time.time() - start) * 1000
            )
        
        # Set up TypeScript project
        print("  Setting up TypeScript project...")
        self.setup_ts_project()
        
        # Note: We don't actually run npm install here as it would be slow
        # This is a demonstration of the approach
        
        print(f"  TypeScript project created at: {self.TS_DIR}/")
        print("  To complete setup, run:")
        print(f"    cd {self.TS_DIR} && npm install && npm run fetch")
        print("")
        print("  NOTE: This lab creates the scaffolding. Full implementation")
        print("  would require the Jupiter Perpetuals IDL for proper decoding.")
        
        return LabResult(
            method="TypeScript",
            success=False,
            error="TypeScript scaffolding created - manual setup required",
            latency_ms=(time.time() - start) * 1000,
            raw_data={
                "ts_dir": self.TS_DIR,
                "next_steps": [
                    f"cd {self.TS_DIR}",
                    "npm install",
                    "# Add Jupiter Perpetuals IDL",
                    "npm run fetch"
                ]
            }
        )


# =============================================================================
# COMPARISON: Current MVP Method (Buy/Sell Spread)
# =============================================================================

class MVPSpreadMethod:
    """
    For comparison: the current MVP buy/sell spread approach.
    This shows what the bot currently uses.
    """
    
    def __init__(self):
        pass
    
    def run(self) -> LabResult:
        """Execute the MVP spread method for comparison."""
        start = time.time()
        
        print("\n[COMPARISON: MVP Buy/Sell Spread Method]")
        print("-" * 50)
        
        try:
            # Import from the main bot
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from lp_arbitrage import JLPPriceFetcher
            
            fetcher = JLPPriceFetcher()
            buy_price, sell_price = fetcher.get_prices()
            
            if buy_price and sell_price:
                spread = (sell_price - buy_price) / buy_price * 100
                
                print(f"  Buy Price:  ${buy_price:.4f}")
                print(f"  Sell Price: ${sell_price:.4f}")
                print(f"  Spread:     {spread:+.4f}%")
                
                return LabResult(
                    method="MVP Spread",
                    success=True,
                    virtual_price=buy_price,  # Using buy price as "virtual" proxy
                    aum_usd=None,
                    jlp_supply=None,
                    latency_ms=(time.time() - start) * 1000,
                    raw_data={
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                        "spread_pct": spread
                    }
                )
            else:
                return LabResult(
                    method="MVP Spread",
                    success=False,
                    error="Could not fetch prices",
                    latency_ms=(time.time() - start) * 1000
                )
                
        except ImportError as e:
            return LabResult(
                method="MVP Spread",
                success=False,
                error=f"Could not import from lp_arbitrage: {e}",
                latency_ms=(time.time() - start) * 1000
            )


# =============================================================================
# MAIN LAB RUNNER
# =============================================================================

def print_banner():
    print("=" * 60)
    print("  JLP Virtual Price Lab")
    print("  Testing On-Chain Data Fetching Approaches")
    print("=" * 60)
    print(f"  RPC URL: {DEFAULT_RPC_URL[:50]}...")
    print(f"  JLP Pool: {JLP_POOL_ACCOUNT}")
    print(f"  JLP Mint: {JLP_TOKEN_MINT}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="JLP Virtual Price Lab")
    parser.add_argument("--method", choices=["rpc", "anchorpy", "typescript", "mvp", "all"],
                        default="all", help="Method to test")
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL, help="Solana RPC URL")
    args = parser.parse_args()
    
    print_banner()
    
    results = []
    
    if args.method in ["rpc", "all"]:
        method = SoldersRPCMethod(args.rpc_url)
        results.append(method.run())
    
    if args.method in ["anchorpy", "all"]:
        method = AnchorpyMethod(args.rpc_url)
        results.append(method.run())
    
    if args.method in ["typescript", "all"]:
        method = TypeScriptMethod(args.rpc_url)
        results.append(method.run())
    
    if args.method in ["mvp", "all"]:
        method = MVPSpreadMethod()
        results.append(method.run())
    
    # Print summary
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    
    for result in results:
        print(f"\n{result}")
    
    # Recommendations
    print("\n" + "=" * 60)
    print("  RECOMMENDATIONS")
    print("=" * 60)
    
    successful = [r for r in results if r.success]
    
    if not successful:
        print("""
  No methods succeeded in fetching true virtual price.
  
  Next steps:
  1. The Direct RPC method shows the Pool account structure
     but needs the correct offset for aumUsd field
  
  2. For anchorpy: Install dependencies and obtain IDL file
     pip install anchorpy solana solders
     
  3. For TypeScript: Clone the reference implementation
     git clone https://github.com/julianfssen/jupiter-perps-anchor-idl-parsing
     
  4. Alternative: Use the MVP buy/sell spread method which
     works but measures DEX spread, not true NAV
""")
    else:
        print(f"\n  {len(successful)} method(s) succeeded.")
        for r in successful:
            if r.virtual_price:
                print(f"  - {r.method}: ${r.virtual_price:.4f}")


if __name__ == "__main__":
    main()
