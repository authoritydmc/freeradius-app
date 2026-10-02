"""api/db_init.py — backward-compat shim.

Schema is owned by versioned migrations in api/migrations/*.sql,
applied via api/migrate.py (run_migrations / ensure_migrated).

This module is kept so old imports (init_all_tables, get_db_connection)
keep working. Do NOT add new DDL here — add a new migration file instead.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

from urllib.parse import urlparse


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
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )


def init_all_tables():
    """Deprecated: delegates to the versioned migration runner."""
    try:
        from api.migrate import run_migrations
    except ImportError:  # pragma: no cover - script context
        from migrate import run_migrations
    return run_migrations()
