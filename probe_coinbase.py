import json
from coinbase.rest import RESTClient

# Update this path to your downloaded JSON file
JSON_FILE_PATH = "cdp_api_key.json"

try:
    with open(JSON_FILE_PATH, 'r') as f:
        creds = json.load(f)
    
    api_key = creds['name']
    api_secret = creds['privateKey']

    # Never print any part of key material -- just confirm presence/shape.
    print(f"API Key: present ({len(api_key)} chars)" if api_key else "API Key: MISSING")
    print(f"Private Key: present ({len(api_secret)} chars)" if api_secret else "Private Key: MISSING")

    client = RESTClient(api_key=api_key, api_secret=api_secret)
    accounts = client.get_accounts()
    print(f"\n✓ SUCCESS! Found {len(accounts.accounts)} accounts")
    
except FileNotFoundError:
    print(f"✗ JSON file not found: {JSON_FILE_PATH}")
    print("  Update JSON_FILE_PATH in this script to point to your downloaded file")
except KeyError as e:
    print(f"✗ Missing key in JSON file: {e}")
except Exception as e:
    print(f"\n✗ FAILED: {e}")
