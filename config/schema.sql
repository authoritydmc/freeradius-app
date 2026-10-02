-- ============================================================================
-- RajLabs FreeRADIUS Enterprise — PostgreSQL schema (idempotent)
-- Creates every table the FastAPI backend touches, plus stock FreeRADIUS
-- accounting tables. Safe to run repeatedly (CREATE TABLE IF NOT EXISTS).
-- Applied automatically by scripts/entrypoint.sh when radcheck is missing.
-- ============================================================================

-- Authentication: per-user check attributes (e.g. Cleartext-Password)
CREATE TABLE IF NOT EXISTS radcheck (
    id         SERIAL PRIMARY KEY,
    username   TEXT NOT NULL DEFAULT '',
    attribute  TEXT NOT NULL DEFAULT '',
    op         TEXT NOT NULL DEFAULT ':=',
    value      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_radcheck_username ON radcheck (username);

-- Authorization: per-user reply attributes
CREATE TABLE IF NOT EXISTS radreply (
    id         SERIAL PRIMARY KEY,
    username   TEXT NOT NULL DEFAULT '',
    attribute  TEXT NOT NULL DEFAULT '',
    op         TEXT NOT NULL DEFAULT '=',
    value      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_radreply_username ON radreply (username);

-- User -> group mapping
CREATE TABLE IF NOT EXISTS radusergroup (
    username   TEXT NOT NULL DEFAULT '',
    groupname  TEXT NOT NULL DEFAULT '',
    priority   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_radusergroup_username ON radusergroup (username);
CREATE INDEX IF NOT EXISTS idx_radusergroup_groupname ON radusergroup (groupname);

-- Group check attributes (e.g. Simultaneous-Use)
CREATE TABLE IF NOT EXISTS radgroupcheck (
    id         SERIAL PRIMARY KEY,
    groupname  TEXT NOT NULL DEFAULT '',
    attribute  TEXT NOT NULL DEFAULT '',
    op         TEXT NOT NULL DEFAULT ':=',
    value      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_radgroupcheck_groupname ON radgroupcheck (groupname);

-- Group reply attributes (bandwidth, VLAN, timeouts, ...)
CREATE TABLE IF NOT EXISTS radgroupreply (
    id         SERIAL PRIMARY KEY,
    groupname  TEXT NOT NULL DEFAULT '',
    attribute  TEXT NOT NULL DEFAULT '',
    op         TEXT NOT NULL DEFAULT '=',
    value      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_radgroupreply_groupname ON radgroupreply (groupname);

-- NAS clients (routers / APs). The API masks `secret` on read.
CREATE TABLE IF NOT EXISTS nas (
    id          SERIAL PRIMARY KEY,
    nasname     TEXT NOT NULL,
    shortname   TEXT,
    type        TEXT NOT NULL DEFAULT 'other',
    ports       INTEGER,
    secret      TEXT NOT NULL DEFAULT 'secret',
    server      TEXT,
    community   TEXT,
    description TEXT NOT NULL DEFAULT 'RADIUS Client'
);

-- NAS reload tracking for simultaneous use queries
CREATE TABLE IF NOT EXISTS nasreload (
    nasipaddress INET PRIMARY KEY,
    reloadtime   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Accounting sessions (populated by FreeRADIUS rlm_sql).
-- inet columns: the API selects nasipaddress::text / framedipaddress::text.
CREATE TABLE IF NOT EXISTS radacct (
    radacctid           BIGSERIAL PRIMARY KEY,
    acctsessionid       TEXT NOT NULL DEFAULT '',
    acctuniqueid        TEXT NOT NULL DEFAULT '',
    username            TEXT,
    realm               TEXT,
    nasipaddress        INET NOT NULL DEFAULT '0.0.0.0',
    nasportid           TEXT,
    nasporttype         TEXT,
    acctstarttime       TIMESTAMPTZ,
    acctupdatetime      TIMESTAMPTZ,
    acctstoptime        TIMESTAMPTZ,
    acctinterval         BIGINT,
    acctsessiontime     BIGINT,
    acctauthentic       TEXT,
    connectinfo_start   TEXT,
    connectinfo_stop    TEXT,
    acctinputoctets     BIGINT,
    acctoutputoctets    BIGINT,
    calledstationid     TEXT,
    callingstationid    TEXT,
    acctterminatecause   TEXT,
    servicetype         TEXT,
    framedprotocol      TEXT,
    framedipaddress     INET NOT NULL DEFAULT '0.0.0.0'
);
CREATE INDEX IF NOT EXISTS idx_radacct_username ON radacct (username);
CREATE INDEX IF NOT EXISTS idx_radacct_active ON radacct (acctstoptime) WHERE acctstoptime IS NULL;
CREATE INDEX IF NOT EXISTS idx_radacct_starttime ON radacct (acctstarttime);

-- Authentication attempts log. NOTE: the API deliberately never selects the
-- `pass` column — attempted passwords must not leak through any endpoint.
CREATE TABLE IF NOT EXISTS radpostauth (
    id        SERIAL PRIMARY KEY,
    username  TEXT NOT NULL DEFAULT '',
    pass      TEXT NOT NULL DEFAULT '',
    reply     TEXT NOT NULL DEFAULT '',
    authdate  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS eap_type TEXT;
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS calling_station TEXT;
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS called_station TEXT;
CREATE INDEX IF NOT EXISTS idx_radpostauth_username ON radpostauth (username);
CREATE INDEX IF NOT EXISTS idx_radpostauth_authdate ON radpostauth (authdate);

-- Admin audit trail (also auto-created by the API at startup)
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    admin_user  TEXT NOT NULL,
    action      TEXT NOT NULL,
    target_user TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON admin_audit_log (ts);

-- Revoked admin session tokens (also auto-created by the API at startup)
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    revoked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason      TEXT
);

-- Verified-device lockdown (per-user MAC allowlist, default OFF).
-- Enforced by the unlang policy in sites-available/default (post-auth).
CREATE TABLE IF NOT EXISTS user_device_policy (
    username          TEXT PRIMARY KEY,
    require_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS verified_devices (
    username    TEXT NOT NULL,
    mac         TEXT NOT NULL, -- normalized: 12 uppercase hex chars, no separators
    label       TEXT,
    added_by    TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, mac)
);
CREATE INDEX IF NOT EXISTS idx_verified_devices_mac ON verified_devices (mac);

-- Reject reason + diagnostics context for the Auth History view
-- (written by postauth_query: reason, eap/mac/ap context).
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS reason TEXT;
