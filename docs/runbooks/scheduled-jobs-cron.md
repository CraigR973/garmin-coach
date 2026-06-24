# Scheduled jobs — reliability & external cron

## The problem

All scheduled work runs in-process via APScheduler inside the **web container**
(`src/main.py` lifespan → `create_scheduler()`). That is only reliable if the
container runs continuously. In prod it does not: for days the Hive 15-minute
poll produced only *manual* readings, because the container is (re)started /
idle-cycled often enough that a plain interval rarely reaches its first fire,
and wall-clock jobs (06:30 morning sync, evening nudges) only fire if the
container happens to be awake at that minute.

Diagnosis (2026-06-24): **two compounding causes.** (1) `pyhiveapi` was missing
from `apps/api/requirements.txt`, so the Hive poll raised `ModuleNotFoundError`
in the **prod container** — every `railway run` test passed only because it uses
the *local* venv, which had the package installed ad-hoc (fixed:
`pyhiveapi>=0.5.16` added to `requirements.txt`). (2) The web container wasn't
running continuously (Railway App Sleeping), so the in-process scheduler rarely
fired the 15-minute interval at all. **Both** had to be fixed: install the
dependency **and** keep the container always-on (or move to external cron).

## Two-part fix

### 1. Band-aid (shipped): seed the interval jobs

`create_scheduler()` seeds the Hive poll with `next_run_time = now + 2 min` (the
Garmin activity poll was already seeded at +5 min), so a freshly started
container polls Hive shortly after startup instead of waiting a full interval.
This does **not** help the wall-clock jobs (06:30 etc.).

### 2. External cron (the durable fix)

Run each job from an external scheduler via the single-job runner:

    python -m src.run_scheduled <job>

| job             | cadence              | suggested cron (UTC)   |
|-----------------|----------------------|------------------------|
| `hive-poll`     | every 15 min         | `*/15 * * * *`         |
| `activity-poll` | hourly               | `0 * * * *`            |
| `backup`        | 03:00 UTC            | `0 3 * * *`            |
| `morning-sync`  | 06:30 Europe/London  | `30 6 * * *`  ⚠ DST    |
| `autopush`      | 07/13/19 London      | `0 7,13,19 * * *`  ⚠   |
| `evening-nudge` | 20:00 London         | `0 20 * * *`  ⚠        |
| `evening-alerts`| 19–22 London, /15    | `*/15 19-22 * * *`  ⚠  |

⚠ **DST:** Railway/most cron runs in UTC and does not track Europe/London
BST↔GMT. The interval jobs (`hive-poll`, `activity-poll`, `backup`) are
timezone-agnostic and move cleanly. The wall-clock jobs drift ±1h across DST
under a fixed UTC cron. Options, best first:

1. **Keep the container always-on** (disable Railway "App Sleeping" on the `api`
   service) and let in-process APScheduler keep the wall-clock jobs — it already
   handles DST via `timezone=Europe/London`. Use external cron only for the
   interval jobs / resilience.
2. Accept ±1h drift on the wall-clock jobs under a fixed UTC cron.
3. Run them more frequently and gate inside the job on the London-local time.

### Railway Cron setup

Railway runs a cron on a **service**, run-to-completion. The `api` web service
can't also be a cron, so add one Railway service per cron job (same repo/image):

- Root Directory = repo root (so the Docker build context sees `/migrations`).
- Start command = `python -m src.run_scheduled <job>` (no `alembic upgrade head`).
- Set the **Cron Schedule** from the table above.
- Same env vars as `api` (`DATABASE_URL`, `GARMIN_*`, `HIVE_TOKENSTORE_B64`,
  `ANTHROPIC_*`, `INTERVALS_*`).

### Cutover — avoid double-runs

Jobs are idempotent (Hive just appends a reading; morning analysis is
idempotent-per-day; activity/daily upsert), so cron + APScheduler can overlap
briefly with no harm. Once cron is verified, set `SCHEDULER_ENABLED=false` on the
`api` service so the in-process scheduler stops and jobs run only via cron.

The runner exits 0 even when a job fails internally (the job functions log and
swallow their own errors, matching the in-process scheduler). Watch the logs, not
the exit code, for job health.
