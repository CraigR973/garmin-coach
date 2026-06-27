"""Admin-only backfill runner for historical Garmin data.

Walks a date range and, for each day, reuses the *same* idempotent
``GarminSyncService`` the 06:30 job uses to pull daily metrics + sleep, plus a
monthly-chunked activity sync. It reads from Garmin and writes only to our DB.

Design notes:
  - **Idempotent / resumable.** Per-day upserts mean a re-run is safe; with
    ``--skip-existing`` (default) days that already have a ``daily_metrics`` row
    are skipped, so a crash mid-run resumes where it stopped.
  - **429-safe.** Each Garmin fetch is wrapped in exponential backoff, and
    ``--throttle`` paces calls between days so a year-long pull does not hammer
    Garmin's unofficial API.
  - **Per-day isolation.** One bad day is logged and skipped; it never aborts the
    whole backfill.
  - **Commit-per-day.** Progress is durable as it goes.

Usage (prod — run via ``railway run`` so the prod token blob + DATABASE_URL are
injected; data lands in prod Supabase):

    railway run --service api python -m src.garmin_history_backfill \
        --start 2025-06-24 --dry-run
    # then drop --dry-run to write
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models.coaching import DailyMetric
from src.models.profile import Profile
from src.services.garmin_sync import (
    GarminConnectClient,
    GarminSyncService,
    parse_daily_metric_fields,
    parse_sleep_fields,
)


@dataclass
class BackfillSummary:
    start: date
    end: date
    days_total: int = 0
    days_skipped: int = 0
    days_synced: int = 0
    days_failed: int = 0
    daily_metrics_synced: int = 0
    sleep_synced: int = 0
    activities_synced: int = 0
    timeseries_synced: int = 0
    errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"Window: {self.start.isoformat()} → {self.end.isoformat()} ({self.days_total} days)",
            f"Days synced: {self.days_synced}  skipped(existing): {self.days_skipped}  "
            f"failed: {self.days_failed}",
            f"Daily-metric rows written: {self.daily_metrics_synced}",
            f"Sleep rows written: {self.sleep_synced}",
            f"Activities written: {self.activities_synced}  "
            f"(timeseries samples: {self.timeseries_synced})",
        ]
        if self.errors:
            lines.append(f"Errors ({len(self.errors)}):")
            lines.extend(f"  - {e}" for e in self.errors[:20])
            if len(self.errors) > 20:
                lines.append(f"  ... and {len(self.errors) - 20} more")
        return "\n".join(lines)


def parse_detail_types(raw: str | None) -> set[str] | None:
    """Parse a ``--detail-types`` CSV into a set, or ``None`` for all types.

    An empty/whitespace-only value is treated as ``None`` (all types) rather than
    an empty set (which would fetch details for nothing).
    """
    if not raw:
        return None
    types = {token.strip() for token in raw.split(",") if token.strip()}
    return types or None


def daily_dates(start: date, end: date) -> list[date]:
    """Inclusive list of dates from ``start`` to ``end``."""
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into per-calendar-month (start, end) ranges."""
    if end < start:
        return []
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        nxt_first = (
            date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
        )
        chunks.append((cur, min(end, nxt_first - timedelta(days=1))))
        cur = nxt_first
    return chunks


# Retry tunables (module-level so tests can monkeypatch the delay to 0).
_RETRY_ATTEMPTS = 5
_RETRY_DELAY_SEC = 3.0
_RETRY_BACKOFF = 2.0


async def _retry(operation: Callable[[], Any]) -> Any:
    """Run a blocking Garmin call with exponential backoff (default 3, 6, 12, 24s)."""
    delay = _RETRY_DELAY_SEC
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return operation()
        except Exception:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(delay)
            delay *= _RETRY_BACKOFF
    raise RuntimeError("retry loop exited unexpectedly")


async def _has_daily_metric(session: AsyncSession, user_id: Any, day: date) -> bool:
    result = await session.execute(
        select(DailyMetric.id)
        .where(DailyMetric.user_id == user_id, DailyMetric.calendar_date == day)
        .limit(1)
    )
    return result.first() is not None


async def run_backfill(
    session: AsyncSession,
    profile: Profile,
    *,
    client: GarminConnectClient,
    start: date,
    end: date,
    dry_run: bool = False,
    skip_existing: bool = True,
    throttle: float = 0.0,
    activities: bool = True,
    activity_details: bool = True,
    detail_types: set[str] | None = None,
    log_fn: Callable[[str], None] = print,
) -> BackfillSummary:
    """Backfill daily metrics/sleep (per day) and activities (per month chunk)."""
    summary = BackfillSummary(start=start, end=end)
    sync_service = GarminSyncService(session)

    dates = daily_dates(start, end)
    summary.days_total = len(dates)

    for day in dates:
        if skip_existing and not dry_run and await _has_daily_metric(session, profile.id, day):
            summary.days_skipped += 1
            continue
        try:
            payloads = await _retry(lambda: client.fetch_daily_payloads(day))
            if dry_run:
                metric_fields = parse_daily_metric_fields(day, payloads)
                sleep_fields = parse_sleep_fields(payloads.sleep)
                has_metric = any(
                    metric_fields.get(k) is not None
                    for k in ("readiness_score", "hrv_last_night_avg_ms", "resting_heart_rate_bpm")
                )
                has_sleep = sleep_fields.get("score") is not None
                summary.daily_metrics_synced += int(has_metric)
                summary.sleep_synced += int(has_sleep)
                summary.days_synced += 1
                log_fn(
                    f"  {day.isoformat()}  metrics={'y' if has_metric else '-'}  "
                    f"sleep={sleep_fields.get('score') if has_sleep else '-'}  (dry-run)"
                )
            else:
                result = await sync_service.sync_daily(profile.id, day, payloads, commit=True)
                summary.daily_metrics_synced += result.daily_metrics_synced
                summary.sleep_synced += result.sleep_synced
                summary.days_synced += 1
                log_fn(
                    f"  {day.isoformat()}  daily+{result.daily_metrics_synced} "
                    f"sleep+{result.sleep_synced}"
                )
        except Exception as exc:  # noqa: BLE001 - per-day isolation
            summary.days_failed += 1
            summary.errors.append(f"{day.isoformat()}: {type(exc).__name__}: {exc}")
            log_fn(f"  {day.isoformat()}  FAILED: {type(exc).__name__}: {exc}")
        if throttle:
            await asyncio.sleep(throttle)

    if activities:
        for chunk_start, chunk_end in month_chunks(start, end):
            try:
                payloads = await _retry(
                    lambda: client.fetch_activity_payloads(
                        chunk_start,
                        chunk_end,
                        include_details=activity_details and not dry_run,
                        detail_types=detail_types,
                    )
                )
                count = len(payloads.summaries)
                if dry_run:
                    summary.activities_synced += count
                    log_fn(
                        f"  {chunk_start.isoformat()}..{chunk_end.isoformat()}  "
                        f"activities={count}  (dry-run)"
                    )
                else:
                    result = await sync_service.sync_activities(profile.id, payloads, commit=True)
                    summary.activities_synced += result.activities_synced
                    summary.timeseries_synced += result.timeseries_samples_synced
                    log_fn(
                        f"  {chunk_start.isoformat()}..{chunk_end.isoformat()}  "
                        f"activities+{result.activities_synced} "
                        f"samples+{result.timeseries_samples_synced}"
                    )
            except Exception as exc:  # noqa: BLE001 - per-chunk isolation
                summary.errors.append(
                    f"activities {chunk_start.isoformat()}..{chunk_end.isoformat()}: "
                    f"{type(exc).__name__}: {exc}"
                )
                log_fn(
                    f"  {chunk_start.isoformat()}..{chunk_end.isoformat()}  "
                    f"FAILED: {type(exc).__name__}: {exc}"
                )
            if throttle:
                await asyncio.sleep(throttle)

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="ISO start date, e.g. 2025-06-24")
    parser.add_argument("--end", default=None, help="ISO end date (default: today)")
    parser.add_argument("--display-name", default="Mark", help="Private user (default: Mark)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch + report coverage without writing"
    )
    parser.add_argument(
        "--throttle", type=float, default=1.5, help="Seconds to pause between calls (default 1.5)"
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-sync days that already have a daily_metrics row",
    )
    parser.add_argument(
        "--no-activities",
        dest="activities",
        action="store_false",
        help="Skip the activity backfill (daily metrics + sleep only)",
    )
    parser.add_argument(
        "--no-activity-details",
        dest="activity_details",
        action="store_false",
        help="Backfill activity summaries only, not per-second time-series",
    )
    parser.add_argument(
        "--detail-types",
        default=None,
        help=(
            "Comma-separated activityType keys to fetch per-second details for, e.g. "
            "'indoor_cycling,road_biking,cycling,walking'. Default: all types. Summaries are "
            "always backfilled for every type; this only scopes which get the costly "
            "get_activity_details call (and the resulting time-series rows)."
        ),
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()
    if end < start:
        raise SystemExit(f"--end {end} is before --start {start}")

    detail_types = parse_detail_types(args.detail_types)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Profile).where(
                Profile.display_name == args.display_name,
                Profile.deleted_at.is_(None),
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise SystemExit(f"Profile {args.display_name!r} not found")

        scope = "all types" if detail_types is None else ", ".join(sorted(detail_types))
        print(
            f"{'DRY RUN: ' if args.dry_run else ''}backfilling Garmin history for "
            f"{args.display_name!r}: {start.isoformat()} → {end.isoformat()}\n"
            f"activity details: {'off' if not args.activity_details else scope}\n"
        )
        summary = await run_backfill(
            session,
            profile,
            client=GarminConnectClient(),
            start=start,
            end=end,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
            throttle=args.throttle,
            activities=args.activities,
            activity_details=args.activity_details,
            detail_types=detail_types,
        )

    print("\n" + summary.render())


if __name__ == "__main__":
    asyncio.run(_main())
