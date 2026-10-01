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
    simultaneous_use: Optional[int] = 3
    session_timeout: Optional[int] = None # in seconds
    idle_timeout: Optional[int] = 1800 # in seconds
    bandwidth_down_kbps: Optional[int] = None # WISPr-Bandwidth-Max-Down
    bandwidth_up_kbps: Optional[int] = None # WISPr-Bandwidth-Max-Up
    extra_attributes: Optional[Dict[str, str]] = None

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

# Group Management
@app.get("/radius/api/groups", tags=["Groups"])
@app.get("/api/groups", tags=["Groups"])
def list_groups(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    groupname, attribute, op, value
                FROM radgroupreply
                ORDER BY groupname ASC, attribute ASC
            """)
            rows = cur.fetchall()
            
            groups_map = {}
            for r in rows:
                g = r["groupname"]
                if g not in groups_map:
                    groups_map[g] = {"groupname": g, "attributes": []}
                groups_map[g]["attributes"].append({
                    "attribute": r["attribute"],
                    "op": r["op"],
                    "value": r["value"]
                })
            return list(groups_map.values())
    finally:
        conn.close()

@app.post("/radius/api/groups", tags=["Groups"])
@app.post("/api/groups", tags=["Groups"])
def create_or_update_group(payload: GroupCreateRequest, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radgroupreply WHERE groupname = %s", (payload.groupname,))
            
            if payload.simultaneous_use is not None:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Simultaneous-Use', ':=', %s)", (payload.groupname, str(payload.simultaneous_use)))
            
            if payload.session_timeout is not None:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Session-Timeout', '=', %s)", (payload.groupname, str(payload.session_timeout)))

            if payload.idle_timeout is not None:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Idle-Timeout', '=', %s)", (payload.groupname, str(payload.idle_timeout)))

            if payload.bandwidth_down_kbps is not None:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'WISPr-Bandwidth-Max-Down', '=', %s)", (payload.groupname, str(payload.bandwidth_down_kbps * 1000)))

            if payload.bandwidth_up_kbps is not None:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'WISPr-Bandwidth-Max-Up', '=', %s)", (payload.groupname, str(payload.bandwidth_up_kbps * 1000)))

            if payload.extra_attributes:
                for k, v in payload.extra_attributes.items():
                    cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, %s, '=', %s)", (payload.groupname, k, v))

            conn.commit()
            return {"status": "success", "message": f"Group '{payload.groupname}' saved successfully"}
    finally:
        conn.close()

@app.delete("/radius/api/groups/{groupname}", tags=["Groups"])
@app.delete("/api/groups/{groupname}", tags=["Groups"])
def delete_group(groupname: str, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM radgroupreply WHERE groupname = %s", (groupname,))
            cur.execute("DELETE FROM radgroupcheck WHERE groupname = %s", (groupname,))
            conn.commit()
            return {"status": "success", "message": f"Group '{groupname}' deleted successfully"}
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

    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_pem = os.path.join(CERTS_DIR, "ca.pem")

    if not os.path.exists(ca_key) or not os.path.exists(ca_pem):
        raise HTTPException(status_code=500, detail="FreeRADIUS CA key/cert not found. Bootstrap certificates first.")

    try:
        # 1. Generate client private key
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)

        # 2. Generate CSR
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)

        # 3. Sign client cert with FreeRADIUS CA
        subprocess.run([
            "openssl", "x509", "-req", "-in", user_csr,
            "-CA", ca_pem, "-CAkey", ca_key, "-CAcreateserial",
            "-out", user_crt, "-days", str(days),
            "-passin", "pass:whatever"
        ], check=True, capture_output=True)

        # 4. Package as PKCS#12 bundle (.p12)
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", user_crt, "-inkey", user_key, "-certfile", ca_pem,
            "-out", user_p12, "-name", f"RajLabs RADIUS - {uname}",
            "-password", f"pass:{p12_pass}"
        ], check=True, capture_output=True)

        # Set permissions
        subprocess.run(["chmod", "644", user_p12, user_crt], check=False)

        return {
            "status": "success",
            "message": f"EAP-TLS Client certificate issued for user '{uname}'",
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
    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_pem = os.path.join(CERTS_DIR, "ca.pem")

    try:
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)
        subprocess.run([
            "openssl", "x509", "-req", "-in", user_csr,
            "-CA", ca_pem, "-CAkey", ca_key, "-CAcreateserial",
            "-out", user_crt, "-days", str(days),
            "-passin", "pass:whatever"
        ], check=True, capture_output=True)
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", user_crt, "-inkey", user_key, "-certfile", ca_pem,
            "-out", user_p12, "-name", f"RajLabs RADIUS - {uname}",
            "-password", f"pass:{p12_pass}"
        ], check=True, capture_output=True)
        subprocess.run(["chmod", "644", user_p12, user_crt], check=False)

        return {
            "status": "success",
            "success": True,
            "message": f"Certificate enrolled successfully for {uname}",
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


