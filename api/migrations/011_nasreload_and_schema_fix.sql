-- ============================================================================
-- Migration 011 - nasreload table, radpostauth reason column & clean reply attributes
-- FreeRADIUS simul_count_query joins nasreload for Simultaneous-Use checks.
-- Simultaneous-Use belongs in radgroupcheck (check item), not radgroupreply.
-- ============================================================================

CREATE TABLE IF NOT EXISTS nasreload (
    nasipaddress INET PRIMARY KEY,
    reloadtime   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS reason TEXT;

DELETE FROM radgroupreply WHERE attribute = 'Simultaneous-Use';
