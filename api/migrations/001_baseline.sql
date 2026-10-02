-- ============================================================================
-- Migration 001 — baseline schema (single source of truth, no legacy cruft)
--
-- This project is 1 day old: there is NO legacy system to support.
-- All tables are created here exactly once. Future schema changes MUST go
-- in a new numbered file (002_*.sql, 003_*.sql, ...) — never edit this file
-- after it has been applied to any environment.
-- Applied + tracked via schema_migrations by api/migrate.py (idempotent).
-- ============================================================================

-- --- FreeRADIUS standard tables -------------------------------------------
CREATE TABLE IF NOT EXISTS radcheck (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '==',
    value VARCHAR(253) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radcheck_username_idx ON radcheck (username);

CREATE TABLE IF NOT EXISTS radreply (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '=',
    value VARCHAR(253) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radreply_username_idx ON radreply (username);

CREATE TABLE IF NOT EXISTS radgroupcheck (
    id SERIAL PRIMARY KEY,
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '==',
    value VARCHAR(253) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupcheck_groupname_idx ON radgroupcheck (groupname);

CREATE TABLE IF NOT EXISTS radgroupreply (
    id SERIAL PRIMARY KEY,
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '=',
    value VARCHAR(253) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupreply_groupname_idx ON radgroupreply (groupname);

CREATE TABLE IF NOT EXISTS radusergroup (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL DEFAULT '',
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS radusergroup_username_idx ON radusergroup (username);

CREATE TABLE IF NOT EXISTS radacct (
    radacctid BIGSERIAL PRIMARY KEY,
    acctsessionid VARCHAR(64) NOT NULL DEFAULT '',
    acctuniqueid VARCHAR(32) NOT NULL DEFAULT '',
    username VARCHAR(64) NOT NULL DEFAULT '',
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    realm VARCHAR(64) DEFAULT '',
    nasipaddress INET NOT NULL DEFAULT '0.0.0.0',
    nasportid VARCHAR(32) DEFAULT NULL,
    nasporttype VARCHAR(32) DEFAULT NULL,
    acctstarttime TIMESTAMP WITH TIME ZONE NULL,
    acctupdatetime TIMESTAMP WITH TIME ZONE NULL,
    acctstoptime TIMESTAMP WITH TIME ZONE NULL,
    acctinterval INTEGER DEFAULT NULL,
    acctsessiontime BIGINT DEFAULT NULL,
    acctauthentic VARCHAR(32) DEFAULT NULL,
    connectinfo_start VARCHAR(50) DEFAULT NULL,
    connectinfo_stop VARCHAR(50) DEFAULT NULL,
    acctinputoctets BIGINT DEFAULT NULL,
    acctoutputoctets BIGINT DEFAULT NULL,
    calledstationid VARCHAR(50) NOT NULL DEFAULT '',
    callingstationid VARCHAR(50) NOT NULL DEFAULT '',
    acctterminatecause VARCHAR(32) NOT NULL DEFAULT '',
    servicetype VARCHAR(32) DEFAULT NULL,
    framedprotocol VARCHAR(32) DEFAULT NULL,
    framedipaddress INET DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS radacct_username_idx ON radacct (username);
CREATE INDEX IF NOT EXISTS radacct_sessionid_idx ON radacct (acctsessionid);
CREATE INDEX IF NOT EXISTS radacct_active_idx ON radacct (acctstoptime) WHERE acctstoptime IS NULL;

CREATE TABLE IF NOT EXISTS radpostauth (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL DEFAULT '',
    pass VARCHAR(64) NOT NULL DEFAULT '',
    reply VARCHAR(32) NOT NULL DEFAULT '',
    reason TEXT,
    authdate TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    class VARCHAR(64) DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS radpostauth_username_idx ON radpostauth (username);

CREATE TABLE IF NOT EXISTS nas (
    id SERIAL PRIMARY KEY,
    nasname VARCHAR(128) NOT NULL,
    shortname VARCHAR(32),
    type VARCHAR(30) DEFAULT 'other',
    ports INTEGER,
    secret VARCHAR(60) NOT NULL,
    server VARCHAR(64),
    community VARCHAR(50),
    description VARCHAR(200) DEFAULT 'RADIUS Client'
);

-- --- Central entitlement / billing tables ---------------------------------
CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    description TEXT,
    recharge_required BOOLEAN DEFAULT TRUE,
    max_session_seconds INTEGER DEFAULT 86400,
    default_plan_id INTEGER,
    bandwidth_down_kbps INTEGER,
    bandwidth_up_kbps INTEGER,
    vlan_id INTEGER,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    plan_type VARCHAR(32) DEFAULT 'STANDARD',
    price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(8) NOT NULL DEFAULT 'INR',
    validity_days INT NOT NULL DEFAULT 1,
    validity_seconds BIGINT NOT NULL DEFAULT 86400,
    max_session_seconds INTEGER DEFAULT 86400,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(128),
    phone VARCHAR(32),
    group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    recharge_required_override BOOLEAN DEFAULT NULL,
    status VARCHAR(32) DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    gateway VARCHAR(64) NOT NULL,
    gateway_order_id VARCHAR(128),
    gateway_payment_id VARCHAR(128) UNIQUE NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'INR',
    status VARCHAR(32) DEFAULT 'PENDING',
    verified_at TIMESTAMP WITH TIME ZONE,
    raw_reference TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(32) DEFAULT 'ACTIVE',
    payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS subscriptions_user_status_idx ON subscriptions (user_id, status);

CREATE TABLE IF NOT EXISTS vouchers (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) UNIQUE NOT NULL,
    plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    validity_seconds INTEGER NOT NULL DEFAULT 86400,
    max_uses INTEGER DEFAULT 1,
    current_uses INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(64) DEFAULT 'ADMIN',
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS vouchers_code_idx ON vouchers (code);

CREATE TABLE IF NOT EXISTS voucher_redemptions (
    id SERIAL PRIMARY KEY,
    voucher_id INTEGER REFERENCES vouchers(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
    redeemed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_events (
    id SERIAL PRIMARY KEY,
    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(64),
    event VARCHAR(64) NOT NULL,
    target_type VARCHAR(32),
    target_id VARCHAR(64),
    metadata JSONB,
    ip VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS audit_events_created_idx ON audit_events (created_at DESC);

-- --- Admin / device / session tables (previously scattered ensure_*) ------
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    admin_user TEXT NOT NULL,
    action TEXT NOT NULL,
    target_user TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason TEXT
);

CREATE TABLE IF NOT EXISTS user_device_policy (
    username TEXT PRIMARY KEY,
    require_verified BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS verified_devices (
    username TEXT NOT NULL,
    mac TEXT NOT NULL,
    label TEXT,
    added_by TEXT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, mac)
);
CREATE INDEX IF NOT EXISTS idx_verified_devices_mac ON verified_devices (mac);

-- --- Seeds (clean: current pricing only, no legacy 20/100/250 rows) -------
INSERT INTO system_settings (key, value, description)
VALUES
('upi_vpa', 'wifi@rajlabs', 'Active UPI Virtual Payment Address (VPA) for QR recharge'),
('upi_merchant_name', 'RajLabs Enterprise WiFi', 'Merchant / Payee Name displayed on UPI checkout apps'),
('default_voucher_code', 'WELCOME24H', 'Default promotional voucher code for new onboarding users'),
('currency', 'INR', 'Default system currency symbol/code')
ON CONFLICT (key) DO NOTHING;

INSERT INTO groups (name, description, recharge_required, max_session_seconds, bandwidth_down_kbps, bandwidth_up_kbps, vlan_id, is_admin)
VALUES
('FREE', 'Free tier network access with bandwidth caps (No recharge required)', FALSE, 86400, 10000, 2000, 30, FALSE),
('PAID', 'Standard paid subscriber tier requiring active recharge/subscription', TRUE, 86400, 100000, 50000, 10, FALSE),
('STAFF', 'Internal employee and operations tier (Exempt from recharge)', FALSE, 86400, 100000, 50000, 10, FALSE),
('GUEST', 'Short-term guest hotspot tier with time limits', TRUE, 7200, 10000, 2000, 30, FALSE),
('admins', 'Administrative authority with console access', FALSE, 86400, NULL, NULL, 99, TRUE)
ON CONFLICT (name) DO NOTHING;

INSERT INTO plans (name, plan_type, price, currency, validity_days, validity_seconds, max_session_seconds, description, enabled)
SELECT '1 Day Daily Pass', 'DAILY', 10.00, 'INR', 1, 86400, 86400, 'Emergency 24-hour unlimited high-speed access (₹10/day)', TRUE
WHERE NOT EXISTS (SELECT 1 FROM plans);
INSERT INTO plans (name, plan_type, price, currency, validity_days, validity_seconds, max_session_seconds, description, enabled)
SELECT '7 Days Weekly Pass', 'WEEKLY', 30.00, 'INR', 7, 604800, 86400, '7 Days high-speed broadband access (₹4.28/day — Save 57% vs Daily)', TRUE
WHERE NOT EXISTS (SELECT 1 FROM plans WHERE validity_days = 7);
INSERT INTO plans (name, plan_type, price, currency, validity_days, validity_seconds, max_session_seconds, description, enabled)
SELECT '30 Days Monthly Unlimited', 'MONTHLY', 51.35, 'INR', 30, 2592000, 86400, 'Best Value! Full 30 days unlimited Wi-Fi at ₹1.71/day (₹50 base + 2.7% PG gateway fee)', TRUE
WHERE NOT EXISTS (SELECT 1 FROM plans WHERE validity_days = 30);

INSERT INTO vouchers (code, validity_seconds, max_uses, current_uses, is_active, created_by)
VALUES ('WELCOME24H', 86400, 1000, 0, TRUE, 'SYSTEM')
ON CONFLICT (code) DO NOTHING;
