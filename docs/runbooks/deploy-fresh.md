# Fresh Deploy Runbook

Provision Garmin Coach from zero without rediscovering the Phase 0b traps.

## Prerequisites

Use repo-root commands with absolute paths; do not rely on system Node or Python.

- Node: `~/.nvm/versions/node/v20.20.2/bin/node`
- pnpm: `pnpm@9.15.0`
- Python: `~/.local/bin/python3.12`
- CLIs: `gh`, `supabase`, `railway`, `vercel`

Install missing CLIs before starting the deploy loop:

```bash
brew install gh supabase/tap/supabase railway
pnpm add -g vercel
```

If `vercel` resolves through system Node v14, run it through the Node 20 environment or install it under the Node 20 prefix.

## Supabase

The live project is shared with the movie app and isolated by schema:

- Project ref: `pzqmswvozjnkxbqqowuj`
- Region: `eu-north-1`
- Garmin Coach schema: `coach`

For a new provision, prefer the same pattern unless the free-tier/project constraints have changed.

1. Create or choose the Supabase project.
2. Enable the connection pooler if it is not already enabled.
3. Use the session-mode pooler URL for Railway and local deployed-like tests:

```text
postgresql+asyncpg://postgres.<project-ref>:<password>@aws-1-eu-north-1.pooler.supabase.com:5432/postgres
```

Do not use:

- The direct `db.<ref>.supabase.co:5432` host from Railway. Railway egress is IPv6-only and Supabase direct hosts can be IPv4-only.
- Transaction-mode pooler port `6543`. `asyncpg` named prepared statements can collide through transaction pooling.

The app/Alembic config targets the `coach` schema via `SET search_path TO coach, public` and stores Alembic state in that schema.

## Railway

Railway serves the FastAPI backend.

Current live service:

- Project: `d43542f3-5165-420d-a14d-298832d23904`
- Service: `api`
- Healthcheck: `/api/v1/health`
- Live health URL: `https://api-production-e2bc7.up.railway.app/api/v1/health`

Required setup:

1. Create a Railway project/service for the API.
2. Set service Root Directory to the repo root.
3. Use the repo-root `railway.toml`; it pins the Dockerfile builder.
4. Set environment variables:
   - `DATABASE_URL`: Supabase session-mode pooler URL on port `5432`
   - `JWT_ACCESS_SECRET`
   - `JWT_REFRESH_SECRET`
   - `FRONTEND_ORIGIN`
   - `VAPID_PUBLIC_KEY`
   - `VAPID_PRIVATE_KEY`
   - `VAPID_CONTACT_EMAIL`
   - `SENTRY_DSN_BACKEND` if enabled
   - Data-source/API secrets as their integrations ship
5. Deploy and verify:

```bash
railway up --service api
```

The Dockerfile starts with `alembic upgrade head`, then runs uvicorn. If migrations fail, the container exits and the healthcheck never cuts over to that deployment.

## Vercel

Vercel serves the Vite frontend and proxies same-origin API requests to Railway.

Current live project:

- URL: `https://garmin-coach-one.vercel.app`
- Config: repo-root `vercel.json`
- Node: pinned through root `package.json` `engines.node = "20.x"`

Required setup:

1. Import the GitHub repo into Vercel, or use the existing project.
2. Keep the project root at the repository root so Vercel reads the root `vercel.json`.
3. Keep install/build commands from `vercel.json`:
   - `pnpm install --frozen-lockfile`
   - `pnpm --dir apps/web build`
4. Set frontend env:
   - `VITE_API_URL=""`
   - `VITE_VAPID_PUBLIC_KEY`
   - `VITE_SENTRY_DSN` if enabled
5. Deploy:

```bash
~/.local/bin/vercel --prod
```

`VITE_API_URL=""` is intentional. It makes frontend calls relative (`/api/*`), then `vercel.json` rewrites them to the Railway API. Setting it to the Railway URL switches the app to direct cross-origin calls and makes backend CORS part of the auth path.

## Smoke Test

1. Open `https://garmin-coach-one.vercel.app`.
2. Confirm the login page loads without console errors.
3. Confirm backend health:

```bash
curl -fsS https://api-production-e2bc7.up.railway.app/api/v1/health
```

Expected:

```json
{"status":"ok"}
```

4. If a seeded user exists, log in and confirm the dashboard loads.

## First Checks When It Fails

- `Network is unreachable` from Railway to Supabase: the direct DB host was used. Switch to the session-mode pooler.
- `DuplicatePreparedStatementError`: transaction-mode pooler was used. Switch to session mode, port `5432`.
- Vercel cannot resolve `workspace:*`: Vercel is not reading the repo-root `vercel.json`, or install is not using pnpm.
- `railway redeploy` repeats an old error: it can reuse the old image. Use `railway up --service api` when source changed.
