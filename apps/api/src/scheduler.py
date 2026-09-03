"""Background scheduler — APScheduler harness for garmin-coach.

Current jobs:
  - daily_backup: runs at 03:00 UTC
  - metric_baseline_refresh: at 02:30 Europe/London, recomputes every active
    profile's personal metric baselines from stored history (Batch 228) — before
    it existed nothing refreshed them at all, and they drifted up to 46 days
  - hive_temperature_poll: polls Hive indoor temperature every 15 minutes
  - wake_check: every ~15 min within Mark's morning window, does a light
    sleep-only Garmin poll and fires run_wake_nudge once his wake is stable
    (back-to-sleep guard) — replaces the old fixed 06:30 cron so the inputs are
    synced whatever time he surfaces
  - morning_backstop: at 11:00 Europe/London, runs run_morning_weather_sync
    regardless, so a verdict is always produced even if he never checks in
  - garmin_activity_poll: polls Garmin hourly and nudges for a post-session check-in
  - post_workout_backstop: at 20:30 local, generates any same-day unread sessions
  - workout_autopush: pushes approved workout proposals due today
  - weekly_review_delivery: Sunday 18:00 local, writes the week into the coach thread
  - state_change_coach: late morning local, writes one meaningful transition into the coach thread
  - longitudinal_analysis: daily collector plus idempotent monthly whole-history submission
  - evening_sleep_nudge: sends a quiet, projection-backed 20:00 sleep push
  - evening_monitoring_alerts: checks thermal and source freshness before bed
  - fan_control: every ~15 min within the overnight window, reconciles the Dreo
    bedroom fan to the live indoor temperature (Batch 27.2)
  - egress_budget: every ~15 min, flushes the response-byte counter and stages
    an operator alert against the shared Supabase egress cap (Batch 204,
    DS190-07) — a leading-indicator proxy, not the real provider meter

The morning splits at its sync → generate seam (Batch 85, DECISIONS #158): the wake
job runs run_wake_nudge (pull all inputs + "good morning" nudge, no LLM), the
check-in is the primary generate trigger, and run_morning_weather_sync (full
sync + generate + push) is now the 11:00 backstop for a morning he never engages.
See docs/designs/wake-triggered-morning.md and DECISIONS #87 / #158.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import (  # type: ignore[import-untyped,unused-ignore]
    AsyncIOScheduler,
)
from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.coaching import (
    Activity,
    Analysis,
    FanStateReading,
    MetricBaseline,
    Sleep,
    TemperatureReading,
)
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.operations import JobRun
from src.models.profile import Profile
from src.services.activity_timeseries_retention import (
    RETENTION_DAYS,
    purge_expired_timeseries,
)
from src.services.anthropic_text import AnthropicApiError
from src.services.backup import create_backup, latest_backup, restore_latest_backup
from src.services.dreo_fan import (
    DreoCredentials,
    DreoCredentialsError,
    DreoFanClient,
    DreoFanError,
)
from src.services.egress_budget import (
    BUDGET_BYTES as EGRESS_BUDGET_BYTES,
)
from src.services.egress_budget import (
    STAGE_ORDINAL as EGRESS_STAGE_ORDINAL,
)
from src.services.egress_budget import (
    STORAGE_BUDGET_BYTES,
    evaluate_storage_stage,
    response_byte_counter,
)
from src.services.egress_budget import (
    evaluate_stage as evaluate_egress_stage,
)
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.environment_sync import (
    EnvironmentSyncService,
    HiveClient,
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
    GarminSyncService,
    parse_sleep_fields,
)
from src.services.generation_requests import GenerationRequestInProgress
from src.services.holiday_pause import HolidayPauseService
from src.services.job_runs import JobResult, run_tracked_job
from src.services.longitudinal_analysis import (
    BillingAlertNotReady,
    LongitudinalAnalysisService,
)
from src.services.metric_baselines import (
    BASELINE_STALENESS_LIMIT_DAYS,
    DB_HISTORY_SOURCE,
    MetricBaselineBackfillService,
    unincorporated_nights,
)
from src.services.morning_inputs import morning_input_presence
from src.services.morning_pipeline import (
    BACKSTOP_POLICY,
    MorningBriefPipeline,
)
from src.services.morning_pipeline import (
    commit_step as _commit_morning_step,
)
from src.services.nudge_alerts import NudgeAlertService
from src.services.post_flexibility_analysis import PostFlexibilityAnalysisService
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService
from src.services.post_workout_analysis import PostWorkoutAnalysisService
from src.services.profile_clock import (
    profile_now as _profile_now,
)
from src.services.profile_clock import (
    profile_today as _profile_today,
)
from src.services.retry import retry_sync as _retry_sync
from src.services.session_recovery import restore_after_rollback as _restore_after_rollback
from src.services.state_change_coach import StateChangeCoachService
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
from src.services.weekly_review_delivery import WeeklyReviewDeliveryService
from src.services.workout_delivery import WorkoutDeliveryService

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def run_scheduled_backup() -> JobResult:
    """Daily backup job — runs at 03:00 UTC."""
    try:
        info = await create_backup(settings.backup_dir, settings.database_url)
        log.info("scheduled backup complete", filename=info.filename, size_bytes=info.size_bytes)
        return JobResult.succeeded(backups=1, size_bytes=info.size_bytes)
    except Exception as exc:
        reason = str(exc)
        log.exception("scheduled backup failed")
        _log_backup_operator_alert("backup_failed", reason)
        audit_rows = 0
        try:
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
                audit_rows = 1
        except Exception:
            log.exception("recording scheduled backup failure audit failed")
        return JobResult.failed("backup_failed", backups=0, audit_rows=audit_rows)


async def run_longitudinal_analysis() -> JobResult:
    """Collect completed batches, then submit at most one run per user/month."""

    counters = {
        "profiles": 0,
        "submitted": 0,
        "pending": 0,
        "completed": 0,
        "findings_routed": 0,
    }
    skipped_alert_gate = 0
    failures = 0
    async with AsyncSessionLocal() as session:
        profiles = list(
            (
                await session.execute(
                    select(Profile).where(
                        Profile.is_active.is_(True),
                        Profile.deleted_at.is_(None),
                        select(Sleep.id).where(Sleep.user_id == Profile.id).exists(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not profiles:
            return JobResult.skipped("no_active_profiles")
        for player in profiles:
            # Rollback expires ORM attributes even though the session factory
            # uses expire_on_commit=False. Snapshot the scalar context before
            # the try block so failure logging/alerting never performs implicit
            # async IO outside greenlet_spawn.
            player_id = player.id
            subject_date = datetime.now(ZoneInfo(player.timezone or "UTC")).date()
            counters["profiles"] += 1
            service = LongitudinalAnalysisService(session)
            try:
                collected = await service.collect_pending(player)
                counters["pending"] += collected.pending
                counters["completed"] += collected.completed
                counters["findings_routed"] += collected.findings_routed
                submitted = await service.submit_monthly(
                    player,
                    as_of_date=subject_date,
                )
                counters["submitted"] += int(submitted.submitted)
            except BillingAlertNotReady as exc:
                await session.rollback()
                skipped_alert_gate += 1
                log.warning(
                    "longitudinal analysis submission gated",
                    user_id=str(player_id),
                    reason=exc.reason,
                )
            except AnthropicApiError as exc:
                await session.rollback()
                failures += 1
                await NudgeAlertService(session).notify_admin_generation_failure(
                    reason=exc.reason,
                    subject_date=subject_date,
                    artifact="longitudinal_analysis",
                )
            except Exception:
                await session.rollback()
                failures += 1
                log.exception("longitudinal analysis failed", user_id=str(player_id))

    if failures:
        return JobResult.degraded(
            "longitudinal_analysis_failed",
            **counters,
            failures=failures,
            alert_gated=skipped_alert_gate,
        )
    if skipped_alert_gate == counters["profiles"]:
        return JobResult.skipped(
            "admin_billing_alert_not_ready",
            **counters,
            alert_gated=skipped_alert_gate,
        )
    return JobResult.succeeded(**counters, alert_gated=skipped_alert_gate)


async def run_metric_baseline_refresh() -> JobResult:
    """Recompute every active profile's ``metric_baselines`` from stored history.

    Batch 228 / Decision #306. Before this job, ``MetricBaselineBackfillService
    .rebuild`` was reachable only from ``src/metric_baselines_backfill``, a manual
    admin runner — so a personal baseline was refreshed only when a human happened
    to add a *new* metric. ``metric_baselines.created_at`` records every refresh
    that has ever occurred: 2026-06-24, 2026-07-05, 2026-08-20, 2026-08-26, a
    longest gap of 46 days. That is not cosmetic: the 2026-08-26 run moved Mark's
    readiness median 59.0 → 61.0, and ``effective_readiness_floor`` is
    ``max(personal_center, 60)`` (``services/personal_baselines.py``), so the
    soft-sleep Green gate had been sitting a point more permissive than his own
    history warranted. DECISIONS #249 guards a *sinking* median making that rule
    permissive; nobody had considered a *rising* one that simply never arrives.

    ``rebuild`` is idempotent and commits itself, so a same-day re-run reports
    ``unchanged`` rather than rewriting. Failures are isolated per profile: an
    earlier profile's committed rebuild survives a later one's rollback.
    """

    counters = {"profiles": 0, "created": 0, "updated": 0, "unchanged": 0}
    failures = 0
    async with AsyncSessionLocal() as session:
        profiles = await _active_profiles(session)
        if not profiles:
            log.info("metric baseline refresh skipped", reason="no_active_profiles")
            return JobResult.skipped("no_active_profiles", **counters)

        service = MetricBaselineBackfillService(session)
        for profile in profiles:
            # Snapshot before the try block: a rollback expires ORM attributes,
            # so failure logging must not trigger implicit async IO.
            profile_id = profile.id
            counters["profiles"] += 1
            try:
                result = await service.rebuild(profile)
            except Exception:
                await session.rollback()
                failures += 1
                log.exception("metric baseline refresh failed", profile_id=str(profile_id))
                continue
            counters["created"] += result.baselines_created
            counters["updated"] += result.baselines_updated
            counters["unchanged"] += result.baselines_unchanged
            log.info(
                "metric baselines refreshed",
                profile_id=str(profile_id),
                window_start=result.window_start.isoformat() if result.window_start else None,
                window_end=result.window_end.isoformat() if result.window_end else None,
                samples_considered=result.samples_considered,
                created=result.baselines_created,
                updated=result.baselines_updated,
                unchanged=result.baselines_unchanged,
            )

    if failures:
        return JobResult.degraded("metric_baseline_refresh_failed", **counters, failures=failures)
    return JobResult.succeeded(**counters)


async def run_activity_timeseries_retention() -> JobResult:
    """Bound the table that is 82% of the database (Batch 247.2 / DS237-02).

    **Dry-run until ``activity_timeseries_retention_enabled`` is set.** The table
    is excluded from every backup, so a purge is irreversible; running it once is
    a decision with a row count attached rather than a side effect of a deploy.
    Until then this still earns its place, because it turns "somebody should
    measure this" into a counter in ``job_runs`` on every pass.
    """

    enabled = settings.activity_timeseries_retention_enabled
    async with AsyncSessionLocal() as session:
        result = await purge_expired_timeseries(session, dry_run=not enabled)

    counters = {
        "retention_days": RETENTION_DAYS,
        "expired_rows": result.expired_rows,
        "expired_activities": result.expired_activities,
        "deleted_rows": result.deleted_rows,
    }
    if result.dry_run:
        return JobResult.skipped("dry_run", **counters)
    return JobResult.succeeded(**counters)


async def run_workout_proposal_expiry() -> JobResult:
    """Retire delivery proposals for workout dates that have been and gone.

    Batch 249.4 (CI239-12). CI211-01 recorded 16 stale ``proposed`` rows at the
    Batch 211 refresh and 17 at the Batch 239 one — growing, all for past dates,
    with no path out of the state. It stayed "hygiene" for two refreshes because
    the daily loop looks proposals up by ``planned_workout_id`` and so never trips
    over them, but the count is also the *measurement* of how many eased Amber and
    Red offers were made and never taken, and a measurement nobody can read is not
    one. Nothing is deleted; the row keeps its IR and its history.
    """

    async with AsyncSessionLocal() as session:
        expired = await WorkoutDeliveryService(session).expire_stale_proposals()

    if expired:
        log.info(
            "expired stale workout delivery proposals",
            expired=len(expired),
            oldest_workout_date=min(row.workout_date for row in expired).isoformat(),
            newest_workout_date=max(row.workout_date for row in expired).isoformat(),
        )
    return JobResult.succeeded(expired=len(expired))


async def run_backup_restore_drill() -> JobResult:
    """Restore the latest backup into a disposable database and check invariants.

    Batch 247 (DS237-04) registers this weekly. Batch 196 built the machinery and
    it had **never once been pointed at a real archive** — zero ``job_runs`` rows
    in the entire history of the table — so everything about the backup was right
    except the part that matters: ``pg_restore --list`` proves an archive can be
    *parsed*, never that it can be *restored*.
    """

    if not settings.backup_restore_database_url:
        # Not a failure: an unconfigured drill has not failed, it has not run, and
        # reporting it as failed every week would be a standing false alarm that
        # teaches the operator to ignore this job. But it must not read as
        # healthy either — "configured but inert" is the exact shape DS237-01
        # found everywhere, so say plainly what is still unproved.
        log.warning(
            "backup restore drill is not configured",
            reason="backup_restore_database_url_unset",
            consequence="no backup has ever been proved restorable",
            alert_route="sentry",
        )
        return JobResult.skipped("not_configured")

    try:
        result = await restore_latest_backup(
            settings.backup_dir,
            settings.database_url,
            settings.backup_restore_database_url,
        )
        return JobResult.succeeded(
            restored_tables=result.restored_tables,
            profiles=result.profile_rows,
            analyses=result.analysis_rows,
            excluded_activity_timeseries_rows=result.excluded_activity_timeseries_rows,
        )
    except Exception as exc:
        reason = str(exc)
        log.exception("backup restore drill failed")
        _log_backup_operator_alert("backup_restore_drill_failed", reason)
        return JobResult.failed("backup_restore_drill_failed")


def _log_backup_operator_alert(kind: str, reason: str) -> None:
    """Structured log hook for provider/external monitors, outside user pushes."""

    log.error(
        "operator backup alert",
        kind=kind,
        reason=reason,
        alert_route="provider_log_or_external_monitor",
    )


def _log_operator_alert(kind: str, reason: str, **fields: Any) -> None:
    """Operator-only alert for a condition the *user* cannot act on.

    Same route as ``_log_backup_operator_alert`` (which keeps its own event name
    because the runbook names it), for conditions that must never reach Mark's
    phone. The user-facing stale-source pushes in ``nudge_alerts`` are the other
    half of this split: those tell him to put his watch on, this tells Craig a
    background job has stopped.
    """

    log.error(
        "operator alert",
        kind=kind,
        reason=reason,
        alert_route="provider_log_or_external_monitor",
        **fields,
    )


async def run_egress_budget_check() -> JobResult:
    """Flush the response-byte counter, meter storage, and stage both alerts.

    Runs every 15 min alongside the other interval jobs. Each run persists its
    own delta as a ``job_runs`` counter (the durable record — see
    ``services/egress_budget.py`` for why the in-memory counter alone is not),
    and only logs an operator alert when a day's highest staged threshold
    increases, so a sustained overage does not spam every 15 minutes.

    **Batch 247 makes three corrections and adds one instrument.**

    DS237-03 Defect C: the egress budget is the org-wide **monthly** cap and a
    single day's total was being compared against it. Warning fired at 2.75 GB in
    one day, while a steady 200 MB/day — 6 GB/month, over the cap — scored 0.036
    and read ``ok`` for ever. Month-to-date is what the cap is about, so
    month-to-date is what is now compared.

    DS237-03 Defect A: this counter sums **HTTP response bytes**, which travel
    application → client. The bytes that bill travel pooler → application, a
    direction this proxy cannot see at all — which is why it recorded 16,312,169
    bytes and stage ``ok`` on the day Supabase attributed 6.475 GB to this
    project, a ~397x understatement by the one instrument built to prevent it.
    Teaching it to count the other direction is a real change to the database
    layer and is not attempted here; instead the counters and the alert now say
    ``http_response_bytes``, which is all this can honestly claim.

    DS237-02: ``pg_database_size`` joins the counters with its own staged
    threshold. The database is at ~90% of a 500 MB cap, growing ~1.85 MB/day, and
    was watched by nothing — in an app that has already filled its disk once
    (DECISIONS #93). This job already runs every 15 minutes, already opens a
    session, already writes counters and already dedupes alerts, so measuring it
    here also builds the time series to project from, instead of the two anchors a
    month apart that the audit had to reason from.
    """

    delta = response_byte_counter.drain()
    now = datetime.now(UTC)
    day_start = datetime(now.year, now.month, now.day)
    month_start = datetime(now.year, now.month, 1)

    backup_bytes_today = 0
    latest = latest_backup(settings.backup_dir)
    if latest is not None and latest.created_at.astimezone(UTC).date() == now.date():
        backup_bytes_today = latest.size_bytes

    async with AsyncSessionLocal() as session:
        month_counters = (
            (
                await session.execute(
                    select(JobRun.counters).where(
                        JobRun.job_name == "egress-budget",
                        JobRun.started_at_utc >= month_start,
                    )
                )
            )
            .scalars()
            .all()
        )
        today_counters = (
            (
                await session.execute(
                    select(JobRun.counters).where(
                        JobRun.job_name == "egress-budget",
                        JobRun.started_at_utc >= day_start,
                    )
                )
            )
            .scalars()
            .all()
        )
        database_bytes = int(
            await session.scalar(select(func.pg_database_size(func.current_database()))) or 0
        )

    def _sum_bytes(rows: Iterable[Any]) -> int:
        # The key was renamed in Batch 247; rows written before it carry the old
        # one, and a month-to-date sum spans the rename on the day it ships.
        return sum(
            int(row.get("http_response_bytes_delta", row.get("response_bytes_delta", 0)))
            for row in rows
        )

    prior_today = _sum_bytes(today_counters)
    prior_month = _sum_bytes(month_counters)
    prior_max_ordinal = max(
        (int(row.get("alert_stage_ordinal", 0)) for row in today_counters), default=0
    )
    prior_max_storage_ordinal = max(
        (int(row.get("storage_stage_ordinal", 0)) for row in today_counters), default=0
    )

    total_today = prior_today + delta + backup_bytes_today
    total_month = prior_month + delta + backup_bytes_today
    stage = evaluate_egress_stage(total_month)
    ordinal = EGRESS_STAGE_ORDINAL[stage]
    storage_stage = evaluate_storage_stage(database_bytes)
    storage_ordinal = EGRESS_STAGE_ORDINAL[storage_stage]

    if ordinal > prior_max_ordinal:
        _log_egress_operator_alert(stage, total_month)
    if storage_ordinal > prior_max_storage_ordinal:
        _log_storage_operator_alert(storage_stage, database_bytes)

    counters = {
        "http_response_bytes_delta": delta,
        "backup_bytes_today": backup_bytes_today,
        "http_response_bytes_today": total_today,
        "http_response_bytes_month": total_month,
        "alert_stage_ordinal": ordinal,
        "database_bytes": database_bytes,
        "storage_stage_ordinal": storage_ordinal,
    }
    if stage == "ok" and storage_stage == "ok":
        return JobResult.succeeded(**counters)
    worst = stage if ordinal >= storage_ordinal else f"storage_{storage_stage}"
    return JobResult.degraded(f"egress_budget_{worst}", **counters)


def _log_storage_operator_alert(stage: str, database_bytes: int) -> None:
    """Batch 247 (DS237-02). Same route as the egress and backup alerts.

    ``log.error`` is the delivery mechanism, because that is the level
    ``SENTRY_DSN_BACKEND`` captures — the same reasoning as Batch 242.5's ledger
    check.
    """

    log.error(
        "operator storage alert",
        kind=f"database_storage_{stage}",
        database_bytes=database_bytes,
        budget_bytes=STORAGE_BUDGET_BYTES,
        used_fraction=round(database_bytes / STORAGE_BUDGET_BYTES, 4),
        # The trap, carried on the alert itself rather than left in a runbook:
        # near a full disk, VACUUM FULL / CLUSTER / CTAS all need the new copy's
        # size free and cannot run. Only dump / truncate / reload works then.
        remediation="delete_then_plain_vacuum; a full disk needs dump/truncate/reload",
        alert_route="sentry",
    )


def _log_egress_operator_alert(stage: str, total_bytes_month: int) -> None:
    """Structured log hook, outside user pushes — same route as backup alerts.

    Batch 247 (DS237-03) corrects what this claims. The field is named for what
    it counts — HTTP response bytes, application → client — because the bytes
    that bill travel pooler → application and this proxy cannot see them. On
    2026-08-30 it read 16,312,169 bytes and stage ``ok`` while Supabase
    attributed 6.475 GB to the project. An instrument that overstates its own
    scope is worse than one that admits it, because the green reading was taken
    as evidence.
    """

    log.error(
        "operator egress alert",
        kind=f"egress_budget_{stage}",
        http_response_bytes_month=total_bytes_month,
        budget_bytes=EGRESS_BUDGET_BYTES,
        measures="http_response_bytes (application->client); the billed direction "
        "is pooler->application and is not visible to this proxy",
        alert_route="sentry",
    )


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


async def run_hive_temperature_poll() -> JobResult:
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
                return JobResult.skipped("no_hive_profiles", profiles=0, readings=0)

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
        return JobResult.succeeded(profiles=len(profiles), readings=synced)
    except Exception:
        log.exception("hive temperature poll failed")
        return JobResult.failed("hive_poll_failed")


async def run_evening_sleep_nudge() -> JobResult:
    """Send useful projected sleep guidance in each active profile's timezone."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("evening sleep nudge skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0, nudges=0)

            service = NudgeAlertService(session)
            holiday_service = HolidayPauseService(session)
            nudges_recorded = 0
            skipped_holiday = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                if (
                    await holiday_service.get_overnight_away_window_for_date(profile, subject_date)
                    is not None
                ):
                    skipped_holiday += 1
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
        return JobResult.succeeded(
            profiles=len(profiles),
            nudges=nudges_recorded,
            skipped_holiday=skipped_holiday,
        )
    except Exception:
        log.exception("evening sleep nudge failed")
        return JobResult.failed("evening_nudge_failed")


async def run_weekly_review_delivery() -> JobResult:
    """Generate and deliver the ISO week ending this Sunday at 18:00 local."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("weekly review delivery skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0)

            holiday_service = HolidayPauseService(session)
            service = WeeklyReviewDeliveryService(session)
            generated = 0
            messages = 0
            pushes = 0
            skipped_holiday = 0
            skipped_in_flight = 0
            failed = 0
            for profile in profiles:
                # Batch 242 (CR236-01): an earlier iteration's rollback expired
                # this instance, so reload before the first attribute read.
                await _restore_after_rollback(session, profile)
                # Snapshot the scalars before anything can fail, so every
                # handler below logs from a local instead of from an instance a
                # rollback has since expired. See _restore_after_rollback.
                profile_id = profile.id
                subject_date = _profile_today(profile)
                if (
                    await holiday_service.get_active_window_for_date(profile, subject_date)
                    is not None
                ):
                    skipped_holiday += 1
                    log.info(
                        "weekly review delivery skipped",
                        reason="holiday_away",
                        profile_id=str(profile_id),
                        subject_date=subject_date.isoformat(),
                    )
                    continue
                try:
                    result = await service.run(
                        profile,
                        as_of=subject_date,
                        commit=True,
                    )
                    generated += int(result.generated)
                    messages += int(result.message_created)
                    pushes += int(result.push_recorded)
                except GenerationRequestInProgress:
                    # Batch 232.1: Decision #266 runs the Railway ``weekly-review``
                    # cron *and* this in-process job on purpose, so exactly one of
                    # them losing the artifact lock is the designed outcome, not a
                    # failure. Falling into the handler below would post a failure
                    # turn into Mark's coach thread and alert the operator about a
                    # review the other runner is writing successfully.
                    skipped_in_flight += 1
                    await session.rollback()
                    log.info(
                        "weekly review delivery deferred to the in-flight holder",
                        profile_id=str(profile_id),
                        subject_date=subject_date.isoformat(),
                    )
                    continue
                except Exception as exc:
                    failed += 1
                    await session.rollback()
                    reason = exc.reason if isinstance(exc, AnthropicApiError) else "other"
                    log.exception(
                        "weekly review delivery failed",
                        profile_id=str(profile_id),
                        subject_date=subject_date.isoformat(),
                        reason=reason,
                    )
                    # record_failure and the operator alert both take the live
                    # instance, so it has to be usable again before they run —
                    # this is the path CR236-01 stopped reaching at all.
                    await _restore_after_rollback(session, profile)
                    try:
                        await service.record_failure(
                            profile,
                            subject_date=subject_date,
                            commit=False,
                        )
                        await NudgeAlertService(session).notify_admin_generation_failure(
                            reason=reason,
                            subject_date=subject_date,
                            artifact="weekly_review",
                            commit=False,
                        )
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        log.exception(
                            "recording weekly review failure state failed",
                            profile_id=str(profile_id),
                            subject_date=subject_date.isoformat(),
                        )
        log.info(
            "weekly review delivery complete",
            profiles=len(profiles),
            generated=generated,
            messages=messages,
            pushes=pushes,
            skipped_holiday=skipped_holiday,
            skipped_in_flight=skipped_in_flight,
            failed=failed,
        )
        counters = {
            "profiles": len(profiles),
            "generated": generated,
            "messages": messages,
            "pushes": pushes,
            "skipped_holiday": skipped_holiday,
            "skipped_in_flight": skipped_in_flight,
            "failed": failed,
        }
        if failed:
            return JobResult.degraded("profile_failures", **counters)
        if skipped_holiday == len(profiles):
            return JobResult.skipped("holiday_away", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("weekly review delivery failed")
        return JobResult.failed("weekly_review_failed")


async def run_state_change_coach() -> JobResult:
    """Deliver at most one meaningful state-change coach turn per profile/week."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("state-change coach skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0)

            holiday_service = HolidayPauseService(session)
            service = StateChangeCoachService(session)
            delivered = 0
            skipped_budget = 0
            skipped_no_transition = 0
            skipped_holiday = 0
            failed = 0
            for profile in profiles:
                await _restore_after_rollback(session, profile)
                profile_id = profile.id
                subject_date = _profile_today(profile)
                if (
                    await holiday_service.get_active_window_for_date(profile, subject_date)
                    is not None
                ):
                    skipped_holiday += 1
                    log.info(
                        "state-change coach skipped",
                        reason="holiday_away",
                        profile_id=str(profile_id),
                        subject_date=subject_date.isoformat(),
                    )
                    continue
                try:
                    result = await service.run(profile, as_of=subject_date, commit=True)
                    delivered += int(result.message_created)
                    skipped_budget += int(result.reason == "budget_spent")
                    skipped_no_transition += int(result.reason == "no_transition")
                except Exception:
                    failed += 1
                    await session.rollback()
                    log.exception(
                        "state-change coach failed",
                        profile_id=str(profile_id),
                        subject_date=subject_date.isoformat(),
                    )
        log.info(
            "state-change coach complete",
            profiles=len(profiles),
            delivered=delivered,
            skipped_budget=skipped_budget,
            skipped_no_transition=skipped_no_transition,
            skipped_holiday=skipped_holiday,
            failed=failed,
        )
        counters = {
            "profiles": len(profiles),
            "delivered": delivered,
            "skipped_budget": skipped_budget,
            "skipped_no_transition": skipped_no_transition,
            "skipped_holiday": skipped_holiday,
            "failed": failed,
        }
        if failed:
            return JobResult.degraded("profile_failures", **counters)
        if skipped_holiday == len(profiles):
            return JobResult.skipped("holiday_away", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("state-change coach failed")
        return JobResult.failed("state_change_failed")


async def run_evening_monitoring_alerts() -> JobResult:
    """Check bedtime thermal state and source freshness for active profiles."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("evening monitoring alerts skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0, alerts=0)

            service = NudgeAlertService(session)
            holiday_service = HolidayPauseService(session)
            alerts_recorded = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                holiday_away = (
                    await holiday_service.get_overnight_away_window_for_date(profile, subject_date)
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
        # Batch 228: a nightly job that silently stops is the same defect this
        # batch fixes, wearing a different hat — and nothing writes a `job_runs`
        # row for a run that never happened, so the detector has to live in a job
        # that *is* still running. This one fires sixteen times a day and already
        # owns "is a source stale?". Its own session, deliberately: a read that
        # fails here must not abort the transaction the thermal alerts were
        # written in.
        stale_baselines = await _check_metric_baseline_freshness(profiles)
        log.info(
            "evening monitoring alerts complete",
            profiles=len(profiles),
            alerts=alerts_recorded,
            stale_baselines=stale_baselines,
        )
        return JobResult.succeeded(
            profiles=len(profiles),
            alerts=alerts_recorded,
            stale_baselines=stale_baselines,
        )
    except Exception:
        log.exception("evening monitoring alerts failed")
        return JobResult.failed("evening_alerts_failed")


async def _check_metric_baseline_freshness(profiles: Iterable[Profile]) -> int:
    """Alert the **operator** when a profile's baselines have stopped tracking it.

    Deliberately not one of the ``evaluate_stale_sources`` pushes: every one of
    those tells Mark to do something he can do (put the watch on, check Hive). A
    baseline that has stopped refreshing is Craig's to fix, and a push about it
    would be noise on the one surface reserved for actionable inputs.

    Best-effort — it can never fail the evening alerts that already ran.
    """

    alerted = 0
    try:
        async with AsyncSessionLocal() as session:
            for profile in profiles:
                oldest_sleep, newest_sleep = (
                    await session.execute(
                        select(
                            func.min(Sleep.calendar_date),
                            func.max(Sleep.calendar_date),
                        ).where(Sleep.user_id == profile.id)
                    )
                ).one()
                window_end = await session.scalar(
                    select(func.min(MetricBaseline.window_end_date)).where(
                        MetricBaseline.user_id == profile.id,
                        MetricBaseline.source == DB_HISTORY_SOURCE,
                    )
                )
                lag = unincorporated_nights(
                    newest_sleep_date=newest_sleep,
                    oldest_sleep_date=oldest_sleep,
                    baseline_window_end=window_end,
                )
                if lag is None or lag < BASELINE_STALENESS_LIMIT_DAYS:
                    continue
                alerted += 1
                _log_operator_alert(
                    "metric_baselines_stale",
                    "no_baseline_rows" if window_end is None else "baseline_window_behind_history",
                    profile_id=str(profile.id),
                    unincorporated_nights=lag,
                    limit_days=BASELINE_STALENESS_LIMIT_DAYS,
                    baseline_window_end=window_end.isoformat() if window_end else None,
                    newest_sleep_date=newest_sleep.isoformat() if newest_sleep else None,
                )
    except Exception:
        log.exception("metric baseline freshness check failed")
    return alerted


async def run_wake_nudge() -> JobResult:
    """Wake-triggered morning **sync + nudge** (Batch 85).

    Pulls all external inputs (weather + today's Garmin daily metrics/sleep; Hive
    indoor temp already streams from its own poll) into Postgres so they are sitting
    ready before Mark is up, then fires the "good morning" nudge inviting him to
    check in. Generation has moved *off* the wake trigger onto his check-in (the
    primary trigger) and the 11:00 backstop (fallback), so by the time he taps the
    data is already synced and the brief generates fast. Idempotent: the nudge is
    one-per-day and is skipped once today's brief already exists (he checked in, or
    the backstop generated it).

    Batch 251 renamed this from ``run_morning_sync``: ``run_scheduled.py`` exposes
    *the backstop* under the job name ``morning-sync``, so the two names collided
    on the one word that told them apart. The job this function is — the wake nudge
    — is not exposed to the external runner at all.
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("morning sync skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0)
            pipeline = MorningBriefPipeline(session)
            inputs = await pipeline.sync_inputs(profiles)
            nudges_sent = 0
            failures = inputs.failures
            for profile in profiles:
                nudge = await pipeline.send_wake_nudge(profile)
                nudges_sent += 1 if nudge.sent else 0
                failures += nudge.failures
        log.info(
            "morning sync complete",
            profiles=len(profiles),
            days=inputs.weather_days,
            daily_metrics=inputs.daily_metrics,
            sleep=inputs.sleep,
            nudges_sent=nudges_sent,
            failed=failures,
        )
        counters = {
            "profiles": len(profiles),
            "days": inputs.weather_days,
            "daily_metrics": inputs.daily_metrics,
            "sleep": inputs.sleep,
            "nudges_sent": nudges_sent,
            "failed": failures,
        }
        if failures:
            return JobResult.degraded("step_failures", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("morning sync failed")
        return JobResult.failed("morning_sync_failed")


async def run_morning_weather_sync() -> JobResult:
    """Full morning pipeline: sync inputs, then generate + push the verdict.

    This is the **11:00 backstop** (and the external-cron ``morning-sync`` entry) —
    it guarantees a verdict even for a morning Mark never engaged with. On the
    primary path generation is triggered by his check-in and the wake job runs the
    lighter run_wake_nudge (sync + nudge) instead (Batch 85). Idempotent per
    profile: generate_and_store and push_brief_ready short-circuit if the brief /
    push already happened via the check-in (Batch 112 converged the backstop onto
    the same brief-ready notification the check-in path sends, so there is one
    "your brief is ready" push regardless of which path generated it first).

    Batch 251: the ladder below the sync now lives in ``MorningBriefPipeline``,
    which the check-in trigger runs too. What is left here is the job's own
    concern — iterating active profiles and turning per-profile outcomes into a
    ``JobResult``.
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("morning weather sync skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0)
            pipeline = MorningBriefPipeline(session, policy=BACKSTOP_POLICY)
            inputs = await pipeline.sync_inputs(profiles)
            analyses_generated = 0
            analyses_existing = 0
            failures = inputs.failures
            proposals_regenerated = 0
            chronic_deload_proposals = 0
            brief_ready_pushes = 0
            drivers_cached = 0
            inputs_not_ready = 0
            for profile in profiles:
                outcome = await pipeline.generate_brief(profile)
                analyses_generated += 1 if outcome.generated else 0
                analyses_existing += 1 if outcome.existing else 0
                inputs_not_ready += 1 if outcome.inputs_not_ready else 0
                proposals_regenerated += outcome.proposals_regenerated
                chronic_deload_proposals += outcome.chronic_deload_proposals
                brief_ready_pushes += outcome.brief_ready_pushes
                drivers_cached += outcome.drivers_cached
                failures += outcome.failures
        log.info(
            "morning weather sync complete",
            profiles=len(profiles),
            days=inputs.weather_days,
            daily_metrics=inputs.daily_metrics,
            sleep=inputs.sleep,
            analyses_generated=analyses_generated,
            analyses_existing=analyses_existing,
            proposals_regenerated=proposals_regenerated,
            chronic_deload_proposals=chronic_deload_proposals,
            brief_ready_pushes=brief_ready_pushes,
            drivers_cached=drivers_cached,
            inputs_not_ready=inputs_not_ready,
            failed=failures,
        )
        counters = {
            "profiles": len(profiles),
            "days": inputs.weather_days,
            "daily_metrics": inputs.daily_metrics,
            "sleep": inputs.sleep,
            "analyses_generated": analyses_generated,
            "analyses_existing": analyses_existing,
            "proposals_regenerated": proposals_regenerated,
            "chronic_deload_proposals": chronic_deload_proposals,
            "brief_ready_pushes": brief_ready_pushes,
            "drivers_cached": drivers_cached,
            "inputs_not_ready": inputs_not_ready,
            "failed": failures,
        }
        if failures:
            return JobResult.degraded("step_failures", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("morning weather sync failed")
        return JobResult.failed("morning_pipeline_failed")


async def run_wake_check() -> JobResult:
    """Poll Garmin sleep and fire the morning sync once Mark has actually woken.

    Replaces the fixed 06:30 cron. Per active profile, within the morning window
    (Europe/London local), it: (1) short-circuits once today's Garmin inputs
    prove synced; (2) does a light sleep-only Garmin poll; (3) applies the
    back-to-sleep stability guard against the previously persisted ``sleepEnd``
    (services/wake_detection.is_morning_ready); (4) persists the current
    ``sleepEnd`` as a ``wake_check`` audit row for the next poll's comparison. If
    any profile is ready (stable wake, or the ~11:00 backstop) it runs
    ``run_wake_nudge`` once — which is idempotent per profile, so re-firing on
    later polls is harmless.
    """
    try:
        any_ready = False
        failures = 0
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("wake check skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0)

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
                # An analysis is not a sync marker: the 2026-08-20 check-in made
                # an empty read and that old condition cancelled the sync which
                # would have repaired it. A morning DailyMetric proves a full
                # Garmin pull completed. Before the backstop, require Sleep too
                # so a lagging real night keeps polling; afterward, daily-without-
                # sleep is an honest watch-not-worn/no-session result.
                inputs = await morning_input_presence(
                    session,
                    user_id=profile.id,
                    subject_date=today,
                )
                if inputs.ready_for_read(allow_missing_sleep=now_local.time() >= BACKSTOP):
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
                    failures += 1
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
                if not await _commit_morning_step(
                    session,
                    step="wake_check",
                    profile_id=profile.id,
                    subject_date=today,
                ):
                    failures += 1
                    continue
                if decision.action == "fire":
                    fired += 1
                    any_ready = True
                elif decision.action == "nap_ignored":
                    napped += 1
                else:
                    waiting += 1
        log.info(
            "wake check complete",
            profiles=len(profiles),
            fired=fired,
            waiting=waiting,
            napped=napped,
            failed=failures,
        )
        # Once wake is stable, sync all inputs and fire the "good morning" nudge —
        # generation itself waits for his check-in (Batch 85). Runs on its own
        # session after the last-seen state is committed; idempotent per profile.
        if any_ready:
            morning_result = await run_wake_nudge()
            if morning_result.exit_code:
                failures += 1
        counters = {
            "profiles": len(profiles),
            "fired": fired,
            "waiting": waiting,
            "napped": napped,
            "failed": failures,
        }
        if failures:
            return JobResult.degraded("step_failures", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("wake check failed")
        return JobResult.failed("wake_check_failed")


async def run_garmin_activity_poll() -> JobResult:
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
                return JobResult.skipped("no_active_profiles", profiles=0)

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
        return JobResult.succeeded(
            profiles=len(profiles),
            activities=activities_synced,
            timeseries_samples=timeseries_synced,
            checkin_nudges=checkin_nudges,
        )
    except Exception:
        log.exception("garmin activity poll failed")
        return JobResult.failed("activity_poll_failed")


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
) -> tuple[int, int]:
    """Push one notification per newly generated post-workout analysis (Batch 45).

    Each push is wrapped so a failure never blocks the activity poll; the
    ``analysis-{activity_id}`` tag keeps it idempotent and the audit row lands in
    the poll's trailing commit. An existing analysis (``generated`` is ``False``,
    e.g. regenerated on a newer check-in / prompt bump) never re-pushes.
    """
    pushed = 0
    failures = 0
    # Batch 242 (CR236-01): hoisted before the loop — the rollback below expires
    # the instance, and the caller keeps using it after this returns.
    profile_id = profile.id
    for item in results:
        if not item.generated:
            continue
        try:
            if await nudge_service.push_workout_analysis(
                profile, item.analysis, kind=kind, commit=False
            ):
                pushed += 1
        except Exception:
            failures += 1
            await nudge_service.session.rollback()
            log.exception(
                "post-workout push failed",
                profile_id=str(profile_id),
                kind=kind,
            )
            await _restore_after_rollback(nudge_service.session, profile)
            break
    return pushed, failures


async def run_post_workout_backstop() -> JobResult:
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
            failures = 0
            for profile in profiles:
                await _restore_after_rollback(session, profile)
                # Batch 242 (CR236-01): hoisted before the *reader* loop — one
                # reader's rollback would otherwise expire the instance the next
                # three readers take, and _push_new_analyses rolls back too.
                profile_id = profile.id
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
                        generated_now = sum(1 for item in results if item.generated)
                        pushed_now, push_failures = await _push_new_analyses(
                            NudgeAlertService(session), profile, results, kind=kind
                        )
                        if push_failures:
                            failures += push_failures
                            continue
                        await session.commit()
                        generated += generated_now
                        pushes += pushed_now
                    except Exception:
                        failures += 1
                        await session.rollback()
                        log.exception(
                            "post-workout backstop reader failed",
                            profile_id=str(profile_id),
                            kind=kind,
                        )
                        await _restore_after_rollback(session, profile)
        log.info(
            "post-workout backstop complete",
            profiles=len(profiles),
            analyses_generated=generated,
            analysis_pushes=pushes,
            failed=failures,
        )
        counters = {
            "profiles": len(profiles),
            "analyses_generated": generated,
            "analysis_pushes": pushes,
            "failed": failures,
        }
        if failures:
            return JobResult.degraded("step_failures", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("post-workout backstop failed")
        return JobResult.failed("post_workout_backstop_failed")


async def run_workout_autopush() -> JobResult:
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
                return JobResult.skipped("no_active_profiles", profiles=0)

            service = ExecutableCoachingService(session)
            pushed = 0
            failed = 0
            for profile in profiles:
                await _restore_after_rollback(session, profile)
                profile_id = profile.id
                try:
                    results = await service.auto_push_due(profile)
                    pushed += len(results)
                except Exception:
                    failed += 1
                    await session.rollback()
                    log.exception(
                        "workout autopush failed for profile",
                        profile_id=str(profile_id),
                    )
        log.info("workout autopush complete", profiles=len(profiles), pushed=pushed, failed=failed)
        counters = {"profiles": len(profiles), "pushed": pushed, "failed": failed}
        if failed:
            return JobResult.degraded("profile_failures", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("workout autopush failed")
        return JobResult.failed("autopush_failed")


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


async def run_fan_control() -> JobResult:
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
            return JobResult.skipped("no_dreo_credentials")
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("fan control skipped", reason="no_active_profiles")
                return JobResult.skipped("no_active_profiles", profiles=0)
            profile = profiles[0]
            now_local = _profile_now(profile)
            phase = loop_phase(now_local.time())
            if phase == "idle":
                # Daytime: a true no-op — no cloud call, and not charted.
                return JobResult.skipped("outside_overnight_window", profiles=1)
            subject_date = now_local.date()
            if (
                await HolidayPauseService(session).get_overnight_away_window_for_date(
                    profile, subject_date
                )
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
                return JobResult.skipped("holiday_away", profiles=1)
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
                return JobResult.succeeded(profiles=1, ticks=1, commands=0)
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
        counters = {
            "profiles": 1,
            "ticks": 1,
            "commands": int(result.action == "apply"),
            "unreachable": int(result.action == "unreachable"),
        }
        if result.action == "unreachable":
            return JobResult.degraded("fan_unreachable", **counters)
        return JobResult.succeeded(**counters)
    except Exception:
        log.exception("fan control failed")
        return JobResult.failed("fan_control_failed")


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
        partial(run_tracked_job, "backup", run_scheduled_backup),
        trigger="cron",
        hour=3,
        minute=0,
        id="daily_backup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        # Batch 228 / Decision #306. 02:30 Europe/London is chosen, not inherited:
        #  - it is a full hour before `wake_detection.WINDOW_START` (03:30) opens
        #    the morning window, and 75 min before Mark's earliest observed wake
        #    (03:45), so it can never race the read it feeds;
        #  - the newest `sleep` row at that hour is always yesterday's, because
        #    tonight's is written by the wake sync — so the night being judged is
        #    never inside the 84-night distribution it is judged against;
        #  - it is 01:30 UTC under BST and 02:30 UTC under GMT, so it lands before
        #    the 03:00 *UTC* `daily_backup` in both, and the nightly dump carries
        #    the freshened rows rather than yesterday's.
        # In-process APScheduler handles BST/GMT; a fixed-UTC external cron would
        # not (see docs/runbooks/scheduled-jobs-cron.md).
        partial(run_tracked_job, "baseline-refresh", run_metric_baseline_refresh),
        trigger="cron",
        hour=2,
        minute=30,
        timezone=settings.weather_timezone,
        id="metric_baseline_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        partial(run_tracked_job, "hive-poll", run_hive_temperature_poll),
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
        partial(run_tracked_job, "wake-check", run_wake_check),
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
        # worn / container down through the window), guarantee a verdict by 11:00
        # (Batch 138 / Decision #217 — moved later from 09:30 so a genuine lie-in
        # isn't force-read on stale data; keep in step with wake_detection.BACKSTOP).
        # run_morning_weather_sync is idempotent per profile, so this no-ops if the
        # wake trigger already fired. In-process APScheduler handles BST/GMT.
        partial(run_tracked_job, "morning-sync", run_morning_weather_sync),
        trigger="cron",
        hour=11,
        minute=0,
        timezone=settings.weather_timezone,
        id="morning_backstop",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        partial(run_tracked_job, "activity-poll", run_garmin_activity_poll),
        trigger="interval",
        hours=1,
        id="garmin_activity_poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(UTC) + timedelta(minutes=5),
    )
    scheduler.add_job(
        partial(run_tracked_job, "post-workout-backstop", run_post_workout_backstop),
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
        partial(run_tracked_job, "autopush", run_workout_autopush),
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
        partial(run_tracked_job, "weekly-review", run_weekly_review_delivery),
        trigger="cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        timezone=settings.weather_timezone,
        id="weekly_review_delivery",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        partial(run_tracked_job, "state-change", run_state_change_coach),
        trigger="cron",
        hour=11,
        minute=45,
        timezone=settings.weather_timezone,
        id="state_change_coach",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        # Batch 220: polling an existing Message Batch is no-spend; the submitter
        # itself is monthly-idempotent and refuses to spend until the operator
        # billing alert has an active push recipient.
        partial(run_tracked_job, "longitudinal-analysis", run_longitudinal_analysis),
        trigger="cron",
        hour=12,
        minute=15,
        timezone=settings.weather_timezone,
        id="longitudinal_analysis",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        partial(run_tracked_job, "evening-nudge", run_evening_sleep_nudge),
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
        partial(run_tracked_job, "evening-alerts", run_evening_monitoring_alerts),
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
        partial(run_tracked_job, "fan-control", run_fan_control),
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
    # Batch 247.2: daily at 03:40 UTC, after the backup has been taken so a purge
    # can never race the archive that does not contain this table anyway. Dry-run
    # until deliberately enabled.
    scheduler.add_job(
        partial(run_tracked_job, "timeseries-retention", run_activity_timeseries_retention),
        "cron",
        hour=3,
        minute=40,
        id="timeseries_retention",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Batch 249.4 (CI239-12): daily at 03:50 UTC, right after the retention pass
    # and well clear of the morning loop, because a proposal that expires while
    # Mark is looking at his week would be a surprise for no benefit.
    scheduler.add_job(
        partial(run_tracked_job, "proposal-expiry", run_workout_proposal_expiry),
        "cron",
        hour=3,
        minute=50,
        id="proposal_expiry",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Batch 247.3 (DS237-04): weekly, an hour after the 03:00 UTC backup, so a
    # regression in the archive surfaces within seven days rather than at the
    # moment of need. Skips honestly until BACKUP_RESTORE_DATABASE_URL is set.
    scheduler.add_job(
        partial(run_tracked_job, "backup-drill", run_backup_restore_drill),
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        id="backup_drill",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        partial(run_tracked_job, "egress-budget", run_egress_budget_check),
        trigger="interval",
        minutes=15,
        id="egress_budget",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(UTC) + timedelta(minutes=6),
    )
    return scheduler
