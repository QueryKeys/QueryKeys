#!/usr/bin/env python3
"""
Derive Polymarket L2 API keys from your L1 private key.

Usage:
    python scripts/derive_api_keys.py

Outputs the api_key, api_secret, api_passphrase that you should add to .env.
These are deterministically derived from your private key — no server call needed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main():
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    if not private_key:
        print("ERROR: Set POLYMARKET_PRIVATE_KEY in .env first.")
        sys.exit(1)

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.constants import POLYGON

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=POLYGON,
            key=private_key,
        )
        creds = client.derive_api_key()
        print("\n✅ API Keys derived successfully!\n")
        print("Add these to your .env file:")
        print(f"POLYMARKET_API_KEY={creds.api_key}")
        print(f"POLYMARKET_API_SECRET={creds.api_secret}")
        print(f"POLYMARKET_API_PASSPHRASE={creds.api_passphrase}")
        print()
        print("⚠️  Keep these secret — they authorize trading on your behalf.")
    except ImportError:
        print("ERROR: py-clob-client not installed. Run: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
