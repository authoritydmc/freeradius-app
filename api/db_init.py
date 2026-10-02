import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

from urllib.parse import urlparse

def get_db_connection():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    dbname = os.getenv("POSTGRES_DB", "radius")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")

    db_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRESQL_URL")
    if db_url:
        try:
            parsed = urlparse(db_url)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
            if parsed.path and len(parsed.path) > 1:
                dbname = parsed.path.lstrip("/")
            if parsed.username:
                user = parsed.username
            if parsed.password:
                password = parsed.password
        except Exception:
            pass

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )

def init_all_tables():
    """
    Initializes PostgreSQL tables for FreeRADIUS standard schema,
    Access Entitlement models, Payments, Subscriptions, Vouchers,
    System Settings, and Audit logging.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Standard FreeRADIUS Tables
            cur.execute("""
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
                nasipaddress INET NOT NULL,
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
                authdate TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                class VARCHAR(64) DEFAULT NULL
            );

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
            """);

            # 2. Central Entitlement & Access Models
            cur.execute("""
            -- System Settings table (UPI VPA, Merchant Name, etc.)
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Groups table
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

            -- Plans table
            CREATE TABLE IF NOT EXISTS plans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(64) NOT NULL,
                plan_type VARCHAR(32) DEFAULT 'STANDARD', -- DAILY, WEEKLY, MONTHLY, GUEST, VIP, PROMO
                price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                validity_seconds INTEGER NOT NULL,
                max_session_seconds INTEGER DEFAULT 86400,
                description TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Users table
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(64) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                email VARCHAR(128),
                phone VARCHAR(32),
                group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
                recharge_required_override BOOLEAN DEFAULT NULL, -- NULL=inherit group, TRUE=require recharge, FALSE=exempt
                status VARCHAR(32) DEFAULT 'ACTIVE', -- ACTIVE, DISABLED
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Payments ledger (Idempotent transactions)
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
                gateway VARCHAR(64) NOT NULL, -- RAZORPAY, CASHFREE, UPI_QR, VOUCHER, EMAIL, MANUAL_ADMIN
                gateway_order_id VARCHAR(128),
                gateway_payment_id VARCHAR(128) UNIQUE NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                currency VARCHAR(10) DEFAULT 'INR',
                status VARCHAR(32) DEFAULT 'PENDING', -- PENDING, SUCCESS, FAILED, REFUNDED
                verified_at TIMESTAMP WITH TIME ZONE,
                raw_reference TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Subscriptions (Entitlements)
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
                starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(32) DEFAULT 'ACTIVE', -- ACTIVE, EXPIRED, CANCELLED
                payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS subscriptions_user_status_idx ON subscriptions (user_id, status);

            -- Vouchers table
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

            -- Voucher Redemptions table
            CREATE TABLE IF NOT EXISTS voucher_redemptions (
                id SERIAL PRIMARY KEY,
                voucher_id INTEGER REFERENCES vouchers(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
                redeemed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );

            -- Audit Events
            CREATE TABLE IF NOT EXISTS audit_events (
                id SERIAL PRIMARY KEY,
                actor_type VARCHAR(32) NOT NULL, -- USER, ADMIN, SYSTEM, WEBHOOK
                actor_id VARCHAR(64),
                event VARCHAR(64) NOT NULL,
                target_type VARCHAR(32),
                target_id VARCHAR(64),
                metadata JSONB,
                ip VARCHAR(64),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS audit_events_created_idx ON audit_events (created_at DESC);
            """)

            # 3. Seed Default System Settings
            cur.execute("""
            INSERT INTO system_settings (key, value, description)
            VALUES
            ('upi_vpa', 'wifi@rajlabs', 'Active UPI Virtual Payment Address (VPA) for QR recharge'),
            ('upi_merchant_name', 'RajLabs Enterprise WiFi', 'Merchant / Payee Name displayed on UPI checkout apps'),
            ('default_voucher_code', 'WELCOME24H', 'Default promotional voucher code for new onboarding users'),
            ('currency', 'INR', 'Default system currency symbol/code')
            ON CONFLICT (key) DO NOTHING;
            """)

            # 4. Seed Default Policy Groups
            cur.execute("SELECT COUNT(*) as count FROM groups;")
            if cur.fetchone()["count"] == 0:
                cur.execute("""
                INSERT INTO groups (name, description, recharge_required, max_session_seconds, bandwidth_down_kbps, bandwidth_up_kbps, vlan_id, is_admin)
                VALUES
                ('FREE', 'Free tier network access with bandwidth caps (No recharge required)', FALSE, 86400, 10000, 2000, 30, FALSE),
                ('PAID', 'Standard paid subscriber tier requiring active recharge/subscription', TRUE, 86400, 100000, 50000, 10, FALSE),
                ('STAFF', 'Internal employee and operations tier (Exempt from recharge)', FALSE, 86400, 100000, 50000, 10, FALSE),
                ('GUEST', 'Short-term guest hotspot tier with time limits', TRUE, 7200, 10000, 2000, 30, FALSE),
                ('admins', 'Administrative authority with console access', FALSE, 86400, NULL, NULL, 99, TRUE)
                ON CONFLICT (name) DO NOTHING;
                """)

            # 5. Seed Default Plans
            cur.execute("SELECT COUNT(*) as count FROM plans;")
            if cur.fetchone()["count"] == 0:
                cur.execute("""
                INSERT INTO plans (name, plan_type, price, validity_seconds, max_session_seconds, description, enabled)
                VALUES
                ('1 Day Pass', 'DAILY', 20.00, 86400, 86400, '24 hours high-speed Internet access (₹20)', TRUE),
                ('7 Days (Weekly)', 'WEEKLY', 100.00, 604800, 86400, '7 days unlimited high-speed Internet access (₹100)', TRUE),
                ('30 Days (Monthly)', 'MONTHLY', 250.00, 2592000, 86400, '30 days unlimited high-speed Internet access (₹250)', TRUE)
                ON CONFLICT DO NOTHING;
                """)

            # 6. Seed Default Promotional Voucher
            cur.execute("SELECT COUNT(*) as count FROM vouchers WHERE code = 'WELCOME24H';")
            if cur.fetchone()["count"] == 0:
                cur.execute("""
                INSERT INTO vouchers (code, validity_seconds, max_uses, current_uses, is_active, created_by)
                VALUES ('WELCOME24H', 86400, 1000, 0, TRUE, 'SYSTEM')
                ON CONFLICT (code) DO NOTHING;
                """)

            # 7. Seed Default NAS localhost
            cur.execute("SELECT COUNT(*) as count FROM nas;")
            if cur.fetchone()["count"] == 0:
                cur.execute("""
                INSERT INTO nas (nasname, shortname, type, secret, description)
                VALUES ('127.0.0.1', 'localhost', 'other', %s, 'Localhost Test Client')
                ON CONFLICT DO NOTHING;
                """, (os.getenv("RADIUS_SECRET", "testing123"),))

            conn.commit()
            logging.info("Database schema initialized with vouchers, system settings, and central access tables.")
    finally:
        conn.close()
