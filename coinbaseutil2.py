from coinbase.rest import RESTClient
import json
import os

# Default path for Coinbase credentials JSON file
DEFAULT_CREDENTIALS_PATH = "cdp_api_key.json"

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
