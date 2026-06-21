# Garmin Coach — Agent Instructions

> **This is the canonical instruction file for ALL coding agents on this repo
> (Claude Code, Codex, etc.).** `CLAUDE.md` is a symlink to this file. Codex reads
> `AGENTS.md` natively. Keep everything cross-tool here — never put a decision or
> a convention somewhere only one tool can see.

Private AI fitness & sleep coach for Craig's dad ("Mark"), optionally a 2nd user.
Pulls Garmin/Hive/weather data, holds his profile + training plan + rules as
persistent state, and generates a daily morning verdict + post-workout analysis
with Claude.

## Source of truth — read these first
| Doc | Holds |
|---|---|
| `ARCHITECTURE.md` | The spec: data sources, knowledge base, analysis engine, data model, roadmap |
| `DECISIONS.md` | Why things are the way they are — a running decision log. **Don't re-litigate a settled decision; append a new one if you change course.** |
| `STATUS.md` | Where we are *right now* + the next step + gotchas. **Read at the start of every session; update at the end.** |

**Cross-tool rule:** the repo is the single source of truth. Claude Code has a
private memory store; treat it as a convenience cache only — every durable fact
must also live in these in-repo docs so Codex (and future sessions) can see it.

## Origin
Forked from the WC2026 predictor to inherit its infra (auth, APScheduler,
web-push, PWA, shadcn, CI, Docker, Railway/Vercel). The football domain is being
stripped (Phase 0). A reusable starter template will be distilled from the two
apps *later* — do not extract it prematurely.

## Stack
FastAPI + async SQLAlchemy + asyncpg + Postgres (Supabase) + Alembic + APScheduler
/ React 18 + Vite + Tailwind + shadcn/ui + recharts. Auth: name + PIN + JWT.
1–2 private users, no public sign-up. Hosting: Supabase + Railway (API) + Vercel (web).

## Bash discipline
- **Never `cd`** (sandbox blocks it; a blocked `cd` surfaces as a misleading ENOSPC error). Use absolute paths.
- Python is **3.12** (`~/.local/bin/python3.12`). System `python3` is 3.7 — too old (garth/pyhiveapi need ≥3.10). The api venv (`apps/api/.venv`) is created during setup.
- Validated data-source spikes (throwaway, NOT in this repo): `~/garmin-spike/spike.py` (Garmin), `~/garmin-spike/hive_spike.py` (Hive), venv `~/garmin-spike/.venv`. **Real sample JSON in `~/garmin-spike/out/` + `out_hive/` is the canonical reference for field shapes.**

## Data sources (all validated 18–19 Jun 26)
- **Garmin** `garminconnect` — email+pw, garth token cache persists ~1yr (no re-MFA).
- **Hive** `pyhiveapi` (sync) — account uses AWS Cognito **SMS_MFA**, so headless operation resumes from a cached Cognito **refresh token** (`HIVE_TOKENSTORE_B64`, seeded once via `scripts/bootstrap_hive_tokenstore.py`), *not* a password login (DECISIONS #59); live indoor temp from `API(token).getAll()`.
- **Weather** Open-Meteo (keyless), Kilmarnock lat 55.6045 / long -4.5249.

## Conventions
- `/api/v1/` prefix · `{data, meta, errors}` envelope · snake_case DB / camelCase JSON · UTC `*_utc` columns · IANA timezone per user.
- Branches `feat/`/`fix/`/`chore/`; Conventional Commits; small, well-described commits (`git log` is a handoff).
- Tests ship with every change.

## Commands (once the api venv + web deps exist)
- Backend test/lint/type: `PYTHONPATH=apps/api apps/api/.venv/bin/python -m pytest|ruff check|mypy src` (use absolute paths in the sandbox).
- Frontend: `pnpm --dir apps/web test|build|lint`.

## Session handoff protocol (both tools)
At the **end** of a work session: (1) update `STATUS.md` — overwrite the "Now"
block (current state + next step + gotchas) and prepend a dated line to the
"Log"; (2) append any architectural decision to `DECISIONS.md` (what + why);
(3) commit. The next agent — Claude or Codex — then starts from a known state.
