from coinbase.rest import RESTClient
import json

class BlobbyTrader:
    def __init__(self, api_key, api_secret):
        """Initialize the Coinbase REST client with API credentials."""
        self.client = RESTClient(api_key=api_key, api_secret=api_secret)
    
    def get_product_details(self, product_id):
        """Get details for a specific product (e.g., 'BTC-USD')."""
        try:
            product = self.client.get_product(product_id)
            return product
        except Exception as e:
            print(f"Error getting product details for {product_id}: {e}")
            return None
    
    def market_order_buy(self, product_id, quote_size):
        """Place a market buy order for the specified product and amount in quote currency."""
        try:
            order = self.client.market_order_buy(
                client_order_id=self._generate_order_id(),
                product_id=product_id,
                quote_size=quote_size
            )
            print(f"Market buy order placed: {product_id} for ${quote_size}")
            return order
        except Exception as e:
            print(f"Error placing market buy order for {product_id}: {e}")
            return None
    
    def market_order_sell(self, product_id, base_size):
        """Place a market sell order for the specified product and amount in base currency."""
        try:
            order = self.client.market_order_sell(
                client_order_id=self._generate_order_id(),
                product_id=product_id,
                base_size=base_size
            )
            print(f"Market sell order placed: {product_id} for {base_size}")
            return order
        except Exception as e:
            print(f"Error placing market sell order for {product_id}: {e}")
            return None
    
    def _generate_order_id(self):
        """Generate a unique order ID."""
        import uuid
        return str(uuid.uuid4())
