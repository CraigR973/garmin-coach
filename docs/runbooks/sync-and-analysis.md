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

## Garmin sync

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `garmin activity poll failed` with `LoginRequiredException` | garth token cache expired or missing | Set `GARMIN_EMAIL` / `GARMIN_PASSWORD` in Railway env and restart; garth will re-authenticate and write a fresh token cache |
| `garmin activity poll failed` with `GarminConnectTooManyRequestsError` | rate-limited by Garmin | Wait 5–10 minutes; the next hourly poll will retry automatically |
| `activities: 0` in success log consistently | garth token cache present but stale | Delete `GARMIN_TOKENSTORE` path (default `~/.garminconnect`) and restart so garth re-authenticates |
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

## Evening nudge and monitoring alerts

These jobs send web push notifications and write audit rows to `analyses`.

**Common failures:**

| Symptom | Cause | Recovery |
|---|---|---|
| `evening sleep nudge failed` | VAPID keys not configured | Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL` in Railway env |
| `sentCount: 0` in audit row | No push subscription registered, or push service rejected | Expected until user has subscribed in the PWA settings; not a job failure |
| Thermal alert not fired at >20°C | No recent Hive reading (stale by >2 h) | Stale-source alert fires instead; check Hive sync |

## Backup

The daily 03:00 UTC backup calls `pg_dump` and writes a `.sql` file to `backup_dir` (default `/tmp/garmin_coach_backups`).

**Notes:**

- Railway containers use ephemeral storage: `/tmp/` backups do not survive redeployment. For durable backups, set `BACKUP_DIR` to a mounted volume or export the Railway service volume.
- `pg_dump` failure writes an `AuditLog` row with `action_type=backup_failed`; check the Railway logs for `scheduled backup failed`.
- The Supabase dashboard also provides point-in-time restore for the production database independently of these backups.

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
