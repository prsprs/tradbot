"""
Local Wallet - Load Solana keypair via interactive prompt.

This provides a secure alternative to WalletConnect for DEX trading.
The private key is prompted at startup (only in DEX live mode) and
stored in memory only - never written to disk or environment.
"""

import base64
import getpass
import json
from typing import Optional


class LocalWallet:
    """Solana wallet using local keypair from interactive prompt."""
    
    def __init__(self, private_key: Optional[str] = None):
        """Initialize wallet from private key.
        
        Args:
            private_key: Base58-encoded private key, or None to skip loading.
        """
        self._keypair = None
        self._public_key = None
        
        if private_key:
            self._load_keypair(private_key)
    
    def _load_keypair(self, private_key: str):
        """Load keypair from base58-encoded private key.
        
        Args:
            private_key: Base58-encoded private key (64 bytes when decoded).
        """
        try:
            from solders.keypair import Keypair
            
            private_key = private_key.strip()
            key_len = len(private_key)
            print(f"[WALLET] Key length: {key_len} characters")
            
            # Try direct base58 string method first (most common: Phantom export)
            try:
                self._keypair = Keypair.from_base58_string(private_key)
                self._public_key = str(self._keypair.pubkey())
                addr = self._public_key
                print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                return
            except Exception as e:
                print(f"[WALLET] Base58 string method failed: {e}")
                # Try decoding and using from_bytes directly
                try:
                    import base58
                    decoded = base58.b58decode(private_key)
                    print(f"[WALLET] Decoded to {len(decoded)} bytes")
                    
                    if len(decoded) == 64:
                        print(f"[WALLET] Trying from_bytes (64-byte keypair)...")
                        self._keypair = Keypair.from_bytes(decoded)
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                    elif len(decoded) == 32:
                        print(f"[WALLET] Trying from_seed (32-byte secret)...")
                        self._keypair = Keypair.from_seed(decoded)
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                except Exception as e2:
                    if "signature error" in str(e2):
                        print(f"[WALLET] Invalid keypair - bytes are not a valid ed25519 key")
                        print(f"[WALLET] Please verify you exported the PRIVATE KEY from Phantom")
                        print(f"[WALLET] (Settings → Security & Privacy → Export Private Key)")
                    else:
                        print(f"[WALLET] Fallback decode failed: {e2}")
            
            # Try JSON array format (Solana CLI)
            if private_key.startswith('['):
                try:
                    key_array = json.loads(private_key)
                    if isinstance(key_array, list) and len(key_array) == 64:
                        self._keypair = Keypair.from_bytes(bytes(key_array))
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                except Exception as e:
                    print(f"[WALLET] JSON array method failed: {e}")
            
            print(f"[WALLET] Failed to decode private key")
                
        except ImportError:
            print("[WALLET] Error: solders not installed")
            print("[WALLET] Run: pip install solders")
        except Exception as e:
            print(f"[WALLET] Error loading keypair: {e}")
    
    def _decode_key(self, private_key: str) -> Optional[bytes]:
        """Decode private key from various formats.
        
        Supports:
        - Base58 encoded (Phantom export format)
        - JSON array of bytes (Solana CLI format)
        - Base64 encoded
        
        Args:
            private_key: Encoded private key string.
        
        Returns:
            64-byte key or None on error.
        """
        private_key = private_key.strip()
        
        # Try JSON array first (Solana CLI format: [1,2,3,...])
        if private_key.startswith('['):
            try:
                key_array = json.loads(private_key)
                if isinstance(key_array, list) and len(key_array) == 64:
                    print(f"[WALLET] Detected JSON array format (64 bytes)")
                    return bytes(key_array)
                else:
                    print(f"[WALLET] JSON array has {len(key_array)} elements (expected 64)")
            except json.JSONDecodeError as e:
                print(f"[WALLET] Invalid JSON: {e}")
        
        # Try base58 (Phantom export format)
        try:
            import base58
            decoded = base58.b58decode(private_key)
            if len(decoded) == 64:
                print(f"[WALLET] Detected base58 format (64 bytes)")
                return decoded
            elif len(decoded) == 32:
                # Some wallets export just the secret key (32 bytes)
                # Need to derive the full keypair
                print(f"[WALLET] Detected 32-byte secret key, deriving full keypair...")
                from solders.keypair import Keypair
                kp = Keypair.from_seed(decoded)
                return bytes(kp)
            else:
                print(f"[WALLET] Base58 decoded to {len(decoded)} bytes (expected 64 or 32)")
        except Exception as e:
            print(f"[WALLET] Base58 decode failed: {e}")
        
        # Try base64
        try:
            decoded = base64.b64decode(private_key)
            if len(decoded) == 64:
                print(f"[WALLET] Detected base64 format (64 bytes)")
                return decoded
            elif len(decoded) == 32:
                print(f"[WALLET] Detected 32-byte base64, deriving full keypair...")
                from solders.keypair import Keypair
                kp = Keypair.from_seed(decoded)
                return bytes(kp)
            else:
                print(f"[WALLET] Base64 decoded to {len(decoded)} bytes (expected 64 or 32)")
        except Exception as e:
            # Not base64, that's fine
            pass
        
        print(f"[WALLET] Could not decode key (length: {len(private_key)} chars)")
        return None
    
    def is_loaded(self) -> bool:
        """Check if wallet keypair is loaded."""
        return self._keypair is not None
    
    def get_address(self) -> Optional[str]:
        """Get wallet public key (address).
        
        Returns:
            Base58-encoded public key or None.
        """
        return self._public_key
    
    def get_keypair(self):
        """Get the solders Keypair object.
        
        Returns:
            Keypair object or None.
        """
        return self._keypair
    
    def sign_transaction(self, transaction_bytes: bytes) -> Optional[bytes]:
        """Sign a serialized transaction.
        
        Args:
            transaction_bytes: Serialized transaction to sign.
        
        Returns:
            Signed transaction bytes or None on error.
        """
        if not self._keypair:
            print("[WALLET] Error: No keypair loaded")
            return None
        
        try:
            from solders.transaction import VersionedTransaction
            
            # Deserialize the transaction
            tx = VersionedTransaction.from_bytes(transaction_bytes)
            
            # Create a new signed transaction using the message and keypair
            # This automatically signs the message correctly
            message = tx.message
            signed_tx = VersionedTransaction(message, [self._keypair])
            
            return bytes(signed_tx)
            
        except Exception as e:
            print(f"[WALLET] Error signing transaction: {e}")
            return None
    
    def sign_message(self, message: bytes) -> Optional[bytes]:
        """Sign an arbitrary message.
        
        Args:
            message: Message bytes to sign.
        
        Returns:
            Signature bytes or None on error.
        """
        if not self._keypair:
            print("[WALLET] Error: No keypair loaded")
            return None
        
        try:
            signature = self._keypair.sign_message(message)
            return bytes(signature)
        except Exception as e:
            print(f"[WALLET] Error signing message: {e}")
            return None


def prompt_for_private_key() -> Optional[str]:
    """Prompt user for private key with hidden input.
    
    Returns:
        Private key string or None if user cancels.
    """
    print("\n" + "=" * 60)
    print("DEX LIVE TRADING - WALLET REQUIRED")
    print("=" * 60)
    print("\nTo execute trades, you need to provide your Solana wallet key.")
    print("\nExport from Phantom:")
    print("  Settings → Security & Privacy → Export Private Key")
    print("\nThe key will be stored in memory only (not saved to disk).")
    print("Press Ctrl+C to cancel.\n")
    
    try:
        key = getpass.getpass("Enter Solana private key (hidden): ")
        if key.strip():
            return key.strip()
        else:
            print("[WALLET] No key entered")
            return None
    except KeyboardInterrupt:
        print("\n[WALLET] Cancelled by user")
        return None


def get_wallet_interactive() -> LocalWallet:
    """Get a LocalWallet by prompting for the private key.
    
    Returns:
        LocalWallet instance (may not be loaded if user cancels).
    """
    key = prompt_for_private_key()
    return LocalWallet(key)


def get_wallet_for_whatif() -> LocalWallet:
    """Get an empty LocalWallet for what-if mode (no key needed).
    
    Returns:
        Empty LocalWallet instance.
    """
    return LocalWallet(None)
