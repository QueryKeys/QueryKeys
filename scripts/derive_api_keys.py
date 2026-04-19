#!/usr/bin/env python3
"""
Derive Polymarket L2 API keys from your L1 private key.

Usage:
    python scripts/derive_api_keys.py

Outputs the api_key, api_secret, api_passphrase to add to .env.
Keys are deterministically derived from your private key — no account creation needed.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

_HEX_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def normalize_key(raw: str) -> str:
    """Strip whitespace and 0x prefix, validate it is 64 hex chars."""
    key = raw.strip()
    if key.lower().startswith("0x"):
        key = key[2:]
    if not _HEX_RE.match(key):
        raise ValueError(
            f"Private key must be 64 hex characters (32 bytes).\n"
            f"  Got {len(key)} chars: {key[:8]}...\n"
            f"  Make sure you copied the full key without spaces or quotes."
        )
    return "0x" + key          # py-clob-client expects 0x prefix


def main():
    raw = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
    if not raw or raw == "0xYOUR_PRIVATE_KEY_HERE":
        print(
            "ERROR: POLYMARKET_PRIVATE_KEY is not set.\n"
            "  1. Open .env\n"
            "  2. Set POLYMARKET_PRIVATE_KEY=0x<your 64-char hex private key>\n"
            "  3. Run this script again."
        )
        sys.exit(1)

    try:
        private_key = normalize_key(raw)
    except ValueError as exc:
        print(f"ERROR: Invalid private key — {exc}")
        sys.exit(1)

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.constants import POLYGON
    except ImportError:
        print("ERROR: py-clob-client not installed.\n  Run: pip install -r requirements.txt")
        sys.exit(1)

    print(f"Deriving API keys for key starting with {private_key[:6]}...")
    try:
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=POLYGON,
            key=private_key,
        )
        creds = client.derive_api_key()

        print("\nAPI Keys derived successfully!\n")
        print("Add these lines to your .env file:")
        print(f"POLYMARKET_API_KEY={creds.api_key}")
        print(f"POLYMARKET_API_SECRET={creds.api_secret}")
        print(f"POLYMARKET_API_PASSPHRASE={creds.api_passphrase}")
        print("\nWARNING: Keep these secret — they authorize trading on your behalf.")

    except Exception as exc:
        print(f"ERROR: {exc}")
        print("\nCommon fixes:")
        print("  - Ensure your private key is exactly 64 hex chars (32 bytes)")
        print("  - Ensure you have internet access (Polygon RPC is queried)")
        print("  - Try: pip install --upgrade py-clob-client")
        sys.exit(1)


if __name__ == "__main__":
    main()
