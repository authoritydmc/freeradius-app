-- ============================================================================
-- Migration 008 - one redemption per user per voucher
-- The per-user duplicate check is check-then-insert: concurrent double
-- redeems could both pass. The database now enforces it; the redeem path
-- catches the violation and reports "already redeemed" cleanly.
-- Forward-only, idempotent.
-- ============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_voucher_redemptions_user
    ON voucher_redemptions (voucher_id, user_id);
