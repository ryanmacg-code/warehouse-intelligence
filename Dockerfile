# ── Stage 1: build deps in a virtual env ──────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Create venv and install only the server deps (not dev/tooling packages)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
# Install only the runtime packages (first 5 lines of requirements.txt)
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "mcp>=1.27" \
    "psycopg2-binary>=2.9" \
    "python-dotenv>=1.0"


# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim

# Non-root user for security
RUN useradd -m -r -u 1001 appuser

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy only the files the server needs at runtime
COPY app.py pvx_mcp_server.py db_client.py context.py ./

RUN chown -R appuser:appuser /app
USER appuser

# Railway injects PORT; default to 8080 for local Docker testing
ENV PORT=8080

EXPOSE 8080

# Healthcheck hits the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8080}/health')" || exit 1

# exec form ensures uvicorn receives SIGTERM for graceful shutdown.
# Shell form with exec so $PORT is expanded at runtime.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --log-level info"]
