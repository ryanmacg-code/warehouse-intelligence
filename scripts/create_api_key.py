#!/usr/bin/env python3
"""
Mint a new API key for a tenant and record its hash in api_keys.

Usage:
    python scripts/create_api_key.py --tenant <uuid> --name "..." --env live|test

Example:
    python scripts/create_api_key.py \
        --tenant 00000000-0000-0000-0000-000000000001 \
        --name "Claude.ai prod" \
        --env live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow imports from the project root regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import db_client
from auth.api_keys import generate_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a WMS API key.")
    parser.add_argument("--tenant", required=True, help="Tenant UUID")
    parser.add_argument("--name", required=True, help="Label for this key (e.g. 'Claude.ai prod')")
    parser.add_argument("--env", required=True, choices=["live", "test"])
    args = parser.parse_args()

    plaintext, key_hash = generate_key(args.env)
    key_prefix = plaintext[:12]

    conn = db_client.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (args.tenant, key_hash, key_prefix, args.name),
            )
            key_id = cur.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print()
    print("=" * 64)
    print("  API KEY CREATED — COPY THIS NOW, IT WILL NOT BE SHOWN AGAIN")
    print("=" * 64)
    print(f"  ID     : {key_id}")
    print(f"  Tenant : {args.tenant}")
    print(f"  Name   : {args.name}")
    print(f"  Env    : {args.env}")
    print(f"  Prefix : {key_prefix}")
    print()
    print(f"  KEY    : {plaintext}")
    print()
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
