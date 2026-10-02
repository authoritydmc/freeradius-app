# Backup & High Availability

Short version: **do not dual-write from the app.** PostgreSQL already solves
"two copies" at the right layer. This stack uses three complementary mechanisms:

| Layer | What | Protects against | RPO / RTO |
|---|---|---|---|
| Streaming replica (async) | Live second copy on another host | Primary host/disk death | Seconds of writes / minutes |
| Nightly dumps + offsite push | `scripts/backup.sh` → `BACKUP_PUSH_TARGET` | Accidental deletes, corruption, both hosts dying | Up to 24h / ~30 min restore |
| Certs archive | Same backup run (DB alone is useless without `ca.key`) | CA loss (= re-issuing every certificate) | — |

## Why not write to two databases from the code?

- FreeRADIUS `rlm_sql` has **no write broadcast**: `redundant { sql1 sql2 }`
  fails over but only the first success processes, so accounting/postauth
  would still land in exactly one DB.
- Dual-write in the API (every INSERT to two connections, two-phase commit
  by hand) buys split-brain bugs: half-written users, diverging passwords,
  irreconcilable radacct sequences.
- Postgres streaming replication copies **everything byte-identical**
  (RADIUS + API rows, no code paths to maintain).

## 1. Live replica (second PostgreSQL)

On a second host, run stock Postgres and bootstrap from the primary:

```bash
# on the standby host (same Postgres major version, same superuser password)
pg_basebackup -h <primary-ip> -p 5432 -U postgres -D /var/lib/postgresql/data \
  -Fp -Xs -P -R
# -R writes standby.signal + primary_conninfo automatically; then start postgres.
```

`postgresql.conf` (standby): `hot_standby = on`.
`postgresql.conf` (primary): `wal_level = replica`, `max_wal_senders >= 3`.

Point the API at both hosts — it lands on the writable node automatically:

```env
POSTGRES_HOST=pg-primary,pg-standby
```

FreeRADIUS keeps its single `server` entry (it cannot do multi-host), so it
stays on the primary. On failover: promote the standby
(`pg_ctl promote` / `SELECT pg_promote()`), repoint FreeRADIUS `POSTGRES_HOST`
to the promoted host (or swap a DNS name / virtual IP), restart the container.

## 2. Failover behaviour

- **API + portal**: automatic via `POSTGRES_HOST="primary,standby"` — writes
  always land on the primary, reads never hit a read-only node by accident.
- **FreeRADIUS auth/accounting**: manual repoint + container restart
  (or front both DBs with PgBouncer/HAProxy and repoint that instead —
  then nothing restarts).
- **Migrations** (`api/migrate.py`) also use the writable-node rule, so a
  boot against a standby can never half-migrate a read-only copy.

## 3. Offsite dumps (the real backup)

```bash
# nightly cron on any host that can reach Postgres + SSH
POSTGRES_HOST=pg-primary POSTGRES_PASSWORD=... \
BACKUP_PUSH_TARGET=backup@backup-host:/srv/rajlabs-backups \
  ./scripts/backup.sh /srv/rajlabs-backups
```

What you get per run: `radius-db-<ts>.sql.gz` + `radius-certs-<ts>.tar.gz`
(14-run rotation). Test the restore quarterly on a scratch host:

```bash
./scripts/restore.sh radius-db-<ts>.sql.gz radius-certs-<ts>.tar.gz
```

Rule of thumb: an untested restore is not a backup. The DB dump without the
certs archive is only half a restore — `ca.key` lives in the certs tarball.
