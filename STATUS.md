# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Phase:** 0 COMPLETE — skeleton is live; Phase 0b deploy runbooks added.

**Live endpoints:**
- Frontend: https://garmin-coach-one.vercel.app (Vercel, deploy via `~/.local/bin/vercel --prod` from repo root)
- Backend: https://api-production-e2bc7.up.railway.app/api/v1/health → `{"status":"ok"}`
- DB: Supabase project `pzqmswvozjnkxbqqowuj` (eu-north-1), `coach` schema, migration 001 applied

**Hosting identifiers (non-secret):**
- GitHub repo: https://github.com/CraigR973/garmin-coach (private)
- Supabase project ref: `pzqmswvozjnkxbqqowuj` (shared with movie app via `coach` schema isolation)
- Railway project: `d43542f3-5165-420d-a14d-298832d23904`, service `api`
- Vercel project: `garmin-coach-one.vercel.app`
- DB connection: Supabase session-mode pooler `aws-1-eu-north-1.pooler.supabase.com:5432`

**Next:** Decide whether to connect Railway + Vercel to GitHub auto-deploy. Recommendation is `main` → production on both, Vercel PR/branch previews only, Railway main-only. Then Phase 1 — data model + sync jobs:
1. Seed Mark's profile (admin) and optionally a 2nd user directly in DB
2. Define Garmin/Hive/weather data model from `~/garmin-spike/out/` JSON shapes
3. Three sync jobs: Garmin (garth), Hive (pyhiveapi), Open-Meteo
4. 84-night Garmin backfill
5. Morning analysis prompt + Claude call

## Gotchas
- Python is **3.12** (`~/.local/bin/python3.12`); api venv at `apps/api/.venv`.
- Node.js: use `~/.nvm/versions/node/v20.20.2/bin/node` + pnpm (system node v14).
- `score-input.tsx`, `offlineQueue.ts`, `sw.ts` still have "predictions" refs — offline-queue infra, rename in Phase 1.
- `apps/api/src/auth.py` has dead `create_email_verify_token` / `decode_email_verify_token` — remove in a future pass.
- Railway is **NOT** connected to GitHub auto-deploy. To deploy: `railway up --service api` (builds from local source), or connect in Railway dashboard Settings > Source Repo.
- Treat Vercel as manual unless/until the dashboard shows a Git provider link. Deploy frontend with `~/.local/bin/vercel --prod` from repo root.
- Production web API wiring is intentionally same-origin: `VITE_API_URL=""`, calls go to `/api/*`, and root `vercel.json` rewrites to Railway. Do not set it to the Railway URL unless deliberately switching to cross-origin.
- Supabase pooler: **session mode (port 5432)** only — asyncpg named prepared statements conflict in transaction mode (port 6543).
- Admin profiles must be seeded directly in DB (no signup endpoint by design — Decision #21).

## Log
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
