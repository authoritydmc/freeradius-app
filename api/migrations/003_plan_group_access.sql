-- ============================================================================
-- Migration 003 — plan <-> group access control
-- A plan with zero rows here is buyable by EVERYONE (default, unchanged
-- behavior). Add rows to restrict a plan to specific RADIUS groups
-- (e.g. a VIP-only plan: one row ('vip')).
-- Forward-only, idempotent. Never edit applied files.
-- ============================================================================

CREATE TABLE IF NOT EXISTS plan_group_access (
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    groupname VARCHAR(64) NOT NULL,
    PRIMARY KEY (plan_id, groupname)
);
CREATE INDEX IF NOT EXISTS plan_group_access_group_idx ON plan_group_access (groupname);
