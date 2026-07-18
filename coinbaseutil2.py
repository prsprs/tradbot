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
            self._log_order_result(order)
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
            self._log_order_result(order)
            return order
        except Exception as e:
            print(f"Error placing market sell order for {product_id}: {e}")
            return None
    
    def _log_order_result(self, order):
        """Log key fields from a Coinbase order response to confirm fill status."""
        if order is None:
            print("[ORDER] No order response received")
            return
        try:
            order_dict = order.to_dict() if hasattr(order, 'to_dict') else vars(order)
            order_id = order_dict.get('order_id') or order_dict.get('id', 'N/A')
            status = order_dict.get('status', 'N/A')
            success = order_dict.get('success', 'N/A')
            failure_reason = order_dict.get('failure_reason', None)
            order_config = order_dict.get('order_configuration', {})
            filled_size = order_dict.get('filled_size', 'N/A')
            filled_value = order_dict.get('filled_value', 'N/A')
            avg_price = order_dict.get('average_filled_price', 'N/A')
            print(f"[ORDER] ID: {order_id} | Status: {status} | Success: {success}")
            print(f"[ORDER] Filled size: {filled_size} | Filled value: {filled_value} | Avg price: {avg_price}")
            if failure_reason:
                print(f"[ORDER] Failure reason: {failure_reason}")
        except Exception as e:
            print(f"[ORDER] Could not parse order response: {e}")
            print(f"[ORDER] Raw response: {order}")

    def _generate_order_id(self):
        """Generate a unique order ID."""
        import uuid
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
