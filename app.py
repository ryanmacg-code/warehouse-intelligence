"""
FastAPI wrapper for the Aria London WMS MCP server.

Exposes:
  POST/GET /mcp    — MCP Streamable HTTP endpoint (all tools)
  GET  /health     — liveness probe
  GET  /version    — service metadata

Auth: every /mcp request must carry Authorization: Bearer <api_key>.
The key is verified against api_keys (SHA-256 hash, revoked_at IS NULL) and
the resolved tenant_id is bound to tenant_id_var (context.py), which is read
by _effective_tenant_id() in pvx_mcp_server.py.
/health and /version are unauthenticated (Railway health checks).

Run locally:  uvicorn app:app --host 0.0.0.0 --port 8080 --reload
Run in Docker: CMD in Dockerfile (uvicorn app:app ...)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from auth.api_keys import verify_api_key
from auth.oauth import verify_oauth_token
from auth.oauth_routes import router as oauth_router
from context import tenant_id_var
from db_client import get_conn

# ── Version ────────────────────────────────────────────────────────────────────
SERVICE_VERSION = "1.0.0"
BUILD_TIME = datetime.now(timezone.utc).isoformat()

# ── Import FastMCP instance (registers all tools as side-effect) ───────────────
from pvx_mcp_server import mcp  # noqa: E402  (after load_dotenv in pvx_mcp_server)

# Thin ASGI wrapper: Starlette's Mount strips "/mcp" from "/mcp", leaving path=""
# which doesn't match the sub-app's Route("/"). Normalise "" → "/" so it matches
# without issuing an HTTP redirect.
class _MCPPathNormalizer:
    __slots__ = ("_app",)

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and not scope.get("path"):
            scope = {**scope, "path": "/", "raw_path": b"/"}
        await self._app(scope, receive, send)


# Pre-create the MCP ASGI sub-app; this also initialises the session manager
# so that mcp.session_manager is available for the lifespan below.
_mcp_asgi = _MCPPathNormalizer(mcp.streamable_http_app())

# ── Lifespan: start/stop the MCP session manager with the FastAPI app ──────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Aria London WMS — MCP Server",
    version=SERVICE_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,  # prevent Starlette 307-redirecting /mcp → /mcp/
)


# ── Middleware: API key + OAuth token authentication ──────────────────────────
# Exempt paths (all non-/mcp): /health, /version, /.well-known/*, /authorize, /token
@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """Require a valid Bearer token on every /mcp request."""
    if not request.url.path.startswith("/mcp"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Expected Authorization: Bearer <token>"},
        )

    raw = auth[len("Bearer "):]
    conn = get_conn()
    try:
        tenant_id = verify_api_key(raw, conn)
        if tenant_id is None:
            tenant_id = verify_oauth_token(raw, conn)
    finally:
        conn.close()

    if tenant_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Invalid or revoked token"},
        )

    token = tenant_id_var.set(str(tenant_id))
    try:
        return await call_next(request)
    finally:
        tenant_id_var.reset(token)


# ── Utility endpoints ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Liveness probe — returns 200 when the server is up."""
    return {
        "status": "ok",
        "service": "aria-wms-mcp",
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/version")
async def version():
    """Service metadata."""
    return {
        "version": SERVICE_VERSION,
        "service": "aria-wms-mcp",
        "transport": "streamable-http",
        "mcp_endpoint": "/mcp",
        "build_time": BUILD_TIME,
        "tools": [
            "get_orders", "get_inventory", "get_returns", "get_stock_movements",
            "get_inbound_shipments", "get_packing_stations", "get_pick_jobs",
            "get_locations", "get_operators", "get_sync_status",
            "analyse_returns", "get_stock_adjustments", "get_warehouse_health",
        ],
    }


# ── OAuth routes ──────────────────────────────────────────────────────────────
app.include_router(oauth_router)

# ── Mount MCP sub-app at /mcp ─────────────────────────────────────────────────
# Mount at "/mcp" (no trailing slash). redirect_slashes=False on the FastAPI app
# stops the outer router redirecting /mcp → /mcp/. _MCPPathNormalizer above
# handles the inner case: Starlette strips "/mcp" leaving path="", which the
# sub-app's Route("/") wouldn't match without the normalisation.
app.mount("/mcp", _mcp_asgi)


# ── Local dev entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
