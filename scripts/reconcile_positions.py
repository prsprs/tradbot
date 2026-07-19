#!/usr/bin/env python3
"""Position reconciliation (T5, plan Phase 1): bot-attributed positions vs.
read-only Coinbase account balances.

The bot's execution ledger (executionledger.py) records what the BOT bought;
`get_accounts` reports what the ACCOUNT actually holds. These are NOT the same
thing -- the account also holds legacy positions the bot never bought (and, per
EVALUATION_LESSONS_LEARNED 5.5, manual trades). This script prints both side by
side and flags the drift, with a loud disclaimer that bot positions are an
attribution, not account truth.

READ-ONLY by default: reads the ledger and calls get_accounts only.

--repair (F2): additionally hunt down ledger rows that may have diverged from
the exchange -- 'unconfirmed' fills (order placed, fill never confirmed;
nothing else re-polls these), 'unverified_failure' rows (create failed and the
lookup couldn't confirm placement), and orphaned intent rows (a crash between
the intent and fill writes) -- by RE-POLLING get_order and matching by
client_order_id, then APPENDING corrected fill rows (append-only, never
rewriting history, each tagged with a `repaired_via` provenance field).
--repair still PLACES NOTHING: it makes read-only exchange calls plus local
ledger writes only.

Usage:
    ./venv/bin/python scripts/reconcile_positions.py
    ./venv/bin/python scripts/reconcile_positions.py --repair
    HISTORY_DIR=/path/to/scratch ./venv/bin/python scripts/reconcile_positions.py

Exit code is always 0 (a reconciliation report is informational, not a
pass/fail gate).
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import executionledger


# USD-ish quote currencies we don't treat as tradeable "positions".
_CASH_CURRENCIES = {'USD', 'USDC', 'USDT'}


def _fmt(value):
    """Compact numeric formatting for small crypto sizes."""
    if value is None:
        return '-'
    if abs(value) >= 1:
        return f'{value:.6f}'
    return f'{value:.8f}'


def reconcile(bot_positions, account_balances):
    """Build reconciliation rows from bot positions and account balances.

    Returns a list of dicts: {coin, bot_size, account_balance, flag}. `flag` is
    one of:
      * 'ok'                 -- bot and account agree (within tolerance)
      * 'bot-unknown balance'-- account holds it, the bot never bought it
                                (legacy/manual position)
      * 'drift'              -- both hold it but sizes differ
      * 'bot-only'           -- bot thinks it holds it, account shows none
    """
    coins = set(bot_positions) | set(account_balances)
    coins -= _CASH_CURRENCIES
    rows = []
    for coin in sorted(coins):
        bot_size = bot_positions.get(coin)
        acct = account_balances.get(coin)
        if bot_size and acct is None:
            flag = 'bot-only'
        elif not bot_size and acct:
            flag = 'bot-unknown balance'
        elif bot_size and acct is not None:
            flag = 'ok' if abs(bot_size - acct) <= 1e-8 else 'drift'
        else:
            flag = 'ok'
        rows.append({
            'coin': coin,
            'bot_size': bot_size,
            'account_balance': acct,
            'flag': flag,
        })
    return rows


def apply_repairs(targets, resolver, ledger=executionledger):
    """Resolve repair targets against the exchange (READ-ONLY) and append
    corrected ledger rows (F2). Returns a list of per-target result dicts.

    `resolver` must provide two READ-ONLY methods (BlobbyTrader implements both;
    tests inject an in-memory fake):
      * poll_order_status(order_id) -> OrderResult | None    (get_order)
      * find_order_by_client_order_id(coin, client_order_id) -> OrderResult | None

    Neither places or modifies an order. A corrected fill row is written ONLY
    when the exchange reports something terminal (a confirmed FILL, or a
    verified terminal failure); a still-open / still-unresolvable target is left
    for a later pass. The corrected row is a NEW append carrying the original
    ledger_id plus a `repaired_via` provenance field -- history rows are never
    rewritten.
    """
    results = []
    for t in targets:
        lid = t['ledger_id']
        order = None
        via = None
        # 'unconfirmed' rows carry a real order_id -> re-poll get_order first.
        if t.get('kind') == 'unconfirmed' and t.get('order_id'):
            order = resolver.poll_order_status(t['order_id'])
            via = 'get_order'
        # Orphans, unverified failures, and unconfirmed rows whose order_id did
        # not resolve fall back to the client_order_id lookup.
        if order is None and t.get('client_order_id'):
            order = resolver.find_order_by_client_order_id(t['coin'], t['client_order_id'])
            via = 'client_order_id_lookup'
        if order is None:
            results.append({'ledger_id': lid, 'kind': t['kind'], 'action': 'unresolved'})
            continue
        status = order.ledger_status()
        if status in (executionledger.FILLED, executionledger.FAILED):
            ledger.record_fill(
                lid, status=status, order_id=order.order_id,
                filled_size=order.filled_size, avg_fill_price=order.avg_fill_price,
                fees_usd=order.fees_usd, repaired_via=via)
            results.append({'ledger_id': lid, 'kind': t['kind'], 'action': 'repaired',
                            'status': status, 'via': via})
        else:
            # Still OPEN / still unverifiable -> record nothing, revisit later.
            results.append({'ledger_id': lid, 'kind': t['kind'],
                            'action': 'still_open', 'status': status})
    return results


def _print_repair_report(targets, results):
    print("=" * 72)
    print("LEDGER REPAIR (--repair) -- read-only exchange calls + ledger appends")
    print("=" * 72)
    print("Places NOTHING. Re-polls unconfirmed fills and resolves orphaned /")
    print("unverified intents by client_order_id, appending corrected rows")
    print("(never rewriting history) with a `repaired_via` provenance field.")
    print("-" * 72)
    if not targets:
        print("No repairable rows found (no unconfirmed / unverified / orphaned")
        print("live ledger_ids).")
        print("=" * 72)
        return
    repaired = [r for r in results if r['action'] == 'repaired']
    still = [r for r in results if r['action'] == 'still_open']
    unresolved = [r for r in results if r['action'] == 'unresolved']
    for r in results:
        detail = r.get('status', '')
        via = f" via {r['via']}" if r.get('via') else ''
        print(f"  {r['ledger_id']}  [{r['kind']}] -> {r['action']}"
              f"{(': ' + detail) if detail else ''}{via}")
    print("-" * 72)
    print(f"Targets: {len(targets)} | repaired: {len(repaired)} | "
          f"still-open: {len(still)} | unresolved: {len(unresolved)}")
    print("=" * 72)


def _print_report(rows, account_available):
    print("=" * 72)
    print("POSITION RECONCILIATION -- bot-attributed positions vs. account truth")
    print("=" * 72)
    print("DISCLAIMER: 'Bot' positions are derived from the execution ledger")
    print("(confirmed LIVE fills only). They are an ATTRIBUTION, not account")
    print("truth: legacy holdings and manual trades appear only under 'Account'.")
    print("-" * 72)
    if not account_available:
        print("NOTE: account balances unavailable (get_accounts failed or no")
        print("credentials) -- showing bot positions only.")
        print("-" * 72)
    print(f"{'Coin':<10}{'Bot (ledger)':>18}{'Account':>18}   Flag")
    print("-" * 72)
    if not rows:
        print("(no positions on either side)")
    for r in rows:
        print(f"{r['coin']:<10}{_fmt(r['bot_size']):>18}{_fmt(r['account_balance']):>18}"
              f"   {r['flag']}")
    print("-" * 72)
    drift = [r for r in rows if r['flag'] in ('drift', 'bot-only')]
    legacy = [r for r in rows if r['flag'] == 'bot-unknown balance']
    print(f"Legacy/manual (bot-unknown balance): {len(legacy)}"
          + (f"  -> {', '.join(r['coin'] for r in legacy)}" if legacy else ""))
    print(f"Drift (bot vs account mismatch):     {len(drift)}"
          + (f"  -> {', '.join(r['coin'] for r in drift)}" if drift else ""))
    print("=" * 72)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-accounts', action='store_true',
                        help='Skip the Coinbase get_accounts call (ledger positions only).')
    parser.add_argument('--repair', action='store_true',
                        help='Re-poll unconfirmed fills and resolve orphaned / '
                             'unverified intents via the client_order_id lookup, '
                             'appending corrected ledger rows (read-only exchange '
                             'calls + ledger writes; PLACES NOTHING).')
    args = parser.parse_args(argv)

    print(f"[reconcile] execution ledger: {executionledger.EXECUTIONS_FILE}")

    # --repair runs FIRST so the position report below reflects any corrections.
    if args.repair:
        targets = executionledger.find_repair_targets(executionledger.load_executions())
        if not targets:
            _print_repair_report(targets, [])
        else:
            try:
                from coinbaseutil2 import BlobbyTrader
                trader = BlobbyTrader()
                results = apply_repairs(targets, trader)
                _print_repair_report(targets, results)
            except Exception as e:
                print(f"[reconcile] --repair skipped (could not reach exchange, "
                      f"read-only): {e}")

    bot_positions = executionledger.positions(trading_mode='live')

    account_balances = {}
    account_available = False
    if not args.no_accounts:
        try:
            from coinbaseutil2 import BlobbyTrader
            trader = BlobbyTrader()
            account_balances = trader.list_account_balances(nonzero_only=True)
            account_available = True
        except Exception as e:
            print(f"[reconcile] could not read account balances (read-only): {e}")

    rows = reconcile(bot_positions, account_balances)
    _print_report(rows, account_available)
    return 0


if __name__ == '__main__':
    sys.exit(main())
