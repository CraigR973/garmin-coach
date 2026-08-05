from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.week_ahead import WeekAheadService

WEEK_START = date(2026, 6, 29)
WEEK_END = date(2026, 7, 5)


@pytest.mark.asyncio
async def test_week_ahead_packet_names_plan_mix_hardest_day_and_protecting_night(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    block_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = Profile(
            id=user_id,
            display_name="Week ahead test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(profile)
        await session.flush()
        session.add(
            PlanBlock(
                id=block_id,
                user_id=user_id,
                name="Build 2",
                version=1,
                sequence_index=2,
                block_type="build",
                start_date=WEEK_START,
                end_date=WEEK_END,
            )
        )
        session.add_all(
            [
                PlannedWorkout(
                    user_id=user_id,
                    plan_block_id=block_id,
                    workout_date=date(2026, 6, 30),
                    version=1,
                    title="VO2 Max",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                ),
                PlannedWorkout(
                    user_id=user_id,
                    plan_block_id=block_id,
                    workout_date=date(2026, 7, 2),
                    version=1,
                    title="Sweet Spot",
                    workout_type="bike_sweet_spot",
                    status="planned",
                    is_active=True,
                    planned_duration_min=75,
                ),
                PlannedWorkout(
                    user_id=user_id,
                    plan_block_id=block_id,
                    workout_date=date(2026, 7, 5),
                    version=1,
                    title="Long Z2",
                    workout_type="bike_endurance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=120,
                ),
            ]
        )
        await session.commit()

        packet = await WeekAheadService(session).build(profile, week_start=WEEK_START)

    assert packet["window"] == {
        "kind": "coming_iso_week",
        "startDate": WEEK_START.isoformat(),
        "endDate": WEEK_END.isoformat(),
    }
    assert packet["trainingWeek"]["window"]["kind"] == "coming_iso_week"
    assert packet["blockSummary"]["primaryBlockType"] == "build"
    assert packet["blockSummary"]["hasMidWeekChange"] is False
    assert [item["title"] for item in packet["qualitySessions"]] == ["VO2 Max", "Sweet Spot"]
    assert packet["hardestSession"]["title"] == "VO2 Max"
    assert packet["protectingNight"] == {
        "date": "2026-06-29",
        "weekday": "Monday",
        "protectsWorkoutId": packet["hardestSession"]["id"],
        "protectsWorkoutTitle": "VO2 Max",
    }
    buckets = {item["bucket"]: item for item in packet["weeklyMix"]["buckets"]}
    assert buckets["vo2"]["target"] == 1
    assert buckets["sweet_spot"]["target"] == 1
    assert buckets["z2"]["target"] == 1
    assert packet["coachingContract"]["classificationImpact"] == "none"


@pytest.mark.asyncio
async def test_recovery_week_zero_quality_targets_are_explicit_not_shortfalls(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    block_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = Profile(
            id=user_id,
            display_name="Recovery week test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(profile)
        await session.flush()
        session.add(
            PlanBlock(
                id=block_id,
                user_id=user_id,
                name="Recovery",
                version=1,
                sequence_index=3,
                block_type="recovery",
                start_date=WEEK_START,
                end_date=WEEK_END,
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                plan_block_id=block_id,
                workout_date=date(2026, 7, 1),
                version=1,
                title="Recovery spin",
                workout_type="bike_recovery",
                status="planned",
                is_active=True,
                planned_duration_min=45,
            )
        )
        await session.commit()

        packet = await WeekAheadService(session).build(profile, week_start=WEEK_START)

    assert packet["blockSummary"]["recoveryStructured"] is True
    assert "target=0 quality buckets are not shortfalls" in packet["blockSummary"]["guidance"]
    buckets = {item["bucket"]: item for item in packet["weeklyMix"]["buckets"]}
    assert buckets["vo2"]["target"] == 0
    assert buckets["vo2"]["atRisk"] is False
    assert buckets["sweet_spot"]["target"] == 0
    assert buckets["sweet_spot"]["atRisk"] is False
