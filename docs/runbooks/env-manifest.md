# Environment Variable Manifest

Every runtime variable used by the backend (Railway) or frontend (Vercel), and
which surface owns it per environment. Variables marked ⚠️ will break production
**silently** if misconfigured — a mismatch passes all CI checks and only fails in
a real browser or under prod load.

---

## Backend variables (Railway)

Set in Railway per-environment secrets (Production / Staging).

| Variable | Production | Staging | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ required | ✅ required | ⚠️ Wrong value → boot failure or wrong DB writes |
| `JWT_ACCESS_SECRET` | ✅ required | ✅ required | Must not be a placeholder in prod (boot validator rejects it) |
| `JWT_REFRESH_SECRET` | ✅ required | ✅ required | Same |
| `SUPABASE_URL` | ✅ required | ✅ required | |
| `SUPABASE_ANON_KEY` | ✅ required | ✅ required | |
| `SUPABASE_SERVICE_KEY` | ✅ required | ✅ required | Boot validator rejects empty value in prod |
| `FOOTBALL_DATA_API_KEY` | ✅ required | ✅ required | Boot validator rejects empty value in prod |
| `VAPID_PUBLIC_KEY` | ✅ required | ✅ required | |
| `VAPID_PRIVATE_KEY` | ✅ required | ✅ required | Boot validator rejects empty value in prod |
| `VAPID_CONTACT_EMAIL` | optional | optional | Defaults to `admin@example.com` |
| `FRONTEND_ORIGIN` | ✅ required | ✅ required | ⚠️ Must be the exact Vercel origin (`https://wc2026-prod.vercel.app` / `https://wc2026-staging.vercel.app`); a localhost value is rejected by the boot validator in prod; a wrong value breaks CORS silently |
| `ENVIRONMENT` | `production` | `staging` | ⚠️ Controls the boot validator and security headers; wrong value bypasses prod checks |
| `SCHEDULER_ENABLED` | `true` (default) | `false` | ⚠️ Must be `false` on staging — leaving it `true` causes double result-fetches and real push notifications alongside prod |
| `RESEND_API_KEY` | ✅ required | optional | |
| `EMAIL_FROM` | optional | optional | Defaults to `WC2026 Predictor <noreply@example.com>` |
| `SENTRY_DSN_BACKEND` | optional | optional | Leave empty to disable Sentry on that env |
| `LOG_LEVEL` | optional | optional | Defaults to `INFO` |
| `RAILWAY_GIT_COMMIT_SHA` | injected by Railway | injected by Railway | Never set manually; Railway injects the deploy commit SHA; exposed via `GET /api/v1/health` |
| `BACKUP_DIR` | optional | optional | Defaults to `/tmp/wc2026_backups` |

---

## Frontend variables (Vercel build-time)

Set on the Vercel project per-environment (Production / Preview / Development).
All `VITE_*` vars are baked into the JS bundle at build time — changing them
requires a redeploy.

| Variable | `wc2026-prod` | `wc2026-staging` | Notes |
|---|---|---|---|
| `VITE_API_URL` | ✅ required | ✅ required | ⚠️ **Critical.** Missing → R5.1 guard throws at module load → blank page. Must be the HTTPS backend URL, never localhost. Caught by CI `prod-bundle-check` job. |
| `VITE_SUPABASE_URL` | ✅ required | ✅ required | |
| `VITE_SUPABASE_ANON_KEY` | ✅ required | ✅ required | |
| `VITE_VAPID_PUBLIC_KEY` | ✅ required | ✅ required | Must match backend `VAPID_PUBLIC_KEY` exactly |
| `VITE_SENTRY_DSN` | optional | optional | Leave empty to disable Sentry on that env |

---

## Local development (`.env` file)

See [`.env.example`](../../.env.example) for the full list with inline comments.
Local dev uses `ENVIRONMENT=development` (default), which bypasses the prod boot
validator — localhost values for `DATABASE_URL`, `FRONTEND_ORIGIN`, etc. are fine.

---

## Mismatch scenarios that break prod silently

| Misconfiguration | Symptom | Where caught |
|---|---|---|
| `VITE_API_URL` missing from Vercel prod build | Blank page on load | CI `prod-bundle-check` guard test |
| `FRONTEND_ORIGIN` pointing at localhost or wrong domain | All API calls fail with CORS error | Boot validator rejects localhost; wrong HTTPS domain fails at runtime |
| `DATABASE_URL` wrong | Backend connects to wrong DB; predictions/scores silently written elsewhere | Boot validator rejects empty; wrong value only fails at query time |
| `SCHEDULER_ENABLED=true` on staging | Football-data.org quota consumed twice; real push notifications sent to players from staging | Set `false` on staging Railway env (Operator action OP3) |
| `ENVIRONMENT` not set to `production` on Railway prod | Boot validator skipped; placeholder secrets accepted; HSTS header omitted | Manual check / OP2 audit |
