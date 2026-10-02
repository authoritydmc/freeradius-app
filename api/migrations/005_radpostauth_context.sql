-- ============================================================================
-- Migration 005 - radpostauth diagnostics context
-- Rejects from EAP outer identities (User-Name "anonymous") carry no usable
-- username, so the dashboard needs the surrounding context to explain them:
-- EAP type, device MAC (Calling-Station-Id) and AP/SSID (Called-Station-Id).
-- Forward-only, idempotent. Never edit applied files.
-- ============================================================================

ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS eap_type TEXT;
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS calling_station TEXT;
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS called_station TEXT;

CREATE INDEX IF NOT EXISTS idx_radpostauth_called ON radpostauth (called_station);
