"""Tests for Batch 15 holiday pause/resume.

Covers the four acceptance pillars:
  1. Recovery-week equivalent treatment (planned workouts skipped).
  2. Build1 → Build2 block continuation on return.
  3. Build2 → repeat Build1 block continuation on return.
  4. KB versioning of the holiday window.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.holiday_pause import (
    HOLIDAY_PAUSE_SOURCE,
    HOLIDAY_RESUME_SOURCE,
    KB_SECTION,
    HolidayPauseService,
    HolidayWindow,
    active_holiday_window_for_date,
    continuation_label,
    continuation_week_number,
    holiday_windows_covering_date,
    is_build1,
)

# ---------------------------------------------------------------------------
# Pure-function tests (no DB)
# ---------------------------------------------------------------------------


def test_is_build1_identifies_first_in_pair() -> None:
    assert is_build1(1) is True
    assert is_build1(2) is False
    assert is_build1(4) is True
    assert is_build1(5) is False
    assert is_build1(7) is True
    assert is_build1(8) is False
    assert is_build1(10) is True
    assert is_build1(11) is False


def test_continuation_label_build1_gives_build2() -> None:
    assert continuation_label(1, "build") == "Build2"
    assert continuation_label(4, "build") == "Build2"
    assert continuation_label(7, "build") == "Build2"
    assert continuation_label(10, "build") == "Build2"


def test_continuation_label_build2_gives_build1() -> None:
    assert continuation_label(2, "build") == "Build1"
    assert continuation_label(5, "build") == "Build1"
    assert continuation_label(8, "build") == "Build1"
    assert continuation_label(11, "build") == "Build1"


def test_continuation_label_non_build_gives_build1() -> None:
    assert continuation_label(3, "recovery") == "Build1"
    assert continuation_label(12, "taper") == "Build1"


def test_continuation_week_number_build1_gives_next() -> None:
    assert continuation_week_number(1, "build") == 2
    assert continuation_week_number(4, "build") == 5
    assert continuation_week_number(7, "build") == 8


def test_continuation_week_number_build2_gives_previous() -> None:
    assert continuation_week_number(2, "build") == 1
    assert continuation_week_number(5, "build") == 4
    assert continuation_week_number(8, "build") == 7


def test_continuation_week_number_non_build_gives_one() -> None:
    assert continuation_week_number(3, "recovery") == 1


def test_holiday_date_helpers_keep_history_but_only_active_window_means_away() -> None:
    subject_date = date(2026, 7, 12)
    resumed = HolidayWindow(
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 14),
        paused_at_utc=datetime(2026, 7, 9, 12, 0),
        resumed_at_utc=datetime(2026, 7, 11, 12, 0),
    )
    active = HolidayWindow(
        start_date=date(2026, 7, 12),
        end_date=date(2026, 7, 20),
        paused_at_utc=datetime(2026, 7, 11, 18, 0),
    )

    assert holiday_windows_covering_date([resumed, active], subject_date) == [resumed, active]
    assert active_holiday_window_for_date([resumed, active], subject_date) is active
    assert active_holiday_window_for_date([resumed], subject_date) is None
    assert active_holiday_window_for_date([active], date(2026, 7, 21)) is None


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------

WEEK_START = date(2026, 7, 6)  # a Monday
HOLIDAY_START = date(2026, 7, 13)
HOLIDAY_END = date(2026, 7, 20)
POST_WEEK = date(2026, 7, 20)


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Holiday Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


def _planned(
    user_id: uuid.UUID,
    workout_date: date,
    workout_type: str,
    *,
    plan_block_id: uuid.UUID | None = None,
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_block_id=plan_block_id,
        workout_date=workout_date,
        version=1,
        title=f"{workout_type} on {workout_date}",
        workout_type=workout_type,
        status="planned",
        is_active=True,
        planned_duration_min=60,
        intensity_target="Zone 2",
        structured_workout={"format": "bike", "steps": []},
        source="test",
    )


def _block(
    user_id: uuid.UUID,
    seq: int,
    block_type: str,
    start: date,
) -> PlanBlock:
    return PlanBlock(
        id=uuid.uuid4(),
        user_id=user_id,
        name=f"Week {seq:02d} {block_type.title()}",
        version=1,
        sequence_index=seq,
        block_type=block_type,
        start_date=start,
        end_date=start + timedelta(days=6),
        goals_json={},
        raw_plan={},
    )


# ----------------------------------------------------------
# 15.1 — recovery-week equivalent: workouts skipped
# ----------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_marks_workouts_as_skipped(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                _planned(user_id, HOLIDAY_START, "bike_vo2"),
                _planned(user_id, HOLIDAY_START + timedelta(days=2), "bike_sweet_spot"),
                _planned(user_id, HOLIDAY_START - timedelta(days=1), "bike_endurance"),
            ]
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)

        result = await service.pause(user, HOLIDAY_START, HOLIDAY_END)

        assert result.skipped_count == 2  # only the two inside the window

        active = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= HOLIDAY_START,
                        PlannedWorkout.workout_date <= HOLIDAY_END,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert all(w.status == "skipped" for w in active)
        assert all(w.source == HOLIDAY_PAUSE_SOURCE for w in active)
        assert all(w.version == 2 for w in active)


@pytest.mark.asyncio
async def test_pause_stores_kb_window(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == KB_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert kb is not None
        windows = kb.content["windows"]
        assert len(windows) == 1
        assert windows[0]["startDate"] == HOLIDAY_START.isoformat()
        assert windows[0]["endDate"] == HOLIDAY_END.isoformat()
        assert windows[0]["resumedAtUtc"] is None


@pytest.mark.asyncio
async def test_double_pause_raises_conflict(db_conn: AsyncConnection) -> None:
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        with pytest.raises(HTTPException) as exc_info:
            next_start = HOLIDAY_START + timedelta(days=7)
            next_end = HOLIDAY_END + timedelta(days=7)
            await service.pause(user, next_start, next_end)
        assert exc_info.value.status_code == 409


# ----------------------------------------------------------
# 15.2 — Build1 → Build2 continuation
# ----------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_build1_continues_to_build2(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    pre_block_id = uuid.uuid4()
    post_block_id = uuid.uuid4()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        pre_block = PlanBlock(
            id=pre_block_id,
            user_id=user_id,
            name="Week 04 Build",
            version=1,
            sequence_index=4,  # Build1 (4-1)%3 == 0
            block_type="build",
            start_date=WEEK_START,
            end_date=WEEK_START + timedelta(days=6),
            goals_json={},
            raw_plan={},
        )
        post_block = PlanBlock(
            id=post_block_id,
            user_id=user_id,
            name="Week 05 Build",
            version=1,
            sequence_index=5,
            block_type="build",
            start_date=POST_WEEK,
            end_date=POST_WEEK + timedelta(days=6),
            goals_json={},
            raw_plan={},
        )
        session.add_all([pre_block, post_block])
        # Add a planned workout in the post-holiday block to verify versioning
        post_date = POST_WEEK + timedelta(days=1)
        session.add(_planned(user_id, post_date, "bike_vo2", plan_block_id=post_block_id))
        await session.commit()

    # First pause so we have an active window
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END)

    # Now resume
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        result = await service.resume(user)

        assert result.continuation_label == "Build2"
        assert result.regenerated_count > 0

        # The first post-holiday week now has new workouts from the continuation template
        active = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= POST_WEEK,
                        PlannedWorkout.workout_date <= POST_WEEK + timedelta(days=6),
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(w.source == HOLIDAY_RESUME_SOURCE for w in active)
        # At least one regenerated workout replaced a pre-existing version
        assert any(w.version > 1 for w in active if w.source == HOLIDAY_RESUME_SOURCE)


# ----------------------------------------------------------
# 15.3 — Build2 → repeat Build1 continuation
# ----------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_build2_repeats_build1(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    pre_block_id = uuid.uuid4()
    post_block_id = uuid.uuid4()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        pre_block = PlanBlock(
            id=pre_block_id,
            user_id=user_id,
            name="Week 05 Build",
            version=1,
            sequence_index=5,  # Build2 (5-1)%3 == 1
            block_type="build",
            start_date=WEEK_START,
            end_date=WEEK_START + timedelta(days=6),
            goals_json={},
            raw_plan={},
        )
        post_block = PlanBlock(
            id=post_block_id,
            user_id=user_id,
            name="Week 06 Recovery",
            version=1,
            sequence_index=6,
            block_type="build",  # a build block is what we resume into
            start_date=POST_WEEK,
            end_date=POST_WEEK + timedelta(days=6),
            goals_json={},
            raw_plan={},
        )
        session.add_all([pre_block, post_block])
        post_date = POST_WEEK + timedelta(days=1)
        session.add(_planned(user_id, post_date, "bike_endurance", plan_block_id=post_block_id))
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        result = await service.resume(user)

        assert result.continuation_label == "Build1"
        assert result.regenerated_count > 0

        active = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= POST_WEEK,
                        PlannedWorkout.workout_date <= POST_WEEK + timedelta(days=6),
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(w.source == HOLIDAY_RESUME_SOURCE for w in active)


@pytest.mark.asyncio
async def test_resume_marks_window_resumed(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        result = await service.resume(user)

        assert result.window.resumed_at_utc is not None
        assert result.window.is_active is False

    # KB should show resumed_at_utc set
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == KB_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert kb is not None
        windows = kb.content["windows"]
        assert len(windows) == 1
        assert windows[0]["resumedAtUtc"] is not None


@pytest.mark.asyncio
async def test_resume_without_active_holiday_raises(db_conn: AsyncConnection) -> None:
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        with pytest.raises(HTTPException) as exc_info:
            await service.resume(user)
        assert exc_info.value.status_code == 404
