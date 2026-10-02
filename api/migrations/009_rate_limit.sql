-- ============================================================================
-- Migration 009 - shared rate-limit buckets
-- check_rate_limit() stores per-IP sliding windows here so every uvicorn
-- worker enforces the same budget (in-memory buckets diverge per worker).
-- Rows self-prune on every check; the index keeps it cheap. Forward-only,
-- idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS rate_limit_hits (
    scope_ip TEXT NOT NULL,
    ts       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_scope_ts
    ON rate_limit_hits (scope_ip, ts);
