#!/usr/bin/env python3
"""
Sync Let's Encrypt / ACME public certificates from Traefik (Coolify) to FreeRADIUS.
Extracts live certificates for wifi.rajlabs.in / backend.rajlabs.in from acme.json
and installs them into FreeRADIUS so Android, iOS, Windows, and macOS devices
connect with zero certificate warnings using trusted public Root CAs.
"""

import os
import sys
import json
import base64
import subprocess
import argparse

DEFAULT_ACME_JSON = "/data/coolify/proxy/acme.json"
DEFAULT_TARGET_DIR = "/etc/freeradius/3.0/certs"
TARGET_DOMAINS = ["wifi.rajlabs.in", "backend.rajlabs.in", "radius.rajlabs.in"]

def extract_acme_certs(acme_json_path: str, primary_domain: str = "wifi.rajlabs.in"):
    if not os.path.exists(acme_json_path):
        raise FileNotFoundError(f"acme.json not found at {acme_json_path}")

    with open(acme_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    found_cert = None
    found_key = None
    matched_domain = None

    # Search through all resolvers (e.g. 'letsencrypt', 'http', etc.)
    for resolver_name, resolver in data.items():
        if not isinstance(resolver, dict):
            continue
        certs = resolver.get("Certificates", [])
        for entry in certs:
            domain_info = entry.get("domain", {})
            main_domain = domain_info.get("main", "")
            sans = domain_info.get("sans", []) or []
            all_domains = [main_domain] + list(sans)

            if primary_domain in all_domains or any(d in TARGET_DOMAINS for d in all_domains):
                cert_b64 = entry.get("certificate", "")
                key_b64 = entry.get("key", "")
                if cert_b64 and key_b64:
                    found_cert = base64.b64decode(cert_b64).decode("utf-8")
                    found_key = base64.b64decode(key_b64).decode("utf-8")
                    matched_domain = main_domain
                    if main_domain == primary_domain:
                        break
        if found_cert and matched_domain == primary_domain:
            break

    if not found_cert or not found_key:
        raise ValueError(f"No ACME certificate found matching {primary_domain} or {TARGET_DOMAINS} in {acme_json_path}")

    return found_cert, found_key, matched_domain

def install_certs(cert_pem: str, key_pem: str, target_dir: str):
    os.makedirs(target_dir, exist_ok=True)
    server_pem = os.path.join(target_dir, "server.pem")
    server_key = os.path.join(target_dir, "server.key")

    with open(server_pem, "w", encoding="utf-8") as f:
        f.write(cert_pem)
    os.chmod(server_pem, 0o644)

    with open(server_key, "w", encoding="utf-8") as f:
        f.write(key_pem)
    os.chmod(server_key, 0o600)

    print(f"✅ Successfully installed public ACME certificate to {server_pem} and {server_key}")

def main():
    parser = argparse.ArgumentParser(description="Sync ACME Let's Encrypt certificates to FreeRADIUS")
    parser.add_argument("--acme-json", default=os.getenv("ACME_JSON_PATH", DEFAULT_ACME_JSON), help="Path to acme.json")
    parser.add_argument("--target-dir", default=os.getenv("RADIUS_CERTS_DIR", DEFAULT_TARGET_DIR), help="Target FreeRADIUS certs dir")
    parser.add_argument("--domain", default=os.getenv("RADIUS_PUBLIC_HOST", "wifi.rajlabs.in"), help="Primary domain to extract")
    parser.add_argument("--reload-container", action="store_true", help="Reload FreeRADIUS inside running container")
    args = parser.parse_args()

    try:
        cert_pem, key_pem, domain = extract_acme_certs(args.acme_json, args.domain)
        print(f"📦 Found valid Let's Encrypt certificate for {domain}")
        install_certs(cert_pem, key_pem, args.target_dir)

        if args.reload_container:
            res = subprocess.run(["pkill", "-HUP", "-f", "freeradius"], capture_output=True)
            if res.returncode == 0:
                print("🔄 FreeRADIUS configuration reloaded successfully.")
            else:
                print("ℹ️ FreeRADIUS process not found or reloaded via container manager.")
    except Exception as e:
        print(f"❌ Error syncing certificates: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
