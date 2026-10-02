#!/bin/bash
set -e

echo "=== Starting RajLabs FreeRADIUS Stack ==="

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-radius}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
RADIUS_SECRET="${RADIUS_SECRET:-testing123}"
# Password of the local CA private key created by FreeRADIUS `certs/bootstrap`
CA_KEY_PASSWORD="${CA_KEY_PASSWORD:-whatever}"

# Export for FreeRADIUS SQL module ($ENV{POSTGRES_*}) and sub-processes
export RADIUS_SECRET CA_KEY_PASSWORD POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD

# UTC everywhere: Python expiry uses UTC epoch and FreeRADIUS `expiration`
# parses Expiration wall-time in local zone — these must agree.
export TZ=UTC

# Fail closed on published default admin/session secrets (GitHub issue #5).
weak_secret() {
  case "$1" in
    ""|"testing123"|"admin123"|"password"|"changeme"|"change-me"|"change_this_session_secret_in_production_32_chars!"|"YourStrongRadiusSharedSecret_123!"|"YourAdminPassword123!"|"YourStrongAdminPassword_123!"|"YourRandomSecretKeyForSigningSessions_32_Chars"|"YourRandom32CharacterSessionKey_abc123!") return 0;;
    *) return 1;;
  esac
}
if weak_secret "${RADIUS_ADMIN_PASSWORD:-}" || weak_secret "${SESSION_SECRET:-}" || [ "${#SESSION_SECRET}" -lt 32 ]; then
  echo "ERROR: RADIUS_ADMIN_PASSWORD and SESSION_SECRET must be set to strong, non-default values (>=32 chars for SESSION_SECRET)." >&2
  echo "Generate one with: openssl rand -hex 32" >&2
  echo "Refusing to boot. See .env.example." >&2
  exit 1
fi
if weak_secret "${RADIUS_SECRET:-}"; then
  echo "WARNING: RADIUS_SECRET is a published default — rotate it now and update every NAS/router." >&2
fi

PG_WAIT_TIMEOUT="${PG_WAIT_TIMEOUT:-30}"
elapsed=0
echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT} (timeout ${PG_WAIT_TIMEOUT}s)..."
until PGPASSWORD="${POSTGRES_PASSWORD}" pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}"; do
  if [ "$elapsed" -ge "$PG_WAIT_TIMEOUT" ]; then
    echo "FATAL: PostgreSQL unreachable at ${POSTGRES_HOST}:${POSTGRES_PORT} after ${PG_WAIT_TIMEOUT}s. Exiting." >&2
    exit 1
  fi
  echo "PostgreSQL is unavailable - sleeping 2s"
  sleep 2
  elapsed=$((elapsed + 2))
done
echo "PostgreSQL is ready!"

# Apply versioned DB migrations (api/migrations/*.sql via api/migrate.py).
# Forward-only, idempotent, tracked in schema_migrations — safe on every boot.
# Fails fast on error (Issue #31).
if python3 -c "import api.migrate" 2>/dev/null; then
  echo "Applying versioned database migrations..."
  if ! python3 -m api.migrate; then
    echo "FATAL: Database migrations failed. Refusing to boot against broken schema." >&2
    exit 1
  fi
elif [ -f /app/config/schema.sql ]; then
  if [ "$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT to_regclass('public.radcheck')" 2>/dev/null)" != "radcheck" ]; then
    echo "Applying database schema from /app/config/schema.sql..."
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -f /app/config/schema.sql
    echo "Database schema applied."
  else
    echo "Database schema already present (radcheck exists), skipping."
  fi
else
  echo "WARNING: no migrator or schema.sql found, skipping auto-apply." >&2
fi

RAD_DIR="/etc/freeradius/3.0"
echo "Configuring FreeRADIUS at ${RAD_DIR}..."

# Bootstrap EAP-TLS certificates if not generated (GitHub issue #16).
BOOTSTRAP_STRICT="${BOOTSTRAP_STRICT:-0}"
if [ ! -f "${RAD_DIR}/certs/ca.pem" ] || [ ! -f "${RAD_DIR}/certs/server.pem" ]; then
  echo "Bootstrapping FreeRADIUS EAP-TLS CA and Server certificates..."
  chmod +x "${RAD_DIR}/certs/bootstrap" 2>/dev/null || true
  if (cd "${RAD_DIR}/certs" && ./bootstrap); then
    echo "Certificate bootstrap completed."
  else
    echo "ERROR: Certificate bootstrap failed (no ca.pem/server.pem)." >&2
    if [ "${BOOTSTRAP_STRICT}" = "1" ]; then
      echo "BOOTSTRAP_STRICT=1 — refusing to boot without PKI material." >&2
      exit 1
    fi
    echo "WARNING: continuing without fresh PKI material; EAP-TLS will fail until fixed." >&2
  fi
fi

mkdir -p "${RAD_DIR}/certs/clients"

# --- EAP server identity (Public ACME / Let's Encrypt or Local CA) --------
if [ -z "${EAP_SERVER_CN:-}" ]; then
  if [ -n "${RADIUS_PUBLIC_HOST:-}" ]; then
    EAP_SERVER_CN="${RADIUS_PUBLIC_HOST}"
  elif [ -n "${COOLIFY_FQDN:-}" ]; then
    EAP_SERVER_CN="$(printf '%s' "${COOLIFY_FQDN}" | tr ',' '\n' | grep -v '/' | head -n 1)"
    if [ -z "${EAP_SERVER_CN}" ]; then
      EAP_SERVER_CN="$(printf '%s' "${COOLIFY_FQDN}" | tr ',' '\n' | head -n 1 | cut -d'/' -f1)"
    fi
  fi
fi
EAP_SERVER_CN="${EAP_SERVER_CN:-wifi.rajlabs.in}"

# Check for mounted or provided public Let's Encrypt / ACME certificates
ACME_IMPORTED=0
if [ -n "${EAP_SERVER_CERT_BASE64:-}" ] && [ -n "${EAP_SERVER_KEY_BASE64:-}" ]; then
  echo "Loading public Server Certificate from base64 environment variables..."
  printf '%s' "${EAP_SERVER_CERT_BASE64}" | base64 -d > "${RAD_DIR}/certs/server.pem"
  printf '%s' "${EAP_SERVER_KEY_BASE64}" | base64 -d > "${RAD_DIR}/certs/server.key"
  chmod 644 "${RAD_DIR}/certs/server.pem"
  chmod 600 "${RAD_DIR}/certs/server.key"
  ACME_IMPORTED=1
elif [ -f "/app/certs/server.pem" ] && [ -f "/app/certs/server.key" ]; then
  echo "Importing public Server Certificate from /app/certs/..."
  cp -f "/app/certs/server.pem" "${RAD_DIR}/certs/server.pem"
  cp -f "/app/certs/server.key" "${RAD_DIR}/certs/server.key"
  chmod 644 "${RAD_DIR}/certs/server.pem"
  chmod 600 "${RAD_DIR}/certs/server.key"
  ACME_IMPORTED=1
elif [ -f "${RAD_DIR}/certs/acme/server.pem" ] && [ -f "${RAD_DIR}/certs/acme/server.key" ]; then
  echo "Importing public Server Certificate from ${RAD_DIR}/certs/acme/..."
  cp -f "${RAD_DIR}/certs/acme/server.pem" "${RAD_DIR}/certs/server.pem"
  cp -f "${RAD_DIR}/certs/acme/server.key" "${RAD_DIR}/certs/server.key"
  chmod 644 "${RAD_DIR}/certs/server.pem"
  chmod 600 "${RAD_DIR}/certs/server.key"
  ACME_IMPORTED=1
elif [ -f "/traefik-certs/acme.json" ] || [ -f "/etc/traefik/certs/acme.json" ] || [ -f "/data/coolify/proxy/acme.json" ]; then
  ACME_SRC=""
  for candidate in "/traefik-certs/acme.json" "/etc/traefik/certs/acme.json" "/data/coolify/proxy/acme.json"; do
    if [ -f "${candidate}" ]; then
      ACME_SRC="${candidate}"
      break
    fi
  done
  echo "Found Traefik/Coolify ACME file at ${ACME_SRC} — extracting public certificate for ${EAP_SERVER_CN}..."
  if python3 /app/scripts/sync-acme-certs.py --acme-json "${ACME_SRC}" --domain "${EAP_SERVER_CN}" --out-dir "${RAD_DIR}/certs"; then
    echo "Public Let's Encrypt certificate extracted and loaded for ${EAP_SERVER_CN}."
    ACME_IMPORTED=1
  else
    echo "WARNING: Could not extract domain ${EAP_SERVER_CN} from ${ACME_SRC}."
  fi
fi

if [ "${ACME_IMPORTED}" = "1" ]; then
  echo "FreeRADIUS is configured with Public Trusted Server Certificate for ${EAP_SERVER_CN}."
else
  # SAN validation for Local CA server cert
  if [ -f "${RAD_DIR}/certs/server.pem" ] && [ -f "${RAD_DIR}/certs/ca.pem" ] && [ -f "${RAD_DIR}/certs/ca.key" ]; then
    if printf '%s' "${EAP_SERVER_CN}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
      EAP_SAN="IP:${EAP_SERVER_CN}"
      EAP_SAN_MATCH="${EAP_SERVER_CN}"
    else
      EAP_SAN="DNS:${EAP_SERVER_CN}"
      EAP_SAN_MATCH="${EAP_SERVER_CN}"
    fi

    if openssl x509 -in "${RAD_DIR}/certs/server.pem" -noout -ext subjectAltName 2>/dev/null | grep -q "${EAP_SAN_MATCH}"; then
      echo "EAP server certificate already carries SAN ${EAP_SAN_MATCH}."
    else
      echo "EAP server certificate lacks SAN ${EAP_SAN_MATCH} — re-issuing from local CA..."
      (
        cd "${RAD_DIR}/certs" || exit 1
        TS="$(date +%Y%m%d%H%M%S)"
        cp -f server.pem "server.pem.bak.${TS}" 2>/dev/null || true
        cp -f server.key "server.key.bak.${TS}" 2>/dev/null || true
        KEYPASS_ARGS=""
        if openssl rsa -in server.key -passin env:CA_KEY_PASSWORD -noout >/dev/null 2>&1; then
          KEYPASS_ARGS="-passin env:CA_KEY_PASSWORD"
        elif ! openssl rsa -in server.key -noout >/dev/null 2>&1; then
          echo "Existing server.key unreadable — generating a fresh key..."
          openssl genrsa -out server.key 2048
        fi
        # shellcheck disable=SC2086
        if openssl req -new -key server.key ${KEYPASS_ARGS} -out /tmp/eap-server.csr \
             -subj "/C=IN/ST=Delhi/O=RajLabs/CN=${EAP_SERVER_CN}" \
          && printf "subjectAltName=%s\n" "${EAP_SAN}" > /tmp/eap-server.ext \
          && openssl x509 -req -in /tmp/eap-server.csr \
             -CA ca.pem -CAkey ca.key -passin env:CA_KEY_PASSWORD \
             -CAcreateserial -days 825 -sha256 -extfile /tmp/eap-server.ext \
             -out server.pem \
          && openssl verify -CAfile ca.pem server.pem >/dev/null \
          && openssl x509 -in server.pem -noout -ext subjectAltName 2>/dev/null | grep -q "${EAP_SAN_MATCH}"; then
          echo "EAP server certificate re-issued with SAN ${EAP_SAN_MATCH}."
        else
          echo "WARNING: server cert re-issue failed — restoring previous files." >&2
          cp -f "server.pem.bak.${TS}" server.pem 2>/dev/null || true
          cp -f "server.key.bak.${TS}" server.key 2>/dev/null || true
        fi
        rm -f /tmp/eap-server.csr /tmp/eap-server.ext
      ) || echo "WARNING: EAP identity fixup failed; continuing with current server.pem." >&2
    fi
  fi
fi

if [ -f "${RAD_DIR}/certs/server.pem" ]; then
  echo "Effective EAP server identity (tell users to type the DNS name as Domain on Android):"
  openssl x509 -in "${RAD_DIR}/certs/server.pem" -noout -subject -issuer -ext subjectAltName 2>/dev/null || true
fi

# Guarded copy of configuration files
cp -f /app/config/clients.conf "${RAD_DIR}/clients.conf"
cp -f /app/config/mods-available/sql "${RAD_DIR}/mods-available/sql"
cp -f /app/config/sites-available/default "${RAD_DIR}/sites-available/default"
if [ -f /app/config/mods-available/eap ]; then
  cp -f /app/config/mods-available/eap "${RAD_DIR}/mods-available/eap"
  ln -sf "${RAD_DIR}/mods-available/eap" "${RAD_DIR}/mods-enabled/eap"
fi
if [ -f /app/config/sites-available/inner-tunnel ]; then
  cp -f /app/config/sites-available/inner-tunnel "${RAD_DIR}/sites-available/inner-tunnel"
  ln -sf "${RAD_DIR}/sites-available/inner-tunnel" "${RAD_DIR}/sites-enabled/inner-tunnel"
fi
if [ -f /app/config/dictionary ]; then
  cp -f /app/config/dictionary "${RAD_DIR}/dictionary"
fi
if [ -f /app/config/policy.d/rajlabs ]; then
  cp -f /app/config/policy.d/rajlabs "${RAD_DIR}/policy.d/rajlabs"
fi

ln -sf "${RAD_DIR}/mods-available/sql" "${RAD_DIR}/mods-enabled/sql"
ln -sf "${RAD_DIR}/sites-available/default" "${RAD_DIR}/sites-enabled/default"

chown -R freerad:freerad "${RAD_DIR}"
chmod 640 "${RAD_DIR}/clients.conf" "${RAD_DIR}/mods-available/sql" "${RAD_DIR}/sites-available/default"
[ -f "${RAD_DIR}/sites-available/inner-tunnel" ] && chmod 640 "${RAD_DIR}/sites-available/inner-tunnel" || true
[ -f "${RAD_DIR}/policy.d/rajlabs" ] && chmod 640 "${RAD_DIR}/policy.d/rajlabs" || true

# Ensure FreeRADIUS authentication accepts/rejects log to container stdout
sed -i 's/^[[:space:]]*destination = .*/\tdestination = stdout/' "${RAD_DIR}/radiusd.conf"
sed -i 's/^[[:space:]]*auth = .*/\tauth = yes/' "${RAD_DIR}/radiusd.conf"
sed -i 's/^[[:space:]]*#\?[[:space:]]*auth_badpass = .*/\tauth_badpass = yes/' "${RAD_DIR}/radiusd.conf"
sed -i 's/^[[:space:]]*#\?[[:space:]]*auth_goodpass = .*/\tauth_goodpass = yes/' "${RAD_DIR}/radiusd.conf"

echo "Validating FreeRADIUS configuration syntax..."
freeradius -C -l stdout || {
  echo "FreeRADIUS configuration syntax check failed!"
  exit 1
}
echo "FreeRADIUS configuration is valid."

cleanup() {
  echo "Terminating FreeRADIUS and API..."
  kill -TERM "$RADIUSD_PID" 2>/dev/null || true
  kill -TERM "$UVICORN_PID" 2>/dev/null || true
  wait "$RADIUSD_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

if [ "${RADIUS_DEBUG:-0}" = "1" ] || [ "${DEBUG:-false}" = "true" ]; then
  echo "Starting FreeRADIUS in verbose DEBUG mode (-X)..."
  freeradius -X -l stdout &
else
  echo "Starting FreeRADIUS daemon (auth logging enabled)..."
  freeradius -f -l stdout &
fi
RADIUSD_PID=$!

echo "Starting FreeRADIUS API & Dashboard on port 8090..."
# --proxy-headers and --forwarded-allow-ips: real client IPs behind Traefik/Coolify.
# UVICORN_WORKERS: raise for larger installs (default 1).
python3 -m uvicorn app:app --host 0.0.0.0 --port 8090 --app-dir /app/api \
  --proxy-headers --forwarded-allow-ips='*' --workers "${UVICORN_WORKERS:-1}" &
UVICORN_PID=$!

echo "RajLabs FreeRADIUS & Web Dashboard are up and running!"
wait -n "$RADIUSD_PID" "$UVICORN_PID"
