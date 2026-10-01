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
# (upstream bootstrap default). NOT a client .p12 password — every client bundle
# gets its own random password from the API. Change only together with a CA
# re-bootstrap; keep it out of logs.
CA_KEY_PASSWORD="${CA_KEY_PASSWORD:-whatever}"

export RADIUS_SECRET CA_KEY_PASSWORD

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

echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
until PGPASSWORD="${POSTGRES_PASSWORD}" pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}"; do
  echo "PostgreSQL is unavailable - sleeping 2s"
  sleep 2
done
echo "PostgreSQL is ready!"

# Apply DB schema on fresh installs (GitHub issue #12): only when radcheck is
# missing, so reboots never touch existing data.
if [ -f /app/config/schema.sql ]; then
  if [ "$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT to_regclass('public.radcheck')" 2>/dev/null)" != "radcheck" ]; then
    echo "Applying database schema from /app/config/schema.sql..."
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -f /app/config/schema.sql
    echo "Database schema applied."
  else
    echo "Database schema already present (radcheck exists), skipping."
  fi
else
  echo "WARNING: /app/config/schema.sql not found, skipping auto-apply." >&2
fi

RAD_DIR="/etc/freeradius/3.0"
echo "Configuring FreeRADIUS at ${RAD_DIR}..."

# Bootstrap EAP-TLS certificates if not generated (GitHub issue #16).
# BOOTSTRAP_STRICT=1 aborts boot when bootstrap fails; default warns loudly and
# continues so signer-only / pre-provisioned installs keep booting.
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

cp -f /app/config/clients.conf "${RAD_DIR}/clients.conf"
cp -f /app/config/mods-available/sql "${RAD_DIR}/mods-available/sql"
cp -f /app/config/sites-available/default "${RAD_DIR}/sites-available/default"

ln -sf "${RAD_DIR}/mods-available/sql" "${RAD_DIR}/mods-enabled/sql"
ln -sf "${RAD_DIR}/sites-available/default" "${RAD_DIR}/sites-enabled/default"

chown -R freerad:freerad "${RAD_DIR}"
chmod 640 "${RAD_DIR}/clients.conf" "${RAD_DIR}/mods-available/sql" "${RAD_DIR}/sites-available/default"

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

echo "Starting FreeRADIUS daemon..."
freeradius -f -l stdout &
RADIUSD_PID=$!

echo "Starting FreeRADIUS API & Dashboard on port 8090..."
# --proxy-headers: correct client IPs behind Traefik/Coolify (rate limits + audit).
# UVICORN_WORKERS: raise for larger installs (default 1 keeps memory low).
python3 -m uvicorn app:app --host 0.0.0.0 --port 8090 --app-dir /app/api \
  --proxy-headers --workers "${UVICORN_WORKERS:-1}" &
UVICORN_PID=$!

echo "RajLabs FreeRADIUS & Web Dashboard are up and running!"
wait -n "$RADIUSD_PID" "$UVICORN_PID"
