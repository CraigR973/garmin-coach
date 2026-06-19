# Runbook: Ongoing Deploys

Deploy patterns for day-to-day work after the initial setup in
[`deploy.md`](deploy.md). Covers the normal change → staging → prod flow,
hotfixes, and rollback.

---

## The setup, in one diagram

```
feat/ fix/ chore/  ──►  /ship-staging  ──►  staging branch
                                                  │
         ┌────────────────────────────────────────┴───────────────────────────────┐
         ▼  CI gate (deploy-staging job)                    Railway GitHub integration
   Vercel deploy                                        Railway auto-deploy + migrate
   wc2026-staging.vercel.app                            (alembic upgrade head on boot;
   (frontend)                                            healthcheck gates the cutover)
                                                         staging API + staging DB
         │
         ▼  soak on iPhone, then:  /ship-prod   (refuses unless the staging-HEAD CI run is green)
                                                  │
                                             main branch
                                                  │
         ┌────────────────────────────────────────┴───────────────────────────────┐
         ▼  Vercel GitHub integration                       Railway GitHub integration
   Vercel auto-deploy                                   Railway auto-deploy + migrate
   wc2026-prod.vercel.app                                    (alembic upgrade head on boot)
   (frontend)                                            prod API + prod DB
```

Frontend (Vercel) and backend (Railway) deploy on **independent planes**: Vercel
on staging is gated behind GitHub Actions CI (the `deploy-staging` job), Railway
deploys straight off its own GitHub integration on push. Railway's own gate is the
boot migration + healthcheck — if `alembic upgrade head` or the app fails to come
up healthy, the container exits and Railway keeps the **last healthy deployment**
serving, so a bad migration never half-applies to a live DB.

| What | Where it deploys | How it deploys |
|---|---|---|
| Push to `main` | `wc2026-prod.vercel.app` (frontend) | Vercel GitHub integration auto-deploys |
| Push to `main` | `wc2026-api-production-a0f4.up.railway.app` (backend) | Railway GitHub integration auto-deploys; root `Dockerfile` CMD runs `alembic upgrade head` then uvicorn |
| Push to `staging` | `wc2026-staging.vercel.app` (frontend) | GitHub Actions `deploy-staging` job in `ci.yml` runs after every other job passes, then `vercel deploy --prod` (remote build, not `--prebuilt` — see CI comment) |
| Push to `staging` | `wc2026-predictor-staging.up.railway.app` (backend) | Railway GitHub integration auto-deploys; same `Dockerfile` migrate-on-boot |
| Push to any other branch | nothing | Both Vercel projects skip the build (ignore-build-step); Railway only tracks `main`/`staging` |
| Local CLI `vercel deploy` | one-off preview URL on whichever project's linked | rare — only when staging is currently in use by someone else |

---

## Normal change flow

1. **Branch off `main`**:
   ```bash
   git checkout main && git pull --ff-only origin main
   git checkout -b feat/whatever  # or fix/, chore/
   ```
2. **Develop, commit, push**. CI runs but no deploy.
3. **Open a PR into `main`** (target = `main`, not `staging`). PR previews on Vercel are off — verify on staging instead.
4. **Merge into `staging`** (fast-forward where possible):
   ```bash
   git checkout staging && git pull --ff-only origin staging
   git merge --no-ff feat/whatever -m "merge: feat/whatever -> staging"
   git push origin staging
   ```
   GitHub Actions runs the full CI suite. On success, deploys to
   `https://wc2026-staging.vercel.app`. **Test on iPhone here.**
5. **When happy, merge `staging` → `main`** (or merge the original PR):
   ```bash
   git checkout main && git pull --ff-only origin main
   git merge --ff-only staging  # or non-ff if there are merge commits
   git push origin main
   ```
   Vercel auto-deploys to `https://wc2026-prod.vercel.app`. **Live in ~90 s.**

> [!NOTE]
> Tests + typecheck + lint + alembic-migration-check + Playwright smoke
> are a **hard gate** on the staging branch. The `deploy-staging` job in
> `.github/workflows/ci.yml` won't fire unless every other job in the
> same run succeeded.

---

## Hotfix flow (production is broken)

The fastest fix is to roll back, not roll forward.

### Frontend rollback (Vercel, ~30 s)

In the Vercel dashboard for `wc2026-prod`:
1. Go to **Deployments** tab.
2. Find the last known-good production deployment (look for the green
   ✓ + "Production" badge before the bad one).
3. Hover the row → **⋯** menu → **Promote to Production**.
4. Confirm. The custom domain (`wc2026-prod.vercel.app` + any alias) repoints
   in seconds.

A pure frontend regression only needs this step.

### Backend rollback (Railway)

The backend deploys from the root `Dockerfile`, so a rollback re-runs a
*previous* image — but mind the migration it carries.

1. Railway dashboard → `wc2026-api-prod` service → **Deployments**.
2. Find the last healthy deployment before the bad one → **⋯** → **Redeploy**.
   Railway rebuilds that commit; its `alembic upgrade head` is a no-op when the
   schema is already at or ahead of that revision.
3. **A forward-only migration does not undo itself by redeploying an older
   image** — the old image's `alembic upgrade head` will not *downgrade* the DB.
   If the bad release migrated the schema and you must reverse it, run the
   explicit `alembic downgrade` (see `restore.md`), and only if that migration
   was written reversibly. This is the whole reason we use expand/contract: an
   additive migration needs no rollback, so the older image runs cleanly against
   the newer schema and you can roll the API back independently of the DB.

### Roll forward instead (if rollback won't help)

1. Branch off `main` (which is the broken state):
   ```bash
   git checkout main && git pull origin main
   git checkout -b fix/$(date +%Y%m%d)-something
   ```
2. Fix, commit, push.
3. Open a PR → `main`. **Skip the staging merge** for time-critical hotfixes.
4. Merge to `main`. Vercel auto-deploys in ~90 s.

> [!WARNING]
> The "skip staging" route bypasses iPhone-touch validation on the staging
> URL. Only use during an active outage or a kickoff-time fire. For
> anything non-urgent, do the normal `staging → main` two-step.

---

## Schema changes (backend migration + frontend)

A migration and the frontend that depends on it ship in the **same merge** —
no manual ordering, no separate `railway up`. The model sequences it for you:

1. Merge to `staging` via `/ship-staging`. Railway redeploys the staging backend
   and runs `alembic upgrade head` against the **staging DB** on boot (root
   `Dockerfile` CMD); Vercel deploys the staging frontend. If the migration
   fails, the staging container never goes healthy and the previous one keeps
   serving — you catch it on staging, not in prod.
2. Soak on the staging iPhone. The migration has now proven itself against a
   real (staging) database.
3. Promote with `/ship-prod`. It refuses unless the staging-HEAD CI run is green,
   then merges `staging → main`. Railway runs the **same** migration against the
   **prod DB** on boot. Because it already succeeded on staging, this is the
   gated-but-automatic step — no hand-run migration against prod, ever.
4. **Use expand/contract during the live tournament window (Jun 11 – Jul 19,
   2026).** Keep new columns nullable, add before removing, backfill in a
   follow-up — so old app code keeps working against the new schema during the
   brief window where both run. A migration that drops or renames a column the
   running app still reads will break in-flight prediction submits.

---

## Kickoff-time freeze

During the **30 minutes before and 30 minutes after** any scheduled match
kickoff, don't push to `main`. Players are submitting predictions and any
deploy briefly interrupts in-flight requests.

- Find the next kickoff: `Schedule` page on the live site, or query
  `/api/v1/matches/upcoming?n=1`.
- If a hotfix is truly required during this window, ship it but warn the
  player group on whatever channel you use.

---

## Operational concerns

### Where to look when something's off

- **Vercel deployments**:
  [vercel.com/craigr973s-projects/wc2026-prod/deployments](https://vercel.com/craigr973s-projects/wc2026-prod/deployments)
  [vercel.com/craigr973s-projects/wc2026-staging/deployments](https://vercel.com/craigr973s-projects/wc2026-staging/deployments)
- **GitHub Actions runs**:
  [github.com/CraigR973/wc2026-predictor/actions](https://github.com/CraigR973/wc2026-predictor/actions)
- **Railway backend logs**: `railway logs --service wc2026-api`
- **Sentry frontend + backend errors**: see project links in
  `~/.claude/projects/-Users-craigrobinson-wc-2026-predictor/memory/`
- **Supabase tables**: dashboard or use the Supabase MCP.

### Single-replica assumption

The backend is designed for **exactly one Railway replica**. APScheduler runs
in-process and has no leader election — scaling to 2+ replicas would double-fire
every scheduled job (result fetches, push notifications, score recalculations).
The `alembic upgrade head` on boot also has no distributed lock, so two replicas
starting simultaneously would race on the same migration. Do not increase the
replica count without first moving the scheduler to a separate worker process and
adding a migration lock (e.g. a Postgres advisory lock on `env.py`).

### Required secrets

- `VERCEL_TOKEN` on the GitHub repo (used by `deploy-staging` job in CI).
  Rotate annually via [vercel.com/account/tokens](https://vercel.com/account/tokens).
- `GITHUB_TOKEN` available in `.env` locally (for ad-hoc CI status
  polling and the gh-less PR creation flow).

### What auto-deploy will NOT catch

- A frontend that builds but throws at module load (R5 hard-assert
  catches `VITE_API_URL` missing; other env vars don't have asserts).
- A backend migration that runs but corrupts data (no automated
  rollback — see `restore.md`).
- A 4xx/5xx surge on the API (set up uptime monitoring before launch).
- A PWA service worker that updates but the cached old assets stay on a
  user's home-screen icon (the SW now has `skipWaiting + clientsClaim`,
  so this is mostly resolved, but iOS still caches the icon itself
  separately — icon changes need a reinstall).

---

## Local manual deploy (escape hatch)

Only use when the GitHub Action pipeline is broken and you need to push
something out right now.

```bash
cd apps/web

# Deploy to staging (overwrites wc2026-staging.vercel.app)
VERCEL_PROJECT_ID=prj_hVMpuWm33XjuNrVUWrCti27ZfIX7 \
VERCEL_ORG_ID=team_MVQMOaFtYHlwO5QVzSOZQ0Ud \
vercel deploy --prod --yes

# Deploy to prod (overwrites wc2026-prod.vercel.app — be careful)
VERCEL_PROJECT_ID=prj_xSA1k6vKHfk0KLRjGNPUTluZD8UT \
VERCEL_ORG_ID=team_MVQMOaFtYHlwO5QVzSOZQ0Ud \
vercel deploy --prod --yes
```

Requires `vercel login` to have been run on the laptop. Skips all CI
checks — use sparingly.
