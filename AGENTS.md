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
| `docs/phase-batches.md` | The batch ledger: every batch's phases, goal, acceptance criteria and shipped result |
| `docs/agent-commands/` | The procedures for starting, verifying and closing out a batch — tool-agnostic, follow them whatever you are |

**Before building a batch, re-verify its ledger row against the code.** A row is
often authored days or weeks before it is built, so its `file:line` references,
measurements and "reuse X, which already does Y" pointers decay. A spec naming
the wrong pattern will be followed faithfully into a broken result — Batch 216's
row told the build to copy the very path that batch exists to fix. Correct the
row and say so before writing code. Full procedure in
`docs/agent-commands/batch-start.md` step 4.

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
/ React 18 + Vite + Tailwind + shadcn/ui + recharts. Auth: revocable opaque
device tokens provisioned by single-use activation links.
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
- Backend test: `PYTHONPATH=apps/api apps/api/.venv/bin/python -m pytest -c apps/api/pyproject.toml` (the explicit config keeps `asyncio_mode=auto` when invoked from the repo root).
- Backend lint/type: `PYTHONPATH=apps/api apps/api/.venv/bin/python -m ruff check apps/api/src apps/api/tests` and `PYTHONPATH=apps/api apps/api/.venv/bin/python -m mypy apps/api/src` (use absolute paths in the sandbox).
- Frontend: `pnpm --dir apps/web test|build|lint` — but the **unit-test gate is `pnpm -r test`** (run from the repo root, Node 20), which is what CI runs. `--dir apps/web` skips `packages/shared` entirely, so a shared-schema test can pass locally by never running (Batch 206).

## Batch close-out is automatic (project override)

**This project overrides the global "close-out is explicit" default** (Craig,
2026-09-03). When a batch's implementation is complete and its gate is green,
run `docs/agent-commands/closeout.md` straight through — merge to `main`, verify
production, tick the docs, strike the ledger row — without waiting to be asked.
Do not stop at "ready for review" and hand back.

`main` auto-deploys to Railway and Vercel (Decision #39), so an automatic
close-out is an automatic production deploy. That is the intent, and it is why
the gate in front of it is not optional:

- Every CI check green on **both** the push and PR waves, and the local gates
  (`pytest`, `ruff check`, `ruff format --check`, `mypy src`, `pnpm -r test`,
  web build/lint) clean before the merge.
- The close-out procedure's own guardrails still bind — above all the
  prompt-version rule: a bump withdraws every stored analysis at the old
  version, so decide in writing what gets regenerated, then drive the *real*
  lookup and regenerate it.
- Production is verified after the deploy, not assumed.

**Still explicit, and never folded into an automatic close-out:** anything
needing Craig's judgement rather than a green gate — Mark-facing copy he has not
signed off, destructive or irreversible operations (the retention purge,
`VACUUM FULL`, any data deletion), credential and hosting changes, and spending
real Anthropic money to regenerate beyond what the close-out itself requires. If
a batch's close-out would touch one of those, do the rest and stop at that step
with the reason.

## Session handoff protocol (both tools)
At the **end** of a work session: (1) update `STATUS.md` — overwrite the "Now"
block (current state + next step + gotchas) and prepend a dated line to the
"Log"; (2) append any architectural decision to `DECISIONS.md` (what + why);
(3) commit. The next agent — Claude or Codex — then starts from a known state.
