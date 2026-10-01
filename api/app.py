import os
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
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Request, status, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Database configuration from environment
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "radius")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
RADIUS_SECRET = os.getenv("RADIUS_SECRET", "testing123")

# Central Rajlabs-CA Cert Signer API Integration
CERT_SIGNER_API_URL = os.getenv("CERT_SIGNER_API_URL", "").rstrip("/")
CERT_SIGNER_API_KEY = os.getenv("CERT_SIGNER_API_KEY", "")

ADMIN_FALLBACK_USER = os.getenv("RADIUS_ADMIN_USER", "admin")
ADMIN_FALLBACK_PASS = os.getenv("RADIUS_ADMIN_PASSWORD", "admin123")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change_this_session_secret_in_production_32_chars!")

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
        if secrets.compare_digest(sig, expected_sig):
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
        print("Auth DB check error:", e)

    if secrets.compare_digest(user, ADMIN_FALLBACK_USER) and secrets.compare_digest(passwd, ADMIN_FALLBACK_PASS):
        return True
    return False

def verify_certificate_and_get_admin(cert_pem_or_p12_bytes: bytes, p12_password: str = "whatever") -> str:
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
            
            cmd = ["openssl", "pkcs12", "-in", p12_path, "-nokeys", "-out", cert_path, "-passin", f"pass:{p12_password}"]
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
    # Startup check
    try:
        conn = get_db_connection()
        conn.close()
        print("Connected successfully to PostgreSQL database:", POSTGRES_DB)
    except Exception as e:
        print("Warning: Database connection failed during startup:", e)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Models
class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    password_type: str = Field(default="Cleartext-Password") # Cleartext-Password, SHA2-Password, etc.
    group: Optional[str] = None
    attributes: Optional[Dict[str, str]] = None

class PasswordChangeRequest(BaseModel):
    password: str = Field(..., min_length=1)
    password_type: str = Field(default="Cleartext-Password")

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

class DisconnectSessionRequest(BaseModel):
    username: str
    nas_ip: str
    nas_secret: Optional[str] = None
    acct_session_id: Optional[str] = None
    framed_ip: Optional[str] = None

class IssueCertRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    cert_password: Optional[str] = "whatever"
    valid_days: Optional[int] = 365
    email: Optional[str] = None

class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    remember: Optional[bool] = True

class CertLoginRequest(BaseModel):
    cert_pem: Optional[str] = None
    p12_b64: Optional[str] = None
    p12_password: Optional[str] = "whatever"

# Authentication Endpoints
@app.post("/radius/api/auth/login", tags=["Authentication"])
@app.post("/api/auth/login", tags=["Authentication"])
def admin_login(payload: AdminLoginRequest, response: Response):
    if not verify_admin_user(payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials. Access denied."
        )
    
    token = generate_session_token(payload.username)
    max_age = 7 * 86400 if payload.remember else None
    response.set_cookie(
        key="admin_session",
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=True
    )
    return {
        "status": "success",
        "token": token,
        "username": payload.username,
        "role": "admin",
        "message": f"Welcome back, {payload.username}!"
    }

@app.post("/radius/api/auth/cert-login", tags=["Authentication"])
@app.post("/api/auth/cert-login", tags=["Authentication"])
def admin_cert_login(payload: CertLoginRequest, response: Response):
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
        admin_user = verify_certificate_and_get_admin(cert_data, payload.p12_password or "whatever")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Certificate verification failure: {str(e)}")

    token = generate_session_token(admin_user)
    response.set_cookie(
        key="admin_session",
        value=token,
        max_age=7 * 86400,
        httponly=True,
        samesite="lax",
        secure=True
    )
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
def admin_logout(response: Response):
    response.delete_cookie(key="admin_session")
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

            # Count issued client certificates
            issued_certs = len([f for f in os.listdir(CLIENT_CERTS_DIR) if f.endswith(".p12")])

            return {
                "total_users": user_count,
                "active_sessions": active_sessions,
                "total_accounting_records": total_accounting,
                "total_auth_logs": total_auth_logs,
                "nas_clients": nas_count,
                "total_groups": group_count,
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
                        "check_attributes": [],
                        "reply_attributes": []
                    }
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

            return list(users_map.values())
    finally:
        conn.close()

@app.post("/radius/api/users", tags=["Users"])
@app.post("/api/users", tags=["Users"])
def create_or_update_user(payload: UserCreateRequest, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
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
            return {"status": "success", "message": f"User '{payload.username}' created/updated successfully"}
    finally:
        conn.close()

@app.delete("/radius/api/users/{username}", tags=["Users"])
@app.delete("/api/users/{username}", tags=["Users"])
def delete_user(username: str, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radcheck WHERE username = %s", (username,))
            cur.execute("DELETE FROM radreply WHERE username = %s", (username,))
            cur.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
            conn.commit()
            return {"status": "success", "message": f"User '{username}' deleted successfully"}
    finally:
        conn.close()

@app.put("/radius/api/users/{username}/password", tags=["Users"])
@app.put("/api/users/{username}/password", tags=["Users"])
def update_user_password(username: str, payload: PasswordChangeRequest, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (username,))
            cur.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, %s, ':=', %s)
            """, (username, payload.password_type, payload.password))
            conn.commit()
            return {"status": "success", "message": f"Password updated for user '{username}'"}
    finally:
        conn.close()

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

def explain_attribute(attr: str, val: str) -> str:
    attr_lower = attr.lower()
    if "simultaneous-use" in attr_lower:
        return f"Limits user to {val} concurrent active device login(s)."
    elif "bandwidth-max-down" in attr_lower:
        mbps = f"{int(val)/1_000_000:.0f}" if val.isdigit() else val
        return f"Caps download speed at {mbps} Mbps (WISPr)."
    elif "bandwidth-max-up" in attr_lower:
        mbps = f"{int(val)/1_000_000:.0f}" if val.isdigit() else val
        return f"Caps upload speed at {mbps} Mbps (WISPr)."
    elif "mikrotik-rate-limit" in attr_lower:
        return f"MikroTik RouterOS rate-limit queue: {val}."
    elif "session-timeout" in attr_lower:
        mins = int(val) // 60 if val.isdigit() else val
        return f"Max session duration: {mins} min ({val}s)."
    elif "idle-timeout" in attr_lower:
        mins = int(val) // 60 if val.isdigit() else val
        return f"Inactivity disconnect: {mins} min ({val}s)."
    elif "acct-interim-interval" in attr_lower:
        return f"Telemetry update frequency: every {val}s."
    elif "tunnel-private-group-id" in attr_lower:
        return f"Dynamically isolates device on VLAN #{val}."
    elif "tunnel-type" in attr_lower:
        return "802.1X VLAN Protocol (13 = VLAN)."
    elif "tunnel-medium-type" in attr_lower:
        return "802.1X Medium (6 = 802.1Q Ethernet)."
    elif "framed-pool" in attr_lower:
        return f"Allocates IP from DHCP pool '{val}'."
    elif "service-type" in attr_lower:
        return f"Service role: {val}."
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
def get_accounting(limit: int = 50, active_only: bool = False, username: Optional[str] = None, _: str = Depends(authenticate_admin)):
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
            params = []
            if active_only:
                query += " AND acctstoptime IS NULL"
            if username:
                query += " AND username = %s"
                params.append(username)
            
            query += " ORDER BY radacctid DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()

@app.get("/radius/api/auth-logs", tags=["Logs & Accounting"])
@app.get("/api/auth-logs", tags=["Logs & Accounting"])
def get_auth_logs(limit: int = 50, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, username, reply, authdate, pass 
                FROM radpostauth 
                ORDER BY id DESC LIMIT %s
            """, (limit,))
            return cur.fetchall()
    finally:
        conn.close()

# Disconnect Session via RADIUS CoA / Disconnect-Request (RFC 5176)
@app.post("/radius/api/sessions/disconnect", tags=["Sessions"])
@app.post("/api/sessions/disconnect", tags=["Sessions"])
def disconnect_session(payload: DisconnectSessionRequest, _: str = Depends(authenticate_admin)):
    secret = payload.nas_secret or RADIUS_SECRET
    cmd = f"echo 'User-Name = \"{payload.username}\"' | radclient -r 1 {payload.nas_ip}:3799 disconnect '{secret}'"
    if payload.acct_session_id:
        cmd = f"echo -e 'User-Name = \"{payload.username}\"\\nAcct-Session-Id = \"{payload.acct_session_id}\"' | radclient -r 1 {payload.nas_ip}:3799 disconnect '{secret}'"

    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        output = res.stdout + res.stderr
        success = "Disconnect-ACK" in output or "CoA-ACK" in output
        return {
            "success": success,
            "status": "Session Disconnected (ACK)" if success else "Sent / Response: " + output.strip(),
            "output": output.strip()
        }
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
                        logging.info(f"Certificate signed successfully via Rajlabs-CA Cert Signer for {username}")
                        return res_json["certificate"], res_json.get("fullChain") or res_json["certificate"]
        except Exception as e:
            logging.warning(f"Cert-Signer microservice request to {CERT_SIGNER_API_URL} failed ({e}), falling back to local CA.")

    # Local FreeRADIUS CA Fallback
    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_pem = os.path.join(CERTS_DIR, "ca.pem")
    if not os.path.exists(ca_key) or not os.path.exists(ca_pem):
        raise HTTPException(status_code=500, detail="No certificate authority available (Cert-Signer unreachable and local CA missing).")

    temp_crt_path = user_csr_path + ".crt"
    subprocess.run([
        "openssl", "x509", "-req", "-in", user_csr_path,
        "-CA", ca_pem, "-CAkey", ca_key, "-CAcreateserial",
        "-out", temp_crt_path, "-days", str(days),
        "-passin", "pass:whatever"
    ], check=True, capture_output=True)

    with open(temp_crt_path, "r") as f:
        crt_pem = f.read()
    with open(ca_pem, "r") as f:
        ca_pem_content = f.read()

    if os.path.exists(temp_crt_path):
        os.remove(temp_crt_path)

    return crt_pem, ca_pem_content

@app.post("/radius/api/certs/issue", tags=["Certificates"])
@app.post("/api/certs/issue", tags=["Certificates"])
def issue_client_certificate(payload: IssueCertRequest, _: str = Depends(authenticate_admin)):
    uname = payload.username
    p12_pass = payload.cert_password or "whatever"
    days = payload.valid_days or 365
    email = payload.email or f"{uname}@rajlabs.in"

    user_key = os.path.join(CLIENT_CERTS_DIR, f"{uname}.key")
    user_csr = os.path.join(CLIENT_CERTS_DIR, f"{uname}.csr")
    user_crt = os.path.join(CLIENT_CERTS_DIR, f"{uname}.crt")
    user_p12 = os.path.join(CLIENT_CERTS_DIR, f"{uname}.p12")

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

        # Set permissions
        subprocess.run(["chmod", "644", user_p12, user_crt], check=False)

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

@app.get("/radius/api/certs/{username}/download", tags=["Certificates"])
@app.get("/api/certs/{username}/download", tags=["Certificates"])
def download_client_p12(username: str, _: str = Depends(authenticate_admin)):
    p12_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
    if not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail=f"No certificate found for user '{username}'. Issue one first.")
    return FileResponse(p12_path, media_type="application/x-pkcs12", filename=f"{username}_rajlabs_radius.p12")

@app.get("/radius/api/certs/{username}/mobileconfig", tags=["Certificates"])
@app.get("/api/certs/{username}/mobileconfig", tags=["Certificates"])
def download_apple_mobileconfig(username: str, ssid: str = "RajLabs-Enterprise", _: str = Depends(authenticate_admin)):
    """Generates an Apple .mobileconfig WiFi Profile containing the client certificate for 1-click install on iOS / macOS."""
    p12_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
    ca_path = os.path.join(CERTS_DIR, "ca.pem")

    if not os.path.exists(p12_path) or not os.path.exists(ca_path):
        raise HTTPException(status_code=404, detail="Client certificate or CA not found.")

    with open(p12_path, "rb") as f:
        p12_b64 = base64.b64encode(f.read()).decode("utf-8")

    with open(ca_path, "rb") as f:
        ca_b64 = base64.b64encode(f.read()).decode("utf-8")

    profile_uuid = str(uuid.uuid4())
    wifi_uuid = str(uuid.uuid4())
    cert_uuid = str(uuid.uuid4())
    ca_uuid = str(uuid.uuid4())

    mobileconfig = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadDisplayName</key>
    <string>RajLabs Wi-Fi ({username})</string>
    <key>PayloadIdentifier</key>
    <string>in.rajlabs.radius.wifi.{username}</string>
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
        <!-- Root CA -->
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
        <!-- Client PKCS#12 Certificate -->
        <dict>
            <key>Password</key>
            <string>whatever</string>
            <key>PayloadCertificateFileName</key>
            <string>{username}.p12</string>
            <key>PayloadContent</key>
            <data>{p12_b64}</data>
            <key>PayloadDisplayName</key>
            <string>RajLabs User Identity ({username})</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.usercert.{username}</string>
            <key>PayloadType</key>
            <string>com.apple.security.pkcs12</string>
            <key>PayloadUUID</key>
            <string>{cert_uuid}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
        </dict>
        <!-- Wi-Fi EAP-TLS Profile -->
        <dict>
            <key>AutoJoin</key>
            <true/>
            <key>EncryptionType</key>
            <string>WPA2</string>
            <key>HIDDEN_NETWORK</key>
            <false/>
            <key>PayloadDisplayName</key>
            <string>Wi-Fi ({ssid})</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.wifi.config</string>
            <key>PayloadType</key>
            <string>com.apple.wifi.managed</string>
            <key>PayloadUUID</key>
            <string>{wifi_uuid}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>SSID_STR</key>
            <string>{ssid}</string>
            <key>EAPClientConfiguration</key>
            <dict>
                <key>AcceptEAPTypes</key>
                <array>
                    <integer>13</integer> <!-- 13 = EAP-TLS -->
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
    return Response(
        content=mobileconfig,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": f'attachment; filename="RajLabs_{username}_WiFi.mobileconfig"'}
    )

# Live RADIUS Testing (radtest)
@app.post("/radius/api/test-auth", tags=["Testing"])
@app.post("/api/test-auth", tags=["Testing"])
def test_radius_authentication(payload: AuthTestRequest, _: str = Depends(authenticate_admin)):
    secret = payload.secret or RADIUS_SECRET
    cmd = [
        "radtest",
        payload.username,
        payload.password,
        payload.nas_ip or "127.0.0.1",
        "0",
        secret
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        output = result.stdout + result.stderr
        success = "Access-Accept" in output
        return {
            "success": success,
            "status": "Accepted" if success else "Rejected / Failed",
            "output": output.strip(),
            "command": f"radtest {payload.username} [REDACTED] {payload.nas_ip} 0 [SECRET]"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "status": "Timeout",
            "output": "RADIUS authentication timed out. Make sure the FreeRADIUS daemon is running and listening on UDP 1812."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run radtest: {str(e)}")

class PortalEnrollCertRequest(BaseModel):
    username: str
    password: str
    device_name: Optional[str] = "Personal Device"
    cert_password: Optional[str] = "whatever"

# Public Self-Service Device Certificate Enrollment & Auto-Login
@app.post("/radius/api/portal/enroll-certificate", tags=["Captive Portal"])
@app.post("/api/portal/enroll-certificate", tags=["Captive Portal"])
def portal_enroll_certificate(payload: PortalEnrollCertRequest):
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

    uname = payload.username
    p12_pass = payload.cert_password or "whatever"
    days = 365
    email = f"{uname}@rajlabs.in"

    user_key = os.path.join(CLIENT_CERTS_DIR, f"{uname}.key")
    user_csr = os.path.join(CLIENT_CERTS_DIR, f"{uname}.csr")
    user_crt = os.path.join(CLIENT_CERTS_DIR, f"{uname}.crt")
    user_p12 = os.path.join(CLIENT_CERTS_DIR, f"{uname}.p12")

    try:
        # 1. Generate client private key & CSR
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)

        # 2. Sign certificate with central Cert Signer or Local CA
        cert_pem, ca_chain_pem = sign_certificate_with_ca(uname, user_csr, days=days, san_list=[email, f"{uname}.local"])
        with open(user_crt, "w") as f:
            f.write(cert_pem)
        
        ca_chain_file = os.path.join(CLIENT_CERTS_DIR, f"{uname}-chain.crt")
        with open(ca_chain_file, "w") as f:
            f.write(ca_chain_pem)

        # 3. Package as PKCS#12 bundle (.p12)
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", user_crt, "-inkey", user_key, "-certfile", ca_chain_file,
            "-out", user_p12, "-name", f"RajLabs RADIUS - {uname}",
            "-password", f"pass:{p12_pass}"
        ], check=True, capture_output=True)
        subprocess.run(["chmod", "644", user_p12, user_crt], check=False)

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
def portal_download_mobileconfig(username: str, ssid: str = "RajLabs-Enterprise"):
    p12_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
    ca_path = os.path.join(CERTS_DIR, "ca.pem")

    if not os.path.exists(p12_path) or not os.path.exists(ca_path):
        raise HTTPException(status_code=404, detail="Client certificate not found. Enroll first.")

    with open(p12_path, "rb") as f:
        p12_b64 = base64.b64encode(f.read()).decode("utf-8")

    with open(ca_path, "rb") as f:
        ca_b64 = base64.b64encode(f.read()).decode("utf-8")

    profile_uuid = str(uuid.uuid4())
    wifi_uuid = str(uuid.uuid4())
    cert_uuid = str(uuid.uuid4())
    ca_uuid = str(uuid.uuid4())

    mobileconfig = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadDisplayName</key>
    <string>RajLabs Wi-Fi ({username})</string>
    <key>PayloadIdentifier</key>
    <string>in.rajlabs.radius.wifi.{username}</string>
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
            <string>whatever</string>
            <key>PayloadCertificateFileName</key>
            <string>{username}.p12</string>
            <key>PayloadContent</key>
            <data>{p12_b64}</data>
            <key>PayloadDisplayName</key>
            <string>RajLabs Identity ({username})</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.usercert.{username}</string>
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
            <string>Wi-Fi ({ssid})</string>
            <key>PayloadIdentifier</key>
            <string>in.rajlabs.radius.wifi.config</string>
            <key>PayloadType</key>
            <string>com.apple.wifi.managed</string>
            <key>PayloadUUID</key>
            <string>{wifi_uuid}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>SSID_STR</key>
            <string>{ssid}</string>
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
    return Response(
        content=mobileconfig,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": f'attachment; filename="RajLabs_{username}_WiFi.mobileconfig"'}
    )

@app.get("/radius/api/portal/download-cert", tags=["Captive Portal"])
@app.get("/api/portal/download-cert", tags=["Captive Portal"])
def portal_download_cert(username: str):
    p12_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
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


