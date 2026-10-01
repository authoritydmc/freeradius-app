import os
import re
import ipaddress
import subprocess
import secrets
import shutil
import base64
import uuid
import time
import hmac
import hashlib
import tempfile
import json
import logging
import urllib.request
import urllib.error
from xml.sax.saxutils import escape as _xml_escape
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Request, status, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ----------------------------------------------------------------------------
# Structured logging (single logger, secret-redacting, env-tunable level)
# ----------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("freeradius")

_SENSITIVE_KEYS = ("password", "passwd", "secret", "token", "p12", "private", "authorization")

def redact(obj):
    """Recursively mask secret values so plaintext credentials never hit logs."""
    if isinstance(obj, dict):
        return {
            k: ("***REDACTED***" if any(s in str(k).lower() for s in _SENSITIVE_KEYS) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj

# Database configuration from environment
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "radius")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
RADIUS_SECRET = os.getenv("RADIUS_SECRET", "testing123")

# Central Rajlabs-CA Cert Signer API Integration (all env-based, no hardcoded URLs)
CERT_SIGNER_API_URL = os.getenv("CERT_SIGNER_API_URL", "").rstrip("/")
CERT_SIGNER_API_KEY = os.getenv("CERT_SIGNER_API_KEY", "")
# Public RADIUS host shown in UI/docs (the UDP endpoint routers point at).
# Defaults to the API host when unset; override when UDP and HTTPS differ.
RADIUS_PUBLIC_HOST = os.getenv("RADIUS_PUBLIC_HOST", "")

# Short-lived cache for the signer health probe (avoid blocking the UI)
_SIGNER_STATUS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}

ADMIN_FALLBACK_USER = os.getenv("RADIUS_ADMIN_USER", "admin")
ADMIN_FALLBACK_PASS = os.getenv("RADIUS_ADMIN_PASSWORD", "admin123")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change_this_session_secret_in_production_32_chars!")

# Table retention in days (issue #9, 0 = keep forever). Purged once at startup.
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "365") or 365)
ACCOUNTING_RETENTION_DAYS = int(os.getenv("ACCOUNTING_RETENTION_DAYS", "365") or 365)

def purge_expired_tables() -> None:
    """Best-effort startup purge so audit/accounting tables can't grow forever."""
    from datetime import timedelta
    jobs = []
    if AUDIT_RETENTION_DAYS > 0:
        jobs.append(("admin_audit_log", "ts", AUDIT_RETENTION_DAYS))
    if ACCOUNTING_RETENTION_DAYS > 0:
        jobs.append(("radacct", "acctstarttime", ACCOUNTING_RETENTION_DAYS))
    if not jobs:
        return
    try:
        conn = get_db_connection()
    except Exception as e:
        logger.warning("Retention purge skipped (DB unreachable): %s", e)
        return
    try:
        with conn.cursor() as cur:
            for table, col, days in jobs:
                try:
                    cur.execute(
                        f"DELETE FROM {table} WHERE {col} < NOW() - (%s || ' days')::interval",
                        (str(days),),
                    )
                    n = cur.rowcount
                    conn.commit()
                    if n:
                        logger.info("Retention purge: removed %s row(s) from %s older than %s days", n, table, days)
                except Exception as e:
                    conn.rollback()
                    logger.warning("Retention purge failed for %s: %s", table, e)
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Startup secret hygiene (GitHub issue #5): refuse to boot on published defaults.
# ----------------------------------------------------------------------------
_KNOWN_BAD_SECRETS = frozenset({
    "", "testing123", "admin123", "password", "changeme", "change-me",
    "change_this_session_secret_in_production_32_chars!",
    "YourStrongRadiusSharedSecret_123!",
    "YourAdminPassword123!",
    "YourStrongAdminPassword_123!",
    "YourRandomSecretKeyForSigningSessions_32_Chars",
    "YourRandom32CharacterSessionKey_abc123!",
})

def _is_weak_secret(value: Optional[str]) -> bool:
    if not value:
        return True
    return value.strip() in _KNOWN_BAD_SECRETS


def check_startup_secrets() -> None:
    """Fail closed when admin/session secrets are missing, default, or short.

    RADIUS_SECRET keeps a warning (routers need *some* value to interoperate),
    but SESSION_SECRET and RADIUS_ADMIN_PASSWORD are fatal: the former mints
    admin session tokens via HMAC and the latter guards the fallback login.
    """
    errors = []
    if _is_weak_secret(SESSION_SECRET) or len(SESSION_SECRET or "") < 32:
        errors.append(
            "SESSION_SECRET is missing, a published default, or shorter than 32 chars. "
            "Set a strong random value (e.g. `openssl rand -hex 32`). Refusing to boot."
        )
    if _is_weak_secret(ADMIN_FALLBACK_PASS):
        errors.append(
            "RADIUS_ADMIN_PASSWORD is missing or a published default (e.g. admin123). "
            "Set a strong admin password. Refusing to boot."
        )
    if _is_weak_secret(RADIUS_SECRET):
        logger.warning(
            "RADIUS_SECRET is a published default (testing123) — rotate it now and "
            "update every NAS/router; accepting it only so existing routers keep working."
        )
    if errors:
        for e in errors:
            logger.error("Startup secret check FAILED: %s", e)
        raise RuntimeError("Refusing to boot: " + " ".join(errors))


# ----------------------------------------------------------------------------
# Shared input validators + CoA helper (GitHub issue #2: no shell=True anywhere)
# ----------------------------------------------------------------------------
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_ACCT_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._\-/:]{1,128}$")

def validate_username(value: str) -> str:
    if not value or not _USERNAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="Invalid username. Use 1-64 chars: letters, digits, dot, underscore, hyphen.",
        )
    return value


def validate_nas_ip(value: str) -> str:
    if not value:
        raise HTTPException(status_code=422, detail="nas_ip is required.")
    v = value.strip()
    # Strip an optional :port suffix callers sometimes include; we always use 3799.
    if v.count(":") == 1 and v.rsplit(":", 1)[1].isdigit():
        v = v.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(v)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid nas_ip '{value}'. Must be an IPv4/IPv6 address.")
    return v


def validate_acct_session_id(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    if not _ACCT_SESSION_ID_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail="Invalid Acct-Session-Id.")
    return value


def send_coa_disconnect(username: str, nas_ip: str, secret: str,
                         acct_session_id: Optional[str] = None,
                         framed_ip: Optional[str] = None) -> tuple[bool, str]:
    """Send a Disconnect-Request via radclient without ever invoking a shell.

    Returns (success, raw_output). All inputs are validated; radclient receives
    attributes on stdin and argv carries no user-controlled shell syntax.
    """
    username = validate_username(username)
    nas_ip = validate_nas_ip(nas_ip)
    acct_session_id = validate_acct_session_id(acct_session_id)
    if framed_ip not in (None, ""):
        try:
            ipaddress.ip_address(framed_ip.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid Framed-IP-Address.")
    if not secret or len(secret) > 256:
        raise HTTPException(status_code=422, detail="Invalid NAS secret.")
    lines = [f'User-Name = "{username}"']
    if acct_session_id:
        lines.append(f'Acct-Session-Id = "{acct_session_id}"')
    if framed_ip:
        lines.append(f'Framed-IP-Address = "{framed_ip.strip()}"')
    attrs = "\n".join(lines)
    cmd = ["radclient", "-r", "1", f"{nas_ip}:3799", "disconnect", secret]
    try:
        res = subprocess.run(cmd, input=attrs, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return False, "radclient timed out after 5s"
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="radclient binary not found on server.")
    output = (res.stdout or "") + (res.stderr or "")
    success = "Disconnect-ACK" in output or "CoA-ACK" in output
    return success, output.strip()


def verify_portal_user(username: str, password: str) -> None:
    """Same credential check as enroll: username + password proof required."""
    validate_username(username)
    if not password:
        raise HTTPException(status_code=401, detail="Authentication failed. Invalid username or password.")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rc.username, rc.value FROM radcheck rc "
                "WHERE rc.username = %s AND rc.attribute LIKE '%%Password'",
                (username,),
            )
            row = cur.fetchone()
            if not row or not secrets.compare_digest(str(row["value"]), password):
                raise HTTPException(status_code=401, detail="Authentication failed. Invalid username or password.")
    finally:
        conn.close()


def generate_p12_password(length: int = 20) -> str:
    """Per-issuance random PKCS#12 password (never a well-known default)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(max(12, min(length, 64))))


def safe_client_path(username: str, suffix: str) -> str:
    """Join CLIENT_CERTS_DIR safely; rejects traversal even if regex is bypassed."""
    validate_username(username)
    p = os.path.abspath(os.path.join(CLIENT_CERTS_DIR, f"{username}{suffix}"))
    base = os.path.abspath(CLIENT_CERTS_DIR)
    if p != base and not p.startswith(base + os.sep):
        raise HTTPException(status_code=400, detail="Invalid username.")
    return p


def repackage_p12_for_mobileconfig(username: str) -> tuple[bytes, str]:
    """Build a fresh .p12 (random password) from stored key/crt/chain for Apple profiles.

    The stored bundle's password is never persisted server-side, so re-exporting
    per download keeps every mobileconfig self-consistent without a static secret.
    """
    key_path = safe_client_path(username, ".key")
    crt_path = safe_client_path(username, ".crt")
    chain_path = safe_client_path(username, "-chain.crt")
    if not (os.path.exists(key_path) and os.path.exists(crt_path)):
        raise HTTPException(status_code=404, detail="Client certificate not found. Enroll first.")
    fresh_pass = generate_p12_password()
    with tempfile.NamedTemporaryFile(suffix=".p12", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        cmd = ["openssl", "pkcs12", "-export", "-in", crt_path, "-inkey", key_path,
               "-out", tmp_path, "-name", f"RajLabs RADIUS - {username}",
               "-password", f"pass:{fresh_pass}"]
        if os.path.exists(chain_path):
            cmd[cmd.index("-inkey") + 2:cmd.index("-inkey") + 2] = ["-certfile", chain_path]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(tmp_path, "rb") as f:
            return f.read(), fresh_pass
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", "replace") if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"Failed to package Apple profile: {err}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def build_mobileconfig(username: str, ssid: str, p12_bytes: bytes, p12_password: str) -> str:
    """Render Apple .mobileconfig XML with escaped values (no static passwords)."""
    ca_path = os.path.join(CERTS_DIR, "ca.pem")
    if not os.path.exists(ca_path):
        raise HTTPException(status_code=404, detail="CA certificate not found.")
    with open(ca_path, "rb") as f:
        ca_b64 = base64.b64encode(f.read()).decode("utf-8")
    p12_b64 = base64.b64encode(p12_bytes).decode("utf-8")
    safe_user = _xml_escape(username)
    safe_ssid = _xml_escape(ssid or "RajLabs-Enterprise")
    safe_pass = _xml_escape(p12_password)
    profile_uuid, wifi_uuid, cert_uuid, ca_uuid = (str(uuid.uuid4()) for _ in range(4))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadDisplayName</key>
    <string>RajLabs Wi-Fi ({safe_user})</string>
    <key>PayloadIdentifier</key>
    <string>in.rajlabs.radius.wifi.{safe_user}</string>
    <key>PayloadRemovalDisallowed</key>
    <false/>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>{profile_uuid}</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
    <key>PayloadContent</key>
    <array>
        <dict>
            <key>PayloadCertificateFileName</key>
            <string>RajLabs_Root_CA.cer</string>
            <key>PayloadContent</key>
            <data>{ca_b64}</data>
            <key>PayloadDisplayName</key>
            <string>RajLabs RADIUS Root CA</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.ca</string>
            <key>PayloadType</key>
            <string>cops.root</string>
            <key>PayloadUUID</key>
            <string>{ca_uuid}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
        </dict>
        <dict>
            <key>Password</key>
            <string>{safe_pass}</string>
            <key>PayloadCertificateFileName</key>
            <string>{safe_user}.p12</string>
            <key>PayloadContent</key>
            <data>{p12_b64}</data>
            <key>PayloadDisplayName</key>
            <string>RajLabs User Identity ({safe_user})</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.usercert.{safe_user}</string>
            <key>PayloadType</key>
            <string>com.apple.security.pkcs12</string>
            <key>PayloadUUID</key>
            <string>{cert_uuid}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
        </dict>
        <dict>
            <key>AutoJoin</key>
            <true/>
            <key>EncryptionType</key>
            <string>WPA2</string>
            <key>HIDDEN_NETWORK</key>
            <false/>
            <key>PayloadDisplayName</key>
            <string>Wi-Fi ({safe_ssid})</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.wifi.config</string>
            <key>PayloadType</key>
            <string>com.apple.wifi.managed</string>
            <key>PayloadUUID</key>
            <string>{wifi_uuid}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>SSID_STR</key>
            <string>{safe_ssid}</string>
            <key>EAPClientConfiguration</key>
            <dict>
                <key>AcceptEAPTypes</key>
                <array>
                    <integer>13</integer>
                </array>
                <key>PayloadCertificateAnchorUUID</key>
                <array>
                    <string>{ca_uuid}</string>
                </array>
                <key>UserPayloadCertificateIdentityUUID</key>
                <string>{cert_uuid}</string>
            </dict>
        </dict>
    </array>
</dict>
</plist>"""

# ----------------------------------------------------------------------------
# Password policy & secure generation (single source of truth, mirrored in UI)
# ----------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
PASSWORD_SYMBOLS = "!@#$%^*-_=+"
_PASSWORD_AMBIGUOUS = set("l1IoO0|`'\"")

def password_strength(password: str) -> Dict[str, Any]:
    """Returns entropy estimate + human label. No secrets logged."""
    import math
    classes = 0
    if any(c.islower() for c in password):
        classes += 26
    if any(c.isupper() for c in password):
        classes += 26
    if any(c.isdigit() for c in password):
        classes += 10
    if any(not c.isalnum() for c in password):
        classes += len(PASSWORD_SYMBOLS)
    entropy = round(len(password) * math.log2(classes), 1) if classes > 1 else 0.0
    if len(password) < PASSWORD_MIN_LENGTH or entropy < 45:
        label = "weak"
    elif entropy < 70:
        label = "fair"
    elif entropy < 90:
        label = "good"
    else:
        label = "strong"
    return {"entropy_bits": entropy, "strength": label}

def validate_password_policy(password: str, username: Optional[str] = None):
    """Raises HTTPException 422 on policy violation."""
    if not password or not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
        raise HTTPException(status_code=422, detail=f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters long.")
    if username and password.strip().lower() == username.strip().lower():
        raise HTTPException(status_code=422, detail="Password must not be the same as the username.")
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(not c.isalnum() for c in password)
    if not (has_lower and has_upper and has_digit and has_symbol):
        raise HTTPException(status_code=422, detail="Password must include upper-case, lower-case, digit and symbol characters.")

def generate_secure_password(length: int = 16, use_symbols: bool = True, exclude_ambiguous: bool = True) -> str:
    length = max(PASSWORD_MIN_LENGTH, min(int(length or 16), 64))
    lower = "abcdefghjkmnpqrstuvwxyz" if exclude_ambiguous else "abcdefghijklmnopqrstuvwxyz"
    upper = "ABCDEFGHJKMNPQRSTUVWXYZ" if exclude_ambiguous else "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "23456789" if exclude_ambiguous else "0123456789"
    symbols = "".join(c for c in PASSWORD_SYMBOLS if c not in _PASSWORD_AMBIGUOUS) if exclude_ambiguous else PASSWORD_SYMBOLS
    pools = [lower, upper, digits] + ([symbols] if use_symbols else [])
    alphabet = "".join(pools)
    # Guarantee at least one char from each required class
    chars = [secrets.choice(p) for p in pools]
    while len(chars) < length:
        chars.append(secrets.choice(alphabet))
    # Fisher-Yates shuffle with secrets
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)

def ensure_audit_table():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_audit_log (
                    id SERIAL PRIMARY KEY,
                    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    admin_user TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_user TEXT,
                    detail TEXT
                )
            """)
            conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Could not ensure admin_audit_log table: %s", e)

def log_audit(admin_user: str, action: str, target_user: Optional[str] = None, detail: Optional[str] = None):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_audit_log (admin_user, action, target_user, detail) VALUES (%s, %s, %s, %s)",
                (admin_user, action, target_user, detail),
            )
            conn.commit()
        conn.close()
        logger.info("AUDIT admin=%s action=%s target=%s detail=%s", admin_user, action, target_user, detail)
    except Exception as e:
        logger.warning("Audit log write failed (%s %s): %s", action, target_user, e)

CERTS_DIR = "/etc/freeradius/3.0/certs"
CLIENT_CERTS_DIR = "/etc/freeradius/3.0/certs/clients"
os.makedirs(CLIENT_CERTS_DIR, exist_ok=True)

def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )

def generate_session_token(username: str) -> str:
    timestamp = int(time.time())
    data = f"{username}:{timestamp}"
    sig = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    raw = f"{data}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_revoked_tokens_table() -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS revoked_tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    reason TEXT
                )
            """)
            conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Could not ensure revoked_tokens table: %s", e)


def revoke_session_token(token: str, reason: str = "logout") -> None:
    """Server-side logout (issue #6): a revoked token is rejected even before TTL."""
    ensure_revoked_tokens_table()
    username = None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username = raw.split(":")[0]
    except Exception:
        username = "unknown"
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO revoked_tokens (token_hash, username, reason) VALUES (%s, %s, %s) "
                "ON CONFLICT (token_hash) DO NOTHING",
                (_token_hash(token), username, reason),
            )
            # Prune entries older than the max token TTL (7d) — no unbounded growth.
            cur.execute("DELETE FROM revoked_tokens WHERE revoked_at < NOW() - INTERVAL '8 days'")
            conn.commit()
    finally:
        conn.close()


def revoke_all_user_tokens(username: str, reason: str = "password_reset") -> int:
    """Sign-out-everywhere for one admin (issue #6). Stateless HMAC tokens can't be
    enumerated, so record a per-user cutoff: tokens minted before it are rejected."""
    ensure_revoked_tokens_table()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO revoked_tokens (token_hash, username, reason) VALUES (%s, %s, %s) "
                "ON CONFLICT (token_hash) DO NOTHING",
                (f"ALL:{username}", username, reason),
            )
            cur.execute(
                "UPDATE revoked_tokens SET revoked_at = NOW(), reason = %s "
                "WHERE token_hash = %s",
                (reason, f"ALL:{username}"),
            )
            cur.execute("DELETE FROM revoked_tokens WHERE revoked_at < NOW() - INTERVAL '8 days'")
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def _user_cutoff(username: str) -> float:
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT revoked_at FROM revoked_tokens WHERE token_hash = %s", (f"ALL:{username}",))
            row = cur.fetchone()
            if row and row["revoked_at"]:
                return row["revoked_at"].timestamp()
    except Exception:
        pass
    return 0.0


def _is_token_revoked(token: str) -> bool:
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM revoked_tokens WHERE token_hash = %s", (_token_hash(token),))
            return cur.fetchone() is not None
    except Exception:
        return False


def verify_session_token(token: str) -> Optional[str]:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        username, timestamp_str, sig = parts
        timestamp = int(timestamp_str)
        # 7 days session expiration
        if time.time() - timestamp > 7 * 86400:
            return None
        expected_sig = hmac.new(SESSION_SECRET.encode(), f"{username}:{timestamp}".encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected_sig):
            return None
        # Rejected if individually revoked or minted before a sign-out-everywhere cutoff.
        if timestamp < _user_cutoff(username):
            return None
        if _is_token_revoked(token):
            return None
        return username
    except Exception:
        pass
    return None

def verify_admin_user(user: str, passwd: str) -> bool:
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rc.username, rc.value, rug.groupname
                FROM radcheck rc
                LEFT JOIN radusergroup rug ON rc.username = rug.username
                WHERE rc.username = %s AND rc.attribute LIKE '%%Password'
            """, (user,))
            row = cur.fetchone()
            if row:
                stored_pass = row["value"]
                group = row["groupname"]
                conn.close()
                if secrets.compare_digest(stored_pass, passwd) and (group == "admins" or user in ["raj", "shipra", "admin"]):
                    return True
        conn.close()
    except Exception as e:
        logger.warning("Auth DB check error: %s", e)

    if secrets.compare_digest(user, ADMIN_FALLBACK_USER) and secrets.compare_digest(passwd, ADMIN_FALLBACK_PASS):
        return True
    return False

def verify_certificate_and_get_admin(cert_pem_or_p12_bytes: bytes, p12_password: Optional[str] = None) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f_cert:
        cert_path = f_cert.name

    try:
        if b"-----BEGIN CERTIFICATE-----" in cert_pem_or_p12_bytes:
            with open(cert_path, "wb") as f:
                f.write(cert_pem_or_p12_bytes)
        else:
            with tempfile.NamedTemporaryFile(suffix=".p12", delete=False) as f_p12:
                f_p12.write(cert_pem_or_p12_bytes)
                p12_path = f_p12.name

            # No well-known default: caller must supply the per-issuance p12 password
            # (legacy bundles whose password the user still knows keep working when typed in).
            cmd = ["openssl", "pkcs12", "-in", p12_path, "-nokeys", "-out", cert_path,
                   "-passin", f"pass:{p12_password or ''}"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if os.path.exists(p12_path):
                os.remove(p12_path)
            if res.returncode != 0:
                raise ValueError("Invalid PKCS#12 certificate format or incorrect password")

        # Verify against Root CA
        ca_path = os.path.join(CERTS_DIR, "ca.pem")
        verify_cmd = ["openssl", "verify", "-CAfile", ca_path, cert_path]
        v_res = subprocess.run(verify_cmd, capture_output=True, text=True)
        if v_res.returncode != 0 or "OK" not in v_res.stdout:
            raise ValueError(f"Certificate failed Root CA validation: {v_res.stderr or v_res.stdout}")

        # Extract Subject / Common Name
        subject_cmd = ["openssl", "x509", "-in", cert_path, "-noout", "-subject"]
        s_res = subprocess.run(subject_cmd, capture_output=True, text=True)
        subject_str = s_res.stdout.strip()
        cn = None
        for part in subject_str.split(","):
            if "CN" in part:
                cn = part.split("=")[-1].strip()
                break
        
        if not cn:
            raise ValueError("Common Name (CN) missing from certificate subject")

        # Admin authorization check
        if cn in ["raj", "shipra", "admin"]:
            return cn

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT groupname FROM radusergroup WHERE username = %s", (cn,))
                row = cur.fetchone()
                if row and row["groupname"] == "admins":
                    return cn
        finally:
            conn.close()

        raise ValueError(f"Certificate for '{cn}' is authentic, but user lacks Administrator role")
    finally:
        if os.path.exists(cert_path):
            os.remove(cert_path)

def authenticate_admin(request: Request) -> str:
    """Verifies admin status via Bearer Token, Admin Session Cookie, or HTTP Basic Auth."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            user = verify_session_token(token)
            if user:
                return user
        elif auth_header.startswith("Basic "):
            try:
                encoded = auth_header[6:].strip()
                decoded = base64.b64decode(encoded).decode()
                u, p = decoded.split(":", 1)
                if verify_admin_user(u, p):
                    return u
            except Exception:
                pass

    cookie_token = request.cookies.get("admin_session")
    if cookie_token:
        user = verify_session_token(cookie_token)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized. FreeRADIUS Administrator credentials or certificate required.",
        headers={"WWW-Authenticate": 'Bearer realm="RajLabs FreeRADIUS Admin Area"'}
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed on published default secrets (issue #5) before touching the DB.
    check_startup_secrets()
    try:
        purge_expired_tables()
    except Exception as e:
        logger.warning("Retention purge error: %s", e)
    # Startup check
    try:
        conn = get_db_connection()
        conn.close()
        logger.info("Connected successfully to PostgreSQL database: %s", POSTGRES_DB)
    except Exception as e:
        logger.warning("Database connection failed during startup: %s", e)
    try:
        ensure_audit_table()
    except Exception as e:
        logger.warning("Audit table init failed: %s", e)
    try:
        ensure_revoked_tokens_table()
    except Exception as e:
        logger.warning("Revoked-tokens table init failed: %s", e)
    try:
        ensure_device_tables()
    except Exception as e:
        logger.warning("Device tables init failed: %s", e)
    yield

app = FastAPI(
    title="RajLabs FreeRADIUS Enterprise Management API",
    description="Secured Enterprise REST API, EAP-TLS PKI & Dashboard for FreeRADIUS at backend.rajlabs.in/radius",
    version="2.0.0",
    docs_url=None,
    openapi_url=None,
    redoc_url=None,
    lifespan=lifespan
)

# Browser transport hardening (issue #8): same-origin by default; explicit allowlist
# via CORS_ORIGINS (comma-separated). A wildcard is only used when credentials
# are off, since browsers reject `*` + credentials anyway.
_CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_CORS_ALLOW_CREDENTIALS = bool(_CORS_ORIGINS)
if not _CORS_ORIGINS:
    logger.info("CORS: same-origin only (set CORS_ORIGINS to allow dashboard origins).")

# Cookie transport: Secure cookies need HTTPS. Behind plain-HTTP LAN testing the
# browser silently drops Secure cookies, so allow opting out explicitly.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") != "0"
if not COOKIE_SECURE:
    logger.warning("COOKIE_SECURE=0 — admin_session cookie without Secure flag (use only on trusted LAN / HTTP testing).")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS if _CORS_ORIGINS else ["*"],
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def set_admin_session_cookie(response: Response, token: str, remember: bool = True) -> None:
    response.set_cookie(
        key="admin_session",
        value=token,
        max_age=7 * 86400 if remember else None,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


# ----------------------------------------------------------------------------
# Lightweight per-IP rate limiting (issue #7). No extra dependencies: a
# sliding-window counter in memory. Tunable via env; 429 + Retry-After.
# NOTE: single-process memory. Behind multiple uvicorn workers each worker
# enforces its own budget (fail-safe direction for availability).
# ----------------------------------------------------------------------------
import threading as _threading

_RL_BUCKETS: Dict[str, List[float]] = {}
_RL_LOCK = _threading.Lock()
RL_LOGIN_PER_MIN = int(os.getenv("RL_LOGIN_PER_MIN", "10") or 10)
RL_ENROLL_PER_MIN = int(os.getenv("RL_ENROLL_PER_MIN", "5") or 5)
RL_TEST_AUTH_PER_MIN = int(os.getenv("RL_TEST_AUTH_PER_MIN", "20") or 20)
RL_CERT_ISSUE_PER_MIN = int(os.getenv("RL_CERT_ISSUE_PER_MIN", "10") or 10)


def _client_ip(request: Optional[Request]) -> str:
    try:
        if request and request.client:
            return request.client.host or "unknown"
    except Exception:
        pass
    return "unknown"


def check_rate_limit(request: Optional[Request], scope: str, per_minute: int) -> None:
    if per_minute <= 0:
        return
    now = time.time()
    window = 60.0
    key = f"{scope}:{_client_ip(request)}"
    with _RL_LOCK:
        hits = _RL_BUCKETS.get(key, [])
        hits = [t for t in hits if now - t < window]
        if len(hits) >= per_minute:
            retry_after = int(window - (now - hits[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        _RL_BUCKETS[key] = hits

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Access log: method, path, status, latency. Bodies never logged (may hold passwords)."""
    start = time.time()
    status_code: Optional[int] = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        status_code = 500
        logger.exception("%s %s -> 500 (unhandled)", request.method, request.url.path)
        raise
    finally:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        client = request.client.host if request.client else "?"
        # Health checks are noisy; keep them at DEBUG
        if request.url.path.endswith("/api/health"):
            logger.debug("%s %s %s %sms client=%s", request.method, request.url.path, status_code, elapsed_ms, client)
        elif status_code and status_code >= 400:
            logger.warning("%s %s %s %sms client=%s", request.method, request.url.path, status_code, elapsed_ms, client)
        else:
            logger.info("%s %s %s %sms client=%s", request.method, request.url.path, status_code, elapsed_ms, client)

# Request Models
class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    password_type: str = Field(default="Cleartext-Password") # Cleartext-Password, SHA2-Password, etc.
    group: Optional[str] = None
    attributes: Optional[Dict[str, str]] = None

class PasswordChangeRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    password_type: str = Field(default="Cleartext-Password")
    disconnect_active: Optional[bool] = False

class PasswordGenerateRequest(BaseModel):
    length: Optional[int] = 16
    symbols: Optional[bool] = True
    exclude_ambiguous: Optional[bool] = True

class GroupCreateRequest(BaseModel):
    groupname: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = None
    simultaneous_use: Optional[int] = 3 # Simultaneous-Use (Max concurrent logins)
    session_timeout: Optional[int] = None # in seconds (e.g. 7200 = 2 hours)
    idle_timeout: Optional[int] = 1800 # in seconds (e.g. 1800 = 30 min)
    acct_interim_interval: Optional[int] = 300 # in seconds (e.g. 300 = 5 min)
    bandwidth_down_kbps: Optional[int] = None # WISPr-Bandwidth-Max-Down (in Kbps, e.g. 50000 = 50 Mbps)
    bandwidth_up_kbps: Optional[int] = None # WISPr-Bandwidth-Max-Up (in Kbps, e.g. 25000 = 25 Mbps)
    mikrotik_rate_limit: Optional[str] = None # e.g. "25M/50M"
    vlan_id: Optional[int] = None # 802.1Q VLAN Tag (e.g. 10, 20, 30)
    framed_pool: Optional[str] = None # NAS DHCP Pool Name
    is_admin: Optional[bool] = False # Administrative-User role
    extra_reply_attributes: Optional[Dict[str, str]] = None
    extra_check_attributes: Optional[Dict[str, str]] = None

class ApplyPresetRequest(BaseModel):
    preset_id: str
    groupname: Optional[str] = None

class NasCreateRequest(BaseModel):
    nasname: str = Field(..., description="IP Address or CIDR subnet (e.g. 192.168.1.1 or 0.0.0.0/0)")
    shortname: str = Field(..., description="Friendly short name")
    type: str = Field(default="other")
    secret: str = Field(..., min_length=1)
    description: Optional[str] = "RADIUS Client"

class AuthTestRequest(BaseModel):
    username: str
    password: str
    nas_ip: Optional[str] = "127.0.0.1"
    secret: Optional[str] = None
    calling_station_id: Optional[str] = None  # optional device MAC to simulate (tests MAC-lock policy)

class DisconnectSessionRequest(BaseModel):
    username: str
    nas_ip: str
    nas_secret: Optional[str] = None
    acct_session_id: Optional[str] = None
    framed_ip: Optional[str] = None


class DevicePolicyUpdate(BaseModel):
    require_verified: bool


class VerifiedDeviceAdd(BaseModel):
    mac: str = Field(..., min_length=1, max_length=32)
    label: Optional[str] = Field(default=None, max_length=64)

class IssueCertRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    cert_password: Optional[str] = None
    valid_days: Optional[int] = 365
    email: Optional[str] = None

class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    remember: Optional[bool] = True

class CertLoginRequest(BaseModel):
    cert_pem: Optional[str] = None
    p12_b64: Optional[str] = None
    p12_password: Optional[str] = None

# Authentication Endpoints
@app.post("/radius/api/auth/login", tags=["Authentication"])
@app.post("/api/auth/login", tags=["Authentication"])
def admin_login(payload: AdminLoginRequest, response: Response, request: Request):
    check_rate_limit(request, "login", RL_LOGIN_PER_MIN)
    if not verify_admin_user(payload.username, payload.password):
        client = request.client.host if request.client else "?"
        logger.warning("Admin login FAILED username=%s client=%s", payload.username, client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials. Access denied."
        )
    logger.info("Admin login success username=%s", payload.username)
    
    token = generate_session_token(payload.username)
    set_admin_session_cookie(response, token, remember=bool(payload.remember))
    return {
        "status": "success",
        "token": token,
        "username": payload.username,
        "role": "admin",
        "message": f"Welcome back, {payload.username}!"
    }

@app.post("/radius/api/auth/cert-login", tags=["Authentication"])
@app.post("/api/auth/cert-login", tags=["Authentication"])
def admin_cert_login(payload: CertLoginRequest, response: Response, request: Request):
    check_rate_limit(request, "login", RL_LOGIN_PER_MIN)
    cert_data = None
    if payload.cert_pem and payload.cert_pem.strip():
        cert_data = payload.cert_pem.encode("utf-8")
    elif payload.p12_b64 and payload.p12_b64.strip():
        try:
            cert_data = base64.b64decode(payload.p12_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Base64 encoded PKCS#12 bundle.")
    else:
        raise HTTPException(status_code=400, detail="Please provide a valid PEM certificate or PKCS#12 bundle.")

    try:
        admin_user = verify_certificate_and_get_admin(cert_data, payload.p12_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Certificate verification failure: {str(e)}")

    token = generate_session_token(admin_user)
    set_admin_session_cookie(response, token, remember=True)
    return {
        "status": "success",
        "token": token,
        "username": admin_user,
        "auth_method": "x509_certificate",
        "role": "admin",
        "message": f"Certificate verified! Welcome back Administrator {admin_user}."
    }

@app.post("/radius/api/auth/logout", tags=["Authentication"])
@app.post("/api/auth/logout", tags=["Authentication"])
def admin_logout(request: Request, response: Response):
    # Revoke the presented token server-side when possible (issue #6); the
    # cookie is best-effort (Secure/HttpOnly flags must match to clear it).
    raw = request.cookies.get("admin_session")
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        raw = header[7:].strip() or raw
    if raw:
        try:
            revoke_session_token(raw, reason="logout")
        except Exception:
            pass
    response.delete_cookie(key="admin_session", samesite="lax", secure=COOKIE_SECURE, path="/")
    return {"status": "success", "message": "Logged out successfully"}

@app.get("/radius/api/auth/me", tags=["Authentication"])
@app.get("/api/auth/me", tags=["Authentication"])
def admin_get_current_user(current_admin: str = Depends(authenticate_admin)):
    return {
        "status": "success",
        "username": current_admin,
        "role": "admin",
        "authenticated": True
    }

# Public Health Check
@app.get("/radius/api/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
def public_health_check():
    db_ok = False
    db_error = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 as ok")
            db_ok = True
        conn.close()
    except Exception as e:
        db_error = str(e)

    radius_ok = False
    try:
        res = subprocess.run(["pgrep", "-f", "freeradius"], capture_output=True, text=True)
        if res.returncode == 0:
            radius_ok = True
        else:
            res2 = subprocess.run(["pgrep", "-f", "radiusd"], capture_output=True, text=True)
            radius_ok = res2.returncode == 0
    except Exception:
        pass

    overall_status = "healthy" if (db_ok and radius_ok) else "degraded"
    return {
        "status": overall_status,
        "database": {"connected": db_ok, "error": db_error, "host": POSTGRES_HOST, "database": POSTGRES_DB},
        "freeradius_process": {"running": radius_ok}
    }

# Protected OpenAPI / Swagger Documentation
@app.get("/radius/docs", include_in_schema=False)
def get_swagger_documentation(_: str = Depends(authenticate_admin)):
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url="/radius/openapi.json", title="RajLabs FreeRADIUS Docs")

@app.get("/radius/openapi.json", include_in_schema=False)
def get_open_api_endpoint(_: str = Depends(authenticate_admin)):
    from fastapi.openapi.utils import get_openapi
    return get_openapi(title="RajLabs FreeRADIUS API", version="2.0.0", routes=app.routes)

# Protected Statistics & Dashboard Overview
@app.get("/radius/api/stats", tags=["Stats"])
@app.get("/api/stats", tags=["Stats"])
def get_stats(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT username) as user_count FROM radcheck;")
            user_count = cur.fetchone()["user_count"]

            cur.execute("SELECT COUNT(*) as active_sessions FROM radacct WHERE acctstoptime IS NULL;")
            active_sessions = cur.fetchone()["active_sessions"]

            cur.execute("SELECT COUNT(*) as total_accounting FROM radacct;")
            total_accounting = cur.fetchone()["total_accounting"]

            cur.execute("SELECT COUNT(*) as total_auth_logs FROM radpostauth;")
            total_auth_logs = cur.fetchone()["total_auth_logs"]

            cur.execute("SELECT COUNT(*) as nas_count FROM nas;")
            nas_count = cur.fetchone()["nas_count"]

            cur.execute("SELECT COUNT(DISTINCT groupname) as group_count FROM radgroupreply;")
            group_count = cur.fetchone()["group_count"]

            try:
                cur.execute("SELECT COUNT(DISTINCT callingstationid) AS d FROM radacct WHERE callingstationid IS NOT NULL AND callingstationid <> '';")
                known_devices = cur.fetchone()["d"]
            except Exception:
                known_devices = 0

            # Count issued client certificates
            issued_certs = len([f for f in os.listdir(CLIENT_CERTS_DIR) if f.endswith(".p12")])

            return {
                "total_users": user_count,
                "active_sessions": active_sessions,
                "total_accounting_records": total_accounting,
                "total_auth_logs": total_auth_logs,
                "nas_clients": nas_count,
                "total_groups": group_count,
                "known_devices": known_devices,
                "client_certificates": issued_certs
            }
    finally:
        conn.close()

# User Management
@app.get("/radius/api/users", tags=["Users"])
@app.get("/api/users", tags=["Users"])
def list_users(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    rc.id, rc.username, rc.attribute, rc.op, rc.value,
                    rug.groupname
                FROM radcheck rc
                LEFT JOIN radusergroup rug ON rc.username = rug.username
                ORDER BY rc.username ASC
            """)
            checks = cur.fetchall()

            cur.execute("SELECT id, username, attribute, op, value FROM radreply ORDER BY username ASC")
            replies = cur.fetchall()

            # Active session counts per user (no secrets involved)
            active_counts: Dict[str, int] = {}
            try:
                cur.execute("SELECT username, COUNT(*) AS c FROM radacct WHERE acctstoptime IS NULL GROUP BY username")
                for r in cur.fetchall():
                    active_counts[r["username"]] = int(r["c"])
            except Exception:
                pass

            # Last successful/attempted auth per user
            last_auth: Dict[str, Any] = {}
            try:
                cur.execute("SELECT username, MAX(authdate) AS last_auth FROM radpostauth GROUP BY username")
                for r in cur.fetchall():
                    v = r["last_auth"]
                    last_auth[r["username"]] = v.isoformat() if hasattr(v, "isoformat") else str(v)
            except Exception:
                pass

            users_map = {}
            for row in checks:
                u = row["username"]
                if u not in users_map:
                    # Check if client certificate exists for this user
                    cert_path = os.path.join(CLIENT_CERTS_DIR, f"{u}.p12")
                    users_map[u] = {
                        "username": u,
                        "group": row["groupname"],
                        "has_certificate": os.path.exists(cert_path),
                        "password_type": None,
                        "active_sessions": 0,
                        "last_auth": None,
                        "check_attributes": [],
                        "reply_attributes": []
                    }
                if "Password" in row["attribute"] and not users_map[u]["password_type"]:
                    users_map[u]["password_type"] = row["attribute"]
                users_map[u]["check_attributes"].append({
                    "id": row["id"],
                    "attribute": row["attribute"],
                    "op": row["op"],
                    "value": "********" if "Password" in row["attribute"] else row["value"]
                })

            for row in replies:
                u = row["username"]
                if u in users_map:
                    users_map[u]["reply_attributes"].append({
                        "id": row["id"],
                        "attribute": row["attribute"],
                        "op": row["op"],
                        "value": row["value"]
                    })

            for u, data in users_map.items():
                data["active_sessions"] = active_counts.get(u, 0)
                data["last_auth"] = last_auth.get(u)

            return list(users_map.values())
    finally:
        conn.close()

@app.get("/radius/api/users/{username}", tags=["Users"])
@app.get("/api/users/{username}", tags=["Users"])
def get_user_detail(username: str, _: str = Depends(authenticate_admin)):
    """Single-user detail (passwords always masked) for edit drawers."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rc.id, rc.username, rc.attribute, rc.op, rug.groupname
                FROM radcheck rc
                LEFT JOIN radusergroup rug ON rc.username = rug.username
                WHERE rc.username = %s
            """, (username,))
            checks = cur.fetchall()
            if not checks:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
            cur.execute("SELECT id, username, attribute, op, value FROM radreply WHERE username = %s", (username,))
            replies = cur.fetchall()
            active_sessions = 0
            try:
                cur.execute("SELECT COUNT(*) AS c FROM radacct WHERE username = %s AND acctstoptime IS NULL", (username,))
                active_sessions = int(cur.fetchone()["c"])
            except Exception:
                pass
            last_auth = None
            try:
                cur.execute("SELECT MAX(authdate) AS last_auth FROM radpostauth WHERE username = %s", (username,))
                v = cur.fetchone()["last_auth"]
                last_auth = v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else None)
            except Exception:
                pass
            cert_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
            password_type = next((r["attribute"] for r in checks if "Password" in r["attribute"]), None)
            return {
                "username": username,
                "group": checks[0]["groupname"],
                "has_certificate": os.path.exists(cert_path),
                "password_type": password_type,
                "active_sessions": active_sessions,
                "last_auth": last_auth,
                "check_attributes": [
                    {"id": r["id"], "attribute": r["attribute"], "op": r["op"],
                     "value": "********" if "Password" in r["attribute"] else None}
                    for r in checks
                ],
                "reply_attributes": [
                    {"id": r["id"], "attribute": r["attribute"], "op": r["op"], "value": r["value"]}
                    for r in replies
                ],
            }
    finally:
        conn.close()

@app.post("/radius/api/users/password/generate", tags=["Users"])
@app.post("/api/users/password/generate", tags=["Users"])
def generate_password_endpoint(payload: PasswordGenerateRequest, admin_user: str = Depends(authenticate_admin)):
    length = max(PASSWORD_MIN_LENGTH, min(int(payload.length or 16), 64))
    password = generate_secure_password(length, payload.symbols is not False, payload.exclude_ambiguous is not False)
    info = password_strength(password)
    logger.info("Password generated by admin=%s length=%s strength=%s", admin_user, len(password), info["strength"])
    return {"password": password, "length": len(password), "entropy_bits": info["entropy_bits"], "strength": info["strength"]}

@app.get("/radius/api/users/password/policy", tags=["Users"])
@app.get("/api/users/password/policy", tags=["Users"])
def get_password_policy(_: str = Depends(authenticate_admin)):
    return {
        "min_length": PASSWORD_MIN_LENGTH,
        "max_length": PASSWORD_MAX_LENGTH,
        "require_upper": True,
        "require_lower": True,
        "require_digit": True,
        "require_symbol": True,
        "default_generate_length": 16,
    }

@app.post("/radius/api/users", tags=["Users"])
@app.post("/api/users", tags=["Users"])
def create_or_update_user(payload: UserCreateRequest, admin_user: str = Depends(authenticate_admin)):
    validate_password_policy(payload.password, payload.username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (payload.username,))
            existed = cur.fetchone() is not None
            cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (payload.username,))
            
            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, %s, ':=', %s)
            """, (payload.username, payload.password_type, payload.password))

            if payload.group:
                cur.execute("DELETE FROM radusergroup WHERE username = %s", (payload.username,))
                cur.execute("""
                    INSERT INTO radusergroup (username, groupname, priority)
                    VALUES (%s, %s, 1)
                """, (payload.username, payload.group))

            if payload.attributes:
                for attr, val in payload.attributes.items():
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = %s", (payload.username, attr))
                    cur.execute("""
                        INSERT INTO radreply (username, attribute, op, value)
                        VALUES (%s, %s, '=', %s)
                    """, (payload.username, attr, val))

            conn.commit()
            log_audit(admin_user, "user_create" if not existed else "user_update", payload.username, f"group={payload.group}")
            return {"status": "success", "created": not existed, "message": f"User '{payload.username}' {'created' if not existed else 'updated'} successfully"}
    finally:
        conn.close()

@app.delete("/radius/api/users/{username}", tags=["Users"])
@app.delete("/api/users/{username}", tags=["Users"])
def delete_user(username: str, admin_user: str = Depends(authenticate_admin)):
    username = validate_username(username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radcheck WHERE username = %s", (username,))
            cur.execute("DELETE FROM radreply WHERE username = %s", (username,))
            cur.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
            conn.commit()
            # Revoke EAP-TLS identity too (issue #10): a deleted user must not
            # keep a working certificate. Portal downloads then 404.
            removed_certs = 0
            for suffix in (".key", ".csr", ".crt", ".p12", "-chain.crt"):
                try:
                    p = safe_client_path(username, suffix)
                except HTTPException:
                    continue
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        removed_certs += 1
                except OSError as e:
                    logger.warning("Cert cleanup failed for %s%s: %s", username, suffix, e)
            log_audit(admin_user, "user_delete", username,
                      f"cert_files_removed={removed_certs}" if removed_certs else None)
            msg = f"User '{username}' deleted successfully"
            if removed_certs:
                msg += f" (revoked + removed {removed_certs} certificate file(s))"
            return {"status": "success", "message": msg, "cert_files_removed": removed_certs}
    finally:
        conn.close()

# Verified-device lockdown (per-user MAC allowlist, default OFF)
@app.get("/radius/api/users/{username}/devices", tags=["Users"])
@app.get("/api/users/{username}/devices", tags=["Users"])
def get_device_policy(username: str, _: str = Depends(authenticate_admin)):
    return {"username": validate_username(username), **get_user_devices(validate_username(username))}


@app.put("/radius/api/users/{username}/device-policy", tags=["Users"])
@app.put("/api/users/{username}/device-policy", tags=["Users"])
def set_device_policy(username: str, payload: DevicePolicyUpdate, admin_user: str = Depends(authenticate_admin)):
    username = validate_username(username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_device_policy (username, require_verified, updated_at) VALUES (%s, %s, NOW()) "
                "ON CONFLICT (username) DO UPDATE SET require_verified = EXCLUDED.require_verified, updated_at = NOW()",
                (username, payload.require_verified),
            )
            conn.commit()
    finally:
        conn.close()
    state = "ON — only verified devices can connect" if payload.require_verified else "OFF — any device can connect"
    log_audit(admin_user, "device_policy", username, f"require_verified={payload.require_verified}")
    return {"status": "success", "username": username,
            "require_verified": payload.require_verified,
            "message": f"MAC lockdown {state} for '{username}'."}


@app.post("/radius/api/users/{username}/devices", tags=["Users"])
@app.post("/api/users/{username}/devices", tags=["Users"])
def add_verified_device(username: str, payload: VerifiedDeviceAdd, admin_user: str = Depends(authenticate_admin)):
    username = validate_username(username)
    mac = normalize_mac(payload.mac)
    if not mac:
        raise HTTPException(status_code=422, detail="Invalid MAC. Use e.g. AA:BB:CC:DD:EE:FF.")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (username,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
            cur.execute(
                "INSERT INTO verified_devices (username, mac, label, added_by) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (username, mac) DO UPDATE SET label = EXCLUDED.label",
                (username, mac, (payload.label or "").strip() or None, admin_user),
            )
            conn.commit()
    finally:
        conn.close()
    log_audit(admin_user, "device_trust", username, f"mac={pretty_mac(mac)} label={payload.label or '-'}")
    return {"status": "success", "username": username, "mac": mac, "pretty": pretty_mac(mac),
            "vendor": mac_vendor(mac),
            "message": f"Device {pretty_mac(mac)} verified for '{username}'."}


@app.delete("/radius/api/users/{username}/devices/{mac}", tags=["Users"])
@app.delete("/api/users/{username}/devices/{mac}", tags=["Users"])
def remove_verified_device(username: str, mac: str, admin_user: str = Depends(authenticate_admin)):
    username = validate_username(username)
    norm = normalize_mac(mac)
    if not norm:
        raise HTTPException(status_code=422, detail="Invalid MAC.")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM verified_devices WHERE username = %s AND mac = %s", (username, norm))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="That device is not on this user's verified list.")
            conn.commit()
    finally:
        conn.close()
    log_audit(admin_user, "device_untrust", username, f"mac={pretty_mac(norm)}")
    return {"status": "success", "message": f"Device {pretty_mac(norm)} removed from '{username}'."}


@app.put("/radius/api/users/{username}/password", tags=["Users"])
@app.put("/api/users/{username}/password", tags=["Users"])
def update_user_password(username: str, payload: PasswordChangeRequest, admin_user: str = Depends(authenticate_admin)):
    validate_password_policy(payload.password, username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (username,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
            cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (username,))
            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, %s, ':=', %s)
            """, (username, payload.password_type, payload.password))
            conn.commit()
    finally:
        conn.close()
    # Audit (never logs the plaintext password)
    info = password_strength(payload.password)
    log_audit(admin_user, "password_reset", username, f"type={payload.password_type} strength={info['strength']}")
    disconnected = 0
    if payload.disconnect_active:
        try:
            conn2 = get_db_connection()
            with conn2.cursor() as cur:
                cur.execute("SELECT DISTINCT nasipaddress::text AS nas_ip FROM radacct WHERE username = %s AND acctstoptime IS NULL AND nasipaddress IS NOT NULL", (username,))
                nas_ips = [r["nas_ip"] for r in cur.fetchall() if r["nas_ip"]]
            conn2.close()
            for nas_ip in nas_ips:
                try:
                    ok, _ = send_coa_disconnect(username, nas_ip, RADIUS_SECRET)
                    if ok:
                        disconnected += 1
                except Exception:
                    continue
        except Exception as e:
            logger.warning("CoA disconnect after password reset failed for %s: %s", username, e)
    # Self-reset signs out everywhere (issue #6): the old admin password must not
    # leave other sessions valid.
    sessions_revoked = False
    if username == admin_user:
        try:
            revoke_all_user_tokens(admin_user, reason="self_password_reset")
            sessions_revoked = True
        except Exception as e:
            logger.warning("Sign-out-everywhere failed for %s: %s", admin_user, e)
    from datetime import datetime, timezone
    logger.info("Password reset username=%s by=%s disconnect=%s sessions_dropped=%s sessions_revoked=%s", username, admin_user, payload.disconnect_active, disconnected, sessions_revoked)
    return {
        "status": "success",
        "message": f"Password updated for user '{username}'" + (f" ({disconnected} session(s) disconnected)" if payload.disconnect_active else ""),
        "username": username,
        "updated_by": admin_user,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "disconnected_sessions": disconnected,
    }

@app.get("/radius/api/audit", tags=["Users"])
@app.get("/api/audit", tags=["Users"])
def list_audit_log(limit: int = 50, _: str = Depends(authenticate_admin)):
    ensure_audit_table()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, ts, admin_user, action, target_user, detail FROM admin_audit_log ORDER BY id DESC LIMIT %s", (min(limit, 200),))
            rows = cur.fetchall()
            for r in rows:
                if hasattr(r.get("ts"), "isoformat"):
                    r["ts"] = r["ts"].isoformat()
            return rows
    finally:
        conn.close()

# ============================================================================
# Public client config + Cert-Signer connectivity status
# ============================================================================
def _probe_http_json(url: str, headers: Dict[str, str], timeout: int = 5) -> Dict[str, Any]:
    """Single GET probe. Never raises; never logs secrets."""
    start = time.time()
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2048).decode("utf-8", "replace")
            return {"ok": True, "status": resp.status, "body": body,
                    "latency_ms": round((time.time() - start) * 1000, 1)}
    except urllib.error.HTTPError as e:
        try:
            body = e.read(512).decode("utf-8", "replace")
        except Exception:
            body = ""
        return {"ok": False, "status": e.code, "body": body,
                "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "status": None, "body": f"{type(e).__name__}: {e}",
                "latency_ms": round((time.time() - start) * 1000, 1)}

@app.get("/radius/api/public-config", tags=["Health"])
@app.get("/api/public-config", tags=["Health"])
def get_public_config(request: Request):
    """Unauthenticated client facts: RADIUS host/ports, portal path, signer presence (no secrets)."""
    host = RADIUS_PUBLIC_HOST or (request.headers.get("host", "").split(":")[0] if request.headers.get("host") else "")
    return {
        "radius_host": host,
        "radius_ports": {"auth": 1812, "acct": 1813, "coa": 3799},
        "portal_path": "/radius/portal",
        "signer_configured": bool(CERT_SIGNER_API_URL),
    }

@app.get("/radius/api/certs/signer-status", tags=["Certificates"])
@app.get("/api/certs/signer-status", tags=["Certificates"])
def cert_signer_status(refresh: bool = False, _: str = Depends(authenticate_admin)):
    """Live Cert-Signer health: reachability + API-key validity. Key value never returned."""
    from urllib.parse import urlparse
    from datetime import datetime, timezone
    now = time.time()
    if not refresh and _SIGNER_STATUS_CACHE["data"] and now - _SIGNER_STATUS_CACHE["at"] < 30:
        return _SIGNER_STATUS_CACHE["data"]

    checked_at = datetime.now(timezone.utc).isoformat()
    if not CERT_SIGNER_API_URL:
        data = {
            "configured": False, "mode": "local", "reachable": True, "key_valid": None,
            "status_code": None, "latency_ms": None, "host": None, "checked_at": checked_at,
            "detail": "CERT_SIGNER_API_URL is not set — certificates are signed by the local FreeRADIUS CA. Set CERT_SIGNER_API_URL (+ CERT_SIGNER_API_KEY) to use the central Rajlabs-CA.",
        }
        _SIGNER_STATUS_CACHE.update({"at": now, "data": data})
        return data

    host = urlparse(CERT_SIGNER_API_URL).hostname or CERT_SIGNER_API_URL
    headers = {"Accept": "application/json"}
    if CERT_SIGNER_API_KEY:
        headers["x-api-key"] = CERT_SIGNER_API_KEY

    probe = None
    tried = []
    for path in ("/api/v1/health", "/health"):
        r = _probe_http_json(CERT_SIGNER_API_URL + path, headers)
        tried.append({"path": path, "status": r["status"]})
        if r["ok"] or r["status"] in (401, 403):
            probe = r
            break
        probe = r  # keep last network-level result if nothing answered

    assert probe is not None
    if probe["ok"]:
        data = {
            "configured": True, "mode": "remote", "reachable": True,
            "key_valid": True if CERT_SIGNER_API_KEY else None,
            "status_code": probe["status"], "latency_ms": probe["latency_ms"],
            "host": host, "checked_at": checked_at,
            "detail": f"Connected to central Cert-Signer at {host} ({probe['latency_ms']} ms). New certificates will be signed remotely."
                      + ("" if CERT_SIGNER_API_KEY else " No API key configured — signer accepts unauthenticated health checks."),
        }
    elif probe["status"] in (401, 403):
        data = {
            "configured": True, "mode": "local-fallback", "reachable": True,
            "key_valid": False, "status_code": probe["status"],
            "latency_ms": probe["latency_ms"], "host": host, "checked_at": checked_at,
            "detail": f"Signer at {host} is reachable but rejected our API key (HTTP {probe['status']}). Check CERT_SIGNER_API_KEY. Certificates will fall back to the local CA until the key is fixed.",
        }
    else:
        data = {
            "configured": True, "mode": "local-fallback", "reachable": False,
            "key_valid": None, "status_code": probe["status"],
            "latency_ms": probe["latency_ms"], "host": host, "checked_at": checked_at,
            "detail": f"Cannot reach Cert-Signer at {host}: {probe['body'][:160]}. Certificates will fall back to the local CA. Check CERT_SIGNER_API_URL and network egress.",
        }
    logger.info("Signer status checked by=%s reachable=%s mode=%s host=%s", _, data["reachable"], data["mode"], host)
    _SIGNER_STATUS_CACHE.update({"at": now, "data": data})
    return data

# ============================================================================
# Group Policy Management & Presets
# ============================================================================
GROUP_PRESETS = [
    {
        "id": "staff-enterprise",
        "name": "🚀 Enterprise Staff",
        "groupname": "staff",
        "description": "High-throughput policy for corporate employees and development teams.",
        "simultaneous_use": 5,
        "bandwidth_down_kbps": 100000, # 100 Mbps
        "bandwidth_up_kbps": 50000,   # 50 Mbps
        "session_timeout": 86400,     # 24 Hours
        "idle_timeout": 7200,         # 2 Hours
        "acct_interim_interval": 300,
        "vlan_id": 10,
        "framed_pool": "corp_pool",
        "mikrotik_rate_limit": "50M/100M",
        "is_admin": False,
        "badge": "100M/50M • 5 Dev • VLAN 10"
    },
    {
        "id": "guest-hotspot",
        "name": "☕ Guest Hotspot",
        "groupname": "guests",
        "description": "Fair-share rate-limited policy with time-based session caps for cafe and visitor Wi-Fi.",
        "simultaneous_use": 1,
        "bandwidth_down_kbps": 10000, # 10 Mbps
        "bandwidth_up_kbps": 2000,   # 2 Mbps
        "session_timeout": 7200,     # 2 Hours
        "idle_timeout": 900,         # 15 Minutes
        "acct_interim_interval": 120,
        "vlan_id": 30,
        "framed_pool": "guest_pool",
        "mikrotik_rate_limit": "2M/10M",
        "is_admin": False,
        "badge": "10M/2M • 1 Dev • 2hr Cap • VLAN 30"
    },
    {
        "id": "vip-uncapped",
        "name": "👑 VIP / Executive",
        "groupname": "vip",
        "description": "Unthrottled maximum priority tier with high concurrency for executives and core servers.",
        "simultaneous_use": 10,
        "bandwidth_down_kbps": None,
        "bandwidth_up_kbps": None,
        "session_timeout": None,
        "idle_timeout": 86400,
        "acct_interim_interval": 300,
        "vlan_id": 1,
        "framed_pool": "vip_pool",
        "mikrotik_rate_limit": None,
        "is_admin": False,
        "badge": "Uncapped • 10 Dev • 24hr Idle"
    },
    {
        "id": "iot-isolated",
        "name": "🤖 Smart Office / IoT",
        "groupname": "iot",
        "description": "Isolated low-bandwidth network policy for smart appliances, sensors, printers, and cameras.",
        "simultaneous_use": 1,
        "bandwidth_down_kbps": 5000,  # 5 Mbps
        "bandwidth_up_kbps": 1000,   # 1 Mbps
        "session_timeout": None,
        "idle_timeout": 86400,
        "acct_interim_interval": 600,
        "vlan_id": 50,
        "framed_pool": "iot_pool",
        "mikrotik_rate_limit": "1M/5M",
        "is_admin": False,
        "badge": "5M/1M • 1 Dev • VLAN 50"
    },
    {
        "id": "security-admins",
        "name": "🛡️ Network Administrators",
        "groupname": "admins",
        "description": "Administrative authority with administrative console access and elevated management rights.",
        "simultaneous_use": 5,
        "bandwidth_down_kbps": None,
        "bandwidth_up_kbps": None,
        "session_timeout": None,
        "idle_timeout": 3600,
        "acct_interim_interval": 300,
        "vlan_id": 99,
        "framed_pool": "mgmt_pool",
        "mikrotik_rate_limit": None,
        "is_admin": True,
        "badge": "Admin Console Access • VLAN 99"
    }
]

# ----------------------------------------------------------------------------
# Human-readable RADIUS glossary (single source of truth for hover tooltips).
# Keys are lower-cased attribute / term names; values are plain-English help.
# The frontend fetches the same map via GET /radius/api/glossary.
# ----------------------------------------------------------------------------
RADIUS_GLOSSARY: Dict[str, str] = {
    "user-name": "Simple: the login name. Example: User-Name = 'raj'. This is who is trying to connect.",
    "cleartext-password": "Simple: the password saved for this user. Hidden as ******** in the screen for safety.",
    "simultaneous-use": "Simple: how many phones/laptops can use this login at the same time. Example: 2 = only 2 devices together.",
    "session-timeout": "Simple: max Wi-Fi time before auto-logout. Example: 7200 = 2 hours, then user must login again.",
    "idle-timeout": "Simple: if phone sits idle (no internet use) for this long, Wi-Fi cuts off. Example: 900 = 15 mins idle.",
    "acct-interim-interval": "Simple: how often the router sends 'still online + data used' updates. Example: 300 = every 5 mins.",
    "wispr-bandwidth-max-down": "Simple: max download speed. Example: 50000000 = 50 Mbps download limit.",
    "wispr-bandwidth-max-up": "Simple: max upload speed. Example: 25000000 = 25 Mbps upload limit.",
    "mikrotik-rate-limit": "Simple: MikroTik speed rule. Example: '25M/50M' = 25 Mbps upload / 50 Mbps download.",
    "mikrotik-group": "Simple: which MikroTik profile this user gets (like staff or guest speed settings).",
    "tunnel-type": "Simple: technical code that says 'use VLAN'. Value 13 always means VLAN.",
    "tunnel-medium-type": "Simple: technical code that says 'over ethernet cable/Wi-Fi'. Value 6 = normal network.",
    "tunnel-private-group-id": "Simple: which separate network (VLAN) the user goes to. Example: 10 = staff network, 30 = guest network.",
    "framed-ip-address": "Simple: the Wi-Fi address given to this phone/laptop. Example: Framed-IP-Address = 10.10.0.12 means that device got 10.10.0.12.",
    "framed-ip-netmask": "Simple: tells how big the local network is. Example: 255.255.255.0 = about 250 devices can fit.",
    "framed-pool": "Simple: name of the address box the router picks IPs from. Example: 'staff_pool'.",
    "framed-protocol": "Simple: how internet is delivered to the device. Usually PPP or Wi-Fi login.",
    "calling-station-id": "Simple: the phone/laptop's own Wi-Fi ID (MAC). Example: AA-BB-CC-DD-EE-FF. Tells which exact device connected.",
    "called-station-id": "Simple: which Wi-Fi box (AP) the user joined. Shows AP address + name like 'MyWiFi'.",
    "nas-ip-address": "Simple: the Wi-Fi router's address that asked us 'can this user join?'. That router must be added in NAS Clients.",
    "nas-identifier": "Simple: nickname of the Wi-Fi router (instead of its IP number).",
    "nas-port": "Simple: which plug/port of the router the user came from. Mostly just info.",
    "nas-port-type": "Simple: what kind of connection it is. 19 = Wi-Fi wireless.",
    "acct-session-id": "Simple: bill-slip number for this one connection. Needed to disconnect one device without touching others.",
    "acct-start-time": "Simple: when this Wi-Fi connection started.",
    "acct-stop-time": "Simple: when it ended. If empty, user is still online now.",
    "acct-session-time": "Simple: total time connected, in seconds. Example: 3600 = 1 hour.",
    "acct-input-octets": "Simple: how much the user uploaded. Example: 1000000 = about 1 MB uploaded.",
    "acct-output-octets": "Simple: how much the user downloaded. Example: 100000000 = about 100 MB downloaded.",
    "acct-terminate-cause": "Simple: why Wi-Fi ended. Examples: user turned Wi-Fi off, idle too long, time over, admin kicked.",
    "acct-status-type": "Simple: what happened now — Started, Still going (update), or Stopped.",
    "service-type": "Simple: what access is given. Framed-User = normal Wi-Fi. Administrative-User = can open admin page.",
    "reply-message": "Simple: message shown to user, like 'wrong password' or 'welcome back'.",
    "filter-id": "Simple: rule-name that blocks/allows sites. Example: 'guest_acl' = guests can only open basic sites.",
    "login-time": "Simple: allowed hours. Example: 'Wk0800-1800' = weekdays 8am to 6pm only.",
    "expiration": "Simple: expiry date of this account. After this date login stops. Good for guests.",
    "auth-type": "Simple: how password is checked (PAP, CHAP, EAP). You normally don't need to change this.",
    "eap-type": "Simple: Wi-Fi login style. EAP-TLS = with certificate (no password). PEAP = with username + password.",
    "access-accept": "Simple: login OK — password correct, allowed in.",
    "access-reject": "Simple: login failed — wrong password or blocked by rule (like too many devices).",
    "coa": "Simple: remote kick button. Sends 'disconnect now' to the router on port 3799.",
    "nas-secret": "Simple: secret password between router and this server. Must be exactly same on both sides, else Wi-Fi login silently fails.",
    "cidr": "Simple: short way to write many IPs. Example: 192.168.1.0/24 = all 192.168.1.x addresses.",
}

def _fmt_duration(seconds: str) -> str:
    try:
        s = int(seconds)
        if s >= 3600 and s % 3600 == 0:
            return f"{s // 3600}h ({seconds}s)"
        if s >= 3600:
            return f"{s / 3600:.1f}h ({seconds}s)"
        if s >= 60:
            return f"{s // 60} min ({seconds}s)"
        return f"{seconds}s"
    except Exception:
        return str(seconds)

def glossary_lookup(term: str) -> str:
    """Case-insensitive glossary lookup with normalised key matching."""
    if not term:
        return ""
    key = term.strip().lower()
    if key in RADIUS_GLOSSARY:
        return RADIUS_GLOSSARY[key]
    compact = key.replace("_", "-").replace(" ", "-")
    if compact in RADIUS_GLOSSARY:
        return RADIUS_GLOSSARY[compact]
    return ""

def explain_attribute(attr: str, val: str) -> str:
    """Value-aware one-liner in simple words: '<Attr> = <val> — what it means.'"""
    attr_lower = (attr or "").strip().lower()
    base = glossary_lookup(attr_lower)
    if "simultaneous-use" in attr_lower:
        return f"Simultaneous-Use = {val} — simple: only {val} device(s) can use this login together."
    elif "bandwidth-max-down" in attr_lower:
        try:
            mbps = f"{int(val) // 1_000_000} Mbps" if str(val).isdigit() else str(val)
        except Exception:
            mbps = str(val)
        return f"WISPr-Bandwidth-Max-Down = {val} — simple: download speed limit {mbps}."
    elif "bandwidth-max-up" in attr_lower:
        try:
            mbps = f"{int(val) // 1_000_000} Mbps" if str(val).isdigit() else str(val)
        except Exception:
            mbps = str(val)
        return f"WISPr-Bandwidth-Max-Up = {val} — simple: upload speed limit {mbps}."
    elif "mikrotik-rate-limit" in attr_lower:
        return f"Mikrotik-Rate-Limit = {val} — simple: router speed rule {val} (upload/download)."
    elif "session-timeout" in attr_lower:
        return f"Session-Timeout = {val} — simple: Wi-Fi cuts after {_fmt_duration(val)}, login again."
    elif "idle-timeout" in attr_lower:
        return f"Idle-Timeout = {val} — simple: if no internet use for {_fmt_duration(val)}, Wi-Fi cuts."
    elif "acct-interim-interval" in attr_lower:
        return f"Acct-Interim-Interval = {val} — simple: router sends usage update every {val} secs."
    elif "tunnel-private-group-id" in attr_lower:
        return f"Tunnel-Private-Group-ID = {val} — simple: puts device in separate network #{val} (like staff vs guest)."
    elif "framed-pool" in attr_lower:
        return f"Framed-Pool = {val} — simple: router picks IP from box named '{val}'."
    elif "framed-ip-address" in attr_lower:
        return f"Framed-IP-Address = {val} — simple: this is the Wi-Fi address given to the phone/laptop."
    elif "calling-station-id" in attr_lower:
        return f"Calling-Station-Id = {val} — simple: this is the phone/laptop's own Wi-Fi ID."
    elif "called-station-id" in attr_lower:
        return f"Called-Station-Id = {val} — simple: this is the Wi-Fi box the user joined."
    if base:
        return f"{attr} = {val} — {base}"
    return f"{attr} = {val}"

def generate_policy_summary(sim_use, down_k, up_k, s_timeout, i_timeout, vlan, is_admin, mikrotik) -> str:
    parts = []
    if is_admin:
        parts.append("👑 Admin Console Access")
    if sim_use:
        parts.append(f"📱 Max {sim_use} device{'s' if sim_use > 1 else ''}")
    if down_k and up_k:
        parts.append(f"⚡ ↓{down_k//1000}M / ↑{up_k//1000}M")
    elif down_k:
        parts.append(f"⚡ ↓{down_k//1000}M")
    elif mikrotik:
        parts.append(f"⚡ MikroTik {mikrotik}")
    else:
        parts.append("🚀 Uncapped Speed")
        
    if s_timeout:
        parts.append(f"⏱️ {s_timeout//3600 if s_timeout >= 3600 else s_timeout//60}{'h' if s_timeout >= 3600 else 'm'} session")
    if i_timeout:
        parts.append(f"💤 {i_timeout//60}m idle timeout")
    if vlan:
        parts.append(f"🏷️ VLAN #{vlan}")
    return " • ".join(parts) if parts else "Open Policy (No limits)"

@app.get("/radius/api/groups/presets", tags=["Groups"])
@app.get("/api/groups/presets", tags=["Groups"])
def get_group_presets(_: str = Depends(authenticate_admin)):
    return GROUP_PRESETS


@app.get("/radius/api/glossary", tags=["Groups"])
@app.get("/api/glossary", tags=["Groups"])
def get_glossary(_: str = Depends(authenticate_admin)):
    """Simple-words dictionary for hover tooltips. Keys are lower-case terms."""
    return RADIUS_GLOSSARY

@app.get("/radius/api/groups", tags=["Groups"])
@app.get("/api/groups", tags=["Groups"])
def list_groups(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Fetch reply attributes
            cur.execute("SELECT id, groupname, attribute, op, value FROM radgroupreply ORDER BY groupname ASC, attribute ASC")
            reply_rows = cur.fetchall()

            # 2. Fetch check attributes
            cur.execute("SELECT id, groupname, attribute, op, value FROM radgroupcheck ORDER BY groupname ASC, attribute ASC")
            check_rows = cur.fetchall()

            # 3. Fetch users per group
            cur.execute("SELECT groupname, username FROM radusergroup ORDER BY groupname ASC, username ASC")
            user_rows = cur.fetchall()

            users_by_group = {}
            for u in user_rows:
                g = u["groupname"]
                if g not in users_by_group:
                    users_by_group[g] = []
                users_by_group[g].append(u["username"])

            groups_map = {}

            # Gather all known group names
            all_groups = set([r["groupname"] for r in reply_rows] + [c["groupname"] for c in check_rows] + list(users_by_group.keys()))
            for g in sorted(all_groups):
                groups_map[g] = {
                    "groupname": g,
                    "user_count": len(users_by_group.get(g, [])),
                    "users": users_by_group.get(g, []),
                    "simultaneous_use": None,
                    "session_timeout": None,
                    "idle_timeout": None,
                    "acct_interim_interval": None,
                    "bandwidth_down_kbps": None,
                    "bandwidth_up_kbps": None,
                    "mikrotik_rate_limit": None,
                    "vlan_id": None,
                    "framed_pool": None,
                    "is_admin": (g == "admins"),
                    "reply_attributes": [],
                    "check_attributes": [],
                    "summary": ""
                }

            # Populate reply attributes & extracted values
            for r in reply_rows:
                g = r["groupname"]
                attr = r["attribute"]
                val = r["value"]
                explanation = explain_attribute(attr, val)
                groups_map[g]["reply_attributes"].append({
                    "id": r["id"],
                    "attribute": attr,
                    "op": r["op"],
                    "value": val,
                    "explanation": explanation
                })

                if attr == "Simultaneous-Use" and val.isdigit():
                    groups_map[g]["simultaneous_use"] = int(val)
                elif attr == "Session-Timeout" and val.isdigit():
                    groups_map[g]["session_timeout"] = int(val)
                elif attr == "Idle-Timeout" and val.isdigit():
                    groups_map[g]["idle_timeout"] = int(val)
                elif attr == "Acct-Interim-Interval" and val.isdigit():
                    groups_map[g]["acct_interim_interval"] = int(val)
                elif attr == "WISPr-Bandwidth-Max-Down" and val.isdigit():
                    groups_map[g]["bandwidth_down_kbps"] = int(val) // 1000
                elif attr == "WISPr-Bandwidth-Max-Up" and val.isdigit():
                    groups_map[g]["bandwidth_up_kbps"] = int(val) // 1000
                elif attr == "Mikrotik-Rate-Limit":
                    groups_map[g]["mikrotik_rate_limit"] = val
                elif attr == "Tunnel-Private-Group-ID" and val.isdigit():
                    groups_map[g]["vlan_id"] = int(val)
                elif attr == "Framed-Pool":
                    groups_map[g]["framed_pool"] = val
                elif attr == "Service-Type" and val == "Administrative-User":
                    groups_map[g]["is_admin"] = True

            # Populate check attributes
            for c in check_rows:
                g = c["groupname"]
                attr = c["attribute"]
                val = c["value"]
                explanation = explain_attribute(attr, val)
                groups_map[g]["check_attributes"].append({
                    "id": c["id"],
                    "attribute": attr,
                    "op": c["op"],
                    "value": val,
                    "explanation": explanation
                })
                if attr == "Simultaneous-Use" and val.isdigit():
                    groups_map[g]["simultaneous_use"] = int(val)

            # Generate summaries
            for g, data in groups_map.items():
                data["summary"] = generate_policy_summary(
                    data["simultaneous_use"],
                    data["bandwidth_down_kbps"],
                    data["bandwidth_up_kbps"],
                    data["session_timeout"],
                    data["idle_timeout"],
                    data["vlan_id"],
                    data["is_admin"],
                    data["mikrotik_rate_limit"]
                )

            return list(groups_map.values())
    finally:
        conn.close()

@app.post("/radius/api/groups", tags=["Groups"])
@app.post("/api/groups", tags=["Groups"])
def create_or_update_group(payload: GroupCreateRequest, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Clean existing group attributes
            cur.execute("DELETE FROM radgroupreply WHERE groupname = %s", (payload.groupname,))
            cur.execute("DELETE FROM radgroupcheck WHERE groupname = %s", (payload.groupname,))

            # 1. Simultaneous-Use (Check & Reply)
            if payload.simultaneous_use is not None and payload.simultaneous_use > 0:
                cur.execute("INSERT INTO radgroupcheck (groupname, attribute, op, value) VALUES (%s, 'Simultaneous-Use', ':=', %s)", (payload.groupname, str(payload.simultaneous_use)))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Simultaneous-Use', '=', %s)", (payload.groupname, str(payload.simultaneous_use)))

            # 2. Administrative Role
            if payload.is_admin or payload.groupname == "admins":
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Service-Type', '=', 'Administrative-User')", (payload.groupname,))

            # 3. Session & Idle Timeouts
            if payload.session_timeout is not None and payload.session_timeout > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Session-Timeout', '=', %s)", (payload.groupname, str(payload.session_timeout)))

            if payload.idle_timeout is not None and payload.idle_timeout > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Idle-Timeout', '=', %s)", (payload.groupname, str(payload.idle_timeout)))

            # 4. Accounting Interim Interval
            if payload.acct_interim_interval is not None and payload.acct_interim_interval > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Acct-Interim-Interval', '=', %s)", (payload.groupname, str(payload.acct_interim_interval)))

            # 5. Bandwidth Limits (WISPr standard)
            if payload.bandwidth_down_kbps is not None and payload.bandwidth_down_kbps > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'WISPr-Bandwidth-Max-Down', '=', %s)", (payload.groupname, str(payload.bandwidth_down_kbps * 1000)))

            if payload.bandwidth_up_kbps is not None and payload.bandwidth_up_kbps > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'WISPr-Bandwidth-Max-Up', '=', %s)", (payload.groupname, str(payload.bandwidth_up_kbps * 1000)))

            # 6. MikroTik Rate Limit
            if payload.mikrotik_rate_limit and payload.mikrotik_rate_limit.strip():
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Mikrotik-Rate-Limit', '=', %s)", (payload.groupname, payload.mikrotik_rate_limit.strip()))

            # 7. 802.1Q VLAN Dynamic Tagging
            if payload.vlan_id is not None and payload.vlan_id > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Type', '=', '13')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Medium-Type', '=', '6')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Private-Group-ID', '=', %s)", (payload.groupname, str(payload.vlan_id)))

            # 8. DHCP Framed Pool
            if payload.framed_pool and payload.framed_pool.strip():
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Framed-Pool', '=', %s)", (payload.groupname, payload.framed_pool.strip()))

            # 9. Extra Custom Reply & Check Attributes
            if payload.extra_reply_attributes:
                for k, v in payload.extra_reply_attributes.items():
                    if k.strip() and v.strip():
                        cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, %s, '=', %s)", (payload.groupname, k.strip(), v.strip()))

            if payload.extra_check_attributes:
                for k, v in payload.extra_check_attributes.items():
                    if k.strip() and v.strip():
                        cur.execute("INSERT INTO radgroupcheck (groupname, attribute, op, value) VALUES (%s, %s, ':=', %s)", (payload.groupname, k.strip(), v.strip()))

            conn.commit()
            return {"status": "success", "message": f"Policy Group '{payload.groupname}' saved successfully!"}
    finally:
        conn.close()

@app.post("/radius/api/groups/apply-preset", tags=["Groups"])
@app.post("/api/groups/apply-preset", tags=["Groups"])
def apply_group_preset(payload: ApplyPresetRequest, _: str = Depends(authenticate_admin)):
    preset = next((p for p in GROUP_PRESETS if p["id"] == payload.preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{payload.preset_id}' not found.")
    
    groupname = payload.groupname or preset["groupname"]
    req = GroupCreateRequest(
        groupname=groupname,
        description=preset.get("description"),
        simultaneous_use=preset.get("simultaneous_use"),
        bandwidth_down_kbps=preset.get("bandwidth_down_kbps"),
        bandwidth_up_kbps=preset.get("bandwidth_up_kbps"),
        session_timeout=preset.get("session_timeout"),
        idle_timeout=preset.get("idle_timeout"),
        acct_interim_interval=preset.get("acct_interim_interval"),
        vlan_id=preset.get("vlan_id"),
        framed_pool=preset.get("framed_pool"),
        mikrotik_rate_limit=preset.get("mikrotik_rate_limit"),
        is_admin=preset.get("is_admin", False)
    )
    return create_or_update_group(req, _)

@app.delete("/radius/api/groups/{groupname}", tags=["Groups"])
@app.delete("/api/groups/{groupname}", tags=["Groups"])
def delete_group(groupname: str, _: str = Depends(authenticate_admin)):
    if groupname == "admins":
        raise HTTPException(status_code=400, detail="Cannot delete default 'admins' system group.")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radgroupreply WHERE groupname = %s", (groupname,))
            cur.execute("DELETE FROM radgroupcheck WHERE groupname = %s", (groupname,))
            cur.execute("DELETE FROM radusergroup WHERE groupname = %s", (groupname,))
            conn.commit()
            return {"status": "success", "message": f"Policy Group '{groupname}' and associated user assignments removed successfully."}
    finally:
        conn.close()

# NAS Clients
@app.get("/radius/api/nas", tags=["NAS"])
@app.get("/api/nas", tags=["NAS"])
def list_nas(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nasname, shortname, type, ports, secret, description FROM nas ORDER BY id ASC")
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/radius/api/nas", tags=["NAS"])
@app.post("/api/nas", tags=["NAS"])
def create_nas(payload: NasCreateRequest, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO nas (nasname, shortname, type, secret, description)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (payload.nasname, payload.shortname, payload.type, payload.secret, payload.description))
            new_id = cur.fetchone()["id"]
            conn.commit()
            return {"status": "success", "id": new_id, "message": f"NAS client '{payload.shortname}' added successfully"}
    finally:
        conn.close()

@app.delete("/radius/api/nas/{nas_id}", tags=["NAS"])
@app.delete("/api/nas/{nas_id}", tags=["NAS"])
def delete_nas(nas_id: int, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nas WHERE id = %s", (nas_id,))
            conn.commit()
            return {"status": "success", "message": f"NAS client #{nas_id} deleted successfully"}
    finally:
        conn.close()

# Logs & Accounting Sessions
@app.get("/radius/api/accounting", tags=["Logs & Accounting"])
@app.get("/api/accounting", tags=["Logs & Accounting"])
def get_accounting(limit: int = 50, active_only: bool = False, username: Optional[str] = None,
                   since: Optional[str] = None, until: Optional[str] = None,
                   _: str = Depends(authenticate_admin)):
    """Accounting records. `limit` is clamped 1..500 (LIMIT -1 would dump the table).
    Optional `since`/`until` filter acctstarttime (ISO date or datetime)."""
    from datetime import datetime
    try:
        limit = min(max(int(limit or 50), 1), 500)
    except (TypeError, ValueError):
        limit = 50
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT
                    radacctid, acctsessionid, username, nasipaddress::text,
                    acctstarttime, acctstoptime, acctsessiontime,
                    acctinputoctets, acctoutputoctets, acctterminatecause,
                    framedipaddress::text, callingstationid, calledstationid
                FROM radacct
                WHERE 1=1
            """
            params: List[Any] = []
            if active_only:
                query += " AND acctstoptime IS NULL"
            if username:
                query += " AND username = %s"
                params.append(username)
            for key, col, op in (("since", "acctstarttime", ">="), ("until", "acctstarttime", "<=")):
                raw = {"since": since, "until": until}[key]
                if raw:
                    try:
                        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    except ValueError:
                        raise HTTPException(status_code=422, detail=f"Invalid {key} datetime. Use ISO format.")
                    query += f" AND {col} {op} %s"
                    params.append(ts)

            query += " ORDER BY radacctid DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Device inventory (MAC -> vendor + history), derived from radacct.
# Calling-Station-Id is the device MAC the NAS reported; the OUI (first 3
# bytes) identifies the manufacturer. MAC randomization means one physical
# device can appear as several MACs — the UI notes this.
# Curated top-vendor prefixes (full IEEE OUI list is 30k+ rows and needs
# downloads; this covers the common phone/laptop/IoT makers offline).
# ----------------------------------------------------------------------------
OUI_VENDORS: Dict[str, str] = {
    # Apple (large blocks)
    "88E09F": "Apple", "8C8590": "Apple", "8C7B9D": "Apple", "903C92": "Apple",
    "A45E60": "Apple", "A4B816": "Apple", "A8861D": "Apple", "AC3C7A": "Apple",
    "B06541": "Apple", "B87424": "Apple", "BC926B": "Apple", "C82A14": "Apple",
    "D02598": "Apple", "D89695": "Apple", "DC2B61": "Apple", "E0ACCB": "Apple",
    "E4C283": "Apple", "F41B6C": "Apple", "F4F15A": "Apple", "F82793": "Apple",
    "3C2EFF": "Apple", "0479E2": "Apple", "0C4DE9": "Apple", "283737": "Apple",
    "5C96F3": "Apple", "60F587": "Apple", "6CB4F5": "Apple", "70ECE4": "Apple",
    "7C6DF8": "Apple", "7CD657": "Apple",
    # Samsung
    "3C8BFE": "Samsung", "50CCF8": "Samsung", "80301D": "Samsung", "84CF0D": "Samsung",
    "8C7712": "Samsung", "A8F239": "Samsung", "C4FE59": "Samsung", "D072DC": "Samsung",
    "E4E0A6": "Samsung", "F02A4A": "Samsung", "001632": "Samsung",
    # Xiaomi / Redmi / Poco
    "0C98A6": "Xiaomi", "14F65A": "Xiaomi", "28E36A": "Xiaomi", "34CE00": "Xiaomi",
    "3CF96C": "Xiaomi", "64CC2E": "Xiaomi", "7C1CF3": "Xiaomi", "989EC5": "Xiaomi",
    # Huawei / Honor
    "00E02C": "Huawei",
    "00E0FC": "Huawei", "2C57A2": "Huawei", "48AD08": "Huawei", "5C7D5E": "Huawei",
    "E4A748": "Huawei", "F4C714": "Huawei",
    # Oppo / Vivo / Realme / OnePlus
    "1C87A4": "Oppo", "A4C3F0": "Oppo", "2C5B7F": "Oppo",
    "34E2FD": "Vivo", "68AB1E": "Vivo", "7CDD20": "Vivo",
    "18EFD6": "Realme", "4839C4": "Realme",
    "9CE230": "OnePlus", "F4B85C": "OnePlus", "3063F9": "OnePlus",
    # Google / Motorola / Nothing
    "F4F5D8": "Google", "94EB2D": "Google", "D8B36A": "Motorola",
    "346607": "Motorola", "A0B439": "Motorola",
    # Laptops / desktops
    "001A11": "Google", "3C5A37": "Google",
    "00A0C9": "Intel", "001E64": "Intel", "30D042": "Intel", "34F690": "Intel",
    "DC7196": "Intel", "7CCB0D": "Intel",
    "001B77": "Atheros", "040CCE": "Atheros", "B0C554": "Atheros",
    "00265E": "Realtek", "00E04C": "Realtek", "52C28A": "Realtek",
    "001320": "Ralink", "0C8411": "Ralink",
    "000F66": "Cisco-Linksys", "0013C3": "Cisco-Linksys", "58BC27": "Cisco-Linksys",
    "001E13": "D-Link", "1C5F2B": "D-Link", "7811DC": "D-Link",
    "04D9F5": "Ubiquiti", "802AA8": "Ubiquiti", "F0E7E2": "Ubiquiti",
    "9CADEF": "Ubiquiti", "B4FBF6": "Ubiquiti",
    "00156D": "Ubiquiti", "DCEB69": "MikroTik", "6C3B6B": "MikroTik",
    "CC2D8C": "MikroTik", "E48D8C": "MikroTik",
    # IoT / misc
    "24A160": "Espressif", "3C6105": "Espressif", "A0A3B3": "Espressif",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "18B430": "Amazon",
    "44650D": "Amazon", "74C246": "Amazon", "F0D2F1": "Amazon",
    "000272": "Amazon", "38F73D": "Amazon",
    "FC1910": "Amazon", "8871E5": "Amazon",
    "0017C4": "Quanta", "D0577B": "Quanta",
    "00236D": "Apple", "002500": "Apple",
}

# Remove any accidental non-hex placeholder keys (keeps map clean if edited).
OUI_VENDORS = {k: v for k, v in OUI_VENDORS.items() if v and re.fullmatch(r"[0-9A-F]{6}", k)}


def mac_vendor(mac: Optional[str]) -> str:
    """Manufacturer from the MAC OUI prefix, or 'Unknown' / randomized hint."""
    if not mac:
        return "—"
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    if len(clean) < 6:
        return "Unknown"
    oui = clean[:6]
    if oui in OUI_VENDORS:
        return OUI_VENDORS[oui]
    # Locally-administered bit set (2nd hex digit 2/6/A/E) => often randomized MAC.
    try:
        if int(oui[1], 16) & 0b0010:
            return "Unknown (likely randomized MAC)"
    except ValueError:
        pass
    return "Unknown"


def format_bytes(n: Any) -> str:
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


# ----------------------------------------------------------------------------
# Verified-device lockdown (per-user MAC allowlist, default OFF).
# Enforcement happens in FreeRADIUS (sites-available/default, unlang policy
# reading these tables); the API manages the lists and audit trail.
# MACs are stored normalized: 12 uppercase hex chars, no separators.
# ----------------------------------------------------------------------------
def normalize_mac(mac: Optional[str]) -> Optional[str]:
    """'aa-bb-cc-dd-ee-ff' / 'aabb.ccdd.eeff' / 'AABBCCDDEEFF' -> 'AABBCCDDEEFF'."""
    if not mac:
        return None
    clean = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(clean) != 12 or not re.fullmatch(r"[0-9a-fA-F]{12}", clean):
        return None
    return clean.upper()


def pretty_mac(normalized: str) -> str:
    n = (normalized or "").upper()
    if len(n) != 12:
        return normalized or ""
    return ":".join(n[i:i + 2] for i in range(0, 12, 2))


def ensure_device_tables() -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_device_policy (
                    username TEXT PRIMARY KEY,
                    require_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verified_devices (
                    username TEXT NOT NULL,
                    mac TEXT NOT NULL,
                    label TEXT,
                    added_by TEXT,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (username, mac)
                )
            """)
            # Reject-reason column for the auth history (safe on existing DBs).
            cur.execute("ALTER TABLE radpostauth ADD COLUMN IF NOT EXISTS reason TEXT")
            conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Could not ensure device tables: %s", e)


def get_user_devices(username: str) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT require_verified FROM user_device_policy WHERE username = %s", (username,))
            row = cur.fetchone()
            require_verified = bool(row["require_verified"]) if row else False
            cur.execute("SELECT mac, label, added_by, added_at FROM verified_devices WHERE username = %s ORDER BY added_at",
                        (username,))
            devices = []
            for r in cur.fetchall():
                at = r.get("added_at")
                devices.append({
                    "mac": r["mac"],
                    "pretty": pretty_mac(r["mac"]),
                    "vendor": mac_vendor(r["mac"]),
                    "label": r.get("label"),
                    "added_by": r.get("added_by"),
                    "added_at": at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None),
                })
            return {"require_verified": require_verified, "devices": devices}
    finally:
        conn.close()


@app.get("/radius/api/devices", tags=["Logs & Accounting"])
@app.get("/api/devices", tags=["Logs & Accounting"])
def list_devices(username: Optional[str] = None, limit: int = 200,
                 _: str = Depends(authenticate_admin)):
    """Known devices aggregated by Calling-Station-Id (device MAC).

    Per MAC: vendor (OUI), owning user (most recent), first/last seen, session
    count, bytes up/down, last IP / NAS / AP, and whether currently online.
    """
    try:
        limit = min(max(int(limit or 200), 1), 1000)
    except (TypeError, ValueError):
        limit = 200
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            agg_q = """
                SELECT callingstationid AS mac,
                       COUNT(*) AS sessions,
                       MIN(acctstarttime) AS first_seen,
                       MAX(acctstarttime) AS last_seen,
                       COALESCE(SUM(acctinputoctets), 0)::bigint AS up_bytes,
                       COALESCE(SUM(acctoutputoctets), 0)::bigint AS down_bytes,
                       COUNT(*) FILTER (WHERE acctstoptime IS NULL) AS online_count
                FROM radacct
                WHERE callingstationid IS NOT NULL AND callingstationid <> ''
            """
            params: List[Any] = []
            if username:
                agg_q += " AND username = %s"
                params.append(username)
            agg_q += " GROUP BY callingstationid ORDER BY last_seen DESC NULLS LAST LIMIT %s"
            params.append(limit)
            cur.execute(agg_q, tuple(params))
            rows = cur.fetchall()

            # Latest session detail per MAC (user, IP, NAS, AP).
            cur.execute("""
                SELECT DISTINCT ON (callingstationid) callingstationid AS mac,
                       username, framedipaddress::text AS ip,
                       nasipaddress::text AS nas, calledstationid AS ap,
                       acctstarttime AS seen
                FROM radacct
                WHERE callingstationid IS NOT NULL AND callingstationid <> ''
                ORDER BY callingstationid, acctstarttime DESC NULLS LAST
            """)
            latest = {r["mac"]: r for r in cur.fetchall()}

            out = []
            for r in rows:
                mac = r["mac"]
                lat = latest.get(mac, {})
                fs, ls = r.get("first_seen"), r.get("last_seen")
                out.append({
                    "mac": mac,
                    "vendor": mac_vendor(mac),
                    "username": lat.get("username"),
                    "sessions": int(r.get("sessions") or 0),
                    "online": int(r.get("online_count") or 0) > 0,
                    "first_seen": fs.isoformat() if hasattr(fs, "isoformat") else (str(fs) if fs else None),
                    "last_seen": ls.isoformat() if hasattr(ls, "isoformat") else (str(ls) if ls else None),
                    "up_bytes": int(r.get("up_bytes") or 0),
                    "down_bytes": int(r.get("down_bytes") or 0),
                    "up": format_bytes(r.get("up_bytes")),
                    "down": format_bytes(r.get("down_bytes")),
                    "total": format_bytes(int(r.get("up_bytes") or 0) + int(r.get("down_bytes") or 0)),
                    "last_ip": lat.get("ip"),
                    "last_nas": lat.get("nas"),
                    "last_ap": lat.get("ap"),
                })
            return out
    finally:
        conn.close()


@app.get("/radius/api/auth-logs", tags=["Logs & Accounting"])
@app.get("/api/auth-logs", tags=["Logs & Accounting"])
def get_auth_logs(limit: int = 50, username: Optional[str] = None, result: Optional[str] = None, _: str = Depends(authenticate_admin)):
    """RADIUS authentication attempts. NOTE: the `pass` column (attempted passwords)
    is deliberately never selected — it must not leak through the API.
    `reason` carries the rule that rejected the attempt (e.g. unverified device)."""
    try:
        select_reason = ", reason"
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'radpostauth' AND column_name = 'reason'")
            if not cur.fetchone():
                select_reason = ""
        conn.close()
    except Exception:
        select_reason = ""
        try:
            conn.close()
        except Exception:
            pass
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = f"SELECT id, username, reply, authdate{select_reason} FROM radpostauth WHERE 1=1"
            params: List[Any] = []
            if username:
                query += " AND username ILIKE %s"
                params.append(f"%{username}%")
            if result == "accept":
                query += " AND reply = 'Access-Accept'"
            elif result == "reject":
                query += " AND reply = 'Access-Reject'"
            query += " ORDER BY id DESC LIMIT %s"
            params.append(min(max(int(limit or 50), 1), 500))
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            out = []
            for r in rows:
                reply = (r.get("reply") or "").strip()
                if reply == "Access-Accept":
                    event = "accept"
                elif reply == "Access-Reject":
                    event = "reject"
                else:
                    event = "other"
                ts = r.get("authdate")
                reason = (r.get("reason") or "").strip() if select_reason else ""
                out.append({
                    "id": r.get("id"),
                    "username": r.get("username"),
                    "event": event,
                    "reply": reply or "—",
                    "reason": reason or None,
                    "rule": reason or ("Authenticated OK" if event == "accept" else "Rejected (no reason recorded — see server logs)"),
                    "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else None),
                })
            return out
    finally:
        conn.close()

# Disconnect Session via RADIUS CoA / Disconnect-Request (RFC 5176)
@app.post("/radius/api/sessions/disconnect", tags=["Sessions"])
@app.post("/api/sessions/disconnect", tags=["Sessions"])
def disconnect_session(payload: DisconnectSessionRequest, _: str = Depends(authenticate_admin)):
    secret = payload.nas_secret or RADIUS_SECRET
    try:
        success, output = send_coa_disconnect(
            payload.username, payload.nas_ip, secret,
            acct_session_id=payload.acct_session_id, framed_ip=payload.framed_ip,
        )
        logger.info("CoA disconnect username=%s nas=%s success=%s by=%s", payload.username, payload.nas_ip, success, _)
        return {
            "success": success,
            "status": "Session Disconnected (ACK)" if success else "Sent / Response: " + output.strip(),
            "output": output.strip()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send disconnect packet: {str(e)}")

# ==============================================================================
# PKI & EAP-TLS CERTIFICATE MANAGEMENT
# ==============================================================================
@app.get("/radius/api/certs/ca", tags=["Certificates"])
@app.get("/api/certs/ca", tags=["Certificates"])
def download_ca_cert(_: str = Depends(authenticate_admin)):
    ca_path = os.path.join(CERTS_DIR, "ca.pem")
    if not os.path.exists(ca_path):
        ca_path = os.path.join(CERTS_DIR, "ca.crt")
    if not os.path.exists(ca_path):
        raise HTTPException(status_code=404, detail="CA certificate not found. Run cert bootstrap first.")
    return FileResponse(ca_path, media_type="application/x-x509-ca-cert", filename="RajLabs_FreeRADIUS_Root_CA.pem")

@app.get("/radius/api/certs", tags=["Certificates"])
@app.get("/api/certs", tags=["Certificates"])
def list_certificates(_: str = Depends(authenticate_admin)):
    certs = []
    for f in sorted(os.listdir(CLIENT_CERTS_DIR)):
        if f.endswith(".p12"):
            uname = f[:-4]
            crt_path = os.path.join(CLIENT_CERTS_DIR, f"{uname}.crt")
            mtime = os.path.getmtime(os.path.join(CLIENT_CERTS_DIR, f))
            certs.append({
                "username": uname,
                "p12_file": f,
                "has_crt": os.path.exists(crt_path),
                "created_at": mtime
            })
    return certs

def sign_certificate_with_ca(username: str, user_csr_path: str, days: int = 365, san_list: Optional[List[str]] = None) -> tuple[str, str]:
    """
    Signs a client CSR using the central Rajlabs-CA Cert-Signer API (if configured),
    or falls back to the local FreeRADIUS CA.
    Returns: (issued_cert_pem, ca_chain_pem)
    """
    if CERT_SIGNER_API_URL:
        try:
            with open(user_csr_path, "r") as f:
                csr_content = f.read()
            
            headers = {"Content-Type": "application/json"}
            if CERT_SIGNER_API_KEY:
                headers["x-api-key"] = CERT_SIGNER_API_KEY
            
            sans = san_list or [f"{username}@rajlabs.in", f"{username}.local"]
            payload_data = {
                "csr": csr_content,
                "san": sans,
                "days": days
            }
            
            req_url = f"{CERT_SIGNER_API_URL}/api/v1/sign"
            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload_data).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    if res_json.get("success"):
                        logger.info("Certificate signed successfully via Rajlabs-CA Cert Signer for %s", username)
                        return res_json["certificate"], res_json.get("fullChain") or res_json["certificate"]
        except Exception as e:
            logger.warning("Cert-Signer microservice request to %s failed (%s), falling back to local CA.", CERT_SIGNER_API_URL, e)

    # Local FreeRADIUS CA Fallback
    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_pem = os.path.join(CERTS_DIR, "ca.pem")
    if not os.path.exists(ca_key) or not os.path.exists(ca_pem):
        raise HTTPException(status_code=500, detail="No certificate authority available (Cert-Signer unreachable and local CA missing).")

    temp_crt_path = user_csr_path + ".crt"
    # CA_KEY_PASSWORD unlocks the local CA private key created by `certs/bootstrap`
    # (upstream default for that key). It is NOT a client certificate password:
    # every client .p12 gets its own random password via generate_p12_password().
    ca_key_password = os.getenv("CA_KEY_PASSWORD", "") or None
    sign_cmd = [
        "openssl", "x509", "-req", "-in", user_csr_path,
        "-CA", ca_pem, "-CAkey", ca_key, "-CAcreateserial",
        "-out", temp_crt_path, "-days", str(days),
    ]
    if ca_key_password:
        sign_cmd += ["-passin", f"pass:{ca_key_password}"]
    subprocess.run(sign_cmd, check=True, capture_output=True)

    with open(temp_crt_path, "r") as f:
        crt_pem = f.read()
    with open(ca_pem, "r") as f:
        ca_pem_content = f.read()

    if os.path.exists(temp_crt_path):
        os.remove(temp_crt_path)

    return crt_pem, ca_pem_content

@app.post("/radius/api/certs/issue", tags=["Certificates"])
@app.post("/api/certs/issue", tags=["Certificates"])
def issue_client_certificate(payload: IssueCertRequest, request: Request, _: str = Depends(authenticate_admin)):
    check_rate_limit(request, "cert-issue", RL_CERT_ISSUE_PER_MIN)
    uname = validate_username(payload.username)
    # Per-issuance random password (issue #3): never a well-known default.
    p12_pass = payload.cert_password or generate_p12_password()
    days = min(max(int(payload.valid_days or 365), 1), 825)
    email = payload.email or f"{uname}@rajlabs.in"

    user_key = safe_client_path(uname, ".key")
    user_csr = safe_client_path(uname, ".csr")
    user_crt = safe_client_path(uname, ".crt")
    user_p12 = safe_client_path(uname, ".p12")

    try:
        # 1. Generate client private key
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)

        # 2. Generate CSR
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)

        # 3. Sign client cert (via Central Cert Signer or Local CA fallback)
        cert_pem, ca_chain_pem = sign_certificate_with_ca(uname, user_csr, days=days, san_list=[email, f"{uname}.local"])
        with open(user_crt, "w") as f:
            f.write(cert_pem)
        
        ca_chain_file = os.path.join(CLIENT_CERTS_DIR, f"{uname}-chain.crt")
        with open(ca_chain_file, "w") as f:
            f.write(ca_chain_pem)

        # 4. Package as PKCS#12 bundle (.p12)
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", user_crt, "-inkey", user_key, "-certfile", ca_chain_file,
            "-out", user_p12, "-name", f"RajLabs RADIUS - {uname}",
            "-password", f"pass:{p12_pass}"
        ], check=True, capture_output=True)

        # Private key material: owner/group read only (never world-readable).
        for _p in (user_key, user_p12, user_crt):
            try:
                os.chmod(_p, 0o600)
            except OSError:
                pass

        logger.info("Client certificate issued username=%s by=%s via=%s", uname, _, 'Rajlabs-CA API' if CERT_SIGNER_API_URL else 'Local CA')
        return {
            "status": "success",
            "message": f"EAP-TLS Client certificate issued for user '{uname}' (Signed via {'Rajlabs-CA API' if CERT_SIGNER_API_URL else 'Local CA'})",
            "username": uname,
            "p12_password": p12_pass,
            "download_url": f"/radius/api/certs/{uname}/download",
            "mobileconfig_url": f"/radius/api/certs/{uname}/mobileconfig"
        }
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode() if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"OpenSSL generation failed: {err}")

@app.get("/radius/api/certs/orphans", tags=["Certificates"])
@app.get("/api/certs/orphans", tags=["Certificates"])
def list_orphaned_certificates(_: str = Depends(authenticate_admin)):
    """One-off cleanup helper (issue #10): certs on disk with no matching radcheck row."""
    try:
        disk_users = {f[:-4] for f in os.listdir(CLIENT_CERTS_DIR) if f.endswith(".p12")}
    except OSError:
        return []
    if not disk_users:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT username FROM radcheck")
            db_users = {r["username"] for r in cur.fetchall()}
    finally:
        conn.close()
    return sorted(disk_users - db_users)


@app.delete("/radius/api/certs/orphans/{username}", tags=["Certificates"])
@app.delete("/api/certs/orphans/{username}", tags=["Certificates"])
def delete_orphaned_certificate(username: str, admin_user: str = Depends(authenticate_admin)):
    """Remove cert material for an already-deleted user."""
    username = validate_username(username)
    removed = 0
    for suffix in (".key", ".csr", ".crt", ".p12", "-chain.crt"):
        p = safe_client_path(username, suffix)
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError:
            pass
    if not removed:
        raise HTTPException(status_code=404, detail=f"No certificate material found for '{username}'.")
    log_audit(admin_user, "orphan_cert_cleanup", username, f"cert_files_removed={removed}")
    return {"status": "success", "message": f"Removed {removed} orphaned file(s) for '{username}'."}


@app.get("/radius/api/certs/{username}/download", tags=["Certificates"])
@app.get("/api/certs/{username}/download", tags=["Certificates"])
def download_client_p12(username: str, _: str = Depends(authenticate_admin)):
    p12_path = safe_client_path(validate_username(username), ".p12")
    if not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail=f"No certificate found for user '{username}'. Issue one first.")
    return FileResponse(p12_path, media_type="application/x-pkcs12", filename=f"{username}_rajlabs_radius.p12")

@app.get("/radius/api/certs/{username}/mobileconfig", tags=["Certificates"])
@app.get("/api/certs/{username}/mobileconfig", tags=["Certificates"])
def download_apple_mobileconfig(username: str, ssid: str = "RajLabs-Enterprise", _: str = Depends(authenticate_admin)):
    """Generates an Apple .mobileconfig WiFi Profile (fresh random p12 password per download)."""
    username = validate_username(username)
    p12_bytes, fresh_pass = repackage_p12_for_mobileconfig(username)
    mobileconfig = build_mobileconfig(username, ssid, p12_bytes, fresh_pass)
    return Response(
        content=mobileconfig,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": f'attachment; filename="RajLabs_{username}_WiFi.mobileconfig"'}
    )

def parse_radtest_output(output: str) -> tuple[bool, str]:
    """Verdict from radtest/radclient output.

    Must match the actual reply line (``Received Access-Accept``): a bare
    ``"Access-Accept" in output`` check is wrong because rejects print
    ``Expected Access-Accept got Access-Reject`` (which made every reject
    show green in the dashboard).
    """
    out = output or ""
    if "Received Access-Reject" in out:
        return False, "Rejected"
    if "Received Access-Accept" in out:
        return True, "Accepted"
    if "No reply" in out or "timed out" in out.lower():
        return False, "Timeout / no reply"
    return False, "Rejected / Failed"


# Live RADIUS Testing (radtest, or radclient when a device MAC is simulated)
@app.post("/radius/api/test-auth", tags=["Testing"])
@app.post("/api/test-auth", tags=["Testing"])
def test_radius_authentication(payload: AuthTestRequest, request: Request, _: str = Depends(authenticate_admin)):
    check_rate_limit(request, "test-auth", RL_TEST_AUTH_PER_MIN)
    validate_username(payload.username)
    nas_ip = validate_nas_ip(payload.nas_ip or "127.0.0.1")
    secret = payload.secret or RADIUS_SECRET
    if payload.calling_station_id:
        mac = normalize_mac(payload.calling_station_id)
        if not mac:
            raise HTTPException(status_code=422, detail="Invalid Calling-Station-Id. Use a MAC like AA:BB:CC:DD:EE:FF.")
        cmd = ["radclient", f"{nas_ip}:1812", "auth", secret]
        attrs = (f'User-Name = "{payload.username}"\n'
                 f'User-Password = "{payload.password}"\n'
                 f'Calling-Station-Id = "{pretty_mac(mac)}"\n'
                 f'NAS-IP-Address = "127.0.0.1"')
        shown = f"radclient {nas_ip}:1812 auth (+ Calling-Station-Id {pretty_mac(mac)})"
    else:
        cmd = ["radtest", payload.username, payload.password, nas_ip, "0", secret]
        attrs = None
        shown = f"radtest {payload.username} [REDACTED] {nas_ip} 0 [SECRET]"
    try:
        result = subprocess.run(cmd, input=attrs, capture_output=True, text=True, timeout=5)
        output = result.stdout + result.stderr
        success, verdict = parse_radtest_output(output)
        logger.info("Test-auth username=%s nas=%s mac=%s success=%s by=%s",
                    payload.username, nas_ip, payload.calling_station_id or "-", success, _)
        return {
            "success": success,
            "status": verdict,
            "output": output.strip(),
            "command": shown
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "status": "Timeout",
            "output": "RADIUS authentication timed out. Make sure the FreeRADIUS daemon is running and listening on UDP 1812."
        }
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="radtest/radclient binary not found on server.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run radtest: {str(e)}")

class PortalEnrollCertRequest(BaseModel):
    username: str
    password: str
    device_name: Optional[str] = "Personal Device"
    cert_password: Optional[str] = None


class PortalDownloadRequest(BaseModel):
    username: str
    password: str

# Public Self-Service Device Certificate Enrollment & Auto-Login
@app.post("/radius/api/portal/enroll-certificate", tags=["Captive Portal"])
@app.post("/api/portal/enroll-certificate", tags=["Captive Portal"])
def portal_enroll_certificate(payload: PortalEnrollCertRequest, request: Request):
    # Throttle BEFORE the 2048-bit RSA keygen: floods stay CPU-cheap (issue #7).
    check_rate_limit(request, "enroll", RL_ENROLL_PER_MIN)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rc.username, rc.value 
                FROM radcheck rc 
                WHERE rc.username = %s AND rc.attribute LIKE '%%Password'
            """, (payload.username,))
            row = cur.fetchone()
            if not row or not secrets.compare_digest(row["value"], payload.password):
                raise HTTPException(status_code=401, detail="Authentication failed. Invalid username or password.")
    finally:
        conn.close()

    uname = validate_username(payload.username)
    # Per-enrollment random password (issue #3): never a well-known default.
    p12_pass = payload.cert_password or generate_p12_password()
    days = 365
    email = f"{uname}@rajlabs.in"

    user_key = safe_client_path(uname, ".key")
    user_csr = safe_client_path(uname, ".csr")
    user_crt = safe_client_path(uname, ".crt")
    user_p12 = safe_client_path(uname, ".p12")

    try:
        # 1. Generate client private key & CSR
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)

        # 2. Sign certificate with central Cert Signer or Local CA
        cert_pem, ca_chain_pem = sign_certificate_with_ca(uname, user_csr, days=days, san_list=[email, f"{uname}.local"])
        with open(user_crt, "w") as f:
            f.write(cert_pem)

        ca_chain_file = safe_client_path(uname, "-chain.crt")
        with open(ca_chain_file, "w") as f:
            f.write(ca_chain_pem)

        # 3. Package as PKCS#12 bundle (.p12)
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", user_crt, "-inkey", user_key, "-certfile", ca_chain_file,
            "-out", user_p12, "-name", f"RajLabs RADIUS - {uname}",
            "-password", f"pass:{p12_pass}"
        ], check=True, capture_output=True)
        for _p in (user_key, user_p12, user_crt):
            try:
                os.chmod(_p, 0o600)
            except OSError:
                pass

        return {
            "status": "success",
            "success": True,
            "message": f"Certificate enrolled successfully for {uname} (Signed by {'Rajlabs-CA PKI' if CERT_SIGNER_API_URL else 'Local CA'})",
            "username": uname,
            "mobileconfig_url": f"/radius/api/portal/download-mobileconfig?username={uname}",
            "p12_download_url": f"/radius/api/portal/download-cert?username={uname}",
            "p12_password": p12_pass
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate certificate: {str(e)}")

@app.get("/radius/api/portal/download-mobileconfig", tags=["Captive Portal"])
@app.get("/api/portal/download-mobileconfig", tags=["Captive Portal"])
def portal_download_mobileconfig(username: str, password: str = "", ssid: str = "RajLabs-Enterprise"):
    """Owner-only Apple profile: requires the account password (issue #3)."""
    verify_portal_user(username, password)
    p12_bytes, fresh_pass = repackage_p12_for_mobileconfig(validate_username(username))
    mobileconfig = build_mobileconfig(username, ssid, p12_bytes, fresh_pass)
    return Response(
        content=mobileconfig,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": f'attachment; filename="RajLabs_{username}_WiFi.mobileconfig"'}
    )


@app.post("/radius/api/portal/download-mobileconfig", tags=["Captive Portal"])
@app.post("/api/portal/download-mobileconfig", tags=["Captive Portal"])
def portal_download_mobileconfig_post(payload: PortalDownloadRequest, ssid: str = "RajLabs-Enterprise"):
    """POST variant (password in body, not URL) for the portal UI."""
    return portal_download_mobileconfig(payload.username, payload.password, ssid)


@app.post("/radius/api/portal/download-cert", tags=["Captive Portal"])
@app.post("/api/portal/download-cert", tags=["Captive Portal"])
def portal_download_cert_post(payload: PortalDownloadRequest):
    """Owner-only .p12 download: requires the account password (issue #3)."""
    verify_portal_user(payload.username, payload.password)
    p12_path = safe_client_path(validate_username(payload.username), ".p12")
    if not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail="Certificate not found. Enroll first.")
    return FileResponse(p12_path, media_type="application/x-pkcs12", filename=f"RajLabs_{payload.username}_Certificate.p12")

@app.get("/radius/api/portal/download-cert", tags=["Captive Portal"])
@app.get("/api/portal/download-cert", tags=["Captive Portal"])
def portal_download_cert(username: str, password: str = ""):
    """Owner-only .p12 download (GET variant): requires the account password (issue #3)."""
    verify_portal_user(username, password)
    p12_path = safe_client_path(validate_username(username), ".p12")
    if not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail="Certificate not found. Enroll first.")
    return FileResponse(p12_path, media_type="application/x-pkcs12", filename=f"RajLabs_{username}_Certificate.p12")

# Public Captive Portal Splash Page
@app.get("/radius/portal", response_class=HTMLResponse, tags=["Captive Portal"])
@app.get("/portal", response_class=HTMLResponse, tags=["Captive Portal"])
def get_captive_portal():
    portal_path = os.path.join(STATIC_DIR, "portal.html")
    if os.path.exists(portal_path):
        with open(portal_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RajLabs Wi-Fi Login Portal</h1>")

# Mount static files & Protected Web Dashboard
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/radius/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_root")

@app.get("/radius", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/radius/", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
def get_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RajLabs FreeRADIUS Dashboard</h1>")


