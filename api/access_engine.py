import os
import datetime
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "radius"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )

def get_access_decision(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Central Access Decision Engine.
    Evaluates:
      1. Account active vs disabled
      2. Group or User recharge exemption requirement
      3. Active subscription / entitlement presence
      4. Dynamic Session-Timeout = min(remaining_validity, max_session_cap, 86400)
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Disabled account check
    if user_info.get("status") == "DISABLED":
        return {
            "decision": "DENY",
            "reason": "Account is disabled",
            "session_timeout": 0,
            "recharge_required": True,
            "remaining_seconds": 0
        }

    # 2. Determine if recharge is required
    # User override takes precedence over Group policy
    override = user_info.get("recharge_required_override")
    if override is not None:
        recharge_required = bool(override)
    else:
        recharge_required = bool(user_info.get("group_recharge_required", True))

    # 3. If recharge NOT required (Free / Staff / VIP / Exempt)
    if not recharge_required:
        group_max = user_info.get("group_max_session_seconds") or 86400
        session_timeout = min(int(group_max), 86400)
        return {
            "decision": "ALLOW",
            "reason": "Account exempt from recharge (Group/User Exemption)",
            "session_timeout": session_timeout,
            "recharge_required": False,
            "remaining_seconds": None,
            "subscription": None
        }

    # 4. Paid / Recharge required tier - Check active subscription
    sub = user_info.get("active_subscription")
    if not sub:
        return {
            "decision": "DENY",
            "reason": "Recharge required. No active subscription found.",
            "session_timeout": 0,
            "recharge_required": True,
            "remaining_seconds": 0
        }

    expires_at = sub.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    elif isinstance(expires_at, datetime.datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)

    remaining = (expires_at - now).total_seconds()
    if remaining <= 0:
        return {
            "decision": "DENY",
            "reason": "Subscription expired. Please recharge to continue.",
            "session_timeout": 0,
            "recharge_required": True,
            "remaining_seconds": 0,
            "subscription": sub
        }

    # Dynamic 1-Day Maximum Session Cap rule:
    # session_timeout = min(remaining_seconds, plan.max_session_seconds or 86400, 86400)
    plan_max = sub.get("plan_max_session_seconds") or 86400
    session_timeout = int(min(remaining, plan_max, 86400))
    if session_timeout <= 0:
        return {
            "decision": "DENY",
            "reason": "Subscription validity exhausted",
            "session_timeout": 0,
            "recharge_required": True,
            "remaining_seconds": 0
        }

    return {
        "decision": "ALLOW",
        "reason": f"Active entitlement valid until {expires_at.isoformat()}",
        "session_timeout": session_timeout,
        "recharge_required": True,
        "remaining_seconds": int(remaining),
        "subscription": sub
    }

def get_user_full_context(username: str, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieves full user context including group, overrides, and latest active subscription."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    u.id, u.username, u.password_hash, u.email, u.phone,
                    u.group_id, u.recharge_required_override, u.status,
                    g.name as group_name, g.recharge_required as group_recharge_required,
                    g.max_session_seconds as group_max_session_seconds,
                    g.bandwidth_down_kbps, g.bandwidth_up_kbps, g.vlan_id
                FROM users u
                LEFT JOIN groups g ON u.group_id = g.id
                WHERE u.username = %s
            """, (username,))
            user_row = cur.fetchone()
            if not user_row:
                return None

            user_data = dict(user_row)

            # Fetch active subscription if any
            cur.execute("""
                SELECT 
                    s.id as subscription_id, s.user_id, s.plan_id, s.starts_at, s.expires_at, s.status,
                    p.name as plan_name, p.price as plan_price, p.validity_seconds,
                    p.max_session_seconds as plan_max_session_seconds
                FROM subscriptions s
                LEFT JOIN plans p ON s.plan_id = p.id
                WHERE s.user_id = %s AND s.status = 'ACTIVE' AND s.expires_at > CURRENT_TIMESTAMP
                ORDER BY s.expires_at DESC
                LIMIT 1
            """, (user_data["id"],))
            sub_row = cur.fetchone()
            user_data["active_subscription"] = dict(sub_row) if sub_row else None
            return user_data
    finally:
        if should_close:
            conn.close()

def sync_user_radius_attributes(username: str, conn=None):
    """
    Synchronizes radcheck, radreply, and radusergroup for FreeRADIUS
    based on the central Access Decision Engine result.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        user_ctx = get_user_full_context(username, conn=conn)
        if not user_ctx:
            return

        decision = get_access_decision(user_ctx)
        
        with conn.cursor() as cur:
            if decision["decision"] == "ALLOW":
                # Ensure credentials are present in radcheck
                cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute = 'Auth-Type'", (username,))
                cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (username,))
                cur.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Cleartext-Password', ':=', %s)
                """, (username, user_ctx["password_hash"]))

                # Ensure group assignment
                group_name = user_ctx["group_name"] or "PAID"
                cur.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
                cur.execute("""
                    INSERT INTO radusergroup (username, groupname, priority)
                    VALUES (%s, %s, 1)
                """, (username, group_name))

                # Inject dynamic Session-Timeout = min(remaining, 86400)
                cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Session-Timeout'", (username,))
                cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Reply-Message'", (username,))
                cur.execute("""
                    INSERT INTO radreply (username, attribute, op, value)
                    VALUES (%s, 'Session-Timeout', '=', %s)
                """, (username, str(decision["session_timeout"])))

            else:
                # DENY - Set Auth-Type := Reject with helpful message
                cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute LIKE '%%Password'", (username,))
                cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute = 'Auth-Type'", (username,))
                cur.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Auth-Type', ':=', 'Reject')
                """, (username,))
                
                cur.execute("DELETE FROM radreply WHERE username = %s AND attribute = 'Reply-Message'", (username,))
                cur.execute("""
                    INSERT INTO radreply (username, attribute, op, value)
                    VALUES (%s, 'Reply-Message', '=', %s)
                """, (username, decision["reason"]))

            conn.commit()
    finally:
        if should_close:
            conn.close()
