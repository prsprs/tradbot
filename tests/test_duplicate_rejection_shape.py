"""Pin the REAL Coinbase duplicate-client_order_id behavior (captured live,
RUNBOOK_live_acceptance.md §7, 2026-07-19).

Finding: Coinbase does not error on a duplicate client_order_id -- it returns
success=true with the ORIGINAL order_id (idempotent dedupe, no second fill).
There is no error text, so _looks_like_duplicate cannot fire on the real
duplicate shape; the reliable duplicate signal is the returned order_id
matching the ledger's existing order_id for that client_order_id.
"""
import json
from pathlib import Path

from coinbaseutil2 import BlobbyTrader

FIXTURE = Path(__file__).parent / "fixtures" / "coinbase" / "duplicate_rejection.json"


def _load():
    return json.loads(FIXTURE.read_text())


def test_duplicate_resubmit_is_idempotent_success_not_error():
    fx = _load()
    resp = fx["duplicate_resubmit_response"]
    assert resp["success"] is True
    assert "error_response" not in resp
    # Same order_id as the original fill -- no second order was created.
    assert (resp["success_response"]["order_id"]
            == fx["_original_fill"]["order_id"])
    assert (resp["success_response"]["client_order_id"]
            == fx["_original_fill"]["client_order_id"])


def test_looks_like_duplicate_cannot_fire_on_real_duplicate_shape():
    # The real duplicate response carries no error text at all, so the
    # annotation heuristic has nothing to match. This is expected: recovery
    # is not gated on the heuristic (F2), and duplicate detection must key on
    # order_id identity, not error strings.
    assert BlobbyTrader._looks_like_duplicate("") is False
    assert BlobbyTrader._looks_like_duplicate(None) is False
    # It still recognizes textual duplicate errors should Coinbase ever
    # return one (e.g. from a different endpoint or API version).
    assert BlobbyTrader._looks_like_duplicate("DUPLICATE_CLIENT_ORDER_ID") is True


# ============================================================================
# MP-1 (audit 2026-07-19): the ledger now ACTS on the real duplicate signal.
# The fixture pins the exact live-captured shape; these tests pin what the
# execution ledger does when that shape reaches record_fill: the repeat row is
# marked duplicate_of the original and excluded from positions and cap sums.
# ============================================================================
import pytest

import executionledger as led


@pytest.fixture
def ledger_file(tmp_path, monkeypatch):
    f = tmp_path / "executions.json"
    monkeypatch.setattr(led, "EXECUTIONS_FILE", str(f))
    return f


def test_ledger_marks_real_duplicate_shape_and_counts_position_once(ledger_file):
    """End-to-end with the fixture's REAL values: run 1 fills; run 2 resubmits
    the same client_order_id and gets back the ORIGINAL order_id
    (success:true, no error). The second fill row is marked duplicate_of and
    the position/cap tallies count the one real order exactly once."""
    fx = _load()
    original = fx["_original_fill"]
    dup_resp = fx["duplicate_resubmit_response"]["success_response"]

    # Run 1: the real fill.
    l1 = led.append_intent(run_id="run_1", trading_mode="live", coin="ETH",
                           intended_notional_usd=5.0,
                           client_order_id=original["client_order_id"])
    led.record_fill(l1, status="filled", order_id=original["order_id"],
                    filled_size=original["filled_size"],
                    avg_fill_price=original["avg_price"])

    # Run 2: resubmit -> Coinbase returns the ORIGINAL order_id (the fixture
    # shape) -- this is the ONLY duplicate signal (no error text exists).
    assert dup_resp["order_id"] == original["order_id"]
    l2 = led.append_intent(run_id="run_2", trading_mode="live", coin="ETH",
                           intended_notional_usd=5.0,
                           client_order_id=dup_resp["client_order_id"])
    dup_row = led.record_fill(l2, status="filled", order_id=dup_resp["order_id"],
                              filled_size=original["filled_size"],
                              avg_fill_price=original["avg_price"])

    assert dup_row["duplicate_of"] == l1
    # One real order -> one position, once.
    assert led.positions(trading_mode="live") == pytest.approx(
        {"ETH": float(original["filled_size"])})
    # ...and the duplicate attempt does not consume the daily cap twice.
    assert led.live_spend_today() == pytest.approx(5.0)
