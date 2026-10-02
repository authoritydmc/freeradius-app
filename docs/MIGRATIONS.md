# Database migrations — how it works

Single source of truth: **`api/migrations/*.sql`**, applied by **`api/migrate.py`**.

## Why not Alembic / scattered `ensure_*`?

- No ORM in this codebase (raw `psycopg2`) → Alembic would add SQLAlchemy for zero benefit.
- The old pattern (`init_all_tables()` + `ensure_plans_table()` + `ensure_audit_table()` …
  called from request handlers and startup) was racy, slow, and drift-prone: every
  call-site could create a slightly different table, and "legacy price rewrites"
  (₹20/₹100/₹250 → ₹10/₹30/₹51.35) kept mutating user data on boot.
- This project is 1 day old — there is **no legacy system**. `001_baseline.sql`
  creates the full clean schema (current ₹10/₹30/₹51.35 seeds only) exactly once.

## Layout

```
api/migrations/001_baseline.sql      # full schema + clean seeds (never edit after apply)
api/migrations/002_perf_indexes.sql  # example follow-up (indexes for overview/audit)
api/migrate.py                       # runner: schema_migrations table, ordered, idempotent
scripts/entrypoint.sh                # runs `python3 -m api.migrate` on every boot
api/app.py lifespan                  # runs run_migrations() at API startup
```

## Rules

1. **Forward-only.** Never edit an applied file. New change → new file `003_<slug>.sql`.
2. **Idempotent.** Every statement must be re-runnable (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`).
3. **Env-dependent seeds stay in code.** `RADIUS_SECRET`-based NAS localhost seed lives in
   `run_migrations()` (`_seed_nas_localhost`), not in SQL.
4. **Request handlers never run DDL.** They call `ensure_migrated()` (cached no-op after
   first call). Old `ensure_*` / `init_all_tables` are deprecated shims delegating to it.
5. **Test locally:** `python -m api.migrate` (uses `POSTGRES_*` / `DATABASE_URL` env).

## Adding a migration

```sql
-- api/migrations/003_add_column.sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS notes TEXT;
```

Then `python -m api.migrate` locally, commit both the file and the rebuilt
`api/static/dist` if frontend changed. CI runs `pytest` + `npm run lint` + `vite build`.
