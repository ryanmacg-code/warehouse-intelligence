"""Request-scoped context variables shared between app.py and pvx_mcp_server.py."""
from contextvars import ContextVar

# Populated by the tenant_scoping middleware in app.py for every /mcp request.
# pvx_mcp_server._effective_tenant_id() falls back to ARIA_TENANT_ID env var
# when empty, preserving local stdio dev mode.
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")
