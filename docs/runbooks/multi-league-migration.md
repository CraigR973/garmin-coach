# Runbook: Multi-League Migration

Complete operator checklist for applying the multi-league schema changes
(migrations `011`–`014`) and the Steele backfill against staging or prod.

Migrations 011–013 are additive and reversible. Migration 014 (NOT NULL
constraints) is forward-only in practice — rolling it back requires
re-allowing NULLs that should not exist.

The full design lives in [`docs/multi-league-architecture.md`](../multi-league-architecture.md).

---

## Prerequisites

- `DATABASE_URL` exported in the shell, pointing at the target environment.
- Repo at the commit that ships migration 014 (the final M8 commit).
- A pre-flight backup taken via [`restore.md`](restore.md) step 1.
- `scripts/backfill_multi_league.py` reachable from repo root.
- `apps/api/.venv` populated (`pip install -r apps/api/requirements-dev.txt`).

---

## Step 1 — Build the sidecar JSON

Produce a JSON file mapping every existing profile id to its real email + name.
Profile ids: `SELECT id, display_name FROM profiles WHERE deleted_at IS NULL`.

Shape:

```json
{
  "11111111-1111-1111-1111-111111111111": {
    "email": "craigr973@sky.com",
    "first_name": "Craig",
    "last_name": "Robinson"
  },
  "22222222-2222-2222-2222-222222222222": {
    "email": "lewis@example.com",
    "first_name": "Lewis",
    "last_name": "Steele"
  }
}
```

Rules:
- All fields are optional. Missing values fall back to derived defaults
  (`email = pending+<slug>@steele.invalid`, names split from `display_name`).
- Profiles not listed in the sidecar still get backfilled with the derived
  defaults — they just won't have a real email until the player updates it.
- Email collisions abort the script; fix the sidecar before re-running.

Save the file outside the repo (e.g. `~/.wc2026/sidecar-prod.json`); it
contains PII and must NOT be committed.

---

## Step 2 — Apply migrations 011–013 (schema + backfill preparation)

**Skip if already applied.** `SELECT version_num FROM alembic_version` tells you where you are.

```bash
DATABASE_URL="$TARGET_DB_URL" \
  /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \
  -m alembic -c /Users/craigrobinson/wc_2026_predictor/apps/api/alembic.ini \
  upgrade 013
```

Verify:

```sql
SELECT version_num FROM alembic_version;             -- expect '013'
SELECT to_regclass('public.leagues');                -- expect 'leagues'
SELECT to_regclass('public.league_memberships');     -- expect 'league_memberships'
SELECT to_regclass('public.league_join_requests');   -- expect 'league_join_requests'
SELECT column_name FROM information_schema.columns
  WHERE table_name = 'profiles' AND column_name IN (
    'email','first_name','last_name','email_verified_at','site_role'
  );                                                  -- expect all 5 (nullable at this stage)
```

---

## Step 3 — Dry-run the backfill

This connects to the DB, runs every UPDATE/INSERT inside a transaction,
prints a summary, and **rolls back**. No data changes.

```bash
DATABASE_URL="$TARGET_DB_URL" \
PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api \
  /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \
  /Users/craigrobinson/wc_2026_predictor/scripts/backfill_multi_league.py \
  --sidecar ~/.wc2026/sidecar-prod.json
```

Expected output (numbers vary by environment):

```
=== Multi-league backfill — DRY RUN ===
  Steele league id      : <uuid>
  League created        : True
  Profiles updated      : 15 / 15
  Memberships created   : 15
  Memberships restored  : 0
  Admin memberships     : 1
```

Hard checks: `League created` must be True on the first run; `Admin
memberships` must be exactly 1 (Craig). Warnings about duplicate emails
or operator role-mismatch must be resolved before applying.

---

## Step 4 — Apply the backfill

If the dry-run summary looks right:

```bash
DATABASE_URL="$TARGET_DB_URL" \
PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api \
  /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \
  /Users/craigrobinson/wc_2026_predictor/scripts/backfill_multi_league.py \
  --sidecar ~/.wc2026/sidecar-prod.json \
  --apply
```

The script self-aborts if:
- migration 011 has not been applied (`alembic_version` < `011`);
- no active profile has `display_name = 'Craig'`;
- the resulting Steele league privacy is not `'private'`;
- zero admin memberships would be created.

In any of those cases, no transaction commits.

---

## Step 5 — Post-apply verification

```sql
-- One Steele league, private, Craig as the creator.
SELECT slug, name, privacy, max_members
FROM leagues
WHERE slug = 'steele-spreadsheet';

-- Every active profile is a member.
SELECT
  (SELECT count(*) FROM profiles WHERE deleted_at IS NULL)            AS profiles,
  (SELECT count(*) FROM league_memberships m
     JOIN leagues l ON l.id = m.league_id
     WHERE l.slug = 'steele-spreadsheet' AND m.deleted_at IS NULL)    AS members,
  (SELECT count(*) FROM league_memberships m
     JOIN leagues l ON l.id = m.league_id
     WHERE l.slug = 'steele-spreadsheet' AND m.role = 'admin')        AS admins;
-- Expect: profiles == members; admins = 1.

-- Identity columns populated.
SELECT count(*) AS missing_email FROM profiles
  WHERE deleted_at IS NULL AND email IS NULL;
SELECT count(*) AS missing_site_role FROM profiles
  WHERE deleted_at IS NULL AND site_role IS NULL;
-- Both expected 0.
```

---

## Step 6 — Apply migration 014 (NOT NULL constraints)

**Run only after the backfill has been applied and Step 5 confirms zero NULLs.**
Migration 014 has a built-in guard that aborts if any active profile has a
NULL identity field, so it is safe to run and will tell you exactly how many
rows need fixing if you've missed any.

```bash
DATABASE_URL="$TARGET_DB_URL" \
  /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \
  -m alembic -c /Users/craigrobinson/wc_2026_predictor/apps/api/alembic.ini \
  upgrade 014
```

Verify:

```sql
SELECT version_num FROM alembic_version;  -- expect '014'

-- Columns are now NOT NULL
SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_name = 'profiles'
  AND column_name IN ('email', 'first_name', 'last_name', 'site_role');
-- All four rows: is_nullable = 'NO'

-- Full unique index (no WHERE clause) replaces the partial one
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'profiles' AND indexname = 'ix_profiles_email_unique_lower';
-- indexdef should NOT contain 'WHERE'
```

If the migration aborts with a NULL-count error, rerun the backfill against
the affected profiles (see Step 4), then retry.

---

## Step 7 — Smoke test (staging only)

After staging cutover:

```bash
curl -sf https://<staging-api>/api/v1/health
```

All endpoints must continue to work. Verify email-based login works and that
the deprecated paths (`/api/v1/leaderboard`, `/api/v1/players`, etc.) return
404 — not 410.

---

## Rollback

The migration is reversible. Roll back if Step 5 surfaces unexpected
state and you can't fix forward in a few minutes.

```bash
DATABASE_URL="$TARGET_DB_URL" \
  /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \
  -m alembic -c /Users/craigrobinson/wc_2026_predictor/apps/api/alembic.ini \
  downgrade -1
```

`downgrade()` refuses to run if duplicate `display_name` values exist in
`profiles` (the restored UNIQUE constraint would fail). Resolve duplicates
manually before retrying.

The `v1.0-pre-multi-league` tag on `main` is the application-side rollback
target if the issue is broader than the schema alone.

---

## Notes

- The script is **idempotent** — re-running with the same sidecar produces
  the same state (no duplicate league row, no duplicate memberships).
- Email collisions print a warning but do not abort. Fix the sidecar and
  re-run before continuing.
- The script writes `email_verified_at = NOW()` only for the operator
  (`display_name = 'Craig'`). Everyone else verifies via the M4 flow.
- Per-profile `site_role` derives from the legacy `profiles.role` column:
  `admin → superadmin`, `player → user`.
