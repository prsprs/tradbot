"""Tests for T5 (fill confirmation + execution ledger, plan Phase 1).

Covered:
  1. OrderResult mapping helpers (filled / terminal_failure / ledger_status).
  2. coinbaseutil2 unwrap + fill-confirmation against fixtures built from the
     documented EVALUATION_LESSONS_LEARNED 5.5 response shapes -- the create
     response nests order_id/product/side under `success_response` behind a
     top-level `success` boolean, and the fills (status/filled_size/
     average_filled_price/total_fees) come from a follow-up get_order. The
     fill fixture uses the exact 5.5 numbers (filled_size=0.06562167,
     avg=75.28, fees=0.0593). Fixture realism validated against one real
     read-only get_order captured during development (SOL SELL: filled_size,
     average_filled_price, total_fees all strings; `fee` == '').
  3. get_order polling across an OPEN -> FILLED transition; terminal non-FILLED
     (CANCELLED) -> failure; a placed-but-never-confirmed order -> unconfirmed.
  4. Idempotent duplicate handling: a duplicate-client_order_id rejection (both
     the success=false error_response form AND a thrown-exception form) is
     recovered by looking the order up via list_orders (client-side match).
  5. executionledger append/read/positions round trips; positions count only
     confirmed LIVE fills (simulated/what-if and failed excluded).
  6. Daily-cap summation (intended_spend_on_date / daily_cap_would_exceed):
     live-only, per-UTC-date, exact-cap boundary allowed.
  7. What-if synthetic fill rows: status 'simulated', avg_fill_price = ask,
     never counted as a position.

All fixtures are offline; no network, no LLM, no real orders. The Coinbase
client is a fake returning real SDK response objects built from dicts.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import coinbaseutil2
from coinbaseutil2 import BlobbyTrader, OrderResult
import executionledger as led

sys.path.insert(0, str(REPO_ROOT / 'scripts'))
import reconcile_positions

from coinbase.rest.types.orders_types import (
    CreateOrderResponse, GetOrderResponse, ListOrdersResponse,
)


# ============================================================================
# Fixtures modeling the documented 5.5 response shapes
# ============================================================================

CLIENT_ID = 'run_20260718T195400Z-SOL-buy'


def _create_success(order_id='ORDER-SOL-1', product_id='SOL-USD', client_order_id=CLIENT_ID):
    """A successful create: order id / product / side NESTED under
    success_response, gated by a top-level `success` boolean (finding 1.6)."""
    return {
        'success': True,
        'success_response': {
            'order_id': order_id,
            'product_id': product_id,
            'side': 'BUY',
            'client_order_id': client_order_id,
        },
    }


def _create_duplicate_rejection():
    """A create Coinbase rejects as a duplicate client_order_id (success=false
    with an error_response) -- the non-exception duplicate form."""
    return {
        'success': False,
        'error_response': {
            'error': 'DUPLICATE_CLIENT_ORDER_ID',
            'message': 'Order with this client_order_id already exists',
            'new_order_failure_reason': 'DUPLICATE_CLIENT_ORDER_ID',
        },
    }


def _create_generic_failure():
    """A create rejected for a non-duplicate reason (e.g. insufficient funds)."""
    return {
        'success': False,
        'error_response': {
            'error': 'INSUFFICIENT_FUND',
            'message': 'Insufficient balance',
            'new_order_failure_reason': 'INSUFFICIENT_FUND',
        },
    }


def _order_filled(order_id='ORDER-SOL-1', product_id='SOL-USD'):
    """A FILLED get_order body using the exact 5.5 measured numbers. Note the
    numeric fields are STRINGS and `fee` is '' -- both mirror the real
    read-only get_order captured during development."""
    return {'order': {
        'order_id': order_id,
        'product_id': product_id,
        'side': 'BUY',
        'status': 'FILLED',
        'filled_size': '0.06562167',
        'average_filled_price': '75.28',
        'total_fees': '0.0593',
        'fee': '',
        'filled_value': '4.94',
        'number_of_fills': '1',
        'client_order_id': CLIENT_ID,
    }}


def _order_open(order_id='ORDER-SOL-1', product_id='SOL-USD'):
    return {'order': {
        'order_id': order_id,
        'product_id': product_id,
        'side': 'BUY',
        'status': 'OPEN',
        'filled_size': '0',
        'average_filled_price': '0',
    }}


def _order_cancelled(order_id='ORDER-SOL-1', product_id='SOL-USD'):
    return {'order': {
        'order_id': order_id,
        'product_id': product_id,
        'side': 'BUY',
        'status': 'CANCELLED',
        'filled_size': '0',
        'average_filled_price': '0',
        'total_fees': '0',
    }}


class FakeClient:
    """Stand-in for the Coinbase RESTClient returning real SDK response objects.

    get_order pops from a queue so tests can script OPEN -> FILLED. list_orders
    returns whatever orders were seeded for duplicate recovery.
    """
    def __init__(self, create_body=None, get_order_bodies=None,
                 list_orders_body=None, raise_on_create=None, raise_on_list=None):
        self._create_body = create_body or _create_success()
        self._get_order_bodies = list(get_order_bodies or [])
        self._list_orders_body = list_orders_body or {'orders': []}
        self._raise_on_create = raise_on_create
        self._raise_on_list = raise_on_list
        self.create_calls = []
        self.list_calls = []

    def market_order_buy(self, client_order_id, product_id, quote_size, **kw):
        self.create_calls.append(
            {'client_order_id': client_order_id, 'product_id': product_id,
             'quote_size': quote_size})
        if self._raise_on_create is not None:
            raise self._raise_on_create
        return CreateOrderResponse(dict(self._create_body))

    def get_order(self, order_id, **kw):
        if not self._get_order_bodies:
            raise AssertionError('get_order called more times than scripted')
        body = self._get_order_bodies.pop(0)
        return GetOrderResponse(dict(body))

    def list_orders(self, product_ids=None, limit=None, **kw):
        self.list_calls.append({'product_ids': product_ids, 'limit': limit})
        if self._raise_on_list is not None:
            raise self._raise_on_list
        return ListOrdersResponse(dict(self._list_orders_body))


def _trader_with(client):
    """A BlobbyTrader wired to a FakeClient without touching credentials."""
    t = BlobbyTrader.__new__(BlobbyTrader)
    t.client = client
    return t


# ============================================================================
# 1. OrderResult mapping helpers
# ============================================================================

def test_order_result_filled_and_ledger_status():
    r = OrderResult(success=True, order_id='O1', status='FILLED',
                    filled_size=0.1, avg_fill_price=75.28, fees_usd=0.06)
    assert r.filled is True
    assert r.terminal_failure is False
    assert r.ledger_status() == 'filled'


def test_order_result_terminal_failure():
    r = OrderResult(success=True, order_id='O1', status='CANCELLED')
    assert r.filled is False
    assert r.terminal_failure is True
    assert r.ledger_status() == 'failed'


def test_order_result_create_rejected_is_failed():
    r = OrderResult(success=False, failure_reason='INSUFFICIENT_FUND')
    assert r.filled is False
    assert r.terminal_failure is True
    assert r.ledger_status() == 'failed'


def test_order_result_open_is_unconfirmed():
    r = OrderResult(success=True, order_id='O1', status='OPEN')
    assert r.filled is False
    assert r.terminal_failure is False
    assert r.ledger_status() == 'unconfirmed'


def test_order_result_success_no_status_is_unconfirmed():
    """Create succeeded but get_order never returned -> unconfirmed."""
    r = OrderResult(success=True, order_id='O1', status=None)
    assert r.ledger_status() == 'unconfirmed'


# ============================================================================
# 2 & 3. Unwrap + fill confirmation
# ============================================================================

def test_market_order_buy_unwraps_success_response_and_fill():
    client = FakeClient(create_body=_create_success(),
                        get_order_bodies=[_order_filled()])
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00',
                                     run_id='run_20260718T195400Z', coin='SOL',
                                     poll_delay=0)
    assert result.success is True
    # order_id came from success_response, not a top-level key.
    assert result.order_id == 'ORDER-SOL-1'
    assert result.product_id == 'SOL-USD'
    assert result.side == 'BUY'
    # Fill fields came from get_order, coerced from strings to floats.
    assert result.filled is True
    assert result.status == 'FILLED'
    assert result.filled_size == pytest.approx(0.06562167)
    assert result.avg_fill_price == pytest.approx(75.28)
    assert result.fees_usd == pytest.approx(0.0593)


def test_deterministic_client_order_id_is_used():
    client = FakeClient(get_order_bodies=[_order_filled()])
    trader = _trader_with(client)
    trader.market_order_buy('SOL-USD', '5.00', run_id='run_ABC', coin='SOL',
                            poll_delay=0)
    assert client.create_calls[0]['client_order_id'] == 'run_ABC-SOL-buy'


def test_client_order_id_falls_back_to_uuid_without_run_and_coin():
    cid = BlobbyTrader.build_client_order_id(None, None, 'buy')
    # uuid4 string form (has dashes, not the deterministic template)
    assert '-buy' not in cid
    assert len(cid) == 36


def test_fees_prefer_total_fees_over_empty_fee():
    """The real get_order has fee='' and the real value in total_fees."""
    client = FakeClient(get_order_bodies=[_order_filled()])
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.fees_usd == pytest.approx(0.0593)


def test_poll_transitions_open_to_filled():
    client = FakeClient(get_order_bodies=[_order_open(), _order_filled()])
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_tries=3, poll_delay=0)
    assert result.filled is True
    assert result.filled_size == pytest.approx(0.06562167)


def test_poll_exhausted_while_open_is_unconfirmed():
    client = FakeClient(get_order_bodies=[_order_open(), _order_open()])
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_tries=2, poll_delay=0)
    assert result.success is True
    assert result.filled is False
    assert result.ledger_status() == 'unconfirmed'


def test_terminal_cancelled_is_failure():
    client = FakeClient(get_order_bodies=[_order_cancelled()])
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is True       # create was accepted
    assert result.filled is False
    assert result.ledger_status() == 'failed'


def test_generic_create_failure_returns_failure_result():
    client = FakeClient(create_body=_create_generic_failure())
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False
    assert result.filled is False
    assert 'INSUFFICIENT_FUND' in (result.failure_reason or '')


# ============================================================================
# 4. Idempotent duplicate handling
# ============================================================================

def test_duplicate_rejection_recovers_existing_order():
    """success=false DUPLICATE -> look up by client_order_id -> treat as
    success, with the existing order's fills."""
    existing = _order_filled()['order']
    existing['client_order_id'] = CLIENT_ID
    client = FakeClient(
        create_body=_create_duplicate_rejection(),
        list_orders_body={'orders': [existing]},
    )
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00',
                                     run_id='run_20260718T195400Z', coin='SOL',
                                     poll_delay=0)
    assert result.success is True
    assert result.idempotent_reuse is True
    assert result.order_id == 'ORDER-SOL-1'
    assert result.filled is True
    assert result.fees_usd == pytest.approx(0.0593)


def test_duplicate_exception_recovers_existing_order():
    """A thrown duplicate error is recovered the same way."""
    existing = _order_filled()['order']
    existing['client_order_id'] = CLIENT_ID
    client = FakeClient(
        list_orders_body={'orders': [existing]},
        raise_on_create=Exception('duplicate client_order_id already exists'),
    )
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00',
                                     run_id='run_20260718T195400Z', coin='SOL',
                                     poll_delay=0)
    assert result.success is True
    assert result.idempotent_reuse is True
    assert result.order_id == 'ORDER-SOL-1'


def test_duplicate_but_no_matching_order_is_failure():
    """Duplicate rejection with no recoverable order -> surfaced as failure."""
    client = FakeClient(
        create_body=_create_duplicate_rejection(),
        list_orders_body={'orders': []},  # nothing matches
    )
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False


def test_non_duplicate_exception_is_failure_not_recovered():
    client = FakeClient(raise_on_create=Exception('network timeout'))
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False
    assert 'network timeout' in (result.failure_reason or '')


# ============================================================================
# 5. Ledger append / read / positions
# ============================================================================

@pytest.fixture
def ledger_file(tmp_path, monkeypatch):
    """Redirect the ledger to a scratch file for the duration of a test."""
    f = tmp_path / 'executions.json'
    monkeypatch.setattr(led, 'EXECUTIONS_FILE', str(f))
    return f


def test_append_intent_then_fill_round_trip(ledger_file):
    lid = led.append_intent(run_id='run_A', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0,
                            client_order_id='run_A-SOL-buy')
    rows = led.load_executions()
    assert len(rows) == 1
    intent = rows[0]
    assert intent['status'] == 'intent'
    assert intent['coin'] == 'SOL'
    assert intent['side'] == 'BUY'
    assert intent['intended_notional_usd'] == 5.0
    assert intent['client_order_id'] == 'run_A-SOL-buy'

    led.record_fill(lid, status='filled', order_id='O1', filled_size=0.0656,
                    avg_fill_price=75.28, fees_usd=0.0593)
    rows = led.load_executions()
    assert len(rows) == 2
    fill = rows[1]
    assert fill['ledger_id'] == lid
    assert fill['status'] == 'filled'
    assert fill['order_id'] == 'O1'
    assert fill['avg_fill_price'] == 75.28


def test_record_fill_rejects_bad_status(ledger_file):
    lid = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0, client_order_id='c')
    with pytest.raises(ValueError):
        led.record_fill(lid, status='bogus')


def test_positions_count_only_confirmed_live_fills(ledger_file):
    # Two live buys of SOL (filled), one failed, one what-if simulated.
    l1 = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                           intended_notional_usd=5.0, client_order_id='c1')
    led.record_fill(l1, status='filled', filled_size=0.06562167, avg_fill_price=75.28)
    l2 = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                           intended_notional_usd=5.0, client_order_id='c2')
    led.record_fill(l2, status='filled', filled_size=0.06, avg_fill_price=76.0)
    l3 = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                           intended_notional_usd=5.0, client_order_id='c3')
    led.record_fill(l3, status='failed')
    l4 = led.append_intent(run_id='r', trading_mode='whatif', coin='BTC',
                           intended_notional_usd=5.0, client_order_id='c4')
    led.record_fill(l4, status='simulated', avg_fill_price=60000.0)

    pos = led.positions(trading_mode='live')
    assert pos == pytest.approx({'SOL': 0.12562167})
    # what-if never appears as a live position
    assert 'BTC' not in pos


def test_positions_ignore_orphan_fill(ledger_file):
    """A fill row whose intent is missing (crash between) is ignored, not a
    crash."""
    led.record_fill('orphan-ledger-id', status='filled', filled_size=1.0)
    assert led.positions(trading_mode='live') == {}


def test_intent_without_fill_survives_for_reconciliation(ledger_file):
    """A crash after the intent row leaves a reconcilable stub with no fill."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=5.0, client_order_id='c')
    rows = led.load_executions()
    assert len(rows) == 1 and rows[0]['status'] == 'intent'
    # No position yet -- nothing confirmed.
    assert led.positions(trading_mode='live') == {}


# ============================================================================
# 6. Daily-cap summation
# ============================================================================

def _intent(mode, notional, ts):
    return {'status': 'intent', 'trading_mode': mode,
            'intended_notional_usd': notional, 'timestamp': ts}


def test_intended_spend_on_date_live_only_and_dated():
    rows = [
        _intent('live', 5.0, '2026-07-18T10:00:00Z'),
        _intent('live', 5.0, '2026-07-18T20:00:00Z'),
        _intent('whatif', 5.0, '2026-07-18T21:00:00Z'),   # excluded (mode)
        _intent('live', 5.0, '2026-07-19T01:00:00Z'),      # excluded (date)
        {'status': 'filled', 'ledger_id': 'x'},            # not an intent
    ]
    assert led.intended_spend_on_date(rows, '2026-07-18') == pytest.approx(10.0)
    assert led.intended_spend_on_date(rows, '2026-07-19') == pytest.approx(5.0)


def test_daily_cap_would_exceed_boundary(ledger_file):
    now = datetime(2026, 7, 18, 12, 0, 0)
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=10.0, client_order_id='c',
                      timestamp='2026-07-18T09:00:00Z')
    # 10 already committed today; cap 15.
    assert led.daily_cap_would_exceed(5.0, 15.0, now=now) is False   # 15 == cap OK
    assert led.daily_cap_would_exceed(5.01, 15.0, now=now) is True   # 15.01 > cap
    assert led.live_spend_today(now=now) == pytest.approx(10.0)


def test_daily_cap_ignores_whatif(ledger_file):
    now = datetime(2026, 7, 18, 12, 0, 0)
    led.append_intent(run_id='r', trading_mode='whatif', coin='BTC',
                      intended_notional_usd=100.0, client_order_id='c',
                      timestamp='2026-07-18T09:00:00Z')
    assert led.live_spend_today(now=now) == 0.0
    assert led.daily_cap_would_exceed(5.0, 15.0, now=now) is False


# ============================================================================
# 6b. Timestamp format regression guard (datetime.utcnow() -> timezone-aware
# migration, T11). _now_iso() must keep writing a NAIVE ISO-8601 string with
# a literal trailing 'Z' -- no embedded '+00:00' offset -- because
# intended_spend_on_date matches on ts[:10] (a plain 'YYYY-MM-DD' date
# string) and historyutil/tradeanalyzer share this exact on-disk convention.
# A switch to datetime.now(timezone.utc).isoformat() (which appends
# '+00:00') would not break the ts[:10] date match, but WOULD silently
# change every stored timestamp's shape and diverge from historyutil's
# format, which parse_timestamp depends on strip-and-parse-naive for.
# ============================================================================

import re as _re

_NAIVE_Z_TIMESTAMP_RE = _re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$'
)


def test_now_iso_is_naive_with_trailing_z_not_embedded_offset():
    ts = led._now_iso()
    assert _NAIVE_Z_TIMESTAMP_RE.match(ts), (
        f"_now_iso() produced {ts!r}, not a naive 'Z'-suffixed ISO-8601 "
        "string (datetime.now(timezone.utc).isoformat() would add '+00:00')"
    )


def test_append_intent_auto_timestamp_is_same_format_and_datable(ledger_file):
    """append_intent's auto-filled timestamp (no explicit `timestamp=`) must
    still be usable by live_spend_today's UTC-date bucketing."""
    led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                      intended_notional_usd=7.5, client_order_id='c')
    rows = led.load_executions()
    ts = rows[0]['timestamp']
    assert _NAIVE_Z_TIMESTAMP_RE.match(ts)
    # live_spend_today (called with the real current time) must find this
    # row on "today"'s date bucket -- proves ts[:10] still lines up with
    # datetime.now(timezone.utc).strftime('%Y-%m-%d').
    assert led.live_spend_today() == pytest.approx(7.5)


# ============================================================================
# 7. What-if synthetic fill rows
# ============================================================================

def test_whatif_simulated_fill_shape(ledger_file):
    lid = led.append_intent(run_id='r', trading_mode='whatif', coin='BTC',
                            intended_notional_usd=5.0, client_order_id='r-BTC-buy')
    led.record_fill(lid, status='simulated', avg_fill_price=60123.45)
    rows = led.load_executions()
    intent, fill = rows
    assert intent['trading_mode'] == 'whatif'
    assert fill['status'] == 'simulated'
    assert fill['avg_fill_price'] == 60123.45
    assert fill['filled_size'] is None      # no real size for a simulation
    # A simulated fill is never a live position.
    assert led.positions(trading_mode='live') == {}


# ============================================================================
# F2 -- order-create failure must never silently diverge the ledger from reality
# ============================================================================
# The money-path risk (T5 reflection): an ambiguous create timeout whose retry
# isn't recognized as a duplicate gets ledgered 'failed' while the ORIGINAL
# order may have filled -- money spent, ledger wrong. F2: on ANY create failure
# attempt the client_order_id recovery lookup BEFORE writing a failure; when the
# lookup itself can't confirm, ledger a distinct 'unverified_failure' state;
# add reconcile --repair to resolve unconfirmed fills / orphaned + unverified
# intents by re-polling get_order and matching client_order_id.

def test_create_exception_recovers_via_lookup_when_order_exists():
    """An ambiguous create exception (NOT duplicate-looking) whose order
    actually got placed is recovered via the client_order_id lookup -> success,
    not a spurious failure. This is the core F2 fix."""
    existing = _order_filled()['order']
    existing['client_order_id'] = CLIENT_ID
    client = FakeClient(
        list_orders_body={'orders': [existing]},
        raise_on_create=Exception('request timeout'),   # ambiguous, not 'duplicate'
    )
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00',
                                     run_id='run_20260718T195400Z', coin='SOL',
                                     poll_delay=0)
    assert result.success is True
    assert result.idempotent_reuse is True
    assert result.filled is True
    assert result.ledger_status() == 'filled'
    assert client.list_calls, 'recovery lookup should have been attempted'


def test_create_exception_lookup_empty_is_clean_failure():
    """Exception + lookup SUCCEEDS but finds no order -> the order was never
    placed -> clean 'failed' (verified), NOT unverified."""
    client = FakeClient(raise_on_create=Exception('network timeout'),
                        list_orders_body={'orders': []})   # lookup ok, no match
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False
    assert result.unverified is False
    assert result.ledger_status() == 'failed'
    assert 'network timeout' in (result.failure_reason or '')


def test_create_exception_lookup_fails_is_unverified_failure():
    """Exception AND the lookup ITSELF fails (list_orders raises) -> we cannot
    know whether money moved -> 'unverified_failure' (distinct from clean
    failure) so reconcile --repair can hunt it down."""
    client = FakeClient(raise_on_create=Exception('request timeout'),
                        raise_on_list=Exception('503 from list_orders'))
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False
    assert result.unverified is True
    assert result.ledger_status() == 'unverified_failure'


def test_non_exception_failure_lookup_fails_is_unverified():
    """A success=false create whose recovery lookup also fails -> unverified
    (conservative: attempt recovery on ANY create failure, flag when we can't
    confirm)."""
    client = FakeClient(create_body=_create_generic_failure(),
                        raise_on_list=Exception('list_orders down'))
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False
    assert result.unverified is True
    assert result.ledger_status() == 'unverified_failure'


def test_clean_generic_failure_unchanged():
    """A clean rejection (INSUFFICIENT_FUND) with a working lookup that finds
    nothing stays a clean 'failed' -- unchanged from before F2 (the extra
    read-only lookup doesn't alter the verdict)."""
    client = FakeClient(create_body=_create_generic_failure(),
                        list_orders_body={'orders': []})
    trader = _trader_with(client)
    result = trader.market_order_buy('SOL-USD', '5.00', run_id='r', coin='SOL',
                                     poll_delay=0)
    assert result.success is False
    assert result.unverified is False
    assert result.ledger_status() == 'failed'
    assert 'INSUFFICIENT_FUND' in (result.failure_reason or '')


def test_record_fill_accepts_unverified_failure(ledger_file):
    lid = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0, client_order_id='c')
    led.record_fill(lid, status='unverified_failure')
    assert led.load_executions()[-1]['status'] == 'unverified_failure'
    # An unverified failure is never counted as a live position (we don't know
    # if it filled) -- fail-safe until reconcile --repair resolves it.
    assert led.positions(trading_mode='live') == {}


def test_normal_fill_has_no_repaired_via(ledger_file):
    """The normal write path keeps its exact prior row shape (no provenance)."""
    lid = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0, client_order_id='c')
    led.record_fill(lid, status='filled', filled_size=0.06, avg_fill_price=75.0)
    assert 'repaired_via' not in led.load_executions()[-1]


# ---- reconcile --repair -----------------------------------------------------

class FakeResolver:
    """In-memory stand-in for reconcile --repair's read-only exchange access.

    poll_order_status(order_id) and find_order_by_client_order_id(coin, coid)
    return an OrderResult (or None). Places nothing. No network."""
    def __init__(self, by_order_id=None, by_coid=None):
        self._by_order_id = by_order_id or {}
        self._by_coid = by_coid or {}
        self.poll_calls = []
        self.find_calls = []

    def poll_order_status(self, order_id):
        self.poll_calls.append(order_id)
        return self._by_order_id.get(order_id)

    def find_order_by_client_order_id(self, coin, client_order_id):
        self.find_calls.append((coin, client_order_id))
        return self._by_coid.get((coin, client_order_id))


def test_find_repair_targets_skips_resolved_and_whatif():
    rows = [
        # live filled -> resolved, skipped
        {'status': 'intent', 'ledger_id': 'a', 'trading_mode': 'live', 'coin': 'SOL',
         'client_order_id': 'a', 'side': 'BUY', 'run_id': 'r'},
        {'status': 'filled', 'ledger_id': 'a', 'filled_size': 1.0},
        # live unconfirmed -> target
        {'status': 'intent', 'ledger_id': 'b', 'trading_mode': 'live', 'coin': 'ETH',
         'client_order_id': 'b', 'side': 'BUY', 'run_id': 'r'},
        {'status': 'unconfirmed', 'ledger_id': 'b', 'order_id': 'O-b'},
        # live orphan intent (no fill) -> target
        {'status': 'intent', 'ledger_id': 'c', 'trading_mode': 'live', 'coin': 'DOGE',
         'client_order_id': 'c', 'side': 'BUY', 'run_id': 'r'},
        # whatif unconfirmed -> skipped (not a live order)
        {'status': 'intent', 'ledger_id': 'd', 'trading_mode': 'whatif', 'coin': 'BTC',
         'client_order_id': 'd', 'side': 'BUY', 'run_id': 'r'},
        {'status': 'unconfirmed', 'ledger_id': 'd', 'order_id': 'O-d'},
    ]
    targets = led.find_repair_targets(rows)
    assert {t['ledger_id']: t['kind'] for t in targets} == {
        'b': 'unconfirmed', 'c': 'orphan_intent'}


def test_repair_resolves_unconfirmed_fill(ledger_file):
    """An 'unconfirmed' fill is re-polled via get_order; a now-FILLED order
    appends a corrected 'filled' row (repair provenance) and becomes a position.
    A second pass is idempotent."""
    lid = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0, client_order_id='r-SOL-buy')
    led.record_fill(lid, status='unconfirmed', order_id='ORDER-SOL-1')
    assert led.positions(trading_mode='live') == {}   # not counted while unconfirmed

    targets = led.find_repair_targets(led.load_executions())
    assert len(targets) == 1 and targets[0]['kind'] == 'unconfirmed'

    filled = OrderResult(success=True, order_id='ORDER-SOL-1', status='FILLED',
                         filled_size=0.0656, avg_fill_price=75.28, fees_usd=0.0593)
    resolver = FakeResolver(by_order_id={'ORDER-SOL-1': filled})
    results = reconcile_positions.apply_repairs(targets, resolver)
    assert results[0]['action'] == 'repaired' and results[0]['status'] == 'filled'
    assert resolver.poll_calls == ['ORDER-SOL-1']

    repaired = led.load_executions()[-1]
    assert repaired['status'] == 'filled'
    assert repaired['repaired_via'] == 'get_order'
    assert repaired['ledger_id'] == lid
    assert led.positions(trading_mode='live') == pytest.approx({'SOL': 0.0656})
    # Idempotent: nothing left to repair.
    assert led.find_repair_targets(led.load_executions()) == []


def test_repair_resolves_orphaned_intent(ledger_file):
    """An intent with NO fill row (crash between) is resolved via the
    client_order_id lookup."""
    lid = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0, client_order_id='r-SOL-buy')
    targets = led.find_repair_targets(led.load_executions())
    assert len(targets) == 1 and targets[0]['kind'] == 'orphan_intent'

    found = OrderResult(success=True, order_id='ORDER-SOL-9', status='FILLED',
                        filled_size=0.06, avg_fill_price=76.0, fees_usd=0.05)
    resolver = FakeResolver(by_coid={('SOL', 'r-SOL-buy'): found})
    results = reconcile_positions.apply_repairs(targets, resolver)
    assert results[0]['action'] == 'repaired'
    assert results[0]['via'] == 'client_order_id_lookup'
    repaired = led.load_executions()[-1]
    assert repaired['status'] == 'filled'
    assert repaired['repaired_via'] == 'client_order_id_lookup'
    assert led.positions(trading_mode='live') == pytest.approx({'SOL': 0.06})


def test_repair_resolves_unverified_failure(ledger_file):
    """An 'unverified_failure' row is resolved by the client_order_id lookup;
    an order that actually filled becomes a corrected 'filled' row + position."""
    lid = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                            intended_notional_usd=5.0, client_order_id='r-SOL-buy')
    led.record_fill(lid, status='unverified_failure')
    targets = led.find_repair_targets(led.load_executions())
    assert targets[0]['kind'] == 'unverified_failure'

    found = OrderResult(success=True, order_id='ORDER-SOL-7', status='FILLED',
                        filled_size=0.066, avg_fill_price=75.0, fees_usd=0.06)
    resolver = FakeResolver(by_coid={('SOL', 'r-SOL-buy'): found})
    results = reconcile_positions.apply_repairs(targets, resolver)
    assert results[0]['action'] == 'repaired'
    assert led.positions(trading_mode='live') == pytest.approx({'SOL': 0.066})


def test_repair_leaves_still_open_and_unresolved(ledger_file):
    """An unconfirmed order still OPEN, and an orphan the exchange can't find,
    write NO corrected row -- revisited on a later pass."""
    l1 = led.append_intent(run_id='r', trading_mode='live', coin='SOL',
                           intended_notional_usd=5.0, client_order_id='r-SOL-buy')
    led.record_fill(l1, status='unconfirmed', order_id='OPEN-1')
    l2 = led.append_intent(run_id='r', trading_mode='live', coin='ETH',
                           intended_notional_usd=5.0, client_order_id='r-ETH-buy')
    targets = led.find_repair_targets(led.load_executions())
    still_open = OrderResult(success=True, order_id='OPEN-1', status='OPEN')
    resolver = FakeResolver(by_order_id={'OPEN-1': still_open})  # ETH lookup -> None
    before = len(led.load_executions())
    results = reconcile_positions.apply_repairs(targets, resolver)
    actions = {r['ledger_id']: r['action'] for r in results}
    assert actions[l1] == 'still_open'
    assert actions[l2] == 'unresolved'
    assert len(led.load_executions()) == before   # nothing appended
