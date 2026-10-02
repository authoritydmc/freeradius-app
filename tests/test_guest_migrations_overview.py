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


def test_freeradius_control_attrs_are_dictionary_known():
    """freeradius -C rejects unknown attributes, which boot-loops the
    container. Every control: attribute our shipped configs touch must be a
    stock-dictionary one (Tmp-String-N scratch space, Auth-Type, ...)."""
    import re
    known = {"Auth-Type"} | {f"Tmp-String-{i}" for i in range(9)} | {f"Tmp-Integer-{i}" for i in range(9)}
    files = [
        Path("config/sites-available/default"),
        Path("config/mods-available/sql"),
        Path("config/policy.d/rajlabs"),
    ]
    for f in files:
        if not f.exists():
            continue
        text = f.read_text()
        for m in re.finditer(r"&control:([A-Za-z0-9_\-]+)", text):
            assert m.group(1) in known, f"{f}: unknown control attribute '{m.group(1)}' would fail freeradius -C"
        for block in re.finditer(r"update\s+control\s*\{([^}]*)\}", text):
            for m in re.finditer(r"([A-Za-z0-9_\-]+)\s*:=", block.group(1)):
                assert m.group(1) in known, f"{f}: unknown control attribute '{m.group(1)}' would fail freeradius -C"


def test_postauth_query_logs_no_password():
    """Attempted passwords must never reach radpostauth.pass (#18)."""
    text = Path("config/mods-available/sql").read_text()
    m = __import__("re").search(r"postauth_query\s*=\s*\"(.*)\"", text)
    assert m, "postauth_query override missing"
    query = m.group(1)
    assert "User-Password" not in query
    assert "Chap-Password" not in query


def test_radius_sql_interpolations_are_quote_guarded():
    """Every %{attr} reaching SQL must sit inside replace(...''''...'''')
    — rlm_sql does not escape expansions and PQexec runs stacked
    statements, so a bare '%{User-Name}' is injectable (#20)."""
    import re
    for f in (Path("config/mods-available/sql"),
              Path("config/sites-available/default")):
        # Comments (own documentation) carry no executable interpolations.
        text = "\n".join(l for l in f.read_text().splitlines()
                         if not l.lstrip().startswith("#"))
        # Strip guarded occurrences — replace('%{...}', ''''...) quote-doubling —
        # then fail on any leftover interpolation inside SQL string context.
        guarded = re.sub(r"replace\('%\{[^}]*\}',\s*'{4}", "", text)
        for m in re.finditer(r"%\{(User-Name|User-Password|Chap-Password|Calling-Station-Id|Called-Station-Id|EAP-Type|reply:[^}]*)\}", guarded):
            # Allowed only outside SQL strings: reply:Packet-Type etc. in
            # non-SQL unlang is fine — flag it only inside single quotes.
            line_start = guarded.rfind("\n", 0, m.start()) + 1
            before = guarded[line_start:m.start()]
            if before.count("'") % 2 == 1:
                raise AssertionError(f"{f}: unguarded SQL interpolation '%{{{m.group(1)}}}'")


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


def test_group_restricted_plans():
    import inspect
    from api.app import (
        list_plans, create_or_update_plan, manual_activate_payment,
        scan_email_payments, check_plan_group_access,
    )
    # Schema migration exists
    assert Path("api/migrations/003_plan_group_access.sql").exists()
    # Plans API carries group scope end to end
    assert "allowed_groups" in inspect.getsource(list_plans)
    assert "allowed_groups" in inspect.getsource(create_or_update_plan)
    # Admin 1-click overrides loudly instead of silently leaking VIP plans
    assert "group_warning" in inspect.getsource(manual_activate_payment)
    # Automated email recon never overrides a restriction
    assert "skipped_group_restriction" in inspect.getsource(scan_email_payments)
    # No restriction rows => everyone allowed
    assert "everyone" in inspect.getsource(check_plan_group_access).lower()
    # Plan manager UI assigns groups; buying surfaces respect them
    pm = Path("frontend/src/components/PlansManager.jsx").read_text(encoding="utf-8")
    assert "allowed_groups" in pm and "Available to groups" in pm
    portal = Path("frontend/src/components/PortalView.jsx").read_text(encoding="utf-8")
    assert "visiblePlans" in portal
    dash = Path("frontend/src/components/UserDashboard.jsx").read_text(encoding="utf-8")
    assert "visiblePlans" in dash


def test_password_qr_auth_and_compact_groups():
    import inspect
    from api.app import update_user_password
    # Reset flow hits the real endpoint (PUT .../password), never a missing route
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "users/${encodeURIComponent(resetUsername)}/password" in users_tab
    assert "reset-password" not in users_tab
    # Reset modal: copy button + new-password labeling + Save & QR.
    # Passwords are cleartext (MS-CHAP needs it), so the modal says the
    # current one can't be shown and offers blank = phone-number reset.
    assert "Copy new password" in users_tab
    assert "can't be shown" in users_tab
    assert "Blank = reset to phone number" in users_tab
    assert "Save & QR" in users_tab
    # Table test-auth prompts for the secret and runs a real verdict
    assert "Test Auth:" in users_tab and "runAuthTest" in users_tab
    assert "body: JSON.stringify({ username, password: '' })" not in users_tab
    # QR embeds the known password (reset handoff passes it through)
    qr = Path("frontend/src/components/WifiQrModal.jsx").read_text(encoding="utf-8")
    assert "user?.password" in qr
    # Groups tab is compact rows, not bulky cards
    groups = Path("frontend/src/components/GroupsTab.jsx").read_text(encoding="utf-8")
    assert "min-w-[760px]" in groups
    assert "md:grid-cols-2 lg:grid-cols-3" not in groups
    assert "app.put" in inspect.getsource(update_user_password)


def test_cert_handoff_popup_and_upstream_revoke():
    import inspect
    from api.app import (
        revoke_client_certificate, delete_client_certificate,
        delete_orphaned_certificate, revoke_upstream_certificate,
    )
    # Delete/revoke go upstream (signer delete API + CRL) with local ledger
    assert Path("api/migrations/004_revoked_certificates.sql").exists()
    assert "/api/v1/certificates/" in inspect.getsource(revoke_upstream_certificate)
    assert "revoke_upstream_certificate" in inspect.getsource(delete_client_certificate)
    assert "record_cert_revocation" in inspect.getsource(delete_client_certificate)
    assert "record_cert_revocation" in inspect.getsource(revoke_client_certificate)
    assert "record_cert_revocation" in inspect.getsource(delete_orphaned_certificate)
    # Fresh issue clears the revocation record
    from api.app import issue_client_certificate
    assert "clear_cert_revocation" in inspect.getsource(issue_client_certificate)
    # Gated handoff popup: password shown once, close requires copy/download
    modal = Path("frontend/src/components/CertIssuedModal.jsx").read_text(encoding="utf-8")
    assert "shown once" in modal and "attemptClose" in modal
    for f in ("UsersTab.jsx", "CertsTab.jsx", "UserDashboard.jsx"):
        src = Path(f"frontend/src/components/{f}").read_text(encoding="utf-8")
        assert "CertIssuedModal" in src, f


def test_phone_onboarding():
    import inspect
    from api.app import create_or_update_user, update_user_profile, list_users
    assert "phone" in inspect.getsource(create_or_update_user)
    assert "phone" in inspect.getsource(update_user_profile)
    assert "phone" in inspect.getsource(list_users)
    modal = Path("frontend/src/components/OnboardModal.jsx").read_text(encoding="utf-8")
    assert "wa.me" in modal and "sms:" in modal
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "OnboardModal" in users_tab and "phone" in users_tab


def test_utr_handoff_is_honest():
    """The portal UTR form must never imply auto-activation (#35)."""
    portal = Path("frontend/src/components/PortalView.jsx").read_text(encoding="utf-8")
    assert "does NOT auto-activate" in portal
    assert "recorded for user" not in portal
    assert "auto-activated in 2 minutes" not in portal
    cred = Path("frontend/src/components/CredResultModal.jsx").read_text(encoding="utf-8")
    assert "wa.me/${phoneDigits}" in cred


def test_onboarding_invite_with_password_and_wifi_url():

    api_js = Path("frontend/src/utils/api.js").read_text(encoding="utf-8")
    assert "WIFI_PORTAL_BASE_URL" in api_js
    assert "wifi.rajlabs.in" in api_js
    modal = Path("frontend/src/components/OnboardModal.jsx").read_text(encoding="utf-8")
    # Password included when known, markup-highlighted, wifi-domain links
    assert "initialPassword" in modal
    assert "*Password:*" in modal
    assert "portalUrlFor" in modal
    assert "window.location.origin" not in modal
    # Creation handoff prefills it; credential card uses the same domain
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "lastCreatedCreds" in users_tab
    cred = Path("frontend/src/components/CredResultModal.jsx").read_text(encoding="utf-8")
    assert "portalUrlFor" in cred and "window.location.origin" not in cred
    qr = Path("frontend/src/components/WifiQrModal.jsx").read_text(encoding="utf-8")
    assert "portalUrlFor" in qr


def test_log_dossiers_and_users_redesign():
    import inspect
    from api.app import _redacted_settings
    # Secrets never reach the audit trail in readable form
    red = _redacted_settings({
        "upi_vpa": "wifi@rajlabs",
        "email_imap_password": "hunter2",
        "razorpay_key_secret": "s3cr3t",
        "cashfree_app_id": "public-id-1",
    })
    assert red["upi_vpa"] == "wifi@rajlabs"
    assert red["email_imap_password"] == "***REDACTED***"
    assert red["razorpay_key_secret"] == "***REDACTED***"
    assert red["cashfree_app_id"] == "public-id-1"
    # Log rows open a dossier modal with parsed pairs + copy
    logs = Path("frontend/src/components/LogsTab.jsx").read_text(encoding="utf-8")
    assert "LogDetailModal" in logs and "cursor-pointer" in logs
    modal = Path("frontend/src/components/LogDetailModal.jsx").read_text(encoding="utf-8")
    assert "parseDetailPairs" in modal and "Copy JSON" in modal
    # Users table: sticky identity, relative countdowns, overflow menu
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "sticky left-10" in users_tab
    assert "timeLeft(" in users_tab
    assert "RowMenu" in users_tab
    assert "quickBan" in users_tab and "quickRevoke" in users_tab
    assert Path("frontend/src/components/RowMenu.jsx").exists()
    api_js = Path("frontend/src/utils/api.js").read_text(encoding="utf-8")
    assert "timeLeft" in api_js


def test_subscription_revoke_and_narrow_user_column():
    import inspect
    from api.app import revoke_subscription_endpoint
    from api.entitlements import revoke_subscription
    from api.app import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/radius/api/subscriptions/{subscription_id}/revoke" in paths
    # Engine cancels, re-syncs RADIUS and kicks sessions with audit
    src = inspect.getsource(revoke_subscription)
    assert "CANCELLED" in src and "sync_user_radius_attributes" in src
    assert "SUBSCRIPTION_REVOKED" in src
    # Dossier exposes per-subscription revoke for ACTIVE rows
    dossier = Path("frontend/src/components/UserDetailModal.jsx").read_text(encoding="utf-8")
    assert "handleRevoke" in dossier and "subscriptions/${sub.id}/revoke" in dossier
    # Narrow sticky identity column keeps other columns reachable on phones
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "max-w-[104px]" in users_tab


def test_ban_bulk_and_inline_feedback():
    import inspect
    from api.app import ban_user, unban_user, bulk_user_action, list_users
    from api.app import BAN_MESSAGE, _apply_user_ban
    # Ban is password-preserving: only toggles Reject rows, never touches secrets
    helper = inspect.getsource(_apply_user_ban)
    assert "Auth-Type" in helper and "LIKE '%%Password'" not in helper
    assert "banned" in inspect.getsource(list_users)
    # Bulk endpoint covers ban/unban/revoke/delete with per-user results
    src = inspect.getsource(bulk_user_action)
    assert "revoke_certs" in src and "succeeded" in src
    # Shared inline-feedback buttons exist and are actually used
    ab = Path("frontend/src/components/ActionButton.jsx").read_text(encoding="utf-8")
    assert "AsyncButton" in ab and "CopyButton" in ab
    for f, needle in (
        ("UsersTab.jsx", "AsyncButton"),
        ("UsersTab.jsx", "CopyButton"),
        ("UsersTab.jsx", "runBulkAction"),
        ("UsersTab.jsx", "BANNED"),
        ("UsersTab.jsx", "resetResult"),
        ("UsersTab.jsx", "saveResult"),
        ("CertsTab.jsx", "AsyncButton"),
        ("GroupsTab.jsx", "AsyncButton"),
        ("SessionsTab.jsx", "AsyncButton"),
        ("PlansManager.jsx", "AsyncButton"),
        ("CredResultModal.jsx", "CopyButton"),
        ("OnboardModal.jsx", "CopyButton"),
        ("WifiQrModal.jsx", "CopyButton"),
    ):
        assert needle in Path(f"frontend/src/components/{f}").read_text(encoding="utf-8"), f"{f}:{needle}"


def test_upi_invoice_note_and_guest_lifecycle():
    from api.payment_engine import parse_bank_upi_text
    # New canonical note carries username + invoice + plan
    r = parse_bank_upi_text("Rs. 51.35 credited by UPI/CRED/123456789012/WIFI:guest-9185:20261002-K7Q2:3.")
    assert r["matched"] is True
    assert r["username"] == "guest-9185"
    assert r["invoice"] == "20261002-K7Q2"
    assert r["plan_id"] == 3
    # Legacy notes keep parsing exactly as before
    old = parse_bank_upi_text("Rs. 30.0 credited Ref No 987654321098 Note wifi:aman.")
    assert (old["username"], old["plan_id"], old["invoice"]) == ("aman", None, None)
    old2 = parse_bank_upi_text("Rs. 10 credited UTR 111122223333 wifi:raj:1")
    assert (old2["username"], old2["plan_id"]) == ("raj", 1)
    # Portal QR builds a spec-shaped UPI intent with the invoice note
    portal = Path("frontend/src/components/PortalView.jsx").read_text(encoding="utf-8")
    assert "WIFI:${u}:${getInvoice(plan.id, u)}:${plan.id}" in portal
    assert "upi://pay?${params.toString()}" in portal
    # Portal guests get a 24h Expiration and are auto-purged when it lapses
    import inspect
    from api.app import portal_create_guest_pass
    from api.entitlements import cleanup_expired_guest_accounts
    assert "Expiration" in inspect.getsource(portal_create_guest_pass)
    assert "guest\\_%" in inspect.getsource(cleanup_expired_guest_accounts) or "guest\\\\_%" in inspect.getsource(cleanup_expired_guest_accounts)
    # Table test-auth jumps to the tester with the user prefilled
    users_tab = Path("frontend/src/components/UsersTab.jsx").read_text(encoding="utf-8")
    assert "propOnTestAuth(username)" in users_tab
    tester = Path("frontend/src/components/TesterTab.jsx").read_text(encoding="utf-8")
    assert "initialUsername" in tester
