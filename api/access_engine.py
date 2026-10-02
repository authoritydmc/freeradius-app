import os
import datetime
from typing import Dict, Any, Optional
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
    """Retrieves full user context including group, overrides, and latest active subscription.

    Group policy resolution (first hit wins):
      1. central users.group_id -> groups (preferred, admin-maintained)
      2. RADIUS radusergroup membership -> central groups by name
         (covers users whose central group_id is stale/missing)
      3. RADIUS radgroupreply RajLabs-Recharge-Exempt / Administrative-User flag
         (covers policy groups created only in RADIUS tables)
      4. default: recharge required.
    """
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

            if user_data.get("group_recharge_required") is None:
                # Fallback: resolve via live RADIUS membership, not the cached group_id.
                fallback_name, fallback_recharge, fallback_max = _resolve_group_policy(cur, username)
                if fallback_name is not None:
                    user_data["group_name"] = user_data.get("group_name") or fallback_name
                if fallback_recharge is not None:
                    user_data["group_recharge_required"] = fallback_recharge
                else:
                    user_data["group_recharge_required"] = True
                if fallback_max is not None and not user_data.get("group_max_session_seconds"):
                    user_data["group_max_session_seconds"] = fallback_max

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


def _resolve_group_policy(cur, username: str):
    """Best-effort (group_name, recharge_required, max_session_seconds) for a user.

    Never raises: any lookup failure yields (None, None, None) so the caller
    falls back to recharge-required.
    """
    try:
        cur.execute("SELECT groupname FROM radusergroup WHERE username = %s ORDER BY priority ASC LIMIT 1", (username,))
        row = cur.fetchone()
        group_name = (row.get("groupname") or "").strip() if row else ""
        if not group_name:
            return None, None, None
        try:
            cur.execute("SELECT recharge_required, max_session_seconds FROM groups WHERE UPPER(name) = UPPER(%s) LIMIT 1", (group_name,))
            grow = cur.fetchone()
            if grow and grow.get("recharge_required") is not None:
                return group_name, bool(grow.get("recharge_required")), grow.get("max_session_seconds")
        except Exception:
            pass
        # RADIUS-native exempt markers (written by the Groups admin UI).
        try:
            cur.execute("SELECT attribute, value FROM radgroupreply WHERE groupname = %s", (group_name,))
            exempt = False
            for r in (cur.fetchall() or []):
                if r.get("attribute") == "RajLabs-Recharge-Exempt" and (r.get("value") or "") == "1":
                    exempt = True
                if r.get("attribute") == "Service-Type" and (r.get("value") or "") == "Administrative-User":
                    exempt = True
            if exempt:
                return group_name, False, None
        except Exception:
            pass
        return group_name, None, None
    except Exception:
        return None, None, None

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
                # Clear any stale reject marker. Credentials are deliberately
                # PRESERVED: radcheck holds the live Wi-Fi password (written by
                # user create / password reset flows). Overwriting it here with
                # users.password_hash used to break logins after every
                # recharge, because central rows created at onboarding carry a
                # random placeholder — users then had to "reset password" to
                # get back online. Only seed a password when none exists.
                cur.execute("DELETE FROM radcheck WHERE username = %s AND attribute = 'Auth-Type'", (username,))
                cur.execute("SELECT 1 FROM radcheck WHERE username = %s AND attribute LIKE '%%Password' LIMIT 1", (username,))
                if not cur.fetchone() and user_ctx.get("password_hash"):
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
