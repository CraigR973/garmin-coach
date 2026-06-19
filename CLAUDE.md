# Garmin Coach — CLAUDE.md

Private AI fitness & sleep coach for Craig's dad. Pulls Garmin/Hive/weather data,
holds his profile + training plan + rules as persistent state, and generates a
daily morning verdict + post-workout analysis with Claude.

**Read `ARCHITECTURE.md` first** — it's the authoritative spec (data sources,
knowledge base, analysis engine, data model, roadmap, Phase 0 status).

## Origin
Forked from the WC2026 predictor to inherit its infra (auth, APScheduler,
web-push, PWA, shadcn, CI, Docker, Railway/Vercel). The football domain is being
stripped. A reusable starter template will be distilled from the two apps *later*
— do not extract it prematurely.

## Stack
FastAPI + async SQLAlchemy + asyncpg + Postgres (Supabase) + Alembic + APScheduler
/ React 18 + Vite + Tailwind + shadcn/ui + recharts. Auth: name + PIN + JWT.
1–2 private users, no public sign-up.

## Bash discipline
- **Never `cd`** (sandbox blocks it; a blocked `cd` shows as a misleading ENOSPC). Use absolute paths.
- Python is **3.12**: `~/.local/bin/python3.12`. System `python3` is 3.7 — too old (garth/pyhiveapi need ≥3.10).
- Validated data-source spikes (throwaway, NOT in this repo): `~/garmin-spike/spike.py` (Garmin), `~/garmin-spike/hive_spike.py` (Hive), venv at `~/garmin-spike/.venv`. **Real sample JSON in `~/garmin-spike/out/` + `out_hive/` — the canonical reference for field shapes when building the data model.**

## Data sources (all validated 18–19 Jun 26)
- **Garmin** `garminconnect` — email+pw, garth token cache persists ~1yr (no re-MFA).
- **Hive** `pyhiveapi` (sync) — no 2FA on his account → headless re-login; live indoor temp from `API(token).getAll()`.
- **Weather** Open-Meteo (keyless), Kilmarnock lat 55.6045 / long -4.5249.

## Conventions (inherited)
`/api/v1/` prefix · `{data, meta, errors}` envelope · snake_case DB / camelCase JSON · UTC `*_utc` columns · IANA timezone per user · branches `feat/`/`fix/`/`chore/` · Conventional Commits · tests ship with every phase.

## Key context (memory)
Project facts persist in `~/.claude/projects/-Users-craigrobinson-wc-2026-predictor/memory/`: `project_garmin_fitness_app`, `reference_garmin_app_handover`. His source docs: `~/Downloads/Dad Fitness/`.
