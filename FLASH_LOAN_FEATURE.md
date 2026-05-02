# Flash Loan Arbitrage Feature

## Overview

This feature enables **atomic arbitrage** using flash loans, where the entire arbitrage cycle—borrow, trade, repay—executes in a single transaction. If any step fails, the entire transaction reverts, meaning no capital is at risk and no loan is ever actually taken.

### Why Flash Loans?

| Aspect | Current Approach | Flash Loan Approach |
|--------|------------------|---------------------|
| Capital required | Full trade amount | Zero (borrowed) |
| Risk if trade fails | Execution risk | None (atomic revert) |
| Transaction count | 2+ (buy, sell) | 1 (atomic) |
| MEV exposure | High (multiple txns) | Lower (single txn) |
| Profit capture | Delayed | Instant |

---

## Core Concept

### Flash Loan Mechanics

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SINGLE ATOMIC TRANSACTION                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. BORROW                                                              │
│     ┌──────────────┐                                                    │
│     │ Flash Loan   │──── Borrow $X USDC ────►                          │
│     │ Provider     │                                                    │
│     └──────────────┘                                                    │
│           │                                                             │
│           ▼                                                             │
│  2. EXECUTE ARBITRAGE                                                   │
│     ┌──────────────┐      ┌──────────────┐                             │
│     │ Buy JLP at   │ ───► │ Sell JLP at  │                             │
│     │ discount     │      │ market price │                             │
│     └──────────────┘      └──────────────┘                             │
│           │                      │                                      │
│           └──────────┬───────────┘                                      │
│                      ▼                                                  │
│  3. REPAY + PROFIT                                                      │
│     ┌──────────────┐                                                    │
│     │ Flash Loan   │◄─── Repay $X + fee, keep profit ────              │
│     │ Provider     │                                                    │
│     └──────────────┘                                                    │
│                                                                         │
│  ✓ SUCCESS: Profit transferred to wallet                               │
│  ✗ FAILURE: Entire transaction reverts, no loan taken                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Atomicity Guarantee

The key property of flash loans is **atomicity**:

```
IF repayment_amount >= borrowed_amount + fee:
    Transaction succeeds → Profit captured
ELSE:
    Transaction reverts → State unchanged, no loss
```

This means:
- **No liquidation risk**: Loan must be repaid in same transaction
- **No collateral required**: Borrow any available amount
- **Risk-free execution**: Failed arbitrage = no cost (except gas)

---

## True Arbitrage vs Spread Trading

### The Problem with "Slow Motion" Arbitrage

The current `lp_arbitrage.py` implementation is **NOT true arbitrage**. It executes one trade per cycle:

```
┌─────────────────────────────────────────────────────────────────┐
│          CURRENT IMPLEMENTATION (SPREAD TRADING)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Cycle 1: Spread = -2% (discount)                              │
│    → BUY JLP via Jupiter swap                                  │
│    → Hope price reverts to NAV                                 │
│                                                                 │
│  Cycle 2...N: Wait...                                          │
│    → HOLD (exposed to market risk)                             │
│    → BTC/ETH/SOL could crash                                   │
│                                                                 │
│  Cycle M: Spread = +3% (premium)                               │
│    → SELL JLP via Jupiter swap                                 │
│    → Maybe capture profit... maybe not                         │
│                                                                 │
│  PROBLEMS:                                                      │
│  ✗ Hours/days between buy and sell                             │
│  ✗ Directional exposure to underlying assets                   │
│  ✗ NOT risk-free                                               │
│  ✗ NOT arbitrage                                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### True Atomic Arbitrage

True arbitrage captures the spread **instantly** in a single transaction:

```
┌─────────────────────────────────────────────────────────────────┐
│              TRUE ATOMIC ARBITRAGE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SAME TRANSACTION:                                              │
│    1. Acquire asset at Price A                                 │
│    2. Dispose asset at Price B                                 │
│    3. Profit = |Price B - Price A| - fees                      │
│                                                                 │
│  KEY INSIGHT:                                                   │
│  For JLP, there are TWO different prices:                      │
│    • NAV Price: Pool AUM / JLP Supply (mint/redeem price)      │
│    • Market Price: DEX swap price (Jupiter liquidity)          │
│                                                                 │
│  Arbitrage exploits the GAP between these prices.              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Two Arbitrage Paths

#### Path 1: Discount Arbitrage (Market < NAV)

When JLP trades at a **discount** on the market:

```
┌─────────────────────────────────────────────────────────────────┐
│          DISCOUNT ARBITRAGE (Market Price < NAV)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Condition: Market = $3.70, NAV = $3.80 (2.6% discount)        │
│                                                                 │
│  ATOMIC TRANSACTION:                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Flash borrow $1000 USDC                              │   │
│  │                      ↓                                   │   │
│  │ 2. Buy JLP on market (Jupiter swap)                     │   │
│  │    $1000 → 270.27 JLP @ $3.70                           │   │
│  │                      ↓                                   │   │
│  │ 3. Redeem JLP at NAV (Jupiter Perps removeLiquidity)    │   │
│  │    270.27 JLP → $1027.03 @ $3.80 NAV                    │   │
│  │                      ↓                                   │   │
│  │ 4. Repay flash loan + fee                               │   │
│  │    $1000 + $0.90 (Kamino 0.09%) = $1000.90              │   │
│  │                      ↓                                   │   │
│  │ 5. PROFIT: $1027.03 - $1000.90 = $26.13                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Requirements:                                                  │
│  • Jupiter Perps must allow redemption at NAV                  │
│  • Sufficient pool liquidity for redemption                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Path 2: Premium Arbitrage (Market > NAV)

When JLP trades at a **premium** on the market:

```
┌─────────────────────────────────────────────────────────────────┐
│          PREMIUM ARBITRAGE (Market Price > NAV)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Condition: Market = $3.90, NAV = $3.80 (2.6% premium)         │
│                                                                 │
│  ATOMIC TRANSACTION:                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Flash borrow $1000 USDC                              │   │
│  │                      ↓                                   │   │
│  │ 2. Mint JLP at NAV (Jupiter Perps addLiquidity)         │   │
│  │    $1000 → 263.16 JLP @ $3.80 NAV                       │   │
│  │                      ↓                                   │   │
│  │ 3. Sell JLP on market (Jupiter swap)                    │   │
│  │    263.16 JLP → $1026.32 @ $3.90                        │   │
│  │                      ↓                                   │   │
│  │ 4. Repay flash loan + fee                               │   │
│  │    $1000 + $0.90 (Kamino 0.09%) = $1000.90              │   │
│  │                      ↓                                   │   │
│  │ 5. PROFIT: $1026.32 - $1000.90 = $25.42                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Requirements:                                                  │
│  • Jupiter Perps must allow minting at NAV                     │
│  • Pool not at AUM cap (minting disabled when capped)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Jupiter Perpetuals Instructions

The key to true arbitrage is using **Jupiter Perpetuals program** directly, not Jupiter AMM swaps:

| Operation | Jupiter Perps Instruction | Price Basis |
|-----------|--------------------------|-------------|
| Mint JLP | `addLiquidity` | NAV (AUM/Supply) |
| Redeem JLP | `removeLiquidity` | NAV (AUM/Supply) |
| Swap (buy) | Jupiter Aggregator | Market (AMM) |
| Swap (sell) | Jupiter Aggregator | Market (AMM) |

```rust
// Jupiter Perpetuals Program ID
const JUPITER_PERPS_PROGRAM: Pubkey = pubkey!("PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu");

// Add liquidity (mint JLP at NAV)
pub fn add_liquidity(
    pool: Pubkey,
    custody: Pubkey,        // Which asset to deposit (USDC, SOL, etc.)
    amount_in: u64,         // Amount of collateral
    min_lp_amount: u64,     // Minimum JLP to receive
) -> Instruction;

// Remove liquidity (redeem JLP at NAV)
pub fn remove_liquidity(
    pool: Pubkey,
    custody: Pubkey,        // Which asset to receive
    lp_amount: u64,         // Amount of JLP to burn
    min_amount_out: u64,    // Minimum collateral to receive
) -> Instruction;
```

### Comparison Summary

| Aspect | Current "Arbitrage" | True Atomic Arbitrage |
|--------|--------------------|-----------------------|
| Transactions | 2+ (separate cycles) | 1 (atomic) |
| Time between trades | Hours to days | Milliseconds |
| Price risk | High (market can move) | Zero (same block) |
| Capital at risk | Full position | Zero (flash loan) |
| Profit certainty | Uncertain | Guaranteed or reverts |
| Complexity | Low (Python only) | High (smart contract) |

---

## Architecture

### Option A: Solana Program (Native)

Deploy a custom Solana program that orchestrates the flash loan and arbitrage.

```
┌─────────────────────────────────────────────────────────────────┐
│                     SOLANA PROGRAM                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐           │
│  │ Flash Loan  │   │  Jupiter    │   │  Jupiter    │           │
│  │ Instruction │──►│  Swap CPI   │──►│  Swap CPI   │           │
│  │  (Borrow)   │   │  (Buy JLP)  │   │  (Sell JLP) │           │
│  └─────────────┘   └─────────────┘   └─────────────┘           │
│         │                                    │                  │
│         │          ┌─────────────┐          │                  │
│         └─────────►│   Repay +   │◄─────────┘                  │
│                    │   Profit    │                              │
│                    └─────────────┘                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Pros:
  + Native Solana, lowest latency
  + Full control over execution
  + Can optimize for gas

Cons:
  - Complex Rust development
  - Must handle CPI to multiple programs
  - Deployment and upgrade complexity
```

### Option B: Solana Program with Anchor Framework

Use Anchor for safer, more maintainable Solana program development.

```rust
// Pseudocode - Anchor program structure
#[program]
pub mod flash_arbitrage {
    pub fn execute_arbitrage(
        ctx: Context<ExecuteArbitrage>,
        borrow_amount: u64,
        min_profit: u64,
    ) -> Result<()> {
        // 1. Flash borrow from lending protocol
        flash_loan::borrow(ctx.accounts.lending_pool, borrow_amount)?;
        
        // 2. Buy JLP at discount (CPI to Jupiter)
        let jlp_received = jupiter::swap(
            ctx.accounts.jupiter_program,
            ctx.accounts.usdc_account,
            ctx.accounts.jlp_account,
            borrow_amount,
        )?;
        
        // 3. Sell JLP at market price (CPI to Jupiter)
        let usdc_received = jupiter::swap(
            ctx.accounts.jupiter_program,
            ctx.accounts.jlp_account,
            ctx.accounts.usdc_account,
            jlp_received,
        )?;
        
        // 4. Verify profit and repay
        let repay_amount = borrow_amount + flash_loan_fee;
        require!(usdc_received >= repay_amount + min_profit, ErrorCode::InsufficientProfit);
        
        flash_loan::repay(ctx.accounts.lending_pool, repay_amount)?;
        
        // 5. Transfer profit to user
        let profit = usdc_received - repay_amount;
        transfer_to_user(ctx.accounts.user_wallet, profit)?;
        
        Ok(())
    }
}
```

```
Pros:
  + Safer than raw Rust (Anchor checks)
  + Better tooling and testing
  + Active community support

Cons:
  - Anchor runtime overhead
  - Still requires Rust knowledge
  - IDL management
```

### Option C: Jito Bundles (No Smart Contract)

Use Jito bundles to submit multiple transactions atomically without deploying a program.

```
┌─────────────────────────────────────────────────────────────────┐
│                      JITO BUNDLE                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Transaction 1: Borrow from lending protocol                   │
│  Transaction 2: Buy JLP via Jupiter                            │
│  Transaction 3: Sell JLP via Jupiter                           │
│  Transaction 4: Repay loan + tip to Jito                       │
│                                                                 │
│  Atomicity: Bundle succeeds or fails as a unit                 │
│  Tip: Pay Jito validators for priority inclusion               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Pros:
  + No smart contract deployment
  + Python/TypeScript client only
  + Quick iteration

Cons:
  - Not true atomic (sequential txns)
  - Jito tip costs
  - Bundle may not land in same slot
  - Less control over execution
```

### Option D: Cross-Chain Flash Loan (EVM + Bridge)

Use established EVM flash loan protocols (Aave, dYdX) and bridge to Solana.

```
┌─────────────────────────────────────────────────────────────────┐
│  ETHEREUM/ARBITRUM                    │  SOLANA                 │
├───────────────────────────────────────┼─────────────────────────┤
│                                       │                         │
│  1. Aave Flash Loan (USDC)           │                         │
│          │                            │                         │
│          ▼                            │                         │
│  2. Bridge USDC via Wormhole ────────►│  3. Receive USDC       │
│                                       │          │              │
│                                       │          ▼              │
│                                       │  4. Buy JLP            │
│                                       │          │              │
│                                       │          ▼              │
│                                       │  5. Sell JLP           │
│                                       │          │              │
│  7. Repay Aave  ◄────────────────────│  6. Bridge back        │
│                                       │                         │
└───────────────────────────────────────┴─────────────────────────┘

Pros:
  + Mature flash loan infrastructure
  + Larger liquidity pools
  + Battle-tested contracts

Cons:
  - NOT ATOMIC (bridge latency breaks atomicity)
  - Bridge fees and risks
  - Complex multi-chain coordination
  - Defeats flash loan purpose
```

**Note**: Option D is included for completeness but **violates atomicity** due to bridge latency. Not recommended for true flash loan arbitrage.

---

## Solana Flash Loan Providers

### Available Protocols

| Protocol | Flash Loan Support | Max Amount | Fee | Notes |
|----------|-------------------|------------|-----|-------|
| **Solend** | Yes | Pool liquidity | 0.3% | Most established |
| **Marginfi** | Yes | Pool liquidity | Variable | Growing TVL |
| **Kamino** | Yes | Pool liquidity | 0.09% | Lower fees |
| **Port Finance** | Limited | Lower | 0.3% | Smaller pools |
| **Mango Markets** | No native | N/A | N/A | Would need wrapper |

### Solend Flash Loan Interface

```rust
// Solend flash loan instruction
pub struct FlashLoanInstruction {
    pub amount: u64,
    pub reserve: Pubkey,          // USDC reserve
    pub destination: Pubkey,      // Borrower's token account
    pub reserve_liquidity: Pubkey,
    pub lending_market: Pubkey,
}

// Fee calculation
flash_loan_fee = amount * 0.003  // 0.3% = 30 basis points
```

### Kamino Flash Loan Interface

```rust
// Kamino flash loan (lower fees)
pub struct KaminoFlashLoan {
    pub amount: u64,
    pub reserve: Pubkey,
    pub fee_bps: u16,  // 9 bps = 0.09%
}
```

---

## Smart Contract Design

### Program Structure

```
flash_arbitrage/
├── programs/
│   └── flash_arbitrage/
│       ├── src/
│       │   ├── lib.rs              # Entry point
│       │   ├── instructions/
│       │   │   ├── mod.rs
│       │   │   ├── execute_arb.rs  # Main arbitrage instruction
│       │   │   └── admin.rs        # Admin functions
│       │   ├── state/
│       │   │   ├── mod.rs
│       │   │   └── config.rs       # Program config PDA
│       │   ├── errors.rs           # Custom errors
│       │   └── utils.rs            # Helpers
│       └── Cargo.toml
├── tests/
│   └── flash_arbitrage.ts          # Integration tests
├── app/
│   └── client.py                   # Python client
└── Anchor.toml
```

### Account Structure

```rust
#[account]
pub struct ArbConfig {
    pub authority: Pubkey,           // Owner/admin
    pub min_profit_bps: u16,         // Minimum profit threshold (basis points)
    pub max_borrow: u64,             // Maximum borrow amount
    pub enabled: bool,               // Kill switch
    pub total_profit: u64,           // Cumulative profit tracker
    pub total_arbs: u64,             // Total successful arbitrages
    pub bump: u8,                    // PDA bump
}

#[derive(Accounts)]
pub struct ExecuteArbitrage<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,
    
    #[account(
        seeds = [b"config"],
        bump = config.bump,
        constraint = config.enabled @ ErrorCode::ArbDisabled
    )]
    pub config: Account<'info, ArbConfig>,
    
    // Flash loan accounts
    #[account(mut)]
    pub lending_pool: AccountInfo<'info>,
    #[account(mut)]
    pub reserve_liquidity: AccountInfo<'info>,
    
    // Token accounts
    #[account(mut)]
    pub usdc_account: Account<'info, TokenAccount>,
    #[account(mut)]
    pub jlp_account: Account<'info, TokenAccount>,
    
    // Programs
    pub lending_program: Program<'info, SolendProgram>,
    pub jupiter_program: AccountInfo<'info>,
    pub token_program: Program<'info, Token>,
}
```

### Core Logic

```rust
pub fn execute_arbitrage(
    ctx: Context<ExecuteArbitrage>,
    borrow_amount: u64,
    jupiter_buy_data: Vec<u8>,   // Serialized Jupiter swap instruction
    jupiter_sell_data: Vec<u8>,  // Serialized Jupiter swap instruction
) -> Result<()> {
    let config = &ctx.accounts.config;
    
    // Validate
    require!(borrow_amount <= config.max_borrow, ErrorCode::ExceedsMaxBorrow);
    
    let initial_balance = ctx.accounts.usdc_account.amount;
    
    // Step 1: Flash borrow
    solend_cpi::flash_borrow(
        ctx.accounts.lending_program.to_account_info(),
        ctx.accounts.lending_pool.to_account_info(),
        ctx.accounts.reserve_liquidity.to_account_info(),
        ctx.accounts.usdc_account.to_account_info(),
        borrow_amount,
    )?;
    
    // Step 2: Buy JLP (USDC → JLP)
    jupiter_cpi::swap(
        ctx.accounts.jupiter_program.to_account_info(),
        jupiter_buy_data,
    )?;
    
    // Step 3: Sell JLP (JLP → USDC)
    jupiter_cpi::swap(
        ctx.accounts.jupiter_program.to_account_info(),
        jupiter_sell_data,
    )?;
    
    // Step 4: Calculate profit and repay
    ctx.accounts.usdc_account.reload()?;
    let final_balance = ctx.accounts.usdc_account.amount;
    
    let flash_fee = borrow_amount * 30 / 10000;  // 0.3%
    let repay_amount = borrow_amount + flash_fee;
    
    require!(
        final_balance >= initial_balance + repay_amount,
        ErrorCode::InsufficientFunds
    );
    
    let profit = final_balance - initial_balance - repay_amount;
    let min_profit = borrow_amount * config.min_profit_bps as u64 / 10000;
    
    require!(profit >= min_profit, ErrorCode::BelowMinProfit);
    
    // Step 5: Repay flash loan
    solend_cpi::flash_repay(
        ctx.accounts.lending_program.to_account_info(),
        ctx.accounts.lending_pool.to_account_info(),
        ctx.accounts.usdc_account.to_account_info(),
        repay_amount,
    )?;
    
    // Step 6: Update stats
    let config = &mut ctx.accounts.config;
    config.total_profit += profit;
    config.total_arbs += 1;
    
    emit!(ArbitrageExecuted {
        timestamp: Clock::get()?.unix_timestamp,
        borrow_amount,
        profit,
        flash_fee,
    });
    
    Ok(())
}
```

---

## Python Client Integration

### Client Architecture

```python
# flash_client.py

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient

class FlashArbitrageClient:
    """Client for interacting with the flash arbitrage program."""
    
    PROGRAM_ID = Pubkey.from_string("FLASH_ARB_PROGRAM_ID")
    
    def __init__(self, rpc_url: str, wallet: Keypair):
        self.client = AsyncClient(rpc_url)
        self.wallet = wallet
    
    async def check_opportunity(
        self,
        virtual_price: float,
        market_price: float,
        trade_amount_usd: float,
    ) -> dict:
        """Check if flash arbitrage is profitable."""
        
        spread = (market_price - virtual_price) / virtual_price
        
        # Cost breakdown
        flash_loan_fee = trade_amount_usd * 0.003  # 0.3%
        jupiter_fees = trade_amount_usd * 0.002    # ~0.2% estimate
        gas_cost = 0.01  # ~$0.01 SOL
        
        total_cost = flash_loan_fee + jupiter_fees + gas_cost
        cost_pct = total_cost / trade_amount_usd
        
        # Profit calculation
        gross_profit = abs(spread) * trade_amount_usd
        net_profit = gross_profit - total_cost
        
        return {
            "spread_pct": spread * 100,
            "trade_amount": trade_amount_usd,
            "flash_loan_fee": flash_loan_fee,
            "jupiter_fees": jupiter_fees,
            "gas_cost": gas_cost,
            "total_cost": total_cost,
            "cost_pct": cost_pct * 100,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
            "profitable": net_profit > 0,
            "direction": "BUY" if spread < 0 else "SELL",
        }
    
    async def build_arbitrage_tx(
        self,
        borrow_amount: int,
        direction: str,  # "BUY" or "SELL"
    ) -> Transaction:
        """Build the flash arbitrage transaction."""
        
        # Get Jupiter swap instructions
        if direction == "BUY":
            # Buy JLP at discount, sell at market
            buy_ix = await self._get_jupiter_swap_ix(
                input_mint=USDC_MINT,
                output_mint=JLP_MINT,
                amount=borrow_amount,
            )
            sell_ix = await self._get_jupiter_swap_ix(
                input_mint=JLP_MINT,
                output_mint=USDC_MINT,
                amount=0,  # Use all JLP received
            )
        else:
            # Borrow JLP value, sell for USDC
            # (Different flow for premium arbitrage)
            pass
        
        # Build transaction with flash loan wrapper
        tx = Transaction()
        tx.add(self._build_flash_arb_ix(
            borrow_amount=borrow_amount,
            buy_data=buy_ix.data,
            sell_data=sell_ix.data,
        ))
        
        return tx
    
    async def execute(
        self,
        borrow_amount: int,
        direction: str,
        simulate_first: bool = True,
    ) -> dict:
        """Execute flash arbitrage."""
        
        tx = await self.build_arbitrage_tx(borrow_amount, direction)
        
        if simulate_first:
            sim_result = await self.client.simulate_transaction(tx)
            if sim_result.value.err:
                return {
                    "success": False,
                    "error": str(sim_result.value.err),
                    "simulated": True,
                }
        
        # Send transaction
        result = await self.client.send_transaction(tx, self.wallet)
        
        return {
            "success": True,
            "signature": str(result.value),
            "simulated": False,
        }
```

### Integration with LP Arbitrage Bot

```python
# In lp_arbitrage.py

class LPArbitrageEngine:
    def __init__(self, config: LPConfig, wallet: LocalWallet):
        # ... existing init ...
        
        # Flash loan client (optional)
        self.flash_client = None
        if config.use_flash_loans:
            self.flash_client = FlashArbitrageClient(
                rpc_url=config.rpc_url,
                wallet=wallet.keypair,
            )
    
    async def run_once(self) -> Dict:
        # ... existing price fetching ...
        
        if self.config.use_flash_loans and self.flash_client:
            return await self._execute_flash_arbitrage(
                virtual_price, market_price, spread
            )
        else:
            return await self._execute_standard_arbitrage(
                virtual_price, market_price, spread
            )
    
    async def _execute_flash_arbitrage(
        self,
        virtual_price: float,
        market_price: float,
        spread: float,
    ) -> Dict:
        """Execute arbitrage using flash loan."""
        
        # Check profitability with flash loan costs
        opportunity = await self.flash_client.check_opportunity(
            virtual_price=virtual_price,
            market_price=market_price,
            trade_amount_usd=self.config.trade_amount_usd,
        )
        
        if not opportunity["profitable"]:
            return {
                "action": "HOLD",
                "reason": f"Not profitable after flash loan costs: ${opportunity['net_profit']:.2f}",
            }
        
        # Execute flash arbitrage
        if self.config.trading_mode == "live":
            result = await self.flash_client.execute(
                borrow_amount=int(self.config.trade_amount_usd * 1e6),
                direction=opportunity["direction"],
            )
            return {
                "action": opportunity["direction"],
                "executed": result["success"],
                "profit": opportunity["net_profit"],
                "tx_signature": result.get("signature"),
            }
        else:
            return {
                "action": opportunity["direction"],
                "executed": False,
                "simulated_profit": opportunity["net_profit"],
                "mode": "whatif",
            }
```

---

## Cost Analysis

### Break-Even Calculation

```
For a $1,000 flash loan arbitrage:

Flash loan fee (Solend 0.3%):     $3.00
Jupiter swap fees (~0.2% × 2):    $4.00
Solana gas (~2 txns worth):       $0.02
───────────────────────────────────────
Total cost:                       $7.02
Break-even spread:                0.702%
```

### Comparison: Flash Loan vs Standard

| Metric | Standard Arbitrage | Flash Loan Arbitrage |
|--------|-------------------|----------------------|
| Capital required | $1,000 | $0 |
| Flash loan fee | $0 | $3.00 |
| Swap fees | $4.00 | $4.00 |
| Gas | $0.02 | $0.02 |
| **Total cost** | **$4.02** | **$7.02** |
| **Break-even spread** | **0.402%** | **0.702%** |
| Risk if trade fails | Lost gas + slippage | Gas only |
| Capital efficiency | Low | Infinite |

### When to Use Flash Loans

Flash loans make sense when:
1. **Capital constrained**: Don't have $X to trade
2. **Large opportunities**: Spread > ~0.7% (break-even)
3. **Risk aversion**: Want atomic execution guarantee
4. **Scaling**: Can borrow more than you own

Flash loans are NOT ideal when:
1. **Small spreads**: Spread < 0.7% won't cover fees
2. **Already capitalized**: Own funds have lower break-even
3. **High frequency**: Extra fee per trade adds up

---

## Cost Reduction Strategies

The 0.7% break-even spread is **potentially unrealistic** for JLP arbitrage, where typical spreads are 0.1-0.3%. This section explores strategies to reduce overhead and lower the break-even threshold.

### Strategy 1: Use Lower-Fee Flash Loan Providers

| Provider | Fee | Break-Even Impact |
|----------|-----|-------------------|
| Solend | 0.30% | Baseline |
| Kamino | 0.09% | **-0.21%** |
| Marginfi | ~0.10% | **-0.20%** |
| Custom Pool | 0.00-0.05% | **-0.25 to -0.30%** |

**Kamino Example:**
```
Flash loan fee (Kamino 0.09%):    $0.90
Jupiter swap fees (~0.2% × 2):    $4.00
Solana gas:                       $0.02
───────────────────────────────────────
Total cost:                       $4.92
Break-even spread:                0.492%  (down from 0.702%)
```

**Recommendation**: Use Kamino as primary, Solend as fallback.

---

### Strategy 2: Direct JLP Mint/Redeem (Skip Jupiter Swaps)

Instead of swapping through Jupiter AMM, mint/redeem JLP directly with Jupiter Perpetuals.

```
┌─────────────────────────────────────────────────────────────────┐
│  CURRENT: Jupiter AMM Swap                                      │
│  USDC → [AMM Pool] → JLP                                       │
│  Fee: ~0.2% per swap × 2 = 0.4%                                │
├─────────────────────────────────────────────────────────────────┤
│  OPTIMIZED: Direct Mint/Redeem                                  │
│  USDC → [Jupiter Perps Program] → JLP (mint)                   │
│  JLP → [Jupiter Perps Program] → USDC (redeem)                 │
│  Fee: Built into spread, potentially lower                      │
└─────────────────────────────────────────────────────────────────┘
```

**Potential savings**: 0.2-0.3% (eliminating AMM intermediary fees)

**Implementation**:
```rust
// Direct mint via Jupiter Perpetuals program
pub fn mint_jlp(
    ctx: Context<MintJlp>,
    usdc_amount: u64,
) -> Result<()> {
    // CPI to Jupiter Perpetuals addLiquidity instruction
    jupiter_perps_cpi::add_liquidity(
        ctx.accounts.perps_program,
        ctx.accounts.pool,
        ctx.accounts.usdc_custody,
        usdc_amount,
    )?;
    Ok(())
}
```

**Revised cost with Kamino + direct mint:**
```
Flash loan fee (Kamino 0.09%):    $0.90
Direct mint/redeem spread:        $1.00  (estimated 0.1%)
Solana gas:                       $0.02
───────────────────────────────────────
Total cost:                       $1.92
Break-even spread:                0.192%  ✓ REALISTIC
```

---

### Strategy 3: Self-Funded Flash Loan Pool

Deploy a private lending pool with zero or minimal fees.

```
┌─────────────────────────────────────────────────────────────────┐
│                  PRIVATE FLASH LOAN POOL                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Deposit capital into own lending pool PDA                  │
│  2. Flash borrow from own pool (0% fee)                        │
│  3. Execute arbitrage                                           │
│  4. Repay to own pool                                          │
│                                                                 │
│  Benefits:                                                      │
│  - Zero flash loan fee                                          │
│  - Full control over liquidity                                  │
│  - Can withdraw capital anytime                                 │
│                                                                 │
│  Drawbacks:                                                     │
│  - Requires capital (defeats "zero capital" benefit)           │
│  - But: Atomicity guarantee still valuable                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation**:
```rust
#[account]
pub struct PrivatePool {
    pub authority: Pubkey,
    pub usdc_vault: Pubkey,
    pub total_deposited: u64,
    pub bump: u8,
}

pub fn flash_borrow_private(
    ctx: Context<FlashBorrowPrivate>,
    amount: u64,
) -> Result<()> {
    // No fee charged - it's our own pool
    transfer_from_vault(ctx.accounts.vault, ctx.accounts.borrower, amount)?;
    Ok(())
}

pub fn flash_repay_private(
    ctx: Context<FlashRepayPrivate>,
    amount: u64,
) -> Result<()> {
    // Just repay principal, no fee
    transfer_to_vault(ctx.accounts.borrower, ctx.accounts.vault, amount)?;
    Ok(())
}
```

**Revised cost with private pool + direct mint:**
```
Flash loan fee (private 0%):      $0.00
Direct mint/redeem spread:        $1.00
Solana gas:                       $0.02
───────────────────────────────────────
Total cost:                       $1.02
Break-even spread:                0.102%  ✓ VERY REALISTIC
```

---

### Strategy 4: Hybrid Approach (Capital + Flash Loan Scaling)

Use own capital for base trades, flash loans only for scaling beyond owned capital.

```
┌─────────────────────────────────────────────────────────────────┐
│                    HYBRID CAPITAL MODEL                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Owned capital: $10,000                                         │
│  Opportunity size: $50,000                                      │
│                                                                 │
│  Trade breakdown:                                               │
│  ├── $10,000 from own funds (0% borrow cost)                   │
│  └── $40,000 from flash loan (0.09% = $36 cost)                │
│                                                                 │
│  Blended borrow cost: $36 / $50,000 = 0.072%                   │
│                                                                 │
│  vs. 100% flash loan: 0.09%                                    │
│  vs. 100% own funds: Limited to $10,000 trade size             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### Strategy 5: Volume-Based Fee Negotiation

For high-volume traders, negotiate reduced fees with lending protocols.

| Volume Tier | Potential Fee Reduction |
|-------------|------------------------|
| < $100K/month | Standard rates |
| $100K - $1M/month | 10-20% discount |
| $1M - $10M/month | 20-40% discount |
| > $10M/month | Custom negotiation |

**Approach**:
1. Contact Kamino/Solend business development
2. Propose volume commitment
3. Request whitelisted address with reduced fees

---

### Strategy 6: Batch Multiple Opportunities

Amortize flash loan fee across multiple arbitrage opportunities in one transaction.

```
┌─────────────────────────────────────────────────────────────────┐
│               BATCHED ARBITRAGE TRANSACTION                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Flash borrow $10,000 USDC (one fee: $9)                    │
│                                                                 │
│  2. Execute multiple arbs:                                      │
│     ├── JLP arbitrage: $3,000                                  │
│     ├── Other LP token: $3,000                                 │
│     └── Third opportunity: $4,000                              │
│                                                                 │
│  3. Repay $10,009                                              │
│                                                                 │
│  Fee per opportunity: $3 (vs $9 if separate)                   │
│  Break-even per trade: ~0.3% (vs 0.5%)                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Limitation**: Requires multiple simultaneous opportunities.

---

### Cost Reduction Summary

| Strategy | Flash Loan Fee | Swap Fee | Break-Even |
|----------|---------------|----------|------------|
| Baseline (Solend + Jupiter) | 0.30% | 0.40% | **0.70%** |
| Kamino + Jupiter | 0.09% | 0.40% | **0.49%** |
| Kamino + Direct Mint | 0.09% | 0.10% | **0.19%** |
| Private Pool + Jupiter | 0.00% | 0.40% | **0.40%** |
| Private Pool + Direct Mint | 0.00% | 0.10% | **0.10%** |
| Hybrid (50% own funds) | 0.045% | 0.10% | **0.15%** |

### Recommended Approach

```
┌─────────────────────────────────────────────────────────────────┐
│              RECOMMENDED IMPLEMENTATION PATH                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase 1: Kamino + Direct Mint/Redeem                          │
│  ├── Break-even: ~0.19%                                        │
│  ├── Complexity: Medium                                         │
│  └── Capital required: None                                     │
│                                                                 │
│  Phase 2: Private Pool + Direct Mint                           │
│  ├── Break-even: ~0.10%                                        │
│  ├── Complexity: Higher                                         │
│  └── Capital required: Yes (but atomic safety)                 │
│                                                                 │
│  Phase 3: Hybrid Scaling                                        │
│  ├── Use own funds for base                                    │
│  ├── Flash loan for scaling beyond capital                     │
│  └── Optimal capital efficiency                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Viability Assessment

Based on historical JLP spread data:

| Spread Range | Frequency | Viable With |
|--------------|-----------|-------------|
| > 0.70% | Rare | Any strategy |
| 0.40% - 0.70% | Occasional | Kamino + Jupiter |
| 0.20% - 0.40% | Common | Kamino + Direct Mint |
| 0.10% - 0.20% | Frequent | Private Pool + Direct Mint |
| < 0.10% | Very frequent | Own capital only |

**Conclusion**: With optimized implementation (Kamino + direct mint), flash loan arbitrage becomes viable for spreads as low as **0.2%**, which is realistic for JLP.

---

## Security Considerations

### Smart Contract Risks

| Risk | Mitigation |
|------|------------|
| Reentrancy | Use Anchor's reentrancy guard, check balances |
| Integer overflow | Use checked math, Rust's built-in checks |
| Unauthorized access | Validate signer, use PDAs |
| Oracle manipulation | Use multiple price sources, sanity checks |
| Front-running | Submit via Jito, use private RPC |

### Operational Security

```rust
// Admin controls
#[account]
pub struct ArbConfig {
    pub authority: Pubkey,      // Only authority can modify
    pub enabled: bool,          // Kill switch
    pub max_borrow: u64,        // Limit exposure
    pub min_profit_bps: u16,    // Minimum profit requirement
    pub allowed_tokens: Vec<Pubkey>,  // Whitelist
}

// Emergency shutdown
pub fn emergency_disable(ctx: Context<Admin>) -> Result<()> {
    require!(
        ctx.accounts.authority.key() == ctx.accounts.config.authority,
        ErrorCode::Unauthorized
    );
    ctx.accounts.config.enabled = false;
    Ok(())
}
```

### Transaction Simulation

Always simulate before executing:

```python
async def safe_execute(self, tx: Transaction) -> dict:
    # 1. Simulate transaction
    sim = await self.client.simulate_transaction(tx)
    
    if sim.value.err:
        return {"error": f"Simulation failed: {sim.value.err}"}
    
    # 2. Check logs for expected behavior
    logs = sim.value.logs
    if "ArbitrageExecuted" not in str(logs):
        return {"error": "Expected event not found in simulation"}
    
    # 3. Extract simulated profit from logs
    profit = self._parse_profit_from_logs(logs)
    if profit < self.min_profit:
        return {"error": f"Simulated profit too low: {profit}"}
    
    # 4. Execute for real
    return await self.client.send_transaction(tx, self.wallet)
```

---

## Implementation Roadmap

### Phase 1: Research & Prototyping (1-2 weeks)
- [ ] Test Solend flash loan on devnet
- [ ] Test Jupiter CPI from custom program
- [ ] Measure actual costs and latency
- [ ] Validate atomicity guarantees

### Phase 2: Smart Contract Development (2-3 weeks)
- [ ] Implement Anchor program
- [ ] Unit tests with local validator
- [ ] Integration tests on devnet
- [ ] Security review / audit prep

### Phase 3: Client Integration (1 week)
- [ ] Python client for flash arbitrage
- [ ] Integrate with existing `lp_arbitrage.py`
- [ ] Add `--use-flash-loans` flag
- [ ] Logging and monitoring

### Phase 4: Deployment & Testing (1-2 weeks)
- [ ] Deploy to mainnet-beta
- [ ] Small-scale live testing
- [ ] Monitor and tune parameters
- [ ] Document operational procedures

---

## Flash Loan Enhancement for Correlated Pair Arbitrage

> **See also:** [`CORRELATED_PAIR_FEATURE.md`](./CORRELATED_PAIR_FEATURE.md) for the full cross-exchange arbitrage design.

The Correlated Pair feature supports arbitrage on **correlated assets** (same or equivalent tokens) across various scenarios. This section examines how flash loans can enhance these strategies.

### Correlated Pair Arbitrage Scenarios

| Scenario | Example | Description |
|----------|---------|-------------|
| **Cross-DEX** | SOL on Jupiter vs Raydium | Same token, different DEXs on same chain |
| **Wrapped/Native** | wTAO vs TAO | Wrapped token vs native, may be same or different venues |
| **Cross-CEX** | BTC on Coinbase vs Binance | Same token on different centralized exchanges |
| **DEX↔CEX** | wTAO on Jupiter vs TAO on Coinbase | Wrapped on DEX vs native on CEX |
| **Single-Exchange Pool** | wTAO/TAO LP on Jupiter | Arbitrage within a single liquidity pool |

### Flash Loan Applicability Matrix

| Scenario | Same Chain? | Flash Loan? | Notes |
|----------|-------------|-------------|-------|
| Jupiter ↔ Raydium | ✅ Yes | ✅ **Yes** | Atomic cross-DEX |
| Jupiter ↔ Orca | ✅ Yes | ✅ **Yes** | Atomic cross-DEX |
| wTAO/TAO pool (Jupiter) | ✅ Yes | ✅ **Yes** | Single-exchange, single-txn |
| wBTC/BTC pool (Curve) | ✅ Yes | ✅ **Yes** | Single-exchange, single-txn |
| Jupiter ↔ Coinbase | ❌ No | ❌ **No** | Cross-chain/system |
| Coinbase ↔ Binance | ❌ No | ❌ **No** | Different systems |
| Uniswap ↔ Sushiswap | ✅ Yes | ✅ **Yes** | Atomic on Ethereum |

### Single-Exchange Arbitrage (Liquidity Pool)

When a wrapped/native pair exists as a **liquidity pool on a single exchange**, flash loans are highly effective:

```
┌─────────────────────────────────────────────────────────────────────────┐
│      SINGLE-EXCHANGE POOL ARBITRAGE (e.g., wTAO/TAO on Jupiter)         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Condition: Pool has imbalanced ratio (wTAO cheap relative to TAO)     │
│                                                                         │
│  SINGLE ATOMIC TRANSACTION:                                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 1. Flash borrow TAO                                             │   │
│  │                      ↓                                           │   │
│  │ 2. Swap TAO → wTAO in the pool (buy cheap wTAO)                 │   │
│  │                      ↓                                           │   │
│  │ 3. Unwrap wTAO → TAO via bridge/wrapper contract                │   │
│  │                      ↓                                           │   │
│  │ 4. Repay flash loan + fee, keep profit                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Key insight: If unwrap is on-chain, entire flow is atomic             │
│  Challenge: Most unwrap operations are cross-chain (not atomic)        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Critical Question:** Can the wrap/unwrap operation happen atomically on-chain?

| Wrapper Type | Atomic? | Example |
|--------------|---------|---------|
| Native wrap (SOL→wSOL) | ✅ Yes | Solana native wrapping |
| On-chain wrapper contract | ✅ Yes | Some synthetic tokens |
| Cross-chain bridge | ❌ No | wTAO (Solana) → TAO (Bittensor) |
| Custodial wrap | ❌ No | WBTC (requires custodian) |

### When Flash Loans Apply (Summary)

| Scenario | Flash Loan Viable? | Why |
|----------|-------------------|-----|
| Cross-DEX (same chain) | ✅ Yes | Both swaps in one transaction |
| Single-exchange pool (atomic unwrap) | ✅ Yes | All operations on-chain |
| Single-exchange pool (bridge unwrap) | ❌ No | Bridge breaks atomicity |
| Cross-chain (DEX↔CEX) | ❌ No | Different systems |
| Cross-CEX | ❌ No | Off-chain systems |

### Architecture: Atomic Cross-DEX Arbitrage

When both exchanges are on Solana, the entire arbitrage executes in a single atomic transaction:

```
┌─────────────────────────────────────────────────────────────────────────┐
│          ATOMIC CROSS-DEX ARBITRAGE (Same Chain)                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Example: SOL is $100 on Jupiter, $101 on Raydium (1% spread)          │
│                                                                         │
│  SINGLE ATOMIC TRANSACTION:                                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 1. Flash borrow $10,000 USDC from Kamino                        │   │
│  │                      ↓                                           │   │
│  │ 2. Buy 100 SOL on Jupiter @ $100                                │   │
│  │    $10,000 USDC → 100 SOL                                       │   │
│  │                      ↓                                           │   │
│  │ 3. Sell 100 SOL on Raydium @ $101                               │   │
│  │    100 SOL → $10,100 USDC                                       │   │
│  │                      ↓                                           │   │
│  │ 4. Repay flash loan + fee                                       │   │
│  │    $10,000 + $9 (Kamino 0.09%) = $10,009                        │   │
│  │                      ↓                                           │   │
│  │ 5. PROFIT: $10,100 - $10,009 = $91                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ✓ SUCCESS: Profit transferred to wallet                               │
│  ✗ FAILURE: Entire transaction reverts, no loss                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Integration with Correlated Pair Bot

The `ArbitragePairBot` (from `CORRELATED_PAIR_FEATURE.md`) can detect when flash loans are applicable:

```python
@dataclass
class ArbitrageBotConfig:
    # ... existing fields from CORRELATED_PAIR_FEATURE.md ...
    exchange_a: str
    exchange_b: str
    token: str
    spread_threshold_pct: float = 1.0
    
    # Flash loan enhancement
    use_flash_loan: bool = False       # Enable atomic execution
    flash_provider: str = "kamino"     # kamino, solend, marginfi

def can_use_flash_loan(exchange_a: str, exchange_b: str) -> bool:
    """Check if both exchanges support atomic transactions."""
    SOLANA_DEXES = {"jupiter", "raydium", "orca", "phoenix", "lifinity"}
    EVM_DEXES = {"uniswap", "sushiswap", "curve", "balancer"}
    
    # Same chain = atomic possible
    if exchange_a in SOLANA_DEXES and exchange_b in SOLANA_DEXES:
        return True
    if exchange_a in EVM_DEXES and exchange_b in EVM_DEXES:
        return True
    
    return False
```

### CLI Integration

```bash
# Standard cross-DEX arbitrage (non-atomic, uses --parallel-mode or sequential)
python arbitrage_pair_bot.py \
    --token SOL \
    --exchange-a jupiter \
    --exchange-b raydium \
    --spread-threshold 0.5 \
    --daemon

# Atomic cross-DEX arbitrage with flash loan (zero capital, zero risk)
python arbitrage_pair_bot.py \
    --token SOL \
    --exchange-a jupiter \
    --exchange-b raydium \
    --spread-threshold 0.2 \
    --use-flash-loan \
    --flash-provider kamino \
    --daemon
```

### Comparison: Standard vs Flash Loan Cross-DEX

| Aspect | Standard (from CORRELATED_PAIR_FEATURE) | Flash Loan Enhanced |
|--------|----------------------------------------|---------------------|
| Capital required | Full trade amount | Zero |
| Execution | Sequential or parallel legs | Single atomic txn |
| Risk if one leg fails | Partial position | None (reverts) |
| Break-even spread | ~0.5% (fees only) | ~0.6% (fees + flash fee) |
| Applicable exchanges | Any two exchanges | Same-chain only |
| Complexity | Python only | Requires smart contract |

### Smart Contract: Cross-DEX Flash Arbitrage

```rust
pub fn execute_cross_dex_arbitrage(
    ctx: Context<CrossDexArbitrage>,
    borrow_amount: u64,
    dex_a_swap_data: Vec<u8>,  // Jupiter swap instruction data
    dex_b_swap_data: Vec<u8>,  // Raydium swap instruction data
) -> Result<()> {
    let initial_balance = ctx.accounts.usdc_account.amount;
    
    // 1. Flash borrow USDC
    flash_loan::borrow(ctx.accounts.lending_pool, borrow_amount)?;
    
    // 2. Buy token on DEX A (cheaper)
    // USDC → Token via Jupiter
    jupiter_cpi::swap(ctx.accounts.jupiter_program, dex_a_swap_data)?;
    
    // 3. Sell token on DEX B (more expensive)
    // Token → USDC via Raydium
    raydium_cpi::swap(ctx.accounts.raydium_program, dex_b_swap_data)?;
    
    // 4. Verify profit and repay
    ctx.accounts.usdc_account.reload()?;
    let final_balance = ctx.accounts.usdc_account.amount;
    
    let flash_fee = borrow_amount * 9 / 10000;  // 0.09% Kamino
    let repay_amount = borrow_amount + flash_fee;
    
    require!(final_balance >= initial_balance + repay_amount, ErrorCode::NoProfitError);
    
    flash_loan::repay(ctx.accounts.lending_pool, repay_amount)?;
    
    // 5. Profit stays in user's USDC account
    emit!(CrossDexArbitrageExecuted {
        dex_a: "jupiter",
        dex_b: "raydium", 
        borrow_amount,
        profit: final_balance - initial_balance - repay_amount,
    });
    
    Ok(())
}
```

### Execution Flow Decision Tree

```
┌─────────────────────────────────────────────────────────────────┐
│                    ARBITRAGE EXECUTION DECISION                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Is --use-flash-loan enabled?                                   │
│       │                                                         │
│       ├── NO → Use standard execution from CORRELATED_PAIR_*    │
│       │        (sequential or --parallel-mode)                  │
│       │                                                         │
│       └── YES → Are both exchanges on same chain?               │
│                     │                                           │
│                     ├── NO → ERROR: Flash loan not supported    │
│                     │        for cross-chain pairs              │
│                     │                                           │
│                     └── YES → Execute atomic flash arbitrage    │
│                               (single transaction, zero risk)   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Break-Even Analysis for Cross-DEX Flash Arbitrage

```
For a $10,000 cross-DEX flash loan arbitrage (Jupiter ↔ Raydium):

Flash loan fee (Kamino 0.09%):     $9.00
Jupiter swap fee (~0.2%):          $20.00
Raydium swap fee (~0.25%):         $25.00
Solana gas:                        $0.02
───────────────────────────────────────────
Total cost:                        $54.02
Break-even spread:                 0.54%
```

**Comparison with non-flash execution:**
```
No flash loan fee:                 $0.00
Jupiter swap fee (~0.2%):          $20.00
Raydium swap fee (~0.25%):         $25.00
Solana gas (2 txns):               $0.04
───────────────────────────────────────────
Total cost:                        $45.04
Break-even spread:                 0.45%
```

**When to use flash loans for cross-DEX:**
- ✅ Use flash loan when: spread > 0.54% AND you want zero-risk atomicity
- ✅ Use flash loan when: you don't have capital but spread is sufficient
- ❌ Skip flash loan when: spread is 0.45-0.54% (profitable without flash fee)
- ❌ Skip flash loan when: you have capital and accept execution risk

### Suitability Assessment: Flash Loans for Correlated Pair Arbitrage

| Scenario | Suitability | Spread Expectation | Competition | Verdict |
|----------|-------------|-------------------|-------------|---------|
| **Cross-DEX (same token)** | ⚠️ Marginal | 0.1-0.3% | Very High (MEV) | Low priority |
| **Single-exchange pool (atomic)** | ✅ Good | 0.5-2% | Moderate | Worth exploring |
| **Wrapped/Native (bridge)** | ❌ N/A | N/A | N/A | Not atomic |
| **DEX↔CEX** | ❌ N/A | 0.5-2% | Low | Not atomic |
| **CEX↔CEX** | ❌ N/A | 0.1-0.5% | Moderate | Not atomic |

**Honest Assessment by Scenario:**

```
┌─────────────────────────────────────────────────────────────────┐
│      FLASH LOAN SUITABILITY: CORRELATED PAIR ARBITRAGE          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SCENARIO 1: Cross-DEX (SOL on Jupiter vs Raydium)             │
│  ──────────────────────────────────────────────────             │
│  Verdict: ⚠️ MARGINALLY SUITABLE                                │
│  - Spreads typically <0.3% (below break-even)                   │
│  - MEV bots dominate, speed is critical                         │
│  - Better suited for HFT infrastructure, not flash loans        │
│                                                                 │
│  SCENARIO 2: Single-Exchange Pool (wTAO/TAO LP)                │
│  ──────────────────────────────────────────────                 │
│  Verdict: ✅ GOOD FIT (if atomic unwrap exists)                 │
│  - Pool imbalances can reach 1-3%                               │
│  - Less competition than cross-DEX                              │
│  - Single transaction simplifies execution                      │
│  ⚠️ BUT: Most wrapped tokens require cross-chain bridge        │
│                                                                 │
│  SCENARIO 3: Wrapped/Native via Bridge (wTAO → TAO)            │
│  ──────────────────────────────────────────────────             │
│  Verdict: ❌ NOT SUITABLE                                       │
│  - Bridge operation breaks atomicity                            │
│  - Cannot use flash loans for this scenario                     │
│  - Use standard correlated pair bot instead                     │
│                                                                 │
│  SCENARIO 4-5: Cross-chain (DEX↔CEX, CEX↔CEX)                  │
│  ────────────────────────────────────────────────               │
│  Verdict: ❌ NOT APPLICABLE                                     │
│  - Flash loans only work on single chain                        │
│  - Use standard correlated pair bot from CORRELATED_PAIR_*.md  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key Insight: Limited Applicability**

Most correlated pair arbitrage scenarios involve **cross-chain or cross-system** operations where flash loans **cannot apply**:

| Common Correlated Pairs | Flash Loan? | Why |
|------------------------|-------------|-----|
| wTAO (Solana) ↔ TAO (Bittensor) | ❌ | Cross-chain bridge |
| WBTC (Ethereum) ↔ BTC (Bitcoin) | ❌ | Cross-chain |
| BTC (Coinbase) ↔ BTC (Binance) | ❌ | Off-chain systems |
| wETH (Solana) ↔ ETH (Ethereum) | ❌ | Cross-chain bridge |
| SOL (Jupiter) ↔ SOL (Raydium) | ✅ | Same chain, same token |

**Recommendation:** 

Flash loans for correlated pair arbitrage are a **niche enhancement**, not a core feature. The majority of correlated pair opportunities (wrapped↔native across chains) **cannot use flash loans** due to atomicity requirements.

---

### Empirical Data: JLP What-If Results

Real-world testing of JLP NAV arbitrage (the "primary" flash loan use case in this document):

```
=== WHAT-IF SUMMARY (TRUE ARBITRAGE) ===
============================================================
Platform: Jupiter JLP
Mode: WHATIF
Total wake-ups: 46
Opportunities detected: 0
  - Premium arbitrage (mint→sell): 0
  - Discount arbitrage (buy→redeem): 0
Simulated P&L: $0.00
============================================================
```

**Analysis:** Over 46 monitoring cycles (~overnight run), **zero profitable flash loan arbitrage opportunities** were detected. This is a significant data point.

---

### Reality Check: Flash Loans in the Modern Crypto Market

```
┌─────────────────────────────────────────────────────────────────┐
│           FLASH LOAN ARBITRAGE: MARKET REALITY                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  THE LOW-HANGING FRUIT HAS BEEN PICKED.                        │
│                                                                 │
│  Flash loan arbitrage was highly profitable in 2020-2021:      │
│  - DeFi protocols were new and inefficient                     │
│  - Fewer sophisticated bots competing                          │
│  - Larger and more frequent price dislocations                 │
│                                                                 │
│  Today's reality (2024+):                                      │
│  - Professional MEV searchers dominate                         │
│  - Jito bundles and private mempools                           │
│  - Sub-second arbitrage execution                              │
│  - Spreads compressed to near-zero                             │
│  - JLP: 46 checks, 0 opportunities (empirical data above)      │
│                                                                 │
│  Implication:                                                   │
│  Flash loan implementation is HIGH EFFORT, LOW REWARD          │
│  for most arbitrage scenarios in mature markets.               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**What this means for our strategy:**

| Use Case | Expected Opportunity | Recommendation |
|----------|---------------------|----------------|
| JLP NAV arbitrage | ❌ Rare (0/46 in testing) | Deprioritize |
| Cross-DEX (same token) | ❌ Rare, MEV-dominated | Deprioritize |
| **Single-exchange pool (atomic)** | ⚠️ **Potentially viable** | **Investigate further** |
| Cross-chain correlated pairs | N/A (not atomic) | Use standard execution |

---

### Revised Assessment: Single-Exchange Pool Arbitrage

Given the empirical evidence that traditional flash loan arbitrage opportunities are rare, **single-exchange pool arbitrage** emerges as the most promising remaining niche:

```
┌─────────────────────────────────────────────────────────────────┐
│     WHY SINGLE-EXCHANGE POOL ARBITRAGE MAY STILL WORK          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. LESS COMPETITION                                            │
│     - Cross-DEX and JLP arbitrage are well-known               │
│     - Pool imbalance arbitrage is more obscure                 │
│     - Fewer bots specifically targeting this niche             │
│                                                                 │
│  2. HIGHER SPREADS POSSIBLE                                     │
│     - LP pools can become significantly imbalanced             │
│     - wTAO/TAO pools may see 1-5% imbalances                   │
│     - Less efficient price discovery than major pairs          │
│                                                                 │
│  3. STRUCTURAL ADVANTAGES                                       │
│     - Single transaction (simpler than cross-DEX)              │
│     - Lower gas costs (one swap vs two)                        │
│     - Atomic by design                                          │
│                                                                 │
│  4. REQUIREMENTS                                                │
│     - Need pools with atomic wrap/unwrap                        │
│     - Or pools with two related assets (stETH/ETH, etc.)       │
│     - Pool must have sufficient liquidity                       │
│                                                                 │
│  CANDIDATES TO INVESTIGATE:                                     │
│  ├── wSOL/SOL pools (native wrapping is atomic)                │
│  ├── stETH/ETH pools (Lido staking derivative)                 │
│  ├── mSOL/SOL pools (Marinade staking derivative)              │
│  └── Other liquid staking derivatives                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key Insight:** Liquid staking derivatives (stETH, mSOL, jitoSOL) are promising because:
1. Wrap/unwrap is **on-chain and atomic** (no bridge)
2. Pools exist on major DEXs
3. Spreads can develop during high volatility or staking/unstaking demand
4. Less attention from MEV bots than pure arbitrage

---

### Deep Dive: Correlated Pair + Single Exchange + Atomic Unwrap + Flash Loan

This is the **most promising flash loan niche** for correlated pair arbitrage. Here's why:

```
┌─────────────────────────────────────────────────────────────────┐
│   CORRELATED PAIR FLASH ARBITRAGE: SINGLE EXCHANGE (ATOMIC)    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SCENARIO: mSOL/SOL pool on Orca is imbalanced                 │
│  mSOL is trading at 0.98 SOL (2% discount to staking rate)     │
│                                                                 │
│  ATOMIC FLASH LOAN ARBITRAGE:                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Flash borrow 100 SOL from Kamino                     │   │
│  │                      ↓                                   │   │
│  │ 2. Swap SOL → mSOL in pool @ 0.98 rate                  │   │
│  │    100 SOL → 102.04 mSOL                                │   │
│  │                      ↓                                   │   │
│  │ 3. Unstake mSOL → SOL via Marinade (ATOMIC on Solana)   │   │
│  │    102.04 mSOL → 102.04 SOL (1:1 redemption)            │   │
│  │                      ↓                                   │   │
│  │ 4. Repay flash loan: 100 SOL + 0.09 SOL fee             │   │
│  │                      ↓                                   │   │
│  │ 5. PROFIT: 102.04 - 100.09 = 1.95 SOL (~$300 at $150)   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  WHY THIS WORKS:                                                │
│  ✓ All operations are ON-CHAIN and ATOMIC                      │
│  ✓ No bridge, no cross-chain, no CEX                           │
│  ✓ Pool imbalances occur during staking demand shifts          │
│  ✓ Flash loan provides capital, atomicity provides safety      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Critical Requirement: Atomic Unstaking**

| Staking Protocol | Unstake Method | Atomic? | Flash Loan Compatible? |
|------------------|----------------|---------|------------------------|
| **Marinade (mSOL)** | Delayed unstake (epochs) | ❌ | ❌ No |
| **Marinade (mSOL)** | Instant unstake (liquidity pool) | ✅ | ✅ **Yes** |
| **Jito (jitoSOL)** | Delayed unstake (1 epoch) | ❌ | ❌ No |
| **Jito (jitoSOL)** | Swap on Jupiter (no native instant) | ✅ | ⚠️ Just a DEX swap* |
| **Lido (stETH)** | Delayed withdrawal | ❌ | ❌ No |
| **Lido (stETH)** | Curve stETH/ETH pool swap | ✅ | ✅ **Yes** |

*Jito does NOT offer native instant unstake. Their docs recommend swapping jitoSOL→SOL on Jupiter. This is atomic but is essentially cross-DEX arbitrage (swap jitoSOL→SOL), not a protocol-level redemption.

**The Catch:** Most liquid staking protocols have **delayed unstaking** (epochs/days). Only **Marinade** offers a true instant unstake via their liquidity pool. Other protocols rely on DEX swaps for "instant" exit, which changes the arbitrage economics.

### Suitability Assessment: Correlated Pair Flash Loan (Atomic Unwrap)

```
┌─────────────────────────────────────────────────────────────────┐
│    VERDICT: ✅ MOST PROMISING FLASH LOAN NICHE                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PROS:                                                          │
│  + Fully atomic (single transaction, revert on failure)         │
│  + Zero capital required (flash loan funded)                    │
│  + Zero risk (atomic = no partial execution)                    │
│  + Higher spreads than cross-DEX (1-3% vs 0.1-0.3%)            │
│  + Less MEV competition (niche, complex)                        │
│  + Structural opportunity (staking demand creates imbalances)   │
│                                                                 │
│  CONS:                                                          │
│  ⚠️ Requires instant unstake mechanism (not all protocols)     │
│  ⚠️ Instant unstake pools have limited liquidity               │
│  ⚠️ Spreads may not exceed break-even after fees               │
│  ⚠️ Still requires smart contract implementation               │
│                                                                 │
│  COMPARED TO OTHER FLASH LOAN USE CASES:                        │
│  ├── JLP NAV arbitrage: 0/46 opportunities (empirical)         │
│  ├── Cross-DEX same token: MEV-dominated, tiny spreads         │
│  └── THIS USE CASE: Untested, but structural advantages        │
│                                                                 │
│  RECOMMENDATION:                                                 │
│  This is worth empirical testing. Build a what-if monitor      │
│  for mSOL/SOL and jitoSOL/SOL pool imbalances before           │
│  investing in smart contract development.                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Break-Even Analysis: Correlated Pair Flash Arbitrage

```
For 100 SOL correlated pair flash arbitrage (mSOL/SOL):

Flash loan fee (Kamino 0.09%):     0.09 SOL
Swap fee (Orca ~0.3%):             0.30 SOL
Instant unstake fee (~0.3%):       0.30 SOL
Solana gas:                        ~0.00 SOL
─────────────────────────────────────────────
Total cost:                        0.69 SOL
Break-even spread:                 0.69%
```

**Comparison to JLP:**
- JLP break-even: ~0.7% (but 0/46 opportunities found)
- Correlated pair break-even: ~0.69% (similar, but different market dynamics)

**When spreads occur:**
- Staking derivative pools imbalance during high staking/unstaking demand
- Market volatility creates temporary dislocations
- Large trades move pool ratios
- Unlike cross-DEX, these are **structural** opportunities, not just latency races

### Integration with CORRELATED_PAIR_FEATURE.md

This use case fits naturally into the correlated pair architecture with a new mode:

```bash
# Standard correlated pair (cross-exchange, non-atomic)
python arbitrage_pair_bot.py \
    --token TAO \
    --exchange-a jupiter \
    --exchange-b coinbase \
    --mode cross-exchange

# Flash loan correlated pair (single-exchange, atomic unwrap)
python arbitrage_pair_bot.py \
    --token mSOL \
    --exchange-a orca \
    --exchange-b marinade-instant \
    --mode atomic-unwrap \
    --use-flash-loan
```

Where `marinade-instant` represents the instant unstake mechanism, and `--mode atomic-unwrap` signals that the bot should use the flash loan + swap + unstake pattern.

### Recommended Next Steps

| Priority | Action | Rationale |
|----------|--------|-----------|
| 1 | Run what-if on **mSOL/SOL** pools (Marinade instant unstake) | Only protocol with true instant unstake |
| 2 | Research Marinade instant unstake pool mechanics | Understand liquidity limits and fees |
| 3 | Build simple mSOL pool imbalance monitor | Collect empirical data |
| 4 | Deprioritize jitoSOL (no native instant unstake) | Swap-only = cross-DEX arbitrage, not protocol redemption |
| 5 | Deprioritize JLP flash arbitrage | 0/46 opportunities in testing |
| 6 | Deprioritize cross-DEX flash arbitrage | MEV-dominated, tight spreads |

**Where flash loans DO add value (revised):**
1. ⚠️ ~~JLP NAV arbitrage~~ → **Deprioritized** (0/46 in testing)
2. ⚠️ ~~Same-chain cross-DEX~~ → **Deprioritized** (MEV-dominated)
3. ✅ **Single-exchange staking derivative pools** → **Most promising niche**

**Where standard execution (non-flash) is better:**
1. All DEX↔CEX pairs (cannot use flash loans anyway)
2. All CEX↔CEX pairs (cannot use flash loans anyway)
3. All wrapped tokens requiring bridges (cannot use flash loans anyway)
4. **Most arbitrage scenarios** (simpler, lower break-even)

### Open Questions: Correlated Pair Flash Arbitrage

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | **Which correlated pair scenarios should support flash loans?** | A. All same-chain scenarios<br>B. Only single-exchange pools<br>C. None (focus on JLP only) | **A** - Support same-chain, but document limitations |
| 2 | **Should we auto-detect flash loan eligibility?** | A. Yes, check if both exchanges on same chain<br>B. No, require explicit flag<br>C. Warn user when not eligible | **A+C** - Auto-detect AND warn when not eligible |
| 3 | **How to handle wrapped tokens with bridges?** | A. Error if flash loan requested<br>B. Fallback to standard execution<br>C. Support hybrid (flash for trade, manual for bridge) | **B** - Graceful fallback to standard mode |
| 4 | **Priority vs other flash loan use cases?** | A. High (many correlated pairs)<br>B. Medium (after JLP)<br>C. Low (limited applicability) | **C** - Limited applicability, JLP is better ROI |
| 5 | **Should single-exchange pool arb be a separate mode?** | A. Yes, distinct `--pool-arb` mode<br>B. No, auto-detect from config<br>C. Part of general cross-exchange mode | **B** - Auto-detect based on exchange_a == exchange_b |
| 6 | **What's the minimum pool imbalance for single-exchange arb?** | A. Same as cross-exchange spread threshold<br>B. Higher (account for slippage)<br>C. Dynamic based on pool depth | **C** - Dynamic, deeper pools can handle tighter spreads |
| 7 | **Should we research which wrapped tokens have atomic unwrap?** | A. Yes, build a registry<br>B. No, assume all require bridges<br>C. Let user specify per-pair | **A** - Build registry, some tokens may surprise us |

---

## Open Questions

### Technical

1. **Which flash loan provider?**
   - Solend: Most established, 0.3% fee
   - Kamino: Lower fee (0.09%), less liquidity
   - Should we support multiple providers?

2. **Jupiter CPI complexity**
   - Jupiter's swap instruction is complex with many accounts
   - How to serialize/deserialize swap data in Rust?
   - Use Jupiter's Rust SDK or raw instruction building?

3. **Transaction size limits**
   - Solana tx max ~1232 bytes
   - Flash loan + 2 Jupiter swaps may exceed
   - Need to use lookup tables (ALTs)?

4. **Compute budget**
   - Complex transaction may exceed 200k compute units
   - Need to request higher compute budget?
   - Cost of additional compute units?

### Economic

5. **Minimum profitable spread**
   - With 0.3% flash loan fee, need ~0.7% spread minimum
   - Are JLP spreads typically this large?
   - Historical analysis needed

6. **Opportunity frequency**
   - How often do spreads exceed break-even?
   - Is flash loan arbitrage viable given opportunity frequency?

7. **Competition**
   - Are other bots doing flash loan JLP arbitrage?
   - Will increased competition compress spreads?

### Operational

8. **Program upgradability**
   - Should the program be upgradable?
   - If yes, what's the upgrade authority model?

9. **Monitoring**
   - How to monitor program health?
   - Alerting on failed transactions?

10. **Key management**
    - Where to store program authority key?
    - HSM, multisig, or single key?

---

## Alternatives Considered

### Alternative 1: Off-Chain Matching

Instead of on-chain flash loans, maintain off-chain capital pool.

```
Pros:
  + No flash loan fees
  + Simpler implementation
  
Cons:
  - Requires capital
  - Not atomic
  - Counterparty risk
```

**Decision**: Proceed with flash loans for atomicity and capital efficiency.

### Alternative 2: MEV Searcher Integration

Partner with existing MEV searchers (e.g., Jito searchers).

```
Pros:
  + Leverage existing infrastructure
  + Access to private order flow
  
Cons:
  - Revenue sharing
  - Less control
  - Dependent on third party
```

**Decision**: Build own program first, consider MEV integration later.

### Alternative 3: Cross-Margin Flash Loan

Use margin protocols that offer flash-loan-like functionality.

```
Pros:
  + May have lower fees
  + More flexible
  
Cons:
  - Less established
  - May require collateral
```

**Decision**: Start with Solend, evaluate alternatives after MVP.

---

## References

### Documentation
- [Solend Flash Loans](https://docs.solend.fi/protocol/flash-loans)
- [Kamino Finance](https://docs.kamino.finance/)
- [Jupiter Integration](https://station.jup.ag/docs)
- [Anchor Book](https://book.anchor-lang.com/)

### Code Examples
- [Solend Flash Loan Example](https://github.com/solendprotocol/solend-sdk/tree/main/examples)
- [Jupiter CPI Example](https://github.com/jup-ag/jupiter-cpi)
- [Anchor Flash Loan Template](https://github.com/coral-xyz/anchor/tree/master/examples)

### Research
- [Flash Loans: A Survey](https://arxiv.org/abs/2010.12252)
- [Solana MEV](https://jito-labs.gitbook.io/mev/)
