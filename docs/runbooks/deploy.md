# Runbook: First-Time Deployment

Use this runbook to deploy the WC 2026 Predictor from scratch onto Supabase (Postgres) + Railway (FastAPI backend) + Vercel (React frontend). Follow the steps in order; each one assumes the previous step succeeded.

Run this **twice** — once for a `staging` environment, then again for `production`. Staging shakes out env-var typos before any real players see them.

---

## Prerequisites

- Accounts: GitHub (repo access), [Supabase](https://supabase.com), [Railway](https://railway.app), [Vercel](https://vercel.com)
- CLIs installed locally:
  - `psql` (for migrations + manual SQL)
  - `node` ≥ 20 and `pnpm`
  - Python 3.11 with the project venv at `apps/api/.venv/`
  - `railway` CLI (`npm i -g @railway/cli`) — only for `railway logs`; deploys go through GitHub, not the CLI
  - `vercel` CLI (`npm i -g vercel`)
- A working clone of this repo at `/Users/craigrobinson/wc_2026_predictor`
- A football-data.org API key — register at <https://www.football-data.org/client/register> (free tier, requires email confirmation)

---

## Step 1 — Provision the Supabase project

1. In the Supabase dashboard, create a new project (region: nearest to Railway region — usually `eu-west-1` if your players are UK).
2. Wait ~2 min for provisioning, then capture from **Project Settings → API**:
   - Project URL → `SUPABASE_URL`
   - `anon` public key → `SUPABASE_ANON_KEY` and `VITE_SUPABASE_ANON_KEY` (same value)
   - `service_role` key → `SUPABASE_SERVICE_KEY` (backend only, never expose)
3. Capture from **Project Settings → Database → Connection string**:
   - Use the **Session pooler** URI (not the direct connection) — Railway cannot reach the direct Supabase host (`db.<ref>.supabase.co:5432`) due to network restrictions. The Session pooler (`aws-0-<region>.pooler.supabase.com:5432`) is publicly accessible.
   - **Important:** rewrite the scheme from `postgresql://` to `postgresql+asyncpg://`, and append `?prepared_statement_cache_size=0` (required because asyncpg's prepared statement cache is incompatible with PgBouncer in session mode).
   - The Session pooler username format is `postgres.<project-ref>`, not just `postgres`.
   - Example: `postgresql+asyncpg://postgres.lesscrmlfijiokureomm:<password>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?prepared_statement_cache_size=0`

> Staging vs prod: create **two separate Supabase projects**, not branches. Service keys are project-scoped; sharing them between envs leaks prod creds into staging.

---

## Step 2 — Generate the JWT + VAPID secrets

JWT secrets (need at least 32 chars each; the two values must differ):

```bash
python -c "import secrets; print('ACCESS=', secrets.token_urlsafe(48)); print('REFRESH=', secrets.token_urlsafe(48))"
```

VAPID keypair (one set per environment — staging and prod must NOT share):

```bash
/Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python - <<'PY'
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

key = ec.generate_private_key(ec.SECP256R1())

pub_bytes = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
print("VAPID_PUBLIC_KEY=" + base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode())

priv_bytes = key.private_numbers().private_value.to_bytes(32, "big")
print("VAPID_PRIVATE_KEY=" + base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode())
PY
```

> **Private key format:** store as a **base64url string** (single line, no PEM headers). Railway strips or corrupts newlines in multi-line env vars, which causes pywebpush to fail with `ASN.1 parsing error: invalid length`. The base64url raw-scalar format avoids this entirely — pywebpush accepts it directly.

Record these in a password manager. You'll paste them into Railway + Vercel in the next steps.

> **Gotcha:** the public key goes into BOTH `VAPID_PUBLIC_KEY` (backend signs push requests) and `VITE_VAPID_PUBLIC_KEY` (frontend subscribes the browser). Same value, two variable names.

---

## Step 3 — Apply migrations to Supabase

This manual migrate is a **first-time bootstrap** only — it gets the schema in
place so the seed in Step 4 can run before the backend service exists. From
Step 5 on, Railway re-runs `alembic upgrade head` on every deploy (Dockerfile
CMD), so you never run this by hand again.

From the repo root, run Alembic against the new Supabase Postgres:

```bash
export DATABASE_URL='postgresql+asyncpg://postgres:<password>@<host>:5432/postgres'
PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api \
  /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/alembic \
  -c /Users/craigrobinson/wc_2026_predictor/apps/api/alembic.ini \
  upgrade head
```

Expect 14 migrations to apply (`001_core_schema` through `014_profiles_not_null_constraints`). Verify with:

```bash
psql "${DATABASE_URL/postgresql+asyncpg/postgres}" -c "\dt"
```

You should see the full schema (profiles, matches, predictions, leaderboard_snapshots, etc.).

> **RLS advisory:** Supabase will flag that 10 tables have Row Level Security disabled. This is intentional — the frontend never queries Postgres directly; all data access goes through the FastAPI backend using the `service_role` key over a direct asyncpg connection. The anon key is unused by the app. RLS is not required here.

---

## Step 4 — Seed tournament data

The seed script is idempotent: groups + teams upserted by code, matches by `match_number`. Re-runnable safely.

```bash
cd /Users/craigrobinson/wc_2026_predictor/apps/api
DATABASE_URL='postgresql+asyncpg://postgres:<password>@<host>:5432/postgres' \
  PYTHONPATH=. .venv/bin/python -m src.seed
```

Expect: 12 groups, 48 teams, 72 group-stage matches loaded. Knockout matches are NOT seeded — they're created automatically after the group stage completes.

`football_data_match_id` columns remain NULL until the sync job populates them — that happens on the first scheduler tick once Railway is up with `FOOTBALL_DATA_API_KEY` set.

---

## Step 5 — Deploy the backend to Railway

The backend deploys **automatically from GitHub**. Railway watches one branch per
service, and on every push it builds the repo-root `Dockerfile`, whose CMD runs
`alembic upgrade head` before uvicorn. There is **no `railway up`** and **no
manual migration step** in normal operation — this section is the one-time wiring.

1. Railway dashboard → **New Project → Deploy from GitHub repo** → pick
   `CraigR973/wc2026-predictor`. Name the service `wc2026-api-{staging,prod}`.
2. **Settings → Source:**
   - **Branch:** `staging` for the staging service, `main` for prod. Railway
     auto-deploys that branch on every push.
   - **Root Directory:** leave at the **repo root** (blank), *not* `apps/api`. The
     build context must include `/migrations`, and the root `railway.toml` pins
     `builder = "dockerfile"` so Railway will not misdetect the monorepo as Node.
   - **Custom Start Command:** leave **empty**. The `Dockerfile` CMD already runs
     `alembic upgrade head && uvicorn …`; a leftover start command silently skips
     the migration step (this exact mistake once let a migration fail to run).

Add **all** of these env vars in the Railway service (Settings → Variables):

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` — the **Session-pooler** URL from Step 1 (with `?prepared_statement_cache_size=0`); Railway cannot reach the direct host |
| `SUPABASE_URL` | from Step 1 |
| `SUPABASE_SERVICE_KEY` | from Step 1 |
| `JWT_ACCESS_SECRET` | from Step 2 |
| `JWT_REFRESH_SECRET` | from Step 2 |
| `VAPID_PUBLIC_KEY` | from Step 2 |
| `VAPID_PRIVATE_KEY` | from Step 2 |
| `VAPID_CONTACT_EMAIL` | your real email — push services may reject placeholder addresses |
| `FOOTBALL_DATA_API_KEY` | from the football-data.org dashboard |
| `FRONTEND_ORIGIN` | leave blank for now — set in Step 7 after Vercel gives you a URL |
| `SENTRY_DSN_BACKEND` | optional (see Step 9) |

`pg_dump` for the daily 03:00 UTC backup is already in the image — the root
`Dockerfile` installs `postgresql-client`. No Nixpacks step needed.

Deploy by pushing the tracked branch (or click **Deploy** for the first build).
Railway builds the Dockerfile, runs `alembic upgrade head` on boot, and the
healthcheck at `/api/v1/health` only goes green **after** the migration completes
— so a green deploy is itself proof the DB migrated.

Once deployed, capture the Railway-generated domain (e.g. `wc2026-api-staging.up.railway.app`). Smoke test:

```bash
curl https://wc2026-api-staging.up.railway.app/api/v1/health
curl https://wc2026-api-staging.up.railway.app/api/v1/health/ready
```

Both must return `200` with `{"status": "ok"}` and `{"status": "ready", "db": "ok"}` respectively. If `/health/ready` returns `db: unreachable`, your `DATABASE_URL` is wrong — most often the asyncpg scheme prefix is missing.

---

## Step 6 — Deploy the frontend to Vercel

```bash
cd /Users/craigrobinson/wc_2026_predictor/apps/web
vercel login
vercel link    # create new project, name it wc2026-{staging,prod}
```

In the Vercel dashboard, confirm:

- **Framework Preset:** Vite (auto-detected)
- **Root Directory:** `apps/web`
- **Build Command:** `pnpm build`
- **Output Directory:** `dist`

Add env vars (Settings → Environment Variables → Production):

| Variable | Value |
|---|---|
| `VITE_API_URL` | the Railway URL from Step 5, e.g. `https://wc2026-api-staging.up.railway.app` |
| `VITE_SUPABASE_URL` | from Step 1 |
| `VITE_SUPABASE_ANON_KEY` | from Step 1 |
| `VITE_VAPID_PUBLIC_KEY` | from Step 2 (same as backend's `VAPID_PUBLIC_KEY`) |
| `VITE_SENTRY_DSN` | optional (see Step 9) |

Deploy:

```bash
vercel --prod
```

Capture the assigned domain (e.g. `wc2026-staging.vercel.app`).

---

## Step 7 — Close the CORS loop

Go back to Railway and set:

```
FRONTEND_ORIGIN=https://wc2026-staging.vercel.app
```

Saving a variable in Railway triggers a redeploy on its own; if it doesn't, hit the dashboard's **Redeploy** button (no `railway up`). Then verify CORS from the frontend domain:

```bash
curl -I -X OPTIONS https://wc2026-api-staging.up.railway.app/api/v1/health \
  -H "Origin: https://wc2026-staging.vercel.app" \
  -H "Access-Control-Request-Method: GET"
```

Look for `access-control-allow-origin: https://wc2026-staging.vercel.app` in the response headers.

---

## Step 8 — Bootstrap the first admin

The join endpoint only creates `player`-role profiles — this is intentional (no env-driven path to admin). Use the operator-only `bootstrap_admin` script.

**Option A (recommended) — create a fresh admin profile in one command:**

```bash
cd /Users/craigrobinson/wc_2026_predictor/apps/api
DATABASE_URL='postgresql+asyncpg://postgres:<password>@<host>:5432/postgres' \
  PYTHONPATH=. .venv/bin/python -m src.bootstrap_admin \
  --display-name "Craig" \
  --timezone "Europe/London"
```

You'll be prompted for the PIN interactively (use `--pin` to pass it inline if you must, but it'll show up in shell history). On success the script prints `created admin '<name>' (id=<uuid>)` and exits 0. Log into the frontend with that name + PIN.

**Option B — promote an existing player you joined via invite:**

If you already issued yourself an invite and joined as a regular `player`, flip your role:

```bash
DATABASE_URL='...' PYTHONPATH=. .venv/bin/python -m src.bootstrap_admin \
  --promote --display-name "Craig"
```

The script refuses with a clear error if the name doesn't exist, is already admin, or the league is at the 15-player cap.

Refresh the frontend — the **Admin** nav link should now appear. From `/admin/invites` you can issue invites for the other players without ever touching the script or SQL again.

---

## Step 9 — (Optional) Wire up Sentry

If you want centralised error tracking:

1. Create two Sentry projects: `wc2026-api` (FastAPI/Python) and `wc2026-web` (React).
2. Set `SENTRY_DSN_BACKEND` in Railway and `VITE_SENTRY_DSN` in Vercel.
3. Trigger a test error from each to confirm events land in Sentry.

PII scrubbing is already enabled in both `apps/api/src/main.py` and `apps/web/src/sentry.ts` — names + PINs are stripped before transmission.

---

## Step 10 — End-to-end smoke test

Sign in as admin, then verify each flow against the deployed staging stack:

- [ ] `/` Dashboard renders with rank `—` and "No upcoming matches" (no results yet)
- [ ] `/schedule` lists all 72 group-stage matches
- [ ] `/groups` shows 12 groups with 4 teams each
- [ ] `/predictions` shows the group tabs and accepts a saved score
- [ ] `/bracket` shows the empty-state "Bracket isn't ready yet"
- [ ] `/settings` → enable push notifications, click **Send test** → notification arrives on the device
- [ ] `/admin/sync` → click **Sync Now** → verify it returns success and updates `last_sync_at` (football-data.org may have no live matches yet — that's fine, `last_sync_action: no_changes` is the expected response pre-tournament)
- [ ] `/admin/invites` → create an invite, copy the link, open in a private window, join as a second player

If any step fails, check **Railway logs** (`railway logs`) and **browser DevTools console** — most prod-only issues are env-var typos that surface here.

---

## Step 11 — Promote to production

Repeat Steps 1–10 with `-prod` names everywhere. **Use a separate Supabase project, separate Railway service, separate Vercel project, and a fresh VAPID keypair** — sharing any of these between staging and prod defeats the point of staging.

Once prod is green, share invite links with the real players.

---

## Common failure modes

| Symptom | Likely cause |
|---|---|
| Frontend loads but every API call returns CORS error | `FRONTEND_ORIGIN` on Railway doesn't match the Vercel domain exactly (must include scheme, no trailing slash) |
| `/health/ready` returns `db: unreachable` with `[Errno 101] Network is unreachable` | Using the Supabase **direct** connection host (`db.<ref>.supabase.co`) — Railway cannot reach it. Switch to the **Session pooler** URL (`aws-0-<region>.pooler.supabase.com:5432`) with `?prepared_statement_cache_size=0` appended. |
| `/health/ready` returns `db: unreachable` with auth error | `DATABASE_URL` is missing the `+asyncpg` scheme suffix, wrong password, or special chars in the password need URL-encoding (`%2C` for `,`, `%21` for `!`, `%26` for `&`). |
| Push subscription returns `InvalidAccessError` | `VITE_VAPID_PUBLIC_KEY` doesn't match the `VAPID_PUBLIC_KEY` Railway is signing with, or one of them is from a different env |
| Service worker never registers | The site is not served over HTTPS — Vercel does this automatically, but a custom domain in pending-verification state can serve HTTP briefly |
| Daily backup at 03:00 UTC fails with `pg_dump: not found` | The root `Dockerfile`'s `apt-get install postgresql-client` line was removed or broke — restore it; that line is what puts `pg_dump` on PATH |
| Auto-sync logs `401 Unauthorized` | `FOOTBALL_DATA_API_KEY` invalid or quota exceeded — free tier is 10 requests/min, 100 requests/day per key |
