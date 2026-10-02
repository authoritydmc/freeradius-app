# Changelog

All notable changes to the **RajLabs FreeRADIUS Enterprise AAA Stack & Portal** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed
- **Android CA trust + .p12 install flow**: Root CA now downloadable as `.crt` (DER, `?format=crt`) for Android's Wi-Fi certificate installer alongside `.pem`; new public `GET /radius/api/public/ca-info` exposes the SHA-256 fingerprint so phones can verify before trusting. PKCS#12 bundles are exported with legacy PBE-SHA1-3DES first (fallback to defaults) so OEM KeyChain imports accept them. Portal certificate downloads now use POST (password in body, never in URL/history).
- **Simple password policy**: min 8 characters, no forced upper/lower/digit/symbol mix — a 10-digit mobile number alone passes. Policy endpoint, strength meter, generators, and hints updated.
- **Recharge no longer breaks logins**: `sync_user_radius_attributes` preserved the radcheck password only by accident before — it overwrote it with the central placeholder, so every subscription start/recharge locked the user out until a manual password reset. It now preserves live credentials (seeds only when missing), and all password-write paths mirror the real password centrally.
- **Group-level exempt now applies**: group save mirrors `recharge_required` into the central `groups` table (the engine never read the RADIUS flag), resolves exempt via live RADIUS membership as fallback, and immediately re-syncs all members so stale Reject rows disappear.
- **Reject reasons always recorded**: `remove_reply_message_if_eap` is now actually defined (shipped `config/policy.d/rajlabs`, previously referenced but missing); post-auth logs exactly one radpostauth row per attempt with EAP method + device MAC + AP/SSID context (migration 005); `anonymous` outer-identity and generic fallbacks name the cause. Requires container rebuild + restart.
- **EAP server identity**: boot re-issues `server.pem` from the existing CA when it lacks a SAN for `EAP_SERVER_CN` (default `RADIUS_PUBLIC_HOST`), so Android stops asking for an unknown domain; the effective CN/SAN is printed at boot and served via `public-config.eap.domain_hint`, which the portal shows as the exact Domain string to type.
- **Simultaneous-Use is clearable**: the field no longer snaps empty back to 1 — blank/0 means no concurrent-device limit (backend skips the row, and the wipe-and-rewrite save removes a previously set limit).
- **Phone number as default password**: blank password on create/reset uses the phone digits (min 8); server returns the effective password, UI has a Phone-fill button. Dropped the dead `password_type` option (always Cleartext — anything else breaks MS-CHAP).
- **Honest password storage**: `users.password_hash` renamed to `users.password_cleartext` (migration 006) — it always held cleartext because MS-CHAP/PEAP requires it; the old name invited a "fix" that would break all logins.
- **Audit coverage completed**: group save/delete and NAS create/delete now write audit rows (they were the only silent admin actions).
- **Access state converges (#25)**: ALLOW sync stamps wall-clock `Expiration` from `expires_at` (recharge no longer leaves paid users hard-rejected) and drops stale guest `Expiration` for exempt users; portal guest `Session-Timeout` moved to `radreply` (was inert in `radcheck`) with collision-safe IDs; group delete re-syncs former members.
- **Postgres HA without dual-write**: `POSTGRES_HOST="primary,standby"` lands API/migration writes on the primary via libpq `target_session_attrs` (all three connectors; single-host unchanged). `backup.sh` pushes a second copy to `BACKUP_PUSH_TARGET`; see `docs/BACKUP_AND_HA.md` for replica setup, promotion, and restore drills. Deliberately no app-level dual-write — `rlm_sql` can't broadcast writes and hand-rolled two-phase commit buys split-brain.

### Added
- **wifi.rajlabs.in mobile-first explainer** in the portal Setup tab: what the site is, PEAP (easiest) vs EAP-TLS (most secure), and per-OS (Android/iOS/Windows/Linux) join steps.
- **Failure-to-portal path**: every reject Reply-Message points to `https://wifi.rajlabs.in` (the 802.1X equivalent of a redirect — the protocol has no HTTP redirect); the auth-event dossier has an "Open captive portal" button with `?user=` deep-link prefill, and the portal pre-fills the login username from it.
- **`GET /radius/api/accounting/gaps`**: lists users accepted recently with zero accounting rows (AP not sending UDP 1813); Sessions tab shows them in an amber banner with the AP-side checklist.
- **Devices tab shows login-seen stations**: MACs from recent auth attempts (new radpostauth context) appear with an "Auth only — no accounting" badge even before the AP sends accounting; also fixed Last-IP never displaying (backend sends `last_ip`).

---

## [2.3.0] - 2026-10-02

### Added
- **Interactive System Settings Admin Tab (`/radius` -> System Settings)**:
  - Full Web UI form to view, configure, and dynamically update Administrator Support Phone/WhatsApp, Display Name, UPI Virtual Payment Address (VPA), Merchant Name, Default Voucher Code, and Currency.
  - Live preview widget illustrating how contact cards and payment badges appear to end users.
  - Audit trail showing all stored settings keys, values, and last updated timestamps.
- **1-Click WhatsApp & SMS Support Recovery**:
  - Embedded in User Captive Portal (`/radius/portal`) and Admin Login modal.
  - Pre-composes automated assistance requests with username context targeting configured administrator WhatsApp / SMS numbers.
- **Dynamic Public Configuration API (`/radius/api/public-config`)**:
  - Serves live system support numbers and UPI metadata directly from PostgreSQL `system_settings` table with graceful environment variable fallbacks.

---

## [2.2.0] - 2026-10-01

### Added
- **User Self-Service Login & Dashboard Portal (`/radius/portal`)**:
  - Direct end-user authentication with session cookie support.
  - Live active entitlement indicator and remaining validity countdown clock.
  - Interactive data usage breakdown (upload/download MB & GB) and live connected session details (IP, MAC, NAS).
  - Dynamic QR code recharge flow supporting Google Pay, PhonePe, Paytm, and BHIM UPI intents with machine-readable payment notes (`WIFI|username|YYYYMMDD|plan`).
  - Self-service promotional and prepaid voucher redemption modal.
- **Admin Dynamic System Settings & Payment Customization (`/radius/api/settings`)**:
  - Configurable UPI VPA ID and Merchant display name without modifying environment variables or redeploying.
  - Default voucher code and onboarding settings.
- **Batch Voucher Generator & Lifecycle Manager**:
  - Bulk cryptographic voucher creation with custom prefix, validity duration, max redemptions, and expiry timestamps.
  - Real-time voucher redemption ledger and tracking.
- **Central Access Decision Engine (`api/access_engine.py`)**:
  - Pure entitlement evaluation (`get_access_decision()`) decoupling authentication from raw database boolean flags.
  - Hardened 1-day maximum session duration enforcement (`Session-Timeout = min(remaining_validity, 86400)`).
  - Dynamic group and user-level recharge exemption overrides.
  - Synchronized FreeRADIUS SQL attribute updater (`sync_user_radius_attributes()`).
- **Subscription Entitlement Ledger & Background Worker (`api/entitlements.py`)**:
  - Idempotent payment processing preventing duplicate recharge activations.
  - Expiry stacking logic (`max(now, existing_expiry) + validity`).
  - Asynchronous background expiry worker running every 30 seconds to clean expired entitlements and sync FreeRADIUS attributes.
  - RFC 5176 Change of Authorization (CoA) / Disconnect Message support (`radclient`) to immediately terminate sessions when entitlements expire.
- **Multi-Gateway Payment Ingestion Engine (`api/payment_providers.py`)**:
  - Webhook handlers with cryptographic signature verification for Razorpay and Cashfree.
  - Machine-readable UPI reference string parser and validator.
  - Bank email alert processor for automated payment verification.
- **Comprehensive Pytest Suite (`tests/test_access_entitlements.py`)**:
  - Complete test coverage for access decision rules, stacking, voucher redemption, and payment idempotency.

### Changed
- Refactored `api/app.py` to use modular engine components (`access_engine.py`, `entitlements.py`, `payment_providers.py`, `db_init.py`).
- Enhanced Admin Dashboard with access decision inspector, voucher generator UI, and live payment ledger.

### Fixed
- Fixed Python typing import compatibility issue in API container startup.

---

## [2.1.0] - 2026-10-01

### Added
- **Centralized CA Integration**: Automated CSR signing and certificate issuance against the RajLabs-CA Cert Signer API.
- **Cross-Platform Enterprise Wi-Fi AP Diagnostics**: Built-in AAA diagnostic test suite for validating RADIUS authentication across Mikrotik, Cisco, UniFi, and Aruba APs.
- **Apple `.mobileconfig` Auto-Provisioning**: Automated profile generation for seamless 1-click EAP-TLS Wi-Fi onboarding on iOS and macOS.

---

## [2.0.0] - 2026-10-01

### Added
- **Enterprise FreeRADIUS 3.0 AAA Stack**:
  - High-performance FreeRADIUS daemon backed by PostgreSQL.
  - FastAPI management service with RESTful CRUD for users, groups, NAS clients, and accounting sessions.
  - Full support for EAP-TLS, PEAP-MSCHAPv2, and PAP/CHAP authentication protocols.
  - MicroTik rate limiting, dynamic VLAN assignment, and QoS bandwidth policies.
  - Modern web dashboard built with Tailwind CSS and Alpine.js.

---

[2.2.0]: https://github.com/rajlabshq/freeradius-app/releases/tag/v2.2.0
[2.1.0]: https://github.com/rajlabshq/freeradius-app/releases/tag/v2.1.0
[2.0.0]: https://github.com/rajlabshq/freeradius-app/releases/tag/v2.0.0
