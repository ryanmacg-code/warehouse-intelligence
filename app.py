"""
FastAPI wrapper for the Aria London WMS MCP server.

Exposes:
  POST/GET /mcp    — MCP Streamable HTTP endpoint (all tools)
  GET  /health     — liveness probe
  GET  /version    — service metadata

Tenant scoping: every /mcp request must include an X-Tenant-Id header
containing a valid UUID.  The value is bound to tenant_id_var (context.py)
and read by _effective_tenant_id() inside pvx_mcp_server.py.

Run locally:  uvicorn app:app --host 0.0.0.0 --port 8080 --reload
Run in Docker: CMD in Dockerfile (uvicorn app:app ...)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from context import tenant_id_var

# ── Version ────────────────────────────────────────────────────────────────────
SERVICE_VERSION = "1.0.0"
BUILD_TIME = datetime.now(timezone.utc).isoformat()

# ── Import FastMCP instance (registers all tools as side-effect) ───────────────
from pvx_mcp_server import mcp  # noqa: E402  (after load_dotenv in pvx_mcp_server)

# Pre-create the MCP ASGI sub-app; this also initialises the session manager
# so that mcp.session_manager is available for the lifespan below.
_mcp_asgi = mcp.streamable_http_app()

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
)


# ── Middleware: bind tenant ID from X-Tenant-Id header ────────────────────────
@app.middleware("http")
async def tenant_scoping(request: Request, call_next):
    """Require X-Tenant-Id on every /mcp request and bind it to the context."""
    if request.url.path.startswith("/mcp"):
        tid = (request.headers.get("X-Tenant-Id") or "").strip()
        if not tid:
            return JSONResponse(
                {
                    "error": "X-Tenant-Id header is required for all MCP requests.",
                    "code": "MISSING_TENANT_ID",
                    "hint": "Add header: X-Tenant-Id: <tenant-uuid>",
                },
                status_code=400,
            )
        token = tenant_id_var.set(tid)
        try:
            response = await call_next(request)
        finally:
            tenant_id_var.reset(token)
        return response
    return await call_next(request)


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


# ── Mount MCP sub-app at /mcp ─────────────────────────────────────────────────
# FastMCP is configured with streamable_http_path="/" so its handler sits at
# the root of the sub-app.  After Starlette strips the "/mcp" prefix, requests
# to POST /mcp reach the handler at "/".
app.mount("/mcp", _mcp_asgi)


# ── Local dev entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
