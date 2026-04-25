-- ── Migration v3: API key authentication ─────────────────────────────────────
-- Run in Supabase SQL Editor (Dashboard → SQL Editor → New query).
-- Safe to run multiple times (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS api_keys (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID        NOT NULL REFERENCES tenants(id),
    key_hash      TEXT        NOT NULL UNIQUE,  -- SHA-256 hex of the full plaintext key
    key_prefix    TEXT        NOT NULL,          -- first 12 chars of plaintext, display only
    name          TEXT        NOT NULL,          -- e.g. "Claude.ai prod"
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);

-- The UNIQUE constraint on key_hash creates the B-tree index used on every
-- auth lookup — no separate CREATE INDEX needed.

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
-- No RLS policies are defined here: this table is only ever accessed via the
-- service-role connection from the MCP middleware (which bypasses RLS by
-- design). If api_keys is ever exposed to anon or authenticated Supabase roles
-- in future, add tenant-scoped SELECT/INSERT/UPDATE policies before doing so.
