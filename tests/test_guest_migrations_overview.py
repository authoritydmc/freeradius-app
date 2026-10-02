"""No-DB regression tests for payment/guest/migration overhaul."""
import os
from pathlib import Path

os.environ.setdefault("RADIUS_SECRET", "TestSecret1234567890!@")
os.environ.setdefault("SESSION_SECRET", "TestSessionSecretLongKey1234567890!@")


def test_generate_session_secret_exists():
    from api.app import generate_session_secret
    s1 = generate_session_secret(24)
    s2 = generate_session_secret(24)
    assert len(s1) == 24 and len(s2) == 24
    assert s1 != s2


def test_migration_files_present_and_baseline_clean():
    mig = Path("api/migrations")
    assert (mig / "001_baseline.sql").exists()
    assert (mig / "002_perf_indexes.sql").exists()
    base = (mig / "001_baseline.sql").read_text()
    # Clean seeds only — no legacy 20/100/250 price rows
    assert "10.00" in base and "51.35" in base
    assert "20.00, 86400" not in base
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" not in base


def test_overview_and_migrate_routes_wired():
    from api.app import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/radius/api/users/{username}/overview" in paths
    # ensure_* shims still importable (backward compat)
    from api.app import ensure_plans_table, ensure_audit_table  # noqa: F401
    from api.migrate import run_migrations, ensure_migrated  # noqa: F401
    from api.db_init import init_all_tables  # noqa: F401


def test_guest_records_zero_rs_sale():
    import inspect
    from api.app import generate_guest_user
    src = inspect.getsource(generate_guest_user)
    assert "GUEST-" in src
    assert "0.00" in src or "0, 0" in src or "0.0" in src
    assert "payment_id" in src
    # UTC-epoch expiry (never wall-clock math) + epoch-ms in response
    assert "gmtime" in src
    assert "expires_at_epoch_ms" in src


def test_reject_reason_fallback_configured():
    text = Path("config/sites-available/default").read_text()
    assert "Post-Auth-Type REJECT" in text
    assert "Reply-Message" in text
    assert "invalid password" in text


def test_expiry_uses_utc_epoch_everywhere():
    import inspect
    from api.entitlements import activate_or_extend_subscription
    src = inspect.getsource(activate_or_extend_subscription)
    assert "timezone.utc" in src
    assert "expires_at_epoch_ms" in src
    # Container + daemon pinned to UTC so wall-time Expiration parses unambiguously
    assert "TZ=UTC" in Path("Dockerfile").read_text()
    assert "TZ=UTC" in Path("scripts/entrypoint.sh").read_text()


def test_console_session_check_and_role_gate():
    src = Path("frontend/src/App.jsx").read_text()
    # Session must validate via the admin-only endpoint, never public /status
    assert "fetchJson('auth/me')" in src
    assert "fetchJson('status')" not in src
    # Regular users get their own self-service dashboard, never admin tabs
    assert "UserDashboard" in src
    assert "currentUser.role !== 'admin'" in src
    # No aggressive polling left (60s background, 60s status tab)
    assert "15000" not in src and "20000" not in src


def test_user_self_service_endpoints():
    from api.app import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/radius/api/me/overview" in paths
    assert "/radius/api/me/password" in paths
    # Self-service auth: any valid session for self — NOT the admin guard,
    # so regular users pass but can only ever see their own account.
    import inspect
    from api.app import get_my_overview, change_own_password
    assert "authenticate_self" in inspect.getsource(get_my_overview)
    assert "authenticate_self" in inspect.getsource(change_own_password)
    assert "authenticate_admin" not in inspect.getsource(get_my_overview)
    # Dashboard covers the user-allowed surface: recharge, own password,
    # certificates, devices/activity, support — no admin affordances.
    dash = Path("frontend/src/components/UserDashboard.jsx").read_text(encoding="utf-8")
    for needle in ("me/overview", "me/password", "portal/enroll-certificate",
                   "certs/", "Recharge", "Change my Wi-Fi password",
                   "Certificates", "My devices", "WhatsApp"):
        assert needle in dash, needle


def test_tester_uses_server_secret():
    src = Path("frontend/src/components/TesterTab.jsx").read_text()
    assert "Shared Secret" not in src
    assert "server secret" in src or "server-side secret" in src


def test_local_time_display_with_tz_label():
    src = Path("frontend/src/utils/api.js").read_text()
    assert "timeZoneName" in src
    assert "1e12" in src  # epoch-ms / epoch-seconds support


def test_exempt_users_shown_as_exempt():
    import inspect
    from api.app import list_users, get_user_overview
    assert "recharge_required" in inspect.getsource(list_users)
    assert "recharge_required" in inspect.getsource(get_user_overview)
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "Exempt" in users_tab
    assert "recharge_required === false" in users_tab
    dossier = Path("frontend/src/components/UserDetailModal.jsx").read_text(encoding="utf-8")
    assert "Exempt from recharge" in dossier
