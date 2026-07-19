from coinbase.rest import RESTClient
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Default path for Coinbase credentials JSON file
DEFAULT_CREDENTIALS_PATH = "cdp_api_key.json"

# Coinbase order statuses that mean "still working" -- keep polling.
_OPEN_STATUSES = frozenset({'OPEN', 'PENDING', 'QUEUED'})
# The one status that means a real, complete fill.
_FILLED_STATUS = 'FILLED'


def _to_float(value):
    """Best-effort float coercion tolerant of None / '' (Coinbase returns
    numeric fields as strings)."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _na(value):
    """Render None as 'N/A' for logging; pass everything else through."""
    return 'N/A' if value is None else value


@dataclass
class OrderResult:
    """Structured outcome of a market_order_buy (T5, plan Phase 1).

    The Coinbase create-order response nests the order id and product under
    `success_response` and carries a top-level `success` boolean; the fill
    details (size, price, fees) are NOT in the create response and require a
    follow-up get_order call (EVALUATION_LESSONS_LEARNED 1.6 / 5.5). This
    object is what market_order_buy returns after unwrapping the create
    response AND polling get_order, so the caller never has to know the shapes.

    The caller MUST distinguish success from failure:
      * `success`  -- Coinbase accepted the create (top-level `success` true),
                      OR an idempotent duplicate lookup recovered the order.
      * `filled`   -- get_order later confirmed status == FILLED. A successful
                      create that never confirms a fill is success=True,
                      filled=False (status may be OPEN/None) -- treat as
                      unconfirmed, not as money spent-and-settled.
      * a create that Coinbase rejected is success=False with failure_reason.
    """
    success: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    product_id: Optional[str] = None
    side: Optional[str] = None
    status: Optional[str] = None            # get_order status, e.g. FILLED/OPEN/CANCELLED
    filled_size: Optional[float] = None
    avg_fill_price: Optional[float] = None
    fees_usd: Optional[float] = None
    filled_value: Optional[float] = None
    failure_reason: Optional[str] = None
    idempotent_reuse: bool = False          # True when recovered via duplicate lookup
    unverified: bool = False                # True when a create failed AND the
                                            # client_order_id lookup ITSELF failed,
                                            # so we cannot know whether the order
                                            # was actually placed/filled (F2). Maps
                                            # to the ledger 'unverified_failure'
                                            # state -- reconcile --repair resolves it.
    raw_create: Optional[Dict[str, Any]] = None
    raw_order: Optional[Dict[str, Any]] = None

    @property
    def filled(self) -> bool:
        """True only when get_order confirmed a complete FILLED status."""
        return bool(self.success and self.status == _FILLED_STATUS)

    @property
    def terminal_failure(self) -> bool:
        """True when the order will never fill: the create was rejected, or
        get_order reported a terminal non-FILLED status (CANCELLED/REJECTED/
        EXPIRED/FAILED)."""
        if not self.success:
            return True
        if self.status is None:
            return False
        return self.status not in _OPEN_STATUSES and self.status != _FILLED_STATUS

    def ledger_status(self) -> str:
        """Map this result to an executionledger fill status.

        FILLED -> 'filled'; a create failure we could NOT verify against the
        exchange (client_order_id lookup itself failed) -> 'unverified_failure'
        (distinct from a clean failure -- the order MAY have filled; F2); a
        rejected create or terminal non-FILLED status we DID verify ->
        'failed'; a placed-but-unconfirmed order (still OPEN, or fill poll
        exhausted) -> 'unconfirmed'.
        """
        if self.filled:
            return 'filled'
        if self.unverified:
            return 'unverified_failure'
        if self.terminal_failure:
            return 'failed'
        return 'unconfirmed'

class BlobbyTrader:
    def __init__(self, credentials_path=None):
        """Initialize the Coinbase REST client with API credentials from JSON file.
        
        Args:
            credentials_path: Path to the Coinbase CDP JSON credentials file.
                            Defaults to 'cdp_api_key.json' in the current directory,
                            or can be set via COINBASE_CREDENTIALS_FILE env var.
        """
        # Determine credentials file path
        if credentials_path is None:
            credentials_path = os.environ.get('COINBASE_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_PATH)
        
        # Load credentials from JSON file
        try:
            with open(credentials_path, 'r') as f:
                creds = json.load(f)
            
            api_key = creds['name']
            api_secret = creds['privateKey']
            
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)
            print(f"Coinbase client initialized from {credentials_path}")
            
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Coinbase credentials file not found: {credentials_path}\n"
                "Download your API key JSON from https://cloud.coinbase.com/access/api"
            )
        except KeyError as e:
            raise ValueError(f"Invalid credentials file format, missing key: {e}")
    
    def get_product_details(self, product_id):
        """Get details for a specific product (e.g., 'BTC-USD')."""
        try:
            product = self.client.get_product(product_id)
            return product
        except Exception as e:
            print(f"Error getting product details for {product_id}: {e}")
            return None
    
    @staticmethod
    def build_client_order_id(run_id=None, coin=None, intent='buy'):
        """Deterministic client_order_id for idempotency (T5).

        `f"{run_id}-{coin}-{intent}"` -- deterministic per (run, coin, intent)
        so a retry of the *same* buy reuses the id and Coinbase dedupes it
        (finding 2.5: a fresh uuid4 per call could double-buy a timed-out-but-
        filled order). Falls back to a uuid4 only when run_id or coin is
        absent, preserving the old behavior for callers that don't pass them.
        """
        if run_id and coin:
            return f"{run_id}-{coin}-{intent}"
        return str(uuid.uuid4())

    def list_account_balances(self, nonzero_only=True):
        """Read-only: map currency -> available balance (float) from get_accounts.

        Used by scripts/reconcile_positions.py to compare account truth against
        the bot's attributed positions. Read-only; never places or modifies an
        order.
        """
        balances = {}
        try:
            resp = self.client.get_accounts(limit=250)
        except Exception as e:
            print(f"Error fetching accounts: {e}")
            return balances
        for acct in getattr(resp, 'accounts', []) or []:
            acct_dict = acct.to_dict() if hasattr(acct, 'to_dict') else dict(acct)
            currency = acct_dict.get('currency')
            avail = acct_dict.get('available_balance') or {}
            if isinstance(avail, dict):
                value = _to_float(avail.get('value'))
            else:
                value = _to_float(avail)
            if currency is None or value is None:
                continue
            if nonzero_only and value == 0:
                continue
            balances[currency] = balances.get(currency, 0.0) + value
        return balances

    def market_order_buy(self, product_id, quote_size, run_id=None, coin=None,
                         client_order_id=None, poll_tries=3, poll_delay=2.0):
        """Place a market buy and return a confirmed, structured OrderResult.

        Contract (T5, plan Phase 1; EVALUATION_LESSONS_LEARNED 1.6 / 5.5):
          1. Uses a DETERMINISTIC client_order_id = f"{run_id}-{coin}-buy"
             (build_client_order_id) so a retry is idempotent; a caller may
             override with an explicit client_order_id.
          2. Unwraps the create response: the order id / product / side are
             nested under `success_response`, gated by the top-level `success`
             boolean. success=False returns a FAILURE result (caller must
             check .success / .filled).
          3. IDEMPOTENCY: if Coinbase rejects the create as a duplicate
             client_order_id, the existing order is looked up (by
             client_order_id via list_orders, filtered client-side) and
             returned as success -- a retry never double-buys.
          4. Polls get_order(order_id) a few short times (poll_tries x
             poll_delay s) while the order is OPEN/PENDING, to capture status,
             filled_size, average_filled_price and total_fees.

        Returns an OrderResult (never None). The caller distinguishes
        success/filled/failed via the object's fields and helpers.
        """
        client_order_id = client_order_id or self.build_client_order_id(run_id, coin, 'buy')
        try:
            resp = self.client.market_order_buy(
                client_order_id=client_order_id,
                product_id=product_id,
                quote_size=quote_size,
            )
        except Exception as e:
            # MONEY PATH (F2): an ambiguous create failure (timeout, network
            # blip, thrown duplicate rejection) may have ACTUALLY PLACED the
            # order. Attempt the client_order_id recovery lookup on ANY
            # exception -- not just ones whose text "looks like" a duplicate --
            # BEFORE writing a failure, so a filled order is never ledgered as
            # a clean failure.
            print(f"Error placing market buy order for {product_id}: {e}")
            return self._resolve_create_failure(
                product_id, client_order_id, f'exception: {e}',
                poll_tries=poll_tries, poll_delay=poll_delay)

        result = self._result_from_create(resp, client_order_id)

        # A create Coinbase rejected (success=false) -- for ANY reason, not just
        # a DUPLICATE-looking one -- gets the same recovery lookup. A genuine
        # rejection (e.g. INSUFFICIENT_FUND) finds no order and stays a clean
        # failure; a duplicate finds and returns the existing order.
        if not result.success:
            return self._resolve_create_failure(
                product_id, client_order_id, result.failure_reason,
                poll_tries=poll_tries, poll_delay=poll_delay)

        print(f"Market buy order placed: {product_id} for ${quote_size} "
              f"(client_order_id={client_order_id})")

        if result.success and result.order_id:
            self._poll_fill(result, tries=poll_tries, delay=poll_delay)

        self._log_order_result(result)
        return result

    def _resolve_create_failure(self, product_id, client_order_id, failure_reason,
                                poll_tries=3, poll_delay=2.0):
        """Resolve a create failure via the client_order_id recovery lookup (F2).

        Three outcomes:
          * lookup FINDS the order   -> success path: return the recovered
            OrderResult (fill fields from the found order, get_order-polled if
            still open). A retry / ambiguous timeout that actually placed the
            order is thereby never ledgered as a failure.
          * lookup SUCCEEDS, no match -> the order was genuinely not placed:
            a CLEAN failure (success=False, unverified=False -> ledger 'failed').
          * lookup ITSELF FAILS       -> we cannot verify whether the order was
            placed: an UNVERIFIED failure (unverified=True -> ledger
            'unverified_failure') so reconcile --repair can resolve it later.
        """
        recovered, lookup_ok = self._recover_order(
            product_id, client_order_id, poll_tries=poll_tries, poll_delay=poll_delay)
        if recovered is not None:
            self._log_order_result(recovered)
            return recovered
        result = OrderResult(success=False, client_order_id=client_order_id,
                             product_id=product_id, side='BUY',
                             failure_reason=failure_reason,
                             unverified=not lookup_ok)
        if not lookup_ok:
            print(f"[ORDER] UNVERIFIED create failure for {product_id} "
                  f"(client_order_id={client_order_id}): lookup could not confirm "
                  f"whether the order was placed -- ledgering 'unverified_failure' "
                  f"for reconcile --repair.")
        self._log_order_result(result)
        return result

    def _result_from_create(self, resp, client_order_id):
        """Unwrap a CreateOrderResponse into an OrderResult (no polling yet)."""
        create_dict = resp.to_dict() if hasattr(resp, 'to_dict') else dict(resp or {})
        success = bool(create_dict.get('success'))
        success_response = create_dict.get('success_response') or {}
        error_response = create_dict.get('error_response') or {}

        order_id = success_response.get('order_id') or create_dict.get('order_id')
        product_id = success_response.get('product_id')
        side = success_response.get('side') or 'BUY'

        failure_reason = None
        if not success:
            # Coinbase spreads the reason across several fields; capture whatever
            # is present so the caller (and the duplicate check) can see it.
            failure_reason = (
                error_response.get('error')
                or error_response.get('new_order_failure_reason')
                or error_response.get('preview_failure_reason')
                or error_response.get('message')
                or create_dict.get('failure_reason')
                or 'unknown_create_failure'
            )

        return OrderResult(
            success=success,
            order_id=order_id,
            client_order_id=success_response.get('client_order_id') or client_order_id,
            product_id=product_id,
            side=side,
            failure_reason=failure_reason,
            raw_create=create_dict,
        )

    def _poll_fill(self, result, tries=3, delay=2.0):
        """Poll get_order into `result` while the order is OPEN/PENDING.

        Mutates `result` in place with status / filled_size /
        average_filled_price / total_fees from the freshest get_order snapshot.
        Stops early once the status is terminal (FILLED or a terminal failure).
        Leaves result.status None (=> 'unconfirmed') if get_order never returns.
        """
        for attempt in range(max(1, tries)):
            order = self._get_order(result.order_id)
            if order is not None:
                self._apply_order(result, order)
                if result.status not in _OPEN_STATUSES:
                    return
            if attempt < tries - 1 and delay > 0:
                time.sleep(delay)

    def _apply_order(self, result, order):
        """Copy fill fields from a get_order Order onto an OrderResult."""
        order_dict = order.to_dict() if hasattr(order, 'to_dict') else dict(order)
        result.raw_order = order_dict
        result.status = order_dict.get('status', result.status)
        result.filled_size = _to_float(order_dict.get('filled_size'))
        result.avg_fill_price = _to_float(order_dict.get('average_filled_price'))
        result.filled_value = _to_float(order_dict.get('filled_value'))
        # total_fees is the summed commission; fall back to `fee` if absent.
        fees = order_dict.get('total_fees')
        if fees is None:
            fees = order_dict.get('fee')
        result.fees_usd = _to_float(fees)
        if not result.product_id:
            result.product_id = order_dict.get('product_id')

    def _get_order(self, order_id):
        """Read-only get_order; returns the Order object or None on error."""
        if not order_id:
            return None
        try:
            resp = self.client.get_order(order_id)
            return getattr(resp, 'order', None)
        except Exception as e:
            print(f"[ORDER] get_order({order_id}) failed: {e}")
            return None

    @staticmethod
    def _looks_like_duplicate(text):
        """Heuristic: does this error string signal a duplicate client_order_id?

        NOTE (F2): recovery is NO LONGER gated on this heuristic -- every create
        failure now attempts the recovery lookup. This is kept only to ANNOTATE
        logs (a duplicate-looking rejection where recovery finds the order is
        the expected idempotent case). VALIDATED LIVE 2026-07-19 (runbook §7,
        fixture tests/fixtures/coinbase/duplicate_rejection.json): Coinbase
        does NOT error on a duplicate client_order_id -- it returns
        success=true with the ORIGINAL order_id and no error text, so this
        heuristic never fires on the real duplicate shape. Duplicate detection
        must key on order_id identity vs the ledger, not error strings.
        """
        if not text:
            return False
        low = str(text).lower()
        return 'duplicate' in low or 'client_order_id' in low and 'exist' in low

    def _recover_order(self, product_id, client_order_id, poll_tries=3, poll_delay=2.0):
        """Recover an already-placed order by client_order_id after a create
        failure (F2 generalization of the old _recover_duplicate).

        Returns (result, lookup_ok):
          * (OrderResult, True)  -- an order matching client_order_id was found;
            returned as a successful, idempotent-reuse OrderResult with the
            found order's fill fields, get_order-polled if still open.
          * (None, True)         -- the lookup SUCCEEDED but no order matched:
            the order was genuinely never placed (caller -> clean failure).
          * (None, False)        -- the lookup ITSELF failed (list_orders threw):
            we cannot know whether the order exists (caller -> unverified
            failure).

        NOTE: the Coinbase SDK's list_orders has NO client_order_id filter
        (verified against the installed SDK), so we list this product's recent
        orders and match client_order_id client-side.
        """
        order, lookup_ok = self._find_order_by_client_order_id(product_id, client_order_id)
        if order is None:
            if lookup_ok:
                print(f"[ORDER] client_order_id={client_order_id}: lookup found no "
                      f"matching order -- the order was not placed (clean failure).")
            return None, lookup_ok
        order_dict = order.to_dict() if hasattr(order, 'to_dict') else dict(order)
        print(f"[ORDER] Idempotent recovery: client_order_id={client_order_id} "
              f"maps to existing order {order_dict.get('order_id')} "
              f"-- treating the create failure as success.")
        result = OrderResult(
            success=True,
            order_id=order_dict.get('order_id'),
            client_order_id=order_dict.get('client_order_id') or client_order_id,
            product_id=order_dict.get('product_id') or product_id,
            side=order_dict.get('side') or 'BUY',
            idempotent_reuse=True,
        )
        self._apply_order(result, order)
        # If the recovered order isn't already terminal, poll get_order for the
        # authoritative fill status (the success path the spec calls for). A
        # recovered order that is already FILLED needs no extra round-trip.
        if result.order_id and result.status in (None, *_OPEN_STATUSES):
            self._poll_fill(result, tries=poll_tries, delay=poll_delay)
        return result, True

    def _find_order_by_client_order_id(self, product_id, client_order_id, limit=100):
        """Return (Order|None, lookup_ok) for the order matching client_order_id.

        list_orders has no client_order_id filter, so we page this product's
        recent orders and match locally. `lookup_ok` is False ONLY when
        list_orders itself raised -- distinguishing "verified: no such order"
        (True, None) from "could not verify" (False, None), which F2 needs to
        choose between a clean and an unverified failure.
        """
        try:
            resp = self.client.list_orders(product_ids=[product_id], limit=limit)
        except Exception as e:
            print(f"[ORDER] list_orders lookup failed: {e}")
            return None, False
        for order in getattr(resp, 'orders', []) or []:
            if getattr(order, 'client_order_id', None) == client_order_id:
                return order, True
        return None, True

    # ---- Read-only helpers for reconcile --repair (place NOTHING) ------------
    def poll_order_status(self, order_id) -> Optional['OrderResult']:
        """Read-only: get_order(order_id) -> OrderResult with fill fields, or None.

        Places/modifies nothing. Used by reconcile --repair to re-poll an
        'unconfirmed' fill row whose order_id is known.
        """
        order = self._get_order(order_id)
        if order is None:
            return None
        result = OrderResult(success=True, order_id=order_id)
        self._apply_order(result, order)
        return result

    def find_order_by_client_order_id(self, coin_or_product, client_order_id
                                      ) -> Optional['OrderResult']:
        """Read-only: resolve an order by client_order_id -> OrderResult, or None.

        Places/modifies nothing. Used by reconcile --repair to resolve an
        orphaned intent or an 'unverified_failure' row (whose order_id may be
        unknown) back to a real order. `coin_or_product` accepts either a bare
        coin ('SOL') or a product id ('SOL-USD').
        """
        product_id = coin_or_product if '-' in str(coin_or_product) else f"{coin_or_product}-USD"
        order, lookup_ok = self._find_order_by_client_order_id(product_id, client_order_id)
        if order is None:
            return None
        order_dict = order.to_dict() if hasattr(order, 'to_dict') else dict(order)
        result = OrderResult(
            success=True,
            order_id=order_dict.get('order_id'),
            client_order_id=order_dict.get('client_order_id') or client_order_id,
            product_id=order_dict.get('product_id') or product_id,
            side=order_dict.get('side') or 'BUY',
            idempotent_reuse=True,
        )
        self._apply_order(result, order)
        return result
    
    def market_order_sell(self, product_id, base_size, run_id=None, coin=None,
                          client_order_id=None):
        """Place a market sell order (SELL/exit path is deferred per the plan).

        Kept minimal but consistent: unwraps the create response into an
        OrderResult and logs the real values (no fill polling, since nothing
        calls this yet). Returns an OrderResult (never None).
        """
        client_order_id = client_order_id or self.build_client_order_id(run_id, coin, 'sell')
        try:
            resp = self.client.market_order_sell(
                client_order_id=client_order_id,
                product_id=product_id,
                base_size=base_size
            )
        except Exception as e:
            print(f"Error placing market sell order for {product_id}: {e}")
            return OrderResult(success=False, client_order_id=client_order_id,
                               product_id=product_id, side='SELL',
                               failure_reason=f'exception: {e}')
        result = self._result_from_create(resp, client_order_id)
        result.side = result.side or 'SELL'
        print(f"Market sell order placed: {product_id} for {base_size}")
        self._log_order_result(result)
        return result

    def _log_order_result(self, result):
        """Log the confirmed, unwrapped fields of an OrderResult (T5).

        Replaces the old logger that read top-level keys (`order_id`,
        `filled_size`, ...) that don't exist on the create response -- those
        are nested under `success_response`, and fills come from get_order, so
        the old logger always printed N/A (finding 1.6 / 5.5). This prints the
        values the caller actually resolved.
        """
        if result is None:
            print("[ORDER] No order response received")
            return
        try:
            # Tolerate a raw CreateOrderResponse being passed in directly.
            if not isinstance(result, OrderResult):
                result = self._result_from_create(
                    result, getattr(result, 'client_order_id', None))
            print(f"[ORDER] ID: {_na(result.order_id)} | "
                  f"Status: {_na(result.status)} | Success: {result.success}"
                  + ("  (idempotent reuse)" if result.idempotent_reuse else ""))
            print(f"[ORDER] Filled size: {_na(result.filled_size)} | "
                  f"Filled value: {_na(result.filled_value)} | "
                  f"Avg price: {_na(result.avg_fill_price)} | "
                  f"Fees: {_na(result.fees_usd)}")
            if result.failure_reason:
                print(f"[ORDER] Failure reason: {result.failure_reason}")
        except Exception as e:
            print(f"[ORDER] Could not log order result: {e}")
            print(f"[ORDER] Raw result: {result}")

    def _generate_order_id(self):
        """Generate a unique order ID (uuid4 fallback for callers without run/coin)."""
        return str(uuid.uuid4())
    
    def list_all_products(self, quote_currency='USD', product_type='SPOT'):
        """List all available products (trading pairs) on Coinbase.
        
        Args:
            quote_currency: Filter by quote currency (default: 'USD')
            product_type: Filter by product type (default: 'SPOT')
            
        Returns:
            List of product dictionaries, or empty list on error
        """
        try:
            response = self.client.get_products(product_type=product_type)
            # Response is a ListProductsResponse object with 'products' attribute
            products = response.products if hasattr(response, 'products') else []
            
            if quote_currency:
                products = [p for p in products if getattr(p, 'quote_currency_id', None) == quote_currency]
            
            return products
        except Exception as e:
            print(f"Error listing products: {e}")
            return []
    
    def list_all_coins(self, quote_currency='USD'):
        """List all coin symbols available for trading on Coinbase.
        
        Args:
            quote_currency: Filter by quote currency (default: 'USD')
            
        Returns:
            List of coin symbols (e.g., ['BTC', 'ETH', 'DOGE', ...])
        """
        products = self.list_all_products(quote_currency=quote_currency)
        coins = [getattr(p, 'base_currency_id', None) for p in products]
        coins = [c for c in coins if c]
        return sorted(set(coins))
    
    def list_coins_by_category(self, category: str, quote_currency='USD'):
        """List coins available on Coinbase filtered by CoinGecko category.
        
        Args:
            category: Category to filter by (e.g., 'meme', 'base ecosystem', 'solana ecosystem')
            quote_currency: Filter by quote currency (default: 'USD')
            
        Returns:
            List of coin symbols matching the category
        """
        from coingeckoutil import filter_coins_by_category
        
        all_coins = self.list_all_coins(quote_currency=quote_currency)
        if not all_coins:
            return []
        
        # Filter by category using CoinGecko
        # Note: This is rate-limited and may take time for large lists
        print(f"Filtering {len(all_coins)} coins by category '{category}'...")
        filtered = filter_coins_by_category(all_coins, [category])
        print(f"Found {len(filtered)} coins in category '{category}'")
        return filtered
