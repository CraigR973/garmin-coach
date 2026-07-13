"""Background scheduler — APScheduler harness for garmin-coach.

Current jobs:
  - daily_backup: runs at 03:00 UTC
  - hive_temperature_poll: polls Hive indoor temperature every 15 minutes
  - wake_check: every ~15 min within Mark's morning window, does a light
    sleep-only Garmin poll and fires run_morning_sync once his wake is stable
    (back-to-sleep guard) — replaces the old fixed 06:30 cron so the inputs are
    synced whatever time he surfaces
  - morning_backstop: at 09:30 Europe/London, runs run_morning_weather_sync
    regardless, so a verdict is always produced even if he never checks in
  - garmin_activity_poll: polls Garmin hourly and nudges for a post-session check-in
  - post_workout_backstop: at 20:30 local, generates any same-day unread sessions
  - workout_autopush: pushes approved workout proposals due today
  - evening_sleep_nudge: sends the 20:00 sleep-protocol push
  - evening_monitoring_alerts: checks thermal and source freshness before bed
  - fan_control: every ~15 min within the overnight window, reconciles the Dreo
    bedroom fan to the live indoor temperature (Batch 27.2)

The morning splits at its sync → generate seam (Batch 85, DECISIONS #158): the wake
job runs run_morning_sync (pull all inputs + "good morning" nudge, no LLM), the
check-in is the primary generate trigger, and run_morning_weather_sync (full
sync + generate + push) is now the 09:30 backstop for a morning he never engages.
See docs/designs/wake-triggered-morning.md and DECISIONS #87 / #158.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from apscheduler.schedulers.asyncio import (  # type: ignore[import-untyped,unused-ignore]
    AsyncIOScheduler,
)
from sqlalchemy import desc, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.coaching import Activity, Analysis, FanStateReading, TemperatureReading
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import Profile
from src.services.backup import create_backup
from src.services.dreo_fan import (
    DreoCredentials,
    DreoCredentialsError,
    DreoFanClient,
    DreoFanError,
)
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.environment_sync import (
    EnvironmentSyncService,
    HiveClient,
    OpenMeteoClient,
    WeatherRequest,
)
from src.services.executable_coaching import ExecutableCoachingService
from src.services.fan_control import (
    INTERVAL_MIN,
    FanControlResult,
    FanDecision,
    FanState,
    Phase,
    decide_fan_action,
    loop_phase,
)
from src.services.garmin_sync import (
    GarminConnectClient,
    GarminDailyPayloads,
    GarminSyncService,
    parse_sleep_fields,
)
from src.services.holiday_pause import HolidayPauseService
from src.services.insights import InsightsService
from src.services.morning_analysis import MorningAnalysisService
from src.services.nudge_alerts import NudgeAlertService
from src.services.post_flexibility_analysis import PostFlexibilityAnalysisService
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService
from src.services.post_workout_analysis import PostWorkoutAnalysisService
from src.services.wake_detection import (
    BACKSTOP,
    DURATION_FLOOR_MIN,
    SETTLE_MIN,
    WAKE_CHECK_ANALYSIS_TYPE,
    WAKE_CHECK_PROMPT_VERSION,
    WINDOW_END,
    WINDOW_START,
    SleepReading,
    WakeDecision,
    is_morning_ready,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def run_scheduled_backup() -> None:
    """Daily backup job — runs at 03:00 UTC."""
    try:
        info = await create_backup(settings.backup_dir, settings.database_url)
        log.info("scheduled backup complete", filename=info.filename, size_bytes=info.size_bytes)
    except Exception as exc:
        reason = str(exc)
        log.exception("scheduled backup failed")
        async with AsyncSessionLocal() as session:
            session.add(
                AuditLog(
                    actor_id=None,
                    actor_type=ActorType.system,
                    action_type=ActionType.backup_failed,
                    target_table="",
                    target_id=None,
                    changes={"error": reason},
                )
            )
            await session.commit()


async def run_connection_warmup() -> None:
    """Keep a pooled DB connection hot so the first open rarely pays a cold connect.

    Batch 62.4: ``pool_recycle=1800`` recycles a connection idle for 30 min, so the
    first request after a quiet spell re-establishes a Supabase-pooler connection
    (TLS + auth) before it can even start querying. A cheap ``SELECT 1`` every few
    minutes keeps at least one pooled connection alive so Mark's first
    ``GET /api/v1/daily-loop`` usually lands on a warm one.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        log.exception("connection warmup failed")


async def run_hive_temperature_poll() -> None:
    """Poll Hive indoor temperature for active Hive-linked profiles."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = (
                (
                    await session.execute(
                        select(Profile).where(
                            Profile.is_active.is_(True),
                            Profile.deleted_at.is_(None),
                            Profile.hive_home_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not profiles:
                log.info("hive temperature poll skipped", reason="no_hive_profiles")
                return

            client = HiveClient()
            payloads = await _retry_sync(client.fetch_payloads)
            service = EnvironmentSyncService(session)
            poll_started_utc = datetime.now(UTC).replace(tzinfo=None)
            synced = 0
            for profile in profiles:
                result = await service.sync_hive_temperatures(
                    profile.id,
                    payloads,
                    captured_at_utc=poll_started_utc,
                    commit=False,
                )
                synced += result.temperature_readings_synced
            await session.commit()
        log.info("hive temperature poll complete", profiles=len(profiles), readings=synced)
    except Exception:
        log.exception("hive temperature poll failed")


async def run_evening_sleep_nudge() -> None:
    """Send the daily sleep-protocol nudge in each active profile's timezone."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("evening sleep nudge skipped", reason="no_active_profiles")
                return

            service = NudgeAlertService(session)
            holiday_service = HolidayPauseService(session)
            nudges_recorded = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                if (
                    await holiday_service.get_active_window_for_date(profile, subject_date)
                    is not None
                ):
                    log.info(
                        "evening sleep nudge skipped",
                        reason="holiday_away",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
                    continue
                if await service.run_evening_nudge(profile, commit=False):
                    nudges_recorded += 1
            await session.commit()
        log.info("evening sleep nudge complete", profiles=len(profiles), nudges=nudges_recorded)
    except Exception:
        log.exception("evening sleep nudge failed")


async def run_evening_monitoring_alerts() -> None:
    """Check bedtime thermal state and source freshness for active profiles."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("evening monitoring alerts skipped", reason="no_active_profiles")
                return

            service = NudgeAlertService(session)
            holiday_service = HolidayPauseService(session)
            alerts_recorded = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                holiday_away = (
                    await holiday_service.get_active_window_for_date(profile, subject_date)
                    is not None
                )
                if holiday_away:
                    log.info(
                        "evening thermal monitoring skipped",
                        reason="holiday_away",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
                alerts_recorded += await service.run_monitoring_alerts(
                    profile,
                    commit=False,
                    include_thermal=not holiday_away,
                )
            await session.commit()
        log.info(
            "evening monitoring alerts complete",
            profiles=len(profiles),
            alerts=alerts_recorded,
        )
    except Exception:
        log.exception("evening monitoring alerts failed")


async def _sync_garmin_daily(
    session: AsyncSession,
    profiles: list[Profile],
    *,
    client: GarminConnectClient | None = None,
) -> tuple[int, int]:
    """Sync today's Garmin daily metrics + sleep for each profile (429-safe).

    Returns ``(daily_metrics_synced, sleep_synced)``. The fetch is wrapped in an
    exponential-backoff retry so a transient Garmin 429 is survived, and each
    profile's sync is isolated: one profile's Garmin failure is logged and
    skipped so it cannot block the others or the downstream morning analysis.
    The caller commits.
    """
    if not profiles:
        return (0, 0)

    client = client or GarminConnectClient()
    sync_service = GarminSyncService(session)
    daily_synced = 0
    sleep_synced = 0
    for profile in profiles:
        subject_date = _profile_today(profile)
        try:
            payloads: GarminDailyPayloads = await _retry_sync(
                lambda: client.fetch_daily_payloads(subject_date),
                backoff=2.0,
            )
            result = await sync_service.sync_daily(
                profile.id,
                subject_date,
                payloads,
                commit=False,
            )
            daily_synced += result.daily_metrics_synced
            sleep_synced += result.sleep_synced
        except Exception:
            log.exception(
                "garmin daily sync failed",
                profile_id=str(profile.id),
                subject_date=subject_date.isoformat(),
            )
    return (daily_synced, sleep_synced)


async def _sync_morning_inputs(
    session: AsyncSession, profiles: list[Profile]
) -> tuple[int, int, int]:
    """Pull weather + today's Garmin daily metrics/sleep for the given profiles.

    Returns ``(weather_days, daily_metrics, sleep)``. Weather syncs first, then the
    Garmin daily sync, so the morning verdict reads today's real readiness + sleep
    instead of empty inputs (Batch 18). The caller commits any final work; this
    helper commits the two sync phases as it goes.
    """
    service = EnvironmentSyncService(session)
    weather_days = 0
    client = OpenMeteoClient()
    for profile in profiles:
        request = WeatherRequest(
            latitude=profile.latitude or settings.weather_latitude,
            longitude=profile.longitude or settings.weather_longitude,
            timezone=profile.timezone or settings.weather_timezone,
        )
        payload = await _retry_async(lambda: client.fetch_daily_payload(request))
        result = await service.sync_weather_daily(
            profile.id,
            payload,
            timezone=request.timezone,
            commit=False,
        )
        weather_days += result.weather_days_synced
    await session.commit()

    daily_metrics_synced, sleep_synced = await _sync_garmin_daily(session, profiles)
    await session.commit()
    return weather_days, daily_metrics_synced, sleep_synced


async def run_morning_sync() -> None:
    """Wake-triggered morning **sync + nudge** (Batch 85).

    Pulls all external inputs (weather + today's Garmin daily metrics/sleep; Hive
    indoor temp already streams from its own poll) into Postgres so they are sitting
    ready before Mark is up, then fires the "good morning" nudge inviting him to
    check in. Generation has moved *off* the wake trigger onto his check-in (the
    primary trigger) and the 09:30 backstop (fallback), so by the time he taps the
    data is already synced and the brief generates fast. Idempotent: the nudge is
    one-per-day and is skipped once today's brief already exists (he checked in, or
    the backstop generated it).
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("morning sync skipped", reason="no_active_profiles")
                return
            weather_days, daily_metrics_synced, sleep_synced = await _sync_morning_inputs(
                session, profiles
            )

            morning = MorningAnalysisService(session)
            nudge_service = NudgeAlertService(session)
            nudges_sent = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                # No point inviting a check-in once today's read is already done
                # (he checked in, or the backstop generated it) — cheap DB read.
                if await morning.latest_analysis(profile.id, subject_date) is not None:
                    continue
                try:
                    if await nudge_service.push_good_morning(
                        profile, subject_date=subject_date, commit=False
                    ):
                        nudges_sent += 1
                except Exception:
                    log.exception(
                        "good morning nudge failed",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
            await session.commit()
        log.info(
            "morning sync complete",
            profiles=len(profiles),
            days=weather_days,
            daily_metrics=daily_metrics_synced,
            sleep=sleep_synced,
            nudges_sent=nudges_sent,
        )
    except Exception:
        log.exception("morning sync failed")


async def run_morning_weather_sync() -> None:
    """Full morning pipeline: sync inputs, then generate + push the verdict.

    This is the **09:30 backstop** (and the external-cron ``morning-sync`` entry) —
    it guarantees a verdict even for a morning Mark never engaged with. On the
    primary path generation is triggered by his check-in and the wake job runs the
    lighter run_morning_sync (sync + nudge) instead (Batch 85). Idempotent per
    profile: generate_and_store and push_morning_verdict short-circuit if the brief
    / push already happened via the check-in.
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            synced, daily_metrics_synced, sleep_synced = await _sync_morning_inputs(
                session, profiles
            )
            analyses_generated = 0
            analyses_existing = 0

            analysis_service = MorningAnalysisService(session)
            coaching_service = ExecutableCoachingService(session)
            nudge_service = NudgeAlertService(session)
            insights_service = InsightsService(session)
            proposals_regenerated = 0
            verdict_pushes = 0
            drivers_cached = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                try:
                    analysis_result = await analysis_service.generate_and_store(
                        profile,
                        subject_date,
                    )
                    if analysis_result.generated:
                        analyses_generated += 1
                    else:
                        analyses_existing += 1
                except Exception:
                    log.exception(
                        "morning analysis failed",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
                    continue
                if analysis_result.generated:
                    # Batch 45: push the verdict the moment it lands. Wrapped so a
                    # push failure never blocks the Amber regeneration below.
                    try:
                        if await nudge_service.push_morning_verdict(
                            profile,
                            analysis_result.analysis,
                            subject_date=subject_date,
                        ):
                            verdict_pushes += 1
                    except Exception:
                        log.exception(
                            "morning verdict push failed",
                            profile_id=str(profile.id),
                            subject_date=subject_date.isoformat(),
                        )
                try:
                    proposals = await coaching_service.regenerate_for_verdict(
                        profile,
                        subject_date,
                        analysis=analysis_result.analysis,
                    )
                    proposals_regenerated += len(proposals)
                except Exception:
                    log.exception(
                        "amber regeneration failed",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
                # Batch 62.2: precompute the 120-day driver correlation once here so
                # GET /api/v1/daily-loop reads it back instead of recomputing on
                # every open. Wrapped so a failure never blocks the morning pipeline.
                try:
                    report = await insights_service.record_drivers(
                        profile,
                        as_of=subject_date,
                        commit=True,
                    )
                    if report.record_count >= 1:
                        drivers_cached += 1
                except Exception:
                    log.exception(
                        "drivers precompute failed",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
        log.info(
            "morning weather sync complete",
            profiles=len(profiles),
            days=synced,
            daily_metrics=daily_metrics_synced,
            sleep=sleep_synced,
            analyses_generated=analyses_generated,
            analyses_existing=analyses_existing,
            proposals_regenerated=proposals_regenerated,
            verdict_pushes=verdict_pushes,
            drivers_cached=drivers_cached,
        )
    except Exception:
        log.exception("morning weather sync failed")


async def run_wake_check() -> None:
    """Poll Garmin sleep and fire the morning verdict once Mark has actually woken.

    Replaces the fixed 06:30 cron. Per active profile, within the morning window
    (Europe/London local), it: (1) short-circuits if today's morning analysis
    already exists; (2) does a light sleep-only Garmin poll; (3) applies the
    back-to-sleep stability guard against the previously persisted ``sleepEnd``
    (services/wake_detection.is_morning_ready); (4) persists the current
    ``sleepEnd`` as a ``wake_check`` audit row for the next poll's comparison. If
    any profile is ready (stable wake, or the ~09:30 backstop) it runs the
    unchanged run_morning_weather_sync once — which is idempotent per profile, so
    re-firing on later polls is harmless.
    """
    try:
        any_ready = False
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("wake check skipped", reason="no_active_profiles")
                return

            morning = MorningAnalysisService(session)
            client: GarminConnectClient | None = None
            fired = 0
            waiting = 0
            napped = 0
            for profile in profiles:
                now_local = _profile_now(profile)
                # Cheap window gate first — no Garmin call outside the window.
                if not (WINDOW_START <= now_local.time() <= WINDOW_END):
                    continue
                today = now_local.date()
                # Short-circuit once today's morning verdict exists (cheap DB read,
                # no Garmin call) — this stops polling for the rest of the day.
                if await morning.latest_analysis(profile.id, today) is not None:
                    continue
                if client is None:
                    client = GarminConnectClient()
                bound_client = client
                try:
                    sleep_payload = await _retry_sync(
                        lambda: bound_client.fetch_sleep(today),
                        backoff=2.0,
                    )
                except Exception:
                    log.exception("wake check sleep fetch failed", profile_id=str(profile.id))
                    continue

                sleep = SleepReading.from_sleep_fields(parse_sleep_fields(sleep_payload))
                prev_sleep_end = await _last_seen_sleep_end(session, profile.id, today)
                decision = is_morning_ready(
                    today=today,
                    sleep=sleep,
                    prev_sleep_end=prev_sleep_end,
                    now=now_local,
                    backstop=BACKSTOP,
                    duration_floor_min=DURATION_FLOOR_MIN,
                    settle_min=SETTLE_MIN,
                )
                await _record_wake_check(session, profile.id, today, decision)
                if decision.action == "fire":
                    fired += 1
                    any_ready = True
                elif decision.action == "nap_ignored":
                    napped += 1
                else:
                    waiting += 1
            await session.commit()
        log.info(
            "wake check complete",
            profiles=len(profiles),
            fired=fired,
            waiting=waiting,
            napped=napped,
        )
        # Once wake is stable, sync all inputs and fire the "good morning" nudge —
        # generation itself waits for his check-in (Batch 85). Runs on its own
        # session after the last-seen state is committed; idempotent per profile.
        if any_ready:
            await run_morning_sync()
    except Exception:
        log.exception("wake check failed")


async def run_garmin_activity_poll() -> None:
    """Poll Garmin for activities, then invite check-ins without running an LLM."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = (
                (
                    await session.execute(
                        select(Profile).where(
                            Profile.is_active.is_(True),
                            Profile.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not profiles:
                log.info("garmin activity poll skipped", reason="no_active_profiles")
                return

            client = GarminConnectClient()
            sync_service = GarminSyncService(session)
            analysis_service = PostWorkoutAnalysisService(session)
            flexibility_service = PostFlexibilityAnalysisService(session)
            strength_service = PostStrengthAnalysisService(session)
            walk_service = PostWalkAnalysisService(session)
            nudge_service = NudgeAlertService(session)
            activities_synced = 0
            timeseries_synced = 0
            checkin_nudges = 0

            for profile in profiles:
                today = _profile_today(profile)
                start_date = today - timedelta(days=3)
                payloads = await _retry_sync(
                    lambda: client.fetch_activity_payloads(start_date, today)
                )
                sync_result = await sync_service.sync_activities(
                    profile.id,
                    payloads,
                    commit=False,
                )
                activities_synced += sync_result.activities_synced
                timeseries_synced += sync_result.timeseries_samples_synced

                since = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=None)
                # Batch 87: identify all four supported post-session types, but
                # stop at the sync -> nudge seam. Generation waits for check-in.
                candidates = [
                    (
                        "ride",
                        await analysis_service.pending_ride_activities(profile.id, since=since),
                    ),
                    (
                        "flexibility",
                        await flexibility_service.pending_flexibility_activities(
                            profile.id, since=since
                        ),
                    ),
                    (
                        "strength",
                        await strength_service.pending_strength_activities(profile.id, since=since),
                    ),
                    ("walk", await walk_service.pending_walk_activities(profile.id, since=since)),
                ]
                checkin_nudges += await _push_pending_checkins(
                    session, nudge_service, profile, candidates
                )

            await session.commit()
        log.info(
            "garmin activity poll complete",
            profiles=len(profiles),
            activities=activities_synced,
            timeseries_samples=timeseries_synced,
            checkin_nudges=checkin_nudges,
        )
    except Exception:
        log.exception("garmin activity poll failed")


async def _push_pending_checkins(
    session: AsyncSession,
    nudge_service: NudgeAlertService,
    profile: Profile,
    candidates: Iterable[tuple[str, Iterable[Activity]]],
) -> int:
    """Nudge only truly unread activities; prompt-version staleness is not new work."""

    grouped = [(kind, activity) for kind, rows in candidates for activity in rows]
    if not grouped:
        return 0
    activity_ids = [activity.id for _, activity in grouped]
    analysed_ids = set(
        (
            await session.execute(
                select(Analysis.activity_id).where(Analysis.activity_id.in_(activity_ids))
            )
        )
        .scalars()
        .all()
    )
    pushed = 0
    for kind, activity in grouped:
        if activity.id in analysed_ids:
            continue
        subject_date = (
            activity.start_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(profile.timezone)).date()
        )
        if await nudge_service.push_workout_checkin(
            profile,
            activity,
            kind=kind,
            subject_date=subject_date,
            commit=False,
        ):
            pushed += 1
    return pushed


async def _push_new_analyses(
    nudge_service: NudgeAlertService,
    profile: Profile,
    results: Iterable[Any],
    *,
    kind: str,
) -> int:
    """Push one notification per newly generated post-workout analysis (Batch 45).

    Each push is wrapped so a failure never blocks the activity poll; the
    ``analysis-{activity_id}`` tag keeps it idempotent and the audit row lands in
    the poll's trailing commit. An existing analysis (``generated`` is ``False``,
    e.g. regenerated on a newer check-in / prompt bump) never re-pushes.
    """
    pushed = 0
    for item in results:
        if not item.generated:
            continue
        try:
            if await nudge_service.push_workout_analysis(
                profile, item.analysis, kind=kind, commit=False
            ):
                pushed += 1
        except Exception:
            log.exception(
                "post-workout push failed",
                profile_id=str(profile.id),
                kind=kind,
            )
    return pushed


async def run_post_workout_backstop() -> None:
    """Generate still-unread same-day sessions before tomorrow's morning packet."""

    try:
        async with AsyncSessionLocal() as session:
            profiles = (
                (
                    await session.execute(
                        select(Profile).where(
                            Profile.is_active.is_(True), Profile.deleted_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            generated = 0
            pushes = 0
            for profile in profiles:
                local_midnight = datetime.combine(
                    _profile_today(profile), datetime.min.time(), tzinfo=ZoneInfo(profile.timezone)
                )
                since = local_midnight.astimezone(UTC).replace(tzinfo=None)
                readers = (
                    (
                        "ride",
                        PostWorkoutAnalysisService(session).generate_for_pending_rides,
                    ),
                    (
                        "flexibility",
                        PostFlexibilityAnalysisService(session).generate_for_pending_flexibility,
                    ),
                    (
                        "strength",
                        PostStrengthAnalysisService(session).generate_for_pending_strength,
                    ),
                    ("walk", PostWalkAnalysisService(session).generate_for_pending_walks),
                )
                for kind, reader in readers:
                    try:
                        results = await reader(profile, since=since, commit=False)
                        generated += sum(1 for item in results if item.generated)
                        pushes += await _push_new_analyses(
                            NudgeAlertService(session), profile, results, kind=kind
                        )
                    except Exception:
                        log.exception(
                            "post-workout backstop reader failed",
                            profile_id=str(profile.id),
                            kind=kind,
                        )
            await session.commit()
        log.info(
            "post-workout backstop complete",
            profiles=len(profiles),
            analyses_generated=generated,
            analysis_pushes=pushes,
        )
    except Exception:
        log.exception("post-workout backstop failed")


async def run_workout_autopush() -> None:
    """Push approved-but-unpushed workout proposals due today.

    Only proposals the user already approved are eligible (Decision #29), so this
    delivers the week-ahead automatically (Decision #31) without ever pushing
    something unapproved. Each profile and each push is isolated so one failure
    (e.g. a missing intervals.icu key) cannot block the rest.
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("workout autopush skipped", reason="no_active_profiles")
                return

            service = ExecutableCoachingService(session)
            pushed = 0
            for profile in profiles:
                try:
                    results = await service.auto_push_due(profile)
                    pushed += len(results)
                except Exception:
                    log.exception(
                        "workout autopush failed for profile",
                        profile_id=str(profile.id),
                    )
        log.info("workout autopush complete", profiles=len(profiles), pushed=pushed)
    except Exception:
        log.exception("workout autopush failed")


async def _active_profiles(session: AsyncSession) -> list[Profile]:
    return list(
        (
            await session.execute(
                select(Profile).where(
                    Profile.is_active.is_(True),
                    Profile.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )


def _profile_zone(profile: Profile) -> ZoneInfo:
    try:
        return ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _profile_now(profile: Profile) -> datetime:
    """Timezone-aware 'now' in the profile's local zone (the wake-check clock)."""
    return datetime.now(_profile_zone(profile))


def _profile_today(profile: Profile) -> date:
    return _profile_now(profile).date()


async def _last_seen_sleep_end(
    session: AsyncSession,
    user_id: uuid.UUID,
    subject_date: date,
) -> datetime | None:
    """The ``sleepEnd`` persisted by the most recent wake_check poll for today."""
    row = await session.scalar(
        select(Analysis)
        .where(
            Analysis.user_id == user_id,
            Analysis.analysis_type == WAKE_CHECK_ANALYSIS_TYPE,
            Analysis.subject_date == subject_date,
        )
        .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
        .limit(1)
    )
    if row is None:
        return None
    raw = row.context_packet.get("sleepEndUtc")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def _record_wake_check(
    session: AsyncSession,
    user_id: uuid.UUID,
    subject_date: date,
    decision: WakeDecision,
) -> None:
    """Upsert the single wake_check audit row per (user, day) — migration-free state.

    Stores the sleepEnd to compare on the next poll and the decision for audit.
    One row per day (updated in place) rather than ~26 inserts.
    """
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    sleep_end = decision.sleep_end_to_persist
    context = {
        "subjectDate": subject_date.isoformat(),
        "action": decision.action,
        "reason": decision.reason,
        "sleepEndUtc": sleep_end.isoformat() if sleep_end is not None else None,
        "checkedAtUtc": now_utc.isoformat(),
    }
    existing = await session.scalar(
        select(Analysis)
        .where(
            Analysis.user_id == user_id,
            Analysis.analysis_type == WAKE_CHECK_ANALYSIS_TYPE,
            Analysis.subject_date == subject_date,
        )
        .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
        .limit(1)
    )
    if existing is not None:
        existing.generated_at_utc = now_utc
        existing.verdict = decision.action
        existing.context_packet = context
        existing.output_markdown = decision.reason
        return
    session.add(
        Analysis(
            user_id=user_id,
            activity_id=None,
            analysis_type=WAKE_CHECK_ANALYSIS_TYPE,
            subject_date=subject_date,
            generated_at_utc=now_utc,
            prompt_version=WAKE_CHECK_PROMPT_VERSION,
            model_name=None,
            verdict=decision.action,
            context_packet=context,
            output_markdown=decision.reason,
            raw_response={},
        )
    )


async def _retry_sync[T](
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
    backoff: float = 1.0,
) -> T:
    """Retry a sync operation, sleeping ``delay_sec`` (× ``backoff`` each retry).

    ``backoff > 1.0`` gives exponential backoff, which keeps the Garmin daily
    sync 429-safe without hammering the API on the rate-limit window.
    """
    delay = delay_sec
    for attempt in range(attempts):
        try:
            return operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= backoff
    raise RuntimeError("retry loop exited unexpectedly")


async def _retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
) -> T:
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay_sec)
    raise RuntimeError("retry loop exited unexpectedly")


# -- Bedroom fan control (Batch 27.2) ----------------------------------------


def _fan_control_configured() -> bool:
    try:
        DreoCredentials.from_settings().validate()
        return True
    except DreoCredentialsError:
        return False


def _fresh_temperature_c(reading: TemperatureReading | None, now_local: datetime) -> float | None:
    """The latest indoor temperature in C if it is fresh (<=45 min old), else None."""
    if reading is None:
        return None
    if not is_hive_temperature_fresh(reading.captured_at_utc, now_utc=now_local.astimezone(UTC)):
        return None
    return round(float(reading.temperature_c), 1)


async def _latest_temperature(
    session: AsyncSession, user_id: uuid.UUID
) -> TemperatureReading | None:
    result = await session.execute(
        select(TemperatureReading)
        .where(TemperatureReading.user_id == user_id)
        .order_by(desc(TemperatureReading.captured_at_utc))
        .limit(1)
    )
    return result.scalars().first()


async def run_fan_control() -> None:
    """Overnight airflow autopilot: reconcile the Dreo fan to the live bedroom temp.

    Within the overnight window (``services/fan_control.loop_phase``) it maps the
    freshest Hive indoor temperature onto a bounded fan target — off, or on at a
    ladder speed — using the Batch 9 sleep-disruption thresholds, and applies only
    the difference from the fan's current state, so the loop is idempotent. A short
    wind-down after the window guarantees the fan is off by morning. It degrades
    gracefully (logs, never raises) when no fan is configured or the cloud is
    unreachable. Single fan / single bedroom (Mark) — see DECISIONS #96.

    Batch 31: every *within-window* fire also persists one ``fan_state_readings``
    tick — including the early-return branches (``auto_off`` when the autopilot is
    off, ``no_data`` / ``unreachable`` when there is no temp / the cloud is down) —
    so the bedroom chart can explain gaps rather than going blank. The fan
    **decision** logic and thresholds are unchanged; this only adds a write.
    """
    try:
        if not _fan_control_configured():
            log.info("fan control skipped", reason="no_dreo_credentials")
            return
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("fan control skipped", reason="no_active_profiles")
                return
            profile = profiles[0]
            now_local = _profile_now(profile)
            phase = loop_phase(now_local.time())
            if phase == "idle":
                # Daytime: a true no-op — no cloud call, and not charted.
                return
            subject_date = now_local.date()
            if (
                await HolidayPauseService(session).get_active_window_for_date(profile, subject_date)
                is not None
            ):
                # Holiday means Mark is away: leave the whole subsystem dormant.
                # Do not touch Dreo and do not manufacture an overnight chart tick.
                log.info(
                    "fan control skipped",
                    reason="holiday_away",
                    profile_id=str(profile.id),
                    subject_date=subject_date.isoformat(),
                )
                return
            captured_at = _floor_to_interval(datetime.now(UTC).replace(tzinfo=None))
            profile_id = profile.id
            if not profile.fan_auto_enabled:
                # Within the window but manual control: never touch the cloud, but
                # record the tick so the chart shows "autopilot off", not a gap.
                log.info("fan control skipped", reason="auto_disabled")
                await _record_fan_state(
                    session,
                    profile_id,
                    captured_at,
                    phase,
                    auto_enabled=False,
                    result=FanControlResult(
                        action="auto_off",
                        observed_temp_c=None,
                        fan_on=None,
                        fan_speed=None,
                        reason="autopilot off",
                    ),
                )
                await session.commit()
                return
            reading = await _latest_temperature(session, profile_id)
            temperature_c = _fresh_temperature_c(reading, now_local)
        # Cloud I/O happens outside the DB session.
        result = await _apply_fan_control(phase, temperature_c)
        # Persist one tick in a fresh session (best-effort: a write failure is
        # caught below and never reaches the fan, which has already acted).
        async with AsyncSessionLocal() as session:
            await _record_fan_state(
                session, profile_id, captured_at, phase, auto_enabled=True, result=result
            )
            await session.commit()
    except Exception:
        log.exception("fan control failed")


async def _apply_fan_control(phase: Phase, temperature_c: float | None) -> FanControlResult:
    """Reconcile the fan and return the outcome for persistence (Batch 31).

    The decision logic is unchanged from Batch 27 — only the return value is new.
    """
    client = DreoFanClient()
    try:
        await asyncio.to_thread(client.connect)
    except DreoFanError as exc:
        log.warning("fan control unreachable", phase=phase, error=str(exc))
        return FanControlResult(
            action="unreachable",
            observed_temp_c=temperature_c,
            fan_on=None,
            fan_speed=None,
            reason="cloud unreachable",
        )
    try:
        state = await asyncio.to_thread(client.read_state)
        current = FanState(is_on=bool(state.is_on), fan_speed=state.fan_speed)
        decision = decide_fan_action(phase=phase, temperature_c=temperature_c, fan_state=current)
        if decision.action == "apply":
            await _execute_fan_decision(client, current, decision)
        log.info(
            "fan control",
            phase=phase,
            temperature_c=temperature_c,
            action=decision.action,
            target_on=decision.target_on,
            target_speed=decision.target_speed,
            reason=decision.reason,
        )
        # Persisted action labels the morning shut-off "winddown" as its own chart
        # state; the effective fan state after the tick is the reconciled target.
        action = "winddown" if phase == "winddown" else decision.action
        return FanControlResult(
            action=action,
            observed_temp_c=temperature_c,
            fan_on=decision.target_on,
            fan_speed=decision.target_speed,
            reason=decision.reason,
        )
    except DreoFanError as exc:
        log.warning("fan control command failed", phase=phase, error=str(exc))
        return FanControlResult(
            action="unreachable",
            observed_temp_c=temperature_c,
            fan_on=None,
            fan_speed=None,
            reason="command failed",
        )
    finally:
        await asyncio.to_thread(client.close)


def _floor_to_interval(moment: datetime, *, minutes: int = INTERVAL_MIN) -> datetime:
    """Floor a UTC-naive timestamp to the loop interval, dropping sub-second parts.

    Quantising the tick timestamp to the 15-min slot makes the unique
    ``(user_id, captured_at_utc)`` key stable, so a coalesced double-fire upserts
    to one row instead of two.
    """
    discard = (moment.minute % minutes) * 60 + moment.second
    return (moment - timedelta(seconds=discard)).replace(microsecond=0)


async def _record_fan_state(
    session: AsyncSession,
    user_id: uuid.UUID,
    captured_at: datetime,
    phase: Phase,
    *,
    auto_enabled: bool,
    result: FanControlResult,
) -> None:
    """Upsert one fan-control tick, idempotent on ``(user_id, captured_at_utc)``."""
    await session.execute(
        pg_insert(FanStateReading)
        .values(
            user_id=user_id,
            captured_at_utc=captured_at,
            phase=phase,
            auto_enabled=auto_enabled,
            observed_temp_c=result.observed_temp_c,
            fan_on=result.fan_on,
            fan_speed=result.fan_speed,
            action=result.action,
            reason=result.reason,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "captured_at_utc"])
    )


async def _execute_fan_decision(
    client: DreoFanClient, current: FanState, decision: FanDecision
) -> None:
    if not decision.target_on:
        await asyncio.to_thread(client.power, False)
        return
    if not current.is_on:
        await asyncio.to_thread(client.power, True)
    if decision.target_speed is not None and current.fan_speed != decision.target_speed:
        await asyncio.to_thread(client.set_speed, decision.target_speed)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        # Batch 62.4: cheap SELECT 1 well inside the 30-min pool_recycle window so a
        # pooled connection is usually hot when Mark opens the app.
        run_connection_warmup,
        trigger="interval",
        minutes=10,
        id="connection_warmup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(UTC) + timedelta(seconds=30),
    )
    scheduler.add_job(
        run_scheduled_backup,
        trigger="cron",
        hour=3,
        minute=0,
        id="daily_backup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_hive_temperature_poll,
        trigger="interval",
        minutes=15,
        id="hive_temperature_poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        # Seed an early first run so a freshly (re)started container polls Hive
        # within ~2 min instead of waiting a full 15-minute interval. The web
        # container is not guaranteed to stay up long enough to reach the first
        # *unseeded* interval fire, which is why the live feed stalled (only
        # manual readings). See docs/runbooks/scheduled-jobs-cron.md.
        next_run_time=datetime.now(UTC) + timedelta(minutes=2),
    )
    scheduler.add_job(
        run_wake_check,
        trigger="interval",
        minutes=15,
        id="wake_check",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        # Seed an early first run so a freshly (re)started container starts
        # polling for Mark's wake within ~3 min instead of up to a full interval
        # (mirrors the Hive/activity polls; see docs/runbooks/scheduled-jobs-cron.md).
        next_run_time=datetime.now(UTC) + timedelta(minutes=3),
    )
    scheduler.add_job(
        # Belt-and-suspenders backstop: even if wake was never detected (watch not
        # worn / container down through the window), guarantee a verdict by 09:30.
        # run_morning_weather_sync is idempotent per profile, so this no-ops if the
        # wake trigger already fired. In-process APScheduler handles BST/GMT.
        run_morning_weather_sync,
        trigger="cron",
        hour=9,
        minute=30,
        timezone=settings.weather_timezone,
        id="morning_backstop",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_garmin_activity_poll,
        trigger="interval",
        hours=1,
        id="garmin_activity_poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(UTC) + timedelta(minutes=5),
    )
    scheduler.add_job(
        run_post_workout_backstop,
        trigger="cron",
        hour=20,
        minute=30,
        timezone=settings.weather_timezone,
        id="post_workout_backstop",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_workout_autopush,
        trigger="cron",
        hour="7,13,19",
        minute=0,
        timezone=settings.weather_timezone,
        id="workout_autopush",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_evening_sleep_nudge,
        trigger="cron",
        hour=20,
        minute=0,
        timezone=settings.weather_timezone,
        id="evening_sleep_nudge",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_evening_monitoring_alerts,
        trigger="cron",
        hour="19-22",
        minute="0,15,30,45",
        timezone=settings.weather_timezone,
        id="evening_monitoring_alerts",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_fan_control,
        trigger="interval",
        minutes=INTERVAL_MIN,
        id="fan_control",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        # Seed an early first run so a freshly (re)started container reconciles the
        # fan within ~4 min instead of waiting a full interval (mirrors the other
        # interval jobs). A cheap no-op outside the overnight window.
        next_run_time=datetime.now(UTC) + timedelta(minutes=4),
    )
    return scheduler
