# Changelog

All notable changes to the **RajLabs FreeRADIUS Enterprise AAA Stack & Portal** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
