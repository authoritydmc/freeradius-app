#!/bin/bash
# RajLabs FreeRADIUS restore: DB dump + certs tarball from scripts/backup.sh.
# Usage: ./scripts/restore.sh <db_dump.sql.gz> <certs.tar.gz>
# Stops the stack first if running under docker compose.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <radius-db-TIMESTAMP.sql.gz> <radius-certs-TIMESTAMP.tar.gz>" >&2
  exit 1
fi

DB_DUMP="$1"
CERTS_TGZ="$2"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-radius}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
CERTS_DIR="${CERTS_DIR:-/etc/freeradius/3.0/certs}"

echo "Restoring database ${POSTGRES_DB} from ${DB_DUMP}..."
gunzip -c "${DB_DUMP}" | PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}" \
  psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1

echo "Restoring certs to ${CERTS_DIR} (previous contents moved to ${CERTS_DIR}.bak-$(date +%Y%m%d-%H%M%S))..."
if [ -d "${CERTS_DIR}" ]; then
  mv "${CERTS_DIR}" "${CERTS_DIR}.bak-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$(dirname "${CERTS_DIR}")"
tar -xzf "${CERTS_TGZ}" -C "$(dirname "${CERTS_DIR}")"
chmod 700 "${CERTS_DIR}"
chmod 600 "${CERTS_DIR}"/*.key "${CERTS_DIR}"/clients/*.p12 2>/dev/null || true

echo "Restore complete. Restart the stack (docker compose up -d) and verify:"
echo "  - Admin Console -> Status shows healthy"
echo "  - radtest for a known user returns Access-Accept"
