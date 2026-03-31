#foo

import datetime
import uuid
import json
import random
from coinbase.rest import RESTClient

class BlobbyTrader:
    def __init__(self, api_key: str, api_secret: str):
        """
        Initializes the CoinbaseTrader with API key and secret.

        Args:
            api_key (str): Your Coinbase Advanced Trade API key.
                           Looks like: "organizations/{org_id}/apiKeys/{key_id}"
            api_secret (str): Your Coinbase Advanced Trade API secret (private key).
                              Looks like: "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
        """
        self.client = RESTClient(api_key=api_key, api_secret=api_secret)
        print("CoinbaseTrader initialized. Please ensure your API keys have the necessary permissions.")



    def get_accounts(self) -> dict:
        """
        Retrieves all trading accounts.

        Returns:
            dict: A dictionary containing account information.
        """
        try:
            accounts = self.client.get_accounts()
            return accounts
        except Exception as e:
            print(f"Error getting accounts: {e}")
            return {}

    def get_product_details(self, product_id: str) -> dict:
        """
        Retrieves details for a specific trading product (e.g., 'BTC-USD').

        Args:
            product_id (str): The ID of the trading pair (e.g., 'BTC-USD').

        Returns:
            dict: A dictionary containing product details, or an empty dict on error.
        """
        try:
            product = self.client.get_product(product_id=product_id)
            return product
        except Exception as e:
            print(f"Error getting product details for {product_id}: {e}")
            return {}

    def market_order_buy(self, productId, quoteSize):
        order = self.client.market_order_buy(
        client_order_id=str(random.randint(0, 100000)),  # Replace with a unique ID
        product_id="PEPE-USD",  # The trading pair you want to trade
        quote_size="25.00"  # The amount of quote currency to spend (e.g., $10 USD)
)


    def place_market_order(self, product_id: str, side: str, amount: float, amount_type: str = 'quote_size') -> dict:
        """
        Places a market order to buy or sell a cryptocurrency.

        Args:
            product_id (str): The trading pair (e.g., 'BTC-USD').
            side (str): 'BUY' or 'SELL'.
            amount (float): The quantity to trade.
                            If amount_type is 'base_size', this is the amount of the base currency (e.g., BTC).
                            If amount_type is 'quote_size', this is the amount of the quote currency (e.g., USD).
            amount_type (str): 'base_size' or 'quote_size'. Determines how 'amount' is interpreted.

        Returns:
            dict: The response from the Coinbase API for the order, or an error dictionary.
        """
        client_order_id = str(uuid.uuid4())
        try:
            if amount_type == 'base_size':
                order_response = self.client.market_order_incremental_market_by_base_size(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    base_size=str(amount)
                )
            elif amount_type == 'quote_size':
                order_response = self.client.market_order_incremental_market_by_quote_size(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    quote_size=str(amount)
                )
            else:
                return {"error": "Invalid amount_type. Must be 'base_size' or 'quote_size'."}

            if order_response.get('success'):
                print(f"Market {side} order placed successfully for {amount} {product_id} (Client Order ID: {client_order_id})")
            else:
                print(f"Error placing market order: {order_response.get('error_response', 'Unknown error')}")
            return order_response
        except Exception as e:
            print(f"An unexpected error occurred while placing market order: {e}")
            return {"error": str(e)}

    def place_limit_order(self, product_id: str, side: str, base_size: float, limit_price: float, time_in_force: str = 'GTC') -> dict:
        """
        Places a limit order to buy or sell a cryptocurrency at a specific price.

        Args:
            product_id (str): The trading pair (e.g., 'BTC-USD').
            side (str): 'BUY' or 'SELL'.
            base_size (float): The amount of the base currency to trade (e.g., 0.001 BTC).
            limit_price (float): The price at which to execute the trade (e.g., 30000.00).
            time_in_force (str): 'GTC' (Good 'Til Canceled), 'IOC' (Immediate Or Cancel), 'FOK' (Fill Or Kill), 'GTD' (Good 'Til Date/Time).
                                 Note: For 'GTD', you'd need to add an 'expiry_time' parameter.

        Returns:
            dict: The response from the Coinbase API for the order, or an error dictionary.
        """
        client_order_id = str(uuid.uuid4())
        try:
            # The Advanced Trade API has specific methods for different time_in_force options.
            # For simplicity, we'll use the 'GTC' (Good Til Canceled) method here.
            # You might need to adjust this for other time_in_force options.
            if time_in_force == 'GTC':
                order_response = self.client.limit_order_gtc(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    base_size=str(base_size),
                    limit_price=str(limit_price)
                )
            elif time_in_force == 'IOC':
                order_response = self.client.limit_order_ioc(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    base_size=str(base_size),
                    limit_price=str(limit_price)
                )
            elif time_in_force == 'FOK':
                order_response = self.client.limit_order_fok(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    base_size=str(base_size),
                    limit_price=str(limit_price)
                )
            elif time_in_force == 'GTD':
                # For GTD, you need an expiry_time. Let's set it for 1 hour from now as an example.
                expiry_time = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat() + "Z"
                order_response = self.client.limit_order_gtd(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    side=side,
                    base_size=str(base_size),
                    limit_price=str(limit_price),
                    end_time=expiry_time
                )
            else:
                return {"error": "Unsupported time_in_force for this simplified method. Check Coinbase API docs for more options."}

            if order_response.get('success'):
                print(f"Limit {side} order placed successfully for {base_size} {product_id} at {limit_price} (Client Order ID: {client_order_id})")
            else:
                print(f"Error placing limit order: {order_response.get('error_response', 'Unknown error')}")
            return order_response
        except Exception as e:
            print(f"An unexpected error occurred while placing limit order: {e}")
            return {"error": str(e)}

    def get_order_status(self, order_id: str = None, client_order_id: str = None) -> dict:
        """
        Retrieves the status of a specific order.

        Args:
            order_id (str, optional): The Coinbase order ID.
            client_order_id (str, optional): The client-generated order ID.
                                              One of these two is required.

        Returns:
            dict: The order details, or an error dictionary.
        """
        try:
            if order_id:
                order_details = self.client.get_order(order_id=order_id)
            elif client_order_id:
                order_details = self.client.get_order_by_client_order_id(client_order_id=client_order_id)
            else:
                return {"error": "Either order_id or client_order_id must be provided."}

            if order_details and not order_details.get('error'):
                print(f"Order Status for {order_id if order_id else client_order_id}: {order_details.get('order', {}).get('status')}")
            else:
                print(f"Error getting order status: {order_details.get('error_response', 'Order not found or unknown error')}")
            return order_details
        except Exception as e:
            print(f"An unexpected error occurred while getting order status: {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        """
        Cancels a specific open order.

        Args:
            order_id (str): The Coinbase order ID to cancel.

        Returns:
            dict: The cancellation response, or an error dictionary.
        """
        try:
            cancel_response = self.client.cancel_orders(order_ids=[order_id])
            if cancel_response.get('results') and cancel_response['results'][0].get('success'):
                print(f"Order {order_id} cancelled successfully.")
            else:
                print(f"Error cancelling order {order_id}: {cancel_response.get('results', [{}])[0].get('error_response', 'Unknown error')}")
            return cancel_response
        except Exception as e:
            print(f"An unexpected error occurred while cancelling order: {e}")
            return {"error": str(e)}

    def get_candles(self, product_id: str, granularity: str, start: datetime.datetime, end: datetime.datetime) -> dict:
        """
        Retrieves historical candlestick data for a product.

        Args:
            product_id (str): The trading pair (e.g., 'BTC-USD').
            granularity (str): The candlestick interval (e.g., 'ONE_MINUTE', 'FIVE_MINUTE', 'ONE_HOUR', 'ONE_DAY').
            start (datetime.datetime): Start time for the candles.
            end (datetime.datetime): End time for the candles.

        Returns:
            dict: A dictionary containing candlestick data.
        """
        try:
            candles = self.client.get_candles(
                product_id=product_id,
                granularity=granularity,
                start=start.isoformat() + "Z",
                end=end.isoformat() + "Z"
            )
            return candles
        except Exception as e:
            print(f"Error getting candles for {product_id}: {e}")
            return {}

