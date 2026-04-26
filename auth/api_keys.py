"""API key generation, hashing, and DB verification."""

from __future__ import annotations

import hashlib
import secrets
from typing import Literal, Optional
from uuid import UUID


def generate_key(env: Literal["live", "test"]) -> tuple[str, str]:
    """Return (plaintext, sha256_hex). Never store the plaintext."""
    token = secrets.token_urlsafe(24)  # 24 bytes → exactly 32 url-safe base64 chars
    plaintext = f"wms_{env}_{token}"
    return plaintext, hash_key(plaintext)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def verify_api_key(plaintext: str, conn) -> Optional[UUID]:
    """
    Hash the key, find an active row in api_keys, update last_used_at, and
    return the tenant_id UUID. Returns None if the key is missing or revoked.
    """
    digest = hash_key(plaintext)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE api_keys
               SET last_used_at = NOW()
             WHERE key_hash = %s
               AND revoked_at IS NULL
            RETURNING tenant_id
            """,
            (digest,),
        )
        row = cur.fetchone()
    conn.commit()
    return UUID(str(row[0])) if row else None
