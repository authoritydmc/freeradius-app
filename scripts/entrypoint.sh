#!/bin/bash
set -e

echo "=== Starting RajLabs FreeRADIUS Stack ==="

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-radius}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
RADIUS_SECRET="${RADIUS_SECRET:-testing123}"

export RADIUS_SECRET

echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
until PGPASSWORD="${POSTGRES_PASSWORD}" pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}"; do
  echo "PostgreSQL is unavailable - sleeping 2s"
  sleep 2
done
echo "PostgreSQL is ready!"

RAD_DIR="/etc/freeradius/3.0"
echo "Configuring FreeRADIUS at ${RAD_DIR}..."

# Bootstrap EAP-TLS certificates if not generated
if [ ! -f "${RAD_DIR}/certs/ca.pem" ] || [ ! -f "${RAD_DIR}/certs/server.pem" ]; then
  echo "Bootstrapping FreeRADIUS EAP-TLS CA and Server certificates..."
  chmod +x "${RAD_DIR}/certs/bootstrap" 2>/dev/null || true
  (cd "${RAD_DIR}/certs" && ./bootstrap) || true
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
python3 -m uvicorn app:app --host 0.0.0.0 --port 8090 --app-dir /app/api &
UVICORN_PID=$!

echo "RajLabs FreeRADIUS & Web Dashboard are up and running!"
wait -n "$RADIUSD_PID" "$UVICORN_PID"
