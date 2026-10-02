"""Guards for the subscription/exempt/accounting fixes.

- sync_user_radius_attributes must never clobber a working radcheck password
  (recharge used to break logins until a manual password reset).
- Group exempt must resolve via RADIUS membership/flags, not only the cached
  central users.group_id.
- Group save must mirror central groups + re-sync members.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api"))

import app
import access_engine


class FakeCursor:
    def __init__(self, handler, log):
        self._handler = handler
        self._log = log
        self._rows = []

    def execute(self, q, p=None):
        flat = " ".join(str(q).split())
        self._log.append((flat[:160], p))
        self._rows = self._handler(flat, p) or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, handler, log=None):
        self._handler = handler
        self.log = log if log is not None else []

    def cursor(self):
        return FakeCursor(self._handler, self.log)

    def commit(self):
        self.log.append(("COMMIT", None))

    def close(self):
        pass


def _user_row(**kw):
    base = {
        "id": 7, "username": "ram", "password_cleartext": "9876543210Ram@",
        "email": None, "phone": None, "group_id": None,
        "recharge_required_override": None, "status": "ACTIVE",
        "group_name": None, "group_recharge_required": None,
        "group_max_session_seconds": None, "bandwidth_down_kbps": None,
        "bandwidth_up_kbps": None, "vlan_id": None,
    }
    base.update(kw)
    return base


def test_sync_allow_preserves_existing_password():
    """ALLOW must not delete/rewrite a working radcheck password."""
    pw_exists = {"yes": True}

    def handler(q, p):
        if "FROM users u" in q:
            return [_user_row(group_recharge_required=False)]  # exempt -> ALLOW
        if "FROM subscriptions s" in q:
            return []
        if "attribute LIKE" in q and "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}] if pw_exists["yes"] else []
        return []

    conn = FakeConn(handler)
    access_engine.sync_user_radius_attributes("ram", conn=conn)
    stmts = [s for s, _ in conn.log]
    assert any("Auth-Type" in s and s.startswith("DELETE") for s in stmts)
    assert not any("%%Password" in s and s.startswith("DELETE") for s in stmts), \
        "sync must not delete existing password rows"
    assert not any("Cleartext-Password" in s and s.startswith("INSERT") for s in stmts), \
        "sync must not rewrite an existing password"


def test_sync_allow_seeds_missing_password():
    """ALLOW seeds a credential only when radcheck has none."""

    def handler(q, p):
        if "FROM users u" in q:
            return [_user_row(group_recharge_required=False)]
        if "FROM subscriptions s" in q:
            return []
        if "attribute LIKE" in q and "SELECT 1 FROM radcheck" in q:
            return []
        return []

    conn = FakeConn(handler)
    access_engine.sync_user_radius_attributes("ram", conn=conn)
    inserts = [ (s, p) for s, p in conn.log if "Cleartext-Password" in s and s.startswith("INSERT")]
    assert len(inserts) == 1
    assert inserts[0][1][1] == "9876543210Ram@"


def test_exempt_falls_back_to_radius_group_flag():
    """Group exempt works even when central users.group_id is stale/missing."""

    def handler(q, p):
        if "FROM users u" in q:
            return [_user_row()]  # group_id NULL -> join yields None
        if "FROM radusergroup" in q:
            return [{"groupname": "vip"}]
        if "FROM groups WHERE UPPER(name)" in q:
            return []  # no central row for custom group
        if "FROM radgroupreply WHERE groupname" in q:
            return [{"attribute": "RajLabs-Recharge-Exempt", "value": "1"}]
        if "FROM subscriptions s" in q:
            return []
        return []

    conn = FakeConn(handler)
    ctx = access_engine.get_user_full_context("ram", conn=conn)
    assert ctx["group_recharge_required"] is False
    decision = access_engine.get_access_decision(ctx)
    assert decision["decision"] == "ALLOW"


def test_group_save_mirrors_central_and_resyncs(monkeypatch):
    """Saving a group writes central groups + re-syncs members immediately."""
    synced = []

    def handler(q, p):
        if "SELECT DISTINCT username FROM radusergroup" in q:
            return [{"username": "u1"}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    monkeypatch.setattr(access_engine, "sync_user_radius_attributes",
                        lambda uname, conn=None: synced.append(uname))

    payload = app.GroupCreateRequest(groupname="vip", recharge_required=False)
    res = app.create_or_update_group(payload, "admin")
    assert res["status"] == "success"
    assert "re-synced" in res["message"]
    assert any("INSERT INTO groups" in s for s, _ in conn.log), \
        "group save must mirror the central groups table"
    assert synced == ["u1"]


def test_new_routes_registered():
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/radius/api/accounting/gaps" in paths
    assert "/radius/api/public/ca-info" in paths


def test_simultaneous_use_nullable_means_no_limit():
    """Blank Simultaneous-Use must validate as null (backend then skips the row)."""
    req = app.GroupCreateRequest(groupname="vip", simultaneous_use=None)
    assert req.simultaneous_use is None
    req2 = app.GroupCreateRequest(groupname="vip", simultaneous_use=2)
    assert req2.simultaneous_use == 2


def test_devices_include_auth_seen_macs(monkeypatch):
    """Devices tab lists login-seen MACs even with zero accounting rows."""
    import datetime

    def handler(q, p):
        if "FROM radpostauth" in q:
            return [{
                "mac": "AABBCCDDEEFF",
                "attempts": 3,
                "last_seen": datetime.datetime(2026, 10, 2, 12, 0, 0),
                "username": "ram",
                "ap": "AA:BB:CC:DD:EE:FF:RajLabs-Enterprise",
            }]
        return []  # no radacct rows at all

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    out = app.list_devices(username=None, limit=200, _="admin")
    assert len(out) == 1
    dev = out[0]
    assert dev["source"] == "auth"
    assert dev["mac"] == "AA:BB:CC:DD:EE:FF"
    assert dev["sessions"] == 0
    assert dev["auth_attempts"] == 3
    assert dev["username"] == "ram"


def test_create_user_blank_password_uses_phone(monkeypatch):
    """Blank password on create defaults to the phone number digits."""

    def handler(q, p):
        if "SELECT 1 FROM radcheck" in q:
            return []  # new user
        if "SELECT id FROM groups" in q:
            return []
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    payload = app.UserCreateRequest(username="ram", password="",
                                    group="staff", phone="+919876543210")
    res = app.create_or_update_user(payload, "admin")
    assert res["password"] == "919876543210"
    assert res["password_source"] == "phone"
    inserts = [(s, p) for s, p in conn.log if s.startswith("INSERT INTO radcheck")]
    assert inserts and inserts[0][1][1] == "919876543210"


def test_create_user_blank_password_without_phone_rejected(monkeypatch):
    """Blank password with no phone must 422 (nothing to default to)."""
    from fastapi import HTTPException

    conn = FakeConn(lambda q, p: [])
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    payload = app.UserCreateRequest(username="ram", password="")
    with pytest.raises(HTTPException) as ei:
        app.create_or_update_user(payload, "admin")
    assert ei.value.status_code == 422


def test_reset_blank_password_uses_phone(monkeypatch):
    """Blank password on reset falls back to the stored phone number."""

    def handler(q, p):
        if "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}]
        if "SELECT phone FROM users" in q:
            return [{"phone": "+919876543210"}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    res = app.update_user_password("ram", app.PasswordChangeRequest(password=""), "admin")
    assert res["password"] == "919876543210"
    assert res["password_source"] == "phone"


def _capture_connect(monkeypatch):
    """Replace psycopg2.connect with a recorder; returns (calls, restore)."""
    import psycopg2

    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("no real DB in unit tests")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)
    return calls


def test_multihost_failover_kwargs_all_connectors(monkeypatch):
    """POSTGRES_HOST='primary,standby' lands writes on the primary node."""
    import migrate

    calls = _capture_connect(monkeypatch)

    monkeypatch.setattr(app, "POSTGRES_HOST", "pg-primary,pg-standby")
    with pytest.raises(RuntimeError):
        app.get_db_connection()
    assert calls[-1]["host"] == "pg-primary,pg-standby"
    assert calls[-1].get("target_session_attrs") == "read-write"

    monkeypatch.setenv("POSTGRES_HOST", "pg-primary,pg-standby")
    with pytest.raises(RuntimeError):
        access_engine.get_db_connection()
    assert calls[-1].get("target_session_attrs") == "read-write"
    with pytest.raises(RuntimeError):
        migrate.get_db_connection()
    assert calls[-1].get("target_session_attrs") == "read-write"


def test_single_host_omits_failover_kwarg(monkeypatch):
    """Single host keeps legacy connect kwargs (zero behaviour change)."""
    calls = _capture_connect(monkeypatch)
    monkeypatch.setattr(app, "POSTGRES_HOST", "localhost")
    with pytest.raises(RuntimeError):
        app.get_db_connection()
    assert "target_session_attrs" not in calls[-1]


def test_sync_allow_stamps_expiration_from_subscription():
    """ALLOW with a subscription upserts wall-clock Expiration (#25)."""
    import datetime

    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
    exp_utc = exp.astimezone(datetime.timezone.utc)

    def handler(q, p):
        if "FROM users u" in q:
            return [_user_row(group_recharge_required=True)]
        if "FROM subscriptions s" in q:
            return [{"subscription_id": 1, "user_id": 7, "plan_id": 2,
                     "starts_at": exp_utc, "expires_at": exp_utc, "status": "ACTIVE",
                     "plan_name": "P", "plan_price": 10.0, "validity_seconds": 86400,
                     "plan_max_session_seconds": 86400}]
        if "attribute LIKE" in q and "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}]
        return []

    conn = FakeConn(handler)
    access_engine.sync_user_radius_attributes("ram", conn=conn)
    exp_inserts = [(s, p) for s, p in conn.log
                   if s.startswith("INSERT INTO radcheck") and "Expiration" in s]
    assert len(exp_inserts) == 1
    assert exp_inserts[0][1][1] == exp_utc.strftime("%d %b %Y %H:%M:%S")


def test_sync_allow_exempt_drops_stale_expiration():
    """ALLOW without subscription deletes lingering guest Expiration (#25)."""

    def handler(q, p):
        if "FROM users u" in q:
            return [_user_row(group_recharge_required=False)]
        if "FROM subscriptions s" in q:
            return []
        if "attribute LIKE" in q and "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}]
        return []

    conn = FakeConn(handler)
    access_engine.sync_user_radius_attributes("ram", conn=conn)
    stmts = [s for s, _ in conn.log]
    assert any(s.startswith("DELETE FROM radcheck") and "Expiration" in s for s in stmts)
    assert not any(s.startswith("INSERT INTO radcheck") and "Expiration" in s for s in stmts)

def test_delete_group_resyncs_members(monkeypatch):
    """Group delete re-derives former members immediately (#25)."""
    synced = []

    def handler(q, p):
        if "SELECT DISTINCT username FROM radusergroup" in q:
            return [{"username": "u1"}, {"username": "u2"}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    monkeypatch.setattr(access_engine, "sync_user_radius_attributes",
                        lambda uname, conn=None: (synced.append(uname), {"decision": "ALLOW"})[1])
    res = app.delete_group("vip", "admin")
    assert res["status"] == "success"
    assert "re-synced" in res["message"]
    assert sorted(synced) == ["u1", "u2"]


def test_sync_deny_preserves_password_rows():
    """DENY blocks via Auth-Type Reject only — credentials survive (#28)."""

    def handler(q, p):
        if "FROM users u" in q:
            return [_user_row(group_recharge_required=True)]
        if "FROM subscriptions s" in q:
            return []  # no sub -> DENY
        if "attribute LIKE" in q and "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}]
        return []

    conn = FakeConn(handler)
    decision = access_engine.sync_user_radius_attributes("ram", conn=conn)
    assert decision["decision"] == "DENY"
    stmts = [s for s, _ in conn.log]
    assert not any("Password" in s and s.startswith("DELETE") for s in stmts), \
        "DENY must not wipe credentials"
    assert any(s.startswith("INSERT INTO radcheck") and "Reject" in s for s in stmts)


def test_bulk_reset_on_deny_user_keeps_password(monkeypatch):
    """Bulk-issued passwords survive the trailing resync on DENY users (#28)."""

    def main_handler(q, p):
        if "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}]
        return []

    def sync_handler(q, p):
        if "FROM users u" in q:
            return [_user_row(group_recharge_required=True)]
        if "FROM subscriptions s" in q:
            return []
        if "attribute LIKE" in q and "SELECT 1 FROM radcheck" in q:
            return [{"1": 1}]
        return []

    main_conn = FakeConn(main_handler)
    sync_conn = FakeConn(sync_handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: main_conn)
    monkeypatch.setattr(access_engine, "get_db_connection", lambda: sync_conn)
    payload = app.BulkPasswordResetRequest(usernames=["ram"], mode="random", length=14)
    res = app.bulk_reset_passwords(payload, "admin")
    assert res["reset"] == 1
    new_pw = res["results"][0]["password"]
    assert new_pw and len(new_pw) == 14
    # Password written (exactly one pre-write delete + one insert)...
    writes = [(s, p) for s, p in main_conn.log
              if s.startswith("INSERT INTO radcheck") and "Cleartext-Password" in s]
    assert writes and writes[0][1][1] == new_pw
    pre_deletes = [s for s, _ in main_conn.log
                   if "Password" in s and s.startswith("DELETE")]
    assert len(pre_deletes) == 1
    # ...and never deleted afterwards by the DENY resync.
    assert not any("Password" in s and s.startswith("DELETE")
                   for s, _ in sync_conn.log)
