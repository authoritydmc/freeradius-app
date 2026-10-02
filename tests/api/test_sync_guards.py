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
    res = app.create_or_update_user(payload, None, "admin")
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
        app.create_or_update_user(payload, None, "admin")
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
    res = app.update_user_password("ram", app.PasswordChangeRequest(password=""), None, "admin")
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


def test_delete_purges_access_and_resets_central(monkeypatch):
    """Delete wipes access + device locks, revokes upstream, keeps ledger (#27)."""
    conn = FakeConn(lambda q, p: [])
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    res = app.delete_user("ram", "admin")
    assert res["status"] == "success"
    stmts = [s for s, _ in conn.log]
    for tbl in ("radcheck", "radreply", "radusergroup",
                "verified_devices", "user_device_policy"):
        assert any(s == f"DELETE FROM {tbl} WHERE username = %s" for s in stmts), tbl
    # Ban can never resurrect: access-control fields reset, ledger retained.
    assert any("UPDATE users SET status = 'ACTIVE'" in s
               and "recharge_required_override = NULL" in s for s in stmts)
    assert not any(s.startswith("DELETE FROM users")
                   or s.startswith("DELETE FROM subscriptions")
                   or s.startswith("DELETE FROM payments") for s in stmts)


def test_duplicate_webhook_acknowledged_without_500(monkeypatch):
    """Concurrent duplicate delivery resolves via ON CONFLICT, no 500 (#29)."""
    import entitlements

    state = {"selects": 0}

    def handler(q, p):
        if "FROM payments" in q and "WHERE gateway_payment_id" in q:
            state["selects"] += 1
            if state["selects"] == 1:
                return []  # first check: unknown...
            return [{"id": 9, "user_id": 7, "plan_id": 2,
                     "status": "SUCCESS", "created_at": "2026-10-02"}]
        if q.startswith("INSERT INTO payments"):
            return []  # ...lost the race: ON CONFLICT DO NOTHING, no row
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(entitlements, "get_db_connection", lambda: conn)
    res = entitlements.process_verified_payment(
        gateway="RAZORPAY", gateway_payment_id="pay_123",
        gateway_order_id="o1", user_id=7, plan_id=2, amount=100.0)
    assert res["status"] == "duplicate_acknowledged"
    assert res["payment_id"] == 9


def test_activation_takes_advisory_lock(monkeypatch):
    """First-time activation serializes per user (stacking, not dupes) (#29)."""
    import datetime
    import entitlements

    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)

    def handler(q, p):
        if "SELECT id, username FROM users" in q:
            return [{"id": 7, "username": "ram"}]
        if "SELECT id, name, validity_seconds, price FROM plans" in q:
            return [{"id": 2, "name": "P", "validity_seconds": 86400, "price": 10.0}]
        if "FROM subscriptions" in q:
            return []
        if q.startswith("INSERT INTO subscriptions"):
            return [{"id": 11, "starts_at": exp, "expires_at": exp, "status": "ACTIVE"}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(entitlements, "get_db_connection", lambda: conn)
    monkeypatch.setattr(entitlements, "sync_user_radius_attributes",
                        lambda *a, **k: {"decision": "ALLOW"})
    res = entitlements.activate_or_extend_subscription(user_id=7, plan_id=2)
    assert res["status"] == "success"
    assert any("pg_advisory_xact_lock" in s for s, _ in conn.log)


def test_voucher_redeem_single_commit(monkeypatch):
    """Quota + entitlement + ledger commit atomically (#29)."""
    import datetime
    import entitlements

    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)

    def handler(q, p):
        if "SELECT id, username FROM users" in q:
            return [{"id": 7, "username": "ram"}]
        if "FROM vouchers" in q and "UPPER(code)" in q:
            return [{"id": 3, "code": "WIFI-AAAA", "plan_id": 2,
                     "validity_seconds": 86400, "max_uses": 1,
                     "current_uses": 0, "is_active": True, "expires_at": exp}]
        if "FROM voucher_redemptions" in q:
            return []
        if "FROM subscriptions s" in q:
            return []
        if q.startswith("INSERT INTO subscriptions"):
            return [{"id": 12, "starts_at": exp, "expires_at": exp, "status": "ACTIVE"}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(entitlements, "get_db_connection", lambda: conn)
    monkeypatch.setattr(entitlements, "sync_user_radius_attributes",
                        lambda *a, **k: {"decision": "ALLOW"})
    res = entitlements.redeem_voucher(7, "wifi-aaaa")
    assert res["status"] == "success"
    commits = [s for s, _ in conn.log if s == "COMMIT"]
    assert len(commits) == 1, f"expected single atomic commit, got {len(commits)}"


def test_voucher_routes_registered():
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/radius/api/vouchers/redeem" in paths
    assert "/radius/api/me/vouchers/redeem" in paths
    assert "/radius/api/vouchers/batch" in paths
    assert "/radius/api/vouchers" in paths


def test_download_token_single_use(monkeypatch):
    """Token downloads work once, then burn; no password in URL (#21)."""
    import datetime
    from fastapi import HTTPException

    state = {"used": False}

    def handler(q, p):
        if "FROM radcheck" in q and "LIKE" in q:
            return [{"username": "ram", "value": "pw123456"}]
        if q.startswith("INSERT INTO portal_download_tokens"):
            return []
        if "FROM portal_download_tokens" in q and "token_hash" in q:
            if state["used"]:
                return [{"username": "ram", "expires_at": None, "used_at": "used"}]
            return [{"username": "ram", "expires_at": None, "used_at": None}]
        if q.startswith("UPDATE portal_download_tokens"):
            state["used"] = True
            return []
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    minted = app.portal_download_token(app.DownloadTokenRequest(username="ram", password="pw123456"), None)
    assert len(minted["token"]) >= 32 and minted["expires_in_seconds"] == 300
    # Valid token, no cert file on disk in tests -> 404 proves auth passed.
    with pytest.raises(HTTPException) as ei:
        app.portal_download_cert(token=minted["token"], request=None)
    assert ei.value.status_code == 404
    # Second use burns.
    with pytest.raises(HTTPException) as ei2:
        app.portal_download_cert(token=minted["token"], request=None)
    assert ei2.value.status_code == 401
    # No token at all -> 401, never password-prompt.
    with pytest.raises(HTTPException) as ei3:
        app.portal_download_cert(token="", request=None)
    assert ei3.value.status_code == 401


def test_download_token_route_registered():
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/radius/api/portal/download-token" in paths


def test_client_ip_ignores_spoofed_headers(monkeypatch):
    """Forwarded headers from untrusted peers must not rewrite identity (#23)."""
    from starlette.datastructures import Headers

    class DummyReq:
        def __init__(self, headers_dict, client_host="203.0.113.9"):
            self.headers = Headers(headers_dict)
            self.client = type("Client", (), {"host": client_host})()

    # Public socket IP + forged XFF/CF headers -> socket IP wins.
    spoofed = DummyReq({"x-forwarded-for": "1.2.3.4",
                        "cf-connecting-ip": "5.6.7.8",
                        "x-real-ip": "9.9.9.9"})
    assert app._client_ip(spoofed) == "203.0.113.9"
    # Trusted proxy (private/docker net) -> first valid forwarded IP wins.
    via_proxy = DummyReq({"x-forwarded-for": "198.51.100.22, 10.0.0.2"},
                         client_host="10.0.0.1")
    assert app._client_ip(via_proxy) == "198.51.100.22"
    # Garbage header values fall back to the socket IP.
    garbage = DummyReq({"x-forwarded-for": "not-an-ip"}, client_host="10.0.0.1")
    assert app._client_ip(garbage) == "10.0.0.1"


def test_shared_rate_limit_enforced_and_zero_disables(monkeypatch):
    """Shared buckets 429 at the limit; per_minute=0 disables (#23)."""
    from fastapi import HTTPException

    def handler(q, p):
        if "SELECT COUNT" in q:
            return [{"c": 99}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    with pytest.raises(HTTPException) as ei:
        app.check_rate_limit(None, "test-scope", 5)
    assert ei.value.status_code == 429
    assert ei.value.headers.get("Retry-After")
    # Disabled limiter never touches the store.
    conn2 = FakeConn(lambda q, p: (_ for _ in ()).throw(AssertionError("no DB expected")))
    monkeypatch.setattr(app, "get_db_connection", lambda: conn2)
    app.check_rate_limit(None, "test-scope", 0)


def test_nas_secret_masked_on_read(monkeypatch):
    """GET /nas never returns the shared secret (#19)."""

    def handler(q, p):
        if "FROM nas" in q:
            return [{"id": 1, "nasname": "10.0.0.1", "shortname": "ap1",
                     "type": "other", "ports": None, "secret": "s3cr3t!",
                     "description": "x"}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    out = app.list_nas("admin")
    assert out[0]["secret"] == ""
    assert out[0]["secret_set"] is True


def test_settings_secrets_masked_and_empty_kept(monkeypatch):
    """Secrets masked on read; blank writes keep existing values (#19)."""

    def handler(q, p):
        if "FROM system_settings" in q:
            return [{"key": "razorpay_key_secret", "value": "live_secret",
                     "description": "", "updated_at": None},
                    {"key": "wifi_ssid", "value": "MySSID",
                     "description": "", "updated_at": None}]
        return []

    conn = FakeConn(handler)
    monkeypatch.setattr(app, "get_db_connection", lambda: conn)
    res = app.get_all_settings("admin")
    assert res["settings"]["razorpay_key_secret"] == ""
    assert res["settings"]["razorpay_key_secret_set"] is True
    assert res["settings"]["wifi_ssid"] == "MySSID"

    # Blank secret must not overwrite...
    conn2 = FakeConn(lambda q, p: [])
    monkeypatch.setattr(app, "get_db_connection", lambda: conn2)
    app.update_settings(app.SystemSettingsUpdateRequest(razorpay_key_secret=""), "admin")
    assert not any("razorpay_key_secret" in s for s, _ in conn2.log)
    # ...but a real value still writes.
    conn3 = FakeConn(lambda q, p: [])
    monkeypatch.setattr(app, "get_db_connection", lambda: conn3)
    app.update_settings(app.SystemSettingsUpdateRequest(razorpay_key_secret="new_secret"), "admin")
    assert any("razorpay_key_secret" in s and s.startswith("INSERT") for s, _ in conn3.log)


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
    res = app.bulk_reset_passwords(payload, None, "admin")
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
