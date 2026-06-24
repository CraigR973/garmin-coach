"""Run a single scheduled job once and exit.

This is the entry point for an *external* scheduler (Railway Cron, GitHub
Actions, cron-job.org, or a manual ``railway run``) when the in-process
APScheduler cannot be relied on — e.g. the web container is not continuously
running, so wall-clock and interval jobs do not fire reliably (see
``docs/runbooks/scheduled-jobs-cron.md``).

Each job name maps to the same coroutine the in-process scheduler runs, so
behaviour is identical; the job functions log and swallow their own errors, so
this exits 0 even on an internal failure (failures are visible in the logs).

Usage:
    python -m src.run_scheduled <job>

Jobs:
    hive-poll       poll Hive indoor temperature
    wake-check      poll Garmin sleep; fire the morning verdict once wake is stable
    morning-sync    weather + Garmin daily sync + morning analysis (wake backstop)
    activity-poll   poll Garmin for new activities + post-workout analysis
    autopush        push approved workout proposals due soon
    evening-nudge   send the evening sleep-protocol nudge
    evening-alerts  bedtime thermal + source-freshness alerts
    backup          database backup
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable

from src.scheduler import (
    run_evening_monitoring_alerts,
    run_evening_sleep_nudge,
    run_garmin_activity_poll,
    run_hive_temperature_poll,
    run_morning_weather_sync,
    run_scheduled_backup,
    run_wake_check,
    run_workout_autopush,
)

JOBS: dict[str, Callable[[], Awaitable[None]]] = {
    "hive-poll": run_hive_temperature_poll,
    "wake-check": run_wake_check,
    "morning-sync": run_morning_weather_sync,
    "activity-poll": run_garmin_activity_poll,
    "autopush": run_workout_autopush,
    "evening-nudge": run_evening_sleep_nudge,
    "evening-alerts": run_evening_monitoring_alerts,
    "backup": run_scheduled_backup,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a single scheduled job once and exit.")
    parser.add_argument("job", choices=sorted(JOBS), help="The scheduled job to run once")
    return parser


async def _run(job: str) -> None:
    await JOBS[job]()


def main() -> None:
    args = _build_parser().parse_args()
    asyncio.run(_run(args.job))


if __name__ == "__main__":
    main()
