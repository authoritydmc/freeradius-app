-- ============================================================================
-- RajLabs FreeRADIUS Enterprise — PostgreSQL schema (cumulative & idempotent)
-- Creates every table the FastAPI backend touches, plus stock FreeRADIUS
-- AAA accounting tables. Safe to run repeatedly (CREATE TABLE IF NOT EXISTS).
-- Primary schema management is tracked via api/migrations/*.sql.
-- ============================================================================

-- Schema migrations tracker
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Authentication: per-user check attributes (e.g. Cleartext-Password, Expiration)
CREATE TABLE IF NOT EXISTS radcheck (
    id         SERIAL PRIMARY KEY,
    username   TEXT NOT NULL DEFAULT '',
    attribute  TEXT NOT NULL DEFAULT '',
    op         TEXT NOT NULL DEFAULT ':=',
    value      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_radcheck_username ON radcheck (username);
CREATE INDEX IF NOT EXISTS idx_radcheck_user_attr ON radcheck (username, attribute);

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

-- Group check attributes (e.g. Simultaneous-Use, Auth-Type)
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

-- NAS clients (routers / APs).
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
CREATE INDEX IF NOT EXISTS idx_radacct_nasip ON radacct (nasipaddress);

-- Authentication attempts log
CREATE TABLE IF NOT EXISTS radpostauth (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL DEFAULT '',
    pass            TEXT NOT NULL DEFAULT '',
    reply           TEXT NOT NULL DEFAULT '',
    authdate        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason          TEXT,
    eap_type        TEXT,
    calling_station TEXT,
    called_station  TEXT
);
ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS reason TEXT;
CREATE INDEX IF NOT EXISTS idx_radpostauth_username ON radpostauth (username);
CREATE INDEX IF NOT EXISTS idx_radpostauth_authdate ON radpostauth (authdate);

-- Central Application Users
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    email       TEXT,
    phone       TEXT,
    notes       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone);

-- Broadband / Wi-Fi Subscription Plans
CREATE TABLE IF NOT EXISTS plans (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    description         TEXT,
    price               NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    validity_seconds    BIGINT NOT NULL DEFAULT 2592000, -- 30 days
    download_bandwidth  BIGINT NOT NULL DEFAULT 0, -- bps (0 = unlimited)
    upload_bandwidth    BIGINT NOT NULL DEFAULT 0, -- bps
    simultaneous_use    INTEGER NOT NULL DEFAULT 1,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User Subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id     INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    status      TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, EXPIRED, CANCELLED
    starts_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status_expires ON subscriptions (status, expires_at);

-- Payment Ledger
CREATE TABLE IF NOT EXISTS payments (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id         INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
    amount          NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    currency        TEXT NOT NULL DEFAULT 'INR',
    payment_method  TEXT NOT NULL DEFAULT 'UPI', -- UPI, CASH, RAZORPAY, STRIPE
    status          TEXT NOT NULL DEFAULT 'PAID', -- PENDING, PAID, FAILED, REFUNDED
    transaction_ref TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);
CREATE INDEX IF NOT EXISTS idx_payments_tx_ref ON payments (transaction_ref);

-- Prepaid Wi-Fi Vouchers
CREATE TABLE IF NOT EXISTS vouchers (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    plan_id     INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    batch_name  TEXT,
    max_uses    INTEGER NOT NULL DEFAULT 1,
    uses_count  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vouchers_code ON vouchers (code);

-- Voucher Redemptions
CREATE TABLE IF NOT EXISTS voucher_redemptions (
    id          SERIAL PRIMARY KEY,
    voucher_id  INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Admin Audit Trail
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    admin_user  TEXT NOT NULL,
    action      TEXT NOT NULL,
    target_user TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON admin_audit_log (ts);

-- Immutable System Audit Events
CREATE TABLE IF NOT EXISTS audit_events (
    id          BIGSERIAL PRIMARY KEY,
    actor_type  TEXT NOT NULL DEFAULT 'SYSTEM',
    actor_id    TEXT,
    event       TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    metadata    JSONB,
    ip          TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_event ON audit_events (event);

-- Revoked Admin Session Tokens
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    revoked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason      TEXT
);

-- Revoked Client TLS Certificates
CREATE TABLE IF NOT EXISTS revoked_certificates (
    serial_number TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    revoked_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason        TEXT
);
CREATE INDEX IF NOT EXISTS idx_revoked_certs_username ON revoked_certificates (username);

-- User Verified Device Lock (MAC allowlist)
CREATE TABLE IF NOT EXISTS user_device_policy (
    username          TEXT PRIMARY KEY,
    require_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS verified_devices (
    username    TEXT NOT NULL,
    mac         TEXT NOT NULL,
    label       TEXT,
    added_by    TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, mac)
);
CREATE INDEX IF NOT EXISTS idx_verified_devices_mac ON verified_devices (mac);

-- System Key-Value Settings
CREATE TABLE IF NOT EXISTS system_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Guest Self-Registration Policies
CREATE TABLE IF NOT EXISTS guest_policies (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE DEFAULT 'default',
    duration_seconds    BIGINT NOT NULL DEFAULT 86400,
    download_bandwidth  BIGINT NOT NULL DEFAULT 0,
    upload_bandwidth    BIGINT NOT NULL DEFAULT 0,
    simultaneous_use    INTEGER NOT NULL DEFAULT 1,
    require_phone_otp   BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
