-- ============================================================================
-- Migration 006 - honest password column name
-- users.password_hash never held a hash: FreeRADIUS MS-CHAP/PEAP needs the
-- CLEAR-TEXT Wi-Fi password, so this column always stored cleartext (real
-- passwords plus onboarding placeholders). The old name invited someone to
-- "fix" it by hashing, which would silently break all password logins.
-- Rename only; values untouched. Forward-only, idempotent.
-- ============================================================================

DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'password_hash'
  ) THEN
    ALTER TABLE users RENAME COLUMN password_hash TO password_cleartext;
  END IF;
END $$;
