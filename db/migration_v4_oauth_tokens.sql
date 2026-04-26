-- Migration v4: OAuth 2.0 access tokens
-- Run in Supabase SQL Editor after migration_v3_api_keys.sql.
-- Safe to run multiple times (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id),
    token_hash  TEXT        NOT NULL UNIQUE,  -- SHA-256 hex; UNIQUE constraint is the auth lookup index
    client_id   TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
-- No RLS policies: accessed only via service-role connection (bypasses RLS by design).
