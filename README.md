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
- **🚀 Coolify & Reverse Proxy Ready**: Native Docker Compose with volume persistence for CA keys and auto-integration with Traefik/Nginx reverse proxies.

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
RADIUS_ADMIN_PASSWORD=YourAdminPassword123!
SESSION_SECRET=YourRandom32CharacterSessionKey_abc123!

RADIUS_API_PORT=8090
```

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

## 🛡️ Authentication Architecture

| Interface | URL | Auth Mode | Capabilities |
| :--- | :--- | :--- | :--- |
| **Admin Console** | `/radius/` | Session Token / X.509 Client Cert / Basic Auth | Manage users, groups, bandwidth tiers, active sessions, and CoA disconnects |
| **User Portal** | `/radius/portal` | Public Web / Router Captive Portal | Credential sign-in, 1-click Apple `.mobileconfig` install, PKCS#12 download |
| **RADIUS Port** | UDP `1812` | 802.1X EAP-TLS, PEAP-MSCHAPv2, PAP/CHAP | Router and AP authentication |

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
