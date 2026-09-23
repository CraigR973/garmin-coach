"""Shared completion and generation-state seam for post-session reads (Batch 159)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Activity, KnowledgeBase, PostActivityGenerationStatus
from src.services.workout_categories import (
    DAY_CATEGORY_CYCLE,
    DAY_CATEGORY_FLEXIBILITY,
    DAY_CATEGORY_WALK,
    DAY_CATEGORY_WEIGHTS,
)
from src.services.workout_completion import (
    PlannedWorkoutMatch,
    complete_matched_planned_workout,
)

PostActivityKind = Literal["ride", "strength", "flexibility", "walk"]
GenerationState = Literal["generating", "ready", "failed"]

STATUS_GENERATING: Literal["generating"] = "generating"
STATUS_READY: Literal["ready"] = "ready"
STATUS_FAILED: Literal["failed"] = "failed"
STALE_GENERATION_REASON = "stale"

ANALYSIS_TYPE_BY_KIND: dict[PostActivityKind, str] = {
    "ride": "post_workout",
    "strength": "post_strength",
    "flexibility": "post_flexibility",
    "walk": "post_walk",
}
SUPPORTED_POST_SESSION_ANALYSIS_TYPES: tuple[str, ...] = tuple(ANALYSIS_TYPE_BY_KIND.values())

_CATEGORY_BY_KIND: dict[PostActivityKind, str] = {
    "ride": DAY_CATEGORY_CYCLE,
    "strength": DAY_CATEGORY_WEIGHTS,
    "flexibility": DAY_CATEGORY_FLEXIBILITY,
    "walk": DAY_CATEGORY_WALK,
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def effective_generation_state(
    row: PostActivityGenerationStatus,
    *,
    now: datetime | None = None,
) -> tuple[GenerationState, str | None]:
    """Derive an orphaned in-flight row as failed without writing on GET."""

    if row.status == STATUS_GENERATING:
        observed_at = now or _utcnow()
        threshold = timedelta(minutes=settings.post_activity_generation_stale_after_minutes)
        if row.updated_at <= observed_at - threshold:
            return STATUS_FAILED, STALE_GENERATION_REASON
        return STATUS_GENERATING, row.reason
    if row.status == STATUS_FAILED:
        return STATUS_FAILED, row.reason
    return STATUS_READY, row.reason


class PostActivityGenerationStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, user_id: uuid.UUID, activity_id: uuid.UUID
    ) -> PostActivityGenerationStatus | None:
        return cast(
            PostActivityGenerationStatus | None,
            await self.session.scalar(
                select(PostActivityGenerationStatus).where(
                    PostActivityGenerationStatus.user_id == user_id,
                    PostActivityGenerationStatus.activity_id == activity_id,
                )
            ),
        )

    async def latest_for_workout(
        self, user_id: uuid.UUID, planned_workout_id: uuid.UUID
    ) -> PostActivityGenerationStatus | None:
        return cast(
            PostActivityGenerationStatus | None,
            await self.session.scalar(
                select(PostActivityGenerationStatus)
                .where(
                    PostActivityGenerationStatus.user_id == user_id,
                    PostActivityGenerationStatus.planned_workout_id == planned_workout_id,
                    PostActivityGenerationStatus.analysis_type.in_(
                        SUPPORTED_POST_SESSION_ANALYSIS_TYPES
                    ),
                )
                .order_by(
                    desc(PostActivityGenerationStatus.updated_at),
                    desc(PostActivityGenerationStatus.created_at),
                )
                .limit(1)
            ),
        )

    async def mark(
        self,
        *,
        user_id: uuid.UUID,
        activity_id: uuid.UUID,
        planned_workout_id: uuid.UUID | None,
        subject_date: date,
        analysis_type: str,
        status: GenerationState,
        reason: str | None = None,
        commit: bool = False,
    ) -> PostActivityGenerationStatus:
        row = await self.get(user_id, activity_id)
        if row is None:
            row = PostActivityGenerationStatus(
                user_id=user_id,
                activity_id=activity_id,
                planned_workout_id=planned_workout_id,
                subject_date=subject_date,
                analysis_type=analysis_type,
                status=status,
                reason=reason,
            )
            self.session.add(row)
        else:
            row.planned_workout_id = planned_workout_id
            row.subject_date = subject_date
            row.analysis_type = analysis_type
            row.status = status
            row.reason = reason
            row.updated_at = _utcnow()
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return row


async def _ftp_watts(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    """The user's FTP from the knowledge base, or ``None`` when it is unset.

    Returns ``None`` rather than a default on purpose: Batch 278's bike rule reads
    executed power *against* this number, and guessing it would compare a real ride
    to an invented denominator.
    """
    section = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.section == "profile",
            KnowledgeBase.is_active.is_(True),
        )
    )
    if section is not None and isinstance(section.content, dict):
        ftp = section.content.get("ftpWatts")
        if isinstance(ftp, int) and ftp > 0:
            return ftp
    return None


async def prepare_post_activity_generation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity: Activity,
    subject_date: date,
    kind: PostActivityKind,
    commit: bool = False,
) -> PlannedWorkoutMatch:
    """Complete/link the matching planned session and mark its read in flight.

    Batch 278: the match can now come back *unlinked* with a deviation, when the
    activity describes a materially different session from the one on the plan.
    """

    match = await complete_matched_planned_workout(
        session,
        user_id=user_id,
        subject_date=subject_date,
        category=_CATEGORY_BY_KIND[kind],
        activity=activity,
        ftp_watts=await _ftp_watts(session, user_id),
    )
    await PostActivityGenerationStatusService(session).mark(
        user_id=user_id,
        activity_id=activity.id,
        planned_workout_id=match.planned_workout_id,
        subject_date=subject_date,
        analysis_type=ANALYSIS_TYPE_BY_KIND[kind],
        status=STATUS_GENERATING,
        commit=commit,
    )
    return match


async def mark_post_activity_generation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity_id: uuid.UUID,
    planned_workout_id: uuid.UUID | None,
    subject_date: date,
    kind: PostActivityKind,
    status: GenerationState,
    reason: str | None = None,
    commit: bool = False,
) -> None:
    await PostActivityGenerationStatusService(session).mark(
        user_id=user_id,
        activity_id=activity_id,
        planned_workout_id=planned_workout_id,
        subject_date=subject_date,
        analysis_type=ANALYSIS_TYPE_BY_KIND[kind],
        status=status,
        reason=reason,
        commit=commit,
    )
