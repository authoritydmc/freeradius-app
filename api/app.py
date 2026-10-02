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
import asyncio
import string
import datetime
import urllib.request
import urllib.error
import urllib.parse
from xml.sax.saxutils import escape as _xml_escape
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Union
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

# Database configuration from environment (exclusively PostgreSQL)
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "radius")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

_db_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRESQL_URL")
if _db_url:
    try:
        from urllib.parse import urlparse
        _parsed = urlparse(_db_url)
        if _parsed.hostname:
            POSTGRES_HOST = _parsed.hostname
        if _parsed.port:
            POSTGRES_PORT = _parsed.port
        if _parsed.path and len(_parsed.path) > 1:
            POSTGRES_DB = _parsed.path.lstrip("/")
        if _parsed.username:
            POSTGRES_USER = _parsed.username
        if _parsed.password:
            POSTGRES_PASSWORD = _parsed.password
    except Exception:
        pass

RADIUS_SECRET = os.getenv("RADIUS_SECRET", "testing123")

# Central Rajlabs-CA Cert Signer API Integration (all env-based, no hardcoded URLs)
CERT_SIGNER_API_URL = os.getenv("CERT_SIGNER_API_URL", "").rstrip("/")
CERT_SIGNER_API_KEY = os.getenv("CERT_SIGNER_API_KEY", "")
# Public RADIUS host shown in UI/docs (the UDP endpoint routers point at).
# Defaults to the API host when unset; override when UDP and HTTPS differ.
RADIUS_PUBLIC_HOST = os.getenv("RADIUS_PUBLIC_HOST", "")

# Support and Password Reset Contact
ADMIN_CONTACT_PHONE = os.getenv("ADMIN_CONTACT_PHONE", "+919999999999")
ADMIN_CONTACT_NAME = os.getenv("ADMIN_CONTACT_NAME", "Network Administrator")

# Short-lived cache for the signer health probe (avoid blocking the UI)
_SIGNER_STATUS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}

ADMIN_FALLBACK_USER = os.getenv("RADIUS_ADMIN_USER") or os.getenv("ADMIN_FALLBACK_USER") or "admin"
ADMIN_FALLBACK_PASS = os.getenv("RADIUS_ADMIN_PASSWORD") or os.getenv("ADMIN_FALLBACK_PASSWORD") or "admin123"
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


def get_cert_signer_config() -> tuple[str, str]:
    """Retrieve effective Cert-Signer API URL and API Key.
    
    Checks database system_settings first (runtime UI configured),
    falling back to environment variables CERT_SIGNER_API_URL and CERT_SIGNER_API_KEY.
    Automatically resolves frontend URL ca.rajlabs.in to backend signer API.
    """
    url = CERT_SIGNER_API_URL
    key = CERT_SIGNER_API_KEY
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM system_settings WHERE key IN ('cert_signer_api_url', 'cert_signer_api_key')")
            rows = cur.fetchall()
            for r in rows:
                if r["key"] == "cert_signer_api_url" and r["value"] and r["value"].strip():
                    url = r["value"].strip().rstrip("/")
                elif r["key"] == "cert_signer_api_key" and r["value"] and r["value"].strip():
                    key = r["value"].strip()
        conn.close()
    except Exception:
        pass

    if url:
        url = url.rstrip("/")
        if "ca.rajlabs.in" in url and "backend.rajlabs.in" not in url:
            url = "https://backend.rajlabs.in/cert-signer"

    return url, key



def safe_client_path(username: str, suffix: str) -> str:
    """Join CLIENT_CERTS_DIR safely; rejects traversal even if regex is bypassed."""
    validate_username(username)
    try:
        os.makedirs(CLIENT_CERTS_DIR, exist_ok=True)
    except Exception:
        pass
    p = os.path.abspath(os.path.join(CLIENT_CERTS_DIR, f"{username}{suffix}"))
    base = os.path.abspath(CLIENT_CERTS_DIR)
    if p != base and not p.startswith(base + os.sep):
        raise HTTPException(status_code=400, detail="Invalid username.")
    return p


def export_pkcs12_bundle(crt_path: str, key_path: str, out_path: str,
                         friendly_name: str, password: str,
                         chain_path: Optional[str] = None) -> None:
    """Export a .p12 with Android-compatible legacy PBE when possible.

    Why: OpenSSL 3 defaults to AES-256-CBC + SHA256 for PKCS#12. Most
    modern Android versions read that fine, but several OEM file-manager
    / KeyChain import paths only accept the legacy PBE-SHA1-3DES
    encryption. Trying legacy first (falling back to defaults) makes the
    same bundle install on both old and new phones without user confusion.
    """
    base = ["openssl", "pkcs12", "-export",
            "-in", crt_path, "-inkey", key_path,
            "-out", out_path, "-name", friendly_name,
            "-password", f"pass:{password}"]
    if chain_path and os.path.exists(chain_path):
        # insert -certfile <chain> right after -inkey <key>
        idx = base.index("-inkey") + 2
        base[idx:idx] = ["-certfile", chain_path]
    attempts = [
        base + ["-certpbe", "PBE-SHA1-3DES", "-keypbe", "PBE-SHA1-3DES", "-nomaciter"],
        base,
    ]
    last_err = ""
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return
        except subprocess.CalledProcessError as e:
            last_err = ((e.stderr or b"").decode("utf-8", "replace") if e.stderr else str(e))
            continue
    raise subprocess.CalledProcessError(1, attempts[0], stderr=last_err.encode())


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
        export_pkcs12_bundle(crt_path, key_path, tmp_path,
                             f"RajLabs RADIUS - {username}", fresh_pass,
                             chain_path if os.path.exists(chain_path) else None)
        with open(tmp_path, "rb") as f:
            return f.read(), fresh_pass
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", "replace") if getattr(e, "stderr", None) else str(e)
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
# Simple by design (Oct 2026): min 8 characters, anything goes — no forced
# upper/lower/digit/symbol mix. A 10-digit mobile number alone already passes;
# mobile-number + word + symbol passes too. Generated passwords stay strong
# (one char per class); the strength meter only advises, never blocks.
# ----------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 8
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
    """Raises HTTPException 422 on policy violation.

    Simple rule: 8-128 chars and not identical to the username. No forced
    character-class mix — "9876543210", "9876543210ram@" and "Str0ng!Pass#42"
    are all fine. Longer generated passwords remain strong by construction.
    """
    if not password or not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
        raise HTTPException(status_code=422, detail=f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters long.")
    if username and password.strip().lower() == username.strip().lower():
        raise HTTPException(status_code=422, detail="Password must not be the same as the username.")

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

def generate_session_secret(length: int = 24) -> str:
    """Random secret for auto-provisioned users / radcheck passwords.

    Wrapper around generate_secure_password so legacy call-sites
    (manual-activate, email-scan, webhook, cert auto-provision) work.
    """
    return generate_secure_password(length, use_symbols=False, exclude_ambiguous=True)

def ensure_audit_table():
    """Deprecated shim — schema is owned by api/migrations via api/migrate.py."""
    try:
        from api.migrate import ensure_migrated
        ensure_migrated()
    except Exception as e:
        logger.warning("Could not ensure admin_audit_log table: %s", e)

def log_audit(admin_user: str, action: str, target_user: Optional[str] = None, detail: Optional[str] = None):
    try:
        ensure_audit_table()
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

CERTS_DIR = os.getenv("CERTS_DIR", "/etc/freeradius/3.0/certs")
CLIENT_CERTS_DIR = os.getenv("CLIENT_CERTS_DIR", os.path.join(CERTS_DIR, "clients"))
try:
    os.makedirs(CLIENT_CERTS_DIR, exist_ok=True)
except Exception:
    if not os.path.exists(CLIENT_CERTS_DIR):
        local_certs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "certs"))
        CERTS_DIR = local_certs_dir
        CLIENT_CERTS_DIR = os.path.join(CERTS_DIR, "clients")
        try:
            os.makedirs(CLIENT_CERTS_DIR, exist_ok=True)
        except Exception:
            pass

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

def generate_session_token(username: str, role: str = "admin") -> str:
    timestamp = int(time.time())
    if role == "admin":
        data = f"{username}:{timestamp}"
        sig = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        raw = f"{data}:{sig}"
    else:
        data = f"{username}:{role}:{timestamp}"
        sig = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        raw = f"{data}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_revoked_tokens_table() -> None:
    """Deprecated shim — schema is owned by api/migrations via api/migrate.py."""
    try:
        from api.migrate import ensure_migrated
        ensure_migrated()
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
        raw_bytes = base64.urlsafe_b64decode(token.encode())
        # Strict validation: re-encoded must equal input token to prevent trailing garbage bypass in Python < 3.14
        if base64.urlsafe_b64encode(raw_bytes).decode() != token:
            return None
        raw = raw_bytes.decode("utf-8")
        parts = raw.split(":")
        if len(parts) == 3:
            username, timestamp_str, sig = parts
            expected_sig = hmac.new(SESSION_SECRET.encode(), f"{username}:{timestamp_str}".encode(), hashlib.sha256).hexdigest()
        elif len(parts) == 4:
            username, role, timestamp_str, sig = parts
            expected_sig = hmac.new(SESSION_SECRET.encode(), f"{username}:{role}:{timestamp_str}".encode(), hashlib.sha256).hexdigest()
        else:
            return None

        timestamp = int(timestamp_str)
        # 7 days session expiration
        if time.time() - timestamp > 7 * 86400:
            return None
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

def is_user_admin(username: str) -> bool:
    """Returns True if username has Administrator role or matches env fallback admin."""
    u = (username or "").strip()
    if not u:
        return False
    fallback = os.getenv("RADIUS_ADMIN_USER") or os.getenv("ADMIN_FALLBACK_USER") or ADMIN_FALLBACK_USER
    if fallback and secrets.compare_digest(u, fallback):
        return True
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rug.groupname, rgr.attribute, rgr.value
                FROM radusergroup rug
                LEFT JOIN radgroupreply rgr ON rug.groupname = rgr.groupname 
                    AND (rgr.attribute = 'Service-Type' OR rgr.attribute = 'RajLabs-Is-Admin')
                WHERE rug.username = %s
            """, (u,))
            rows = cur.fetchall()
            for r in rows:
                grp = (r.get("groupname") or "").lower()
                attr = r.get("attribute") or ""
                val = r.get("value") or ""
                if grp in ("admins", "admin"):
                    conn.close()
                    return True
                if attr == "Service-Type" and val == "Administrative-User":
                    conn.close()
                    return True
                if attr == "RajLabs-Is-Admin" and val == "1":
                    conn.close()
                    return True
            
            try:
                cur.execute("""
                    SELECT g.is_admin 
                    FROM users u 
                    JOIN groups g ON u.group_id = g.id 
                    WHERE u.username = %s
                """, (u,))
                g_row = cur.fetchone()
                if g_row and g_row.get("is_admin"):
                    conn.close()
                    return True
            except Exception:
                pass
            conn.close()
    except Exception as e:
        logger.warning("is_user_admin check exception: %s", e)
    return False


def check_user_role_and_authenticate(user: str, passwd: str) -> tuple[bool, str, Dict[str, Any]]:
    """
    Unified credential verification against PostgreSQL FreeRADIUS radcheck.
    Returns (authenticated: bool, role: 'admin'|'user', info: dict).
    """
    u = (user or "").strip()
    if not u or not passwd:
        return False, "guest", {}

    # Check fallback environment admin first
    if secrets.compare_digest(u, ADMIN_FALLBACK_USER) and secrets.compare_digest(passwd, ADMIN_FALLBACK_PASS):
        return True, "admin", {"group": "admins", "is_admin": True}

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rc.username, rc.value, rug.groupname
                FROM radcheck rc
                LEFT JOIN radusergroup rug ON rc.username = rug.username
                WHERE rc.username = %s AND rc.attribute LIKE '%%Password'
            """, (u,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False, "guest", {}

            stored_pass = str(row["value"])
            group = str(row["groupname"] or "default").strip()

            cur.execute("""
                SELECT attribute, value FROM radgroupreply 
                WHERE groupname = %s AND (attribute = 'Service-Type' OR attribute = 'RajLabs-Is-Admin')
            """, (group,))
            grp_attrs = cur.fetchall()
            conn.close()

            is_admin = (
                group.lower() in ("admins", "admin") or 
                any(r.get("attribute") == "Service-Type" and r.get("value") == "Administrative-User" for r in grp_attrs) or
                any(r.get("attribute") == "RajLabs-Is-Admin" and r.get("value") == "1" for r in grp_attrs) or
                is_user_admin(u)
            )

            if secrets.compare_digest(stored_pass, passwd):
                role = "admin" if is_admin else "user"
                return True, role, {"group": group, "is_admin": is_admin}
    except Exception as e:
        logger.warning("Auth DB check error: %s", e)

    return False, "guest", {}


def verify_admin_user(user: str, passwd: str) -> bool:
    ok, role, _ = check_user_role_and_authenticate(user, passwd)
    return ok and role == "admin"

def verify_certificate_and_get_user(cert_pem_or_p12_bytes: bytes, p12_password: Optional[str] = None) -> tuple[str, str]:
    """Verifies an X.509 certificate or PKCS#12 bundle against Root CA and returns (username, role)."""
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

            cmd = ["openssl", "pkcs12", "-in", p12_path, "-nokeys", "-out", cert_path,
                   "-passin", f"pass:{p12_password or ''}"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if os.path.exists(p12_path):
                os.remove(p12_path)
            if res.returncode != 0:
                raise ValueError("Invalid PKCS#12 certificate format or incorrect password")

        # Verify against Root CA
        ca_path = os.path.join(CERTS_DIR, "ca.pem")
        if not os.path.exists(ca_path):
            ca_path = os.path.join(CERTS_DIR, "ca.crt")
        if not os.path.exists(ca_path):
            raise ValueError("Root CA certificate not found on server.")

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

        role = "admin" if is_user_admin(cn) else "user"
        return cn, role
    finally:
        if os.path.exists(cert_path):
            os.remove(cert_path)

def verify_certificate_and_get_admin(cert_pem_or_p12_bytes: bytes, p12_password: Optional[str] = None) -> str:
    cn, role = verify_certificate_and_get_user(cert_pem_or_p12_bytes, p12_password)
    if role != "admin":
        raise ValueError(f"Certificate for '{cn}' is authentic, but user lacks Administrator role")
    return cn

def authenticate_admin(request: Request) -> str:
    """Verifies admin status via Bearer Token, Admin Session Cookie, or HTTP Basic Auth."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            user = verify_session_token(token)
            if user and is_user_admin(user):
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
        if user and is_user_admin(user):
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized. FreeRADIUS Administrator credentials or certificate required.",
        headers={"WWW-Authenticate": 'Bearer realm="RajLabs FreeRADIUS Admin Area"'}
    )

def authenticate_self(request: Request) -> str:
    """Any valid session (admin token, user token, or session cookie).

    Returns the caller's own username. Used by /me/* self-service endpoints so
    regular users can manage ONLY their own account — never anyone else's.
    Admins calling /me/* get their own dossier, not another user's.
    """
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif request.cookies.get("admin_session"):
        token = request.cookies.get("admin_session")
    elif request.cookies.get("user_session"):
        token = request.cookies.get("user_session")

    if token:
        user = verify_session_token(token)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized. Please sign in to access your account."
    )

class SelfPasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)

async def _periodic_expiry_worker_loop():
    """Background worker loop: expires subscriptions (RFC 5176 CoA kicks) and
    auto-deletes expired captive-portal guest accounts that never recharged."""
    logger.info("Background session expiry worker started (RFC 5176 CoA / DB Entitlements).")
    while True:
        try:
            await asyncio.sleep(60)
            from api.entitlements import run_periodic_expiry_worker, cleanup_expired_guest_accounts
            count = run_periodic_expiry_worker()
            if count:
                logger.info("Periodic expiry worker: disconnected/expired %s past-due user session(s)", count)
            purged = cleanup_expired_guest_accounts()
            if purged:
                logger.info("Periodic expiry worker: auto-deleted %s expired guest account(s)", purged)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Periodic expiry worker check error: %s", e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed on published default secrets (issue #5) before touching the DB.
    check_startup_secrets()
    # Versioned migrations — single source of truth (api/migrations/*.sql).
    # Replaces the old scattered init_all_tables / ensure_* per-request DDL.
    try:
        from api.migrate import run_migrations
        applied = run_migrations()
        if applied:
            logger.info("Startup migrations applied: %s", applied)
    except Exception as e:
        logger.warning("DB migration check: %s", e)
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
    
    expiry_task = asyncio.create_task(_periodic_expiry_worker_loop())
    try:
        yield
    finally:
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="RajLabs FreeRADIUS Enterprise Management API",
    description="Secured Enterprise REST API, EAP-TLS PKI & Dashboard for FreeRADIUS at backend.rajlabs.in/radius",
    version="2.3.0",
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
RL_LOGIN_PER_MIN = int(os.getenv("RL_LOGIN_PER_MIN", "12") or 12)
RL_ENROLL_PER_MIN = int(os.getenv("RL_ENROLL_PER_MIN", "6") or 6)
RL_TEST_AUTH_PER_MIN = int(os.getenv("RL_TEST_AUTH_PER_MIN", "20") or 20)
RL_CERT_ISSUE_PER_MIN = int(os.getenv("RL_CERT_ISSUE_PER_MIN", "10") or 10)
RL_PORTAL_PER_MIN = int(os.getenv("RL_PORTAL_PER_MIN", "30") or 30)


def _client_ip(request: Optional[Request]) -> str:
    """Extracts client IP supporting Cloudflare tunnels, reverse proxies, and direct connections."""
    if not request:
        return "unknown"
    try:
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip and cf_ip.strip():
            return cf_ip.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff and xff.strip():
            client = xff.split(",")[0].strip()
            if client:
                return client
        x_real = request.headers.get("x-real-ip")
        if x_real and x_real.strip():
            return x_real.strip()
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return "unknown"


def check_rate_limit(request: Optional[Request], scope: str, per_minute: int) -> None:
    """Sliding-window token bucket per IP. Emits 429 Too Many Requests with Retry-After header."""
    if per_minute <= 0:
        return
    now = time.time()
    window = 60.0
    ip = _client_ip(request)
    key = f"{scope}:{ip}"
    with _RL_LOCK:
        hits = _RL_BUCKETS.get(key, [])
        hits = [t for t in hits if now - t < window]
        if len(hits) >= per_minute:
            retry_after = int(window - (now - hits[0])) + 1
            logger.warning("Rate limit exceeded for scope=%s client_ip=%s (limit=%d/min)", scope, ip, per_minute)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests to {scope}. Rate limit exceeded. Try again in {retry_after}s.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(per_minute),
                    "X-RateLimit-Remaining": "0"
                },
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
    # Blank/omitted = use the phone number digits as password (min 8 chars).
    # Always stored as Cleartext-Password: MS-CHAP/PEAP challenge-response
    # cannot work with hashed password attributes.
    password: Optional[str] = None
    group: Optional[str] = None
    attributes: Optional[Dict[str, str]] = None
    # Static client IP: None = leave existing pinning untouched, "" = remove it (DHCP), value = pin it.
    framed_ip: Optional[str] = None
    # Contact for onboarding (WhatsApp/SMS invites). Stored in central users table.
    phone: Optional[str] = None

class UserUpdateRequest(BaseModel):
    password: Optional[str] = None
    group: Optional[str] = None
    attributes: Optional[Dict[str, str]] = None
    framed_ip: Optional[str] = None
    phone: Optional[str] = None


def normalize_phone(value: Optional[str]) -> Optional[str]:
    """Validate + normalize an onboarding phone number (None/"" clears it)."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", value or "")
    # Allow leading country code: 7-15 digits total (E.164 range)
    if value and value.strip():
        if not (7 <= len(digits) <= 15):
            raise HTTPException(status_code=422, detail="Invalid phone number. Use 7-15 digits, e.g. +919876543210.")
        return "+" + digits if str(value).strip().startswith("+") else digits
    return None


def upsert_user_contact(cur, username: str, phone: Optional[str] = None,
                      set_phone: bool = False, group_name: Optional[str] = None):
    """Best-effort central-users contact write (never fails user CRUD).

    set_phone=False only ensures the row exists; set_phone=True writes/clears
    the phone number ("" clears it to NULL).
    """
    try:
        gid = None
        if group_name:
            cur.execute("SELECT id FROM groups WHERE UPPER(name) = UPPER(%s) LIMIT 1", (group_name.strip(),))
            grow = cur.fetchone()
            gid = grow["id"] if grow else None
        if set_phone:
            cur.execute("""
                INSERT INTO users (username, password_cleartext, phone, group_id, status)
                VALUES (%s, %s, %s, %s, 'ACTIVE')
                ON CONFLICT (username) DO UPDATE SET
                    phone = EXCLUDED.phone,
                    group_id = COALESCE(EXCLUDED.group_id, users.group_id)
            """, (username, generate_session_secret(24), phone, gid))
        else:
            cur.execute("""
                INSERT INTO users (username, password_cleartext, group_id, status)
                VALUES (%s, %s, %s, 'ACTIVE')
                ON CONFLICT (username) DO UPDATE SET
                    group_id = COALESCE(EXCLUDED.group_id, users.group_id)
            """, (username, generate_session_secret(24), gid))
    except Exception as e:
        logger.debug("central user contact upsert skipped for %s: %s", username, e)

def sync_central_password(cur, username: str, password: str) -> None:
    """Mirror the live Wi-Fi password into central users.password_cleartext.

    Deliberately CLEARTEXT, not a hash: MS-CHAPv2/PEAP challenge-response
    requires the server to know the actual password (a bcrypt/scrypt hash
    cannot answer challenges), and FreeRADIUS reads radcheck Cleartext-Password
    for the same reason. Never "upgrade" this column to a hash — logins break.

    Best-effort (never fails the caller): the access-engine sync reads this
    column when it must seed a missing radcheck credential, so it has to be
    the real password — never an onboarding placeholder. All password-write
    paths (create, profile update, admin reset, self-service change) call this.
    """
    try:
        cur.execute("""
            INSERT INTO users (username, password_cleartext, status)
            VALUES (%s, %s, 'ACTIVE')
            ON CONFLICT (username) DO UPDATE SET password_cleartext = EXCLUDED.password_cleartext
        """, (username, password))
    except Exception as e:
        logger.debug("central password mirror skipped for %s: %s", username, e)

class GuestUserGenerateRequest(BaseModel):
    duration: Optional[str] = "24h" # "1h", "6h", "12h", "24h" (default), "3d", "7d", "30d"
    group: Optional[str] = "guests"
    prefix: Optional[str] = "guest"
    note: Optional[str] = None

class PasswordChangeRequest(BaseModel):
    # Blank = reset to the user's phone number digits (min 8 chars).
    # Always Cleartext-Password (MS-CHAP/PEAP can't use hashed attributes).
    password: Optional[str] = None
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
    rate_limit: Optional[str] = None # Alias for mikrotik_rate_limit
    vlan_id: Optional[Union[int, str]] = None # 802.1Q VLAN Tag (e.g. 10, 20, 30 or "")
    framed_pool: Optional[str] = None # NAS DHCP Pool Name
    is_admin: Optional[bool] = False # Administrative-User role
    recharge_required: Optional[bool] = True # Whether users in this group need an active paid plan
    require_device_verification: Optional[bool] = False # Lock group members to verified MAC addresses
    extra_reply_attributes: Optional[Dict[str, str]] = None
    extra_check_attributes: Optional[Dict[str, str]] = None

class PlanCreateRequest(BaseModel):
    id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=64)
    price: float = Field(default=0.0, ge=0)
    currency: Optional[str] = "INR"
    validity_days: int = Field(default=1, ge=1)
    max_session_seconds: Optional[int] = 86400
    description: Optional[str] = None
    # Group restriction: None = leave unchanged on update (all groups on create);
    # [] = everyone; ["vip"] = VIP-only, etc. (RADIUS group names).
    allowed_groups: Optional[List[str]] = None


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

class SystemSettingsUpdateRequest(BaseModel):
    admin_contact_phone: Optional[str] = None
    admin_contact_name: Optional[str] = None
    upi_vpa: Optional[str] = None
    upi_merchant_name: Optional[str] = None
    default_voucher_code: Optional[str] = None
    currency: Optional[str] = None
    cert_signer_api_url: Optional[str] = None
    cert_signer_api_key: Optional[str] = None
    wifi_ssid: Optional[str] = None
    wifi_auth_type: Optional[str] = None
    # Payment Gateways & Email Reconciliation
    payment_active_gateway: Optional[str] = None
    razorpay_key_id: Optional[str] = None
    razorpay_key_secret: Optional[str] = None
    razorpay_webhook_secret: Optional[str] = None
    cashfree_app_id: Optional[str] = None
    cashfree_secret_key: Optional[str] = None
    cashfree_env: Optional[str] = None
    payu_merchant_key: Optional[str] = None
    payu_merchant_salt: Optional[str] = None
    email_imap_host: Optional[str] = None
    email_imap_port: Optional[int] = None
    email_imap_user: Optional[str] = None
    email_imap_password: Optional[str] = None
    email_imap_folder: Optional[str] = None

class ManualPaymentActivateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    plan_id: Optional[int] = None
    validity_days: Optional[int] = None
    amount: float = Field(default=0.0, ge=0)
    utr: Optional[str] = None
    note: Optional[str] = None
    gateway: Optional[str] = "MANUAL_ADMIN"

class EmailScanRequest(BaseModel):
    folder: Optional[str] = "INBOX"
    limit: Optional[int] = 30
    auto_activate: Optional[bool] = True

class GatewayTestRequest(BaseModel):
    gateway: str
    key_id: Optional[str] = None
    key_secret: Optional[str] = None
    app_id: Optional[str] = None
    secret_key: Optional[str] = None
    env: Optional[str] = "TEST"
    imap_host: Optional[str] = None
    imap_port: Optional[int] = 993
    imap_user: Optional[str] = None
    imap_password: Optional[str] = None
    imap_folder: Optional[str] = "INBOX"




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
@app.post("/radius/api/auth/unified-login", tags=["Authentication"])
@app.post("/api/auth/unified-login", tags=["Authentication"])
def unified_login(payload: AdminLoginRequest, response: Response, request: Request):
    check_rate_limit(request, "login", RL_LOGIN_PER_MIN)
    ok, role, info = check_user_role_and_authenticate(payload.username, payload.password)
    if not ok:
        client = _client_ip(request)
        logger.warning("Authentication FAILED username=%s client=%s", payload.username, client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password. Access denied."
        )

    logger.info("Authentication SUCCESS username=%s role=%s group=%s", payload.username, role, info.get("group"))
    token = generate_session_token(payload.username, role=role)
    set_admin_session_cookie(response, token, remember=bool(payload.remember))

    redirect_url = "/radius" if role == "admin" else "/radius/portal"
    return {
        "status": "success",
        "token": token,
        "username": payload.username,
        "role": role,
        "group": info.get("group", "default"),
        "redirect_url": redirect_url,
        "message": f"Welcome back, {payload.username}!" if role == "admin" else f"Welcome {payload.username} to RajLabs Wi-Fi!"
    }

@app.post("/radius/api/auth/cert-login", tags=["Authentication"])
@app.post("/api/auth/cert-login", tags=["Authentication"])
def cert_login(payload: CertLoginRequest, response: Response, request: Request):
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
        username, role = verify_certificate_and_get_user(cert_data, payload.p12_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Certificate verification failure: {str(e)}")

    token = generate_session_token(username, role=role)
    if role == "admin":
        set_admin_session_cookie(response, token, remember=True)
    redirect_url = "/radius" if role == "admin" else "/radius/portal"
    return {
        "status": "success",
        "token": token,
        "username": username,
        "auth_method": "x509_certificate",
        "role": role,
        "redirect_url": redirect_url,
        "message": f"Certificate verified! Welcome {username} ({'Administrator' if role == 'admin' else 'Wi-Fi Member'})."
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

# Public Health Check & Status
@app.get("/radius/api/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
@app.get("/radius/api/status", tags=["Health"])
@app.get("/api/status", tags=["Health"])
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
        "api_ok": True,
        "db_ok": db_ok,
        "radius_ok": radius_ok,
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
    return get_openapi(title="RajLabs FreeRADIUS API", version="2.3.0", routes=app.routes)

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

            # Onboarding contact numbers (central users table)
            phones: Dict[str, str] = {}
            try:
                cur.execute("SELECT username, phone FROM users WHERE phone IS NOT NULL AND phone <> ''")
                for r in cur.fetchall():
                    if r.get("phone"):
                        phones[r["username"]] = r["phone"]
            except Exception:
                pass

            # Ban state: central DISABLED or an Auth-Type Reject row present
            banned: Dict[str, bool] = {}
            try:
                cur.execute("SELECT username FROM users WHERE status = 'DISABLED'")
                for r in cur.fetchall():
                    banned[r["username"]] = True
                cur.execute("SELECT DISTINCT username FROM radcheck WHERE attribute = 'Auth-Type' AND value = 'Reject'")
                for r in cur.fetchall():
                    banned[r["username"]] = True
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
                        "expiration": None,
                        "active_sessions": 0,
                        "last_auth": None,
                        "phone": None,
                        "check_attributes": [],
                        "reply_attributes": []
                    }
                if "Password" in row["attribute"] and not users_map[u]["password_type"]:
                    users_map[u]["password_type"] = row["attribute"]
                if row["attribute"].lower() == "expiration":
                    users_map[u]["expiration"] = row["value"]
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
                data["phone"] = phones.get(u)
                data["banned"] = bool(banned.get(u, False))

            # Active subscription per user (for Users-table subscription column).
            # Best-effort: central `users`/`subscriptions` may lag radcheck-only rows.
            try:
                cur.execute("""
                    SELECT u.username, p.name AS plan_name, s.expires_at AS expires_at,
                           s.status AS status
                    FROM users u
                    JOIN subscriptions s ON s.user_id = u.id
                    LEFT JOIN plans p ON s.plan_id = p.id
                    WHERE s.status = 'ACTIVE' AND s.expires_at > CURRENT_TIMESTAMP
                """)
                for r in cur.fetchall():
                    un = r.get("username")
                    if un in users_map:
                        exp = r.get("expires_at")
                        users_map[un]["subscription"] = {
                            "plan_name": r.get("plan_name") or "Custom Pass",
                            "expires_at": exp.isoformat() if hasattr(exp, "isoformat") else (str(exp) if exp else None),
                            "status": r.get("status"),
                        }
                for u, data in users_map.items():
                    data.setdefault("subscription", None)
            except Exception as e:
                logger.debug("list_users subscription enrichment skipped: %s", e)
                for u, data in users_map.items():
                    data.setdefault("subscription", None)

            # Recharge policy per user (same rule as the access engine: user
            # override wins, else the central group policy; unknown → required).
            # Lets the table show "Exempt" instead of a misleading "No subscription".
            try:
                cur.execute("SELECT name, recharge_required FROM groups")
                group_policy = {str(r.get("name", "")).upper(): bool(r.get("recharge_required", True))
                                for r in cur.fetchall()}
                cur.execute("SELECT username, recharge_required_override FROM users")
                overrides = {r.get("username"): r.get("recharge_required_override")
                             for r in cur.fetchall()}
                for u, data in users_map.items():
                    ov = overrides.get(u, None)
                    if ov is not None:
                        data["recharge_required"] = bool(ov)
                        data["recharge_policy"] = "user override"
                    else:
                        g = (data.get("group") or "").upper()
                        data["recharge_required"] = group_policy.get(g, True)
                        data["recharge_policy"] = f"group:{data.get('group')}" if data.get("group") else "default"
            except Exception as e:
                logger.debug("list_users recharge-policy enrichment skipped: %s", e)
                for u, data in users_map.items():
                    data.setdefault("recharge_required", True)
                    data.setdefault("recharge_policy", "default")

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
            phone = None
            try:
                cur.execute("SELECT phone FROM users WHERE username = %s LIMIT 1", (username,))
                prow = cur.fetchone()
                phone = prow["phone"] if prow else None
            except Exception:
                pass
            return {
                "username": username,
                "group": checks[0]["groupname"],
                "has_certificate": os.path.exists(cert_path),
                "password_type": password_type,
                "phone": phone,
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

@app.get("/radius/api/users/{username}/overview", tags=["Users"])
@app.get("/api/users/{username}/overview", tags=["Users"])
def get_user_overview(username: str, _: str = Depends(authenticate_admin)):
    """Full subscriber dossier for the Users-table detail popup.

    Returns identity + group, active subscription (plan, expiry, remaining),
    recent payments/subscriptions, usage stats, verified + seen devices,
    live sessions and recent auth history with reject reasons.
    Passwords are never returned.
    """
    uname = validate_username(username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT rc.username, rug.groupname
                FROM radcheck rc
                LEFT JOIN radusergroup rug ON rc.username = rug.username
                WHERE rc.username = %s LIMIT 1
            """, (uname,))
            id_row = cur.fetchone()
            if not id_row:
                raise HTTPException(status_code=404, detail=f"User '{uname}' not found.")
            group = id_row.get("groupname")

            # Central user id (may be missing for legacy radcheck-only users)
            user_id = None
            try:
                cur.execute("SELECT id, status, phone FROM users WHERE username = %s LIMIT 1", (uname,))
                u_row = cur.fetchone()
                if u_row:
                    user_id = u_row["id"]
            except Exception:
                u_row = None

            # Subscriptions (latest 10, active first)
            subscriptions = []
            active_sub = None
            try:
                if user_id is not None:
                    cur.execute("""
                        SELECT s.id, s.starts_at, s.expires_at, s.status,
                               p.id AS plan_id, p.name AS plan_name, p.price AS plan_price,
                               p.validity_days AS plan_validity_days,
                               pay.amount AS pay_amount, pay.gateway AS pay_gateway,
                               pay.gateway_payment_id AS pay_ref
                        FROM subscriptions s
                        LEFT JOIN plans p ON s.plan_id = p.id
                        LEFT JOIN payments pay ON s.payment_id = pay.id
                        WHERE s.user_id = %s
                        ORDER BY CASE WHEN s.status = 'ACTIVE' AND s.expires_at > CURRENT_TIMESTAMP THEN 0 ELSE 1 END,
                                 s.expires_at DESC
                        LIMIT 10
                    """, (user_id,))
                    for r in cur.fetchall():
                        def _iso(v):
                            return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else None)
                        def _ms(v):
                            try:
                                return int(v.timestamp() * 1000) if hasattr(v, "timestamp") else None
                            except Exception:
                                return None
                        item = {
                            "id": r["id"],
                            "plan_id": r.get("plan_id"),
                            "plan_name": r.get("plan_name") or "Custom Pass",
                            "plan_price": float(r["plan_price"]) if r.get("plan_price") is not None else None,
                            "plan_validity_days": r.get("plan_validity_days"),
                            "starts_at": _iso(r.get("starts_at")),
                            "expires_at": _iso(r.get("expires_at")),
                            "expires_at_epoch_ms": _ms(r.get("expires_at")),
                            "status": r.get("status"),
                            "payment_amount": float(r["pay_amount"]) if r.get("pay_amount") is not None else None,
                            "payment_gateway": r.get("pay_gateway"),
                            "payment_ref": r.get("pay_ref"),
                        }
                        subscriptions.append(item)
                    active_sub = next((s for s in subscriptions
                                       if s["status"] == "ACTIVE"), None)
            except Exception as e:
                logger.debug("overview subscriptions skipped for %s: %s", uname, e)

            # Payments (latest 10)
            payments = []
            try:
                if user_id is not None:
                    cur.execute("""
                        SELECT p.id, p.plan_id, COALESCE(pl.name, 'Custom Pass') AS plan_name,
                               p.gateway, p.gateway_payment_id, p.amount, p.status,
                               p.verified_at, p.created_at
                        FROM payments p
                        LEFT JOIN plans pl ON p.plan_id = pl.id
                        WHERE p.user_id = %s
                        ORDER BY p.created_at DESC LIMIT 10
                    """, (user_id,))
                    for r in cur.fetchall():
                        def _iso2(v):
                            return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else None)
                        payments.append({
                            "id": r["id"],
                            "plan_name": r.get("plan_name"),
                            "gateway": r.get("gateway"),
                            "reference": r.get("gateway_payment_id"),
                            "amount": float(r["amount"]) if r.get("amount") is not None else 0.0,
                            "status": r.get("status"),
                            "created_at": _iso2(r.get("created_at")),
                        })
            except Exception as e:
                logger.debug("overview payments skipped for %s: %s", uname, e)

            # Live sessions
            live_sessions = []
            try:
                cur.execute("""
                    SELECT radacctid, acctsessionid, nasipaddress::text AS nas_ip,
                           framedipaddress::text AS framed_ip, callingstationid,
                           acctstarttime, acctinputoctets, acctoutputoctets
                    FROM radacct WHERE username = %s AND acctstoptime IS NULL
                    ORDER BY radacctid DESC LIMIT 20
                """, (uname,))
                for r in cur.fetchall():
                    st = r.get("acctstarttime")
                    live_sessions.append({
                        "radacctid": r.get("radacctid"),
                        "acctsessionid": r.get("acctsessionid"),
                        "nas_ip": r.get("nas_ip"),
                        "framed_ip": r.get("framed_ip"),
                        "mac": r.get("callingstationid"),
                        "started_at": st.isoformat() if hasattr(st, "isoformat") else (str(st) if st else None),
                        "in_octets": int(r.get("acctinputoctets") or 0),
                        "out_octets": int(r.get("acctoutputoctets") or 0),
                    })
            except Exception:
                pass

            # Recent auth history (with reject reason, never passwords)
            auth_history = []
            try:
                cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='radpostauth' AND column_name='reason'")
                has_reason = bool(cur.fetchone())
                q = "SELECT username, reply, authdate" + (", reason" if has_reason else "") + " FROM radpostauth WHERE username = %s ORDER BY id DESC LIMIT 15"
                cur.execute(q, (uname,))
                for r in cur.fetchall():
                    ts = r.get("authdate")
                    auth_history.append({
                        "reply": r.get("reply") or "—",
                        "reason": (r.get("reason") if has_reason else None),
                        "at": ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else None),
                    })
            except Exception:
                pass

            # Usage totals (upload/download/sessions) from radacct
            usage = {"total_sessions": 0, "up_bytes": 0, "down_bytes": 0, "total_hours": 0.0}
            try:
                cur.execute("""
                    SELECT COUNT(*) AS n,
                           COALESCE(SUM(acctinputoctets),0)::bigint AS up_b,
                           COALESCE(SUM(acctoutputoctets),0)::bigint AS down_b,
                           COALESCE(SUM(acctsessiontime),0)::bigint AS secs
                    FROM radacct WHERE username = %s
                """, (uname,))
                ur = cur.fetchone() or {}
                usage = {
                    "total_sessions": int(ur.get("n") or 0),
                    "up_bytes": int(ur.get("up_b") or 0),
                    "down_bytes": int(ur.get("down_b") or 0),
                    "total_hours": round(int(ur.get("secs") or 0) / 3600, 2),
                }
            except Exception:
                pass

            # Seen devices (from accounting Calling-Station-Id)
            seen_devices = []
            try:
                cur.execute("""
                    SELECT callingstationid AS mac, COUNT(*) AS sessions,
                           MAX(acctstarttime) AS last_seen
                    FROM radacct
                    WHERE username = %s AND callingstationid IS NOT NULL AND callingstationid <> ''
                    GROUP BY callingstationid ORDER BY last_seen DESC NULLS LAST LIMIT 20
                """, (uname,))
                for r in cur.fetchall():
                    ls = r.get("last_seen")
                    seen_devices.append({
                        "mac": r.get("mac"),
                        "sessions": int(r.get("sessions") or 0),
                        "last_seen": ls.isoformat() if hasattr(ls, "isoformat") else (str(ls) if ls else None),
                    })
            except Exception:
                pass

            # Verified devices (MAC allowlist)
            verified = {"require_verified": False, "devices": []}
            try:
                cur.execute("SELECT require_verified FROM user_device_policy WHERE username = %s", (uname,))
                pr = cur.fetchone()
                if pr:
                    verified["require_verified"] = bool(pr.get("require_verified"))
                cur.execute("SELECT mac, label, added_at FROM verified_devices WHERE username = %s ORDER BY added_at DESC LIMIT 50", (uname,))
                for r in cur.fetchall():
                    at = r.get("added_at")
                    verified["devices"].append({
                        "mac": r.get("mac"),
                        "label": r.get("label"),
                        "added_at": at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None),
                    })
            except Exception:
                pass

            cert_path = os.path.join(CLIENT_CERTS_DIR, f"{uname}.p12")
            # Recharge policy for this user (mirrors list_users rule).
            recharge_required, recharge_policy = True, "default"
            try:
                ov = (u_row.get("recharge_required_override")
                      if isinstance(u_row, dict) else None)
                if ov is not None:
                    recharge_required, recharge_policy = bool(ov), "user override"
                else:
                    cur.execute("SELECT recharge_required FROM groups WHERE UPPER(name) = UPPER(%s) LIMIT 1", (group or "",))
                    gr = cur.fetchone()
                    if gr is not None:
                        recharge_required = bool(gr.get("recharge_required", True))
                        recharge_policy = f"group:{group}"
            except Exception:
                pass
            try:
                cur.execute("SELECT 1 FROM radcheck WHERE username = %s AND attribute = 'Auth-Type' AND value = 'Reject' LIMIT 1", (uname,))
                has_reject_row = bool(cur.fetchone())
            except Exception:
                has_reject_row = False
            return {
                "username": uname,
                "group": group,
                "status": (u_row.get("status") if u_row else "ACTIVE"),
                "banned": bool((u_row.get("status") if u_row else "") == "DISABLED" or has_reject_row),
                "phone": (u_row.get("phone") if u_row else None),
                "recharge_required": recharge_required,
                "recharge_policy": recharge_policy,
                "has_certificate": os.path.exists(cert_path),
                "active_subscription": active_sub,
                "subscriptions": subscriptions,
                "payments": payments,
                "usage": usage,
                "verified_devices": verified,
                "seen_devices": seen_devices,
                "live_sessions": live_sessions,
                "auth_history": auth_history,
            }
    finally:
        conn.close()

@app.get("/radius/api/me/overview", tags=["Self Service"])
@app.get("/api/me/overview", tags=["Self Service"])
def get_my_overview(caller: str = Depends(authenticate_self)):
    """Own subscriber dossier (subscription, usage, payments, devices,
    sessions, auth history). Users can ONLY see themselves; admins calling
    this get their own account, never another user's."""
    return get_user_overview(username=caller, _=caller)


@app.post("/radius/api/me/password", tags=["Self Service"])
@app.post("/api/me/password", tags=["Self Service"])
def change_own_password(payload: SelfPasswordChangeRequest, request: Request, caller: str = Depends(authenticate_self)):
    """Change your own Wi-Fi password (current-password proof required).

    Keeps the current session alive. Plaintext passwords are never logged.
    """
    uname = validate_username(caller)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rc.username, rc.attribute, rc.value FROM radcheck rc "
                "WHERE rc.username = %s AND rc.attribute LIKE '%%Password'",
                (uname,),
            )
            row = cur.fetchone()
            if not row or not secrets.compare_digest(str(row["value"]), payload.current_password):
                raise HTTPException(status_code=401, detail="Current password is incorrect.")
            validate_password_policy(payload.new_password, uname)
            attr = row["attribute"] or "Cleartext-Password"
            cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (uname,))
            cur.execute(
                "INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, %s, ':=', %s)",
                (uname, attr, payload.new_password),
            )
            sync_central_password(cur, uname, payload.new_password)
            conn.commit()
    finally:
        conn.close()
    info = password_strength(payload.new_password)
    log_audit(uname, "self_password_change", uname, f"strength={info['strength']}")
    logger.info("Self-service password change username=%s strength=%s", uname, info["strength"])
    return {"status": "success", "message": "Your Wi-Fi password was updated successfully."}


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
        "min_classes": 1,
        "require_upper": False,
        "require_lower": False,
        "require_digit": False,
        "require_symbol": False,
        "description": f"Min {PASSWORD_MIN_LENGTH} characters — anything goes (e.g. 9876543210). Longer is stronger.",
        "default_generate_length": 16,
    }

# ----------------------------------------------------------------------------
# NAS-subnet coverage guard: a static Framed-IP-Address must belong to the
# NAS-side LAN (e.g. local 192.168/172.16), never the server's own cloud
# subnet. Checks warn (never block — routed setups are legitimate).
# ----------------------------------------------------------------------------
def read_nas_networks() -> tuple[List[str], bool]:
    """Parse nas.nasname into networks. Returns (cidr_list, has_catch_all)."""
    nets: List[str] = []
    catch_all = False
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT nasname FROM nas")
                for r in cur.fetchall():
                    raw = (r.get("nasname") or "").strip()
                    if not raw:
                        continue
                    try:
                        net = ipaddress.ip_network(raw, strict=False)
                    except ValueError:
                        continue  # hostname — cannot map to a subnet
                    if net.prefixlen == 0:
                        catch_all = True
                    nets.append(str(net))
        finally:
            conn.close()
    except Exception as e:
        logger.warning("NAS subnet read failed: %s", e)
        return [], False
    return sorted(set(nets)), catch_all


def check_ip_coverage(ip_str: Optional[str]) -> Dict[str, Any]:
    """Is this client IP inside a registered NAS subnet?"""
    try:
        ip = ipaddress.ip_address((ip_str or "").strip())
    except ValueError:
        return {"ip": ip_str, "valid": False, "covered": False, "known": True,
                "nas_networks": [],
                "message": f"'{ip_str}' is not a valid IPv4/IPv6 address — the NAS will fail or ignore it."}
    nets, catch_all = read_nas_networks()
    if catch_all:
        return {"ip": str(ip), "valid": True, "covered": True, "known": True,
                "nas_networks": nets,
                "message": f"{ip} is accepted (a catch-all 0.0.0.0/0 NAS entry covers every subnet)."}
    if not nets:
        return {"ip": str(ip), "valid": True, "covered": None, "known": False,
                "nas_networks": [],
                "message": "No NAS subnets registered yet — cannot verify. Add your routers under NAS Clients first."}
    hits = [n for n in nets if ip in ipaddress.ip_network(n)]
    if hits:
        return {"ip": str(ip), "valid": True, "covered": True, "known": True,
                "nas_networks": nets,
                "message": f"{ip} belongs to NAS subnet {hits[0]} — safe to pin."}
    return {"ip": str(ip), "valid": True, "covered": False, "known": True,
            "nas_networks": nets,
            "message": f"{ip} is outside all registered NAS subnets ({', '.join(nets)}) — "
                       "devices there get an unroutable address (Wi-Fi connects, no internet). "
                       "Use DHCP or a Framed-Pool instead."}


def framed_ip_warnings(attributes: Optional[Dict[str, str]], scope: str) -> List[str]:
    """Warnings for static Framed-IP-Address use (never blocks the save)."""
    warnings: List[str] = []
    if not attributes:
        return warnings
    found = False
    for attr, val in attributes.items():
        if (attr or "").strip().lower() != "framed-ip-address":
            continue
        found = True
        cov = check_ip_coverage(val)
        if not cov["valid"] or cov["covered"] is False:
            warnings.append(f"{scope}: {cov['message']}")
    if found and scope.startswith("Group"):
        warnings.append(f"{scope}: one static IP shared by every member will clash "
                        "as soon as two devices are online — prefer Framed-Pool or per-user IPs.")
    return warnings


@app.get("/radius/api/networks/coverage", tags=["NAS"])
@app.get("/api/networks/coverage", tags=["NAS"])
def get_ip_coverage(ip: str = Query(...), _: str = Depends(authenticate_admin)):
    """Live check for the UI: is this client IP inside a registered NAS subnet?"""
    return check_ip_coverage(ip)


@app.post("/radius/api/users", tags=["Users"])
@app.post("/api/users", tags=["Users"])
def create_or_update_user(payload: UserCreateRequest, admin_user: str = Depends(authenticate_admin)):
    phone = normalize_phone(payload.phone) if payload.phone is not None else None
    # Blank password defaults to the phone number digits (e.g. 919876543210).
    raw_pw = (payload.password or "").strip()
    pw_source = "given"
    if not raw_pw:
        if phone:
            raw_pw = re.sub(r"\D", "", phone)
            if len(raw_pw) < PASSWORD_MIN_LENGTH:
                raise HTTPException(status_code=422, detail="Phone number too short to use as password — set an explicit password (min 8 characters).")
            pw_source = "phone"
        else:
            raise HTTPException(status_code=422, detail="Password is required when no phone number is given (leave blank to use the phone number).")
    validate_password_policy(raw_pw, payload.username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (payload.username,))
            existed = cur.fetchone() is not None
            cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (payload.username,))

            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Cleartext-Password', ':=', %s)
            """, (payload.username, raw_pw))

            if payload.group:
                cur.execute("DELETE FROM radusergroup WHERE username = %s", (payload.username,))
                cur.execute("""
                    INSERT INTO radusergroup (username, groupname, priority)
                    VALUES (%s, %s, 1)
                """, (payload.username, payload.group))

                # If new user and group has RajLabs-Require-Device-Lock, initialize user_device_policy
                if not existed:
                    cur.execute("SELECT 1 FROM radgroupreply WHERE groupname = %s AND attribute = 'RajLabs-Require-Device-Lock' AND value = '1'", (payload.group,))
                    if cur.fetchone():
                        cur.execute("""
                            INSERT INTO user_device_policy (username, require_verified, updated_at)
                            VALUES (%s, TRUE, NOW())
                            ON CONFLICT (username) DO NOTHING
                        """, (payload.username,))

            if payload.attributes:
                for attr, val in payload.attributes.items():
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = %s", (payload.username, attr))
                    cur.execute("""
                        INSERT INTO radreply (username, attribute, op, value)
                        VALUES (%s, %s, '=', %s)
                    """, (payload.username, attr, val))

            # Static IP pinning: explicit None leaves it, "" removes it (DHCP).
            ip_attrs: Dict[str, str] = {}
            if payload.framed_ip is not None:
                if payload.framed_ip.strip():
                    try:
                        ipaddress.ip_address(payload.framed_ip.strip())
                    except ValueError:
                        raise HTTPException(status_code=422, detail=f"'{payload.framed_ip}' is not a valid IP address.")
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Framed-IP-Address'", (payload.username,))
                    cur.execute("INSERT INTO radreply (username, attribute, op, value) VALUES (%s, 'Framed-IP-Address', '=', %s)",
                                (payload.username, payload.framed_ip.strip()))
                    ip_attrs = {"Framed-IP-Address": payload.framed_ip.strip()}
                else:
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Framed-IP-Address'", (payload.username,))

            # Onboarding contact (central users table; never fails the CRUD)
            upsert_user_contact(cur, payload.username, phone=phone,
                                set_phone=payload.phone is not None,
                                group_name=payload.group)
            # Central password mirror (access-engine seeds from here when needed)
            sync_central_password(cur, payload.username, raw_pw)

            conn.commit()
            merged = dict(payload.attributes or {})
            merged.update(ip_attrs)
            warnings = framed_ip_warnings(merged, f"User '{payload.username}'")
            log_audit(admin_user, "user_create" if not existed else "user_update", payload.username,
                      f"group={payload.group} password_source={pw_source}" + (f" warnings={len(warnings)}" if warnings else ""))
            return {"status": "success", "created": not existed,
                    "message": f"User '{payload.username}' {'created' if not existed else 'updated'} successfully"
                               + (" (password = phone number)" if pw_source == "phone" else ""),
                    "password": raw_pw,
                    "password_source": pw_source,
                    "warnings": warnings}
    finally:
        conn.close()

@app.put("/radius/api/users/{username}", tags=["Users"])
@app.put("/api/users/{username}", tags=["Users"])
def update_user_profile(username: str, payload: UserUpdateRequest, admin_user: str = Depends(authenticate_admin)):
    uname = validate_username(username)
    phone = normalize_phone(payload.phone) if payload.phone is not None else None
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (uname,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"User '{uname}' not found.")

            # Update password if provided and non-empty
            if payload.password and payload.password.strip():
                validate_password_policy(payload.password, uname)
                cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (uname,))
                cur.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Cleartext-Password', ':=', %s)
                """, (uname, payload.password))
                sync_central_password(cur, uname, payload.password)

            # Update group membership
            if payload.group is not None:
                cur.execute("DELETE FROM radusergroup WHERE username = %s", (uname,))
                if payload.group.strip():
                    cur.execute("""
                        INSERT INTO radusergroup (username, groupname, priority)
                        VALUES (%s, %s, 1)
                    """, (uname, payload.group.strip()))

            # Update extra attributes
            if payload.attributes is not None:
                for attr, val in payload.attributes.items():
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = %s", (uname, attr))
                    if val and val.strip():
                        cur.execute("""
                            INSERT INTO radreply (username, attribute, op, value)
                            VALUES (%s, %s, '=', %s)
                        """, (uname, attr, val.strip()))

            # Static IP pinning
            ip_attrs: Dict[str, str] = {}
            if payload.framed_ip is not None:
                if payload.framed_ip.strip():
                    try:
                        ipaddress.ip_address(payload.framed_ip.strip())
                    except ValueError:
                        raise HTTPException(status_code=422, detail=f"'{payload.framed_ip}' is not a valid IP address.")
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Framed-IP-Address'", (uname,))
                    cur.execute("INSERT INTO radreply (username, attribute, op, value) VALUES (%s, 'Framed-IP-Address', '=', %s)",
                                (uname, payload.framed_ip.strip()))
                    ip_attrs = {"Framed-IP-Address": payload.framed_ip.strip()}
                else:
                    cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Framed-IP-Address'", (uname,))

            # Onboarding contact ("" clears; None leaves unchanged)
            if payload.phone is not None or (payload.group is not None and payload.group.strip()):
                upsert_user_contact(cur, uname, phone=phone,
                                    set_phone=payload.phone is not None,
                                    group_name=(payload.group or "").strip() or None)

            conn.commit()
            merged = dict(payload.attributes or {})
            merged.update(ip_attrs)
            warnings = framed_ip_warnings(merged, f"User '{uname}'")
            log_audit(admin_user, "user_update", uname,
                      f"group={payload.group}" + (f" warnings={len(warnings)}" if warnings else ""))
            return {"status": "success", "message": f"User '{uname}' updated successfully", "warnings": warnings}
    finally:
        conn.close()

GUEST_DURATION_MAP = {
    "1h": (3600, "1 Hour"),
    "6h": (21600, "6 Hours"),
    "12h": (43200, "12 Hours"),
    "24h": (86400, "1 Day (24 Hours)"),
    "1d": (86400, "1 Day (24 Hours)"),
    "3d": (259200, "3 Days"),
    "7d": (604800, "7 Days (1 Week)"),
    "30d": (2592000, "30 Days (1 Month)")
}

@app.post("/radius/api/users/guest", tags=["Users"])
@app.post("/api/users/guest", tags=["Users"])
def generate_guest_user(payload: Optional[GuestUserGenerateRequest] = None, admin_user: str = Depends(authenticate_admin)):
    """1-Click Guest User Generator with configurable validity (default: 1 day / 24 hours).
    
    Sets FreeRADIUS protocol-level Expiration in radcheck, Session-Timeout in radreply,
    associates group policy, and records active entitlement in subscriptions table.
    """
    if payload is None:
        payload = GuestUserGenerateRequest()
    
    dur_key = (payload.duration or "24h").strip().lower()
    validity_sec, dur_label = GUEST_DURATION_MAP.get(dur_key, (86400, "1 Day (24 Hours)"))
    group_name = (payload.group or "guests").strip()
    prefix = (payload.prefix or "guest").strip().lower()
    if not re.match(r'^[a-zA-Z0-9_\-]+$', prefix):
        prefix = "guest"
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Generate unique random guest username
            username = None
            for _ in range(30):
                suffix = "".join(secrets.choice(string.digits) for _ in range(4))
                candidate = f"{prefix}-{suffix}"
                cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (candidate,))
                if not cur.fetchone():
                    username = candidate
                    break
            if not username:
                username = f"{prefix}-{uuid.uuid4().hex[:6]}"
            
            # 2. Generate secure policy-compliant password
            password = generate_secure_password(length=14, use_symbols=True, exclude_ambiguous=True)
            
            # 3. Compute timestamps from UTC epoch (never wall-clock math).
            # FreeRADIUS `expiration` parses Expiration in the daemon's local
            # zone, so the container runs TZ=UTC (Dockerfile + entrypoint pin)
            # and this string is formatted from gmtime(epoch) explicitly.
            now = datetime.datetime.now(datetime.timezone.utc)
            expires_at = now + datetime.timedelta(seconds=validity_sec)
            expires_epoch_ms = int(expires_at.timestamp() * 1000)
            expiration_str = time.strftime("%d %b %Y %H:%M:%S", time.gmtime(expires_epoch_ms // 1000))
            
            # 4. Insert into FreeRADIUS radcheck (Cleartext-Password & Expiration check attribute)
            cur.execute("DELETE FROM radcheck WHERE username = %s", (username,))
            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Cleartext-Password', ':=', %s)
            """, (username, password))
            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Expiration', ':=', %s)
            """, (username, expiration_str))
            
            # 5. Assign policy group in radusergroup
            cur.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
            cur.execute("""
                INSERT INTO radusergroup (username, groupname, priority)
                VALUES (%s, %s, 1)
            """, (username, group_name))
            
            # 6. Session-Timeout in radreply
            session_timeout = min(validity_sec, 86400)
            cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Session-Timeout'", (username,))
            cur.execute("""
                INSERT INTO radreply (username, attribute, op, value)
                VALUES (%s, 'Session-Timeout', '=', %s)
            """, (username, str(session_timeout)))
            
            # 7. Record in central users, 0-Rs guest sale + subscription (so
            # recharge-gated groups see a valid entitlement, not "no subscription").
            # Best-effort: RADIUS radcheck above is authoritative; ledger must not fail guest creation.
            guest_payment_id = None
            guest_plan_id = None
            try:
                cur.execute("SELECT id FROM groups WHERE UPPER(name) = UPPER(%s) LIMIT 1", (group_name,))
                g_row = cur.fetchone()
                if not g_row:
                    # Fall back to GUEST / FREE central group (case-insensitive)
                    cur.execute("SELECT id FROM groups WHERE UPPER(name) IN ('GUEST', 'GUESTS', 'FREE') ORDER BY CASE WHEN UPPER(name) LIKE 'GUEST%' THEN 0 ELSE 1 END LIMIT 1")
                    g_row = cur.fetchone()
                g_id = g_row["id"] if g_row else None
                # Resolve 1-day plan for ledger linkage (validity_days=1, cheapest first)
                try:
                    cur.execute("SELECT id FROM plans WHERE validity_days = 1 ORDER BY price ASC LIMIT 1")
                    p_row = cur.fetchone()
                    guest_plan_id = p_row["id"] if p_row else None
                except Exception:
                    guest_plan_id = None
                cur.execute("""
                    INSERT INTO users (username, password_cleartext, group_id, status)
                    VALUES (%s, %s, %s, 'ACTIVE')
                    ON CONFLICT (username) DO UPDATE SET password_cleartext = EXCLUDED.password_cleartext, status = 'ACTIVE'
                    RETURNING id
                """, (username, password, g_id))
                u_row = cur.fetchone()
                if u_row:
                    uid = u_row["id"]
                    guest_ref = f"GUEST-{username}-{int(time.time())}"
                    try:
                        cur.execute("""
                            INSERT INTO payments (user_id, plan_id, gateway, gateway_order_id, gateway_payment_id,
                                                  amount, currency, status, verified_at, raw_reference)
                            VALUES (%s, %s, 'GUEST', %s, %s, 0.00, 'INR', 'SUCCESS', CURRENT_TIMESTAMP, %s)
                            RETURNING id
                        """, (uid, guest_plan_id, f"1-click guest {dur_label} by {admin_user}",
                              guest_ref, f"Complimentary 1-click guest pass ({dur_label}), 0 Rs sale"))
                        guest_payment_id = cur.fetchone()["id"]
                    except Exception as pay_err:
                        logger.debug("Guest 0-Rs payment write skipped: %s", pay_err)
                        guest_payment_id = None
                    cur.execute("""
                        INSERT INTO subscriptions (user_id, plan_id, starts_at, expires_at, status, payment_id)
                        VALUES (%s, %s, %s, %s, 'ACTIVE', %s)
                    """, (uid, guest_plan_id, now, expires_at, guest_payment_id))
            except Exception as sub_err:
                logger.debug("Central subscription write skipped: %s", sub_err)
            
            conn.commit()
            log_audit(admin_user, "guest_user_create", username, f"duration={dur_key} ({dur_label}) expires={expires_at.isoformat()}")
            
            return {
                "status": "success",
                "username": username,
                "password": password,
                "group": group_name,
                "duration": dur_key,
                "duration_label": dur_label,
                "validity_seconds": validity_sec,
                "expires_at": expires_at.isoformat(),
                "expires_at_epoch_ms": expires_epoch_ms,
                "expiration_str": expiration_str,
                "message": f"Guest user '{username}' created successfully with {dur_label} access (expires {expiration_str})."
            }
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

class BanActionRequest(BaseModel):
    disconnect: Optional[bool] = False
class BulkUserActionRequest(BaseModel):
    usernames: List[str] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., description="ban | unban | revoke_certs | delete")
    disconnect: Optional[bool] = False

BAN_MESSAGE = "Account banned by administrator. Contact support for reactivation."

def _apply_user_ban(cur, uname: str, banned: bool, admin_user: str) -> None:
    """Password-preserving ban/unban.

    Ban = central status DISABLED + Auth-Type Reject + Reply-Message; all
    credential and policy rows untouched. Unban removes exactly those rows.
    """
    cur.execute("""
        INSERT INTO users (username, password_cleartext, status)
        VALUES (%s, %s, %s)
        ON CONFLICT (username) DO UPDATE SET status = EXCLUDED.status
    """, (uname, generate_session_secret(24), "DISABLED" if banned else "ACTIVE"))
    if banned:
        cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute = 'Auth-Type'", (uname,))
        cur.execute("INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Auth-Type', ':=', 'Reject')", (uname,))
        cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Reply-Message'", (uname,))
        cur.execute("INSERT INTO radreply (username, attribute, op, value) VALUES (%s, 'Reply-Message', '=', %s)", (uname, BAN_MESSAGE))
    else:
        cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute = 'Auth-Type'", (uname,))
        cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Reply-Message' AND value = %s", (uname, BAN_MESSAGE))

def _disconnect_user_sessions(uname: str) -> int:
    """Best-effort CoA disconnect of all live sessions. Returns NAS count hit."""
    hits = 0
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT nasipaddress::text AS nas_ip FROM radacct WHERE username = %s AND acctstoptime IS NULL AND nasipaddress IS NOT NULL", (uname,))
            nas_ips = [r["nas_ip"] for r in cur.fetchall() if r["nas_ip"]]
        conn.close()
        for nas_ip in nas_ips:
            try:
                ok, _ = send_coa_disconnect(uname, nas_ip, RADIUS_SECRET)
                if ok:
                    hits += 1
            except Exception:
                continue
    except Exception as e:
        logger.warning("CoA disconnect sweep failed for %s: %s", uname, e)
    return hits

def _remove_local_cert_files(uname: str) -> tuple[int, Optional[str]]:
    serial = _read_cert_serial(safe_client_path(uname, ".crt"))
    removed = 0
    for suffix in (".key", ".csr", ".crt", ".p12", "-chain.crt"):
        try:
            p = safe_client_path(uname, suffix)
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError:
            pass
    return removed, serial

@app.post("/radius/api/users/{username}/ban", tags=["Users"])
@app.post("/api/users/{username}/ban", tags=["Users"])
def ban_user(username: str, payload: Optional[BanActionRequest] = None, admin_user: str = Depends(authenticate_admin)):
    """Ban an account: immediate RADIUS reject (password untouched)."""
    uname = validate_username(username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (uname,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"User '{uname}' not found.")
            _apply_user_ban(cur, uname, True, admin_user)
            conn.commit()
    finally:
        conn.close()
    kicked = _disconnect_user_sessions(uname) if (payload and payload.disconnect) else 0
    log_audit(admin_user, "user_ban", uname, f"disconnected_nas={kicked}")
    return {"status": "success", "message": f"User '{uname}' banned." + (f" ({kicked} NAS kicked)" if kicked else ""), "banned": True}

@app.post("/radius/api/users/{username}/unban", tags=["Users"])
@app.post("/api/users/{username}/unban", tags=["Users"])
def unban_user(username: str, admin_user: str = Depends(authenticate_admin)):
    """Lift a ban: removes the reject, credentials work again immediately."""
    uname = validate_username(username)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (uname,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"User '{uname}' not found.")
            _apply_user_ban(cur, uname, False, admin_user)
            conn.commit()
    finally:
        conn.close()
    log_audit(admin_user, "user_unban", uname, None)
    return {"status": "success", "message": f"User '{uname}' unbanned.", "banned": False}

@app.post("/radius/api/users/bulk-action", tags=["Users"])
@app.post("/api/users/bulk-action", tags=["Users"])
def bulk_user_action(payload: BulkUserActionRequest, admin_user: str = Depends(authenticate_admin)):
    """One-click action across many users: ban | unban | revoke_certs | delete."""
    action = (payload.action or "").strip().lower()
    if action not in ("ban", "unban", "revoke_certs", "delete"):
        raise HTTPException(status_code=422, detail="action must be one of: ban, unban, revoke_certs, delete.")
    results = []
    for raw in payload.usernames:
        try:
            uname = validate_username(str(raw or "").strip())
        except HTTPException:
            results.append({"username": str(raw), "ok": False, "error": "Invalid username."})
            continue
        try:
            if action in ("ban", "unban"):
                conn = get_db_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (uname,))
                        if not cur.fetchone():
                            raise ValueError(f"User '{uname}' not found.")
                        _apply_user_ban(cur, uname, action == "ban", admin_user)
                        conn.commit()
                finally:
                    conn.close()
                kicked = _disconnect_user_sessions(uname) if payload.disconnect else 0
                log_audit(admin_user, f"user_{action}", uname, f"bulk disconnected_nas={kicked}")
                results.append({"username": uname, "ok": True, "message": f"{action} ok" + (f" ({kicked} NAS kicked)" if kicked else "")})
            elif action == "revoke_certs":
                upstream = revoke_upstream_certificate(uname, reason="cessationOfOperation")
                removed, serial = _remove_local_cert_files(uname)
                try:
                    conn = get_db_connection()
                    with conn.cursor() as cur:
                        record_cert_revocation(cur, uname, serial, "cessationOfOperation", upstream, admin_user)
                        conn.commit()
                    conn.close()
                except Exception as e:
                    logger.debug("revocation ledger unavailable: %s", e)
                log_audit(admin_user, "cert_revoke", uname, f"bulk files_removed={removed}, upstream={upstream.get('method')}:{upstream.get('ok')}")
                results.append({"username": uname, "ok": True, "message": f"revoked upstream + removed {removed} file(s)"})
            else:  # delete
                conn = get_db_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM radcheck WHERE username = %s", (uname,))
                        cur.execute("DELETE FROM radreply WHERE username = %s", (uname,))
                        cur.execute("DELETE FROM radusergroup WHERE username = %s", (uname,))
                        conn.commit()
                    removed, _serial = _remove_local_cert_files(uname)
                    log_audit(admin_user, "user_delete", uname, f"bulk cert_files_removed={removed}")
                    results.append({"username": uname, "ok": True, "message": "deleted"})
                finally:
                    conn.close()
        except HTTPException as e:
            results.append({"username": uname, "ok": False, "error": e.detail})
        except Exception as e:
            results.append({"username": uname, "ok": False, "error": str(e)})
    ok_n = sum(1 for r in results if r["ok"])
    return {"status": "success", "action": action, "succeeded": ok_n, "failed": len(results) - ok_n, "results": results}

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
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (username,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
            # Blank password resets to the user's phone number digits.
            raw_pw = (payload.password or "").strip()
            pw_source = "given"
            if not raw_pw:
                cur.execute("SELECT phone FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                raw_pw = re.sub(r"\D", "", (row.get("phone") if row else "") or "")
                if len(raw_pw) < PASSWORD_MIN_LENGTH:
                    raise HTTPException(status_code=422, detail="No usable phone number on file — type an explicit password (min 8 characters).")
                pw_source = "phone"
            validate_password_policy(raw_pw, username)
            cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (username,))
            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Cleartext-Password', ':=', %s)
            """, (username, raw_pw))
            sync_central_password(cur, username, raw_pw)
            conn.commit()
    finally:
        conn.close()
    # Audit (never logs the plaintext password)
    info = password_strength(raw_pw)
    log_audit(admin_user, "password_reset", username, f"source={pw_source} strength={info['strength']}")
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
        "message": f"Password updated for user '{username}'"
                   + (" (password = phone number)" if pw_source == "phone" else "")
                   + (f" ({disconnected} session(s) disconnected)" if payload.disconnect_active else ""),
        "username": username,
        "password": raw_pw if pw_source == "phone" else None,
        "password_source": pw_source,
        "updated_by": admin_user,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "disconnected_sessions": disconnected,
    }

@app.get("/radius/api/audit", tags=["Users"])
@app.get("/api/audit", tags=["Users"])
@app.get("/radius/api/audit-logs", tags=["Users"])
@app.get("/api/audit-logs", tags=["Users"])
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
        probe_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            **headers
        }
        req = urllib.request.Request(url, headers=probe_headers, method="GET")
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
    """Unauthenticated client facts: RADIUS host/ports, portal path, signer presence, admin contact, upi settings."""
    host = RADIUS_PUBLIC_HOST or (request.headers.get("host", "").split(":")[0] if request.headers.get("host") else "")
    
    phone = ADMIN_CONTACT_PHONE
    name = ADMIN_CONTACT_NAME
    upi_vpa = "wifi@rajlabs"
    upi_merchant = "RajLabs Enterprise WiFi"
    currency = "INR"
    wifi_ssid = "RajLabs-Enterprise"
    wifi_auth_type = "WPA2-Enterprise / EAP-TLS"

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM system_settings WHERE key IN ('admin_contact_phone', 'admin_contact_name', 'upi_vpa', 'upi_merchant_name', 'currency', 'wifi_ssid', 'wifi_auth_type')")
            rows = cur.fetchall()
            settings_dict = {r["key"]: r["value"] for r in rows}
            phone = settings_dict.get("admin_contact_phone") or phone
            name = settings_dict.get("admin_contact_name") or name
            upi_vpa = settings_dict.get("upi_vpa") or upi_vpa
            upi_merchant = settings_dict.get("upi_merchant_name") or upi_merchant
            currency = settings_dict.get("currency") or currency
            wifi_ssid = settings_dict.get("wifi_ssid") or wifi_ssid
            wifi_auth_type = settings_dict.get("wifi_auth_type") or wifi_auth_type
        conn.close()
    except Exception:
        pass

    signer_url, _ = get_cert_signer_config()
    return {
        "radius_host": host,
        "radius_ports": {"auth": 1812, "acct": 1813, "coa": 3799},
        "portal_path": "/radius/portal",
        "wifi_ssid": wifi_ssid,
        "wifi_auth_type": wifi_auth_type,
        "eap": _eap_server_info(),
        "signer_configured": bool(signer_url),
        "admin_contact": {
            "phone": phone,
            "name": name
        },
        "payment_config": {
            "upi_vpa": upi_vpa,
            "merchant_name": upi_merchant,
            "currency": currency
        }
    }

# ============================================================================
# Dynamic System Settings (Admin Configurable Contact, UPI, Currency, WiFi)
# ============================================================================
@app.get("/radius/api/settings", tags=["Settings"])
@app.get("/api/settings", tags=["Settings"])
def get_all_settings(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value, description, updated_at FROM system_settings ORDER BY key ASC")
            rows = cur.fetchall()
            settings_map = {r["key"]: r["value"] for r in rows}
            
            # Populate fallbacks if not explicitly set
            if "admin_contact_phone" not in settings_map:
                settings_map["admin_contact_phone"] = ADMIN_CONTACT_PHONE
            if "admin_contact_name" not in settings_map:
                settings_map["admin_contact_name"] = ADMIN_CONTACT_NAME
            if "cert_signer_api_url" not in settings_map:
                settings_map["cert_signer_api_url"] = CERT_SIGNER_API_URL
            if "cert_signer_api_key" not in settings_map:
                settings_map["cert_signer_api_key"] = CERT_SIGNER_API_KEY
            if "wifi_ssid" not in settings_map:
                settings_map["wifi_ssid"] = "RajLabs-Enterprise"
            if "wifi_auth_type" not in settings_map:
                settings_map["wifi_auth_type"] = "WPA2-Enterprise / EAP-TLS"

            return {
                "settings": settings_map,
                "records": rows
            }
    finally:
        conn.close()

@app.post("/radius/api/settings", tags=["Settings"])
@app.post("/api/settings", tags=["Settings"])
def update_settings(payload: SystemSettingsUpdateRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if payload.admin_contact_phone is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('admin_contact_phone', %s, 'Administrator contact phone / WhatsApp number', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.admin_contact_phone.strip(),))
            if payload.admin_contact_name is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('admin_contact_name', %s, 'Administrator contact display name', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.admin_contact_name.strip(),))
            if payload.upi_vpa is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('upi_vpa', %s, 'Active UPI Virtual Payment Address (VPA)', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.upi_vpa.strip(),))
            if payload.upi_merchant_name is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('upi_merchant_name', %s, 'Merchant display name for UPI payments', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.upi_merchant_name.strip(),))
            if payload.default_voucher_code is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('default_voucher_code', %s, 'Default promotional voucher code for onboarding', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.default_voucher_code.strip(),))
            if payload.currency is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('currency', %s, 'Default system currency code', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.currency.strip().upper(),))
            if payload.cert_signer_api_url is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('cert_signer_api_url', %s, 'Central Rajlabs-CA Cert-Signer API Base URL', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                    """, (payload.cert_signer_api_url.strip().rstrip("/"),))
            if payload.cert_signer_api_key is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('cert_signer_api_key', %s, 'Central Rajlabs-CA Cert-Signer API Key / Token', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.cert_signer_api_key.strip(),))
            if payload.wifi_ssid is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('wifi_ssid', %s, 'Broadcast Wi-Fi SSID Network Name', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.wifi_ssid.strip(),))
            if payload.wifi_auth_type is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('wifi_auth_type', %s, 'Default Wi-Fi Authentication Security Type', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.wifi_auth_type.strip(),))
            if payload.payment_active_gateway is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('payment_active_gateway', %s, 'Active Payment Gateway Mode', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.payment_active_gateway.strip(),))
            if payload.razorpay_key_id is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('razorpay_key_id', %s, 'Razorpay API Key ID', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.razorpay_key_id.strip(),))
            if payload.razorpay_key_secret is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('razorpay_key_secret', %s, 'Razorpay API Key Secret', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.razorpay_key_secret.strip(),))
            if payload.razorpay_webhook_secret is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('razorpay_webhook_secret', %s, 'Razorpay Webhook Secret', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.razorpay_webhook_secret.strip(),))
            if payload.cashfree_app_id is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('cashfree_app_id', %s, 'Cashfree App ID', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.cashfree_app_id.strip(),))
            if payload.cashfree_secret_key is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('cashfree_secret_key', %s, 'Cashfree Secret Key', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.cashfree_secret_key.strip(),))
            if payload.cashfree_env is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('cashfree_env', %s, 'Cashfree Environment (TEST/PROD)', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.cashfree_env.strip().upper(),))
            if payload.payu_merchant_key is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('payu_merchant_key', %s, 'PayU Merchant Key', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.payu_merchant_key.strip(),))
            if payload.payu_merchant_salt is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('payu_merchant_salt', %s, 'PayU Merchant Salt', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.payu_merchant_salt.strip(),))
            if payload.email_imap_host is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('email_imap_host', %s, 'Email IMAP Host for Bank Note Reconciliation', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.email_imap_host.strip(),))
            if payload.email_imap_port is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('email_imap_port', %s, 'Email IMAP Port', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (str(payload.email_imap_port),))
            if payload.email_imap_user is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('email_imap_user', %s, 'Email IMAP Username/Address', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.email_imap_user.strip(),))
            if payload.email_imap_password is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('email_imap_password', %s, 'Email IMAP Password / App Password', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.email_imap_password.strip(),))
            if payload.email_imap_folder is not None:
                cur.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES ('email_imap_folder', %s, 'Email IMAP Folder', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """, (payload.email_imap_folder.strip(),))
            conn.commit()


        # Invalidate signer probe cache on settings update
        _SIGNER_STATUS_CACHE.update({"at": 0.0, "data": None})
        log_audit(current_admin, "SETTINGS_UPDATED", "system",
                  f"Updated system settings: {_redacted_settings(payload.dict(exclude_unset=True))}")
        return {"status": "success", "message": "System settings updated successfully!"}
    finally:
        conn.close()

_SENSITIVE_SETTING_KEYS = ("password", "secret", "salt", "api_key", "apikey", "token", "private")

def _redacted_settings(data: dict) -> dict:
    """Audit-safe settings snapshot: secret values replaced, key names kept."""
    out = {}
    for k, v in (data or {}).items():
        kl = str(k).lower()
        if any(s in kl for s in _SENSITIVE_SETTING_KEYS) and v not in (None, ""):
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out

# ============================================================================
# Wi-Fi Plans & Pricing Management
# ============================================================================
def ensure_plans_table():
    """Deprecated shim — schema + seeds owned by api/migrations/001_baseline.sql.

    No legacy price rewrites: this project has no legacy system, plans are
    seeded once as ₹10 / ₹30 / ₹51.35 and edited only via the Plans API.
    """
    try:
        from api.migrate import ensure_migrated
        ensure_migrated()
    except Exception as e:
        logger.debug("Could not ensure plans table: %s", e)

def _normalize_group_list(groups) -> List[str]:
    """Clean RADIUS group names for plan access lists (dedup, case-preserved)."""
    seen = []
    for g in groups or []:
        name = str(g or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen

def _plan_access_map(cur) -> Dict[int, List[str]]:
    """plan_id -> allowed RADIUS groupnames. Missing table = all unrestricted."""
    try:
        cur.execute("SELECT plan_id, groupname FROM plan_group_access ORDER BY groupname ASC")
        m: Dict[int, List[str]] = {}
        for r in cur.fetchall():
            m.setdefault(r["plan_id"], []).append(r["groupname"])
        return m
    except Exception:
        return {}

def _set_plan_groups(cur, plan_id: int, groups) -> List[str]:
    """Replace a plan's group restriction list. Returns the stored list."""
    clean = _normalize_group_list(groups)
    try:
        cur.execute("DELETE FROM plan_group_access WHERE plan_id = %s", (plan_id,))
        for g in clean:
            cur.execute(
                "INSERT INTO plan_group_access (plan_id, groupname) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (plan_id, g),
            )
    except Exception as e:
        logger.debug("plan_group_access write skipped for plan %s: %s", plan_id, e)
        return []
    return clean

def check_plan_group_access(plan_id: Optional[int], user_group: Optional[str], cur) -> tuple[bool, List[str]]:
    """Is this plan buyable by a user in `user_group`?

    No restriction rows → everyone allowed. Comparison is case-insensitive;
    a missing group (None) only passes unrestricted plans.
    """
    if plan_id is None:
        return True, []
    allowed = _plan_access_map(cur).get(plan_id, [])
    if not allowed:
        return True, []
    if user_group and any(user_group.strip().lower() == a.lower() for a in allowed):
        return True, allowed
    return False, allowed

@app.get("/radius/api/plans", tags=["Plans & Pricing"])
@app.get("/api/plans", tags=["Plans & Pricing"])
def list_plans():
    """Publicly accessible list of active Wi-Fi plans & prices."""
    ensure_plans_table()
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, price, currency, validity_days, validity_seconds, max_session_seconds, description, created_at FROM plans ORDER BY price ASC, validity_days ASC")
            rows = cur.fetchall()
            access = _plan_access_map(cur)
            out = []
            for r in rows:
                out.append({
                    "id": r["id"],
                    "name": r["name"],
                    "price": float(r["price"]),
                    "currency": r.get("currency") or "INR",
                    "validity_days": r["validity_days"],
                    "validity_seconds": r["validity_seconds"],
                    "max_session_seconds": r["max_session_seconds"],
                    "description": r["description"] or "",
                    "allowed_groups": access.get(r["id"], [])
                })
            conn.close()
            return out
    except Exception:
        # Fallback default plans in case DB offline (unrestricted)
        return [
            {"id": 1, "name": "1 Day Daily Pass", "price": 10.0, "currency": "INR", "validity_days": 1, "validity_seconds": 86400, "max_session_seconds": 86400, "description": "Emergency 24-hour unlimited high-speed access (₹10/day)", "allowed_groups": []},
            {"id": 2, "name": "7 Days Weekly Pass", "price": 30.0, "currency": "INR", "validity_days": 7, "validity_seconds": 604800, "max_session_seconds": 86400, "description": "7 Days high-speed broadband access (₹4.28/day — Save 57% vs Daily)", "allowed_groups": []},
            {"id": 3, "name": "30 Days Monthly Unlimited", "price": 51.35, "currency": "INR", "validity_days": 30, "validity_seconds": 2592000, "max_session_seconds": 86400, "description": "Best Value! Full 30 days unlimited Wi-Fi at ₹1.71/day (₹50 base + 2.7% PG gateway fee)", "allowed_groups": []}
        ]

@app.post("/radius/api/plans", tags=["Plans & Pricing"])
@app.post("/api/plans", tags=["Plans & Pricing"])
def create_or_update_plan(payload: PlanCreateRequest, admin_user: str = Depends(authenticate_admin)):
    ensure_plans_table()
    validity_secs = payload.validity_days * 86400
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if payload.id:
                cur.execute("""
                    UPDATE plans 
                    SET name = %s, price = %s, currency = %s, validity_days = %s, validity_seconds = %s, max_session_seconds = %s, description = %s
                    WHERE id = %s
                """, (payload.name.strip(), payload.price, (payload.currency or "INR").upper(), payload.validity_days, validity_secs, payload.max_session_seconds or 86400, payload.description or "", payload.id))
                plan_id = payload.id
                action = "plan_update"
            else:
                cur.execute("""
                    INSERT INTO plans (name, price, currency, validity_days, validity_seconds, max_session_seconds, description)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (payload.name.strip(), payload.price, (payload.currency or "INR").upper(), payload.validity_days, validity_secs, payload.max_session_seconds or 86400, payload.description or ""))
                plan_id = cur.fetchone()["id"]
                action = "plan_create"
            stored_groups = None
            if payload.allowed_groups is not None:
                stored_groups = _set_plan_groups(cur, plan_id, payload.allowed_groups)
            conn.commit()
            scope = f"groups={','.join(stored_groups)}" if stored_groups is not None else "groups=unchanged"
            log_audit(admin_user, action, payload.name, f"price={payload.price} validity_days={payload.validity_days} {scope}")
            return {"status": "success", "message": f"Plan '{payload.name}' saved successfully!", "plan_id": plan_id, "allowed_groups": stored_groups if stored_groups is not None else []}
    finally:
        conn.close()

@app.delete("/radius/api/plans/{plan_id}", tags=["Plans & Pricing"])
@app.delete("/api/plans/{plan_id}", tags=["Plans & Pricing"])
def delete_plan(plan_id: int, admin_user: str = Depends(authenticate_admin)):
    ensure_plans_table()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id = %s RETURNING name", (plan_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Plan not found")
            conn.commit()
            return {"status": "success", "message": f"Plan '{row['name']}' deleted successfully"}
    finally:
        conn.close()

class SubscriptionRevokeRequest(BaseModel):
    reason: Optional[str] = None
    disconnect: Optional[bool] = True

@app.post("/radius/api/subscriptions/{subscription_id}/revoke", tags=["Payments"])
@app.post("/api/subscriptions/{subscription_id}/revoke", tags=["Payments"])
def revoke_subscription_endpoint(subscription_id: int, payload: Optional[SubscriptionRevokeRequest] = None, admin_user: str = Depends(authenticate_admin)):
    """Admin revoke: cancel an ACTIVE subscription immediately (RADIUS re-synced, sessions kicked)."""
    from api.entitlements import revoke_subscription
    try:
        res = revoke_subscription(
            subscription_id,
            actor=admin_user,
            reason=(payload.reason.strip()[:200] if payload and payload.reason else ""),
            disconnect=bool(payload.disconnect) if payload else True,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    log_audit(admin_user, "SUBSCRIPTION_REVOKED", res.get("username"), f"sub_id={subscription_id} reason={(payload.reason if payload else '') or '-'}")
    return res


# ============================================================================
# Payments, Gateways & Email Reconciliation Management
# ============================================================================
@app.get("/radius/api/payments", tags=["Payments"])
@app.get("/api/payments", tags=["Payments"])
def list_payments(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = None,
    gateway_filter: Optional[str] = None,
    query: Optional[str] = None,
    _: str = Depends(authenticate_admin)
):
    """List payment transactions with associated user, plan, gateway, and financial analytics."""
    from api.migrate import ensure_migrated
    ensure_migrated()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            where_clauses = ["1=1"]
            params = []
            if status_filter:
                where_clauses.append("p.status = %s")
                params.append(status_filter.upper())
            if gateway_filter:
                where_clauses.append("p.gateway ILIKE %s")
                params.append(f"%{gateway_filter}%")
            if query:
                where_clauses.append("(u.username ILIKE %s OR p.gateway_payment_id ILIKE %s OR p.gateway_order_id ILIKE %s OR p.raw_reference ILIKE %s)")
                q = f"%{query.strip()}%"
                params.extend([q, q, q, q])

            where_str = " AND ".join(where_clauses)

            # 1. Total counts
            cur.execute(f"""
                SELECT COUNT(*) as count 
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.id
                WHERE {where_str}
            """, tuple(params))
            total_count = cur.fetchone()["count"]

            # 2. Paginated rows
            cur.execute(f"""
                SELECT 
                    p.id, p.user_id, COALESCE(u.username, 'Unknown User') as username,
                    p.plan_id, COALESCE(pl.name, 'Custom Pass') as plan_name,
                    p.gateway, p.gateway_order_id, p.gateway_payment_id,
                    p.amount, p.currency, p.status, p.verified_at,
                    p.raw_reference, p.created_at,
                    s.id as subscription_id, s.status as subscription_status, s.expires_at as subscription_expires_at
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.id
                LEFT JOIN plans pl ON p.plan_id = pl.id
                LEFT JOIN subscriptions s ON s.payment_id = p.id
                WHERE {where_str}
                ORDER BY p.created_at DESC
                LIMIT %s OFFSET %s
            """, tuple(params + [limit, offset]))
            payments_rows = cur.fetchall()

            # 3. Aggregated financial metrics
            cur.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN status = 'SUCCESS' THEN amount ELSE 0 END), 0) as total_revenue,
                    COUNT(CASE WHEN status = 'SUCCESS' THEN 1 END) as successful_count,
                    COUNT(CASE WHEN status = 'PENDING' THEN 1 END) as pending_count,
                    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_count
                FROM payments
            """)
            stats_row = cur.fetchone()

            # 4. Gateway distribution
            cur.execute("""
                SELECT gateway, COUNT(*) as count, COALESCE(SUM(amount), 0) as total_amount
                FROM payments
                WHERE status = 'SUCCESS'
                GROUP BY gateway
            """)
            gateway_stats = cur.fetchall()

            return {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "metrics": {
                    "total_revenue": float(stats_row["total_revenue"]),
                    "successful_count": stats_row["successful_count"],
                    "pending_count": stats_row["pending_count"],
                    "failed_count": stats_row["failed_count"],
                    "gateway_distribution": gateway_stats
                },
                "payments": payments_rows
            }
    finally:
        conn.close()


@app.post("/radius/api/payments/manual-activate", tags=["Payments"])
@app.post("/api/payments/manual-activate", tags=["Payments"])
def manual_activate_payment(payload: ManualPaymentActivateRequest, admin_user: str = Depends(authenticate_admin)):
    """1-Click manual top-up & plan activation via UTR, Note, or Cash collection."""
    from api.migrate import ensure_migrated
    from api.entitlements import process_verified_payment
    ensure_migrated()

    uname = validate_username((payload.username or "").strip())
    # Normalize + validate validity_days (default 30, cap 1..3650)
    validity_days = payload.validity_days if payload.validity_days and payload.validity_days > 0 else 30
    validity_days = max(1, min(int(validity_days), 3650))
    # Normalize UTR / note (DB columns are VARCHAR(128))
    raw_utr = (payload.utr or "").strip().replace(" ", "")
    payment_ref = raw_utr[:128] if raw_utr else f"MANUAL-{uname}-{int(time.time())}"
    note_text = (payload.note or "").strip()[:128]
    gateway_name = (payload.gateway or "MANUAL_ADMIN").strip()[:64] or "MANUAL_ADMIN"

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Validate plan_id up-front to avoid FK violation (payments.plan_id -> plans.id)
            effective_plan_id = payload.plan_id
            if effective_plan_id is not None:
                cur.execute("SELECT id FROM plans WHERE id = %s LIMIT 1", (effective_plan_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail=f"Plan ID {effective_plan_id} not found.")
            # Check or auto-provision in users table
            cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (uname,))
            u_row = cur.fetchone()
            if not u_row:
                cur.execute("""
                    INSERT INTO users (username, password_cleartext, status)
                    VALUES (%s, %s, 'ACTIVE')
                    RETURNING id
                """, (uname, generate_session_secret(24)))
                user_id = cur.fetchone()["id"]
            else:
                user_id = u_row["id"]

            # Also ensure user has at least a default radcheck record
            cur.execute("SELECT id FROM radcheck WHERE username = %s LIMIT 1", (uname,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Cleartext-Password', ':=', %s)
                """, (uname, generate_session_secret(16)))

            # Group-restriction check: admins may override, but the override
            # is surfaced (not silent) so VIP-only plans don't leak quietly.
            group_warning = None
            cur.execute("SELECT groupname FROM radusergroup WHERE username = %s LIMIT 1", (uname,))
            grp_row = cur.fetchone()
            user_group = grp_row["groupname"] if grp_row else None
            ok, allowed = check_plan_group_access(effective_plan_id, user_group, cur)
            if not ok:
                group_warning = (
                    f"Plan is restricted to group(s) {', '.join(allowed)}; "
                    f"user '{uname}' is in '{user_group or 'no group'}' — applied as admin override."
                )

            conn.commit()

        validity_secs = validity_days * 86400

        result = process_verified_payment(
            gateway=gateway_name,
            gateway_payment_id=payment_ref,
            gateway_order_id=note_text or f"Manual activation by {admin_user}",
            user_id=user_id,
            plan_id=effective_plan_id,
            amount=payload.amount,
            currency="INR",
            custom_validity_seconds=validity_secs,
            raw_reference=f"Manual Admin Top-up by {admin_user}: note={note_text}",
            actor_type="ADMIN",
            ip="127.0.0.1"
        )
        log_audit(admin_user, "MANUAL_PAYMENT_ACTIVATED", uname, f"amount={payload.amount} ref={payment_ref} plan_id={effective_plan_id} validity_days={validity_days}" + (f" OVERRIDE:{group_warning}" if group_warning else ""))
        if result.get("status") == "duplicate_acknowledged":
            return {
                "status": "success",
                "message": f"Payment '{payment_ref}' was already processed for user '{uname}' (idempotent replay).",
                "details": result,
                "group_warning": group_warning
            }
        return {
            "status": "success",
            "message": f"Plan successfully activated for user '{uname}' (Ref: {payment_ref})",
            "details": result,
            "group_warning": group_warning
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/radius/api/payments/email/test", tags=["Payments"])
@app.post("/api/payments/email/test", tags=["Payments"])
def test_email_imap(payload: GatewayTestRequest, _: str = Depends(authenticate_admin)):
    """Test IMAP connection to Gmail / Bank mail server."""
    from api.payment_engine import test_imap_connection
    host = payload.imap_host
    port = payload.imap_port or 993
    user = payload.imap_user
    pwd = payload.imap_password

    # If not passed in body, lookup from DB
    if not (host and user and pwd):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM system_settings WHERE key IN ('email_imap_host', 'email_imap_port', 'email_imap_user', 'email_imap_password')")
                smap = {r["key"]: r["value"] for r in cur.fetchall()}
                host = host or smap.get("email_imap_host")
                port = port or int(smap.get("email_imap_port", 993))
                user = user or smap.get("email_imap_user")
                pwd = pwd or smap.get("email_imap_password")
        finally:
            conn.close()

    res = test_imap_connection(host, port, user, pwd)
    return res


@app.post("/radius/api/payments/email/scan", tags=["Payments"])
@app.post("/api/payments/email/scan", tags=["Payments"])
def scan_email_payments(payload: EmailScanRequest, admin_user: str = Depends(authenticate_admin)):
    """Scan IMAP mailbox for bank alert emails, parse UPI notes/UTRs, and auto-activate plans."""
    from api.payment_engine import scan_bank_emails_for_payments
    from api.entitlements import process_verified_payment
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM system_settings WHERE key IN ('email_imap_host', 'email_imap_port', 'email_imap_user', 'email_imap_password', 'email_imap_folder')")
            smap = {r["key"]: r["value"] for r in cur.fetchall()}
            host = smap.get("email_imap_host")
            port = int(smap.get("email_imap_port", 993))
            user = smap.get("email_imap_user")
            pwd = smap.get("email_imap_password")
            folder = payload.folder or smap.get("email_imap_folder", "INBOX")
    finally:
        conn.close()

    if not (host and user and pwd):
        raise HTTPException(status_code=400, detail="IMAP settings not configured. Please set Gmail/IMAP host, username, and app password in Settings.")

    scan_res = scan_bank_emails_for_payments(host, port, user, pwd, folder=folder, limit=payload.limit or 30)
    if not scan_res.get("success"):
        raise HTTPException(status_code=500, detail=scan_res.get("error", "Email scan failed"))

    processed_list = []
    if payload.auto_activate:
        for item in scan_res.get("transactions", []):
            if item.get("matched") and item.get("utr") and item.get("username"):
                uname = item["username"]
                utr = item["utr"]
                amt = item.get("amount") or 0.0
                plan_id = item.get("plan_id")
                invoice = item.get("invoice")
                
                try:
                    c = get_db_connection()
                    with c.cursor() as cur:
                        cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (uname,))
                        u_row = cur.fetchone()
                        if not u_row:
                            cur.execute("INSERT INTO users (username, password_cleartext, status) VALUES (%s, %s, 'ACTIVE') RETURNING id", (uname, generate_session_secret(24)))
                            uid = cur.fetchone()["id"]
                        else:
                            uid = u_row["id"]
                        
                        # Match plan by price if plan_id not in note
                        if not plan_id and amt > 0:
                            cur.execute("SELECT id FROM plans WHERE price = %s LIMIT 1", (amt,))
                            pl = cur.fetchone()
                            if pl:
                                plan_id = pl["id"]
                        # Strict group check: auto-activation never overrides a
                        # group-restricted plan (unlike the admin 1-click flow).
                        cur.execute("SELECT groupname FROM radusergroup WHERE username = %s LIMIT 1", (uname,))
                        grow = cur.fetchone()
                        user_group = grow["groupname"] if grow else None
                        grp_ok, grp_allowed = check_plan_group_access(plan_id, user_group, cur)
                        c.commit()
                        if not grp_ok:
                            processed_list.append({
                                "utr": utr,
                                "username": uname,
                                "amount": amt,
                                "status": "skipped_group_restriction",
                                "reason": f"Plan restricted to {', '.join(grp_allowed)}; user in '{user_group or 'no group'}'"
                            })
                            logger.info("Skipped email auto-activation utr=%s user=%s: group-restricted plan", utr, uname)
                    c.close()

                    if not grp_ok:
                        continue

                    p_res = process_verified_payment(
                        gateway="EMAIL_IMAP",
                        gateway_payment_id=f"UTR-{utr}",
                        gateway_order_id=(f"WIFI:{uname}:{invoice}:{plan_id}" if invoice else f"Note: {uname}"),
                        user_id=uid,
                        plan_id=plan_id,
                        amount=amt,
                        currency="INR",
                        raw_reference=f"Parsed from: {item.get('from', '')} | Subject: {item.get('subject', '')} | invoice={invoice or '-'}",
                        actor_type="WEBHOOK",
                        ip="127.0.0.1"
                    )
                    processed_list.append({
                        "utr": utr,
                        "username": uname,
                        "amount": amt,
                        "invoice": invoice,
                        "status": p_res.get("status")
                    })
                except Exception as e:
                    logger.warning("Failed to auto-process email payment for utr=%s user=%s: %s", utr, uname, e)

    log_audit(admin_user, "EMAIL_PAYMENTS_SCANNED", "system", f"scanned={scan_res.get('scanned_count')} matched={scan_res.get('matched_count')} auto_activated={len(processed_list)}")
    return {
        "status": "success",
        "scan_summary": scan_res,
        "auto_processed": processed_list
    }


@app.post("/radius/api/payments/gateway/test", tags=["Payments"])
@app.post("/api/payments/gateway/test", tags=["Payments"])
def test_payment_gateway(payload: GatewayTestRequest, _: str = Depends(authenticate_admin)):
    """Test Razorpay or Cashfree API credentials."""
    from api.payment_engine import create_razorpay_order, create_cashfree_order
    gw = payload.gateway.lower()

    if gw in ("razorpay", "razor_pay"):
        key_id = payload.key_id
        key_secret = payload.key_secret
        if not (key_id and key_secret):
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT key, value FROM system_settings WHERE key IN ('razorpay_key_id', 'razorpay_key_secret')")
                    smap = {r["key"]: r["value"] for r in cur.fetchall()}
                    key_id = key_id or smap.get("razorpay_key_id")
                    key_secret = key_secret or smap.get("razorpay_key_secret")
            finally:
                conn.close()

        if not (key_id and key_secret):
            return {"ok": False, "error": "Razorpay Key ID and Secret Key are required."}

        res = create_razorpay_order(key_id, key_secret, amount_inr=1.0, receipt=f"test_{int(time.time())}", notes={"test": "probe"})
        if "id" in res:
            return {"ok": True, "message": "Successfully connected and verified Razorpay API keys!", "order_id": res["id"]}
        return {"ok": False, "error": res.get("error", "Failed to verify Razorpay keys")}

    elif gw in ("cashfree", "cash_free"):
        app_id = payload.app_id
        secret = payload.secret_key
        c_env = payload.env or "TEST"
        if not (app_id and secret):
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT key, value FROM system_settings WHERE key IN ('cashfree_app_id', 'cashfree_secret_key', 'cashfree_env')")
                    smap = {r["key"]: r["value"] for r in cur.fetchall()}
                    app_id = app_id or smap.get("cashfree_app_id")
                    secret = secret or smap.get("cashfree_secret_key")
                    c_env = smap.get("cashfree_env", c_env)
            finally:
                conn.close()

        if not (app_id and secret):
            return {"ok": False, "error": "Cashfree App ID and Secret Key are required."}

        res = create_cashfree_order(app_id, secret, order_id=f"test_{int(time.time())}", amount_inr=1.0, customer_id="test_probe", env=c_env)
        if "order_id" in res or "payment_session_id" in res:
            return {"ok": True, "message": "Successfully connected and verified Cashfree credentials!", "order": res}
        return {"ok": False, "error": res.get("error", "Failed to verify Cashfree keys")}

    return {"ok": False, "error": f"Unknown gateway type: {payload.gateway}"}


# ----------------------------------------------------------------------------
# Webhooks for Payment Gateways
# ----------------------------------------------------------------------------
@app.post("/radius/api/webhooks/razorpay", tags=["Payments"])
@app.post("/api/webhooks/razorpay", tags=["Payments"])
async def razorpay_webhook(request: Request):
    """Handle incoming Razorpay payment webhooks."""
    from api.entitlements import process_verified_payment
    from api.payment_engine import verify_razorpay_signature

    body_bytes = await request.body()
    sig = request.headers.get("x-razorpay-signature", "")
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = 'razorpay_webhook_secret' LIMIT 1")
            row = cur.fetchone()
            sec = row["value"] if row else ""
    finally:
        conn.close()

    try:
        event = json.loads(body_bytes.decode())
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    if sec and sig:
        expected = hmac.new(sec.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return JSONResponse(status_code=401, content={"error": "Invalid webhook signature"})

    event_type = event.get("event")
    if event_type == "payment.captured":
        pay_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        pay_id = pay_entity.get("id")
        order_id = pay_entity.get("order_id")
        amount = float(pay_entity.get("amount", 0)) / 100.0
        notes = pay_entity.get("notes", {})
        username = notes.get("username")
        plan_id = int(notes.get("plan_id")) if notes.get("plan_id") else None

        if username and pay_id:
            c = get_db_connection()
            with c.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (username,))
                u_row = cur.fetchone()
                uid = u_row["id"] if u_row else None
                if not uid:
                    cur.execute("INSERT INTO users (username, password_cleartext, status) VALUES (%s, %s, 'ACTIVE') RETURNING id", (username, generate_session_secret(24)))
                    uid = cur.fetchone()["id"]
                c.commit()
            c.close()

            process_verified_payment(
                gateway="RAZORPAY",
                gateway_payment_id=pay_id,
                gateway_order_id=order_id,
                user_id=uid,
                plan_id=plan_id,
                amount=amount,
                currency="INR",
                raw_reference=json.dumps(pay_entity),
                actor_type="WEBHOOK",
                ip=request.client.host if request.client else "127.0.0.1"
            )

    return {"status": "ok"}



@app.get("/radius/api/certs/signer-status", tags=["Certificates"])
@app.get("/api/certs/signer-status", tags=["Certificates"])
@app.get("/radius/api/signer/status", tags=["Certificates"])
@app.get("/api/signer/status", tags=["Certificates"])
def cert_signer_status(refresh: bool = False, _: str = Depends(authenticate_admin)):
    """Live Cert-Signer health: reachability + API-key validity. Key value never returned."""
    from urllib.parse import urlparse
    from datetime import datetime, timezone
    now = time.time()
    if not refresh and _SIGNER_STATUS_CACHE["data"] and now - _SIGNER_STATUS_CACHE["at"] < 30:
        return _SIGNER_STATUS_CACHE["data"]

    checked_at = datetime.now(timezone.utc).isoformat()
    signer_url, signer_key = get_cert_signer_config()

    if not signer_url:
        data = {
            "configured": False, "mode": "local", "reachable": True, "key_valid": None,
            "status_code": None, "latency_ms": None, "host": None, "checked_at": checked_at,
            "detail": "CERT_SIGNER_API_URL is not set — certificates are signed by the local FreeRADIUS CA. Set URL & API Key in Settings or environment to use central Rajlabs-CA.",
        }
        _SIGNER_STATUS_CACHE.update({"at": now, "data": data})
        return data

    host = urlparse(signer_url).hostname or signer_url
    headers = {"Accept": "application/json"}
    if signer_key:
        headers["x-api-key"] = signer_key
        headers["X-API-KEY"] = signer_key
        headers["Authorization"] = f"Bearer {signer_key}"

    # Probe 1: Endpoint Status & Health probe
    probe = None
    for path in ("/api/v1/status", "/health", "/api/v1/health", "/api/v1/tokens/verify", ""):
        r = _probe_http_json(signer_url + path, headers)
        if r["ok"]:
            probe = r
            break
        elif r["status"] in (401, 403):
            probe = r
            break
        probe = r

    assert probe is not None
    if probe["ok"]:
        if signer_key:
            detail_msg = f"Connected & authenticated with Cert-Signer at {host} ({probe['latency_ms']} ms). API token is valid."
            key_valid = True
        else:
            detail_msg = f"Connected to Cert-Signer at {host} ({probe['latency_ms']} ms), but API token is missing. Sign requests may require an API key."
            key_valid = False

        data = {
            "configured": True, "mode": "remote" if key_valid else "remote-unauthenticated", "reachable": True,
            "key_valid": key_valid,
            "token_missing": not bool(signer_key),
            "status_code": probe["status"], "latency_ms": probe["latency_ms"],
            "host": host, "checked_at": checked_at,
            "detail": detail_msg,
        }
    elif probe["status"] in (401, 403):
        data = {
            "configured": True, "mode": "local-fallback", "reachable": True,
            "key_valid": False,
            "token_missing": not bool(signer_key),
            "status_code": probe["status"],
            "latency_ms": probe["latency_ms"], "host": host, "checked_at": checked_at,
            "detail": f"Signer at {host} is reachable but rejected our API key (HTTP {probe['status']}). Verify your token in Settings. Falling back to local CA.",
        }
    else:
        data = {
            "configured": True, "mode": "local-fallback", "reachable": False,
            "key_valid": None,
            "token_missing": not bool(signer_key),
            "status_code": probe["status"],
            "latency_ms": probe["latency_ms"], "host": host, "checked_at": checked_at,
            "detail": f"Cannot reach Cert-Signer at {host}: {probe['body'][:160]}. Certificates will fall back to the local CA. Check URL and network connectivity.",
        }
    logger.info("Signer status checked by=%s reachable=%s mode=%s host=%s key_valid=%s", _, data["reachable"], data["mode"], host, data["key_valid"])
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
                    "recharge_required": (g != "admins"),
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
                    groups_map[g]["recharge_required"] = False
                elif attr == "RajLabs-Recharge-Exempt" and val == "1":
                    groups_map[g]["recharge_required"] = False
                elif attr == "RajLabs-Require-Device-Lock" and val == "1":
                    groups_map[g]["require_device_verification"] = True

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
def create_or_update_group(payload: GroupCreateRequest, admin_user: str = Depends(authenticate_admin)):
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

            # 2. Administrative Role, Recharge Exemption & Device Lock
            if payload.is_admin or payload.groupname == "admins":
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Service-Type', '=', 'Administrative-User')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'RajLabs-Recharge-Exempt', '=', '1')", (payload.groupname,))
            elif payload.recharge_required is False:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'RajLabs-Recharge-Exempt', '=', '1')", (payload.groupname,))

            if payload.require_device_verification:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'RajLabs-Require-Device-Lock', '=', '1')", (payload.groupname,))


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
            eff_rate_limit = payload.mikrotik_rate_limit or payload.rate_limit
            if eff_rate_limit and eff_rate_limit.strip():
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Mikrotik-Rate-Limit', '=', %s)", (payload.groupname, eff_rate_limit.strip()))

            # 7. 802.1Q VLAN Dynamic Tagging
            vlan_num = None
            if payload.vlan_id is not None and str(payload.vlan_id).strip():
                try:
                    vlan_num = int(str(payload.vlan_id).strip())
                except ValueError:
                    pass
            if vlan_num is not None and vlan_num > 0:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Type', '=', '13')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Medium-Type', '=', '6')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Private-Group-ID', '=', %s)", (payload.groupname, str(vlan_num)))

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

            # Mirror into the central groups table: the access-decision engine
            # reads groups.recharge_required (not radgroupreply), so without
            # this the Groups UI "exempt" flag never took effect at RADIUS time.
            try:
                cur.execute("""
                    INSERT INTO groups (name, description, recharge_required,
                                        max_session_seconds, bandwidth_down_kbps,
                                        bandwidth_up_kbps, vlan_id, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        description = COALESCE(NULLIF(EXCLUDED.description, ''), groups.description),
                        recharge_required = EXCLUDED.recharge_required,
                        max_session_seconds = COALESCE(EXCLUDED.max_session_seconds, groups.max_session_seconds),
                        bandwidth_down_kbps = EXCLUDED.bandwidth_down_kbps,
                        bandwidth_up_kbps = EXCLUDED.bandwidth_up_kbps,
                        vlan_id = EXCLUDED.vlan_id,
                        is_admin = EXCLUDED.is_admin,
                        updated_at = CURRENT_TIMESTAMP
                """, (payload.groupname, payload.description,
                      False if (payload.is_admin or payload.groupname == "admins" or payload.recharge_required is False) else True,
                      (payload.session_timeout or 86400),
                      payload.bandwidth_down_kbps, payload.bandwidth_up_kbps,
                      (int(str(payload.vlan_id).strip()) if payload.vlan_id is not None and str(payload.vlan_id).strip().isdigit() else None),
                      bool(payload.is_admin or payload.groupname == "admins")))
            except Exception as e:
                logger.debug("central groups mirror skipped for %s: %s", payload.groupname, e)

            # Re-sync every member: group policy changes (exempt on/off,
            # timeouts) only take effect once radcheck Auth-Type/Session-Timeout
            # rows are rewritten. Previously stale Reject rows survived a
            # group-level exempt, so "exempt" looked not applicable.
            resynced, resync_errors = 0, 0
            try:
                cur.execute("SELECT DISTINCT username FROM radusergroup WHERE groupname = %s", (payload.groupname,))
                members = [r["username"] for r in (cur.fetchall() or []) if r.get("username")]
            except Exception:
                members = []
            conn.commit()
            if members:
                try:
                    from access_engine import sync_user_radius_attributes
                except ImportError:
                    from api.access_engine import sync_user_radius_attributes  # type: ignore
                for uname in members:
                    try:
                        sync_user_radius_attributes(uname)
                        resynced += 1
                    except Exception as e:
                        resync_errors += 1
                        logger.debug("member resync skipped for %s: %s", uname, e)

            warnings = framed_ip_warnings(payload.extra_reply_attributes, f"Group '{payload.groupname}'")
            msg = f"Policy Group '{payload.groupname}' saved successfully!"
            if members:
                msg += f" ({resynced} member(s) re-synced" + (f", {resync_errors} skipped" if resync_errors else "") + ")"
            log_audit(admin_user, "group_save", payload.groupname,
                      f"recharge_required={payload.recharge_required} simultaneous_use={payload.simultaneous_use} resynced={resynced}")
            return {"status": "success", "message": msg,
                    "warnings": warnings}
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
def delete_group(groupname: str, admin_user: str = Depends(authenticate_admin)):
    if groupname == "admins":
        raise HTTPException(status_code=400, detail="Cannot delete default 'admins' system group.")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radgroupreply WHERE groupname = %s", (groupname,))
            cur.execute("DELETE FROM radgroupcheck WHERE groupname = %s", (groupname,))
            cur.execute("DELETE FROM radusergroup WHERE groupname = %s", (groupname,))
            try:
                cur.execute("DELETE FROM groups WHERE name = %s", (groupname,))
            except Exception as e:
                logger.debug("central groups cleanup skipped for %s: %s", groupname, e)
            conn.commit()
            log_audit(admin_user, "group_delete", groupname, None)
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
def create_nas(payload: NasCreateRequest, admin_user: str = Depends(authenticate_admin)):
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
            log_audit(admin_user, "nas_create", payload.shortname, f"nasname={payload.nasname} id={new_id}")
            return {"status": "success", "id": new_id, "message": f"NAS client '{payload.shortname}' added successfully"}
    finally:
        conn.close()

@app.delete("/radius/api/nas/{nas_id}", tags=["NAS"])
@app.delete("/api/nas/{nas_id}", tags=["NAS"])
def delete_nas(nas_id: int, admin_user: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nas WHERE id = %s", (nas_id,))
            conn.commit()
            log_audit(admin_user, "nas_delete", f"#{nas_id}", None)
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

@app.get("/radius/api/accounting/gaps", tags=["Logs & Accounting"])
@app.get("/api/accounting/gaps", tags=["Logs & Accounting"])
def get_accounting_gaps(days: int = 7, _: str = Depends(authenticate_admin)):
    """Users accepted recently (radpostauth) but with zero accounting rows (radacct).

    This is the "authenticated but no session/device" symptom: the NAS sent
    Authentication (UDP 1812) but never sent Accounting (UDP 1813), so
    Sessions, Devices, and usage stay empty. Almost always an AP-side gap —
    accounting server IP/port unset, 1813 blocked, or secret mismatch.
    """
    try:
        days = min(max(int(days or 7), 1), 30)
    except (TypeError, ValueError):
        days = 7
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.username,
                       MAX(p.authdate) AS last_accept,
                       COUNT(*) AS accept_count
                FROM radpostauth p
                WHERE p.reply = 'Access-Accept'
                  AND p.authdate >= NOW() - (%s * INTERVAL '1 day')
                  AND NOT EXISTS (SELECT 1 FROM radacct a WHERE a.username = p.username)
                GROUP BY p.username
                ORDER BY last_accept DESC
                LIMIT 50
            """, (days,))
            rows = cur.fetchall()
            gaps = []
            for r in rows:
                v = r.get("last_accept")
                gaps.append({
                    "username": r.get("username"),
                    "last_accept": v.isoformat() if hasattr(v, "isoformat") else str(v),
                    "accept_count": int(r.get("accept_count") or 0),
                })
            return {"days": days, "gaps": gaps}
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
    """Deprecated shim — schema is owned by api/migrations via api/migrate.py."""
    try:
        from api.migrate import ensure_migrated
        ensure_migrated()
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
                    "source": "accounting",
                })
            # Auth-seen devices: stations that attempted authentication
            # (radpostauth context, migration 005) but never produced an
            # accounting row — typically the AP isn't sending UDP 1813.
            # Without this the Devices tab stays empty with no clue why.
            try:
                cur.execute("""
                    SELECT mac, attempts, last_seen, username, ap FROM (
                        SELECT REPLACE(REPLACE(REPLACE(REPLACE(
                                    UPPER(calling_station), ':', ''), '-', ''), ' ', ''), '.', '') AS mac,
                               COUNT(*) AS attempts,
                               MAX(authdate) AS last_seen,
                               (array_agg(username ORDER BY authdate DESC))[1] AS username,
                               (array_agg(called_station ORDER BY authdate DESC))[1] AS ap
                        FROM radpostauth
                        WHERE calling_station IS NOT NULL AND calling_station <> ''
                          AND authdate >= NOW() - INTERVAL '7 days'
                        GROUP BY 1
                    ) s WHERE mac ~ '^[0-9A-F]{12}$'
                    ORDER BY last_seen DESC LIMIT %s
                """, (limit,))
                have_mac = {r["mac"] for r in rows}
                for r in cur.fetchall():
                    mac = r.get("mac") or ""
                    if not mac or mac in have_mac:
                        continue
                    if username and (r.get("username") or "") != username:
                        continue
                    ls = r.get("last_seen")
                    out.append({
                        "mac": pretty_mac(mac),
                        "vendor": mac_vendor(mac),
                        "username": r.get("username"),
                        "sessions": 0,
                        "online": 0,
                        "first_seen": ls.isoformat() if hasattr(ls, "isoformat") else (str(ls) if ls else None),
                        "last_seen": ls.isoformat() if hasattr(ls, "isoformat") else (str(ls) if ls else None),
                        "up_bytes": 0,
                        "down_bytes": 0,
                        "up": format_bytes(0),
                        "down": format_bytes(0),
                        "total": format_bytes(0),
                        "last_ip": None,
                        "last_nas": None,
                        "last_ap": r.get("ap"),
                        "source": "auth",
                        "auth_attempts": int(r.get("attempts") or 0),
                    })
            except Exception:
                pass  # pre-005 databases simply skip this section
            return out
    finally:
        conn.close()


@app.get("/radius/api/auth-logs", tags=["Logs & Accounting"])
@app.get("/api/auth-logs", tags=["Logs & Accounting"])
def get_auth_logs(limit: int = 50, username: Optional[str] = None, result: Optional[str] = None, _: str = Depends(authenticate_admin)):
    """RADIUS authentication attempts. NOTE: the `pass` column (attempted passwords)
    is deliberately never selected — it must not leak through the API.
    `reason` carries the rule that rejected the attempt (e.g. unverified device);
    `eap_type`/`calling_station`/`called_station` carry device/AP context so
    outer-identity ("anonymous") rows stay diagnosable."""
    try:
        select_reason = ", reason"
        select_ctx = ", eap_type, calling_station, called_station"
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'radpostauth' AND column_name IN ('reason', 'eap_type', 'calling_station', 'called_station')")
            have = {r.get("column_name") for r in (cur.fetchall() or [])}
            if "reason" not in have:
                select_reason = ""
            for col in ("eap_type", "calling_station", "called_station"):
                if col not in have:
                    select_ctx = ""
                    break
        conn.close()
    except Exception:
        select_reason = ""
        select_ctx = ""
        try:
            conn.close()
        except Exception:
            pass
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = f"SELECT id, username, reply, authdate{select_reason}{select_ctx} FROM radpostauth WHERE 1=1"
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
                    "eap_type": (r.get("eap_type") or "").strip() or None,
                    "calling_station": (r.get("calling_station") or "").strip() or None,
                    "called_station": (r.get("called_station") or "").strip() or None,
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
def _eap_server_info() -> Dict[str, Any]:
    """Live EAP server identity from server.pem (public, no secrets).

    Returns {server_cn, server_san[], domain_hint}: the EXACT domain string
    phones must type into the Android "Domain" field. Falls back to
    RADIUS_PUBLIC_HOST / request-independent env when the cert is unreadable,
    so the portal never shows a blank domain.
    """
    info: Dict[str, Any] = {"server_cn": "", "server_san": [], "domain_hint": ""}
    try:
        server_path = os.path.join(CERTS_DIR, "server.pem")
        if os.path.exists(server_path):
            res = subprocess.run(
                ["openssl", "x509", "-in", server_path, "-noout", "-subject", "-ext", "subjectAltName"],
                capture_output=True, text=True, timeout=10)
            out = res.stdout or ""
            for line in out.splitlines():
                s = line.strip()
                if s.startswith("subject="):
                    m = re.search(r"CN\s*=\s*([^,/\n]+)", s)
                    if m:
                        info["server_cn"] = m.group(1).strip().strip('"')
                elif s.startswith("DNS:") or "DNS:" in s or "IP Address:" in s:
                    for part in s.split(","):
                        part = part.strip()
                        if part.startswith("DNS:"):
                            info["server_san"].append(part[4:])
                        elif part.startswith("IP Address:"):
                            info["server_san"].append(part[11:])
    except Exception as e:
        logger.debug("EAP server info parse failed: %s", e)
    dns_names = [s for s in info["server_san"] if s and not re.match(r"^\d+\.\d+\.\d+\.\d+$", s) and ":" not in s]
    info["domain_hint"] = (dns_names[0] if dns_names else "") or info["server_cn"] or (RADIUS_PUBLIC_HOST or "")
    return info


def _resolve_ca_path() -> str:
    for name in ("ca.pem", "ca.crt", "ca.cer"):
        p = os.path.join(CERTS_DIR, name)
        if os.path.exists(p):
            return p
    raise HTTPException(status_code=404, detail="CA certificate not found. Run cert bootstrap first.")


def _ca_info_dict() -> Dict[str, Any]:
    """Public CA fingerprint info so phones can verify before trusting."""
    ca_path = _resolve_ca_path()
    info: Dict[str, Any] = {"filename": os.path.basename(ca_path)}
    try:
        res = subprocess.run(
            ["openssl", "x509", "-in", ca_path, "-noout",
             "-subject", "-issuer", "-dates", "-fingerprint", "-sha256"],
            capture_output=True, text=True, timeout=10)
        for line in (res.stdout or "").splitlines():
            if line.startswith("subject="):
                info["subject"] = line[8:].strip()
            elif line.startswith("issuer="):
                info["issuer"] = line[7:].strip()
            elif line.startswith("notBefore="):
                info["not_before"] = line[10:].strip()
            elif line.startswith("notAfter="):
                info["not_after"] = line[9:].strip()
            elif "Fingerprint=" in line:
                info["sha256_fingerprint"] = line.split("=", 1)[1].strip()
    except Exception as e:
        logger.debug("CA info parse failed: %s", e)
    return info


@app.get("/radius/api/certs/ca", tags=["Certificates"])
@app.get("/api/certs/ca", tags=["Certificates"])
def download_ca_cert(format: str = "pem"):
    """Download the Root CA in the format the phone expects.

    Why this exists: Android's Wi-Fi certificate installer does not
    reliably recognise `.pem`. Samsung/Pixel pickers want `.crt`/`.cer`
    (DER). So `?format=crt|der` converts on the fly; default `pem` keeps
    old links working. Filenames match the format to avoid rename steps.
    """
    ca_path = _resolve_ca_path()
    fmt = (format or "pem").lower().strip().lstrip(".")
    if fmt in ("pem", "crt-pem", "cer-pem"):
        filename = "RajLabs_Root_CA.crt" if fmt != "pem" else "RajLabs_FreeRADIUS_Root_CA.pem"
        return FileResponse(ca_path, media_type="application/x-x509-ca-cert", filename=filename)
    if fmt in ("crt", "cer", "der"):
        try:
            res = subprocess.run(
                ["openssl", "x509", "-in", ca_path, "-outform", "DER"],
                capture_output=True, timeout=10, check=True)
            return Response(content=res.stdout,
                            media_type="application/x-x509-ca-cert",
                            headers={"Content-Disposition": 'attachment; filename="RajLabs_Root_CA.crt"'})
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"CA DER conversion failed: {e}")
    raise HTTPException(status_code=422, detail="format must be one of: pem, crt, der, cer.")


@app.get("/radius/api/certs/ca/info", tags=["Certificates"])
@app.get("/api/certs/ca/info", tags=["Certificates"])
@app.get("/radius/api/public/ca-info", tags=["Captive Portal"])
@app.get("/api/public/ca-info", tags=["Captive Portal"])
def get_ca_info():
    """Public (no auth): CA subject + SHA256 fingerprint for trust verification."""
    return _ca_info_dict()

@app.get("/radius/api/certs", tags=["Certificates"])
@app.get("/api/certs", tags=["Certificates"])
def list_certificates(_: str = Depends(authenticate_admin)):
    certs = []
    if os.path.isdir(CLIENT_CERTS_DIR):
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

@app.get("/radius/api/certs/{username}/inspect", tags=["Certificates"])
@app.get("/api/certs/{username}/inspect", tags=["Certificates"])
def inspect_certificate(username: str, _: str = Depends(authenticate_admin)):
    """Parse and return rich X.509 certificate and chain details for certificate viewer."""
    uname = validate_username(username)
    crt_path = safe_client_path(uname, ".crt")
    chain_path = safe_client_path(uname, "-chain.crt")
    p12_path = safe_client_path(uname, ".p12")

    if not os.path.exists(crt_path) and not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail=f"No certificate found for user '{uname}'.")

    # If crt doesn't exist, we can extract it or check p12
    subject = f"CN={uname}"
    issuer = "Unknown Issuer"
    not_before = ""
    not_after = ""
    serial = ""
    fingerprint = ""
    san_list = []
    text_dump = ""

    if os.path.exists(crt_path):
        try:
            # 1. Subject & Issuer
            res_subj = subprocess.run(["openssl", "x509", "-in", crt_path, "-noout", "-subject", "-issuer", "-serial", "-dates", "-fingerprint", "-sha256"], capture_output=True, text=True)
            lines = res_subj.stdout.splitlines()
            for l in lines:
                if l.startswith("subject="):
                    subject = l[8:].strip()
                elif l.startswith("issuer="):
                    issuer = l[7:].strip()
                elif l.startswith("serial="):
                    serial = l[7:].strip()
                elif l.startswith("notBefore="):
                    not_before = l[10:].strip()
                elif l.startswith("notAfter="):
                    not_after = l[9:].strip()
                elif l.startswith("SHA256 Fingerprint="):
                    fingerprint = l[19:].strip()

            # 2. Text dump & SANs
            res_text = subprocess.run(["openssl", "x509", "-in", crt_path, "-noout", "-text"], capture_output=True, text=True)
            text_dump = res_text.stdout
            if "Subject Alternative Name:" in text_dump:
                san_part = text_dump.split("Subject Alternative Name:")[1].split("\n")[1].strip()
                san_list = [s.strip() for s in san_part.split(",") if s.strip()]
        except Exception as e:
            logger.warning("Failed to parse certificate for %s: %s", uname, e)

    # Chain Inspection
    chain_issuer = ""
    has_chain = os.path.exists(chain_path)
    if has_chain:
        try:
            res_chain = subprocess.run(["openssl", "x509", "-in", chain_path, "-noout", "-subject", "-issuer"], capture_output=True, text=True)
            for l in res_chain.stdout.splitlines():
                if l.startswith("issuer="):
                    chain_issuer = l[7:].strip()
        except Exception:
            pass

    return {
        "username": uname,
        "p12_exists": os.path.exists(p12_path),
        "crt_exists": os.path.exists(crt_path),
        "has_chain": has_chain,
        "subject": subject,
        "issuer": issuer,
        "chain_issuer": chain_issuer or issuer,
        "serial": serial,
        "not_before": not_before,
        "not_after": not_after,
        "fingerprint_sha256": fingerprint,
        "san_list": san_list,
        "raw_text": text_dump,
        "authority_type": "Local FreeRADIUS Root CA" if ("freeradius" in issuer.lower() or "local" in issuer.lower()) else "Central RajLabs-CA PKI"
    }

def authenticate_admin_or_owner(username: str, request: Request) -> str:
    """Allows admins to manage any user, or authenticated users to access their own resource."""
    u = validate_username(username)
    try:
        admin_user = authenticate_admin(request)
        if admin_user:
            return admin_user
    except HTTPException:
        pass

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif request.cookies.get("admin_session"):
        token = request.cookies.get("admin_session")
    elif request.cookies.get("user_session"):
        token = request.cookies.get("user_session")

    if token:
        user = verify_session_token(token)
        if user and secrets.compare_digest(user, u):
            return u

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Unauthorized. Administrator credentials or session for '{u}' required."
    )

def sign_certificate_with_ca(username: str, user_csr_path: str, days: int = 365, san_list: Optional[List[str]] = None) -> tuple[str, str, str]:
    """
    Signs a client CSR using the central Rajlabs-CA Cert-Signer API (if configured),
    or falls back to the local FreeRADIUS CA.
    Returns: (issued_cert_pem, ca_chain_pem, authority_name)
    """
    signer_url, signer_key = get_cert_signer_config()
    if signer_url:
        try:
            with open(user_csr_path, "r") as f:
                csr_content = f.read()
            
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "RajLabs-FreeRADIUS/2.5",
                "Accept": "application/json"
            }
            if signer_key:
                headers["x-api-key"] = signer_key
                headers["X-API-KEY"] = signer_key
                headers["Authorization"] = f"Bearer {signer_key}"
            
            sans = san_list or [f"{username}@rajlabs.in", f"{username}.local"]
            payload_data = {
                "csr": csr_content,
                "san": sans,
                "days": days,
                "purpose": "wifi",
                "ca": "int-wifi"
            }
            
            base = signer_url.rstrip("/")
            if base.endswith("/api/v1"):
                req_url = f"{base}/sign"
            elif base.endswith("/api/v1/sign"):
                req_url = base
            else:
                req_url = f"{base}/api/v1/sign"

            req = urllib.request.Request(
                req_url,
                data=json.dumps(payload_data).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    res_json = json.loads(resp.read().decode("utf-8"))
                    cert_out = res_json.get("certificate") or res_json.get("cert") or res_json.get("data", {}).get("certificate")
                    chain_out = res_json.get("fullChain") or res_json.get("chain") or res_json.get("data", {}).get("fullChain") or cert_out
                    if cert_out:
                        logger.info("Certificate signed successfully via Central Rajlabs-CA Cert Signer for %s", username)
                        return cert_out, chain_out, "Central Rajlabs-CA PKI"
        except Exception as e:
            logger.warning("Cert-Signer microservice request to %s failed (%s), falling back to local CA.", signer_url, e)

    # Local FreeRADIUS CA Fallback
    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_pem = os.path.join(CERTS_DIR, "ca.pem")
    if not (os.path.exists(ca_key) and os.path.exists(ca_pem)):
        try:
            os.makedirs(CERTS_DIR, exist_ok=True)
            subprocess.run(["openssl", "genrsa", "-out", ca_key, "4096"], check=True, capture_output=True)
            subj = "/C=IN/ST=Delhi/O=RajLabs/CN=RajLabs FreeRADIUS Root CA"
            subprocess.run([
                "openssl", "req", "-x509", "-new", "-nodes", "-key", ca_key,
                "-sha256", "-days", "3650", "-out", ca_pem, "-subj", subj
            ], check=True, capture_output=True)
            logger.info("Auto-bootstrapped local FreeRADIUS Root CA at %s", ca_pem)
        except Exception as e:
            logger.warning("Failed to auto-bootstrap local CA: %s", e)

    if not os.path.exists(ca_key) or not os.path.exists(ca_pem):
        raise HTTPException(status_code=500, detail="No certificate authority available (Cert-Signer unreachable and local CA missing).")

    temp_crt_path = user_csr_path + ".crt"
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

    logger.info("Certificate signed locally via FreeRADIUS Root CA for %s", username)
    return crt_pem, ca_pem_content, "Local FreeRADIUS CA"

@app.post("/radius/api/certs/issue", tags=["Certificates"])
@app.post("/api/certs/issue", tags=["Certificates"])
def issue_client_certificate(payload: IssueCertRequest, request: Request, admin_user: str = Depends(authenticate_admin)):
    check_rate_limit(request, "cert-issue", RL_CERT_ISSUE_PER_MIN)
    uname = validate_username(payload.username)
    p12_pass = payload.cert_password or generate_p12_password()
    days = min(max(int(payload.valid_days or 365), 1), 825)
    email = payload.email or f"{uname}@rajlabs.in"

    user_key = safe_client_path(uname, ".key")
    user_csr = safe_client_path(uname, ".csr")
    user_crt = safe_client_path(uname, ".crt")
    user_p12 = safe_client_path(uname, ".p12")

    # 0. Ensure user exists in RADIUS database so EAP-TLS authentication and policy enforcement work
    user_auto_created = False
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM radcheck WHERE username = %s LIMIT 1", (uname,))
            if not cur.fetchone():
                auto_pass = generate_session_secret(24)
                cur.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Cleartext-Password', ':=', %s)
                """, (uname, auto_pass))
                cur.execute("""
                    INSERT INTO radusergroup (username, groupname, priority)
                    VALUES (%s, 'user', 1)
                    ON CONFLICT DO NOTHING
                """, (uname,))
                user_auto_created = True
        conn.close()
    except Exception as e:
        logger.warning("Failed to check/provision user in radcheck: %s", e)

    try:
        # 1. Generate client private key
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)

        # 2. Generate CSR
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)

        # 3. Sign client cert (via Central Cert Signer or Local CA fallback)
        cert_pem, ca_chain_pem, authority = sign_certificate_with_ca(uname, user_csr, days=days, san_list=[email, f"{uname}.local"])
        with open(user_crt, "w") as f:
            f.write(cert_pem)
        
        ca_chain_file = os.path.join(CLIENT_CERTS_DIR, f"{uname}-chain.crt")
        with open(ca_chain_file, "w") as f:
            f.write(ca_chain_pem)

        # 4. Package as PKCS#12 bundle (.p12) — legacy PBE for Android KeyChain compat
        export_pkcs12_bundle(user_crt, user_key, user_p12,
                             f"RajLabs RADIUS - {uname}", p12_pass, ca_chain_file)

        # Private key material: owner/group read only (never world-readable).
        for _p in (user_key, user_p12, user_crt):
            try:
                os.chmod(_p, 0o600)
            except OSError:
                pass

        log_audit(admin_user, "cert_issue", uname, f"authority={authority}, valid_days={days}, email={email}, auto_provisioned={user_auto_created}")
        logger.info("Client certificate issued username=%s by=%s via=%s auto_created=%s", uname, admin_user, authority, user_auto_created)
        # A fresh issue supersedes any prior revocation record for this user.
        try:
            c = get_db_connection()
            with c.cursor() as cur:
                clear_cert_revocation(cur, uname)
                c.commit()
            c.close()
        except Exception as e:
            logger.debug("revocation clear skipped for %s: %s", uname, e)
        return {
            "status": "success",
            "message": f"EAP-TLS Client certificate issued for user '{uname}' (Signed via {authority})",
            "username": uname,
            "authority": authority,
            "auto_provisioned": user_auto_created,
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


def _signer_api_root(signer_url: str) -> str:
    """Normalize any configured signer base to the API root (…/api/v1)."""
    base = (signer_url or "").rstrip("/")
    for suffix in ("/api/v1/sign", "/api/v1/revoke", "/api/v1"):
        if base.endswith(suffix):
            return base[: -len(suffix)] + "/api/v1"
    return base + "/api/v1"


def _signer_headers(signer_key: str) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "RajLabs-FreeRADIUS/2.5"}
    if signer_key:
        headers["x-api-key"] = signer_key
        headers["X-API-KEY"] = signer_key
        headers["Authorization"] = f"Bearer {signer_key}"
    return headers


def revoke_upstream_certificate(uname: str, reason: str = "keyCompromise") -> Dict[str, Any]:
    """Revoke/delete a certificate at the central signer (upstream of us).

    Tries the RESTful delete API first (DELETE /api/v1/certificates/{user} —
    the signer internally revokes, publishes CRL and deletes the record),
    falling back to the legacy POST /api/v1/revoke. A 404 counts as success
    (nothing left upstream). Local-only mode returns ok=False so callers can
    still proceed with file removal + ledger record.
    """
    signer_url, signer_key = get_cert_signer_config()
    if not signer_url:
        return {"ok": False, "method": "local-only", "detail": "No central signer configured."}
    root = _signer_api_root(signer_url)
    headers = _signer_headers(signer_key)
    # 1. Delete API (revoke + CRL + delete, handled inside the signer)
    try:
        req = urllib.request.Request(
            f"{root}/certificates/{urllib.parse.quote(uname, safe='')}",
            headers=headers, method="DELETE",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status in (200, 201, 202, 204, 404):
                return {"ok": True, "method": "signer-delete",
                        "detail": f"Upstream delete returned HTTP {resp.status}."}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": True, "method": "signer-delete",
                    "detail": "Already absent upstream (HTTP 404)."}
        logger.debug("Signer delete API failed for %s: HTTP %s", uname, e.code)
    except Exception as e:
        logger.debug("Signer delete API failed for %s: %s", uname, e)
    # 2. Legacy revoke API fallback
    try:
        req = urllib.request.Request(
            f"{root}/revoke",
            data=json.dumps({"username": uname, "reason": reason}).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status in (200, 201):
                return {"ok": True, "method": "signer-revoke",
                        "detail": f"Upstream revoke returned HTTP {resp.status}."}
            return {"ok": False, "method": "signer-revoke",
                    "detail": f"Upstream revoke returned HTTP {resp.status}."}
    except Exception as e:
        logger.warning("Remote revocation on %s failed (%s)", signer_url, e)
        return {"ok": False, "method": "signer-revoke", "detail": f"Upstream unreachable: {e}"}


def record_cert_revocation(cur, uname: str, serial: Optional[str], reason: str,
                           upstream: Dict[str, Any], revoked_by: Optional[str]):
    """Best-effort ledger write (table comes from migration 004)."""
    try:
        cur.execute("""
            INSERT INTO revoked_certificates (username, serial, reason, upstream_ok, upstream_detail, revoked_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                serial = EXCLUDED.serial, reason = EXCLUDED.reason,
                upstream_ok = EXCLUDED.upstream_ok, upstream_detail = EXCLUDED.upstream_detail,
                revoked_at = CURRENT_TIMESTAMP, revoked_by = EXCLUDED.revoked_by
        """, (uname, serial, reason, bool(upstream.get("ok")),
              f"{upstream.get('method')}: {upstream.get('detail')}"[:500], revoked_by))
    except Exception as e:
        logger.debug("revoked_certificates write skipped for %s: %s", uname, e)


def clear_cert_revocation(cur, uname: str):
    """A fresh (re)issue supersedes any prior revocation record."""
    try:
        cur.execute("DELETE FROM revoked_certificates WHERE username = %s", (uname,))
    except Exception as e:
        logger.debug("revoked_certificates clear skipped for %s: %s", uname, e)


def _read_cert_serial(crt_path: str) -> Optional[str]:
    try:
        if not os.path.exists(crt_path):
            return None
        res = subprocess.run(["openssl", "x509", "-in", crt_path, "-noout", "-serial"],
                             capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and "=" in (res.stdout or ""):
            return res.stdout.strip().split("=")[-1].strip() or None
    except Exception:
        pass
    return None


@app.post("/radius/api/certs/{username}/revoke", tags=["Certificates"])
@app.post("/api/certs/{username}/revoke", tags=["Certificates"])
def revoke_client_certificate(username: str, admin_user: str = Depends(authenticate_admin)):
    uname = validate_username(username)
    # Upstream first: signer delete API (revokes internally + CRL), revoke fallback
    upstream = revoke_upstream_certificate(uname, reason="keyCompromise")
    serial = _read_cert_serial(safe_client_path(uname, ".crt"))

    # Remove the local cert and p12 bundle
    removed = 0
    for suffix in (".key", ".csr", ".crt", ".p12", "-chain.crt"):
        p = safe_client_path(uname, suffix)
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError:
            pass

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            record_cert_revocation(cur, uname, serial, "keyCompromise", upstream, admin_user)
            conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("revocation ledger unavailable: %s", e)

    log_audit(admin_user, "cert_revoke", uname, f"files_removed={removed}, upstream={upstream.get('method')}:{upstream.get('ok')}")
    return {
        "status": "success",
        "message": f"Certificate for '{uname}' has been revoked and client bundle removed.",
        "remote_revoked": bool(upstream.get("ok")),
        "upstream": upstream
    }

@app.delete("/radius/api/certs/{username}", tags=["Certificates"])
@app.delete("/api/certs/{username}", tags=["Certificates"])
def delete_client_certificate(username: str, admin_user: str = Depends(authenticate_admin)):
    """Delete a certificate bundle AND revoke it upstream first.

    Deletion is not just file cleanup: the signer delete API is called so the
    certificate is revoked (CRL) and removed centrally, then local material
    is removed and the revocation is recorded in the ledger.
    """
    uname = validate_username(username)
    upstream = revoke_upstream_certificate(uname, reason="cessationOfOperation")
    serial = _read_cert_serial(safe_client_path(uname, ".crt"))
    removed = 0
    for suffix in (".key", ".csr", ".crt", ".p12", "-chain.crt"):
        p = safe_client_path(uname, suffix)
        try:
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        except OSError:
            pass

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            record_cert_revocation(cur, uname, serial, "cessationOfOperation", upstream, admin_user)
            conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("revocation ledger unavailable: %s", e)

    log_audit(admin_user, "cert_delete", uname, f"files_removed={removed}, upstream={upstream.get('method')}:{upstream.get('ok')}")
    return {
        "status": "success",
        "message": f"Certificate for '{uname}' revoked upstream and bundle deleted successfully.",
        "remote_revoked": bool(upstream.get("ok")),
        "upstream": upstream
    }
@app.delete("/radius/api/certs/orphans/{username}", tags=["Certificates"])
@app.delete("/api/certs/orphans/{username}", tags=["Certificates"])
def delete_orphaned_certificate(username: str, admin_user: str = Depends(authenticate_admin)):
    """Remove cert material for an already-deleted user (revoking upstream too)."""
    username = validate_username(username)
    upstream = revoke_upstream_certificate(username, reason="cessationOfOperation")
    serial = _read_cert_serial(safe_client_path(username, ".crt"))
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
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            record_cert_revocation(cur, username, serial, "cessationOfOperation", upstream, admin_user)
            conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("revocation ledger unavailable: %s", e)
    log_audit(admin_user, "orphan_cert_cleanup", username, f"cert_files_removed={removed}, upstream={upstream.get('method')}:{upstream.get('ok')}")
    return {"status": "success", "message": f"Removed {removed} orphaned file(s) for '{username}'."}


@app.get("/radius/api/certs/{username}/download", tags=["Certificates"])
@app.get("/api/certs/{username}/download", tags=["Certificates"])
def download_client_p12(username: str, request: Request):
    authenticate_admin_or_owner(username, request)
    p12_path = safe_client_path(validate_username(username), ".p12")
    if not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail=f"No certificate found for user '{username}'. Issue one first.")
    return FileResponse(p12_path, media_type="application/x-pkcs12", filename=f"{username}_rajlabs_radius.p12")

@app.get("/radius/api/certs/{username}/mobileconfig", tags=["Certificates"])
@app.get("/api/certs/{username}/mobileconfig", tags=["Certificates"])
def download_apple_mobileconfig(username: str, request: Request, ssid: str = "RajLabs-Enterprise"):
    """Generates an Apple .mobileconfig WiFi Profile (fresh random p12 password per download)."""
    authenticate_admin_or_owner(username, request)
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
    # Server-side secret is authoritative — a client-supplied secret is only
    # honored for advanced NAS setups; the UI no longer asks for it.
    secret = payload.secret or RADIUS_SECRET
    secret_source = "custom" if payload.secret else "server-default"
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
            "command": shown,
            "nas_ip": nas_ip,
            "secret_source": secret_source
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "status": "Timeout",
            "output": "RADIUS authentication timed out. Make sure the FreeRADIUS daemon is running and listening on UDP 1812.",
            "nas_ip": nas_ip,
            "secret_source": secret_source
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
        cert_pem, ca_chain_pem, authority = sign_certificate_with_ca(uname, user_csr, days=days, san_list=[email, f"{uname}.local"])
        with open(user_crt, "w") as f:
            f.write(cert_pem)

        ca_chain_file = safe_client_path(uname, "-chain.crt")
        with open(ca_chain_file, "w") as f:
            f.write(ca_chain_pem)

        # 3. Package as PKCS#12 bundle (.p12) — legacy PBE for Android KeyChain compat
        export_pkcs12_bundle(user_crt, user_key, user_p12,
                             f"RajLabs RADIUS - {uname}", p12_pass, ca_chain_file)
        for _p in (user_key, user_p12, user_crt):
            try:
                os.chmod(_p, 0o600)
            except OSError:
                pass

        log_audit(uname, "portal_enroll_cert", uname, f"authority={authority}, email={email}")
        logger.info("Portal enrolled client certificate for %s via %s", uname, authority)
        try:
            _c = get_db_connection()
            with _c.cursor() as _cur:
                clear_cert_revocation(_cur, uname)
                _c.commit()
            _c.close()
        except Exception as e:
            logger.debug("revocation clear skipped for %s: %s", uname, e)

        return {
            "status": "success",
            "success": True,
            "message": f"Certificate enrolled successfully for {uname} (Signed by {authority})",
            "username": uname,
            "authority": authority,
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


@app.post("/radius/api/portal/login", tags=["Captive Portal"])
@app.post("/api/portal/login", tags=["Captive Portal"])
def portal_login(payload: PortalDownloadRequest):
    """Verify user credentials for portal login."""
    verify_portal_user(payload.username, payload.password)
    # Fetch user's group
    groupname = "users"
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT groupname FROM radusergroup WHERE username = %s ORDER BY priority ASC LIMIT 1", (payload.username,))
            row = cur.fetchone()
            if row and row.get("groupname"):
                groupname = row["groupname"]
    finally:
        conn.close()
    
    return {
        "status": "success",
        "username": payload.username,
        "group": groupname,
        "is_guest": groupname == "guests" or payload.username.startswith("guest_")
    }


@app.post("/radius/api/portal/create-guest-pass", tags=["Captive Portal"])
@app.post("/api/portal/create-guest-pass", tags=["Captive Portal"])
def portal_create_guest_pass(request: Request):
    """Generate a temporary 1-day guest account with random credentials.

    No subscription is granted — the pass must be recharged to stay usable.
    A 24h FreeRADIUS Expiration is stamped so the account stops working AND
    is later auto-deleted by the expiry worker (see cleanup_expired_guests).
    """
    check_rate_limit(request, "guest-pass", 10)
    guest_id = "guest_" + "".join(secrets.choice(string.digits) for _ in range(6))
    guest_pass = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    # UTC wall-time Expiration (container runs TZ=UTC; parsed back the same way)
    expires_epoch = int(time.time()) + 86400
    expiration_str = time.strftime("%d %b %Y %H:%M:%S", time.gmtime(expires_epoch))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Insert radcheck Cleartext-Password
            cur.execute(
                "INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Cleartext-Password', ':=', %s)",
                (guest_id, guest_pass)
            )
            # 24-hour hard expiry (RADIUS-level reject after this)
            cur.execute(
                "INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Expiration', ':=', %s)",
                (guest_id, expiration_str)
            )
            # Insert into radusergroup as 'guests'
            cur.execute(
                "INSERT INTO radusergroup (username, groupname, priority) VALUES (%s, 'guests', 1) "
                "ON CONFLICT DO NOTHING",
                (guest_id,)
            )
            # Add Max-Daily-Session or 24-hr session-timeout
            cur.execute(
                "INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Session-Timeout', ':=', '86400')",
                (guest_id,)
            )
            conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
        "username": guest_id,
        "password": guest_pass,
        "validity_days": 1,
        "max_session_hours": 24,
        "group": "guests",
        "is_guest": True,
        "expires_at_epoch_ms": expires_epoch * 1000,
        "expiration": expiration_str,
        "message": "Guest pass created successfully. Valid for 1-day plans only."
    }

# Static files & React SPA Mounts
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DIST_DIR = os.path.join(STATIC_DIR, "dist")
DIST_ASSETS_DIR = os.path.join(DIST_DIR, "assets")

if os.path.isdir(DIST_ASSETS_DIR):
    app.mount("/radius/assets", StaticFiles(directory=DIST_ASSETS_DIR), name="dist_assets_radius")
    app.mount("/assets", StaticFiles(directory=DIST_ASSETS_DIR), name="dist_assets_root")

if os.path.isdir(STATIC_DIR):
    app.mount("/radius/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_root")

# Public Captive Portal Splash Page
@app.get("/radius/portal", response_class=HTMLResponse, tags=["Captive Portal"])
@app.get("/portal", response_class=HTMLResponse, tags=["Captive Portal"])
def get_captive_portal():
    dist_index = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(dist_index):
        with open(dist_index, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    portal_path = os.path.join(STATIC_DIR, "portal.html")
    if os.path.exists(portal_path):
        with open(portal_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RajLabs Wi-Fi Login Portal</h1>")

@app.get("/radius", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/radius/", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
def get_dashboard(request: Request):
    host = request.headers.get("host", "").lower()
    dist_index = os.path.join(DIST_DIR, "index.html")
    
    # If accessed directly via wifi.rajlabs.in at root, serve captive portal
    if "wifi." in host and request.url.path in ("/", ""):
        if os.path.exists(dist_index):
            with open(dist_index, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        portal_path = os.path.join(STATIC_DIR, "portal.html")
        if os.path.exists(portal_path):
            with open(portal_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
                
    if os.path.exists(dist_index):
        with open(dist_index, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RajLabs FreeRADIUS Dashboard</h1>")


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
@app.get("/radius/favicon.ico", include_in_schema=False)
@app.get("/radius/favicon.svg", include_in_schema=False)
def get_favicon():
    for base in (DIST_DIR, STATIC_DIR):
        for name in ("favicon.svg", "favicon.ico"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                mt = "image/svg+xml" if name.endswith(".svg") else "image/x-icon"
                return FileResponse(p, media_type=mt)
    raise HTTPException(status_code=404, detail="Favicon not found")
