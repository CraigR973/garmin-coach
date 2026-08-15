# Scheduled jobs — reliability & external cron

## The problem

All scheduled work runs in-process via APScheduler inside the **web container**
(`src/main.py` lifespan → `create_scheduler()`). That is only reliable if the
container runs continuously. In prod it does not: for days the Hive 15-minute
poll produced only *manual* readings, because the container is (re)started /
idle-cycled often enough that a plain interval rarely reaches its first fire,
and wall-clock jobs (11:00 morning backstop, evening nudges) only fire if the
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
| `wake-check`    | every 15 min         | `*/15 * * * *`         |
| `morning-sync`  | 11:00 Europe/London  | `0 11 * * *`  ⚠ DST    |
| `autopush`      | 07/13/19 London      | `0 7,13,19 * * *`  ⚠   |
| `weekly-review` | Sunday 18:00 London  | `0 18 * * 0`  ⚠       |
| `state-change`  | 11:45 London         | `45 11 * * *`  ⚠       |
| `evening-nudge` | 20:00 London         | `0 20 * * *`  ⚠        |
| `evening-alerts`| 19–22 London, /15    | `*/15 19-22 * * *`  ⚠  |
| `fan-control`   | every 15 min         | `*/15 * * * *`         |

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

#### Production weekly-review service (Batch 185)

Railway evaluates cron expressions in UTC only. Production therefore schedules
the `weekly-review` service at both Sunday candidates, `0 17,18 * * 0`, and its
start command runs `python -m src.run_scheduled weekly-review` only when
`TZ=Europe/London date +%H` is `18`. One candidate runs at 18:00 through BST and
GMT; the other exits cleanly. The service references the API service's database,
Anthropic, production-validation and VAPID variables, has no public domain, and
uses `restartPolicyType=NEVER`. The shared root `railway.toml` leaves the API
healthcheck path in the resolved deployment manifest; that is web-cutover
metadata, not cron verification. For this run-to-completion service, verify the
scheduled service status plus each execution's exit and logs.

Keep the API's in-process scheduler enabled while only this one external job is
provisioned. The weekly review's PostgreSQL advisory lock plus review/message/
push idempotency make an APScheduler/cron overlap safe.

Every real APScheduler invocation and every external-runner invocation now
records one operator-only `coach.job_runs` row with its cadence window,
start/finish timestamps, `succeeded` / `skipped` / `degraded` / `failed` status,
stable reason and integer counters. The run row uses a separate transaction, so
rolling back the job's own failed work cannot erase its failure evidence.

### Cutover — avoid double-runs

Jobs are idempotent (Hive just appends a reading; morning analysis is
idempotent-per-day; activity/daily upsert), so cron + APScheduler can overlap
briefly with no harm. **Do not set `SCHEDULER_ENABLED=false` yet.** Disabling the
in-process scheduler remains the Decision-gated Batch 195.4 hosting call: Craig
must choose always-on API versus full externalisation, and every external job
must first have a proved successful run. The 20:30 `post_workout_backstop` is
still in-process-only and is deliberately not exposed as a new external service
by Batch 195.

The runner exits 0 only for `succeeded`/`skipped`. Any `degraded` or `failed`
outcome exits 1 after attempting to persist the run row, so Railway/GitHub cron
can alert directly from process state. If even the run-row write fails, the
runner also exits 1 (`reason=job_run_persistence_failed`).
