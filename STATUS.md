# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Phase:** 1 Batch 3 shipped — Hive + weather syncs live.

**Live endpoints:**
- Frontend: https://garmin-coach-one.vercel.app (Vercel, auto-deploy from GitHub `main`; `~/.local/bin/vercel --prod` is break-glass)
- Backend: https://api-production-e2bc7.up.railway.app/api/v1/health → `{"status":"ok"}` plus current deployed SHA
- DB: Supabase project `pzqmswvozjnkxbqqowuj` (eu-north-1), `coach` schema, migrations 001-003 applied

**Hosting identifiers (non-secret):**
- GitHub repo: https://github.com/CraigR973/garmin-coach (private)
- Supabase project ref: `pzqmswvozjnkxbqqowuj` (shared with movie app via `coach` schema isolation)
- Railway project: `d43542f3-5165-420d-a14d-298832d23904`, service `api`
- Vercel project: `garmin-coach` (`garmin-coach-one.vercel.app`)
- DB connection: Supabase session-mode pooler `aws-1-eu-north-1.pooler.supabase.com:5432`

**Next:** Run Phase 1 Batch 4 via `/batch-start 4`.

## Gotchas
- Python is **3.12** (`~/.local/bin/python3.12`); api venv at `apps/api/.venv`.
- Node.js: use `~/.nvm/versions/node/v20.20.2/bin/node` + pnpm (system node v14).
- `score-input.tsx`, `offlineQueue.ts`, `sw.ts` still have "predictions" refs — offline-queue infra, rename in Phase 1.
- `apps/api/src/auth.py` has dead `create_email_verify_token` / `decode_email_verify_token` — remove in a future pass.
- Railway service `api` is connected to GitHub `CraigR973/garmin-coach`, branch `main`. Push to `main` deploys production backend; `railway up --service api` is break-glass.
- Vercel project `garmin-coach` is connected to GitHub `CraigR973/garmin-coach`, production branch `main`, Node `20.x`. Push to `main` deploys production frontend; PR/branch pushes create previews.
- Production web API wiring is intentionally same-origin: `VITE_API_URL=""`, calls go to `/api/*`, and root `vercel.json` rewrites to Railway. Do not set it to the Railway URL unless deliberately switching to cross-origin.
- Vercel previews currently proxy `/api/*` to the production Railway API/DB, so use previews for visual review and avoid mutating real data there.
- Supabase pooler: **session mode (port 5432)** only — asyncpg named prepared statements conflict in transaction mode (port 6543).
- Admin profiles must be seeded directly in DB (no signup endpoint by design — Decision #21).
- Mark seed helper is
  `MARK_PIN=1234 PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m src.seeds`
  after migration `003` is applied; replace `1234` with the real PIN and never commit it.
- Garmin sync uses `GARMIN_EMAIL` / `GARMIN_PASSWORD` from the environment plus
  `GARMIN_TOKENSTORE` for garth's persisted token cache; the app does not store
  Garmin secrets in Postgres.

## Log
- **2026-06-20** — Phase 1 Batch 3 closed out: merged PR #1
  `feat/batch-3-hive-weather-syncs` to `main`, GitHub CI passed on merge commit
  `7f06d1f`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production returned `HTTP 200`, and the same-origin
  `/api/v1/health` rewrite returned the deployed SHA. Batch 3 marked shipped;
  next up is Batch 4 84-night backfill + baselines.
- **2026-06-20** — Phase 1 Batch 3 implementation ready on
  `feat/batch-3-hive-weather-syncs`: added Hive `pyhiveapi` re-login wrapper,
  real-fixture Hive temperature parsing/upserts, Open-Meteo Kilmarnock daily +
  overnight weather parsing/upserts, overnight wind columns, and scheduler jobs
  for 15-minute Hive polling plus 06:30 Europe/London weather sync. Verified
  backend pytest/ruff/mypy and shared package test/typecheck locally; DB-backed
  idempotency tests skipped without `DATABASE_URL`.
- **2026-06-20** — Phase 1 Batch 2 closed out: merged
  `feat/batch-2-garmin-sync-foundation` to `main`, GitHub CI passed on merge
  commit `8ab4e27`, Railway deployed the backend and `/api/v1/health` reported
  that SHA, and Vercel production returned `HTTP 200`. Batch 2 marked shipped;
  next up is Batch 3 Hive + weather syncs.
- **2026-06-20** — Phase 1 Batch 2 implementation ready on
  `feat/batch-2-garmin-sync-foundation`: added Garmin Connect client/login
  wrapper with token-cache strategy, Garmin fixture parsers, daily/sleep/activity
  sync upserts, time-series channel extraction for power/HR/cadence/respiration/
  Performance Condition/Stamina, and no-secret failure tests. Verified backend
  pytest/ruff/mypy locally; one Postgres idempotency test skipped without
  `DATABASE_URL`.
- **2026-06-20** — Phase 1 Batch 1 closed out: merged
  `feat/batch-1-data-model` to `main`, GitHub CI passed on merge commit
  `b2733ca`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production was Ready and the web URL loaded. Batch 1 marked
  shipped; next up is Batch 2 Garmin sync foundation.
- **2026-06-20** — Phase 1 Batch 1 implementation ready on
  `feat/batch-1-data-model`: added `002` v1 coaching schema, SQLAlchemy domain
  models, Mark profile seed helper, shared Zod/TS schemas, data-shape audit, and
  tests. Verified backend pytest/ruff/mypy plus shared package test/typecheck.
- **2026-06-20** — Phase 1 prep complete: added `docs/phase-batches.md`,
  tool-agnostic batch procedures, Claude wrappers, Codex prompt-source wrappers
  with the user-level `~/.codex/prompts` caveat, and fixed stop hooks to point at
  `garmin-coach` + `/closeout`.
- **2026-06-20** — Auto-deploy verified end-to-end on `main` before this handoff
  log commit: GitHub CI green on `05f3c71`; Railway auto-deployed it and
  `/api/v1/health` returned that SHA; Vercel production deploy was Ready.
  Incidental CI cleanup: formatted two API files and added typed `RESEND_API_KEY`
  / `EMAIL_FROM` settings defaults used by the email service.
- **2026-06-20** — Auto-deploy enabled after Craig approved the switch: Railway service
  `api` connected to GitHub `CraigR973/garmin-coach` branch `main`; Vercel project
  `garmin-coach` connected to the same repo with production branch `main`, Git
  deployments enabled, and Node pinned to `20.x`. Recorded DECISIONS #39.
- **2026-06-20** — Phase 0b deploy review follow-up: added fresh/ongoing deploy runbooks,
  fixed stale `.env.example` Supabase pooler guidance, ignored Supabase CLI scratch files,
  pinned Node to 20.x for Vercel, made production `VITE_API_URL=""` same-origin wiring
  explicit in code/config, and ticked Phase 0b complete in ARCHITECTURE. Auto-deploy remains
  a pending explicit decision; no Decision #39 recorded yet.
- **2026-06-20** — Phase 0b complete: GitHub repo created, Supabase `coach` schema live,
  Railway backend healthy, Vercel frontend live. Main connectivity blocker was Railway's
  IPv6-only networking vs Supabase's IPv4-only direct host; resolved via Supabase session-mode
  pooler (`aws-1-eu-north-1.pooler.supabase.com:5432`). See DECISIONS #34-38.
- **2026-06-19** — Zwift delivery validated end-to-end (app→intervals.icu→Zwift; power/timing exact, cadence nuance noted). Folded Zwift/intervals.icu relay, executable-coaching, Ronnestad 30/15 + softened lead-time into ARCHITECTURE.md §2/§6 + DECISIONS #25-33. (No code change — spec only.)
- **2026-06-19** — Phase 0a complete: stripped football domain from backend and
  frontend. 148 backend files changed (1041 ins / 48814 del); 161 frontend files
  changed (748 ins / 27045 del). Backend: 42 tests pass, ruff clean.
  Frontend: TypeScript passes, vite build succeeds.
- **2026-06-19** — Phase 0 started: seeded repo, wrote project docs, set up
  cross-tool structure, pruned WC cruft. Data sources validated via spikes.
