# RADIUS Shared Secret & Credentials Rotation Runbook

This guide covers rotating secrets in **RajLabs FreeRADIUS Enterprise** across Coolify and standalone Docker Compose setups with zero or minimal downtime.

---

## 1. Secrets Overview

| Secret Name | Purpose | Where Defined | Impact of Rotation |
|-------------|---------|---------------|-------------------|
| `RADIUS_SECRET` | Default shared secret for local / fallback NAS clients | `.env` / Coolify Env | Update all NAS APs that use the global default secret |
| `Per-NAS Secret` | Individual router / AP shared secret | `nas` table in PostgreSQL | Update only the specific AP/router (no container restart required) |
| `SESSION_SECRET` | HMAC key for admin / user UI web session tokens | `.env` / Coolify Env | Invalidates all active web UI sessions (forces re-login) |
| `RADIUS_ADMIN_PASSWORD` | Fallback admin UI password | `.env` / Coolify Env | Changes login password for `admin` user |
| `CA_KEY_PASSWORD` | Local CA private key passphrase | `.env` / Coolify Env | Used when minting client/server certs from local CA |

---

## 2. Rotating Per-NAS Shared Secrets (Zero Downtime)

For high-security deployments, do **not** rely on a single global secret. Configure each AP or router with its own row in the `nas` table.

1. In the Web UI, navigate to **NAS Clients** tab.
2. Edit the NAS client or add a new entry with the new secret:
   ```text
   NAS IP / Subnet: 192.168.1.10
   Shortname: AP-Floor-1
   Secret: <new_random_32_char_secret>
   ```
3. Update the corresponding RADIUS secret in your Access Point (UniFi, Cisco, Mikrotik, OpenWrt) admin portal.
4. Test the connection immediately in the **RADIUS Tester** tab.

---

## 3. Rotating Global `RADIUS_SECRET` & `SESSION_SECRET`

### Step A: Generate New High-Entropy Secrets
```bash
# Generate strong 32-character hex secrets
NEW_RADIUS_SECRET=$(openssl rand -hex 24)
NEW_SESSION_SECRET=$(openssl rand -hex 32)
NEW_ADMIN_PASSWORD=$(openssl rand -base64 18)

echo "New RADIUS Secret:  $NEW_RADIUS_SECRET"
echo "New Session Secret: $NEW_SESSION_SECRET"
echo "New Admin Password: $NEW_ADMIN_PASSWORD"
```

### Step B: Apply to Coolify or Docker Compose
- **In Coolify**:
  1. Open Coolify Dashboard -> Select Application -> **Environment Variables**.
  2. Update `RADIUS_SECRET`, `SESSION_SECRET`, and `RADIUS_ADMIN_PASSWORD`.
  3. Click **Deploy / Redeploy**.
- **In Standalone Docker Compose (`server-setups`)**:
  1. Update `.env`:
     ```bash
     RADIUS_SECRET=your_new_radius_secret_here
     SESSION_SECRET=your_new_session_secret_32_chars_here
     RADIUS_ADMIN_PASSWORD=your_new_admin_password_here
     ```
  2. Restart the stack:
     ```bash
     docker compose up -d
     ```

### Step C: Update Network Hardware & Test
1. Update RADIUS Secret on all Access Points and Wireless LAN Controllers.
2. Verify authentication with `radtest`:
   ```bash
   radtest <username> <password> 127.0.0.1 0 "$NEW_RADIUS_SECRET"
   ```
3. Verify via Web UI -> **RADIUS Tester** tab.
