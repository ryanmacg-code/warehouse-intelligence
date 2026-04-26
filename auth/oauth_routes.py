"""OAuth 2.0 authorization routes: discovery, /authorize, /token."""

from __future__ import annotations

import html
import os
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth.oauth import generate_oauth_token, pop_auth_code, store_auth_code, verify_pkce
from db_client import get_conn

router = APIRouter()

# Aria London tenant UUID (Phase A: single-tenant, hardcoded)
_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _client_id() -> str:
    return os.environ.get("CLAUDE_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("CLAUDE_CLIENT_SECRET", "")


def _issuer() -> str:
    base = os.environ.get("OAUTH_ISSUER", "http://localhost:8080")
    return base if base.startswith("http") else f"https://{base}"


@router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata():
    issuer = _issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    }


@router.get("/authorize", response_class=HTMLResponse)
async def authorize_get(
    client_id: str,
    redirect_uri: str,
    state: str = "",
    response_type: str = "code",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
):
    if client_id != _client_id():
        return JSONResponse(status_code=400, content={"error": "unauthorized_client"})

    page = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Authorise — Aria London WMS</title></head>
<body style="font-family:sans-serif;max-width:480px;margin:80px auto;padding:0 16px">
  <h2>Authorise access</h2>
  <p><strong>{html.escape(client_id)}</strong> is requesting access to the Aria London WMS.</p>
  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id"             value="{html.escape(client_id)}">
    <input type="hidden" name="redirect_uri"          value="{html.escape(redirect_uri)}">
    <input type="hidden" name="state"                 value="{html.escape(state)}">
    <input type="hidden" name="code_challenge"        value="{html.escape(code_challenge)}">
    <input type="hidden" name="code_challenge_method" value="{html.escape(code_challenge_method)}">
    <button type="submit" style="padding:10px 24px;font-size:16px">Approve</button>
  </form>
</body>
</html>"""
    return HTMLResponse(content=page)


@router.post("/authorize")
async def authorize_post(
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
):
    if client_id != _client_id():
        return JSONResponse(status_code=400, content={"error": "unauthorized_client"})

    code = secrets.token_urlsafe(32)
    store_auth_code(
        code=code,
        tenant_id=_TENANT_ID,
        client_id=client_id,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        redirect_uri=redirect_uri,
    )
    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode({'code': code, 'state': state})}",
        status_code=302,
    )


@router.post("/token")
async def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code_verifier: str = Form(...),
):
    if grant_type != "authorization_code":
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})

    if client_id != _client_id():
        return JSONResponse(status_code=401, content={"error": "invalid_client"})
    if not _client_secret() or not secrets.compare_digest(client_secret, _client_secret()):
        return JSONResponse(status_code=401, content={"error": "invalid_client"})

    entry = pop_auth_code(code)
    if entry is None:
        return JSONResponse(status_code=400, content={"error": "invalid_grant", "detail": "Code missing or expired"})

    if entry["client_id"] != client_id:
        return JSONResponse(status_code=400, content={"error": "invalid_grant"})

    if entry["redirect_uri"] != redirect_uri:
        return JSONResponse(status_code=400, content={"error": "invalid_grant", "detail": "redirect_uri mismatch"})

    if not verify_pkce(code_verifier, entry["code_challenge"], entry["code_challenge_method"]):
        return JSONResponse(status_code=400, content={"error": "invalid_grant", "detail": "PKCE verification failed"})

    plaintext, token_hash = generate_oauth_token()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oauth_tokens (tenant_id, token_hash, client_id, expires_at)
                VALUES (%s, %s, %s, NOW() + INTERVAL '24 hours')
                """,
                (entry["tenant_id"], token_hash, client_id),
            )
        conn.commit()
    finally:
        conn.close()

    return {"access_token": plaintext, "token_type": "bearer", "expires_in": 3600}
