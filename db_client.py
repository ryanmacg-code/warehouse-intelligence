"""
Thin psycopg2 wrapper used by the sync job and MCP server.
Reads connection params from environment / .env file.
"""

from __future__ import annotations

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

ARIA_TENANT_ID: str = os.environ.get(
    "ARIA_TENANT_ID", "00000000-0000-0000-0000-000000000001"
)


def get_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode="require",
        connect_timeout=30,
        options="-c statement_timeout=60000",
    )


def dict_cursor(conn: psycopg2.extensions.connection):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
