# 🛡️ FreeRADIUS Enterprise AAA & Management Suite

An enterprise-grade, containerized **FreeRADIUS v3.2** server powered by **PostgreSQL 16**, featuring a modern **FastAPI REST API**, an **X.509 EAP-TLS Public Key Infrastructure (PKI)** engine, 1-click **Apple `.mobileconfig` Wi-Fi auto-onboarding**, and responsive **Glassmorphism Web Portals** (Admin Console + User Captive Portal).

![Architecture](https://img.shields.io/badge/Architecture-FreeRADIUS%20v3.2%20%7C%20PostgreSQL%2016-indigo)
![License](https://img.shields.io/badge/License-MIT-emerald)
![Docker](https://img.shields.io/badge/Docker-ARM64%20%2F%20AMD64-blue)

---

## 🌟 Highlights

- **🔒 Enterprise 802.1X & WPA2/WPA3-Enterprise**: High-performance RADIUS Authentication (UDP `1812`), Accounting (UDP `1813`), and Change of Authorization / CoA Disconnect (UDP `3799`).
- **🪪 Integrated EAP-TLS X.509 PKI**: Built-in Certificate Authority that issues signed client certificates and PKCS#12 bundles for zero-password hardware auto-login.
- **🍏 1-Click Apple `.mobileconfig` Generator**: Automatically generates and signs Apple Wi-Fi profiles for instant, passwordless setup on iOS, iPadOS, and macOS.
- **⚡ Modern REST API & Microservice**: Complete FastAPI backend with real-time statistics, dynamic user/group management, radclient test packet simulations, and CoA session drops.
- **🎨 Glassmorphism UI**:
  - **Admin Console (`/radius/`)**: Multi-method authentication supporting **Admin Credentials** and **Digital X.509 Certificate Login** (zero-password PKI).
  - **User Captive Portal (`/radius/portal`)**: Self-service portal supporting Web Login, 1-Click Device Certificate Auto-Enrollment, and Network Diagnostics.
- **🔑 User Password Management**: 1-click secure password generation (14-16 chars), reset with strength evaluation, credential share card (copy, `.txt` download, setup QR, WhatsApp, Telegram, Email), search + group filter, flexible policy (min 8 chars, mobile numbers / passphrases supported).
- **📋 Audit Trail & Structured Logging**: Every create / update / password-reset / delete is recorded in `admin_audit_log` and `audit_events`, visible in Admin Console → Logs with secret redaction and configurable table retention (`AUDIT_RETENTION_DAYS`, `RADPOSTAUTH_RETENTION_DAYS`, etc.).
- **🔐 Reversible Cleartext Storage by RADIUS Necessity**: Stored in standard `Cleartext-Password` format required for 802.1X PEAP/MSCHAPv2 inner-tunnel authentication, and masked across all web UI views.
- **🚀 Coolify, Standalone Compose & Reverse Proxy Ready**: Native Docker Compose with automated Let's Encrypt / ACME public certificate discovery for zero-warning client connections on Android, iOS, Windows, and macOS.

---

## 🏗️ Architecture

```
                             [ Wi-Fi / LAN Routers ]
                       (MikroTik / OpenWrt / UniFi / pfSense)
                                        │
                         UDP 1812 (Auth) / 1813 (Acct)
                                        │
                                        ▼
    ┌───────────────────────────────────────────────────────────────────────┐
    │                       FreeRADIUS Container Stack                      │
    │                                                                       │
    │   ┌─────────────────────┐               ┌─────────────────────────┐   │
    │   │  FreeRADIUS Daemon  │ ◄───────────► │  PostgreSQL 16 Database │   │
    │   │      (Port 1812)    │  rlm_sql_pg   │ (radcheck, radacct, etc)│   │
    │   └──────────▲──────────┘               └────────────▲────────────┘   │
    │              │                                       │                │
    │              │             ┌─────────────────────────┴────────────┐   │
    │              └───────────► │   FastAPI Backend & PKI Engine       │   │
    │                            │            (Port 8090)               │   │
    │                            └──────────────────▲───────────────────┘   │
    │                                               │                       │
    │                                   HTTPS (via Coolify/Traefik)         │
    │                                               │                       │
    │                    ┌──────────────────────────┴─────────────────┐     │
    │                    │                                            │     │
    │          [Admin Dashboard: /radius/]                [Portal: /radius/portal] 
    └───────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart (Docker Compose)

### 1. Clone the repository
```bash
git clone https://github.com/authoritydmc/freeradius-app.git
cd freeradius-app
```

### 2. Configure Environment Variables
Copy the example configuration:
```bash
cp .env.example .env
```

Edit `.env` to configure your PostgreSQL credentials and RADIUS shared secret:
```env
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=radius
POSTGRES_USER=postgres
POSTGRES_PASSWORD=YourStrongDatabasePassword123!

RADIUS_SECRET=YourStrongRadiusSharedSecret_123!
RADIUS_ADMIN_USER=admin
RADIUS_ADMIN_PASSWORD=change_me_to_a_strong_unique_password
SESSION_SECRET=change_me_to_at_least_32_random_chars__openssl_rand_hex_32

RADIUS_API_PORT=8090
LOG_LEVEL=INFO
```

> The container **refuses to boot** when `RADIUS_ADMIN_PASSWORD` / `SESSION_SECRET`
> are missing, shorter than 32 chars (session secret), or equal to a published
> default — the API fails closed the same way. Generate strong values with
> `openssl rand -hex 32`. Rotate `RADIUS_SECRET` on the server **and** every
> NAS/router together. Client `.p12` bundles get a fresh random password at
> each issuance (returned once by the API); portal downloads require the
> account password as proof of ownership.

### 3. Initialize Database Schema
If starting with a fresh PostgreSQL database, import the FreeRADIUS schema:
```bash
docker exec -i postgres psql -U postgres -d radius < config/schema.sql
```

### 4. Build and Start
```bash
docker compose up -d --build
```

Access the web interfaces:
- **Admin Console**: `http://localhost:8090/radius/`
- **User Captive Portal**: `http://localhost:8090/radius/portal`
- **Health Check**: `http://localhost:8090/radius/api/health`

---

## ☁️ Deploying with Coolify

1. In your **Coolify Dashboard**, create a **New Resource** > **Public GitHub Repository**.
2. Point to `https://github.com/authoritydmc/freeradius-app` (Branch: `main` or `master`).
3. Set **Build Pack** to `Docker Compose` or `Dockerfile`.
4. In **Environment Variables**, configure:
   - `POSTGRES_HOST`: e.g. `dev-postgres` (name of your PostgreSQL container in Coolify)
   - `POSTGRES_PORT`: `5432`
   - `POSTGRES_DB`: `radius`
   - `POSTGRES_USER`: `postgres`
   - `POSTGRES_PASSWORD`: `<your-db-password>`
   - `RADIUS_SECRET`: `<your-shared-secret>`
    - `RADIUS_ADMIN_USER`: `<admin-username>`
    - `RADIUS_ADMIN_PASSWORD`: `<admin-password>`
    - `SESSION_SECRET`: `<random-secret-key>`
    - `CERT_SIGNER_API_URL`: e.g. `https://backend.rajlabs.in/cert-signer` (optional; omit for local-CA signing)
    - `CERT_SIGNER_API_KEY`: `<signer-api-key>` (optional)
    - `RADIUS_PUBLIC_HOST`: e.g. `80.225.195.202` (optional; defaults to API host)
5. In **Network / Ports**:
   - Expose UDP ports: `1812:1812/udp`, `1813:1813/udp`, `3799:3799/udp`.
   - Map domain: `https://backend.rajlabs.in` pointing to container port `8090`.
6. Deploy! Coolify will automatically rebuild on every `git push`.

---

## 📡 Router & Access Point Configuration

### MikroTik RouterOS
```routeros
/radius
add address=YOUR_SERVER_IP secret="YourRadiusSharedSecret" service=wireless,hotspot,login authentication-port=1812 accounting-port=1813 timeout=3000ms

/radius incoming
set accept=yes port=3799
```

### OpenWrt (`/etc/config/wireless`)
```uci
config wifi-iface 'default_radio0'
    option device 'radio0'
    option network 'lan'
    option mode 'ap'
    option ssid 'RajLabs-Enterprise'
    option encryption 'wpa2-mixed+eap'
    option auth_server 'YOUR_SERVER_IP'
    option auth_port '1812'
    option auth_secret 'YourRadiusSharedSecret'
    option acct_server 'YOUR_SERVER_IP'
    option acct_port '1813'
    option acct_secret 'YourRadiusSharedSecret'
```

---

## 👥 User Management & Password Operations

From **Admin Console → Users** an admin can do everything without `curl`:

| Action | How | Notes |
| :--- | :--- | :--- |
| **Add user** | `+ Add User` → auto-generated strong password | Strength meter, show/hide, copy |
| **Reset password** | 🔑 per-row → **Regenerate** → Save | Warns before resetting your own admin login |
| **Share credentials** | Result card after create/reset | Copy share text, download `.txt`, QR, WhatsApp / Email |
| **Disconnect sessions** | ☑️ in reset modal (CoA, UDP `3799`) | Drops active sessions immediately |
| **Find users** | Search box + group filter | Counts `filtered / total`, shows online + last-auth badges |
| **Audit** | Admin Console → Logs → Audit Trail | `GET /radius/api/audit?limit=50` |

API equivalents: `POST /radius/api/users/password/generate`, `PUT /radius/api/users/{username}/password` (`{"password","password_type","disconnect_active"}`), `GET /radius/api/users/password/policy`. Passwords are never returned by list/detail APIs (masked as `********`) and never written to logs.

## 📶 Testing Clients from Your Laptop

Turn a Linux laptop into a live **WPA2-Enterprise hotspot** backed by this server, or run a direct auth test — no dependencies to install, secrets are always prompted (never in the command):

```bash
# Linux: start Enterprise hotspot (hostapd + DHCP, prompts for RADIUS secret)
curl -fsSL https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.sh | sudo bash -s -- --ap

# Linux/macOS: direct RADIUS auth test (prompts for secret + credentials)
curl -fsSL https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.sh | bash -s -- --test
```

```powershell
# Windows (PowerShell): interactive auth test via SecureString prompts
irm https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.ps1 | iex
```

> Note: `curl` only checks the HTTPS API (`/radius/api/health`). Real credential checks go over RADIUS/UDP `1812` — that is what the scripts above exercise. Full walkthrough (phone connect flow, flags like `--server`, `--ssid`, `--test`): 👉 **[Wi-Fi Testing & AP Simulation Guide](docs/WIFI_TESTING_AND_AP_SIMULATION_GUIDE.md)**

## 🪪 Central Cert-Signer (optional, env-based)

Client certificates are signed by the **central Rajlabs-CA** when configured, otherwise by the **local FreeRADIUS CA** — no URLs are hardcoded; everything comes from env:

| Variable | Purpose |
| :--- | :--- |
| `CERT_SIGNER_API_URL` | e.g. `https://backend.rajlabs.in/cert-signer` — change it any time, no code change needed |
| `CERT_SIGNER_API_KEY` | Sent as `x-api-key` on signer requests (value never logged or returned by any API) |
| `RADIUS_PUBLIC_HOST` | Host shown in the dashboard/for routers (defaults to the API host) |

**Am I connected?** Open **Admin Console → EAP-TLS** — the status banner shows live state (refreshed every 30s, `Re-check` forces it):
- 🟢 `Connected (host)` — remote signing active (latency shown)
- 🔴 `Unreachable` — falls back to local CA, reason shown (DNS/timeout/connection)
- 🟡 `API key rejected (HTTP 401/403)` — reachable but `CERT_SIGNER_API_KEY` is wrong
- ⚪ `Local CA` — signer not configured at all

API: `GET /radius/api/certs/signer-status` (admin, `?refresh=true` to bypass cache) and `GET /radius/api/public-config` (public client facts, key/URL never exposed).

## 🛡️ Authentication Architecture

| Interface | URL | Auth Mode | Capabilities |
| :--- | :--- | :--- | :--- |
| **Admin Console** | `/radius/` | Session Token / X.509 Client Cert / Basic Auth | Manage users, groups, bandwidth tiers, active sessions, and CoA disconnects |
| **User Portal** | `/radius/portal` | Public Web / Router Captive Portal | Credential sign-in, 1-click Apple `.mobileconfig` install, PKCS#12 download |
| **RADIUS Port** | UDP `1812` | 802.1X EAP-TLS, PEAP-MSCHAPv2, PAP/CHAP | Router and AP authentication |

---

## 🔒 Security, Firewall & Cloud Port Guide

For detailed cloud ingress rules (**Oracle Cloud OCI**, **AWS EC2**, **GCP**, **Azure**, **DigitalOcean**), Linux host firewall (**`ufw`** / **`iptables`**), and Coolify security hardening, see the complete guide:

👉 **[Complete Port & Cloud Security Guide](docs/PORT_SECURITY_GUIDE.md)**

### Key Ports Summary
- **UDP `1812`**: RADIUS Authentication (Inbound from NAS/Routers or `0.0.0.0/0`)
- **UDP `1813`**: RADIUS Accounting (Inbound from NAS/Routers or `0.0.0.0/0`)
- **UDP `3799`**: RADIUS CoA / Disconnect (Inbound from NAS/Routers or `0.0.0.0/0`)
- **TCP `443` / `80`**: HTTPS / HTTP for Traefik Reverse Proxy & Web UI
- **TCP `22`**: SSH Management (Restricted to Admin IPs)

### 📝 Logging & Audit

- **Format**: `timestamp | LEVEL | freeradius | message` (one `freeradius` logger; `LOG_LEVEL=DEBUG` for verbose).
- **Request log**: every API call logs `METHOD path status latency client` — health checks at `DEBUG`, `4xx/5xx` as warnings. Request **bodies are never logged** (they may contain passwords).
- **Event logs**: admin login success/fail (failures warn with username + client IP, never the password), password generate/reset, cert issue, CoA disconnect, test-auth results.
- **Audit trail**: persistent `admin_audit_log` table (auto-created at startup), queryable at `GET /radius/api/audit` and rendered in Admin Console → Logs.
- **Status page**: Admin Console → **Status** tab consolidates everything — core services (API / PostgreSQL / FreeRADIUS daemon), PKI signer state, RADIUS endpoints, usage snapshot, and latest admin activity — with Refresh-all and 15s auto-refresh.

### ⏱️ Rate limits, CORS & cookies

- **Rate limits** (per IP, sliding 60s window, `429 + Retry-After`): login `10/min`, portal enroll `5/min`, test-auth `20/min`, cert issue `10/min`. Tune via `RL_LOGIN_PER_MIN`, `RL_ENROLL_PER_MIN`, `RL_TEST_AUTH_PER_MIN`, `RL_CERT_ISSUE_PER_MIN` (0 = off).
- **CORS**: same-origin only by default. Set `CORS_ORIGINS=https://admin.example.com,https://portal.example.com` to allow dashboard origins (wildcard + credentials is never used).
- **Cookies**: `Secure` by default. For plain-HTTP LAN testing set `COOKIE_SECURE=0` (trusted LAN only) — otherwise the browser silently drops the session cookie and only the Bearer-token path works.
### 📚 Additional Guides & Runbooks
- 🔑 **[Secrets & RADIUS Key Rotation Runbook](docs/ROTATION_RUNBOOK.md)**
- 🛡️ **[Reverse Proxy Security Headers Guide](docs/PROXY_SECURITY_HEADERS.md)**
- 🏢 **[High Availability & Backup / Restore Guide](docs/BACKUP_AND_HA.md)**
- 📡 **[Wi-Fi Testing & AP Simulation Guide](docs/WIFI_TESTING_AND_AP_SIMULATION_GUIDE.md)**
- 🔒 **[Complete Port & Cloud Security Guide](docs/PORT_SECURITY_GUIDE.md)**

### 💾 Backup & restore

```bash
# Back up DB + CA/certs volume (keeps newest 14 of each)
POSTGRES_PASSWORD=... ./scripts/backup.sh ./backups
# Restore on a clean stack
POSTGRES_PASSWORD=... ./scripts/restore.sh ./backups/radius-db-<ts>.sql.gz ./backups/radius-certs-<ts>.tar.gz
```

Schedule `backup.sh` daily (cron) and copy both files encrypted offsite — losing the certs archive means re-issuing every certificate. Table retention: `AUDIT_RETENTION_DAYS` / `ACCOUNTING_RETENTION_DAYS` (default 365, `0` = keep forever), purged at startup.

### 🌐 Static client IPs must live on the NAS-side LAN

A pinned `Framed-IP-Address` must belong to the **local network behind your
routers** (e.g. `192.168.1.50`), never the RADIUS server's own subnet — the
server only *tells* the NAS which address to hand out; a `10.x` pin on a
`192.168/172.16` site connects to Wi-Fi with no route anywhere. The dashboard
checks every static IP against your registered NAS subnets live (user modal
hint + save-time warning) and `GET /radius/api/networks/coverage?ip=…`
answers the same question for scripts. Blank (DHCP) or per-group
`Framed-Pool` is the safe default for roaming users; reserve static pins for
single-subnet devices.

### 🔒 Verified devices (MAC lockdown, off by default)

Per user: **Users → 🛡️ → Only verified devices can connect**. When on, FreeRADIUS
rejects any device whose MAC isn't on that user's verified list, and the
attempt is logged in **Auth History → Rule / Reason**
(`Rejected: device MAC not verified for this user`).
- Add MACs from the **Devices tab → Trust**, or type them in the user's policy modal (any format: `AA:BB:CC:DD:EE:FF`, dashes, Cisco dots — all normalized server-side).
- Deleting a user also removes their verified list. Verify the behavior with the **RADIUS Tester** (optional MAC field simulates a device).
- Note: phones with MAC randomization appear as several devices — verify each one, or turn randomization off for your SSID.

### 🧪 Tests & CI

```bash
python -m pytest tests/ -q   # no database required
```

GitHub Actions runs `py_compile` + pytest + secret-grep guards (fails on `shell=True`, well-known password literals, hardcoded frontend secrets) on every push/PR. Orphaned certs (deleted users, pre-fix installs): `GET /radius/api/certs/orphans` lists them, `DELETE /radius/api/certs/orphans/{username}` removes them.

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
