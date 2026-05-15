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
            # Note: solders can panic on invalid keys, so we catch BaseException
            try:
                self._keypair = Keypair.from_base58_string(private_key)
                self._public_key = str(self._keypair.pubkey())
                addr = self._public_key
                print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                return
            except BaseException as e:
                # Catch both Exception and PanicException from pyo3
                print(f"[WALLET] Base58 string method failed: {type(e).__name__}")
            
            # Try decoding and using from_bytes directly
            try:
                import base58
                decoded = base58.b58decode(private_key)
                print(f"[WALLET] Decoded to {len(decoded)} bytes")
                
                # Debug: analyze the key bytes
                if len(decoded) == 64:
                    # Standard format: first 32 = secret seed, last 32 = public key
                    pubkey_bytes = decoded[32:]
                    pubkey_b58 = base58.b58encode(pubkey_bytes).decode('utf-8')
                    print(f"[WALLET] Public key from bytes[32:64]: {pubkey_b58}")
                    
                    # Try deriving from just the seed (first 32 bytes)
                    seed_bytes = decoded[:32]
                    seed_b58 = base58.b58encode(seed_bytes).decode('utf-8')
                    print(f"[WALLET] Seed from bytes[0:32]: {seed_b58[:16]}...")
                    
                    # Try the reverse (in case Jupiter uses public+secret order)
                    rev_pubkey = decoded[:32]
                    rev_pubkey_b58 = base58.b58encode(rev_pubkey).decode('utf-8')
                    print(f"[WALLET] If reversed, public would be: {rev_pubkey_b58}")
                    
                    # Try deriving public key from ed25519 directly
                    try:
                        from nacl.signing import SigningKey
                        # Use first 32 bytes as ed25519 seed
                        sk = SigningKey(decoded[:32])
                        vk = sk.verify_key
                        derived_pubkey = base58.b58encode(bytes(vk)).decode('utf-8')
                        print(f"[WALLET] ed25519 derived from first32: {derived_pubkey}")
                        
                        # Use last 32 bytes as ed25519 seed
                        sk2 = SigningKey(decoded[32:])
                        vk2 = sk2.verify_key
                        derived_pubkey2 = base58.b58encode(bytes(vk2)).decode('utf-8')
                        print(f"[WALLET] ed25519 derived from last32: {derived_pubkey2}")
                    except ImportError:
                        print(f"[WALLET] (nacl not installed - skipping ed25519 check)")
                    except Exception as e:
                        print(f"[WALLET] ed25519 derivation error: {e}")
                
                if len(decoded) == 64:
                    # Try standard order first (secret + public)
                    print(f"[WALLET] Trying from_bytes (64-byte keypair)...")
                    try:
                        self._keypair = Keypair.from_bytes(decoded)
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                    except BaseException:
                        pass
                    
                    # Try reversed order (some wallets export public + secret)
                    print(f"[WALLET] Trying reversed byte order (public + secret)...")
                    try:
                        reversed_bytes = decoded[32:] + decoded[:32]
                        self._keypair = Keypair.from_bytes(reversed_bytes)
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                    except BaseException:
                        pass
                    
                    # Try just the first 32 bytes as seed
                    print(f"[WALLET] Trying first 32 bytes as seed...")
                    try:
                        self._keypair = Keypair.from_seed(decoded[:32])
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                    except BaseException:
                        pass
                    
                    # Try last 32 bytes as seed
                    print(f"[WALLET] Trying last 32 bytes as seed...")
                    try:
                        self._keypair = Keypair.from_seed(decoded[32:])
                        self._public_key = str(self._keypair.pubkey())
                        addr = self._public_key
                        print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                        return
                    except BaseException as e:
                        print(f"[WALLET] All 64-byte methods failed: {type(e).__name__}")
                elif len(decoded) == 32:
                    print(f"[WALLET] Trying from_seed (32-byte secret)...")
                    self._keypair = Keypair.from_seed(decoded)
                    self._public_key = str(self._keypair.pubkey())
                    addr = self._public_key
                    print(f"[WALLET] Loaded wallet: {addr[:8]}...{addr[-4:]}")
                    return
                else:
                    print(f"[WALLET] Unexpected decoded length: {len(decoded)} bytes")
                    print(f"[WALLET] Expected 64 (full keypair) or 32 (seed only)")
            except Exception as e2:
                err_str = str(e2).lower()
                if "signature" in err_str or "invalid" in err_str:
                    print(f"[WALLET] Invalid keypair - bytes are not a valid ed25519 key")
                    print(f"[WALLET] This might be a PUBLIC key, not a PRIVATE key")
                    print(f"[WALLET] Jupiter: Settings → Security → Show Secret Key")
                else:
                    print(f"[WALLET] Fallback decode failed: {e2}")
            
            # Try mnemonic phrase (12 or 24 words)
            words = private_key.split()
            if len(words) in (12, 24):
                print(f"[WALLET] Detected {len(words)}-word mnemonic phrase")
                
                # Try BIP44 derivation first (Trust Wallet, Phantom use this)
                # Path: m/44'/501'/0'/0'
                try:
                    from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
                    
                    # Generate seed from mnemonic
                    seed = Bip39SeedGenerator(private_key).Generate()
                    
                    # Derive using BIP44 path for Solana: m/44'/501'/0'/0'
                    bip44_ctx = Bip44.FromSeed(seed, Bip44Coins.SOLANA)
                    bip44_acc = bip44_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT)
                    
                    # Get the private key bytes
                    priv_key_bytes = bip44_acc.PrivateKey().Raw().ToBytes()
                    
                    self._keypair = Keypair.from_seed(priv_key_bytes)
                    self._public_key = str(self._keypair.pubkey())
                    addr = self._public_key
                    print(f"[WALLET] Loaded wallet from mnemonic (BIP44): {addr[:8]}...{addr[-4:]}")
                    return
                except ImportError:
                    print(f"[WALLET] BIP44 derivation requires: pip install mnemonic bip-utils")
                    # Fall back to solders method
                except Exception as e:
                    print(f"[WALLET] BIP44 derivation failed: {e}")
                
                # Fallback: Try solders default derivation
                try:
                    self._keypair = Keypair.from_seed_phrase_and_passphrase(private_key, "")
                    self._public_key = str(self._keypair.pubkey())
                    addr = self._public_key
                    print(f"[WALLET] Loaded wallet from mnemonic (solders): {addr[:8]}...{addr[-4:]}")
                    return
                except Exception as e:
                    print(f"[WALLET] Mnemonic method failed: {e}")
            
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
