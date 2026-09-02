"""Run a single scheduled job once and exit.

This is the entry point for an *external* scheduler (Railway Cron, GitHub
Actions, cron-job.org, or a manual ``railway run``) when the in-process
APScheduler cannot be relied on — e.g. the web container is not continuously
running, so wall-clock and interval jobs do not fire reliably (see
``docs/runbooks/scheduled-jobs-cron.md``).

Each job name maps to the same coroutine the in-process scheduler runs. The
shared typed result is persisted to ``job_runs``; degraded/failed runs exit 1 so
the external scheduler can alert from process state as well as logs.

Usage:
    python -m src.run_scheduled <job>

Jobs:
    hive-poll       poll Hive indoor temperature
    wake-check      poll Garmin sleep; fire the morning verdict once wake is stable
    morning-sync    weather + Garmin daily sync + morning analysis (wake backstop)
    activity-poll   poll Garmin for new activities + post-workout analysis
    baseline-refresh  recompute every active profile's metric baselines
    autopush        push approved workout proposals due soon
    weekly-review   generate the ending week's review and deliver it to coach chat
    longitudinal-analysis  collect/submit the monthly whole-history analyst run
    state-change    notice one meaningful state transition and deliver it to coach chat
    evening-nudge   send the evening sleep-protocol nudge
    evening-alerts  bedtime thermal + source-freshness alerts
    backup          database backup
    backup-drill    restore latest backup into a disposable DB and check invariants
    egress-budget   flush the response-byte counter and stage a Supabase egress alert
    ledger-freshness  report any job whose newest job_runs row is overdue
    timeseries-retention  purge per-second samples older than the window (dry-run by default)
"""

from __future__ import annotations

import argparse
import asyncio

from src.scheduler import (
    run_activity_timeseries_retention,
    run_backup_restore_drill,
    run_egress_budget_check,
    run_evening_monitoring_alerts,
    run_evening_sleep_nudge,
    run_fan_control,
    run_garmin_activity_poll,
    run_hive_temperature_poll,
    run_longitudinal_analysis,
    run_metric_baseline_refresh,
    run_morning_weather_sync,
    run_scheduled_backup,
    run_state_change_coach,
    run_wake_check,
    run_weekly_review_delivery,
    run_workout_autopush,
)
from src.services.job_ledger_freshness import run_ledger_freshness_check
from src.services.job_runs import JobOperation, JobResult, run_tracked_job

JOBS: dict[str, JobOperation] = {
    "hive-poll": run_hive_temperature_poll,
    "wake-check": run_wake_check,
    "morning-sync": run_morning_weather_sync,
    "activity-poll": run_garmin_activity_poll,
    "baseline-refresh": run_metric_baseline_refresh,
    "autopush": run_workout_autopush,
    "weekly-review": run_weekly_review_delivery,
    "longitudinal-analysis": run_longitudinal_analysis,
    "state-change": run_state_change_coach,
    "evening-nudge": run_evening_sleep_nudge,
    "evening-alerts": run_evening_monitoring_alerts,
    "fan-control": run_fan_control,
    "backup": run_scheduled_backup,
    "backup-drill": run_backup_restore_drill,
    "egress-budget": run_egress_budget_check,
    "timeseries-retention": run_activity_timeseries_retention,
    # Batch 242.5: deliberately absent from ``create_scheduler`` — a watchdog
    # that rides the scheduler it watches goes down with it. External runner
    # only (Railway cron or a manual ``railway run``).
    "ledger-freshness": run_ledger_freshness_check,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a single scheduled job once and exit.")
    parser.add_argument("job", choices=sorted(JOBS), help="The scheduled job to run once")
    return parser


async def _run(job: str) -> JobResult:
    return await run_tracked_job(job, JOBS[job])


def main() -> None:
    args = _build_parser().parse_args()
    result = asyncio.run(_run(args.job))
    if result.exit_code:
        raise SystemExit(result.exit_code)


if __name__ == "__main__":
    main()
