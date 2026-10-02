-- ============================================================================
-- Migration 002 — overview/audit performance indexes
-- Template for all future changes: one numbered file per change-set,
-- forward-only, idempotent (IF NOT EXISTS). Never edit applied files.
-- ============================================================================

CREATE INDEX IF NOT EXISTS subscriptions_expires_idx
    ON subscriptions (expires_at DESC) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS payments_user_created_idx
    ON payments (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS radpostauth_user_id_idx
    ON radpostauth (username, id DESC);
CREATE INDEX IF NOT EXISTS radacct_user_active_idx
    ON radacct (username) WHERE acctstoptime IS NULL;
