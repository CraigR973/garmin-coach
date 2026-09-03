"""Transport for ``/api/v1/daily-loop`` — four routes and nothing else.

Batch 251 (CR236-09) moved the 45 response models to ``daily_loop_schemas``, the
envelope assembly and the Dreo fan serialization to ``services/daily_loop_envelope``,
and the morning check-in's background generation to ``services/morning_pipeline``.
What is left is what a router is for.
"""

from __future__ import annotations

import uuid
from datetime import date
from time import perf_counter

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import (
    Activity,
)
from src.rate_limit import paid_generation_limit
from src.routers.daily_loop_schemas import (
    AdherenceBody,
    ApiError,
    DailyLoopEnvelope,
    ManualEntryBody,
    PostRideCheckInBody,
)
from src.services.anthropic_text import AnthropicApiError, anthropic_user_message
from src.services.brief_generation_status import (
    BriefGenerationStatusService,
)
from src.services.daily_loop import DailyLoopService
from src.services.daily_loop_envelope import build_envelope, local_today
from src.services.generation_requests import GenerationRequestInProgress
from src.services.morning_pipeline import run_checkin_brief
from src.services.nudge_alerts import NudgeAlertService
from src.services.post_activity_analysis import (
    generate_post_activity_read,
    mark_prepared_post_activity_failed,
    post_activity_kind,
    prepare_post_activity_read,
)
from src.services.session_recovery import restore_after_rollback

router = APIRouter(prefix="/api/v1/daily-loop", tags=["daily-loop"])

log = structlog.get_logger(__name__)


async def _generate_brief_after_checkin(user_id: uuid.UUID, subject_date: date) -> None:
    """The check-in trigger, one line deep (Batch 251, CR236-02).

    This function used to be the third implementation of the morning path — its own
    transaction contract, its own ``GenerationRequestInProgress`` handler, its own
    failure recording, and a function-scope ``from src.scheduler import
    _sync_morning_inputs`` so a router could reach a private scheduler helper. All
    of that is now ``services/morning_pipeline``; what is left is the name the
    background task is registered under.
    """
    await run_checkin_brief(user_id, subject_date)


@router.get("", response_model=DailyLoopEnvelope)
async def get_daily_loop(
    player: CurrentUser,
    subject_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    # Batch 62.5: attribute server time (snapshot round-trips vs envelope compute)
    # so the latency work can be measured before/after from the logs, not guessed.
    started = perf_counter()
    service = DailyLoopService(db)
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    snapshot_ms = round((perf_counter() - started) * 1000, 1)
    envelope = await build_envelope(player, snapshot, db)
    log.info(
        "daily_loop served",
        snapshot_ms=snapshot_ms,
        envelope_ms=round((perf_counter() - started) * 1000 - snapshot_ms, 1),
        total_ms=round((perf_counter() - started) * 1000, 1),
    )
    return envelope


@router.put("/{subject_date}/manual-entry", response_model=DailyLoopEnvelope)
@paid_generation_limit
async def upsert_manual_entry(
    subject_date: date,
    body: ManualEntryBody,
    request: Request,
    player: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    await service.upsert_manual_entry(
        player,
        subject_date=subject_date,
        bp_systolic=body.bpSystolic,
        bp_diastolic=body.bpDiastolic,
        subjective_score=body.subjectiveScore,
        rpe=body.rpe,
        feel=body.feel,
        supplements_json=body.supplementsJson,
        food_json=body.foodJson,
        sleep_setup_json=(
            body.sleepSetupJson.model_dump(exclude_none=True)
            if body.sleepSetupJson is not None
            else None
        ),
        rem_intervention_feedback_json=(
            body.remInterventionFeedbackJson.model_dump()
            if body.remInterventionFeedbackJson is not None
            else None
        ),
        notes=body.notes,
    )
    # Batch 97: keep the check-in as the primary generate trigger, but move the
    # actual brief generation off the request path. Saving returns immediately;
    # the background task regenerates the brief, preserves Batch 85's downgrade-
    # only / never-touch-an-approved-ride guardrails, then fires a ready push.
    if subject_date == local_today(player.timezone):
        # Batch 141: mark generating before the background task runs so the
        # envelope this request returns already reads "generating" (the task
        # flips it to ready/failed), giving the client a real state to poll.
        await BriefGenerationStatusService(db).mark_generating(player.id, subject_date, commit=True)
        background_tasks.add_task(_generate_brief_after_checkin, player.id, subject_date)
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    return await build_envelope(player, snapshot, db)


@router.put(
    "/{subject_date}/planned-workouts/{planned_workout_id}/adherence",
    response_model=DailyLoopEnvelope,
)
async def upsert_workout_adherence(
    subject_date: date,
    planned_workout_id: uuid.UUID,
    body: AdherenceBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    await service.upsert_adherence(
        player,
        subject_date=subject_date,
        planned_workout_id=planned_workout_id,
        adherence_status=body.status,
        rpe=body.rpe,
        feel=body.feel,
        notes=body.notes,
        actual_workout_json=body.actualWorkoutJson,
    )
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    return await build_envelope(player, snapshot, db)


@router.put(
    "/{subject_date}/activities/{activity_id}/post-ride-check-in",
    response_model=DailyLoopEnvelope,
)
@paid_generation_limit
async def upsert_post_ride_checkin(
    subject_date: date,
    activity_id: uuid.UUID,
    body: PostRideCheckInBody,
    request: Request,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    await service.upsert_post_ride_checkin(
        player,
        subject_date=subject_date,
        activity_id=activity_id,
        subjective_score=body.subjectiveScore,
        rpe=body.rpe,
        feel=body.feel,
        notes=body.notes,
    )
    # Batch 87: the generic activity-linked check-in is the primary generation
    # trigger for rides, strength, mobility, and deliberate walks. The save above
    # commits first, so every reader sees the just-entered RPE/feel/notes.
    activity = await db.get(Activity, activity_id)
    read_error: ApiError | None = None
    if activity is not None and post_activity_kind(activity) is not None:
        # Batch 143: the check-in above already committed (service.commit), so his
        # RPE/feel/notes are safe. An Anthropic outage on the read must not 500 that
        # away. Generate inside a SAVEPOINT so a failure rolls back only the
        # half-written analysis (and its planned-workout completion flip), never the
        # committed check-in — then surface a non-fatal note (the activity re-appears
        # as a pending read carrying the saved check-in, so re-submitting is the
        # retry) and alert on a billing outage the same way as the morning brief.
        prepared = await prepare_post_activity_read(db, player, activity, commit=True)
        try:
            async with db.begin_nested():
                await generate_post_activity_read(db, player, activity, force=True, commit=False)
            await db.commit()
        except AnthropicApiError as exc:
            await mark_prepared_post_activity_failed(
                db,
                player,
                activity,
                prepared,
                reason=exc.reason,
                commit=True,
            )
            # Batch 248 (AI238-03): alert on every reason, matching the scheduler.
            await NudgeAlertService(db).notify_admin_generation_failure(
                reason=exc.reason, subject_date=subject_date, commit=True
            )
            read_error = ApiError(
                code="post_workout_read_failed",
                detail=anthropic_user_message(exc.reason),
            )
        except GenerationRequestInProgress:
            # Batch 232.1: another worker owns this activity's read. Roll back the
            # savepoint but leave the prepared ``generating`` status alone — the
            # holder writes the real outcome, and recording a failure here would
            # replace a read that is being generated with a failed one. The 409
            # propagates so the client polls rather than treating it as an error.
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            # Batch 242 (CR236-01): the rollback expired both ORM instances, and
            # ``mark_prepared_post_activity_failed`` reads ``player.id`` and
            # ``activity.id``. Without the reload it raises MissingGreenlet from
            # inside this handler, so the read is never marked failed and Mark is
            # left on a spinner rather than a retryable state. ``prepared`` is a
            # plain dataclass and is unaffected.
            await restore_after_rollback(db, player, activity)
            await mark_prepared_post_activity_failed(
                db,
                player,
                activity,
                prepared,
                reason="generation_error",
                commit=True,
            )
            raise
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    envelope = await build_envelope(player, snapshot, db)
    if read_error is not None:
        envelope.errors.append(read_error)
    return envelope
