# DEX Trading Feature

## Overview

This document explores options for adding decentralized exchange (DEX) trading capabilities to the trading bot. Currently, the bot only supports Coinbase's centralized exchange (CEX) via the REST API.

**Current State:**
- Uses `coinbase.rest.RESTClient` for market orders
- Trades against USD pairs (e.g., `DOGE-USD`)
- Requires Coinbase account with API credentials
- Limited to coins listed on Coinbase CEX

**Why DEX?**
- Access to coins not listed on centralized exchanges
- Trade directly from wallet without custodial risk
- Access to new tokens earlier (before CEX listing)
- Participate in DeFi ecosystem (liquidity pools, yield farming)
- No KYC requirements for trading

---

## MVP Implementation: Solana via WalletConnect + Phantom

### Key Insight: No New Discovery Method Required

The existing Santiment-based discovery already covers DEX coins. Currently, discovered coins are filtered against Coinbase CEX availability. For DEX mode, we simply change the cross-reference target:

```
┌─────────────────────────────────────────────────────────────────┐
│                     DISCOVERY (unchanged)                        │
│  Santiment API → All crypto projects with volume metrics        │
│  + Optional LLM discovery                                        │
│  + Optional chain/category filters                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│   CEX MODE (current)    │     │   DEX MODE (new)        │
│   --exchange=cex        │     │   --exchange=solana-dex │
├─────────────────────────┤     ├─────────────────────────┤
│ Cross-ref: Coinbase     │     │ Cross-ref: Jupiter      │
│ list_all_coins()        │     │ token list (verified)   │
│ ~200 tradeable coins    │     │ ~1000s tradeable tokens │
├─────────────────────────┤     ├─────────────────────────┤
│ Execution: Coinbase API │     │ Execution: WalletConnect│
│ market_order_buy/sell   │     │ + Phantom + Jupiter     │
└─────────────────────────┘     └─────────────────────────┘
```

### Mode Comparison

| Aspect | CEX Mode (`--exchange=cex`) | DEX Mode (`--exchange=solana-dex`) |
|--------|-----------------------------|------------------------------------|
| **Discovery** | Santiment + LLM (same) | Santiment + LLM (same) |
| **Filters** | --chains, --categories (same) | --chains, --categories (same) |
| **Cross-reference** | Coinbase tradeable list | Jupiter verified token list |
| **Coin universe** | ~200 coins | ~1000s tokens (with filters) |
| **Execution** | Coinbase REST API | WalletConnect → Phantom → Jupiter |
| **Authentication** | API key (cdp_api_key.json) | WalletConnect session |
| **User approval** | None (automated) | Required per trade |
| **Fees** | Coinbase spread (~0.5%) | Gas (~$0.001) + slippage |
| **Settlement** | Instant (custodial) | ~400ms (on-chain) |

### Why This Approach

| Decision | Rationale |
|----------|-----------|
| **Reuse discovery** | Santiment already has Solana meme coins with volume metrics |
| **Solana chain** | Most meme coin activity, lowest fees (~$0.001/swap), fastest execution |
| **WalletConnect** | Industry standard, no private key in bot, user approves each trade |
| **Phantom wallet** | Most popular Solana wallet, excellent WalletConnect support |
| **Jupiter DEX** | Best aggregator, optimal routing, simple API, verified token list |

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Trading Bot   │────▶│   WalletConnect  │────▶│  Phantom Wallet │
│  (Python/CLI)   │     │    (WebSocket)   │     │   (Mobile/Ext)  │
└────────┬────────┘     └──────────────────┘     └────────┬────────┘
         │                                                 │
         │  1. Get quote from Jupiter                      │
         │  2. Build swap transaction                      │
         │  3. Send via WalletConnect ──────────────────▶ │
         │                                                 │
         │  4. User approves in Phantom ◀─────────────────│
         │                                                 │
         │  5. Signed tx returned ◀────────────────────────│
         │  6. Submit to Solana RPC                        │
         ▼                                                 │
┌─────────────────┐                              ┌─────────────────┐
│   Jupiter API   │                              │  Solana Network │
│  (Quote/Route)  │                              │   (Execution)   │
└─────────────────┘                              └─────────────────┘
```

### User Flow

1. **Setup (one-time)**
   - User runs bot with `--exchange=solana-dex`
   - Bot displays WalletConnect QR code or deep link
   - User scans with Phantom mobile app (or clicks link for extension)
   - User approves connection

2. **Discovery (same as CEX mode)**
   - Santiment fetches coins with volume metrics
   - Cross-reference with Jupiter verified token list (instead of Coinbase)
   - Apply chain/category filters if specified
   - LLM analyzes and recommends

3. **Trading (each trade)**
   - LLM recommends coin (e.g., "BUY BONK")
   - Bot fetches Jupiter quote
   - Bot sends transaction request via WalletConnect
   - **User receives push notification in Phantom**
   - User reviews and approves (or rejects)
   - Bot receives signed transaction
   - Bot submits to Solana network
   - Bot records result to history

### Implementation Components

| Component | Technology | Notes |
|-----------|------------|-------|
| WalletConnect client | `walletconnect-py` or `pywalletconnect` | Python WC v2 client |
| Jupiter integration | `httpx` to Jupiter API | Quote and swap endpoints |
| Solana RPC | `solana-py` or `solders` | Transaction submission |
| Session persistence | Local JSON file | Maintain WC session across restarts |

### Code Skeleton

```python
# solana_dex_trader.py

import asyncio
from walletconnect import WalletConnectClient
import httpx

class SolanaDEXTrader:
    def __init__(self):
        self.wc_client = None
        self.connected_wallet = None
        self.jupiter_api = "https://quote-api.jup.ag/v6"
    
    async def connect_wallet(self):
        """Initialize WalletConnect and wait for Phantom connection."""
        self.wc_client = WalletConnectClient(
            project_id="YOUR_WALLETCONNECT_PROJECT_ID",
            metadata={
                "name": "Trading Bot",
                "description": "LLM-powered meme coin trader",
                "url": "https://localhost",
                "icons": []
            }
        )
        
        # Generate connection URI
        uri = await self.wc_client.create_session(
            chains=["solana:mainnet"]
        )
        
        print(f"\n{'='*50}")
        print("CONNECT PHANTOM WALLET")
        print(f"{'='*50}")
        print(f"\nScan QR or open link:\n{uri}")
        print(f"\nPhantom deep link:")
        print(f"phantom://wc?uri={uri}")
        print(f"\nWaiting for connection...")
        
        # Wait for user to connect
        session = await self.wc_client.wait_for_session()
        self.connected_wallet = session.accounts[0]
        print(f"\n✓ Connected: {self.connected_wallet}")
        return self.connected_wallet
    
    async def get_swap_quote(self, input_mint: str, output_mint: str, 
                             amount_lamports: int, slippage_bps: int = 50):
        """Get best swap route from Jupiter."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.jupiter_api}/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount_lamports,
                    "slippageBps": slippage_bps
                }
            )
            return response.json()
    
    async def execute_swap(self, input_mint: str, output_mint: str,
                          amount_lamports: int):
        """Execute swap via Phantom approval."""
        # 1. Get quote
        quote = await self.get_swap_quote(input_mint, output_mint, amount_lamports)
        
        out_amount = int(quote["outAmount"])
        print(f"Quote: {amount_lamports} → {out_amount}")
        
        # 2. Get swap transaction from Jupiter
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.jupiter_api}/swap",
                json={
                    "quoteResponse": quote,
                    "userPublicKey": self.connected_wallet,
                    "wrapAndUnwrapSol": True
                }
            )
            swap_tx = response.json()["swapTransaction"]
        
        # 3. Request signature from Phantom via WalletConnect
        print("Requesting Phantom approval...")
        print(">>> Check your Phantom wallet for approval request <<<")
        
        try:
            signature = await self.wc_client.sign_and_send_transaction(
                chain_id="solana:mainnet",
                transaction=swap_tx
            )
            print(f"✓ Transaction confirmed: {signature}")
            print(f"  https://solscan.io/tx/{signature}")
            return signature
        except Exception as e:
            if "rejected" in str(e).lower():
                print("✗ User rejected transaction in Phantom")
            else:
                print(f"✗ Transaction failed: {e}")
            return None


# Token mint addresses
TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    # Add more as needed
}
```

### Design Decisions

#### 1. WalletConnect Integration ✓

| Decision | Value |
|----------|-------|
| **Python library** | Research both `pywalletconnect` and `walletconnect-py`; use whichever is more maintained |
| **WalletConnect version** | v2 (v1 is sunset) |
| **Project ID** | Register at cloud.walletconnect.com (free tier) |
| **Session persistence** | Memory only by default; plaintext file if `--wc-session-logging=true` |

#### 2. User Experience ✓

| Decision | Value |
|----------|-------|
| **Approval timeout** | 5 minutes |
| **Timeout behavior** | Skip coin, continue to next |
| **Phantom not installed** | Show install link, then abort |
| **Mobile vs extension** | Support both (WalletConnect handles) |
| **Connection display** | Link only (no QR code) |

#### 3. Transaction Handling ✓

| Decision | Value |
|----------|-------|
| **Default slippage** | 1%, configurable via `--slippage` |
| **High slippage** | Warn in Phantom approval screen |
| **Priority fee** | Auto (Jupiter handles) |
| **Confirmation** | Wait for confirm before next trade |

#### 4. Jupiter API ✓

| Aspect | Value |
|--------|-------|
| **Cost** | Free (official Jupiter API) |
| **Rate limit** | 10 req/sec (plenty for trading bot) |
| **Latency** | ~80ms |
| **Swap fee** | 0% (official API) |

**Jupiter token list decisions** (conservative MVP defaults, revise based on beta testing):

| Decision | MVP Value | Rationale |
|----------|-----------|-----------|
| **Token list** | Strict verified only | Most conservative; avoids scams/rugs |
| **Symbol-to-mint mapping** | Local cache with API fallback | Minimize API calls; cache on first run |
| **Minimum liquidity** | $100K | Most conservative; ensures tradeable size |
| **Cache refresh** | Daily | Balance freshness vs API load |
| **Symbol collisions** | Error and skip | Most conservative; avoid wrong token |

*Revise based on beta testing - may relax liquidity threshold or token list strictness if too restrictive.*

*Note: Discovery unchanged - Santiment covers Solana meme coins. Jupiter provides cross-reference list.*

#### 5. Integration with Existing Bot ✓

| Decision | Value |
|----------|-------|
| **CLI parameter** | `--dex` (simple flag, implies Solana DEX mode) |
| **History file** | Same `recommendations.json`, add `exchange` field |
| **What-if mode** | Get Jupiter quote, record recommendation, skip WalletConnect/execution |

**What-if mode detail**: In DEX mode, `--trading-mode=whatif` means:
- ✓ Fetch Jupiter quote (free, stateless)
- ✓ Show price, slippage, route info
- ✓ Record recommendation to history
- ✗ Skip sending transaction to Phantom
- ✗ No user approval needed
- ✗ No on-chain execution

This is safe because there's no risk of accidental execution - real trades require explicit Phantom approval.

#### 6. Security ✓

| Decision | Value |
|----------|-------|
| **WC session storage** | Memory only (default); plaintext file only if `--wc-session-logging=true` |
| **Phantom permissions** | Sign transactions only (minimal) |
| **Rate limiting** | 1 trade request per minute |

#### 6a. Wallet Key Authentication (Alternative to WalletConnect)

Since WalletConnect/Reown signup may not be available, an alternative approach uses an **interactive private key prompt** at startup. This is more secure than environment variables.

**Design:**

| Aspect | Value |
|--------|-------|
| **When prompted** | Only in DEX mode with `--trading-mode=live` |
| **Not prompted** | CEX mode, or DEX mode with `--trading-mode=whatif` |
| **Prompt timing** | Once at startup, before any trading begins |
| **Key storage** | In-memory only, never written to disk or env |
| **Key format** | Base58 (Phantom export format) or JSON array (Solana CLI) |
| **Input method** | `getpass` (hidden input, no echo to terminal) |
| **Session lifetime** | Key remains in memory until program exits |

**User Flow:**

```
$ python crypto_trading_bot.py --dex --trading-mode=live --coins=BONK

[DEX] Live trading mode requires wallet key
[DEX] Export from Phantom: Settings → Security → Export Private Key

Enter Solana private key (hidden): ••••••••••••••••••••

[WALLET] Loaded wallet: 7xKXt...9Qm4
[DEX] SolanaDEXTrader initialized (slippage: 1.0%)

... trading proceeds ...
```

**Security Benefits:**

1. **No shell history exposure** - Key never appears in command line or env vars
2. **No disk persistence** - Key exists only in process memory
3. **Conscious action** - User must actively provide key each session
4. **No accidental logging** - Hidden input prevents screen capture/logging
5. **Process isolation** - Key not visible to other processes via `/proc/*/environ`

**Trade-off:**

- Requires user presence at startup (cannot be fully automated)
- For this trading bot, this is acceptable since trades already require monitoring

#### 7. Error Handling ✓

| Decision | Value |
|----------|-------|
| **Phantom disconnect** | Crash (fail fast) |
| **Jupiter API down** | Fail with clear error |
| **Insufficient SOL** | Warn with amount needed, skip |
| **Token not found** | Skip with warning |

#### 8. Chain Restriction ✓

DEX mode currently only supports **Solana** chain (via Jupiter aggregator).

| Mode | Chain Behavior |
|------|----------------|
| **DEX + live** | Only Solana allowed. Auto-sets `--chains=solana` if not specified. Errors if non-Solana chains specified. |
| **DEX + whatif** | Any chain allowed (for research). Warns if non-Solana chains used. |
| **CEX** | No chain restriction (Coinbase handles availability). |

**Rationale:** Prevents discovering coins that cannot be traded. Each blockchain has different DEX infrastructure (Jupiter for Solana, Uniswap for Ethereum, etc.), so chain-specific support must be implemented before enabling trading.

**Future:** To support additional chains, implement chain-specific DEX modules (e.g., `dex/ethereum/`, `dex/base/`) with their own Jupiter-equivalent aggregators.

#### 9. Test Wallet Feature (Pending)

Optional startup validation to verify wallet connectivity before trading.

**Command-Line Interface:**
```bash
--test-wallet          # Test wallet connection on startup (default: false)
```

**Behavior:**
| Flag | Action |
|------|--------|
| `--test-wallet` not set | Skip wallet test, proceed directly to trading |
| `--test-wallet` set | After key prompt, perform test call before continuing |

**Startup Flow with `--test-wallet`:**
```
1. Parse args, initialize Jupiter client
2. Prompt for private key (getpass)
3. Derive public key from private key
4. Test call: Check SOL balance via Solana RPC
5. Display: "Wallet: <pubkey> | Balance: <SOL> SOL"
6. If balance == 0: Warn "⚠️ Wallet has no SOL - trades will fail"
7. Continue to discovery/analysis
```

**Test Call Options:**
| Option | Pros | Cons |
|--------|------|------|
| **getBalance (SOL)** | Fast, single RPC call, shows if wallet can pay fees | Doesn't test token balances |
| **getTokenAccountsByOwner** | Shows all SPL token holdings | Slower, more data than needed |
| **getAccountInfo** | Confirms account exists on-chain | Less informative |

**Recommended:** `getBalance` - simple, fast, directly relevant (need SOL for fees).

**Sample Output:**
```
[DEX] Testing wallet connection...
[DEX] Wallet: 7xKX...3nYz
[DEX] Balance: 0.05 SOL
[DEX] ✓ Wallet connected successfully
```

**Error Cases:**
| Error | Response |
|-------|----------|
| Invalid private key format | "Invalid key format. Expected base58 or JSON array." Exit. |
| RPC connection failed | "Cannot connect to Solana RPC: <error>". Exit. |
| Key valid but balance query fails | "Wallet test failed: <error>". Exit. |

**Design Decisions:**

| Question | Decision |
|----------|----------|
| Required for live trading? | **No** - always optional |
| Check token balances (USDC)? | **No** - SOL balance only |
| Low balance behavior? | **Warn** and continue |
| Cache test results? | **No** - test each run if flag set |
| Environment variable? | **No** - CLI flag only |

---

### Implementation Architecture: Separation of Concerns

This section outlines how to implement DEX support while **minimizing risk to the existing CEX implementation**.

#### Design Principles

1. **Isolate DEX code in separate modules** - No DEX logic in existing files
2. **Share interfaces, not implementations** - Common abstractions, different backends
3. **Feature flag at entry point** - Single `--dex` check gates all DEX code paths
4. **No CEX code changes for MVP** - DEX is purely additive

#### Module Structure

```
tradingbot/
├── crypto_trading_bot.py      # Main entry - add --dex flag check only
├── coinbaseutil2.py          # CEX trading (UNCHANGED)
├── santimentutil.py          # Discovery (UNCHANGED - used by both)
├── historyutil.py            # History recording (minor: add exchange field)
│
├── dex/                      # NEW: All DEX code isolated here
│   ├── __init__.py
│   ├── trader.py             # SolanaDEXTrader class
│   ├── jupiterutil.py        # Jupiter API: quotes, swaps, token list
│   ├── walletconnect.py      # WalletConnect session management
│   └── token_cache.py        # Jupiter token list cache
```

#### Interface Abstraction

Both CEX and DEX traders implement the same interface:

```python
# trader_interface.py (conceptual - may not need explicit file)

class TraderInterface:
    """Common interface for CEX and DEX traders."""
    
    def list_all_coins(self) -> list[str]:
        """Return tradeable coin symbols."""
        ...
    
    def get_price(self, symbol: str) -> tuple[float, float, float]:
        """Return (price, bid, ask) for symbol."""
        ...
    
    def execute_buy(self, symbol: str, amount: float) -> dict:
        """Execute buy order, return result."""
        ...
    
    def execute_sell(self, symbol: str, amount: float) -> dict:
        """Execute sell order, return result."""
        ...
```

```python
# CEX implementation (existing - no changes needed)
class BlobbyTrader:
    def list_all_coins(self): ...      # Already exists
    def get_price(self, symbol): ...   # Already exists  
    def market_order_buy(self, ...):   # Already exists
    def market_order_sell(self, ...):  # Already exists

# DEX implementation (new - in dex/trader.py)
class SolanaDEXTrader:
    def list_all_coins(self): ...      # Jupiter verified token list
    def get_price(self, symbol): ...   # Jupiter quote API
    def execute_buy(self, ...):        # WalletConnect → Phantom → Jupiter swap
    def execute_sell(self, ...):       # WalletConnect → Phantom → Jupiter swap
```

#### Entry Point Isolation

Single decision point in `crypto_trading_bot.py`:

```python
# At startup - ONE place where mode is determined
if args.dex:
    from dex.trader import SolanaDEXTrader
    trader = SolanaDEXTrader()
    EXCHANGE_MODE = "solana-dex"
else:
    from coinbaseutil2 import BlobbyTrader
    trader = BlobbyTrader()
    EXCHANGE_MODE = "cex"

# Rest of code uses `trader` interface - no CEX/DEX conditionals scattered throughout
```

#### Risk Mitigation Checklist

| Risk | Mitigation |
|------|------------|
| **Breaking CEX trading** | DEX code in separate `dex/` directory; no edits to `coinbaseutil2.py` |
| **Discovery regression** | `santimentutil.py` unchanged; only cross-reference target changes |
| **History format breakage** | Add `exchange` field only; existing fields unchanged |
| **Import errors** | DEX imports inside `if args.dex:` block; no import if not using DEX |
| **Dependency conflicts** | New DEX dependencies in separate requirements section |
| **Test coverage gaps** | DEX has own test file `test_dex.py`; CEX tests unchanged |

#### Changes to Existing Files (Minimal)

| File | Change | Risk Level |
|------|--------|------------|
| `crypto_trading_bot.py` | Add `--dex` argument, conditional trader import | Low |
| `historyutil.py` | Add optional `exchange` field to record | Low |
| `requirements.txt` | Add DEX dependencies (optional section) | None |

**No changes to:**
- `coinbaseutil2.py`
- `santimentutil.py`
- `lunarcrushutil.py`
- `tradeanalyzer.py` (can filter by exchange field later)

#### Testing Strategy

```
# CEX regression test (run before and after DEX implementation)
python crypto_trading_bot.py --trading-mode=whatif --coins=DOGE,SHIB

# DEX isolated test
python -m pytest dex/test_dex.py

# DEX integration test
python crypto_trading_bot.py --dex --trading-mode=whatif --coins=BONK,WIF
```

#### Rollback Plan

If DEX causes issues:
1. Remove `--dex` flag handling (single code block)
2. Delete `dex/` directory
3. Remove DEX dependencies from requirements
4. **CEX functionality remains 100% intact**

---

### Alternative Approaches Within Constraints

If WalletConnect + Phantom proves problematic, consider:

#### Alternative A: Phantom Browser Extension Direct

Connect to Phantom browser extension via injected provider (requires browser context).

```python
# Would require running in browser or Electron wrapper
# Not ideal for CLI bot
```
**Verdict**: Not suitable for CLI application

#### Alternative B: Dedicated Bot Wallet + Phantom Funding

Create separate Solana wallet for bot, fund from Phantom manually.

```python
from solders.keypair import Keypair

# Generate dedicated bot wallet (one-time)
bot_keypair = Keypair()
print(f"Fund this address from Phantom: {bot_keypair.pubkey()}")
# User sends SOL from Phantom to bot wallet
# Bot uses bot_keypair for signing (no WC needed)
```

**Verdict**: Backup option if WalletConnect is too slow/unreliable. Less secure (key in bot), but fully automated.

#### Alternative C: Phantom Deeplinks (Mobile Only)

Use Phantom deeplinks to open swap directly in Phantom app.

```python
# Opens Phantom with pre-filled swap
deeplink = f"phantom://swap?inputMint={SOL}&outputMint={BONK}&amount={amount}"
print(f"Open in Phantom: {deeplink}")
# User completes swap manually in Phantom
# Bot cannot confirm execution
```

**Verdict**: Poorest UX - bot cannot track execution. Not recommended.

### Recommended MVP Scope

| Feature | In MVP | Post-MVP |
|---------|--------|----------|
| WalletConnect v2 connection | ✓ | |
| Phantom wallet support | ✓ | |
| Jupiter swap execution | ✓ | |
| SOL → token swaps | ✓ | |
| Token → SOL swaps | ✓ | |
| Token → token swaps | | ✓ |
| Session persistence | ✓ | |
| QR code display | ✓ | |
| 60s approval timeout | ✓ | |
| Configurable slippage | ✓ | |
| Trade history logging | ✓ | |
| What-if mode | ✓ | |
| Multiple wallets | | ✓ |
| Limit orders | | ✓ |
| Auto-approve (dedicated wallet) | | ✓ |
| Base/EVM chain support | | ✓ |

### Dependencies to Add

```
# requirements.txt additions
pywalletconnect>=0.2.0   # WalletConnect v2 client
solders>=0.20.0          # Solana primitives
solana>=0.30.0           # Solana RPC client
qrcode>=7.4              # QR code generation for terminal
httpx>=0.25.0            # Async HTTP for Jupiter API
```

### Next Steps

1. **Register WalletConnect Project ID** at cloud.walletconnect.com
2. **Create `jupiterutil.py`** - Jupiter token list fetching + symbol-to-mint mapping
3. **Prototype WalletConnect connection** with Phantom in isolation
4. **Test Jupiter quote/swap API** in isolation  
5. **Build `SolanaDEXTrader` class** combining WalletConnect + Jupiter
6. **Add `--exchange` parameter** to `crypto_trading_bot.py` (cex | solana-dex)
7. **Modify cross-reference logic** to use Jupiter list when `--exchange=solana-dex`
8. **Add `exchange` field** to history recording
9. **Test full flow** with what-if mode first

---

## Option 1: Coinbase Onchain API

Coinbase provides an Onchain API through the Coinbase Developer Platform (CDP) for interacting with blockchain networks.

### Capabilities
- **Wallet Management**: Create and manage wallets programmatically
- **Token Transfers**: Send/receive tokens on supported chains
- **Smart Contract Interaction**: Call arbitrary contract functions
- **Supported Chains**: Ethereum, Base, Polygon, Arbitrum, Optimism, Solana

### Integration Approach
```python
from coinbase.wallet import Wallet

# Create or load wallet
wallet = Wallet.create()  # or Wallet.load(wallet_id)

# Interact with DEX contract (e.g., Uniswap)
swap_result = wallet.invoke_contract(
    contract_address="0x...",  # Uniswap Router
    method="swapExactTokensForTokens",
    args={...}
)
```

### Pros
- Same SDK/credentials as current CEX integration
- Managed wallet infrastructure
- Multi-chain support
- Good documentation

### Cons
- Requires understanding DEX contract ABIs
- Gas fees on each transaction
- Slippage management needed
- More complex error handling

---

## Option 2: Direct DEX Integration (Uniswap, Jupiter, etc.)

Integrate directly with popular DEX protocols using their SDKs or APIs.

### Uniswap (Ethereum/Base/Polygon/Arbitrum)
```python
from uniswap import Uniswap

uniswap = Uniswap(
    address=wallet_address,
    private_key=private_key,
    version=3,
    provider=web3_provider
)

# Swap ETH for token
uniswap.make_trade(eth, token_address, qty)
```

### Jupiter (Solana)
```python
import httpx

# Get quote
quote = httpx.get(
    "https://quote-api.jup.ag/v6/quote",
    params={
        "inputMint": "So11111111111111111111111111111111111111112",  # SOL
        "outputMint": token_mint,
        "amount": amount_in_lamports,
        "slippageBps": 50
    }
).json()

# Execute swap via transaction
```

### Raydium (Solana)
- Alternative to Jupiter for Solana
- Better for certain token pairs
- AMM and CLMM pools

### Pros
- Direct access to DEX liquidity
- Can optimize for best prices across pools
- Full control over transaction parameters

### Cons
- Must manage private keys securely
- Different SDK/API for each chain
- Complex transaction building
- Gas estimation and management

---

## Option 3: DEX Aggregator APIs

Use aggregator services that find best prices across multiple DEXes.

### 1inch API
```python
import httpx

# Get swap quote across all DEXes
response = httpx.get(
    "https://api.1inch.dev/swap/v6.0/1/swap",
    params={
        "src": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",  # ETH
        "dst": token_address,
        "amount": amount_wei,
        "from": wallet_address,
        "slippage": 1
    },
    headers={"Authorization": f"Bearer {API_KEY}"}
)
```

### 0x API
- Similar to 1inch
- Good for Ethereum and EVM chains
- Professional-grade liquidity

### Pros
- Best prices via aggregation
- Simpler API than direct DEX
- Handles routing complexity

### Cons
- API rate limits
- Some require API keys (may have costs)
- Still need wallet/signing infrastructure

---

## Option 4: Wallet-as-a-Service Providers

Use managed wallet infrastructure with built-in DEX capabilities.

### Privy
- Embedded wallets for apps
- Social login support
- Built-in transaction handling

### Dynamic
- Similar to Privy
- Multi-chain support
- Good developer experience

### Fireblocks
- Enterprise-grade
- MPC wallets (no single private key)
- Expensive but very secure

### Pros
- Abstracts wallet management complexity
- Often includes DEX integrations
- Better security than self-managed keys

### Cons
- Monthly fees
- Vendor lock-in
- May have transaction limits

---

## Option 5: Trading Bots / Infrastructure

Use existing bot infrastructure that handles DEX complexity.

### Hummingbot
- Open source trading bot framework
- Supports many CEX and DEX
- Python-based, could integrate

### 3Commas / Pionex
- Commercial bot platforms
- Some have DEX support
- API access available

### Pros
- Battle-tested infrastructure
- Handles edge cases
- Community support

### Cons
- Another dependency
- May not fit our architecture
- Subscription costs (commercial)

---

## Technical Requirements (All Options)

### Wallet Management
| Requirement | Description |
|-------------|-------------|
| Private Key Storage | Secure storage (env var, secrets manager, HSM) |
| Key Rotation | Ability to rotate compromised keys |
| Multi-sig Option | For larger amounts, require multiple signatures |

### Transaction Handling
| Requirement | Description |
|-------------|-------------|
| Gas Estimation | Estimate gas before submitting |
| Gas Price Strategy | Fast/normal/slow based on urgency |
| Nonce Management | Handle concurrent transactions |
| Retry Logic | Resubmit failed transactions |
| Confirmation Waiting | Wait for block confirmations |

### Slippage & MEV Protection
| Requirement | Description |
|-------------|-------------|
| Slippage Tolerance | Configure max acceptable slippage (e.g., 1%) |
| MEV Protection | Use private mempools (Flashbots, MEV Blocker) |
| Sandwich Attack Prevention | Deadline parameters, private RPCs |

### Price Discovery
| Requirement | Description |
|-------------|-------------|
| Token Price Lookup | Map token symbols to contract addresses |
| Liquidity Check | Verify sufficient liquidity before trading |
| Price Impact | Calculate and limit price impact |

---

## Chain-Specific Considerations

### Ethereum Mainnet
- **Gas Costs**: $5-50+ per swap depending on congestion
- **Speed**: ~12 second blocks
- **DEXes**: Uniswap, Sushiswap, Curve
- **Best For**: Large trades, established tokens

### Base (Coinbase L2)
- **Gas Costs**: $0.01-0.10 per swap
- **Speed**: ~2 second blocks
- **DEXes**: Uniswap, Aerodrome, BaseSwap
- **Best For**: Frequent trading, smaller amounts
- **TVL**: ~$4.7 billion
- **Daily Transactions**: Up to 13M+

#### Base Token Model

Base is a **permissionless EVM-compatible chain**. Unlike a CEX with a fixed coin list, any ERC-20 token can be deployed and traded on Base.

**Token Categories:**

| Category | Examples | Notes |
|----------|----------|-------|
| **Bridged from Ethereum** | ETH, USDC, USDT, DAI, WBTC | Via Base Bridge or third-party bridges |
| **Native Base Tokens** | BRETT, TOSHI, DEGEN, AERO, VIRTUAL | Launched on Base first |
| **Multi-chain Tokens** | USDC (native), AXL, BAL | Circle issues USDC natively on Base |

**Notable Base-Native Tokens:**

| Token | Type | Description |
|-------|------|-------------|
| BRETT | Meme | Popular Base meme coin |
| TOSHI | Meme | Named after Coinbase founder's cat |
| DEGEN | Meme | Farcaster community token |
| AERO | DeFi | Aerodrome DEX governance (~$1.7B volume) |
| VIRTUAL | AI | Virtuals Protocol for AI agents |

#### Token Address Handling

Unlike CEX trading (symbol-based), DEX trading requires **contract addresses**:

```python
# CEX (current bot)
product_id = "BRETT-USD"  # Simple symbol

# DEX (Base)
token_address = "0x532f27101965dd16442E59d40670FaF5eBB142E4"  # BRETT on Base
weth_address = "0x4200000000000000000000000000000000000006"   # WETH on Base
```

**Implementation Considerations:**

1. **Token Registry**: Need mapping of symbols → contract addresses
   - Could use CoinGecko API for address lookup
   - Or maintain local registry for known tokens
   - Must verify addresses (scam tokens use similar names)

2. **Liquidity Verification**: Before trading, check:
   - Pool exists on DEX
   - Sufficient liquidity for trade size
   - Price impact is acceptable

3. **Token Approval**: ERC-20 tokens require approval before swap:
   ```python
   # First transaction: approve DEX to spend tokens
   token.approve(dex_router, amount)
   # Second transaction: execute swap
   dex.swap(token_in, token_out, amount)
   ```

4. **Native ETH vs WETH**: 
   - Base uses ETH for gas
   - DEXes use WETH (wrapped ETH) for swaps
   - May need wrap/unwrap steps

#### Base DEX Options

| DEX | Type | Best For | API/SDK |
|-----|------|----------|---------|
| **Aerodrome** | AMM (ve(3,3)) | Best liquidity on Base | Direct contract calls |
| **Uniswap V3** | Concentrated liquidity | Established pairs | Uniswap SDK |
| **BaseSwap** | AMM | Smaller tokens | Direct contract calls |

**Aerodrome** is the dominant DEX on Base with ~$1.7B in volume. Recommended as primary integration target.

#### Bridging Considerations

To trade on Base, funds must be on Base chain:

| Method | Time | Cost | Notes |
|--------|------|------|-------|
| **Base Bridge** (official) | ~7 days withdraw | Gas only | Safest, slow withdrawals |
| **Across Protocol** | Minutes | ~0.1% fee | Fast, recommended |
| **Stargate** | Minutes | ~0.1% fee | Alternative |
| **Coinbase** | Instant | Free | Deposit/withdraw directly to Base |

**Recommendation**: Use Coinbase CEX as on/off ramp to Base (free, instant)

### Solana
- **Gas Costs**: ~$0.001 per swap
- **Speed**: ~400ms blocks
- **DEXes**: Jupiter, Raydium, Orca
- **Best For**: High-frequency trading, meme coins

### Arbitrum / Optimism
- **Gas Costs**: $0.05-0.50 per swap
- **Speed**: ~2 second blocks
- **DEXes**: Uniswap, Camelot (Arbitrum), Velodrome (Optimism)
- **Best For**: Balance of cost/liquidity

---

## Wallet Integration

DEX trading requires a wallet to sign transactions. Unlike CEX trading (API key auth), DEX trading requires cryptographic signing with a private key.

### Wallet Integration Approaches

| Approach | Security | Complexity | Best For |
|----------|----------|------------|----------|
| **Raw Private Key** | Low (key exposed) | Low | Development/testing |
| **Keystore File** | Medium (encrypted) | Medium | Single-user bots |
| **Hardware Wallet** | High | High | Large amounts |
| **Wallet Connect** | Medium-High | Medium | Interactive use |
| **MPC Wallet** | Very High | High | Enterprise/production |

### Approach 1: Raw Private Key (Development Only)

Simplest but least secure. Key is stored as environment variable or file.

```python
from eth_account import Account
from web3 import Web3

# Load private key from environment
private_key = os.environ.get("WALLET_PRIVATE_KEY")
account = Account.from_key(private_key)

# Sign and send transaction
signed_tx = account.sign_transaction(tx)
tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
```

**⚠️ WARNING**: Never commit private keys to git or expose in logs.

### Approach 2: Encrypted Keystore File

Private key encrypted with password. More secure than raw key.

```python
from eth_account import Account
import json

# Load encrypted keystore
with open("keystore.json", "r") as f:
    keystore = json.load(f)

# Decrypt with password (prompted or from secure source)
password = getpass.getpass("Wallet password: ")
private_key = Account.decrypt(keystore, password)
account = Account.from_key(private_key)
```

### Approach 3: Hardware Wallet (Ledger/Trezor)

Most secure for significant funds. Requires physical device for signing.

```python
from ledgerblue.Dongle import getDongle

# Connect to Ledger
dongle = getDongle(True)

# Sign transaction on device (user must confirm)
signature = dongle.exchange(apdu_sign_command)
```

**Limitation**: Requires user interaction for each transaction. Not suitable for automated trading.

### Approach 4: WalletConnect (Interactive)

Connect to existing wallet apps (Phantom, MetaMask, etc.) via QR code.

```python
from pywalletconnect import WalletConnect

# Create session
wc = WalletConnect()
uri = wc.create_session()
print(f"Scan QR code: {uri}")

# Wait for connection
wc.wait_for_connection()

# Request signature (user approves in wallet app)
signature = wc.sign_transaction(tx)
```

**Limitation**: Requires user to approve each transaction in wallet app.

---

## Phantom Wallet Integration Example

Phantom is a popular multi-chain wallet supporting **Solana**, **Ethereum**, **Base**, and **Polygon**.

### Option A: Export Private Key from Phantom (Not Recommended)

Phantom allows exporting the private key for use in scripts:

1. Open Phantom → Settings → Security & Privacy → Export Private Key
2. Store securely (never in code)

```python
# Solana with exported Phantom key
from solders.keypair import Keypair
import base58

# Phantom exports as base58-encoded secret key
phantom_secret = os.environ.get("PHANTOM_PRIVATE_KEY")
keypair = Keypair.from_base58_string(phantom_secret)

print(f"Wallet address: {keypair.pubkey()}")

# Sign Solana transaction
signed_tx = transaction.sign([keypair])
```

```python
# EVM (Base/Ethereum) with exported Phantom key
from eth_account import Account

# Phantom EVM key is standard hex private key
phantom_evm_key = os.environ.get("PHANTOM_EVM_PRIVATE_KEY")
account = Account.from_key(phantom_evm_key)

print(f"Wallet address: {account.address}")
```

**⚠️ Security Risk**: Exported keys can be stolen. Use separate wallet with limited funds for bot trading.

### Option B: Phantom via WalletConnect (Recommended for Interactive Use)

Connect to Phantom without exposing private key:

```python
from pywalletconnect import WalletConnect

# Initialize WalletConnect session
wc = WalletConnect(
    project_id="your_walletconnect_project_id",
    metadata={
        "name": "Trading Bot",
        "description": "Automated DEX trading",
        "url": "https://yourbot.com",
        "icons": []
    }
)

# Generate connection URI
uri = wc.create_session(chains=["solana:mainnet", "eip155:8453"])  # Solana + Base
print(f"Connect Phantom: {uri}")
# User scans QR or clicks deep link in Phantom

# Wait for approval
session = wc.wait_for_session()
wallet_address = session.accounts[0]

# Request transaction signature
# User sees popup in Phantom and approves
tx_signature = wc.sign_and_send_transaction(
    chain_id="eip155:8453",  # Base
    transaction=swap_tx
)
```

**Pros**: Private key never leaves Phantom, user approves each trade
**Cons**: Not fully automated, requires user interaction

### Option C: Dedicated Bot Wallet (Recommended for Automation)

Create a **separate wallet** specifically for bot trading:

```python
# Generate new wallet for bot use
from eth_account import Account

# Create new account (do this once, save securely)
new_account = Account.create()
print(f"Address: {new_account.address}")
print(f"Private Key: {new_account.key.hex()}")  # Save this securely!

# Fund from Phantom
# Transfer small amount from Phantom to bot wallet address
# This isolates bot funds from main wallet
```

**Workflow:**
1. Create dedicated bot wallet
2. Fund from Phantom with limited amount (e.g., $100-500)
3. Bot uses dedicated wallet's private key
4. If compromised, only bot wallet funds at risk

### Phantom-Specific Considerations

| Feature | Solana | EVM (Base/Ethereum) |
|---------|--------|---------------------|
| **Key Format** | Base58 (64 bytes) | Hex (32 bytes) |
| **Address Format** | Base58 (32 bytes) | 0x-prefixed hex (20 bytes) |
| **Transaction Signing** | Ed25519 | ECDSA secp256k1 |
| **Fee Token** | SOL | ETH |
| **Phantom Deep Link** | `phantom://` | `phantom://` |

### Complete Solana Trading Example with Phantom Key

```python
import os
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
import httpx

# Setup
PHANTOM_KEY = os.environ.get("PHANTOM_SOLANA_KEY")
keypair = Keypair.from_base58_string(PHANTOM_KEY)
solana_client = Client("https://api.mainnet-beta.solana.com")

# Get Jupiter swap quote
async def get_swap_quote(input_mint: str, output_mint: str, amount: int):
    response = httpx.get(
        "https://quote-api.jup.ag/v6/quote",
        params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": 50  # 0.5% slippage
        }
    )
    return response.json()

# Get swap transaction
async def get_swap_transaction(quote: dict):
    response = httpx.post(
        "https://quote-api.jup.ag/v6/swap",
        json={
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True
        }
    )
    return response.json()["swapTransaction"]

# Execute swap
async def execute_swap(input_mint: str, output_mint: str, amount: int):
    # Get quote
    quote = await get_swap_quote(input_mint, output_mint, amount)
    print(f"Quote: {quote['outAmount']} output for {amount} input")
    
    # Get transaction
    swap_tx_base64 = await get_swap_transaction(quote)
    
    # Deserialize and sign
    from solders.transaction import VersionedTransaction
    import base64
    
    tx_bytes = base64.b64decode(swap_tx_base64)
    tx = VersionedTransaction.from_bytes(tx_bytes)
    signed_tx = tx.sign([keypair])
    
    # Send
    signature = solana_client.send_transaction(signed_tx)
    print(f"Transaction: https://solscan.io/tx/{signature}")
    return signature

# Example: Swap 0.1 SOL for BONK
SOL_MINT = "So11111111111111111111111111111111111111112"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
LAMPORTS = 100_000_000  # 0.1 SOL

execute_swap(SOL_MINT, BONK_MINT, LAMPORTS)
```

### Complete Base Trading Example with Phantom Key

```python
import os
from eth_account import Account
from web3 import Web3

# Setup
PHANTOM_EVM_KEY = os.environ.get("PHANTOM_EVM_KEY")
account = Account.from_key(PHANTOM_EVM_KEY)

# Base RPC
w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))

# Aerodrome Router address
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"

# Token addresses on Base
WETH = "0x4200000000000000000000000000000000000006"
BRETT = "0x532f27101965dd16442E59d40670FaF5eBB142E4"

# Simplified swap (actual implementation needs ABI encoding)
def swap_eth_for_token(token_out: str, amount_in_wei: int, min_out: int):
    # Build swap transaction
    tx = {
        "from": account.address,
        "to": AERODROME_ROUTER,
        "value": amount_in_wei,
        "gas": 250000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(account.address),
        "data": encode_swap_call(WETH, token_out, amount_in_wei, min_out)
    }
    
    # Sign and send
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    
    print(f"Transaction: https://basescan.org/tx/{tx_hash.hex()}")
    return tx_hash

# Example: Swap 0.01 ETH for BRETT
swap_eth_for_token(BRETT, w3.to_wei(0.01, "ether"), 0)
```

---

## Trust Wallet Agent SDK Integration (Recommended)

After experiencing key format issues with Jupiter and Phantom mobile wallets (non-standard derivation paths, mismatched public keys), **Trust Wallet's Agent SDK (TWAK)** is the recommended approach for programmatic DEX trading.

### Why Trust Wallet

| Issue with Jupiter/Phantom | Trust Wallet Solution |
|---------------------------|----------------------|
| Private key export produces wrong wallet address | Generates standard BIP39/BIP44 keys locally |
| Mnemonic derivation path mismatch | Uses standard Solana derivation `m/44'/501'/0'/0'` |
| Mobile-first design, difficult automation | CLI-first design, built for automation |
| Key format varies by wallet version | Consistent encrypted keystore format |

### Trust Wallet Agent SDK Features

- **Multi-chain support** - Solana, Ethereum, Base, 25+ chains from one wallet
- **Secure local keys** - BIP39 HD wallet encrypted with AES-256-GCM
- **CLI-based** - `twak` command for all wallet operations
- **Swap execution** - Direct swap commands with password authentication
- **API Gateway** - Prices, balances, quotes without needing wallet password

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Trading Bot   │────▶│   Trust Wallet   │────▶│   Blockchain    │
│  (Python/CLI)   │     │   Agent SDK      │     │   (Solana/EVM)  │
└────────┬────────┘     └──────────────────┘     └─────────────────┘
         │                       │
         │  1. twak swap quote   │
         │  2. twak swap execute │
         │     (with password)   │
         │                       │
         │  3. Transaction hash  │◀────────────────────────────────
         │  4. Confirmation      │
         ▼                       │
┌─────────────────┐     ┌──────────────────┐
│  History Logger │     │  ~/.twak/        │
│                 │     │  wallet.json     │
│                 │     │  (encrypted)     │
└─────────────────┘     └──────────────────┘
```

### Setup Steps

1. **Get API credentials** at [portal.trustwallet.com](https://portal.trustwallet.com)

2. **Install CLI**:
   ```bash
   npm install -g @trustwallet/cli
   # or use without install:
   npx @trustwallet/cli --version
   ```

3. **Initialize credentials**:
   ```bash
   twak init --api-key YOUR_ACCESS_ID --api-secret YOUR_HMAC_SECRET
   ```

4. **Create wallet**:
   ```bash
   twak wallet create
   # Prompts for password, generates encrypted HD wallet
   ```

5. **Get Solana address**:
   ```bash
   twak wallet address --chain solana --password YOUR_PASSWORD
   ```

6. **Fund wallet** - Transfer SOL + USDC to the address

### CLI Commands for Trading

```bash
# Check balance
twak balance --chain solana --password YOUR_PASSWORD

# Get swap quote (no password needed)
twak swap quote --chain solana --from SOL --to USDC --amount 1

# Execute swap (requires password)
twak swap execute --chain solana --from SOL --to USDC --amount 1 --password YOUR_PASSWORD

# Check token price
twak price SOL
```

### Python Integration

```python
import subprocess
import json
import os

class TrustWalletTrader:
    """Trade via Trust Wallet Agent SDK CLI."""
    
    def __init__(self, password: str = None):
        self.password = password or os.environ.get("TWAK_WALLET_PASSWORD")
        self._address = None
    
    def _run_twak(self, args: list, needs_password: bool = False) -> dict:
        """Run twak CLI command and return JSON output."""
        cmd = ["twak"] + args + ["--json"]
        if needs_password and self.password:
            cmd.extend(["--password", self.password])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"twak failed: {result.stderr}")
        return json.loads(result.stdout)
    
    def get_address(self, chain: str = "solana") -> str:
        """Get wallet address for chain."""
        if not self._address:
            result = self._run_twak(
                ["wallet", "address", "--chain", chain],
                needs_password=True
            )
            self._address = result["address"]
        return self._address
    
    def get_balance(self, chain: str = "solana") -> dict:
        """Get wallet balances."""
        return self._run_twak(
            ["balance", "--chain", chain],
            needs_password=True
        )
    
    def get_swap_quote(self, chain: str, from_token: str, 
                       to_token: str, amount: float) -> dict:
        """Get swap quote (no password needed)."""
        return self._run_twak([
            "swap", "quote",
            "--chain", chain,
            "--from", from_token,
            "--to", to_token,
            "--amount", str(amount)
        ])
    
    def execute_swap(self, chain: str, from_token: str,
                     to_token: str, amount: float) -> dict:
        """Execute swap (requires password)."""
        return self._run_twak([
            "swap", "execute",
            "--chain", chain,
            "--from", from_token,
            "--to", to_token,
            "--amount", str(amount)
        ], needs_password=True)


# Usage
trader = TrustWalletTrader(password="your_secure_password")

# Check balance
balance = trader.get_balance("solana")
print(f"SOL: {balance['SOL']}")

# Get quote
quote = trader.get_swap_quote("solana", "USDC", "SOL", 10.0)
print(f"10 USDC -> {quote['outputAmount']} SOL")

# Execute swap
result = trader.execute_swap("solana", "USDC", "SOL", 10.0)
print(f"Tx: {result['txHash']}")
```

### Security Model

| Aspect | Trust Wallet Approach |
|--------|----------------------|
| **Key storage** | Encrypted locally in `~/.twak/wallet.json` |
| **Encryption** | AES-256-GCM with PBKDF2-derived key |
| **Password** | Required for signing, not stored on disk |
| **API keys** | For read-only operations (prices, quotes) |
| **Private keys** | Never leave device, never sent to API |

### Password Handling Options

| Method | Security | Use Case |
|--------|----------|----------|
| `--password` flag | Low (visible in history) | Testing only |
| `TWAK_WALLET_PASSWORD` env | Medium | CI/CD |
| OS keychain | High | Recommended for local |
| Interactive prompt | High | Manual trading |

### Integration with LiveTrader

Replace current `LocalWallet` + Jupiter direct calls with Trust Wallet:

```python
# Before (Jupiter/LocalWallet)
wallet = LocalWallet(private_key)  # Key format issues
jupiter = JupiterClient()
quote = jupiter.get_quote(...)
tx = jupiter.build_swap_transaction(...)
signed = wallet.sign(tx)
result = submit_transaction(signed)

# After (Trust Wallet)
trader = TrustWalletTrader(password)
quote = trader.get_swap_quote("solana", "USDC", "SOL", amount)
result = trader.execute_swap("solana", "USDC", "SOL", amount)
```

### Advantages Summary

1. **No key format issues** - Standard BIP39/BIP44, consistent across all chains
2. **Built for automation** - CLI-first, JSON output, scriptable
3. **Secure by default** - Encrypted storage, password-gated signing
4. **Multi-chain ready** - Same wallet for Solana, Base, Ethereum
5. **Official support** - Trust Wallet maintains the SDK with documentation

### Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `dex/trustwallet.py` | Create | TrustWalletTrader class |
| `dex/trader.py` | Modify | Add Trust Wallet as backend option |
| `correlation_tracker.py` | Modify | Use Trust Wallet in live mode |
| `probe_trustwallet_swap.py` | Create | Test script for Trust Wallet swaps |

---

## Lessons Learned: Private Key Derivation

### The Problem

During implementation, we encountered a **consistent issue across multiple wallet providers** (Jupiter, Phantom, Trust Wallet): exported private keys did not derive to the expected wallet address.

| Wallet | Private Key Export | Derived Address | Expected Address | Match? |
|--------|-------------------|-----------------|------------------|--------|
| Jupiter | 88-char base58 | `B2sdS7cf...` | `FU8PNV...` | ❌ No |
| Phantom | Similar | Different | Expected | ❌ No |
| Trust Wallet | Per-network key | Different | Expected | ❌ No |

This was **not due to**:
- Multiple accounts (checked thoroughly)
- Mixed up keys (verified source)
- Different derivation paths in our code (tested multiple)

### The Solution: Recovery Phrase + BIP44 Derivation

The solution was to use the **wallet's recovery phrase (mnemonic)** with proper BIP44 derivation:

```python
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

# Derive Solana key from mnemonic using BIP44 path: m/44'/501'/0'/0'
seed = Bip39SeedGenerator(mnemonic_phrase).Generate()
bip44_ctx = Bip44.FromSeed(seed, Bip44Coins.SOLANA)
bip44_acc = bip44_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT)
priv_key_bytes = bip44_acc.PrivateKey().Raw().ToBytes()

keypair = Keypair.from_seed(priv_key_bytes)
# This now matches the wallet's displayed address!
```

### Why This Matters

- **Private key export is unreliable** - Different wallets export keys in different formats
- **Recovery phrase is the source of truth** - Standard BIP39/BIP44 derivation is consistent
- **Multi-chain wallets derive different keys per network** - The same seed produces different addresses for ETH vs SOL vs BTC

### Required Dependencies

```bash
pip install bip-utils solders
```

---

## Network Requirements for Jupiter Swaps

### Critical: Both Tokens Must Be on Solana

Jupiter is a **Solana-only DEX aggregator**. For a swap to work:

| Requirement | Details |
|-------------|---------|
| Input token | Must be SPL token on Solana |
| Output token | Must be SPL token on Solana |
| SOL for gas | ~0.005 SOL minimum for transaction fees |
| USDC on Solana | Different from USDC on Ethereum! |

### Common Mistake: Cross-Network Confusion

```
❌ WRONG: USDC on Ethereum → SOL on Solana (Jupiter cannot do this)
✅ RIGHT: USDC on Solana → SOL on Solana (Jupiter handles this)
```

If you transfer USDC from Coinbase to your Solana wallet address via Ethereum network, it goes to a different blockchain entirely. The funds will not appear in your Solana wallet.

### How to Get Tokens on Solana

1. **Direct from exchange** - Withdraw SOL or USDC (SPL) directly to Solana address
2. **Bridge from Ethereum** - Use Portal/Wormhole bridge (has fees)
3. **Swap on Solana** - Once you have any Solana asset, swap to others via Jupiter

---

## Future Enhancement: Cross-Chain Swaps

Trust Wallet supports **cross-chain swaps** that could enable trading tokens across networks:

### Capabilities (Not Yet Implemented)

- Swap ETH on Ethereum → SOL on Solana
- Swap USDC on Base → BONK on Solana
- Automatic bridging behind the scenes

### Implementation Notes

```bash
# Trust Wallet cross-chain swap (future)
twak swap execute --from-chain ethereum --from SOL --to-chain solana --to USDC --amount 1
```

### When to Implement

- When trading strategy requires tokens on different chains
- When gas costs make single-chain arbitrage uneconomical
- When new opportunities emerge on chains other than Solana

---

## Integration Steps: Test Script → Live Trading

### Current State (Completed)

The `probe_trustwallet_swap.py` script demonstrates the full swap flow:

1. ✅ Load wallet from recovery phrase (BIP44 derivation)
2. ✅ Check SOL and token balances via RPC
3. ✅ Get swap quote from Jupiter
4. ✅ Sign transaction with local keypair
5. ✅ Submit transaction to Solana mainnet
6. ✅ Verify updated balances

### Integration into correlation_tracker.py Live Mode

**Step 1: Add wallet initialization to startup**

```python
# In correlation_tracker.py
from dex.local_wallet import LocalWallet
from dex.jupiterutil import JupiterClient

class CorrelationTracker:
    def __init__(self, ...):
        # Existing init...
        
        # Add for live trading
        self._wallet: Optional[LocalWallet] = None
        self._jupiter: Optional[JupiterClient] = None
    
    def _init_live_trading(self, mnemonic: str):
        """Initialize wallet for live trading."""
        self._wallet = LocalWallet(mnemonic)
        if not self._wallet.is_loaded():
            raise RuntimeError("Failed to load wallet")
        
        self._jupiter = JupiterClient()
        print(f"[LIVE] Wallet: {self._wallet.get_address()}")
```

**Step 2: Add execute_trade method**

```python
def execute_swap(self, from_token: str, to_token: str, amount: float) -> Optional[str]:
    """Execute a swap on Jupiter.
    
    Args:
        from_token: Token symbol to sell (e.g., 'SOL', 'USDC')
        to_token: Token symbol to buy
        amount: Amount in token units
    
    Returns:
        Transaction hash or None on failure
    """
    import base64
    import requests
    from solders.transaction import VersionedTransaction
    
    # Get mint addresses
    from_mint = get_mint_with_fallback(from_token)
    to_mint = get_mint_with_fallback(to_token)
    
    if not from_mint or not to_mint:
        print(f"[LIVE] Unknown token: {from_token} or {to_token}")
        return None
    
    # Convert amount to smallest units
    decimals = 9 if from_token == 'SOL' else 6  # SOL=9, most SPL=6
    amount_units = int(amount * (10 ** decimals))
    
    # Get quote
    quote = self._jupiter.get_quote(from_mint, to_mint, amount_units)
    if not quote:
        print(f"[LIVE] No quote for {from_token} → {to_token}")
        return None
    
    # Get swap transaction
    address = self._wallet.get_address()
    swap_tx_b64 = self._jupiter.get_swap_transaction(quote, address)
    if not swap_tx_b64:
        print(f"[LIVE] Failed to get swap transaction")
        return None
    
    # Sign transaction
    tx_bytes = base64.b64decode(swap_tx_b64)
    tx = VersionedTransaction.from_bytes(tx_bytes)
    keypair = self._wallet.get_keypair()
    signed_tx = VersionedTransaction(tx.message, [keypair])
    signed_tx_b64 = base64.b64encode(bytes(signed_tx)).decode('utf-8')
    
    # Submit transaction
    rpc_url = "https://api.mainnet-beta.solana.com"
    resp = requests.post(rpc_url, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [signed_tx_b64, {"encoding": "base64", "skipPreflight": False}]
    }, timeout=30)
    
    result = resp.json()
    if "error" in result:
        print(f"[LIVE] RPC error: {result['error']}")
        return None
    
    tx_hash = result.get("result", "")
    print(f"[LIVE] Swap submitted: {tx_hash}")
    return tx_hash
```

**Step 3: Add to trading decision flow**

```python
def _execute_recommendation(self, recommendation: Dict):
    """Execute a trading recommendation."""
    action = recommendation.get("action")  # "buy" or "sell"
    symbol = recommendation.get("symbol")
    amount_usd = recommendation.get("amount_usd", 10.0)
    
    if action == "buy":
        # Swap USDC → token
        amount_usdc = amount_usd
        tx_hash = self.execute_swap("USDC", symbol, amount_usdc)
    elif action == "sell":
        # Swap token → USDC
        # Need to calculate token amount from USD value
        price = self._jupiter.get_price(symbol)
        if price:
            amount_tokens = amount_usd / price[0]
            tx_hash = self.execute_swap(symbol, "USDC", amount_tokens)
    
    # Log trade
    if tx_hash:
        self._log_trade(symbol, action, amount_usd, tx_hash)
```

**Step 4: Add command-line option**

```python
# In argument parser
parser.add_argument('--live', action='store_true', help='Enable live trading')
parser.add_argument('--wallet-phrase', type=str, help='Wallet recovery phrase (or set WALLET_MNEMONIC env)')

# In main()
if args.live:
    mnemonic = args.wallet_phrase or os.environ.get("WALLET_MNEMONIC")
    if not mnemonic:
        print("ERROR: --wallet-phrase or WALLET_MNEMONIC required for live trading")
        sys.exit(1)
    tracker._init_live_trading(mnemonic)
```

---

## Live Trading Scenario Coverage

### Scenarios Covered ✅

| Scenario | Status | Notes |
|----------|--------|-------|
| Load wallet from recovery phrase | ✅ Complete | BIP44 derivation working |
| Check SOL balance | ✅ Complete | Direct RPC call |
| Check SPL token balance | ✅ Complete | getTokenAccountsByOwner RPC |
| Get swap quote | ✅ Complete | Jupiter quote API |
| Sign transaction locally | ✅ Complete | solders VersionedTransaction |
| Submit transaction | ✅ Complete | sendTransaction RPC |
| Verify transaction result | ✅ Complete | Balance re-check |

### Scenarios Not Yet Implemented ⚠️

| Scenario | Priority | Notes |
|----------|----------|-------|
| ~~Transaction confirmation monitoring~~ | ✅ Done | Polls `getTransaction` with 30s timeout |
| ~~Failed transaction retry~~ | Deferred | Excluded from MVP per user decision |
| ~~Slippage protection~~ | ✅ Done | Tracks actual vs quoted, see Slippage Tracking |
| ~~Gas estimation~~ | ✅ Done | `_check_sol_balance()` verifies SOL before trades |
| ~~Position size limits~~ | Deferred | Liquidity-based limits excluded from MVP |
| ~~Trade history logging~~ | ✅ Done | See Trade History Logging section |
| ~~Error alerting~~ | ✅ Done | `_alert_trade_failure()` logs to `trade_errors.json` |
| ~~Rate limiting~~ | Deferred | Excluded from MVP per user decision |
| Multi-token portfolio tracking | Low | Track all held tokens |

---

## Trade History Logging

### Implementation Status: ✅ Complete

Trade history logging is implemented in `leading_indicator_tester.py` via the `LiveTrader` class.

### Trade Record Structure

Each trade is stored with full cost basis information:

```python
@dataclass
class LiveTrade:
    id: str                    # Unique ID: lt_YYYYMMDD_HHMMSS_NNN
    timestamp: str             # ISO 8601 UTC timestamp
    type: str = "live"         # "live" or "paper"
    pair: str = ""             # "BTC:BONK" format
    action: str = ""           # "BUY" or "SELL"
    follower: str = ""         # Token traded (e.g., "BONK")
    
    # Cost basis fields
    input_token: str = ""      # What we spent (USDC for BUY, token for SELL)
    output_token: str = ""     # What we received (token for BUY, USDC for SELL)
    input_amount: float = 0.0  # Amount spent
    output_amount: float = 0.0 # Amount received
    price_usd: float = 0.0     # Price per token at execution
    
    slippage_bps: int = 100    # Slippage tolerance used
    trigger: Dict = {}         # Why we traded (leader price change)
    timing: Dict = {}          # When (signal time, execution time, lag)
    transaction: Dict = {}     # Blockchain data (signature, status, price_impact)
    outcome: Optional[Dict]    # Post-trade analysis (filled later)
```

### Storage Format

Trades are saved to JSON files in `./live_trades/`:

```
live_trades/
├── BTC_BONK_live.json
├── ETH_PEPE_live.json
└── SOL_WIF_live.json
```

Each file contains:

```json
{
  "pair": "BTC:BONK",
  "wallet": "FU8PNVhh...g22t",
  "trades": [ /* array of LiveTrade records */ ],
  "summary": {
    "total_trades": 10,
    "buys": 6,
    "sells": 4,
    "total_bought_usd": 600.00,
    "total_sold_usd": 450.00,
    "total_tokens_bought": 1500000.0,
    "total_tokens_sold": 1000000.0,
    "avg_buy_price_usd": 0.0004,
    "avg_sell_price_usd": 0.00045,
    "realized_pnl_usd": 50.00,
    "tokens_held": 500000.0,
    "unrealized_cost_basis_usd": 200.00,
    "net_cash_flow_usd": -150.00
  }
}
```

### Cost Basis Calculation

The summary uses **average cost basis** method:

1. **avg_buy_price** = total_bought_usd / total_tokens_bought
2. **avg_sell_price** = total_sold_usd / total_tokens_sold
3. **realized_pnl** = min(tokens_bought, tokens_sold) × (avg_sell - avg_buy)
4. **tokens_held** = tokens_bought - tokens_sold
5. **unrealized_cost_basis** = tokens_held × avg_buy_price

### Persistence Across Restarts

The `LiveTrader` class loads existing trades on initialization:

```python
def _load_existing_trades(self):
    """Load existing trades from file if present."""
    output_file = self.output_path / f"{leader}_{follower}_live.json"
    
    if output_file.exists():
        with open(output_file, 'r') as f:
            data = json.load(f)
        # Reconstruct LiveTrade objects...
```

This ensures:
- Trade history persists across bot restarts
- Trade counter continues from last ID
- Summary stats accumulate correctly

### Transaction Verification

Each trade record includes blockchain verification data:

```python
transaction={
    "signature": "5Kz7...",      # Solana tx signature
    "status": "confirmed",       # Transaction status
    "price_impact_pct": 0.05,   # Actual price impact
}
```

The signature can be used to:
- Verify trade on Solscan: `https://solscan.io/tx/{signature}`
- Audit trade history
- Reconcile with wallet balance

### Slippage Tracking

#### Implementation Status: ✅ Complete

After each trade, the system polls for transaction confirmation and calculates actual slippage by comparing quoted vs actual output amounts.

#### How It Works

1. **Submit transaction** → Get signature
2. **Poll `getTransaction`** → Wait for confirmation (up to 30s)
3. **Parse token balance changes** → Extract actual output amount
4. **Calculate slippage**:
   ```
   slippage_bps = (quoted_output - actual_output) / quoted_output × 10000
   ```

#### Trade Record Fields

```python
@dataclass
class LiveTrade:
    # ... existing fields ...
    output_amount: float = 0.0           # Quoted output (from Jupiter)
    output_amount_actual: Optional[float] = None  # Actual output (post-confirmation)
    slippage_bps: int = 100              # Tolerance setting
    slippage_actual_bps: Optional[int] = None     # Actual slippage measured
```

#### Summary Statistics

```json
{
  "slippage_tracked_trades": 15,
  "avg_slippage_bps": 12.5,
  "max_slippage_bps": 45,
  "min_slippage_bps": -8,
  "trades_exceeded_tolerance": 0,
  "tx_confirmed": 15,
  "tx_failed": 0,
  "tx_unconfirmed": 0
}
```

| Field | Meaning |
|-------|---------|
| `avg_slippage_bps` | Average slippage across all trades (12.5 = 0.125%) |
| `max_slippage_bps` | Worst case slippage |
| `min_slippage_bps` | Best case (negative = got more than quoted) |
| `trades_exceeded_tolerance` | Trades where actual > tolerance setting |

#### Console Output

```
[LIVE] Waiting for confirmation...
[LIVE] Slippage: 0.15% (quoted: 1500.000000, actual: 1497.750000)
```

Or for positive slippage (got more than expected):
```
[LIVE] Positive slippage: 0.08% (got more than quoted)
```

### Security Considerations

| Item | Status | Recommendation |
|------|--------|----------------|
| Mnemonic storage | ⚠️ Env var | Consider encrypted file or secrets manager |
| RPC endpoint | ⚠️ Public | See Private RPC section below |
| Max trade size | ✅ Done | `--max-trade-usd` argument |
| Wallet isolation | ✅ Reminder | Warning displayed at startup |

### Private RPC (Future Enhancement)

The current implementation uses the public Solana RPC endpoint (`https://api.mainnet-beta.solana.com`), which has limitations:

| Issue | Impact | Solution |
|-------|--------|----------|
| Rate limiting | May throttle during high activity | Private RPC |
| MEV/sandwich attacks | Front-running risk on swaps | Private RPC with MEV protection |
| Reliability | Public endpoint can be congested | Dedicated endpoint |

**Recommended providers for production:**

| Provider | Features | Notes |
|----------|----------|-------|
| [Helius](https://helius.dev) | Fast, MEV protection available | Popular for Solana DeFi |
| [QuickNode](https://quicknode.com) | Multi-chain, reliable | Good documentation |
| [Triton](https://triton.one) | High performance | Used by major protocols |

**Implementation (when needed):**

```python
# In LiveTrader or via environment variable
RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# For MEV protection, some providers offer private transaction submission
# that bypasses the public mempool
```

This is not implemented in MVP but documented for future scaling.

---

## Open Questions

### Strategy & Scope

1. ~~**Which chains to support first?**~~ ✅ **Resolved: Solana**
   - Solana chosen for MVP (meme coin ecosystem, low fees)
   - Jupiter aggregator integrated

2. ~~**What types of trades?**~~ ✅ **Resolved: Simple swaps**
   - Simple market swaps implemented
   - Limit orders and LP deferred

3. ~~**Trade size limits?**~~ ✅ **Resolved: --max-trade-usd**
   - `--max-trade-usd` argument enforces maximum
   - No minimum (Solana fees negligible)

4. ~~**How does this interact with existing CEX trading?**~~ ✅ **Resolved: Separate mode**
   - `--trading-mode live` flag for DEX
   - Paper mode remains default

### Security

5. **How to store private keys?** ⚠️ **Acceptable for MVP**
   - Using mnemonic via environment variable
   - Acceptable for small test amounts
   - Consider secrets manager for production

6. **What happens if private key is compromised?** ⚠️ **Deferred**
   - Document incident response when scaling
   - Use `--max-trade-usd` to limit exposure

7. ~~**Should we use a separate wallet for bot trading?**~~ ✅ **Resolved: Recommendation**
   - Warning displayed at live mode startup
   - User responsibility to follow recommendation

### Operational

8. ~~**How to handle gas price spikes?**~~ ✅ **N/A for Solana**
   - Solana fees are fixed (~0.000005 SOL)
   - Not a concern for current implementation

9. **How to handle failed transactions?** ⚠️ **MVP: No retry**
   - Transaction status tracked (confirmed/failed/unconfirmed)
   - Retry logic deferred to future enhancement

10. ~~**How to track DEX trades in history?**~~ ✅ **Resolved: Full logging**
    - `LiveTrade` records with tx signature
    - Cost basis and slippage tracking
    - JSON files in `./live_trades/`

### Economic

11. ~~**What is acceptable cost per trade?**~~ ✅ **N/A for Solana**
    - Solana fees ~$0.001 per trade
    - No minimum trade size needed

12. **How to account for MEV/sandwich attacks?** ⚠️ **MVP: Accept risk**
    - Using public RPC (vulnerable)
    - Private RPC documented for future (see Private RPC section)
    - Slippage tracking helps detect issues

---

## Recommended Approach

### Phase 1: Base Chain via Coinbase Onchain API
**Rationale**: Minimal new dependencies, same credentials, low gas costs

1. Use existing CDP credentials
2. Create/manage wallet via Coinbase Onchain API
3. Integrate with Uniswap on Base for swaps
4. Start with simple market swaps only

### Phase 2: Add Solana via Jupiter
**Rationale**: Access to meme coin ecosystem, very low fees

1. Add Solana wallet management
2. Integrate Jupiter aggregator API
3. Handle SPL token specifics

### Phase 3: Multi-chain Aggregation
**Rationale**: Best execution across chains

1. Add 1inch or similar aggregator
2. Automatic chain selection based on liquidity/cost
3. Cross-chain bridging (if needed)

---

## Alternative Approaches

### A: CEX-Only Strategy
**Don't add DEX support.** Focus on improving CEX trading.
- **Pros**: Simpler, no gas costs, no key management
- **Cons**: Limited to CEX-listed coins, miss early opportunities
- **When to choose**: If primary goal is established coins, not meme coins

### B: Hybrid CEX/DEX via Single Provider
**Use a service that bridges CEX and DEX** (e.g., Matcha, Paraswap Pro)
- **Pros**: Single API for both
- **Cons**: Less control, potential vendor lock-in
- **When to choose**: Speed to market is priority

### C: Copy Trading / Signal Following
**Don't execute DEX trades directly.** Generate signals, user executes manually or via another tool.
- **Pros**: No key management, no gas handling
- **Cons**: Slower execution, user friction
- **When to choose**: Risk-averse approach, or regulatory concerns

### D: Paper Trading / Simulation Only
**Add DEX analysis without actual trading**
- **Pros**: Learn DEX mechanics without risk
- **Cons**: No real trading capability
- **When to choose**: Research/learning phase

---

## Next Steps

1. **Answer open questions** (especially #1, #5, #11)
2. **Prototype Phase 1** on Base testnet
3. **Establish security practices** for key management
4. **Define success metrics** (trade success rate, cost per trade)

---

## Known Limitations & Security Considerations

### Token Address Validation (MITIGATED)

**Status:** Runtime validation implemented in preflight.

**Issue:** Token mint addresses in `dex/token_cache.py` are hardcoded and could be:
- **Stale** — Token migrated to a new contract address
- **Incorrect** — Typo or wrong token entirely
- **Malicious** — If the file is modified by an attacker

**Current State (After Mitigation):**
- Preflight validates that a mint address EXISTS in the cache
- Preflight attempts a Jupiter quote to verify token is TRADEABLE on-chain
- If quote fails, preflight fails fast with clear error message
- Invalid/stale mint addresses are caught before any trading attempt

**Proposed Mitigations:**

1. **Runtime validation** — Query Jupiter API to confirm the mint address is tradeable before preflight passes
2. **Checksum/verification** — Store token metadata (name, symbol, decimals) and verify against on-chain data
3. **Dynamic lookup** — Fetch mint addresses from Jupiter's verified token list API instead of hardcoding

**Workaround (Manual):**
Before trading a new token, manually verify the mint address:
- Check on [Solscan](https://solscan.io)
- Verify on [Jupiter](https://jup.ag) token search
- Compare against official project documentation

---

## References

- [Coinbase Developer Platform](https://docs.cdp.coinbase.com/)
- [Uniswap SDK](https://docs.uniswap.org/sdk/v3/overview)
- [Jupiter API Docs](https://station.jup.ag/docs/apis/swap-api)
- [1inch API](https://portal.1inch.dev/)
- [Base Chain](https://docs.base.org/)
