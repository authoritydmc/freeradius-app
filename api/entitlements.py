import os
import json
import secrets
import datetime
import subprocess
from typing import Optional, Dict, Any, List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

try:
    from access_engine import get_db_connection, sync_user_radius_attributes
except ImportError:
    from api.access_engine import get_db_connection, sync_user_radius_attributes

RADIUS_SECRET = os.getenv("RADIUS_SECRET", "testing123")

def get_system_setting(key: str, default: str = "", conn=None) -> str:
    """Fetches a dynamic system setting value (e.g. upi_vpa, upi_merchant_name)."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
    finally:
        if should_close:
            conn.close()

def set_system_setting(key: str, value: str, description: Optional[str] = None, conn=None):
    """Sets or updates a dynamic system setting."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_settings (key, value, description, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    description = COALESCE(EXCLUDED.description, system_settings.description),
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value, description))
            conn.commit()
    finally:
        if should_close:
            conn.close()

def log_audit_event(actor_type: str, actor_id: Optional[str], event: str,
                    target_type: Optional[str] = None, target_id: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None, ip: Optional[str] = None, conn=None):
    """Writes an immutable audit log entry."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_events (actor_type, actor_id, event, target_type, target_id, metadata, ip)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                actor_type,
                actor_id,
                event,
                target_type,
                target_id,
                json.dumps(metadata) if metadata else None,
                ip
            ))
            conn.commit()
    except Exception as e:
        logging.error(f"Failed to record audit event {event}: {e}")
    finally:
        if should_close:
            conn.close()

def activate_or_extend_subscription(
    user_id: int,
    plan_id: Optional[int],
    payment_id: Optional[int] = None,
    custom_validity_seconds: Optional[int] = None,
    actor_type: str = "SYSTEM",
    actor_id: Optional[str] = None,
    ip: Optional[str] = None
) -> Dict[str, Any]:
    """
    Idempotently activates or stacks/extends subscription validity.
    Stacking formula: new_expiry = max(now, current_active_expiry) + validity_seconds.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Fetch user
            cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
            user_row = cur.fetchone()
            if not user_row:
                raise ValueError(f"User ID {user_id} not found")
            username = user_row["username"]

            validity_sec = custom_validity_seconds
            plan_name = "Custom Pass"
            if plan_id:
                cur.execute("SELECT id, name, validity_seconds, price FROM plans WHERE id = %s", (plan_id,))
                p_row = cur.fetchone()
                if p_row:
                    plan_name = p_row["name"]
                    if validity_sec is None:
                        validity_sec = p_row["validity_seconds"]

            if not validity_sec or validity_sec <= 0:
                validity_sec = 86400

            now = datetime.datetime.now(datetime.timezone.utc)

            # 2. Check for existing active subscription to stack
            cur.execute("""
                SELECT id, expires_at 
                FROM subscriptions 
                WHERE user_id = %s AND status = 'ACTIVE' AND expires_at > CURRENT_TIMESTAMP
                ORDER BY expires_at DESC
                LIMIT 1
                FOR UPDATE
            """, (user_id,))
            existing_sub = cur.fetchone()

            if existing_sub:
                current_expiry = existing_sub["expires_at"]
                if current_expiry.tzinfo is None:
                    current_expiry = current_expiry.replace(tzinfo=datetime.timezone.utc)
                
                base_time = max(now, current_expiry)
                new_expiry = base_time + datetime.timedelta(seconds=validity_sec)

                cur.execute("""
                    UPDATE subscriptions
                    SET expires_at = %s, plan_id = COALESCE(%s, plan_id),
                        payment_id = COALESCE(%s, payment_id), updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, starts_at, expires_at, status
                """, (new_expiry, plan_id, payment_id, existing_sub["id"]))
                sub_record = dict(cur.fetchone())
                action = "SUBSCRIPTION_EXTENDED"
            else:
                starts_at = now
                new_expiry = now + datetime.timedelta(seconds=validity_sec)
                cur.execute("""
                    INSERT INTO subscriptions (user_id, plan_id, starts_at, expires_at, status, payment_id)
                    VALUES (%s, %s, %s, %s, 'ACTIVE', %s)
                    RETURNING id, starts_at, expires_at, status
                """, (user_id, plan_id, starts_at, new_expiry, payment_id))
                sub_record = dict(cur.fetchone())
                action = "SUBSCRIPTION_CREATED"

            conn.commit()

            # 3. Synchronize FreeRADIUS tables
            sync_user_radius_attributes(username, conn=conn)

            # 4. Audit Log
            log_audit_event(
                actor_type=actor_type,
                actor_id=actor_id or username,
                event=action,
                target_type="USER",
                target_id=str(user_id),
                metadata={
                    "username": username,
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                    "validity_seconds": validity_sec,
                    "expires_at": sub_record["expires_at"].isoformat(),
                    "payment_id": payment_id
                },
                ip=ip,
                conn=conn
            )

            return {
                "status": "success",
                "action": action,
                "subscription_id": sub_record["id"],
                "username": username,
                "plan_name": plan_name,
                "starts_at": sub_record["starts_at"].isoformat(),
                "expires_at": sub_record["expires_at"].isoformat(),
                "validity_seconds_added": validity_sec
            }
    finally:
        conn.close()

def process_verified_payment(
    gateway: str,
    gateway_payment_id: str,
    gateway_order_id: Optional[str],
    user_id: int,
    plan_id: Optional[int],
    amount: float,
    currency: str = "INR",
    raw_reference: Optional[str] = None,
    actor_type: str = "PAYMENT_GATEWAY",
    ip: Optional[str] = None
) -> Dict[str, Any]:
    """
    Idempotent payment ingestion. Guarantees 1 payment = 1 entitlement activation.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, plan_id, status, created_at 
                FROM payments 
                WHERE gateway_payment_id = %s
            """, (gateway_payment_id,))
            existing = cur.fetchone()

            if existing:
                return {
                    "status": "duplicate_acknowledged",
                    "payment_id": existing["id"],
                    "message": "Payment was already processed previously."
                }

            now = datetime.datetime.now(datetime.timezone.utc)
            cur.execute("""
                INSERT INTO payments (
                    user_id, plan_id, gateway, gateway_order_id, gateway_payment_id,
                    amount, currency, status, verified_at, raw_reference
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'SUCCESS', %s, %s)
                RETURNING id
            """, (
                user_id, plan_id, gateway, gateway_order_id, gateway_payment_id,
                amount, currency, now, raw_reference
            ))
            payment_id = cur.fetchone()["id"]
            conn.commit()

            log_audit_event(
                actor_type=actor_type,
                actor_id=gateway,
                event="PAYMENT_VERIFIED",
                target_type="PAYMENT",
                target_id=str(payment_id),
                metadata={
                    "gateway": gateway,
                    "gateway_payment_id": gateway_payment_id,
                    "amount": amount,
                    "currency": currency,
                    "user_id": user_id,
                    "plan_id": plan_id
                },
                ip=ip,
                conn=conn
            )

        sub_res = activate_or_extend_subscription(
            user_id=user_id,
            plan_id=plan_id,
            payment_id=payment_id,
            actor_type="WEBHOOK",
            actor_id=gateway,
            ip=ip
        )

        return {
            "status": "success",
            "payment_id": payment_id,
            "subscription": sub_res
        }
    finally:
        conn.close()

def redeem_voucher(user_id: int, voucher_code: str, ip: Optional[str] = None) -> Dict[str, Any]:
    """
    Validates and redeems a promotional or prepaid voucher code for a user.
    """
    conn = get_db_connection()
    try:
        clean_code = voucher_code.strip().upper()
        now = datetime.datetime.now(datetime.timezone.utc)

        with conn.cursor() as cur:
            cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
            user_row = cur.fetchone()
            if not user_row:
                raise ValueError("User not found")
            username = user_row["username"]

            cur.execute("""
                SELECT id, code, plan_id, validity_seconds, max_uses, current_uses, is_active, expires_at
                FROM vouchers
                WHERE UPPER(code) = %s
                FOR UPDATE
            """, (clean_code,))
            v_row = cur.fetchone()

            if not v_row:
                raise ValueError(f"Invalid voucher code '{clean_code}'")

            if not v_row["is_active"]:
                raise ValueError("This voucher is no longer active.")

            if v_row["expires_at"] and v_row["expires_at"] <= now:
                raise ValueError("This voucher has expired.")

            if v_row["current_uses"] >= v_row["max_uses"]:
                raise ValueError("This voucher has reached its maximum usage limit.")

            # Check if user already redeemed this voucher
            cur.execute("""
                SELECT id FROM voucher_redemptions
                WHERE voucher_id = %s AND user_id = %s
            """, (v_row["id"], user_id))
            if cur.fetchone():
                raise ValueError("You have already redeemed this voucher on your account.")

            # Increment usage
            new_uses = v_row["current_uses"] + 1
            is_active = (new_uses < v_row["max_uses"])
            cur.execute("""
                UPDATE vouchers 
                SET current_uses = %s, is_active = %s
                WHERE id = %s
            """, (new_uses, is_active, v_row["id"]))
            conn.commit()

        # Activate / extend entitlement
        sub_res = activate_or_extend_subscription(
            user_id=user_id,
            plan_id=v_row["plan_id"],
            custom_validity_seconds=v_row["validity_seconds"],
            actor_type="VOUCHER",
            actor_id=clean_code,
            ip=ip
        )

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO voucher_redemptions (voucher_id, user_id, subscription_id)
                VALUES (%s, %s, %s)
            """, (v_row["id"], user_id, sub_res["subscription_id"]))
            conn.commit()

            log_audit_event(
                actor_type="USER",
                actor_id=username,
                event="VOUCHER_REDEEMED",
                target_type="VOUCHER",
                target_id=str(v_row["id"]),
                metadata={"code": clean_code, "validity_seconds": v_row["validity_seconds"]},
                ip=ip,
                conn=conn
            )

        return {
            "status": "success",
            "message": f"Voucher '{clean_code}' redeemed successfully! Validity added.",
            "subscription": sub_res
        }
    finally:
        conn.close()

def batch_generate_vouchers(
    count: int,
    plan_id: Optional[int] = None,
    validity_seconds: Optional[int] = None,
    prefix: str = "WIFI",
    max_uses: int = 1,
    expires_in_days: Optional[int] = 30,
    created_by: str = "ADMIN"
) -> List[Dict[str, Any]]:
    """
    Batch generates unique alphanumeric voucher codes.
    """
    conn = get_db_connection()
    try:
        v_sec = validity_seconds or 86400
        if plan_id:
            with conn.cursor() as cur:
                cur.execute("SELECT validity_seconds FROM plans WHERE id = %s", (plan_id,))
                p_row = cur.fetchone()
                if p_row:
                    v_sec = p_row["validity_seconds"]

        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = (now + datetime.timedelta(days=expires_in_days)) if expires_in_days else None

        generated = []
        with conn.cursor() as cur:
            for _ in range(count):
                random_part = secrets.token_hex(3).upper() # e.g. 7A8B9C
                code = f"{prefix.strip().upper()}-{random_part}"
                cur.execute("""
                    INSERT INTO vouchers (code, plan_id, validity_seconds, max_uses, current_uses, is_active, created_by, expires_at)
                    VALUES (%s, %s, %s, %s, 0, TRUE, %s, %s)
                    RETURNING id, code, validity_seconds, max_uses, expires_at
                """, (code, plan_id, v_sec, max_uses, created_by, expires_at))
                row = cur.fetchone()
                generated.append(dict(row))
            conn.commit()

        return generated
    finally:
        conn.close()

def get_user_usage_stats(username: str) -> Dict[str, Any]:
    """
    Computes total data consumed (upload/download in MB/GB), total session time,
    and active live connections from radacct.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_sessions,
                    COALESCE(SUM(acctinputoctets), 0) as total_upload_bytes,
                    COALESCE(SUM(acctoutputoctets), 0) as total_download_bytes,
                    COALESCE(SUM(acctsessiontime), 0) as total_session_seconds
                FROM radacct
                WHERE username = %s
            """, (username,))
            usage = cur.fetchone() or {}

            cur.execute("""
                SELECT 
                    radacctid, acctsessionid, nasipaddress::text, framedipaddress::text,
                    callingstationid, calledstationid, acctstarttime, acctsessiontime,
                    acctinputoctets, acctoutputoctets
                FROM radacct
                WHERE username = %s AND acctstoptime IS NULL
                ORDER BY radacctid DESC
            """, (username,))
            active_sessions = cur.fetchall()

            total_in = int(usage.get("total_upload_bytes") or 0)
            total_out = int(usage.get("total_download_bytes") or 0)
            total_bytes = total_in + total_out

            return {
                "total_sessions": int(usage.get("total_sessions") or 0),
                "total_upload_mb": round(total_in / (1024 * 1024), 2),
                "total_download_mb": round(total_out / (1024 * 1024), 2),
                "total_data_gb": round(total_bytes / (1024 * 1024 * 1024), 3),
                "total_session_hours": round(int(usage.get("total_session_seconds") or 0) / 3600, 2),
                "active_sessions_count": len(active_sessions),
                "active_sessions": active_sessions
            }
    finally:
        conn.close()

def disconnect_active_radius_session(username: str, nas_ip: str = "127.0.0.1", session_id: Optional[str] = None):
    """Sends RFC 5176 Disconnect-Request packet via radclient to terminate expired user session."""
    cmd = f"echo 'User-Name = \"{username}\"' | radclient -r 1 {nas_ip}:3799 disconnect '{RADIUS_SECRET}'"
    if session_id:
        cmd = f"echo -e 'User-Name = \"{username}\"\\nAcct-Session-Id = \"{session_id}\"' | radclient -r 1 {nas_ip}:3799 disconnect '{RADIUS_SECRET}'"
    
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        return res.returncode == 0
    except Exception as e:
        logging.warning(f"Could not disconnect session for {username}: {e}")
        return False

def run_periodic_expiry_worker():
    """Background worker: expires past-due subscriptions and kicks active sessions."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.id, s.user_id, u.username
                FROM subscriptions s
                JOIN users u ON s.user_id = u.id
                WHERE s.status = 'ACTIVE' AND s.expires_at <= CURRENT_TIMESTAMP
            """)
            expired_rows = cur.fetchall()

            if not expired_rows:
                return 0

            for row in expired_rows:
                sub_id = row["id"]
                uname = row["username"]
                uid = row["user_id"]

                cur.execute("UPDATE subscriptions SET status = 'EXPIRED', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (sub_id,))
                conn.commit()

                sync_user_radius_attributes(uname, conn=conn)

                cur.execute("""
                    SELECT acctsessionid, nasipaddress::text 
                    FROM radacct 
                    WHERE username = %s AND acctstoptime IS NULL
                """, (uname,))
                active_sessions = cur.fetchall()

                for sess in active_sessions:
                    disconnect_active_radius_session(uname, sess["nasipaddress"], sess["acctsessionid"])

                log_audit_event(
                    actor_type="SYSTEM",
                    actor_id="EXPIRY_WORKER",
                    event="ACCOUNT_EXPIRED",
                    target_type="USER",
                    target_id=str(uid),
                    metadata={"username": uname, "subscription_id": sub_id, "disconnected_sessions": len(active_sessions)},
                    conn=conn
                )

            return len(expired_rows)
    finally:
        conn.close()
