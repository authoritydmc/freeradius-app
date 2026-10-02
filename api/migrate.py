"""
api/migrate.py — versioned PostgreSQL migration runner (single source of truth).

Why this instead of Alembic / scattered ensure_* / CREATE TABLE IF NOT EXISTS
in request handlers?
- No ORM in this codebase (raw psycopg2) → Alembic adds SQLAlchemy for zero benefit.
- Per-request DDL (init_all_tables / ensure_plans_table / ensure_audit_table …)
  is racy, slow, and hides schema drift: every endpoint could create a slightly
  different table.
- This runner is dbmate/golang-migrate style: ordered *.sql files in
  api/migrations/, tracked in schema_migrations, forward-only, idempotent,
  safe to run on every boot and from CI / entrypoint.

Usage:
    python -m api.migrate          # apply pending migrations (uses env PG vars)
    from api.migrate import run_migrations, ensure_migrated
"""
import logging
import os
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse

logger = logging.getLogger("radius.migrate")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_migrated_cache = {"done": False}


def get_db_connection():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    dbname = os.getenv("POSTGRES_DB", "radius")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")

    db_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRESQL_URL")
    if db_url:
        try:
            parsed = urlparse(db_url)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
            if parsed.path and len(parsed.path) > 1:
                dbname = parsed.path.lstrip("/")
            if parsed.username:
                user = parsed.username
            if parsed.password:
                password = parsed.password
        except Exception:
            pass

    return psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password,
        cursor_factory=RealDictCursor, connect_timeout=5,
        # Multi-host failover: POSTGRES_HOST="primary,standby" lands on the
        # writable node (single-host behaviour untouched).
        **({"target_session_attrs": os.getenv("PG_TARGET_SESSION_ATTRS", "read-write")} if "," in (host or "") else {}),
    )


def _list_migration_files():
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return files


def _ensure_version_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def _applied_versions(cur):
    cur.execute("SELECT version FROM schema_migrations")
    return {r["version"] for r in cur.fetchall()}


def _seed_nas_localhost(cur):
    """Env-dependent seed kept in code (not SQL): localhost NAS for tests/dev."""
    try:
        cur.execute("SELECT COUNT(*) AS c FROM nas")
        if (cur.fetchone() or {}).get("c", 1) == 0:
            cur.execute(
                "INSERT INTO nas (nasname, shortname, type, secret, description)"
                " VALUES ('127.0.0.1', 'localhost', 'other', %s, 'Localhost Test Client')",
                (os.getenv("RADIUS_SECRET", "testing123"),),
            )
    except Exception as e:
        logger.debug("NAS localhost seed skipped: %s", e)


def run_migrations() -> list:
    """Apply all pending *.sql migrations in order. Returns applied versions."""
    files = _list_migration_files()
    if not files:
        logger.warning("No migration files found in %s", MIGRATIONS_DIR)
        return []
    conn = get_db_connection()
    applied_now = []
    try:
        with conn.cursor() as cur:
            _ensure_version_table(cur)
            conn.commit()
            done = _applied_versions(cur)
            for f in files:
                version = f.stem  # e.g. 001_baseline
                if version in done:
                    continue
                sql = f.read_text(encoding="utf-8")
                logger.info("Applying migration %s", f.name)
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (version,),
                )
                conn.commit()
                applied_now.append(version)
            _seed_nas_localhost(cur)
            conn.commit()
    finally:
        conn.close()
    if applied_now:
        logger.info("Migrations applied: %s", applied_now)
    _migrated_cache["done"] = True
    return applied_now


def ensure_migrated():
    """Cheap per-process guard for request handlers (replaces ensure_*/init_* calls).

    First call in the process applies pending migrations; later calls are no-ops.
    If the DB is unreachable at import/startup time, the error surfaces on the
    first request instead of crashing the whole API — same resilience as before,
    without per-request DDL.
    """
    if _migrated_cache["done"]:
        return
    run_migrations()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    done = run_migrations()
    print(f"Applied: {done if done else 'nothing pending — schema up to date'}")
