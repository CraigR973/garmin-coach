# Ongoing Deploy Runbook

Day-to-day deploy and recovery notes for the live Phase 0b stack.

## Current Posture

Production is live and GitHub-connected:

- Backend: Railway service `api`, auto-deployed from `CraigR973/garmin-coach` branch `main`
- Frontend: Vercel project `garmin-coach`, auto-deployed from `CraigR973/garmin-coach` production branch `main`
- Frontend previews: Vercel creates PR/branch preview deployments
- Database: Supabase project `pzqmswvozjnkxbqqowuj`, schema `coach`

Manual CLI deploys are break-glass only. See Decision #39.

## Backend Deploy

For backend code or migrations, push/merge to `main`. Railway builds the repo-root Dockerfile and deploys service `api`.

Break-glass manual deploy:

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

For frontend code/config changes, push/merge to `main`. Vercel builds from the repo-root project with root `vercel.json`.

Break-glass manual deploy:

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

## GitHub Auto-Deploy Verification

Railway:

```bash
railway status
railway service source connect --repo CraigR973/garmin-coach --branch main --service api --json
```

The second command is idempotent; it should report repo `CraigR973/garmin-coach`, branch `main`, and `disconnected: false`.

Vercel:

```bash
~/.local/bin/vercel git connect --cwd /Users/craigrobinson/garmin-coach
~/.local/bin/vercel api /v9/projects/prj_fHufaAaQq2jGuDX8nvI6LwUQOIdL --cwd /Users/craigrobinson/garmin-coach
```

Expected Vercel project fields:

- `link.type`: `github`
- `link.org`: `CraigR973`
- `link.repo`: `garmin-coach`
- `link.productionBranch`: `main`
- `gitProviderOptions.createDeployments`: `enabled`
- `nodeVersion`: `20.x`

With the current single-backend posture, Vercel preview deploys proxy to the production Railway API and production database. Preview is fine for visual review; avoid mutating production data from previews.
