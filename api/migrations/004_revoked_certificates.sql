-- ============================================================================
-- Migration 004 — certificate revocation ledger
-- Every revoke AND every delete records here (username, serial, upstream
-- result, reason). The central signer owns CRL semantics when configured;
-- this ledger is our local proof + UI state. A fresh (re)issue clears the
-- row for that username.
-- Forward-only, idempotent. Never edit applied files.
-- ============================================================================

CREATE TABLE IF NOT EXISTS revoked_certificates (
    username VARCHAR(64) PRIMARY KEY,
    serial TEXT,
    reason VARCHAR(64) NOT NULL DEFAULT 'keyCompromise',
    upstream_ok BOOLEAN NOT NULL DEFAULT FALSE,
    upstream_detail TEXT,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_by VARCHAR(64)
);
