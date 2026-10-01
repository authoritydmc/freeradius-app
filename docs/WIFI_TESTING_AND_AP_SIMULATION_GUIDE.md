# Wi-Fi Testing & Enterprise RADIUS Authentication Guide

This guide explains how to start an **Enterprise Wi-Fi Hotspot** on your Linux machine (laptop, PC, or Raspberry Pi) to test FreeRADIUS authentication from your mobile phones, tablets, or other laptops, as well as how to run interactive zero-dependency tests.

---

## 📡 Live Enterprise Wi-Fi Hotspot (Linux)

You can turn any Linux laptop or PC with a Wi-Fi adapter into a live **WPA2-Enterprise (802.1X)** Access Point. When client devices (smartphones, laptops) connect to this Wi-Fi network, their login requests are authenticated in real-time by your cloud FreeRADIUS server.

### 1. Download & Launch the Hotspot Tool

```bash
curl -fsSL https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.sh | sudo bash -s -- --ap
```

Or clone/download manually:
```bash
curl -fsSL -o test-wifi-radius.sh https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.sh
chmod +x test-wifi-radius.sh
sudo ./test-wifi-radius.sh --ap
```

### 2. What the Script Does Automatically
1. Prompts you **securely** for your RADIUS Shared Secret (input is hidden, never saved to disk).
2. Auto-detects your wireless network interface (e.g. `wlan0`).
3. Configures `hostapd` for WPA2-Enterprise (`802.1X / EAP`) pointing to your FreeRADIUS server (`80.225.195.202:1812`).
4. Configures DHCP (`dnsmasq`) and IP forwarding so connected devices receive an IP address (`192.168.88.x`) and internet access.
5. Starts broadcasting your chosen SSID (default: `RajLabs-Enterprise`).

### 3. Connect Client Devices (Phone / Laptop)
1. Open Wi-Fi on your mobile phone or laptop.
2. Select **`RajLabs-Enterprise`**.
3. Enter your RADIUS username & password when prompted.
4. The hotspot forwards the authentication packet to FreeRADIUS in the cloud and admits the device upon approval!

---

## ⚡ Direct RADIUS Authentication Tests (Without Wi-Fi Hardware)

If you just want to verify credentials or check if UDP port 1812 is open from any machine:

### 🍎 macOS & 🐧 Linux (Interactive & Secure)
```bash
curl -fsSL https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.sh | bash -s -- --test
```
*(Prompts for secret and credentials securely without displaying them on screen)*

### 🪟 Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.ps1 | iex
```
*(Prompts securely via PowerShell SecureString)*

---

## 🛠️ CLI Parameters (Optional)

| Parameter | Description | Default |
|---|---|---|
| `--ap` | Start WPA2-Enterprise Wi-Fi Hotspot | Interactive Menu |
| `--test` | Run direct UDP RADIUS auth test | Interactive Menu |
| `-s, --server <ip>` | RADIUS Server IP or FQDN | `80.225.195.202` |
| `-k, --secret <secret>` | RADIUS Shared Secret | *(Prompted securely)* |
| `-i, --interface <wlan>`| Wi-Fi interface for AP | Auto-detected |
| `--ssid <name>` | Wi-Fi Hotspot name | `RajLabs-Enterprise` |
| `-u, --user <username>` | Username for `--test` | *(Prompted securely)* |
| `-p, --pass <password>` | Password for `--test` | *(Prompted securely)* |
