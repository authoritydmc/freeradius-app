-- ============================================================================
-- Migration 010 - single-use portal download tokens
-- Certificate downloads via plain GET links (needed for iPhone profile
-- install, which cannot use XHR blob downloads) must not carry the account
-- password in the URL. POST /portal/download-token mints a short-lived
-- single-use token after password verification; the GET handlers consume it.
-- Forward-only, idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS portal_download_tokens (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_portal_dl_tokens_expiry
    ON portal_download_tokens (expires_at);
