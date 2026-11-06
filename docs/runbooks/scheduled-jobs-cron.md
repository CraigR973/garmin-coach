# Scheduled jobs — reliability & external cron

**6 Nov, Batch 371:** only `api` remains on Railway; the two retired cron services were deleted by exact ID, with API/volume configuration and the API deployment unchanged. Weekly-review and trend-narratives still run inside the always-on API. The encrypted backup/offsite workflow described below is built but unmerged pending Neon/B2 inputs; production still uses the prior backup code. Do not create replacement cron services from the historical examples below.

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
| `backup`        | 03:00 UTC (Sunday's is the full archive, Batch 341) | `0 3 * * *` |
| `baseline-refresh` | 02:30 Europe/London | `30 1,2 * * *`  ⚠ see below |
| `wake-check`    | every 15 min         | `*/15 * * * *`         |
| `morning-sync`  | 11:00 Europe/London  | `0 11 * * *`  ⚠ DST    |
| `autopush`      | 07/13/19 London      | `0 7,13,19 * * *`  ⚠   |
| `intervals-rail`| 07:05/13:05/19:05 London, and after each start | `5 7,13,19 * * *`  ⚠ |
| `live-ride-check` | 03:15 London (Batch 335; before any morning is read) | `15 2,3 * * *`  ⚠ |
| `weekly-review` | Sunday 18:00 London  | `0 18 * * 0`  ⚠       |
| `state-change`  | 11:45 London         | `45 11 * * *`  ⚠       |
| `longitudinal-analysis` | daily collector; monthly submit | `15 12 * * *`  ⚠ |
| `trend-narratives` | daily current month + season | `30 12 * * *`  ⚠ |
| `evening-nudge` | 20:00 London         | `0 20 * * *`  ⚠        |
| `evening-alerts`| 19–22 London, /15    | `*/15 19-22 * * *`  ⚠  |
| `fan-control`   | every 15 min         | `*/15 * * * *`         |
| `backup-drill` | daily offsite-proof check (371, pending deploy) | `0 5 * * *` |
| `egress-budget` | every 15 min         | `*/15 * * * *`         |
| `ledger-freshness` | hourly            | `20 * * * *`  ⭑ see below |
| `timeseries-retention` | daily 03:40 UTC | `40 3 * * *`  ⚑ see below |

⚑ **`timeseries-retention` ships dry-run and stays that way until somebody
decides otherwise (Batch 247.2).** It deletes per-second samples for activities
older than 90 days — **466,449 rows measured on 2026-09-02** — from
`activity_timeseries`, which is **excluded from every backup by design**, so
there is no undo. With `ACTIVITY_TIMESERIES_RETENTION_ENABLED` unset it measures
and logs what it *would* remove on every pass and deletes nothing, which is
still worth running: it turns "somebody should watch this" into a counter in
`job_runs`. Two things to know before enabling it. The window is keyed on the
**activity's** start time, not the sample's timestamp, so an activity spanning
the cutoff goes whole rather than half. And a `DELETE` returns space to the
free-space map without shrinking the files — `pg_database_size` will barely
move. Actually reclaiming it needs `VACUUM FULL`, `pg_repack` or
dump/truncate/reload, and `VACUUM FULL` needs the live data's size free before
it starts, which is precisely how 2026-06-28 went wrong (DECISIONS #93).

**Retention is on since 2026-09-24 (DECISIONS #349), and the freed space was reclaimed
once on 2026-10-07 (DECISIONS #388):** `VACUUM (FULL, ANALYZE) coach.activity_timeseries`
with `lock_timeout = '5s'`, via `railway run`, took 9.6 s and took the database from
458.1 to 171.0 MB. The storage meter in `egress-budget` sums every database
(`all_databases_bytes`, Batch 325), because that is what Supabase's 500 MB limit is
enforced on.

⭑ **`ledger-freshness` is external-only, on purpose (Batch 242.5).** It is the
one job in this table that is **not** registered on the in-process APScheduler,
and a test asserts that absence. It reads the newest `job_runs` row per job and
`log.error`s any that is older than its tolerance — which is what turns a
scheduler that has silently stopped into an operator signal, so running it on
the scheduler it watches would take it down for exactly the reason it needs to
fire. Give it its own clock: a Railway cron service, or anything external. Its
tolerances live in `services/job_ledger_freshness.MAX_AGE` and a test fails if a
recurring job is added to `run_scheduled.JOBS` without one.

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

#### `baseline-refresh` and its 02:30 slot (Batch 228)

The slot is load-bearing rather than arbitrary, and ±1h of DST drift breaks it —
so if this ever moves to external cron it must take option 3, the same
London-hour guard the `weekly-review` service already uses (`30 1,2 * * *`, and
run only when `TZ=Europe/London date +%H%M` is `0230`). Three reasons, all
measured:

- **It must precede the morning read it feeds.** `wake_detection.WINDOW_START`
  is 03:30 Europe/London and Mark's earliest observed wake is 03:45, so 02:30
  leaves a full hour. A fixed `30 2 * * *` UTC cron lands at 03:30 London under
  BST — exactly `WINDOW_START`.
- **It must not put tonight inside its own distribution.** `rebuild` ends its
  84-night window at the newest stored night, and the `sleep` row for the night
  in progress is written by the wake sync hours later (observed 07:33–08:27), so
  a 02:30 run always ends at yesterday. A run after wake would judge a night
  against a baseline containing it. The ad-hoc admin runs did whichever the
  operator's clock happened to give: the 2026-08-20 12:30 UTC run included that
  morning, the 2026-08-26 06:13 UTC one did not.
- **It should precede the backup.** 02:30 London is 01:30 UTC under BST and
  02:30 UTC under GMT, so it lands before the 03:00 **UTC** `daily_backup` in
  both and the nightly dump carries the freshened rows. (`daily_backup` has no
  `timezone=`, and the scheduler is constructed with `timezone="UTC"`.)

The job is registered in three places and all three must agree on the name
`baseline-refresh`: `create_scheduler`'s `partial(run_tracked_job, ...)`, the
`JOBS` map in `run_scheduled.py`, and `_LOCAL_DAILY_JOBS` in
`services/job_runs.py`. Omitting the third is silent — `scheduled_window` falls
back to a 60-minute bucket and the run history stops meaning "did tonight's run
happen?". `tests/test_metric_baseline_refresh.py` pins all three.

### Historical production configuration (26 Aug; superseded by 371)

`railway status --json` on the `garmin-coach` production environment returns
these services:

| service | cron schedule | start command | what runs |
|---|---|---|---|
| `api` | *none* | *none* (Dockerfile web entrypoint) | every job, via in-process APScheduler |
| `weekly-review` | `0 17,18 * * 0` | London-hour-guarded `python -m src.run_scheduled weekly-review` | that one job, durably |
| `trend-narratives` | `30 11,12 * * *` | London-minute-guarded `python -m src.run_scheduled trend-narratives` | current month + season narratives, durably |

So **the old configuration intended durable external paths for `weekly-review` and `trend-narratives`. The review proved they did not run; both services were deleted on 6 Nov (371).** Everything
else — `baseline-refresh` included — fires only while the `api` container is
awake, which is the reliability caveat this whole runbook exists for. The API
service runs one replica with `restartPolicyType=ON_FAILURE` and no App
Sleeping, and `coach.job_runs` shows the in-process scheduler firing on time
(`backup` at exactly 03:00:00 UTC on each of the last eleven days, ~96
`wake-check` invocations a day), so in practice it holds — but it is a practice,
not a guarantee.

**How to tell the difference without guessing:** every real invocation writes a
`coach.job_runs` row, so a night with no `baseline-refresh` row is a night the
job did not run. `run_evening_monitoring_alerts` also carries an operator-only
detector for the same failure (Batch 228): it logs `operator alert` with
`kind=metric_baselines_stale` once a profile's baselines trail its stored sleep
history by `BASELINE_STALENESS_LIMIT_DAYS` nights or more. That is deliberately
*not* one of the `evaluate_stale_sources` web pushes — those tell Mark to put his
watch on, and a background job that has stopped is not his to fix.

### Railway Cron setup

Railway runs a cron on a **service**, run-to-completion. The `api` web service
can't also be a cron, so add one Railway service per cron job (same repo/image):

- Root Directory = repo root (so the Docker build context sees `/migrations`).
- Set `SCHEDULED_JOB=<job>` instead of a start command: the shared Docker image
  then runs `python -m src.run_scheduled <job>` without `alembic upgrade head`.
- Set the **Cron Schedule** from the table above.
- Same env vars as `api` (`DATABASE_URL`, `GARMIN_*`, `HIVE_TOKENSTORE_B64`,
  `ANTHROPIC_*`, `INTERVALS_*`).

#### Historical weekly-review service (Batch 185; deleted 6 Nov)

Railway evaluates cron expressions in UTC only. Production therefore schedules
the `weekly-review` service at both Sunday candidates, `0 17,18 * * 0`, and its
start command runs `python -m src.run_scheduled weekly-review` only when
`TZ=Europe/London date +%H` is `18`. One candidate runs at 18:00 through BST and
GMT; the other exits cleanly. The service references the API service's database,
Anthropic, production-validation and VAPID variables, has no public domain, and
uses `restartPolicyType=NEVER`. Its settings live in `.railway/railway.ts` (Batch
287); since `railway.toml` was removed on 27 Sep 2026 its deployment manifest no
longer carries the API's health check. For this run-to-completion service, verify
the scheduled service status plus each execution's exit and logs.

Keep the API's in-process scheduler enabled while only this one external job is
provisioned. The weekly review's PostgreSQL advisory lock plus review/message/
push idempotency make an APScheduler/cron overlap safe.

#### Historical trend-narratives service (Batch 266; deleted 6 Nov)

The `trend-narratives` service sets `SCHEDULED_JOB=trend-narratives` and
`SCHEDULED_LONDON_HHMM=1230` on the shared image. It runs at
`30 11,12 * * *` UTC; the image's London-minute guard permits only `12:30`
Europe/London, once through both BST and GMT. It references the API's database,
Anthropic, Sentry and VAPID variables, has no public domain and uses
`restartPolicyType=NEVER`.

Keep the API's in-process scheduler enabled. A transaction-scoped PostgreSQL
advisory lock covers each profile/bucket/period paid call, so an overlap with
the durable runner returns `in_progress` and retries on the next daily run
instead of generating twice.

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

### Longitudinal analyst billing-alert gate

`longitudinal-analysis` polls an already-submitted Anthropic Message Batch on
each invocation and submits at most one paid request per sleep-bearing profile
per calendar month. Empty operator-only profiles are excluded. The submit path
fails closed before token counting or batch creation
unless `ADMIN_ALERT_USER_ID` resolves to an active profile with an active web-
push subscription. It also rejects the subject profile itself as the recipient:
Mark must never receive operator/billing incidents.

The 2026-08-24 preflight over Mark's 427-night history measured the final
columnar prompt at 115,541 bytes and 55,477 input tokens. At the current Sonnet
4.6 Batch rates that is $0.083 of input; with the configured 4,096-token output
cap, one request cannot exceed roughly $0.114 before any provider-side rounding.

Provision the operator as a separate private profile, mint its activation link
with `python -m src.activate --profile <operator-name>`, activate the intended
device, and enable notifications. Confirm an active `push_subscriptions` row,
then set `ADMIN_ALERT_USER_ID` to that profile UUID on the `api` service. A job
run before this is ready exits cleanly as `skipped` with
`admin_billing_alert_not_ready`; it cannot incur Claude spend.

### Encrypted backup and offsite restore proof (Batch 371; pending deploy)

The existing exclusions remain: every archive omits per-second `activity_timeseries` rows; nightly archives also omit `sleep`/`daily_metrics`, and Sunday's full archive keeps those two tables. Authored records and referenced activities stay in both. The volume retains seven new encrypted nightly and four full archives. Existing plaintext is not deleted by that retention policy; retire exact files only after verified encrypted copies and Craig's separate approval.

At 03:00 UTC the API creates an owner-only temporary dump in `/dev/shm` on Linux, checks its complete data stream with `pg_restore --data-only --file=-`, then encrypts to its public age recipient. Only verified ciphertext is published on `/data/backups` as `coach_[full_]YYYYMMDD_HHMMSS.dump.age`; failures retain no new archive or persistent plaintext. `wire_bytes` remains the uncompressed COPY byte count used by the egress meter. Missing key fails, never silently falls back to plaintext. Temporary RAM capacity must fit the dump; exhaustion must alert rather than spill to the retained volume.

Sunday's job copies the newest full and nightly encrypted archives to private B2 under `coach/`. The uploader must be restricted to that bucket/prefix and upload capability, without read/delete/key/bucket administration. A failed export fails the backup job even if the local archive is safe. The GitHub reader uses a separate read-only key; download size and SHA-1/SHA-256 must agree before decrypting. Both archives must exist; both are at most eight days old, matching the weekly offsite RPO. A manual midweek drill may prove the most recent weekly pair without pretending it is a fresh nightly export. Dates in the future are rejected.

GitHub `.github/workflows/backup-restore.yml` runs Sundays 04:17 UTC or manually on reviewed `main` only. It decrypts both archives in a private temporary directory, validates both before touching the target, and restores the full then nightly archive into the dedicated Neon Free database `coach_restore`. Target checks reject Supabase, other regions, poolers, other database names, missing TLS and alternate-host query parameters; the server must identify itself as `coach_restore` and contain no other application's tables. Supabase-specific no-login roles and a NULL `auth.uid()` definition are created only in that disposable target to restore existing RLS dependencies. Invariants cover coach tables/Alembic version, profile/analysis rows, excluded sample rows and weekly-only rows. Each restore starts with a reset of only the disposable `coach` schema; a final reset clears it after success/failure. An interrupted/killed job can leave that disposable copy for the next cleanup: investigate the failed run. No production restore credential is available to this runner.

The private age identity is held off Railway, in GitHub Actions and Craig's recovery copies. The workflow publishes only fixed status/coarse counts, with no database stderr, traceback, archive artifact or cache. Standard public-repository runners are free; the workflow needs no Anthropic call. See `docs/drafts/2026-11-05-batch-371-console-steps.md` for provider setup and exact setting names. The optional local `scripts/create_backup_bucket_key.py` produces the minimal scoped keys without putting master credentials in the app or secrets in stdout/argv.

`python -m src.run_scheduled backup-drill` now means **check the real offsite proof**, not restore plaintext beside the production app. The API runs that check daily at 05:00 UTC, without decryption/restore credentials. It accepts only a successful main schedule/manual workflow run from this repository within eight days; the newest completed failure is not hidden by an older success. Missing/unreadable/stale proof fails the job and emits the existing operator alert. `/health/jobs` also checks the proof timestamp independently of the poll's own age, so a recent local skip or a stopped GitHub schedule cannot report green. The external 30-minute watchdog reads that problem. Re-run the GitHub restore workflow after correcting a failure, then run the evidence check; never mark proof successful by manually inventing a ledger counter.

**Recovery after a loss:** retrieve/decrypt the newest offsite nightly and full archives on a trusted machine with the recovery identity, and compare their embedded dates. Restore the **newer archive** for authored state: Sunday's full is newer than Saturday's nightly and is already standalone. If a nightly archive is newer, restore it and then import only `sleep`/`daily_metrics` rows from the newest full. Replay Garmin days since that full archive and re-fetch per-second samples. Never assume a file called nightly is the freshest one. The legacy local proof helper also leaves the newest dated archive last; the offsite drill resets/checks each separately and clears its target. Test in a disposable target before any production replacement; production restoration/deletion still needs Craig's exact-scope approval. Nightly local authored-data RPO is about one day; the offsite catastrophe RPO is up to one week. RTO remains unmeasured until the real remote drill is timed; no recovery-time promise is made from unit tests.
