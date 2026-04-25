"""
WalletConnect Integration - Session management for Phantom wallet connection.

Features:
- WalletConnect v2 session creation
- Phantom deep link generation
- Transaction signing requests
- Session persistence (optional)
"""

import asyncio
import json
import os
import time
from typing import Callable, Dict, Optional

# WalletConnect configuration
WC_PROJECT_ID_ENV = "WALLETCONNECT_PROJECT_ID"
DEFAULT_APPROVAL_TIMEOUT = 300  # 5 minutes

# Session storage
SESSION_DIR = os.environ.get('DEX_CACHE_DIR', './dex_cache/')
SESSION_FILE = os.path.join(SESSION_DIR, 'wc_session.json')


class WalletConnectSession:
    """Manages WalletConnect v2 session with Phantom wallet."""
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        approval_timeout: int = DEFAULT_APPROVAL_TIMEOUT,
        persist_session: bool = False
    ):
        """Initialize WalletConnect session manager.
        
        Args:
            project_id: WalletConnect Cloud project ID.
                       Falls back to WALLETCONNECT_PROJECT_ID env var.
            approval_timeout: Timeout in seconds for user approval.
            persist_session: If True, save session to file for reuse.
        """
        self.project_id = project_id or os.environ.get(WC_PROJECT_ID_ENV)
        self.approval_timeout = approval_timeout
        self.persist_session = persist_session
        
        self.wc_client = None
        self.session = None
        self.connected_address = None
        self._pairing_uri = None
        
        if not self.project_id:
            print("[WC] Warning: No WalletConnect project ID configured")
            print(f"[WC] Set {WC_PROJECT_ID_ENV} env var or pass project_id")
    
    def _ensure_session_dir(self):
        """Create session directory if needed."""
        os.makedirs(SESSION_DIR, exist_ok=True)
    
    def _load_session(self) -> Optional[Dict]:
        """Load saved session from file.
        
        Returns:
            Session data dictionary or None.
        """
        if not self.persist_session:
            return None
        
        if not os.path.exists(SESSION_FILE):
            return None
        
        try:
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def _save_session(self, session_data: Dict):
        """Save session to file.
        
        Args:
            session_data: Session data to persist.
        """
        if not self.persist_session:
            return
        
        self._ensure_session_dir()
        
        try:
            with open(SESSION_FILE, 'w') as f:
                json.dump(session_data, f, indent=2)
            print(f"[WC] Session saved to {SESSION_FILE}")
        except IOError as e:
            print(f"[WC] Warning: Could not save session: {e}")
    
    def _clear_session(self):
        """Clear saved session file."""
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
            print("[WC] Session file cleared")
    
    async def connect(self) -> Optional[str]:
        """Initialize WalletConnect and wait for Phantom connection.
        
        This creates a new pairing and waits for the user to connect
        their Phantom wallet by scanning the QR code or clicking the link.
        
        Returns:
            Connected wallet address or None on timeout/error.
        """
        if not self.project_id:
            print("[WC] Error: WalletConnect project ID required")
            print(f"[WC] Get one free at https://cloud.walletconnect.com")
            return None
        
        try:
            from pywalletconnect import WCClient, WCClientInvalidOption
        except ImportError:
            print("[WC] Error: pywalletconnect not installed")
            print("[WC] Run: pip install pywalletconnect")
            return None
        
        print("\n" + "=" * 50)
        print("CONNECT PHANTOM WALLET")
        print("=" * 50)
        
        try:
            # Create WalletConnect client
            self.wc_client = WCClient(
                project_id=self.project_id,
                metadata={
                    "name": "Trading Bot",
                    "description": "LLM-powered Solana meme coin trader",
                    "url": "https://localhost",
                    "icons": []
                }
            )
            
            # Create pairing URI for Solana
            self._pairing_uri = await self.wc_client.create_pairing(
                chains=["solana:mainnet"]
            )
            
            # Display connection options
            print(f"\nWalletConnect URI:")
            print(f"{self._pairing_uri}")
            print(f"\nPhantom Deep Link:")
            print(f"phantom://wc?uri={self._pairing_uri}")
            print(f"\nWaiting for connection (timeout: {self.approval_timeout}s)...")
            
            # Wait for user to connect
            start_time = time.time()
            while time.time() - start_time < self.approval_timeout:
                session = await self.wc_client.get_session()
                if session:
                    self.session = session
                    accounts = session.get("namespaces", {}).get("solana", {}).get("accounts", [])
                    if accounts:
                        # Format: solana:mainnet:ADDRESS
                        self.connected_address = accounts[0].split(":")[-1]
                        print(f"\n✓ Connected: {self.connected_address}")
                        
                        if self.persist_session:
                            self._save_session({
                                "address": self.connected_address,
                                "session": session,
                                "connected_at": time.time()
                            })
                        
                        return self.connected_address
                
                await asyncio.sleep(1)
            
            print("\n✗ Connection timed out")
            return None
            
        except Exception as e:
            print(f"\n✗ Connection error: {e}")
            return None
    
    async def sign_transaction(self, transaction_base64: str) -> Optional[str]:
        """Request transaction signature from Phantom.
        
        Args:
            transaction_base64: Base64-encoded Solana transaction.
        
        Returns:
            Transaction signature or None on rejection/error.
        """
        if not self.session or not self.connected_address:
            print("[WC] Error: Not connected to wallet")
            return None
        
        print("\n>>> Check your Phantom wallet for approval request <<<")
        
        try:
            # Send sign request via WalletConnect
            result = await self.wc_client.request(
                chain_id="solana:mainnet",
                request={
                    "method": "solana_signTransaction",
                    "params": {
                        "transaction": transaction_base64
                    }
                }
            )
            
            if result and "signature" in result:
                signature = result["signature"]
                print(f"✓ Transaction signed")
                return signature
            else:
                print("✗ No signature returned")
                return None
                
        except Exception as e:
            error_str = str(e).lower()
            if "rejected" in error_str or "denied" in error_str:
                print("✗ User rejected transaction in Phantom")
            else:
                print(f"✗ Signing error: {e}")
            return None
    
    async def sign_and_send_transaction(self, transaction_base64: str) -> Optional[str]:
        """Request transaction signature and send via Phantom.
        
        Args:
            transaction_base64: Base64-encoded Solana transaction.
        
        Returns:
            Transaction signature (tx hash) or None on rejection/error.
        """
        if not self.session or not self.connected_address:
            print("[WC] Error: Not connected to wallet")
            return None
        
        print("\n>>> Check your Phantom wallet for approval request <<<")
        
        try:
            # Send sign and send request via WalletConnect
            result = await self.wc_client.request(
                chain_id="solana:mainnet",
                request={
                    "method": "solana_signAndSendTransaction",
                    "params": {
                        "transaction": transaction_base64
                    }
                }
            )
            
            if result and "signature" in result:
                signature = result["signature"]
                print(f"✓ Transaction confirmed: {signature}")
                print(f"  https://solscan.io/tx/{signature}")
                return signature
            else:
                print("✗ No signature returned")
                return None
                
        except Exception as e:
            error_str = str(e).lower()
            if "rejected" in error_str or "denied" in error_str:
                print("✗ User rejected transaction in Phantom")
            else:
                print(f"✗ Transaction error: {e}")
            return None
    
    async def disconnect(self):
        """Disconnect from wallet and clean up session."""
        if self.wc_client:
            try:
                await self.wc_client.disconnect()
                print("[WC] Disconnected from wallet")
            except Exception as e:
                print(f"[WC] Disconnect error: {e}")
        
        self.session = None
        self.connected_address = None
        self._clear_session()
    
    def is_connected(self) -> bool:
        """Check if wallet is connected.
        
        Returns:
            True if connected to a wallet.
        """
        return self.connected_address is not None
    
    def get_address(self) -> Optional[str]:
        """Get connected wallet address.
        
        Returns:
            Wallet address or None if not connected.
        """
        return self.connected_address


def generate_phantom_deeplink(wc_uri: str) -> str:
    """Generate a Phantom deep link for WalletConnect URI.
    
    Args:
        wc_uri: WalletConnect pairing URI.
    
    Returns:
        Phantom deep link URL.
    """
    from urllib.parse import quote
    return f"phantom://wc?uri={quote(wc_uri)}"


def run_async(coro):
    """Run an async coroutine synchronously.
    
    Args:
        coro: Coroutine to run.
    
    Returns:
        Result of the coroutine.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)
