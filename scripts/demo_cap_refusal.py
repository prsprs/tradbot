#!/usr/bin/env python3
"""Demo: observe a [DAILY CAP] refusal without spending money or the LLM panel.

WHATIF-ONLY. Refuses to run if TRADING_MODE resolves to 'live'.

Why this script exists (docs/RUNBOOK_live_acceptance.md, "Observing a cap
refusal without spending money"): the daily-cap check only runs inside
maybe_execute_buy(), which only runs after a BUY vote. There is no CLI flag
to force a BUY vote (the panel decides), so an operator running the bot
normally can go a long time without ever seeing a [DAILY CAP] line -- every
vote so far has been HOLD. This script seeds a scratch execution ledger with
a whatif intent that already consumes the whatif daily cap, then calls the
SAME production gate function (crypto_trading_bot.maybe_execute_buy) with a
forced 'BUY' decision, so the refusal path prints for real -- no LLM call,
no network call, no order, no real money, and NOTHING under history/ is
touched.

Usage:
    HISTORY_DIR=/tmp/some-scratch-dir ./venv/bin/python scripts/demo_cap_refusal.py

Run it from a scratch HISTORY_DIR outside the repo (per AGENTS.md hard
rules) -- it writes one whatif intent row to <HISTORY_DIR>/executions.json.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crypto_trading_bot as bot  # noqa: E402
import executionledger as led  # noqa: E402


def main():
    # --- Safety: refuse outright unless everything about this run is whatif.
    trading_mode = os.environ.get('TRADING_MODE', 'whatif').lower()
    if trading_mode == 'live':
        print("[REFUSING TO RUN] TRADING_MODE=live -- this script is "
              "whatif-only. Unset TRADING_MODE or set it to 'whatif'.")
        sys.exit(1)
    if os.environ.get('LIVE_TRADING_CONFIRMED') == '1':
        print("[REFUSING TO RUN] LIVE_TRADING_CONFIRMED=1 is set -- this "
              "script never arms live. Unset it and rerun.")
        sys.exit(1)

    history_dir = os.environ.get('HISTORY_DIR')
    if not history_dir:
        print("[REFUSING TO RUN] Set HISTORY_DIR to a SCRATCH directory "
              "outside the repo (this script writes one ledger row).")
        sys.exit(1)
    history_path = Path(history_dir).resolve()
    if history_path == REPO_ROOT.resolve() or (REPO_ROOT.resolve() / 'history') == history_path:
        print(f"[REFUSING TO RUN] HISTORY_DIR ({history_path}) points at the "
              "repo's real history/ -- use a scratch dir outside the repo.")
        sys.exit(1)
    history_path.mkdir(parents=True, exist_ok=True)
    led.EXECUTIONS_FILE = str(history_path / 'executions.json')

    cap = 5.00
    notional = 5.00

    print("=" * 70)
    print("DEMO: daily-cap refusal path (WHATIF, no money, no network)")
    print("=" * 70)
    print(f"Scratch ledger: {led.EXECUTIONS_FILE}")
    print(f"Daily spend cap: ${cap:.2f}   Notional per buy: ${notional:.2f}")
    print()

    # 1. Seed the ledger with a whatif intent that ALREADY consumes the cap
    #    (mirrors what a prior run in the same UTC day would have left behind
    #    -- same seeding pattern as tests/test_daily_cap_banner.py and
    #    tests/test_run_summary.py).
    led.append_intent(run_id='demo-seed', trading_mode='whatif', coin='SOL',
                       intended_notional_usd=cap, client_order_id='demo-seed-c0')
    already = led.spend_today(trading_mode='whatif')
    print(f"[SEEDED] whatif intent: SOL $5.00 -> ${already:.2f} already "
          "committed today (whatif)")
    print()

    # 2. Wire up the module globals maybe_execute_buy() reads, exactly as
    #    tests/test_run_summary.py's buy_calls fixture does.
    bot.WHATIF_MODE = True
    bot.TRADING_MODE = 'whatif'
    bot.NOTIONAL_USD = notional
    bot.DAILY_SPEND_CAP_USD = cap
    bot.spend_tracker = bot.SpendTracker(cap=100.0, notional=notional)  # run cap wide open
    bot.coinsToBuy = []
    bot.coinsToExclude = set()
    bot.whatif_buys = 0
    bot.daily_cap_blocked = 0
    bot.buy_something = lambda coin: print(f"[UNREACHABLE] buy_something({coin}) "
                                            "-- should never be called: the cap refused first")

    # 3. Force a BUY decision straight into the production gate function --
    #    no LLM call, no panel. This is the exact function real BUY votes
    #    reach after decision_allows_trade() approves them.
    print("[FORCED] Attempting a BUY for BTC (forced decision -- no LLM call)")
    print("-" * 70)
    bot.maybe_execute_buy('BTC')
    print("-" * 70)
    print()
    print(f"Blocked by daily cap: {bot.daily_cap_blocked}")
    print()
    if bot.daily_cap_blocked:
        print("[OK] The [DAILY CAP] refusal fired. No order was placed, "
              "buy_something() was never called, nothing was spent.")
    else:
        print("[UNEXPECTED] The cap did not refuse -- investigate before "
              "trusting this demo's output.")
        sys.exit(1)


if __name__ == '__main__':
    main()
