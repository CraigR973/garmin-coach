"""Shared lifecycle + dispatch for check-in-first post-activity reads."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity
from src.models.profile import Profile
from src.services.activity_dates import activity_local_date as _activity_local_date
from src.services.post_activity_state import (
    PostActivityKind,
    mark_post_activity_generation,
    prepare_post_activity_generation,
)
from src.services.post_flexibility_analysis import (
    PostFlexibilityAnalysisService,
    is_flexibility_activity,
)
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService, is_deliberate_walk
from src.services.post_workout_analysis import PostWorkoutAnalysisService, is_ride_activity
from src.services.strength_brief import is_strength_activity


@dataclass(frozen=True)
class PreparedPostActivityRead:
    kind: PostActivityKind
    subject_date: date
    planned_workout_id: uuid.UUID | None


def post_activity_kind(activity: Activity) -> PostActivityKind | None:
    """Return the one post-session reader that owns ``activity``."""

    if is_flexibility_activity(activity):
        return "flexibility"
    if is_strength_activity(activity):
        return "strength"
    if is_deliberate_walk(activity):
        return "walk"
    if is_ride_activity(activity):
        return "ride"
    return None


async def prepare_post_activity_read(
    session: AsyncSession,
    player: Profile,
    activity: Activity,
    *,
    commit: bool = True,
) -> PreparedPostActivityRead:
    """Persist completion + an in-flight state before the model call begins."""

    kind = post_activity_kind(activity)
    if kind is None:
        raise ValueError("Activity does not have a post-workout reader")
    subject_date = _activity_local_date(activity, player.timezone)
    planned_workout_id = await prepare_post_activity_generation(
        session,
        user_id=player.id,
        activity_id=activity.id,
        subject_date=subject_date,
        kind=kind,
        commit=commit,
    )
    return PreparedPostActivityRead(
        kind=kind,
        subject_date=subject_date,
        planned_workout_id=planned_workout_id,
    )


async def mark_prepared_post_activity_failed(
    session: AsyncSession,
    player: Profile,
    activity: Activity,
    prepared: PreparedPostActivityRead,
    *,
    reason: str,
    commit: bool = True,
) -> None:
    await mark_post_activity_generation(
        session,
        user_id=player.id,
        activity_id=activity.id,
        planned_workout_id=prepared.planned_workout_id,
        subject_date=prepared.subject_date,
        kind=prepared.kind,
        status="failed",
        reason=reason,
        commit=commit,
    )


async def generate_post_activity_read(
    session: AsyncSession,
    player: Profile,
    activity: Activity,
    *,
    force: bool = False,
    commit: bool = True,
) -> tuple[PostActivityKind, Any]:
    """Generate the correct read for an activity after its generic check-in."""

    kind = post_activity_kind(activity)
    result: Any
    if kind == "ride":
        result = await PostWorkoutAnalysisService(session).generate_and_store(
            player, activity, force=force, commit=commit
        )
    elif kind == "strength":
        result = await PostStrengthAnalysisService(session).generate_and_store(
            player, activity, force=force, commit=commit
        )
    elif kind == "flexibility":
        result = await PostFlexibilityAnalysisService(session).generate_and_store(
            player, activity, force=force, commit=commit
        )
    elif kind == "walk":
        result = await PostWalkAnalysisService(session).generate_and_store(
            player, activity, force=force, commit=commit
        )
    else:
        raise ValueError("Activity does not have a post-workout reader")
    return kind, result
