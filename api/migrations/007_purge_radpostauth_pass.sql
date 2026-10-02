-- ============================================================================
-- Migration 007 - purge historic attempted passwords
-- postauth_query no longer logs the tried secret (pass = ''), but rows
-- written before that change still hold cleartext attempts — including
-- mistyped passwords for unrelated accounts. Wipe them. Forward-only,
-- idempotent (WHERE clause makes re-runs a no-op).
-- NOTE: pre-existing offsite backups still contain historic values;
-- rotate/expire them per docs/BACKUP_AND_HA.md.
-- ============================================================================

UPDATE radpostauth SET pass = '' WHERE pass IS NULL OR pass <> '';
