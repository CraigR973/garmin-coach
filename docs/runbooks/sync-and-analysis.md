# Sync and Analysis Runbook

Day-to-day observability and recovery for the scheduled sync and analysis jobs.

## Log format

The backend emits structured JSON logs via structlog. Every log line is a JSON object:

```json
{"event": "garmin activity poll complete", "profiles": 1, "activities": 3, "analyses_generated": 1, "timestamp": "2026-06-20T07:01:00Z", "level": "info"}
```

Key fields:

- `event` — the log message (see per-job events below)
- `level` — `info`, `warning`, or `error`
- `correlation_id` — request-scoped, auto-generated
- `timestamp` — ISO-8601 UTC
- Exception payloads appear as `exception` with traceback

On Railway, view logs via the Railway dashboard → service `api` → **Deployments → Logs**, or stream with:

```bash
railway logs --service api --tail
```

## Scheduler jobs summary

| Job ID | Trigger | Success event | Failure event |
|---|---|---|---|
| `daily_backup` | 03:00 UTC daily | `scheduled backup complete` | `scheduled backup failed` |
| `hive_temperature_poll` | every 15 min | `hive temperature poll complete` | `hive temperature poll failed` |
| `morning_weather_sync` | 06:30 Europe/London | `morning weather sync complete` | `morning weather sync failed` |
| `garmin_activity_poll` | every 60 min | `garmin activity poll complete` | `garmin activity poll failed` |
| `evening_sleep_nudge` | 20:00 Europe/London | `evening sleep nudge complete` | `evening sleep nudge failed` |
| `evening_monitoring_alerts` | 19–22:00 every 15 min (Europe/London) | `evening monitoring alerts complete` | `evening monitoring alerts failed` |

All job failures are swallowed at the top level (the log event includes the traceback) so one failing job does not stop others.

## Production daily-loop gate

Batch 12 and later coaching-delivery work depend on the production daily loop
containing real data, not just returning HTTP 200. Use the strict smoke mode
after setting Railway source/analysis variables and allowing or manually
triggering the jobs:

```bash
API_URL=https://api-production-e2bc7.up.railway.app \
SMOKE_DEVICE_TOKEN=<active-device-token> \
SMOKE_STRICT_DAILY_LOOP=1 \
python3 scripts/smoke_daily_loop.py
```

Strict mode fails unless `/api/v1/daily-loop` has all of:

- non-null `dailyMetrics`
- non-null `sleep`
- non-null `morningAnalysis`
- Hive `thermalState.latestTemperatureC`
- weather `thermalState.overnightLowC`
- weather `thermalState.overnightWindMaxMph`

Required Railway variables for this gate are `ENVIRONMENT=production`,
`GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARMIN_TOKENSTORE`, `HIVE_EMAIL`,
`HIVE_PASSWORD`, `SUPABASE_SERVICE_KEY`, and `ANTHROPIC_API_KEY`. Hosted
deployments should also set `GARMIN_TOKENSTORE_B64` after an interactive
bootstrap because Railway's app filesystem is not a durable Garmin tokenstore.

## Garmin sync

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `garmin activity poll failed` with `LoginRequiredException` | garth token cache expired or missing | Run `PYTHONPATH=apps/api apps/api/.venv/bin/python scripts/bootstrap_garmin_tokenstore.py --env-output /tmp/garmin-token.env`, paste/set `GARMIN_TOKENSTORE_B64` in Railway, then restart |
| `garmin activity poll failed` with `GarminConnectTooManyRequestsError` | rate-limited by Garmin | Wait 5–10 minutes; the next hourly poll will retry automatically |
| `activities: 0` in success log consistently | garth token cache present but stale | Refresh `GARMIN_TOKENSTORE_B64` with `scripts/bootstrap_garmin_tokenstore.py` or delete the local `GARMIN_TOKENSTORE` path before re-bootstrap |
| Activities sync but time-series empty | activity does not have power/HR data | Expected for indoor strength or GPS-only activities |

**Confirming sync health:**

```bash
# Tail for the hourly poll event
railway logs --service api | grep "garmin activity poll"
```

Success looks like:
```json
{"event": "garmin activity poll complete", "profiles": 1, "activities": 1, "timeseries_samples": 5040, "analyses_generated": 1, "analyses_existing": 0}
```

## Hive sync

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `hive temperature poll failed` with auth error | Hive password changed or session expired | Update `HIVE_EMAIL` / `HIVE_PASSWORD` in Railway env; the next 15-minute poll will re-authenticate |
| `readings: 0` in success log | Hive API returned no devices | Check that `HIVE_EMAIL` / `HIVE_PASSWORD` match the Hive account that owns the thermostat |
| Temperature readings stop updating | Hive cloud outage | Wait; polls resume automatically when Hive recovers |

**Confirming sync health:**

```bash
railway logs --service api | grep "hive temperature poll"
```

## Morning weather sync and analysis

The 06:30 Europe/London job runs weather sync first, then triggers morning analysis for each profile.

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `morning weather sync failed` | Open-Meteo unreachable | No action needed; Open-Meteo is keyless and usually recovers within minutes. Analysis will generate the next morning when the job runs again |
| `morning analysis failed` in log (per-profile) | `ANTHROPIC_API_KEY` missing or invalid, or Claude API error | Verify `ANTHROPIC_API_KEY` in Railway env; check Anthropic status page |
| `morning analysis failed` with `no_daily_metrics` | Garmin sync has not run yet for today | Wait for the next hourly Garmin poll or run a manual trigger |
| Analysis `analyses_existing: 1` in log | Analysis already generated for today | Expected; the 06:30 job is idempotent |

**Confirming analysis health:**

```bash
railway logs --service api | grep "morning weather sync"
```

Success with analysis:
```json
{"event": "morning weather sync complete", "profiles": 1, "days": 7, "analyses_generated": 1, "analyses_existing": 0}
```

If `analyses_generated: 0` and `analyses_existing: 0` after the 06:30 window, look for a preceding `morning analysis failed` line with the traceback.

## Post-workout analysis

The hourly Garmin poll detects new rides and generates post-workout analysis once per activity.

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `post-workout analysis failed` per-profile log | `ANTHROPIC_API_KEY` invalid, or Claude API error | Verify key; the next hourly Garmin poll will retry for activities within the last 3 days |
| `analyses_generated: 0` after a ride | Activity was a strength session (wrist HR) — excluded by design | Expected; strength recovery is excluded per data-quality rules |
| Duplicate analyses | Should not occur; `activity_id` idempotency guard prevents it | If seen, check for duplicate `analyses` rows with same `activity_id` |

## Zwift workout delivery

Workout delivery is output-only: the app proposes a workout from
`planned_workouts`, approval records the explicit human gate, and only then does
`push` create an intervals.icu calendar event. Garmin remains the only activity
ingestion source.

Required Railway variables:

- `INTERVALS_API_KEY`
- `INTERVALS_ATHLETE_ID=i618709`
- `INTERVALS_BASE_URL=https://intervals.icu/api/v1`

Operational notes:

- Push uses `POST /api/v1/workout-delivery/proposals/{proposal_id}/push`.
- `.ZWO` fallback is available from
  `GET /api/v1/workout-delivery/proposals/{proposal_id}/zwo`.
- Cadence-critical repeats are emitted as individual steps, not an `IntervalsT`
  repeat block, because Zwift overrides cadence on repeated blocks. PC Zwift
  cadence override behaviour still needs manual verification before treating
  cadence as locked.

## Evening nudge and monitoring alerts

These jobs send web push notifications and write audit rows to `analyses`.

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `evening sleep nudge failed` | VAPID keys not configured | Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL` in Railway env |
| `sentCount: 0` in audit row | No push subscription registered, or push service rejected | Expected until user has subscribed in the PWA settings; not a job failure |
| Thermal alert not fired at >20°C | No recent Hive reading (stale by >2 h) | Stale-source alert fires instead; check Hive sync |

## Backup

The daily 03:00 UTC backup calls `pg_dump` and writes a compressed custom-format
`.dump` archive to `backup_dir` (default `/tmp/garmin_coach_backups`), keeping the
most recent `BACKUP_RETENTION_COUNT` (7).

Restore with `pg_restore`, not `psql` — the archive is not plain SQL:

```bash
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" coach_20260803_030000.dump
```

**Notes:**

- `coach.activity_timeseries` rows are deliberately excluded (`--exclude-table-data`);
  the table definition is restored empty. It is ~85% of the database and is the one
  table replayable from upstream — refill it with `garmin_history_backfill`. Everything
  authored (analyses, check-ins, plans, profile, chat) is included.
- `pg_dump` must be at least the server's major version. Supabase runs PostgreSQL 17,
  so the image installs `postgresql-client-17` from PGDG rather than bookworm's 15 —
  a mismatch aborts every run with `server version mismatch` (this silently broke the
  backup for five nights from 2026-07-29).
- **Durable since 2026-08-04:** Railway volume `api-volume` (5 GB) is attached to service `api`
  at `/data/backups`, and `BACKUP_DIR=/data/backups` is set, so archives survive redeployment.
  Before this, `BACKUP_DIR` defaulted to the container's ephemeral `/tmp` and every archive was
  lost on the next deploy. A verified run writes ~7.4 MB.

  **Off-site cadence / RPO / RTO:** once a week after the Sunday restore drill
  passes, download the newest archive from the Railway volume and store it in an
  encrypted off-site location that is not Railway or Supabase. Keep at least the
  latest four weekly copies. This gives a stated backup RPO of **24 hours for
  data still on the Railway volume** and **7 days for a platform-loss event that
  takes Railway with it**; the practical RTO target is **4 hours** once a
  PostgreSQL target and app env are available.

  Pull the archive from the volume:

  ```bash
  railway volume files --volume api-volume list /
  railway volume files --volume api-volume download /coach_20260804_030000.dump ~/somewhere/
  ```

  Encrypt before it leaves the operator machine or lands in long-term storage,
  for example with age:

  ```bash
  age -r "$BACKUP_AGE_RECIPIENT" \
    -o ~/secure-backups/checkmark/coach_20260804_030000.dump.age \
    ~/somewhere/coach_20260804_030000.dump
  ```

  Treat a downloaded archive as sensitive health data: it holds every analysis,
  check-in, plan and chat message. Do not leave plaintext copies in temp
  directories or shared folders.
- `pg_dump` failure writes an `AuditLog` row with `action_type=backup_failed`,
  emits `scheduled backup failed`, emits the structured `operator backup alert`
  log with `kind=backup_failed`, records a failed `job_runs` row where possible,
  and exits 1 under the external runner. Wire Railway/GitHub/provider monitoring
  to that non-zero exit or structured log. `settings.admin_alert_user_id` still
  does not cover backup alerts: that push is for brief-generation failure, and an
  ops alert must never land on Mark's phone.
- `python -m src.run_scheduled backup-drill` performs the weekly disposable
  restore proof. It restores the newest archive into `BACKUP_RESTORE_DATABASE_URL`
  with `pg_restore --clean --if-exists --no-owner`, then asserts the restored
  schema/table count, Alembic version, profile rows, analysis rows, and the
  deliberate zero-row `activity_timeseries` exclusion. Any restore or invariant
  failure logs `operator backup alert` with `kind=backup_restore_drill_failed`
  and exits 1.
- Supabase point-in-time restore is a **paid-plan** feature; on the free plan these dumps
  are the only backup that exists.

## Dependency gotcha — `cryptography` on an Intel Mac

From 50.0.0, `cryptography` publishes macOS wheels for **arm64 only**. On this Intel Mac a
`pip install -r apps/api/requirements.lock` therefore falls back to the sdist and tries to
compile against OpenSSL and Rust, which fails without those toolchains. Linux is unaffected
— 50.0.0 ships manylinux wheels covering both ubuntu CI and the Debian bookworm image
(`cp39-abi3-manylinux_2_28_x86_64` satisfies Python 3.12), so CI and production install a
prebuilt wheel normally. The local `apps/api/.venv` can stay on an older build for running
pytest/ruff/mypy; it is not what ships.

## Manual job trigger

APScheduler does not expose an HTTP API for triggering jobs. To run a job on demand:

1. Open a Railway shell: **Dashboard → service `api` → Settings → Shell**.
2. Run the job function directly:

```python
import asyncio
from src.scheduler import run_morning_weather_sync
asyncio.run(run_morning_weather_sync())
```

Or use a one-off Railway deploy with a command override.

## Health endpoints

```bash
# Liveness — returns sha of deployed commit
curl https://api-production-e2bc7.up.railway.app/api/v1/health

# Readiness — returns 503 if DB is unreachable
curl https://api-production-e2bc7.up.railway.app/api/v1/health/ready
```

Use `health/ready` in Railway healthcheck config to prevent routing traffic to a container that cannot reach the database.
