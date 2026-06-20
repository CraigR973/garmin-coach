# Ongoing Deploy Runbook

Day-to-day deploy and recovery notes for the live Phase 0b stack.

## Current Posture

Production is live, but deploys are still manual:

- Backend: Railway service `api`, deployed with `railway up --service api`
- Frontend: Vercel project `garmin-coach-one`, deployed with `~/.local/bin/vercel --prod`
- Database: Supabase project `pzqmswvozjnkxbqqowuj`, schema `coach`

Railway is not connected to GitHub auto-deploy yet. Vercel should be treated as manual unless the dashboard shows a Git provider link.

Recommended next operational decision: connect both Railway and Vercel to GitHub, with production deploys from `main` and Vercel preview deploys for PRs/branches. If that is chosen, append a new `DECISIONS.md` entry superseding Decision #37.

## Backend Deploy

For backend code, migrations, or backend env changes:

```bash
railway up --service api
```

Then verify:

```bash
curl -fsS https://api-production-e2bc7.up.railway.app/api/v1/health
```

Expected:

```json
{"status":"ok"}
```

Notes:

- Source changes need `railway up`; `railway redeploy` may reuse the existing image.
- The Railway healthcheck is `/api/v1/health` with a 300 second timeout.
- The Dockerfile command runs `alembic upgrade head` before uvicorn starts.
- If startup/migrations fail, the new container never passes healthcheck and the previous deployment should keep serving.

## Frontend Deploy

For frontend code/config changes:

```bash
~/.local/bin/vercel --prod
```

The app uses same-origin API calls in production:

- `VITE_API_URL=""`
- frontend calls `/api/*`
- repo-root `vercel.json` rewrites `/api/*` to Railway

Do not set `VITE_API_URL` to the Railway URL unless you deliberately want direct cross-origin calls and have verified backend CORS/auth behavior.

## Migrations

Before deploying a migration:

```bash
PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api \
  /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m pytest
```

CI also runs an Alembic migration check:

1. `alembic upgrade head`
2. `alembic downgrade base`

Production migrations run automatically during Railway container startup. A migration that fails before uvicorn starts should fail the deployment healthcheck instead of cutting over.

Manual recovery options:

- Fix the migration and run `railway up --service api` again.
- If a migration partially succeeded and the app cannot start, inspect Supabase state before writing a corrective migration.
- Do not point Railway at transaction-mode pooler port `6543`; use session mode `5432`.

## Rollback

Railway:

- Prefer dashboard rollback to the previous successful deployment if a source deploy is bad.
- Use logs to confirm whether the failure is in Alembic startup or application boot.

Vercel:

- Promote a previous successful deployment from the Vercel dashboard if the frontend is bad.
- Re-run `~/.local/bin/vercel --prod` after fixing source/config.

Supabase:

- Treat DB rollback as a migration exercise, not a dashboard click.
- Use Alembic downgrade only after checking whether live data would be lost.

## Optional GitHub Auto-Deploy Checklist

Only do this after Craig explicitly chooses auto-deploy.

Railway:

1. Open the Railway project.
2. Go to service `api` > Settings > Source Repo.
3. Connect `CraigR973/garmin-coach`.
4. Set branch to `main`.
5. Keep Root Directory as repo root.
6. Trigger one deploy and verify `/api/v1/health`.

Vercel:

1. Open the Vercel project settings.
2. Connect Git provider repo `CraigR973/garmin-coach`.
3. Keep project root at repo root.
4. Confirm Node 20 is selected/respected.
5. Confirm production branch is `main`.
6. Confirm PR/branch preview deploys are enabled.

With the current single-backend posture, Vercel preview deploys proxy to the production Railway API and production database. Preview is fine for visual review; avoid mutating production data from previews.
