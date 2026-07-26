from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, PlannedWorkout, PostActivityGenerationStatus
from src.models.profile import Profile, UserRole
from src.services.post_activity_analysis import (
    generate_post_activity_read,
    post_activity_kind,
    prepare_post_activity_read,
)
from src.services.post_flexibility_analysis import SYSTEM_PROMPT as FLEX_PROMPT
from src.services.post_strength_analysis import SYSTEM_PROMPT as STRENGTH_PROMPT
from src.services.post_walk_analysis import SYSTEM_PROMPT as WALK_PROMPT
from src.services.post_workout_analysis import SYSTEM_PROMPT as RIDE_PROMPT


def _activity(
    activity_type: str,
    name: str,
    *,
    duration_sec: float = 3600,
    distance_m: float = 5_000,
    excluded: bool = False,
) -> MagicMock:
    activity = MagicMock(spec=Activity)
    activity.activity_type = activity_type
    activity.activity_name = name
    activity.duration_sec = duration_sec
    activity.distance_m = distance_m
    activity.exclude_from_recovery = excluded
    return activity


@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        (_activity("indoor_cycling", "Indoor ride"), "ride"),
        (_activity("strength_training", "Dumbbells", excluded=True), "strength"),
        (_activity("other", "Morning mobility"), "flexibility"),
        (_activity("walking", "Lunch walk"), "walk"),
    ],
)
def test_post_activity_kind_dispatches_all_four_readers(activity: MagicMock, expected: str) -> None:
    assert post_activity_kind(activity) == expected


@pytest.mark.asyncio
async def test_checkin_dispatch_forces_the_matching_reader_inline() -> None:
    activity = _activity("other", "Morning mobility")
    expected = MagicMock()
    service = MagicMock()
    service.generate_and_store = AsyncMock(return_value=expected)

    with patch(
        "src.services.post_activity_analysis.PostFlexibilityAnalysisService",
        return_value=service,
    ):
        kind, result = await generate_post_activity_read(
            MagicMock(), MagicMock(), activity, force=True
        )

    assert kind == "flexibility"
    assert result is expected
    service.generate_and_store.assert_awaited_once()
    assert service.generate_and_store.await_args.kwargs["force"] is True


def test_every_post_activity_prompt_answers_checkin_questions() -> None:
    for prompt in (RIDE_PROMPT, STRENGTH_PROMPT, FLEX_PROMPT, WALK_PROMPT):
        assert "question" in prompt
        assert "supplied packet" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "activity_type",
        "activity_name",
        "exclude_from_recovery",
        "duration_sec",
        "distance_m",
        "workout_type",
        "expected_kind",
        "expected_analysis_type",
    ),
    [
        (
            "indoor_cycling",
            "Indoor ride",
            False,
            3600,
            20_000,
            "bike_endurance",
            "ride",
            "post_workout",
        ),
        (
            "strength_training",
            "Dumbbells",
            True,
            1800,
            0,
            "strength_maintenance",
            "strength",
            "post_strength",
        ),
        (
            "other",
            "Morning mobility",
            False,
            960,
            0,
            "mobility",
            "flexibility",
            "post_flexibility",
        ),
        (
            "walking",
            "Deliberate walk",
            False,
            2400,
            4_000,
            "walking",
            "walk",
            "post_walk",
        ),
    ],
)
async def test_shared_prepare_links_and_completes_every_post_activity_type(
    db_conn: AsyncConnection,
    activity_type: str,
    activity_name: str,
    exclude_from_recovery: bool,
    duration_sec: float,
    distance_m: float,
    workout_type: str,
    expected_kind: str,
    expected_analysis_type: str,
) -> None:
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 26)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="Post-activity seam",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        workout = PlannedWorkout(
            user_id=user_id,
            workout_date=subject_date,
            version=1,
            title="Planned session",
            workout_type=workout_type,
            status="planned",
            is_active=True,
            structured_workout={},
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=abs(hash((activity_type, workout_type))) % 1_000_000,
            activity_name=activity_name,
            activity_type=activity_type,
            start_utc=datetime(2026, 7, 26, 8, 0),
            duration_sec=duration_sec,
            distance_m=distance_m,
            exclude_from_recovery=exclude_from_recovery,
            raw_summary={},
        )
        session.add(player)
        await session.flush()
        session.add_all([workout, activity])
        await session.flush()

        prepared = await prepare_post_activity_read(session, player, activity, commit=False)
        status = await session.scalar(
            select(PostActivityGenerationStatus).where(
                PostActivityGenerationStatus.activity_id == activity.id
            )
        )

    assert prepared.kind == expected_kind
    assert prepared.planned_workout_id == workout.id
    assert workout.status == "completed"
    assert status is not None
    assert status.analysis_type == expected_analysis_type
    assert status.status == "generating"


@pytest.mark.asyncio
async def test_shared_prepare_claims_distinct_same_kind_sessions(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 26)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=user_id,
            display_name="Two-a-day",
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        workouts = [
            PlannedWorkout(
                user_id=user_id,
                workout_date=subject_date,
                version=index,
                title=f"Strength {index}",
                workout_type="strength_maintenance",
                status="planned",
                is_active=True,
                structured_workout={},
            )
            for index in (1, 2)
        ]
        activities = [
            Activity(
                user_id=user_id,
                garmin_activity_id=20_000 + index,
                activity_name=f"Strength {index}",
                activity_type="strength_training",
                start_utc=datetime(2026, 7, 26, 7 + index, 0),
                duration_sec=1_800,
                distance_m=0,
                exclude_from_recovery=True,
                raw_summary={},
            )
            for index in (1, 2)
        ]
        session.add_all([*workouts, *activities])
        await session.flush()

        first = await prepare_post_activity_read(session, player, activities[0], commit=False)
        second = await prepare_post_activity_read(session, player, activities[1], commit=False)

    assert first.planned_workout_id is not None
    assert second.planned_workout_id is not None
    assert first.planned_workout_id != second.planned_workout_id
