import os
import subprocess
import secrets
import shutil
import base64
import uuid
import time
import datetime
import hmac
import hashlib
import tempfile
import json
import logging
import asyncio
import urllib.request
import urllib.error
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException, Query, Request, status, Depends, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from db_init import init_all_tables, get_db_connection
    from access_engine import get_access_decision, get_user_full_context, sync_user_radius_attributes
    from entitlements import (
        activate_or_extend_subscription,
        process_verified_payment,
        redeem_voucher,
        batch_generate_vouchers,
        get_user_usage_stats,
        get_system_setting,
        set_system_setting,
        disconnect_active_radius_session,
        run_periodic_expiry_worker,
        log_audit_event
    )
    from payment_providers import PaymentProvider
except ImportError:
    from api.db_init import init_all_tables, get_db_connection
    from api.access_engine import get_access_decision, get_user_full_context, sync_user_radius_attributes
    from api.entitlements import (
        activate_or_extend_subscription,
        process_verified_payment,
        redeem_voucher,
        batch_generate_vouchers,
        get_user_usage_stats,
        get_system_setting,
        set_system_setting,
        disconnect_active_radius_session,
        run_periodic_expiry_worker,
        log_audit_event
    )
    from api.payment_providers import PaymentProvider

# Core Configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "radius")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
RADIUS_SECRET = os.getenv("RADIUS_SECRET", "testing123")

CERT_SIGNER_API_URL = os.getenv("CERT_SIGNER_API_URL", "").rstrip("/")
CERT_SIGNER_API_KEY = os.getenv("CERT_SIGNER_API_KEY", "")

ADMIN_FALLBACK_USER = os.getenv("RADIUS_ADMIN_USER", "admin")
ADMIN_FALLBACK_PASS = os.getenv("RADIUS_ADMIN_PASSWORD", "admin123")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change_this_session_secret_in_production_32_chars!")

RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "secret_razorpay_webhook")
CASHFREE_WEBHOOK_SECRET = os.getenv("CASHFREE_WEBHOOK_SECRET", "secret_cashfree_webhook")

CERTS_DIR = os.getenv("CERTS_DIR", "/etc/freeradius/3.0/certs")
CLIENT_CERTS_DIR = os.getenv("CLIENT_CERTS_DIR", os.path.join(CERTS_DIR, "clients"))
try:
    os.makedirs(CLIENT_CERTS_DIR, exist_ok=True)
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Session helpers
def generate_session_token(username: str, role: str = "admin") -> str:
    timestamp = int(time.time())
    data = f"{username}:{role}:{timestamp}"
    sig = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    raw = f"{data}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()

def verify_session_token(token: str) -> Optional[Tuple[str, str]]:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) == 3:
            # legacy token: username:timestamp:sig
            username, timestamp_str, sig = parts
            role = "admin"
            expected_sig = hmac.new(SESSION_SECRET.encode(), f"{username}:{timestamp_str}".encode(), hashlib.sha256).hexdigest()
        elif len(parts) == 4:
            username, role, timestamp_str, sig = parts
            expected_sig = hmac.new(SESSION_SECRET.encode(), f"{username}:{role}:{timestamp_str}".encode(), hashlib.sha256).hexdigest()
        else:
            return None

        timestamp = int(timestamp_str)
        if time.time() - timestamp > 7 * 86400:
            return None
        if secrets.compare_digest(sig, expected_sig):
            return username, role
    except Exception:
        pass
    return None

def verify_admin_user(user: str, passwd: str) -> bool:
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.password_hash, g.name as group_name, g.is_admin
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.username = %s
            """, (user,))
            row = cur.fetchone()
            if row:
                stored_pass = row["password_hash"]
                conn.close()
                if secrets.compare_digest(stored_pass, passwd) and (row["is_admin"] or row["group_name"] == "admins" or user in ["raj", "shipra", "admin"]):
                    return True
            else:
                cur.execute("""
                    SELECT rc.username, rc.value, rug.groupname
                    FROM radcheck rc
                    LEFT JOIN radusergroup rug ON rc.username = rug.username
                    WHERE rc.username = %s AND rc.attribute LIKE '%%Password'
                """, (user,))
                rrow = cur.fetchone()
                if rrow:
                    conn.close()
                    if secrets.compare_digest(rrow["value"], passwd) and (rrow["groupname"] == "admins" or user in ["raj", "shipra", "admin"]):
                        return True
        conn.close()
    except Exception as e:
        logging.error(f"Auth DB check error: {e}")

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

        ca_path = os.path.join(CERTS_DIR, "ca.pem")
        verify_cmd = ["openssl", "verify", "-CAfile", ca_path, cert_path]
        v_res = subprocess.run(verify_cmd, capture_output=True, text=True)
        if v_res.returncode != 0 or "OK" not in v_res.stdout:
            raise ValueError(f"Certificate failed Root CA validation: {v_res.stderr or v_res.stdout}")

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
            verified = verify_session_token(token)
            if verified and verified[1] == "admin":
                return verified[0]
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
        verified = verify_session_token(cookie_token)
        if verified and verified[1] == "admin":
            return verified[0]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized. FreeRADIUS Administrator credentials or certificate required.",
        headers={"WWW-Authenticate": 'Bearer realm="RajLabs FreeRADIUS Admin Area"'}
    )

def authenticate_user(request: Request) -> Dict[str, Any]:
    """Authenticates regular user via Bearer Token or user_session cookie."""
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("user_session")

    if token:
        verified = verify_session_token(token)
        if verified:
            username = verified[0]
            user_ctx = get_user_full_context(username)
            if user_ctx:
                return user_ctx

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User authentication required. Please sign in."
    )

# Async Background Expiry Worker Task
async def background_expiry_loop():
    logging.info("Starting background subscription expiry worker loop...")
    while True:
        try:
            count = run_periodic_expiry_worker()
            if count > 0:
                logging.info(f"Background worker expired {count} subscription(s) and synced FreeRADIUS state.")
        except Exception as e:
            logging.error(f"Error in background expiry loop: {e}")
        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_all_tables()
        logging.info("Connected successfully to PostgreSQL and verified schema.")
    except Exception as e:
        logging.error(f"Warning: Database initialization failed during startup: {e}")
    
    worker_task = asyncio.create_task(background_expiry_loop())
    yield
    worker_task.cancel()

app = FastAPI(
    title="RajLabs FreeRADIUS Central Access & Entitlement API",
    description="Enterprise REST API, Access Decision Engine, EAP-TLS PKI & Subscription Management for FreeRADIUS",
    version="2.2.0",
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

# ============================================================================
# Request & Response Models
# ============================================================================
class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    password_type: str = Field(default="Cleartext-Password")
    group: Optional[str] = "PAID"
    email: Optional[str] = None
    phone: Optional[str] = None
    recharge_required_override: Optional[bool] = None
    status: Optional[str] = "ACTIVE"
    attributes: Optional[Dict[str, str]] = None

class PasswordChangeRequest(BaseModel):
    password: str = Field(..., min_length=1)

class GroupCreateRequest(BaseModel):
    groupname: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = None
    recharge_required: Optional[bool] = True
    simultaneous_use: Optional[int] = 3
    session_timeout: Optional[int] = 86400
    idle_timeout: Optional[int] = 1800
    acct_interim_interval: Optional[int] = 300
    bandwidth_down_kbps: Optional[int] = None
    bandwidth_up_kbps: Optional[int] = None
    mikrotik_rate_limit: Optional[str] = None
    vlan_id: Optional[int] = None
    framed_pool: Optional[str] = None
    is_admin: Optional[bool] = False

class PlanCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    plan_type: Optional[str] = "STANDARD" # DAILY, WEEKLY, MONTHLY, GUEST, VIP, PROMO
    price: float = Field(..., ge=0)
    validity_days: Optional[int] = None
    validity_seconds: Optional[int] = None
    max_session_seconds: Optional[int] = 86400
    description: Optional[str] = None
    enabled: Optional[bool] = True

class ManualGrantSubscriptionRequest(BaseModel):
    username: str
    plan_id: Optional[int] = None
    validity_days: Optional[int] = None
    validity_seconds: Optional[int] = None
    note: Optional[str] = "Admin manual grant"

class UpiPaymentVerifyRequest(BaseModel):
    username: str
    plan_id: int
    utr: str
    amount: float = 0.0
    reference_note: Optional[str] = None

class VoucherRedeemRequest(BaseModel):
    code: str

class VoucherGenerateRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=1000)
    plan_id: Optional[int] = None
    validity_days: Optional[int] = None
    validity_seconds: Optional[int] = None
    prefix: str = "WIFI"
    max_uses: int = 1
    expires_in_days: Optional[int] = 30

class SystemSettingsUpdateRequest(BaseModel):
    upi_vpa: Optional[str] = None
    upi_merchant_name: Optional[str] = None
    default_voucher_code: Optional[str] = None
    currency: Optional[str] = "INR"

class EmailReceiptRequest(BaseModel):
    subject: str
    body: str
    sender: Optional[str] = "bank-alert@bank.com"

class PortalRechargeOrderRequest(BaseModel):
    username: str
    plan_id: int

class NasCreateRequest(BaseModel):
    nasname: str
    shortname: str
    type: str = "other"
    secret: str
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
    username: str
    cert_password: Optional[str] = "whatever"
    valid_days: Optional[int] = 365
    email: Optional[str] = None

class AdminLoginRequest(BaseModel):
    username: str
    password: str
    remember: Optional[bool] = True

class UserLoginRequest(BaseModel):
    username: str
    password: str
    remember: Optional[bool] = True

class CertLoginRequest(BaseModel):
    cert_pem: Optional[str] = None
    p12_b64: Optional[str] = None
    p12_password: Optional[str] = "whatever"

# ============================================================================
# Admin Authentication Endpoints
# ============================================================================
@app.post("/radius/api/auth/login", tags=["Authentication"])
@app.post("/api/auth/login", tags=["Authentication"])
def admin_login(payload: AdminLoginRequest, response: Response):
    if not verify_admin_user(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid administrator credentials. Access denied.")
    
    token = generate_session_token(payload.username, role="admin")
    max_age = 7 * 86400 if payload.remember else None
    response.set_cookie(key="admin_session", value=token, max_age=max_age, httponly=True, samesite="lax", secure=True)
    return {"status": "success", "token": token, "username": payload.username, "role": "admin", "message": f"Welcome back, {payload.username}!"}

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
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Certificate verification failure: {str(e)}")

    token = generate_session_token(admin_user, role="admin")
    response.set_cookie(key="admin_session", value=token, max_age=7 * 86400, httponly=True, samesite="lax", secure=True)
    return {"status": "success", "token": token, "username": admin_user, "auth_method": "x509_certificate", "role": "admin"}

@app.post("/radius/api/auth/logout", tags=["Authentication"])
@app.post("/api/auth/logout", tags=["Authentication"])
def admin_logout(response: Response):
    response.delete_cookie(key="admin_session")
    return {"status": "success", "message": "Logged out successfully"}

@app.get("/radius/api/auth/me", tags=["Authentication"])
@app.get("/api/auth/me", tags=["Authentication"])
def admin_get_current_user(current_admin: str = Depends(authenticate_admin)):
    return {"status": "success", "username": current_admin, "role": "admin", "authenticated": True}

# ============================================================================
# User Self-Service Authentication & Dashboard Endpoints
# ============================================================================
@app.post("/radius/api/user/login", tags=["User Portal"])
@app.post("/api/user/login", tags=["User Portal"])
def user_portal_login(payload: UserLoginRequest, response: Response):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, username, password_hash, email, status FROM users WHERE username = %s
            """, (payload.username,))
            user_row = cur.fetchone()
            if not user_row or not secrets.compare_digest(user_row["password_hash"], payload.password):
                raise HTTPException(status_code=401, detail="Invalid username or password.")

            if user_row["status"] == "DISABLED":
                raise HTTPException(status_code=403, detail="Account is disabled. Please contact administrator.")

            token = generate_session_token(payload.username, role="user")
            max_age = 7 * 86400 if payload.remember else None
            response.set_cookie(key="user_session", value=token, max_age=max_age, httponly=True, samesite="lax", secure=True)
            
            return {
                "status": "success",
                "token": token,
                "username": payload.username,
                "role": "user",
                "message": f"Welcome back, {payload.username}!"
            }
    finally:
        conn.close()

@app.get("/radius/api/user/me", tags=["User Portal"])
@app.get("/api/user/me", tags=["User Portal"])
def user_portal_get_profile(user_ctx: Dict[str, Any] = Depends(authenticate_user)):
    """
    Returns authenticated user's profile, active entitlement, live validity countdown,
    data usage stats (MB/GB/Sessions), live connected devices, and certificate status.
    """
    username = user_ctx["username"]
    decision = get_access_decision(user_ctx)
    usage = get_user_usage_stats(username)

    # Fetch available recharge plans
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, plan_type, price, validity_seconds, max_session_seconds, description FROM plans WHERE enabled = TRUE ORDER BY price ASC")
            available_plans = cur.fetchall()
            for p in available_plans:
                p["validity_days"] = p["validity_seconds"] // 86400

            # Check issued certificate
            cert_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
            has_cert = os.path.exists(cert_path)
            
            # System UPI VPA & Merchant Name
            upi_vpa = get_system_setting("upi_vpa", "wifi@rajlabs", conn=conn)
            upi_merchant = get_system_setting("upi_merchant_name", "RajLabs WiFi", conn=conn)

            return {
                "status": "success",
                "username": username,
                "email": user_ctx.get("email"),
                "phone": user_ctx.get("phone"),
                "group": user_ctx.get("group_name"),
                "account_status": user_ctx.get("status"),
                "decision": decision["decision"],
                "reason": decision["reason"],
                "session_timeout_seconds": decision["session_timeout"],
                "remaining_seconds": decision["remaining_seconds"],
                "recharge_required": decision["recharge_required"],
                "subscription": decision.get("subscription"),
                "usage_stats": usage,
                "has_certificate": has_cert,
                "available_plans": available_plans,
                "payment_config": {
                    "upi_vpa": upi_vpa,
                    "merchant_name": upi_merchant
                }
            }
    finally:
        conn.close()

@app.post("/radius/api/user/redeem-voucher", tags=["User Portal"])
@app.post("/api/user/redeem-voucher", tags=["User Portal"])
def user_portal_redeem_voucher(payload: VoucherRedeemRequest, request: Request, user_ctx: Dict[str, Any] = Depends(authenticate_user)):
    """User enters promotional/prepaid voucher code for instant entitlement top-up."""
    try:
        res = redeem_voucher(
            user_id=user_ctx["id"],
            voucher_code=payload.code,
            ip=request.client.host if request.client else None
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/radius/api/user/change-password", tags=["User Portal"])
@app.post("/api/user/change-password", tags=["User Portal"])
def user_portal_change_password(payload: PasswordChangeRequest, user_ctx: Dict[str, Any] = Depends(authenticate_user)):
    """Allows user to update their Wi-Fi and portal password."""
    username = user_ctx["username"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE username = %s", (payload.password, username))
            conn.commit()

        sync_user_radius_attributes(username)

        log_audit_event(
            actor_type="USER",
            actor_id=username,
            event="PASSWORD_CHANGED",
            target_type="USER",
            target_id=str(user_ctx["id"])
        )
        return {"status": "success", "message": "Your password has been updated successfully!"}
    finally:
        conn.close()

@app.post("/radius/api/user/logout", tags=["User Portal"])
@app.post("/api/user/logout", tags=["User Portal"])
def user_portal_logout(response: Response):
    response.delete_cookie(key="user_session")
    return {"status": "success", "message": "Signed out successfully."}

# ============================================================================
# Central Access Decision Inspection Endpoint
# ============================================================================
@app.get("/radius/api/access/decision/{username}", tags=["Access Decision"])
@app.get("/api/access/decision/{username}", tags=["Access Decision"])
def inspect_access_decision(username: str, _: str = Depends(authenticate_admin)):
    user_ctx = get_user_full_context(username)
    if not user_ctx:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
    
    decision = get_access_decision(user_ctx)
    return {
        "username": username,
        "status": user_ctx["status"],
        "group": user_ctx["group_name"],
        "recharge_required_effective": decision["recharge_required"],
        "decision": decision["decision"],
        "reason": decision["reason"],
        "session_timeout_seconds": decision["session_timeout"],
        "remaining_validity_seconds": decision["remaining_seconds"],
        "subscription": decision.get("subscription")
    }

# ============================================================================
# Dynamic System Settings (Admin Configurable UPI ID, Merchant, etc.)
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
        if payload.upi_vpa is not None:
            set_system_setting("upi_vpa", payload.upi_vpa.strip(), "Active UPI VPA Address", conn=conn)
        if payload.upi_merchant_name is not None:
            set_system_setting("upi_merchant_name", payload.upi_merchant_name.strip(), "Merchant display name", conn=conn)
        if payload.default_voucher_code is not None:
            set_system_setting("default_voucher_code", payload.default_voucher_code.strip(), "Default onboarding voucher", conn=conn)
        if payload.currency is not None:
            set_system_setting("currency", payload.currency.strip().upper(), "Currency code", conn=conn)

        log_audit_event(
            actor_type="ADMIN",
            actor_id=current_admin,
            event="SETTINGS_UPDATED",
            metadata=payload.dict(exclude_unset=True),
            conn=conn
        )
        return {"status": "success", "message": "System settings updated successfully!"}
    finally:
        conn.close()

# ============================================================================
# Vouchers Management (Admin & Batch Generator)
# ============================================================================
@app.get("/radius/api/vouchers", tags=["Vouchers"])
@app.get("/api/vouchers", tags=["Vouchers"])
def list_vouchers(limit: int = 100, is_active: Optional[bool] = None, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    v.id, v.code, v.plan_id, p.name as plan_name, v.validity_seconds,
                    v.max_uses, v.current_uses, v.is_active, v.created_by, v.expires_at, v.created_at,
                    ROUND(v.validity_seconds / 86400.0, 1) as validity_days
                FROM vouchers v
                LEFT JOIN plans p ON v.plan_id = p.id
                WHERE 1=1
            """
            params = []
            if is_active is not None:
                query += " AND v.is_active = %s"
                params.append(is_active)
            query += " ORDER BY v.id DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/radius/api/vouchers/generate", tags=["Vouchers"])
@app.post("/api/vouchers/generate", tags=["Vouchers"])
def generate_vouchers(payload: VoucherGenerateRequest, current_admin: str = Depends(authenticate_admin)):
    validity_sec = payload.validity_seconds
    if not validity_sec and payload.validity_days:
        validity_sec = payload.validity_days * 86400

    generated = batch_generate_vouchers(
        count=payload.count,
        plan_id=payload.plan_id,
        validity_seconds=validity_sec,
        prefix=payload.prefix,
        max_uses=payload.max_uses,
        expires_in_days=payload.expires_in_days,
        created_by=current_admin
    )

    log_audit_event(
        actor_type="ADMIN",
        actor_id=current_admin,
        event="VOUCHERS_GENERATED",
        metadata={"count": payload.count, "prefix": payload.prefix, "validity_seconds": validity_sec}
    )

    return {
        "status": "success",
        "count": len(generated),
        "vouchers": generated
    }

@app.delete("/radius/api/vouchers/{voucher_id}", tags=["Vouchers"])
@app.delete("/api/vouchers/{voucher_id}", tags=["Vouchers"])
def delete_voucher(voucher_id: int, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vouchers WHERE id = %s RETURNING code", (voucher_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Voucher not found")
            conn.commit()
            log_audit_event(actor_type="ADMIN", actor_id=current_admin, event="VOUCHER_DELETED", target_type="VOUCHER", target_id=str(voucher_id))
            return {"status": "success", "message": f"Voucher '{row['code']}' deleted successfully."}
    finally:
        conn.close()

# ============================================================================
# Plans Management
# ============================================================================
@app.get("/radius/api/plans", tags=["Plans"])
@app.get("/api/plans", tags=["Plans"])
def list_plans():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, plan_type, price, validity_seconds, max_session_seconds, description, enabled, created_at
                FROM plans
                ORDER BY price ASC, validity_seconds ASC
            """)
            rows = cur.fetchall()
            for r in rows:
                r["validity_days"] = r["validity_seconds"] // 86400 if r["validity_seconds"] >= 86400 else round(r["validity_seconds"] / 86400, 2)
            return rows
    finally:
        conn.close()

@app.post("/radius/api/plans", tags=["Plans"])
@app.post("/api/plans", tags=["Plans"])
def create_plan(payload: PlanCreateRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        validity_sec = payload.validity_seconds
        if not validity_sec and payload.validity_days:
            validity_sec = payload.validity_days * 86400

        if not validity_sec or validity_sec <= 0:
            validity_sec = 86400

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO plans (name, plan_type, price, validity_seconds, max_session_seconds, description, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (payload.name, payload.plan_type or "STANDARD", payload.price, validity_sec, payload.max_session_seconds or 86400, payload.description, payload.enabled))
            plan_id = cur.fetchone()["id"]
            conn.commit()

            log_audit_event(
                actor_type="ADMIN",
                actor_id=current_admin,
                event="PLAN_CREATED",
                target_type="PLAN",
                target_id=str(plan_id),
                metadata={"name": payload.name, "price": payload.price, "validity_seconds": validity_sec},
                conn=conn
            )
            return {"status": "success", "id": plan_id, "message": f"Plan '{payload.name}' created successfully."}
    finally:
        conn.close()

@app.put("/radius/api/plans/{plan_id}", tags=["Plans"])
@app.put("/api/plans/{plan_id}", tags=["Plans"])
def update_plan(plan_id: int, payload: PlanCreateRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        validity_sec = payload.validity_seconds
        if not validity_sec and payload.validity_days:
            validity_sec = payload.validity_days * 86400
        if not validity_sec or validity_sec <= 0:
            validity_sec = 86400

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE plans
                SET name = %s, plan_type = %s, price = %s, validity_seconds = %s, max_session_seconds = %s,
                    description = %s, enabled = %s
                WHERE id = %s
            """, (payload.name, payload.plan_type or "STANDARD", payload.price, validity_sec, payload.max_session_seconds or 86400, payload.description, payload.enabled, plan_id))
            conn.commit()

            log_audit_event(
                actor_type="ADMIN",
                actor_id=current_admin,
                event="PLAN_UPDATED",
                target_type="PLAN",
                target_id=str(plan_id),
                conn=conn
            )
            return {"status": "success", "message": f"Plan #{plan_id} updated successfully."}
    finally:
        conn.close()

@app.delete("/radius/api/plans/{plan_id}", tags=["Plans"])
@app.delete("/api/plans/{plan_id}", tags=["Plans"])
def delete_plan(plan_id: int, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id = %s", (plan_id,))
            conn.commit()
            log_audit_event(
                actor_type="ADMIN",
                actor_id=current_admin,
                event="PLAN_DELETED",
                target_type="PLAN",
                target_id=str(plan_id),
                conn=conn
            )
            return {"status": "success", "message": f"Plan #{plan_id} deleted."}
    finally:
        conn.close()

# ============================================================================
# Subscriptions & Entitlements Management
# ============================================================================
@app.get("/radius/api/subscriptions", tags=["Subscriptions"])
@app.get("/api/subscriptions", tags=["Subscriptions"])
def list_subscriptions(username: Optional[str] = None, status_filter: Optional[str] = None, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    s.id, s.user_id, u.username, s.plan_id, p.name as plan_name, p.price,
                    s.starts_at, s.expires_at, s.status, s.payment_id, s.created_at,
                    EXTRACT(EPOCH FROM (s.expires_at - CURRENT_TIMESTAMP)) as remaining_seconds
                FROM subscriptions s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN plans p ON s.plan_id = p.id
                WHERE 1=1
            """
            params = []
            if username:
                query += " AND u.username = %s"
                params.append(username)
            if status_filter:
                query += " AND s.status = %s"
                params.append(status_filter)

            query += " ORDER BY s.id DESC LIMIT 100"
            cur.execute(query, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/radius/api/subscriptions/manual-grant", tags=["Subscriptions"])
@app.post("/api/subscriptions/manual-grant", tags=["Subscriptions"])
def manual_grant_subscription(payload: ManualGrantSubscriptionRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (payload.username,))
            user_row = cur.fetchone()
            if not user_row:
                raise HTTPException(status_code=404, detail=f"User '{payload.username}' not found.")
            user_id = user_row["id"]
            
        validity_sec = payload.validity_seconds
        if not validity_sec and payload.validity_days:
            validity_sec = payload.validity_days * 86400

        res = activate_or_extend_subscription(
            user_id=user_id,
            plan_id=payload.plan_id,
            custom_validity_seconds=validity_sec,
            actor_type="ADMIN",
            actor_id=current_admin
        )
        return res
    finally:
        conn.close()

# ============================================================================
# Payments & Webhooks
# ============================================================================
@app.get("/radius/api/payments", tags=["Payments"])
@app.get("/api/payments", tags=["Payments"])
def list_payments(limit: int = 50, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    pay.id, pay.user_id, u.username, pay.plan_id, p.name as plan_name,
                    pay.gateway, pay.gateway_order_id, pay.gateway_payment_id,
                    pay.amount, pay.currency, pay.status, pay.verified_at, pay.raw_reference, pay.created_at
                FROM payments pay
                LEFT JOIN users u ON pay.user_id = u.id
                LEFT JOIN plans p ON pay.plan_id = p.id
                ORDER BY pay.id DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/radius/api/payments/create-order", tags=["Payments"])
@app.post("/api/payments/create-order", tags=["Payments"])
def create_payment_order(payload: PortalRechargeOrderRequest):
    """Generates dynamic UPI QR code reference and Order intent for user recharge using configured UPI VPA."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username FROM users WHERE username = %s", (payload.username,))
            user_row = cur.fetchone()
            if not user_row:
                raise HTTPException(status_code=404, detail="User not found")
            
            cur.execute("SELECT id, name, price, validity_seconds FROM plans WHERE id = %s AND enabled = TRUE", (payload.plan_id,))
            plan_row = cur.fetchone()
            if not plan_row:
                raise HTTPException(status_code=404, detail="Plan not available")

            upi_vpa = get_system_setting("upi_vpa", "wifi@rajlabs", conn=conn)
            upi_merchant = get_system_setting("upi_merchant_name", "RajLabs WiFi", conn=conn)

            plan_days = max(1, plan_row["validity_seconds"] // 86400)
            upi_ref = PaymentProvider.generate_upi_reference(payload.username, plan_days)
            order_id = f"ORDER_{int(time.time())}_{secrets.token_hex(4)}"

            # Standard UPI deep-link string
            merchant_encoded = urllib.parse.quote(upi_merchant)
            upi_link = f"upi://pay?pa={upi_vpa}&pn={merchant_encoded}&am={plan_row['price']:.2f}&cu=INR&tn={upi_ref}"

            return {
                "order_id": order_id,
                "username": payload.username,
                "plan_id": plan_row["id"],
                "plan_name": plan_row["name"],
                "amount": float(plan_row["price"]),
                "currency": "INR",
                "upi_vpa": upi_vpa,
                "upi_merchant_name": upi_merchant,
                "upi_reference": upi_ref,
                "upi_deeplink": upi_link,
                "instructions": f"Pay ₹{plan_row['price']:.0f} to {upi_vpa} with transaction note: {upi_ref}"
            }
    finally:
        conn.close()

@app.post("/radius/api/payments/upi-verify", tags=["Payments"])
@app.post("/api/payments/upi-verify", tags=["Payments"])
def verify_upi_payment(payload: UpiPaymentVerifyRequest, request: Request):
    """Verifies UPI UTR and activates account."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username FROM users WHERE username = %s", (payload.username,))
            u_row = cur.fetchone()
            if not u_row:
                raise HTTPException(status_code=404, detail=f"User '{payload.username}' not found.")
            user_id = u_row["id"]

            cur.execute("SELECT id, price FROM plans WHERE id = %s", (payload.plan_id,))
            p_row = cur.fetchone()
            if not p_row:
                raise HTTPException(status_code=404, detail="Plan not found")

        client_ip = request.client.host if request.client else None
        res = process_verified_payment(
            gateway="UPI_QR",
            gateway_payment_id=payload.utr.strip(),
            gateway_order_id=None,
            user_id=user_id,
            plan_id=payload.plan_id,
            amount=payload.amount or float(p_row["price"]),
            currency="INR",
            raw_reference=payload.reference_note or payload.utr,
            actor_type="USER_UPI",
            ip=client_ip
        )
        return res
    finally:
        conn.close()

@app.post("/radius/api/payments/webhook/{gateway}", tags=["Payments"])
@app.post("/api/payments/webhook/{gateway}", tags=["Payments"])
async def payment_gateway_webhook(gateway: str, request: Request):
    body_bytes = await request.body()
    gateway_upper = gateway.upper()

    try:
        payload = json.loads(body_bytes.decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if gateway_upper == "RAZORPAY":
        sig = request.headers.get("X-Razorpay-Signature", "")
        if not PaymentProvider.verify_razorpay_signature(body_bytes, sig, RAZORPAY_WEBHOOK_SECRET):
            raise HTTPException(status_code=400, detail="Invalid signature")

        event = payload.get("event")
        if event != "payment.captured":
            return {"status": "ignored", "event": event}

        payment_entity = payload["payload"]["payment"]["entity"]
        payment_id = payment_entity["id"]
        order_id = payment_entity.get("order_id")
        amount = float(payment_entity["amount"]) / 100.0
        currency = payment_entity.get("currency", "INR")
        notes = payment_entity.get("notes", {})
        username = notes.get("username")
        plan_id = int(notes.get("plan_id", 0))

    elif gateway_upper == "CASHFREE":
        sig = request.headers.get("x-webhook-signature", "")
        ts = request.headers.get("x-webhook-timestamp", "")
        if not PaymentProvider.verify_cashfree_signature(body_bytes, sig, ts, CASHFREE_WEBHOOK_SECRET):
            raise HTTPException(status_code=400, detail="Invalid signature")

        data = payload.get("data", {})
        payment_id = data.get("payment", {}).get("cf_payment_id")
        order_id = data.get("order", {}).get("order_id")
        amount = float(data.get("payment", {}).get("payment_amount", 0))
        currency = data.get("payment", {}).get("payment_currency", "INR")
        tags = data.get("order", {}).get("order_tags", {})
        username = tags.get("username")
        plan_id = int(tags.get("plan_id", 0))

    else:
        payment_id = payload.get("payment_id") or payload.get("transaction_id") or f"TXN_{int(time.time())}"
        order_id = payload.get("order_id")
        amount = float(payload.get("amount", 0))
        currency = payload.get("currency", "INR")
        username = payload.get("username")
        plan_id = int(payload.get("plan_id", 1))

    if not username or not plan_id:
        raise HTTPException(status_code=400, detail="Missing username or plan_id metadata in payment event")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            u_row = cur.fetchone()
            if not u_row:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
            user_id = u_row["id"]
    finally:
        conn.close()

    res = process_verified_payment(
        gateway=gateway_upper,
        gateway_payment_id=str(payment_id),
        gateway_order_id=order_id,
        user_id=user_id,
        plan_id=plan_id,
        amount=amount,
        currency=currency,
        raw_reference=json.dumps(payload),
        actor_type="WEBHOOK",
        ip=request.client.host if request.client else None
    )
    return res

@app.post("/radius/api/payments/email-receipt", tags=["Payments"])
@app.post("/api/payments/email-receipt", tags=["Payments"])
def ingest_email_payment_receipt(payload: EmailReceiptRequest, request: Request, _: str = Depends(authenticate_admin)):
    parsed = PaymentProvider.parse_email_payment_receipt(payload.subject, payload.body)
    if not parsed:
        raise HTTPException(status_code=400, detail="Could not parse valid UTR, amount, and reference note from email.")

    username = parsed["username"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            u_row = cur.fetchone()
            if not u_row:
                raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
            user_id = u_row["id"]

            cur.execute("SELECT id FROM plans WHERE validity_seconds = %s LIMIT 1", (parsed["plan_days"] * 86400,))
            p_row = cur.fetchone()
            plan_id = p_row["id"] if p_row else 1
    finally:
        conn.close()

    res = process_verified_payment(
        gateway="EMAIL_RECEIPT",
        gateway_payment_id=parsed["utr"],
        gateway_order_id=None,
        user_id=user_id,
        plan_id=plan_id,
        amount=parsed["amount"],
        currency="INR",
        raw_reference=f"Subject: {payload.subject}\nSender: {payload.sender}",
        actor_type="EMAIL_WORKER",
        ip=request.client.host if request.client else None
    )
    return {"status": "success", "parsed": parsed, "result": res}

# ============================================================================
# Audit Logs
# ============================================================================
@app.get("/radius/api/audit", tags=["Audit"])
@app.get("/api/audit", tags=["Audit"])
def get_audit_logs(limit: int = 50, _: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, actor_type, actor_id, event, target_type, target_id, metadata, ip, created_at
                FROM audit_events
                ORDER BY id DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()
    finally:
        conn.close()

# ============================================================================
# Public Health Check
# ============================================================================
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

# ============================================================================
# Protected Swagger & Dashboard Overview
# ============================================================================
@app.get("/radius/docs", include_in_schema=False)
def get_swagger_documentation(_: str = Depends(authenticate_admin)):
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url="/radius/openapi.json", title="RajLabs FreeRADIUS Docs")

@app.get("/radius/openapi.json", include_in_schema=False)
def get_open_api_endpoint(_: str = Depends(authenticate_admin)):
    from fastapi.openapi.utils import get_openapi
    return get_openapi(title="RajLabs FreeRADIUS Central Access API", version="2.2.0", routes=app.routes)

@app.get("/radius/api/stats", tags=["Stats"])
@app.get("/api/stats", tags=["Stats"])
def get_stats(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as user_count FROM users;")
            user_count = cur.fetchone()["user_count"]

            cur.execute("SELECT COUNT(*) as active_sessions FROM radacct WHERE acctstoptime IS NULL;")
            active_sessions = cur.fetchone()["active_sessions"]

            cur.execute("SELECT COUNT(*) as active_subscriptions FROM subscriptions WHERE status = 'ACTIVE' AND expires_at > CURRENT_TIMESTAMP;")
            active_subs = cur.fetchone()["active_subscriptions"]

            cur.execute("SELECT COUNT(*) as total_vouchers, COUNT(CASE WHEN is_active THEN 1 END) as active_vouchers FROM vouchers;")
            v_stats = cur.fetchone()

            cur.execute("SELECT COUNT(*) as total_payments, COALESCE(SUM(amount), 0) as total_revenue FROM payments WHERE status = 'SUCCESS';")
            pay_stats = cur.fetchone()

            cur.execute("SELECT COUNT(*) as nas_count FROM nas;")
            nas_count = cur.fetchone()["nas_count"]

            cur.execute("SELECT COUNT(*) as group_count FROM groups;")
            group_count = cur.fetchone()["group_count"]

            issued_certs = len([f for f in os.listdir(CLIENT_CERTS_DIR) if f.endswith(".p12")])

            return {
                "total_users": user_count,
                "active_sessions": active_sessions,
                "active_subscriptions": active_subs,
                "total_vouchers": v_stats["total_vouchers"],
                "active_vouchers": v_stats["active_vouchers"],
                "total_revenue": float(pay_stats["total_revenue"]),
                "total_successful_payments": pay_stats["total_payments"],
                "nas_clients": nas_count,
                "total_groups": group_count,
                "client_certificates": issued_certs
            }
    finally:
        conn.close()

# ============================================================================
# User Management
# ============================================================================
@app.get("/radius/api/users", tags=["Users"])
@app.get("/api/users", tags=["Users"])
def list_users(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    u.id, u.username, u.email, u.phone, u.status, u.recharge_required_override,
                    u.created_at, u.updated_at,
                    g.id as group_id, g.name as groupname, g.recharge_required as group_recharge_required,
                    s.id as subscription_id, s.plan_id, p.name as plan_name, s.expires_at, s.status as subscription_status,
                    EXTRACT(EPOCH FROM (s.expires_at - CURRENT_TIMESTAMP)) as remaining_seconds
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                LEFT JOIN LATERAL (
                    SELECT * FROM subscriptions sub 
                    WHERE sub.user_id = u.id AND sub.status = 'ACTIVE' AND sub.expires_at > CURRENT_TIMESTAMP
                    ORDER BY sub.expires_at DESC LIMIT 1
                ) s ON true
                LEFT JOIN plans p ON s.plan_id = p.id
                ORDER BY u.id DESC
            """)
            users_list = cur.fetchall()

            result = []
            for u in users_list:
                cert_path = os.path.join(CLIENT_CERTS_DIR, f"{u['username']}.p12")
                u["has_certificate"] = os.path.exists(cert_path)
                result.append(u)
            return result
    finally:
        conn.close()

@app.post("/radius/api/users", tags=["Users"])
@app.post("/api/users", tags=["Users"])
def create_or_update_user(payload: UserCreateRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            group_name = payload.group or "PAID"
            cur.execute("SELECT id FROM groups WHERE name = %s", (group_name,))
            g_row = cur.fetchone()
            if not g_row:
                cur.execute("INSERT INTO groups (name, recharge_required) VALUES (%s, TRUE) RETURNING id", (group_name,))
                group_id = cur.fetchone()["id"]
            else:
                group_id = g_row["id"]

            cur.execute("""
                INSERT INTO users (username, password_hash, email, phone, group_id, recharge_required_override, status, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (username) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    email = COALESCE(EXCLUDED.email, users.email),
                    phone = COALESCE(EXCLUDED.phone, users.phone),
                    group_id = EXCLUDED.group_id,
                    recharge_required_override = EXCLUDED.recharge_required_override,
                    status = EXCLUDED.status,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, (
                payload.username, payload.password, payload.email, payload.phone,
                group_id, payload.recharge_required_override, payload.status or "ACTIVE"
            ))
            user_id = cur.fetchone()["id"]
            conn.commit()

        sync_user_radius_attributes(payload.username)

        log_audit_event(
            actor_type="ADMIN",
            actor_id=current_admin,
            event="USER_SAVED",
            target_type="USER",
            target_id=str(user_id),
            metadata={"username": payload.username, "group": group_name, "status": payload.status}
        )

        return {"status": "success", "id": user_id, "message": f"User '{payload.username}' saved & synced with RADIUS."}
    finally:
        conn.close()

@app.delete("/radius/api/users/{username}", tags=["Users"])
@app.delete("/api/users/{username}", tags=["Users"])
def delete_user(username: str, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username = %s RETURNING id", (username,))
            deleted = cur.fetchone()
            cur.execute("DELETE FROM radcheck WHERE username = %s", (username,))
            cur.execute("DELETE FROM radreply WHERE username = %s", (username,))
            cur.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
            conn.commit()

            log_audit_event(
                actor_type="ADMIN",
                actor_id=current_admin,
                event="USER_DELETED",
                target_type="USER",
                target_id=str(deleted["id"]) if deleted else username,
                metadata={"username": username}
            )
            return {"status": "success", "message": f"User '{username}' deleted successfully"}
    finally:
        conn.close()

@app.put("/radius/api/users/{username}/password", tags=["Users"])
@app.put("/api/users/{username}/password", tags=["Users"])
def update_user_password(username: str, payload: PasswordChangeRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET password_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE username = %s
            """, (payload.password, username))
            conn.commit()

        sync_user_radius_attributes(username)

        log_audit_event(
            actor_type="ADMIN",
            actor_id=current_admin,
            event="PASSWORD_CHANGED",
            target_type="USER",
            target_id=username
        )
        return {"status": "success", "message": f"Password updated for user '{username}'"}
    finally:
        conn.close()

# ============================================================================
# Group Policy Management
# ============================================================================
@app.get("/radius/api/groups", tags=["Groups"])
@app.get("/api/groups", tags=["Groups"])
def list_groups(_: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    g.id, g.name as groupname, g.description, g.recharge_required,
                    g.max_session_seconds, g.bandwidth_down_kbps, g.bandwidth_up_kbps,
                    g.vlan_id, g.is_admin,
                    COUNT(u.id) as user_count
                FROM groups g
                LEFT JOIN users u ON g.id = u.group_id
                GROUP BY g.id, g.name
                ORDER BY g.id ASC
            """)
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/radius/api/groups", tags=["Groups"])
@app.post("/api/groups", tags=["Groups"])
def create_or_update_group(payload: GroupCreateRequest, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO groups (
                    name, description, recharge_required, max_session_seconds,
                    bandwidth_down_kbps, bandwidth_up_kbps, vlan_id, is_admin, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    recharge_required = EXCLUDED.recharge_required,
                    max_session_seconds = EXCLUDED.max_session_seconds,
                    bandwidth_down_kbps = EXCLUDED.bandwidth_down_kbps,
                    bandwidth_up_kbps = EXCLUDED.bandwidth_up_kbps,
                    vlan_id = EXCLUDED.vlan_id,
                    is_admin = EXCLUDED.is_admin,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, (
                payload.groupname, payload.description,
                payload.recharge_required if payload.recharge_required is not None else True,
                payload.session_timeout or 86400,
                payload.bandwidth_down_kbps, payload.bandwidth_up_kbps,
                payload.vlan_id, payload.is_admin or (payload.groupname == "admins")
            ))
            group_id = cur.fetchone()["id"]

            cur.execute("DELETE FROM radgroupreply WHERE groupname = %s", (payload.groupname,))
            cur.execute("DELETE FROM radgroupcheck WHERE groupname = %s", (payload.groupname,))

            if payload.simultaneous_use:
                cur.execute("INSERT INTO radgroupcheck (groupname, attribute, op, value) VALUES (%s, 'Simultaneous-Use', ':=', %s)", (payload.groupname, str(payload.simultaneous_use)))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Simultaneous-Use', '=', %s)", (payload.groupname, str(payload.simultaneous_use)))

            if payload.bandwidth_down_kbps:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'WISPr-Bandwidth-Max-Down', '=', %s)", (payload.groupname, str(payload.bandwidth_down_kbps * 1000)))
            if payload.bandwidth_up_kbps:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'WISPr-Bandwidth-Max-Up', '=', %s)", (payload.groupname, str(payload.bandwidth_up_kbps * 1000)))

            if payload.vlan_id:
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Type', '=', '13')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Medium-Type', '=', '6')", (payload.groupname,))
                cur.execute("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (%s, 'Tunnel-Private-Group-ID', '=', %s)", (payload.groupname, str(payload.vlan_id)))

            conn.commit()

            log_audit_event(
                actor_type="ADMIN",
                actor_id=current_admin,
                event="GROUP_SAVED",
                target_type="GROUP",
                target_id=str(group_id),
                metadata={"name": payload.groupname, "recharge_required": payload.recharge_required}
            )
            return {"status": "success", "id": group_id, "message": f"Group '{payload.groupname}' saved successfully."}
    finally:
        conn.close()

# ============================================================================
# NAS Clients
# ============================================================================
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
def create_nas(payload: NasCreateRequest, current_admin: str = Depends(authenticate_admin)):
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
            log_audit_event(actor_type="ADMIN", actor_id=current_admin, event="NAS_CREATED", target_type="NAS", target_id=str(new_id))
            return {"status": "success", "id": new_id, "message": f"NAS client '{payload.shortname}' added successfully"}
    finally:
        conn.close()

@app.delete("/radius/api/nas/{nas_id}", tags=["NAS"])
@app.delete("/api/nas/{nas_id}", tags=["NAS"])
def delete_nas(nas_id: int, current_admin: str = Depends(authenticate_admin)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nas WHERE id = %s", (nas_id,))
            conn.commit()
            log_audit_event(actor_type="ADMIN", actor_id=current_admin, event="NAS_DELETED", target_type="NAS", target_id=str(nas_id))
            return {"status": "success", "message": f"NAS client #{nas_id} deleted successfully"}
    finally:
        conn.close()

# ============================================================================
# Accounting & Sessions
# ============================================================================
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

@app.post("/radius/api/sessions/disconnect", tags=["Sessions"])
@app.post("/api/sessions/disconnect", tags=["Sessions"])
def disconnect_session_endpoint(payload: DisconnectSessionRequest, current_admin: str = Depends(authenticate_admin)):
    success = disconnect_active_radius_session(payload.username, payload.nas_ip, payload.acct_session_id)
    log_audit_event(
        actor_type="ADMIN",
        actor_id=current_admin,
        event="SESSION_MANUAL_DISCONNECT",
        target_type="USER",
        target_id=payload.username,
        metadata={"nas_ip": payload.nas_ip, "acct_session_id": payload.acct_session_id, "success": success}
    )
    return {
        "success": success,
        "status": "Session Disconnected (ACK)" if success else "Disconnect Request Sent",
        "username": payload.username
    }

# ============================================================================
# PKI & EAP-TLS Certificates
# ============================================================================
@app.get("/radius/api/certs/ca", tags=["Certificates"])
@app.get("/api/certs/ca", tags=["Certificates"])
def download_ca_cert():
    ca_path = os.path.join(CERTS_DIR, "ca.pem")
    if not os.path.exists(ca_path):
        ca_path = os.path.join(CERTS_DIR, "ca.crt")
    if not os.path.exists(ca_path):
        raise HTTPException(status_code=404, detail="CA certificate not found.")
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
    if CERT_SIGNER_API_URL:
        try:
            with open(user_csr_path, "r") as f:
                csr_content = f.read()
            
            headers = {"Content-Type": "application/json"}
            if CERT_SIGNER_API_KEY:
                headers["x-api-key"] = CERT_SIGNER_API_KEY
            
            sans = san_list or [f"{username}@rajlabs.in", f"{username}.local"]
            payload_data = {"csr": csr_content, "san": sans, "days": days}
            req = urllib.request.Request(
                f"{CERT_SIGNER_API_URL}/api/v1/sign",
                data=json.dumps(payload_data).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    if res_json.get("success"):
                        return res_json["certificate"], res_json.get("fullChain") or res_json["certificate"]
        except Exception as e:
            logging.warning(f"Cert-Signer microservice failed ({e}), falling back to local CA.")

    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_pem = os.path.join(CERTS_DIR, "ca.pem")
    if not os.path.exists(ca_key) or not os.path.exists(ca_pem):
        raise HTTPException(status_code=500, detail="No certificate authority available.")

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
def issue_client_certificate(payload: IssueCertRequest, current_admin: str = Depends(authenticate_admin)):
    uname = payload.username
    p12_pass = payload.cert_password or "whatever"
    days = payload.valid_days or 365
    email = payload.email or f"{uname}@rajlabs.in"

    user_key = os.path.join(CLIENT_CERTS_DIR, f"{uname}.key")
    user_csr = os.path.join(CLIENT_CERTS_DIR, f"{uname}.csr")
    user_crt = os.path.join(CLIENT_CERTS_DIR, f"{uname}.crt")
    user_p12 = os.path.join(CLIENT_CERTS_DIR, f"{uname}.p12")

    try:
        subprocess.run(["openssl", "genrsa", "-out", user_key, "2048"], check=True, capture_output=True)
        subj = f"/C=IN/ST=Delhi/O=RajLabs/CN={uname}/emailAddress={email}"
        subprocess.run(["openssl", "req", "-new", "-key", user_key, "-out", user_csr, "-subj", subj], check=True, capture_output=True)

        cert_pem, ca_chain_pem = sign_certificate_with_ca(uname, user_csr, days=days, san_list=[email, f"{uname}.local"])
        with open(user_crt, "w") as f:
            f.write(cert_pem)
        
        ca_chain_file = os.path.join(CLIENT_CERTS_DIR, f"{uname}-chain.crt")
        with open(ca_chain_file, "w") as f:
            f.write(ca_chain_pem)

        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", user_crt, "-inkey", user_key, "-certfile", ca_chain_file,
            "-out", user_p12, "-name", f"RajLabs RADIUS - {uname}",
            "-password", f"pass:{p12_pass}"
        ], check=True, capture_output=True)
        subprocess.run(["chmod", "644", user_p12, user_crt], check=False)

        log_audit_event(actor_type="ADMIN", actor_id=current_admin, event="CERT_ISSUED", target_type="USER", target_id=uname)

        return {
            "status": "success",
            "message": f"Certificate issued for user '{uname}'",
            "username": uname,
            "p12_password": p12_pass,
            "download_url": f"/radius/api/certs/{uname}/download",
            "mobileconfig_url": f"/radius/api/certs/{uname}/mobileconfig"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenSSL error: {str(e)}")

@app.get("/radius/api/certs/{username}/download", tags=["Certificates"])
@app.get("/api/certs/{username}/download", tags=["Certificates"])
def download_client_p12(username: str):
    p12_path = os.path.join(CLIENT_CERTS_DIR, f"{username}.p12")
    if not os.path.exists(p12_path):
        raise HTTPException(status_code=404, detail="Certificate not found.")
    return FileResponse(p12_path, media_type="application/x-pkcs12", filename=f"{username}_rajlabs_radius.p12")

@app.get("/radius/api/certs/{username}/mobileconfig", tags=["Certificates"])
@app.get("/api/certs/{username}/mobileconfig", tags=["Certificates"])
def download_apple_mobileconfig(username: str, ssid: str = "RajLabs-Enterprise"):
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

# ============================================================================
# Live RADIUS Testing (radtest)
# ============================================================================
@app.post("/radius/api/test-auth", tags=["Testing"])
@app.post("/api/test-auth", tags=["Testing"])
def test_radius_authentication(payload: AuthTestRequest, _: str = Depends(authenticate_admin)):
    secret = payload.secret or RADIUS_SECRET
    cmd = ["radtest", payload.username, payload.password, payload.nas_ip or "127.0.0.1", "0", secret]
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
    except Exception as e:
        return {"success": False, "status": "Error", "output": str(e)}

# Mount Static Files & Splash Pages
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/radius/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_root")

@app.get("/radius/portal", response_class=HTMLResponse, tags=["Captive Portal"])
@app.get("/portal", response_class=HTMLResponse, tags=["Captive Portal"])
def get_captive_portal():
    portal_path = os.path.join(STATIC_DIR, "portal.html")
    if os.path.exists(portal_path):
        with open(portal_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RajLabs Wi-Fi Login Portal</h1>")

@app.get("/radius", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/radius/", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
def get_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RajLabs FreeRADIUS Dashboard</h1>")
