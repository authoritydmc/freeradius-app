#!/bin/bash
# RajLabs FreeRADIUS backup: PostgreSQL dump + CA/certs volume tarball.
# Usage: ./scripts/backup.sh [backup_dir]
# Env: POSTGRES_HOST/PORT/DB/USER/PASSWORD, CERTS_DIR (default /etc/freeradius/3.0/certs)
set -euo pipefail

OUT_DIR="${1:-./backups}"
TS="$(date +%Y%m%d-%H%M%S)"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-radius}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
CERTS_DIR="${CERTS_DIR:-/etc/freeradius/3.0/certs}"

mkdir -p "${OUT_DIR}"
DB_DUMP="${OUT_DIR}/radius-db-${TS}.sql.gz"
CERTS_TGZ="${OUT_DIR}/radius-certs-${TS}.tar.gz"

echo "Dumping PostgreSQL ${POSTGRES_DB}@${POSTGRES_HOST}:${POSTGRES_PORT} -> ${DB_DUMP}"
PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}" \
  pg_dump -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  | gzip > "${DB_DUMP}"

echo "Archiving certs ${CERTS_DIR} -> ${CERTS_TGZ}"
tar -czf "${CERTS_TGZ}" -C "$(dirname "${CERTS_DIR}")" "$(basename "${CERTS_DIR}")"
chmod 600 "${DB_DUMP}" "${CERTS_TGZ}"

# Retention: keep the newest 14 backups of each kind.
ls -t "${OUT_DIR}"/radius-db-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -t "${OUT_DIR}"/radius-certs-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f

# Second copy (the actual "backup"): push both archives to another machine,
# e.g. BACKUP_PUSH_TARGET="backup@backup-host:/srv/rajlabs-backups"
# (key-based SSH). A backup on the same disk as the database is not a backup.
if [ -n "${BACKUP_PUSH_TARGET:-}" ]; then
  if command -v scp >/dev/null 2>&1; then
    echo "Pushing archives -> ${BACKUP_PUSH_TARGET}"
    scp -q "${DB_DUMP}" "${CERTS_TGZ}" "${BACKUP_PUSH_TARGET}/"
    echo "Offsite copy complete."
  else
    echo "WARNING: BACKUP_PUSH_TARGET is set but scp is not installed — offsite copy skipped." >&2
  fi
fi

touch "${OUT_DIR}/.last_backup"
echo "Backup complete: ${DB_DUMP}, ${CERTS_TGZ}"
echo "Copy both files encrypted offsite (losing the certs archive = re-issuing every certificate)."
