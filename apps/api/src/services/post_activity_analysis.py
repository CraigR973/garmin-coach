"""Shared dispatch for check-in-first post-activity reads (Batch 87)."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity
from src.models.profile import Profile
from src.services.post_flexibility_analysis import (
    PostFlexibilityAnalysisService,
    is_flexibility_activity,
)
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService, is_deliberate_walk
from src.services.post_workout_analysis import PostWorkoutAnalysisService, is_ride_activity
from src.services.strength_brief import is_strength_activity

PostActivityKind = Literal["ride", "strength", "flexibility", "walk"]


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
