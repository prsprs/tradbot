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
