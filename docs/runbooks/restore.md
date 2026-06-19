# Runbook: Database Restore

Use this runbook to restore the WC 2026 Predictor database from a backup file.

---

## Prerequisites

- `psql` installed and accessible in your `PATH`
- The target database connection string (from Railway or your staging environment)
- A backup `.sql` file downloaded from the admin backup endpoint

---

## Step 1 — Create a backup (before restoring)

Always take a fresh backup of the current state before overwriting anything.

```bash
# Via the admin API
curl -X POST https://<your-api-domain>/api/v1/admin/backup \
  -H "Authorization: Bearer <admin-jwt-token>"
```

Download the latest backup to your machine:

```bash
curl -OJ https://<your-api-domain>/api/v1/admin/backups/<filename> \
  -H "Authorization: Bearer <admin-jwt-token>"
```

---

## Step 2 — Download the backup you want to restore

```bash
# List available backups
curl https://<your-api-domain>/api/v1/admin/backups \
  -H "Authorization: Bearer <admin-jwt-token>"

# Download the one you need
curl -OJ https://<your-api-domain>/api/v1/admin/backups/wc2026_YYYYMMDD_HHMMSS.sql \
  -H "Authorization: Bearer <admin-jwt-token>"
```

---

## Step 3 — Stop the application

Prevent new writes during the restore. In Railway:

1. Go to the Railway dashboard → your backend service
2. Click **Settings** → **Suspend** (or scale instances to 0)

---

## Step 4 — Drop and recreate the database schema

> **Warning:** This destroys all existing data. Only proceed if you are certain.

```bash
# Connect to the database
psql "postgresql://user:password@host:port/dbname"

# Drop all tables (or drop/recreate the entire database on staging)
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
\q
```

On a Supabase staging branch, you can instead reset via the Supabase CLI:

```bash
supabase db reset --db-url postgresql://...
```

---

## Step 5 — Restore the backup

```bash
psql "postgresql://user:password@host:port/dbname" \
  -f wc2026_YYYYMMDD_HHMMSS.sql
```

If the dump was made with `pg_dump --format=custom`, use `pg_restore` instead:

```bash
pg_restore --clean --no-acl --no-owner \
  -d "postgresql://user:password@host:port/dbname" \
  wc2026_YYYYMMDD_HHMMSS.sql
```

---

## Step 6 — Run migrations (if restoring to a newer schema)

If the backup is from an older schema version and the app has since migrated:

```bash
alembic upgrade head
```

---

## Step 7 — Verify

```bash
psql "postgresql://user:password@host:port/dbname" -c "
SELECT
  (SELECT COUNT(*) FROM profiles)   AS players,
  (SELECT COUNT(*) FROM matches)    AS matches,
  (SELECT COUNT(*) FROM predictions) AS predictions;
"
```

Check that the row counts match your expectations.

---

## Step 8 — Resume the application

In Railway:

1. Go to **Settings** → **Resume** (or scale instances back to 1)
2. Hit the health endpoint to confirm the app is up:

```bash
curl https://<your-api-domain>/api/v1/health
```

---

## Notes

- **Backup location on Railway:** The `BACKUP_DIR` defaults to `/tmp/wc2026_backups`. Files in `/tmp` are ephemeral — **download backups immediately** after creation. Store copies externally (e.g. in your own S3 bucket or local machine).
- **`pg_dump` availability:** The backup API requires `pg_dump` in the server's `PATH`. Verify this is present in your Railway Docker image. If not, use the Supabase dashboard's built-in backup feature instead.
- **Scheduled backups:** A daily backup runs at 03:00 UTC (see `scheduler.py: run_scheduled_backup`). Download and archive these regularly.
- **Pre-tournament backup:** Manually trigger `POST /admin/backup` the night before the tournament starts (June 10, 2026) and download the file to a safe location.
