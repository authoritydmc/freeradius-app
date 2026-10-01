#!/usr/bin/env bash
# ==============================================================================
# 🛡️ RajLabs FreeRADIUS Wi-Fi Hotspot & AAA Diagnostic Suite
# ==============================================================================
# Starts an 802.1X WPA2-Enterprise Wi-Fi Hotspot on your local machine
# or runs direct AAA authentication diagnostics against your FreeRADIUS server.
#
# NO secrets or passwords are stored in this script.
# ==============================================================================

set -e

# Default settings
SERVER="${RADIUS_SERVER:-80.225.195.202}"
AUTH_PORT="${RADIUS_AUTH_PORT:-1812}"
ACCT_PORT="${RADIUS_ACCT_PORT:-1813}"
API_URL="${RADIUS_API_URL:-https://backend.rajlabs.in/radius}"
SSID="${HOTSPOT_SSID:-RajLabs-Enterprise}"
IFACE="${HOTSPOT_IFACE:-}"
ENABLE_NAT="${HOTSPOT_NAT:-1}"
MODE="menu" # default mode

# Parse CLI arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --ap|--host-ap) MODE="ap" ;;
        --test) MODE="test" ;;
        -s|--server) SERVER="$2"; shift ;;
        -k|--secret) SECRET="$2"; shift ;;
        -u|--user|--username) USERNAME="$2"; shift ;;
        -p|--pass|--password) PASSWORD="$2"; shift ;;
        -i|--interface) IFACE="$2"; shift ;;
        --ssid) SSID="$2"; shift ;;
        --auth-port) AUTH_PORT="$2"; shift ;;
        --acct-port) ACCT_PORT="$2"; shift ;;
        --no-nat) ENABLE_NAT=0 ;;
        -h|--help)
            echo "Rajlabs FreeRADIUS Wi-Fi Hotspot & Diagnostic Tool"
            echo ""
            echo "Usage:"
            echo "  $0 --ap [options]     Start WPA2-Enterprise Wi-Fi Hotspot"
            echo "  $0 --test [options]   Test RADIUS authentication directly"
            echo ""
            echo "Options:"
            echo "  -s, --server <ip>        RADIUS Server IP / Hostname (default: 80.225.195.202)"
            echo "  -k, --secret <secret>    RADIUS Client Shared Secret (prompted securely if omitted)"
            echo "  -i, --interface <wlan>   Wireless interface (e.g. wlan0, auto-detected if omitted)"
            echo "  --ssid <name>            Wi-Fi SSID name (default: RajLabs-Enterprise)"
            echo "  -u, --user <username>    Username to test (for --test mode)"
            echo "  -p, --pass <password>    Password to test (prompted securely if omitted)"
            echo "  --no-nat                 Disable automatic DHCP & NAT routing in AP mode"
            echo "  -h, --help               Show this help message"
            exit 0
            ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "================================================================="
echo "   🛡️ RajLabs FreeRADIUS Hotspot & Diagnostic Suite"
echo "================================================================="

# Interactive menu if mode not explicitly chosen
if [ "$MODE" = "menu" ]; then
    echo "Please select an action:"
    echo "  1) 📡 Start WPA2-Enterprise Wi-Fi Hotspot (Test with phones/laptops)"
    echo "  2) 🔐 Run Direct RADIUS Authentication Test from this machine"
    echo "  3) 🌐 Check Web Portal & Health API"
    echo ""
    read -r -p "Select option [1-3] (default: 1): " choice
    choice="${choice:-1}"
    case "$choice" in
        1) MODE="ap" ;;
        2) MODE="test" ;;
        3) MODE="health" ;;
        *) echo "Invalid option"; exit 1 ;;
    esac
fi

# Function: Prompt for secret securely
get_secret() {
    if [ -z "${SECRET:-}" ]; then
        echo ""
        read -r -s -p "🔑 Enter RADIUS NAS Shared Secret: " SECRET
        echo ""
    fi
    if [ -z "$SECRET" ]; then
        echo "❌ Error: RADIUS Shared Secret is required."
        exit 1
    fi
}

# ------------------------------------------------------------------------------
# MODE 1: Wi-Fi Access Point (Hotspot) Launcher
# ------------------------------------------------------------------------------
if [ "$MODE" = "ap" ]; then
    if [ "$EUID" -ne 0 ]; then
        echo "⚠️  Wi-Fi Hotspot creation requires root permissions."
        echo "   Re-running with sudo..."
        exec sudo "$0" --ap -s "$SERVER" ${SECRET:+-k "$SECRET"} ${IFACE:+-i "$IFACE"} --ssid "$SSID" --auth-port "$AUTH_PORT" --acct-port "$ACCT_PORT"
    fi

    # Check dependencies
    for cmd in hostapd iw ip; do
        if ! command -v $cmd >/dev/null 2>&1; then
            echo "❌ Missing dependency: $cmd"
            echo "   Install required packages: sudo apt-get update && sudo apt-get install -y hostapd iw dnsmasq iptables"
            exit 1
        fi
    done

    # Detect Wi-Fi Interface
    if [ -z "$IFACE" ]; then
        IFACE=$(iw dev 2>/dev/null | awk '$1=="Interface"{print $2}' | head -n 1 || true)
        if [ -z "$IFACE" ]; then
            IFACE=$(ip link 2>/dev/null | awk -F: '$2 ~ /wl/{print $2}' | tr -d ' ' | head -n 1 || true)
        fi
    fi

    if [ -z "$IFACE" ]; then
        echo "❌ No wireless interface detected on this system."
        echo "   Specify manually with: -i <interface_name>"
        exit 1
    fi

    echo ""
    echo "📡 Hotspot Configuration:"
    echo "   - Wireless Interface : $IFACE"
    echo "   - Broadcast SSID     : $SSID"
    echo "   - Security Mode      : WPA2-Enterprise (802.1X / EAP)"
    echo "   - FreeRADIUS Server  : $SERVER:$AUTH_PORT"
    echo "   - Accounting Server  : $SERVER:$ACCT_PORT"
    
    get_secret

    # Temporary configuration paths
    TMP_DIR=$(mktemp -d /tmp/rajlabs_ap_XXXXXX)
    TMP_HOSTAPD="$TMP_DIR/hostapd.conf"
    TMP_DNSMASQ="$TMP_DIR/dnsmasq.conf"

    cleanup() {
        echo ""
        echo "🛑 Shutting down Hotspot and restoring network..."
        killall hostapd 2>/dev/null || true
        killall dnsmasq 2>/dev/null || true
        if [ "$ENABLE_NAT" = "1" ]; then
            iptables -D FORWARD -i "$IFACE" -j ACCEPT 2>/dev/null || true
            iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || true
        fi
        ip addr flush dev "$IFACE" 2>/dev/null || true
        rm -rf "$TMP_DIR"
        echo "✅ Cleanup complete."
    }
    trap cleanup EXIT INT TERM

    # Configure hostapd for 802.1X Enterprise Wi-Fi
    cat << EOF > "$TMP_HOSTAPD"
interface=$IFACE
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
ieee8021x=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-EAP
wpa_pairwise=CCMP
rsn_pairwise=CCMP
auth_server_addr=$SERVER
auth_server_port=$AUTH_PORT
auth_server_shared_secret=$SECRET
acct_server_addr=$SERVER
acct_server_port=$ACCT_PORT
acct_server_shared_secret=$SECRET
EOF

    # Configure IP & DHCP server for connecting clients
    if [ "$ENABLE_NAT" = "1" ] && command -v dnsmasq >/dev/null 2>&1; then
        echo "⚙️  Configuring DHCP server and IP range (192.168.88.0/24)..."
        ip link set "$IFACE" up
        ip addr flush dev "$IFACE" 2>/dev/null || true
        ip addr add 192.168.88.1/24 dev "$IFACE"

        cat << EOF > "$TMP_DNSMASQ"
interface=$IFACE
bind-interfaces
dhcp-range=192.168.88.10,192.168.88.100,255.255.255.0,12h
dhcp-option=3,192.168.88.1
dhcp-option=6,1.1.1.1,8.8.8.8
server=1.1.1.1
EOF
        dnsmasq --conf-file="$TMP_DNSMASQ"
        
        # Enable NAT forwarding if internet interface exists
        WAN_IFACE=$(ip route | awk '/default/{print $5}' | head -n 1 || echo "")
        if [ -n "$WAN_IFACE" ] && [ "$WAN_IFACE" != "$IFACE" ]; then
            sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
            iptables -A FORWARD -i "$IFACE" -o "$WAN_IFACE" -j ACCEPT 2>/dev/null || true
            iptables -t nat -A POSTROUTING -o "$WAN_IFACE" -j MASQUERADE 2>/dev/null || true
        fi
    fi

    echo ""
    echo "================================================================="
    echo " 🚀 BROADCASTING LIVE ENTERPRISE WI-FI: '$SSID'"
    echo "================================================================="
    echo " To connect your phone or laptop:"
    echo " 1. Search Wi-Fi and choose '$SSID'"
    echo " 2. Enter your username and password when prompted."
    echo " 3. Authentication will be verified live by FreeRADIUS!"
    echo " Press Ctrl+C to stop broadcasting."
    echo "================================================================="
    echo ""

    hostapd "$TMP_HOSTAPD"
    exit 0
fi

# ------------------------------------------------------------------------------
# MODE 2: Direct RADIUS Authentication & Accounting Test
# ------------------------------------------------------------------------------
if [ "$MODE" = "test" ]; then
    get_secret

    if [ -z "${USERNAME:-}" ]; then
        read -r -p "👤 Enter Username to test: " USERNAME
    fi
    if [ -z "${PASSWORD:-}" ]; then
        read -r -s -p "🔒 Enter Password for $USERNAME: " PASSWORD
        echo ""
    fi

    echo ""
    echo "🔐 Testing 802.1X / Enterprise RADIUS Authentication..."
    python3 - << EOF
import socket, hashlib, os, sys

def test_radius(server, auth_port, secret, user, passwd):
    req_id = os.urandom(1)[0]
    authenticator = os.urandom(16)
    
    u_bytes = user.encode('utf-8')
    attr_user = bytes([1, len(u_bytes) + 2]) + u_bytes
    
    p_bytes = passwd.encode('utf-8')
    p_padded = p_bytes + b'\x00' * ((16 - (len(p_bytes) % 16)) % 16)
    if len(p_padded) == 0: p_padded = b'\x00' * 16
    
    md5_hash = hashlib.md5(secret.encode('utf-8') + authenticator).digest()
    enc_pass = bytes(a ^ b for a, b in zip(p_padded[:16], md5_hash))
    
    for i in range(16, len(p_padded), 16):
        prev_block = enc_pass[i-16:i]
        md5_hash = hashlib.md5(secret.encode('utf-8') + prev_block).digest()
        enc_pass += bytes(a ^ b for a, b in zip(p_padded[i:i+16], md5_hash))
        
    attr_pass = bytes([2, len(enc_pass) + 2]) + enc_pass
    attr_nas = bytes([4, 6, 127, 0, 0, 1])
    attr_port = bytes([5, 6, 0, 0, 0, 0])
    attr_service = bytes([6, 6, 0, 0, 0, 2])
    
    attrs = attr_user + attr_pass + attr_nas + attr_port + attr_service
    length = 20 + len(attrs)
    header = bytes([1, req_id, (length >> 8) & 0xFF, length & 0xFF]) + authenticator
    packet = header + attrs
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    try:
        sock.sendto(packet, (server, int(auth_port)))
        resp, addr = sock.recvfrom(4096)
        if resp[0] == 2:
            print(f"   🎉 SUCCESS: Received Access-Accept (Code 2) from {addr[0]}:{addr[1]}!")
            print(f"   👤 User '{user}' authenticated successfully.")
            return True
        elif resp[0] == 3:
            print(f"   ❌ REJECTED: Received Access-Reject (Code 3) from {addr[0]}:{addr[1]}.")
            return False
        else:
            print(f"   ⚠️  Received RADIUS Packet Code {resp[0]}.")
            return False
    except socket.timeout:
        print(f"   ❌ TIMEOUT: No UDP response from {server}:{auth_port} (Verify cloud firewall & UFW UDP 1812).")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False
    finally:
        sock.close()

if not test_radius("$SERVER", "$AUTH_PORT", "$SECRET", "$USERNAME", "$PASSWORD"):
    sys.exit(1)
EOF
fi

# ------------------------------------------------------------------------------
# MODE 3: Health Endpoint Check
# ------------------------------------------------------------------------------
if [ "$MODE" = "health" ]; then
    echo "🔍 Checking API Health: $API_URL/api/health"
    if command -v curl >/dev/null 2>&1; then
        curl -s "$API_URL/api/health" | (python3 -m json.tool 2>/dev/null || cat)
    else
        python3 -c "import urllib.request; print(urllib.request.urlopen('$API_URL/api/health').read().decode('utf-8'))"
    fi
    echo ""
fi
