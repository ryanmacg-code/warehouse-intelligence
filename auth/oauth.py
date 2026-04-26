"""OAuth 2.0 token generation, hashing, DB verification, and auth code store."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

# In-memory auth code store: code -> {tenant_id, client_id, expires_at,
#                                      code_challenge, code_challenge_method, redirect_uri}
_auth_codes: dict[str, dict] = {}


def store_auth_code(
    code: str,
    tenant_id: str,
    client_id: str,
    code_challenge: str,
    code_challenge_method: str,
    redirect_uri: str,
) -> None:
    _auth_codes[code] = {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "redirect_uri": redirect_uri,
    }


def pop_auth_code(code: str) -> Optional[dict]:
    """Remove and return the auth code entry, or None if missing or expired."""
    entry = _auth_codes.pop(code, None)
    if entry is None:
        return None
    if datetime.now(timezone.utc) > entry["expires_at"]:
        return None
    return entry


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return secrets.compare_digest(computed, code_challenge)


def generate_oauth_token() -> tuple[str, str]:
    """Return (plaintext, sha256_hex). Never store the plaintext."""
    plaintext = f"wms_oauth_{secrets.token_urlsafe(32)}"
    return plaintext, _hash_token(plaintext)


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def verify_oauth_token(plaintext: str, conn) -> Optional[UUID]:
    """
    Hash the token, find an active non-expired row in oauth_tokens, and
    return the tenant_id UUID. Returns None if missing, expired, or revoked.
    """
    digest = _hash_token(plaintext)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tenant_id FROM oauth_tokens
             WHERE token_hash = %s
               AND revoked_at IS NULL
               AND expires_at > NOW()
            """,
            (digest,),
        )
        row = cur.fetchone()
    return UUID(str(row[0])) if row else None
