# 🛡️ FreeRADIUS & Infrastructure Security & Firewall Port Guide

This comprehensive guide outlines the required network ports, cloud security group / security list configurations (Oracle Cloud, AWS, GCP, Azure, DigitalOcean), Linux host firewall rules (`ufw` & `iptables`), and security hardening practices for production deployments.

---

## 📋 1. Network Ports & Protocols Matrix

| Port | Protocol | Scope | Direction | Purpose & Description |
| :--- | :--- | :--- | :--- | :--- |
| **`1812`** | **UDP** | **Public / NAS Subnets** | Inbound | **RADIUS Authentication**: 802.1X, WPA2/WPA3-Enterprise, PAP, MSCHAPv2, EAP-TLS. |
| **`1813`** | **UDP** | **Public / NAS Subnets** | Inbound | **RADIUS Accounting**: Session Start, Interim-Update, and Stop telemetry. |
| **`3799`** | **UDP** | **Public / NAS Subnets** | Inbound | **RADIUS Dynamic Authorization / CoA**: Disconnect-Request & Change-of-Authorization (RFC 3576 / 5176). |
| **`443`** | **TCP** | **Public (Internet)** | Inbound | **HTTPS Web Traffic**: Traefik / Coolify SSL Reverse Proxy for Admin Console (`/radius/`) & Captive Portal (`/radius/portal`). |
| **`80`** | **TCP** | **Public (Internet)** | Inbound | **HTTP Traffic**: Automated Let's Encrypt ACME challenge & HTTP-to-HTTPS redirect. |
| **`22`** | **TCP** | **Admin IPs only** | Inbound | **SSH Server Management**: Remote server administration. |

### ⛔ Ports That MUST NOT Be Publicly Exposed (Internal Only)

| Internal Port | Service | Risk if Exposed | Correct Binding |
| :--- | :--- | :--- | :--- |
| **`8090/TCP`** | FreeRADIUS FastAPI Backend | Unauthenticated API bypass | Bind internally to Docker bridge (`coolify` / `127.0.0.1`). |
| **`5432/TCP`** | PostgreSQL Database | Brute-force attacks & SQL injection | Bind to `127.0.0.1:5432` or Docker network only. |
| **`6379/TCP`** | Redis Cache | Data tampering / remote command execution | Bind to `127.0.0.1:6379` or Docker network only. |
| **`8000/TCP`** | Coolify Admin Dashboard | Unauthorized infrastructure control | Bind to Admin IP / VPN / Private Subnet only. |

---

## ☁️ 2. Cloud Provider Firewall Setup

### 🟧 Oracle Cloud Infrastructure (OCI)

1. Navigate to **Networking** ➔ **Virtual Cloud Networks (VCN)**.
2. Select your VCN and click on **Security Lists** ➔ **Default Security List for your VCN** (or create a dedicated Security List for FreeRADIUS).
3. Click **Add Ingress Rules** with the following definitions:

#### A. RADIUS UDP Ingress Rules:
* **Stateless**: `No`
* **Source CIDR**: `0.0.0.0/0` *(or your Network Access Server / Access Point Public IPs / Subnets for enhanced security)*
* **IP Protocol**: `UDP`
* **Destination Port Range**: `1812,1813,3799`
* **Description**: `FreeRADIUS Auth, Accounting & CoA`

#### B. Web & SSL Ingress Rules:
* **Stateless**: `No`
* **Source CIDR**: `0.0.0.0/0`
* **IP Protocol**: `TCP`
* **Destination Port Range**: `80,443`
* **Description**: `HTTP & HTTPS Traefik Reverse Proxy`

#### C. SSH Management:
* **Stateless**: `No`
* **Source CIDR**: `<Your-Office-or-Home-IP>/32` *(or `0.0.0.0/0` with key-only auth)*
* **IP Protocol**: `TCP`
* **Destination Port Range**: `22`
* **Description**: `SSH Management`

> ⚠️ **OCI OS-level Firewall Note**: Ubuntu and Oracle Linux images on OCI include pre-configured `iptables` reject chains. Run the following on the VM if packets are blocked:
> ```bash
> sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 1812 -j ACCEPT
> sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 1813 -j ACCEPT
> sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 3799 -j ACCEPT
> sudo netfilter-persistent save
> ```

---

### 🟧 Amazon Web Services (AWS EC2)

1. Go to **EC2 Console** ➔ **Network & Security** ➔ **Security Groups**.
2. Select your Instance Security Group and click **Edit inbound rules**.
3. Add the following rules:

| Type | Protocol | Port Range | Source | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Custom UDP** | UDP | `1812` | `0.0.0.0/0` | RADIUS Authentication |
| **Custom UDP** | UDP | `1813` | `0.0.0.0/0` | RADIUS Accounting |
| **Custom UDP** | UDP | `3799` | `0.0.0.0/0` | RADIUS CoA Disconnect |
| **HTTPS** | TCP | `443` | `0.0.0.0/0` | Web UI & API Gateway |
| **HTTP** | TCP | `80` | `0.0.0.0/0` | ACME & HTTPS Redirect |
| **SSH** | TCP | `22` | `My IP` | Secure SSH Access |

---

### 🟦 Google Cloud Platform (GCP)

1. Open **VPC network** ➔ **Firewall**.
2. Click **Create Firewall Rule**:
   - **Name**: `allow-freeradius-ports`
   - **Network**: `default`
   - **Direction of traffic**: `Ingress`
   - **Action on match**: `Allow`
   - **Targets**: `All instances in the network` (or specified Target tag)
   - **Source IPv4 ranges**: `0.0.0.0/0`
   - **Protocols and ports**:
     - `udp:1812,1813,3799`
     - `tcp:80,443,22`

---

## 🐧 3. Host Firewall (`ufw`) Configuration

Run the following commands on the Linux host to configure `ufw`:

```bash
# 1. Set default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 2. Allow SSH (Make sure you do not lock yourself out!)
sudo ufw allow 22/tcp comment "SSH Management"

# 3. Allow Web & SSL Traffic (Traefik / Coolify Proxy)
sudo ufw allow 80/tcp comment "HTTP (Let's Encrypt / Redirect)"
sudo ufw allow 443/tcp comment "HTTPS (Web UI & APIs)"

# 4. Allow RADIUS UDP Traffic
sudo ufw allow 1812/udp comment "FreeRADIUS Auth"
sudo ufw allow 1813/udp comment "FreeRADIUS Acct"
sudo ufw allow 3799/udp comment "FreeRADIUS CoA"

# 5. (Optional) Restrict Coolify Dashboard Port 8000 to your admin IP
# sudo ufw allow from <YOUR_ADMIN_IP> to any port 8000 proto tcp comment "Coolify Admin UI"

# 6. Enable UFW
sudo ufw enable
sudo ufw status verbose
```

### ⚠️ Critical Docker & UFW Interaction
By default, Docker manipulates `iptables` directly and can expose mapped container ports (e.g. `-p 5432:5432`) to the public internet even if `ufw` is active.

**Best Practice Solutions:**
1. **Bind internal services to localhost (`127.0.0.1`)**:
   ```yaml
   ports:
     - "127.0.0.1:5432:5432"  # Safe: only accessible locally & via Docker network
   ```
2. **Use Docker User-defined Networks** (`coolify` / `backend-network`) for inter-container communication without exposing ports on the host.

---

## 🔒 4. Production Security Hardening Checklist

1. **Disable Public Registration in Coolify**:
   - In Coolify Settings, verify `is_registration_enabled` is set to `False`.
2. **Enable 2FA on Coolify & FreeRADIUS**:
   - Ensure Multi-Factor Authentication is active for all administrator accounts.
3. **Automated Secret Rotation**:
   - Regularly rotate the RADIUS shared secrets (`RADIUS_NAS_SECRET`) and database passwords using the automated rotation script:
     ```bash
     python3 /home/ubuntu/server-setups/scripts/rotate-secrets.py --sync-coolify
     ```
4. **Enforce EAP-TLS / Certificate-Based Authentication**:
   - Transition client devices from password-based credentials (PAP/MSCHAP) to cryptographic X.509 client certificates using the built-in PKI engine.
5. **Restrict NAS Clients (`clients.conf`)**:
   - In production, specify exact static IP addresses for your Wi-Fi APs / NAS routers rather than `0.0.0.0/0`.
