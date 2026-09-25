"""Tests for holiday pause/resume (Batch 15, reworked by Batch 290).

1. Recovery-week equivalent treatment (planned workouts skipped).
2. A holiday ends by itself on its end date, so a new one can be set.
3. Resume means "back early": it shortens (or cancels) the window and restores
   the sessions the pause skipped from the return day on — and touches nothing
   else. Batch 15's template regeneration of the week after is gone.
4. KB versioning of the holiday window.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import KnowledgeBase, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.holiday_pause import (
    HOLIDAY_PAUSE_SOURCE,
    HOLIDAY_RESUME_SOURCE,
    KB_SECTION,
    HolidayPauseService,
    HolidayWindow,
    active_holiday_window_for_date,
    holiday_windows_away_overnight,
    holiday_windows_covering_date,
    is_build1,
    overnight_away_window_for_date,
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


def test_a_holiday_runs_until_its_end_date_and_then_ends_by_itself() -> None:
    """Batch 290: Mark's 12-16 Jul window was still "active" on 24 Sep."""
    july = HolidayWindow(
        start_date=date(2026, 7, 12),
        end_date=date(2026, 7, 16),
        paused_at_utc=datetime(2026, 7, 10, 19, 31),
    )
    assert july.is_active_on(date(2026, 7, 12))
    assert july.is_active_on(date(2026, 7, 16))  # the last day is still holiday
    assert not july.is_active_on(date(2026, 7, 17))
    assert not july.is_active_on(date(2026, 9, 24))
    assert july.is_active_on(date(2026, 7, 1))  # set in advance, not yet started
    closed = HolidayWindow(
        start_date=date(2026, 7, 12),
        end_date=date(2026, 7, 16),
        paused_at_utc=datetime(2026, 7, 10, 19, 31),
        resumed_at_utc=datetime(2026, 7, 14, 8, 0),
    )
    assert not closed.is_active_on(date(2026, 7, 14))


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


def test_overnight_away_helpers_are_end_exclusive() -> None:
    active = HolidayWindow(
        start_date=date(2026, 7, 12),
        end_date=date(2026, 7, 16),
        paused_at_utc=datetime(2026, 7, 11, 18, 0),
    )

    assert holiday_windows_away_overnight([active], date(2026, 7, 12)) == [active]
    assert holiday_windows_away_overnight([active], date(2026, 7, 15)) == [active]
    assert holiday_windows_away_overnight([active], date(2026, 7, 16)) == []
    assert overnight_away_window_for_date([active], date(2026, 7, 15)) is active
    assert overnight_away_window_for_date([active], date(2026, 7, 16)) is None


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
            await service.pause(user, next_start, next_end, today=HOLIDAY_START)
        assert exc_info.value.status_code == 409


# ----------------------------------------------------------
# Batch 290 — a holiday ends by itself; resume never rewrites the plan
# ----------------------------------------------------------


async def _active_rows(session: AsyncSession, user_id: uuid.UUID) -> dict[date, PlannedWorkout]:
    rows = (
        (
            await session.execute(
                select(PlannedWorkout).where(
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.workout_date: row for row in rows}


async def _stored_windows(db_conn: AsyncConnection, user_id: uuid.UUID) -> list[dict[str, str]]:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == KB_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        assert kb is not None
        return list(kb.content["windows"])


@pytest.mark.asyncio
async def test_a_new_holiday_can_be_set_once_the_old_one_has_ended(
    db_conn: AsyncConnection,
) -> None:
    """The production case: an unresumed July holiday blocked a new one in September."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END, today=date(2026, 7, 10))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        assert await service.get_active_window(user, today=HOLIDAY_END) is not None
        assert await service.get_active_window(user, today=HOLIDAY_END + timedelta(days=1)) is None
        result = await service.pause(
            user, date(2026, 10, 1), date(2026, 10, 5), today=date(2026, 9, 25)
        )
        assert result.window.start_date == date(2026, 10, 1)

    assert [w["startDate"] for w in await _stored_windows(db_conn, user_id)] == [
        HOLIDAY_START.isoformat(),
        "2026-10-01",
    ]


@pytest.mark.asyncio
async def test_resume_after_the_holiday_ended_is_refused_and_rewrites_nothing(
    db_conn: AsyncConnection,
) -> None:
    """Pressing Resume on a stale window must not reach the plan at all."""
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    after = HOLIDAY_END + timedelta(days=1)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(_planned(user_id, after, "bike_sweet_spot"))
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END, today=date(2026, 7, 10))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        with pytest.raises(HTTPException) as exc_info:
            await service.resume(user, today=date(2026, 9, 25))
        assert exc_info.value.status_code == 404
        rows = await _active_rows(session, user_id)
        assert rows[after].version == 1
        assert rows[after].source == "test"


@pytest.mark.asyncio
async def test_resume_mid_holiday_restores_from_the_return_day_and_nothing_else(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    before = HOLIDAY_START - timedelta(days=1)
    early = [HOLIDAY_START, HOLIDAY_START + timedelta(days=2)]  # 13, 15 Jul
    back = HOLIDAY_START + timedelta(days=4)  # 17 Jul: he comes home
    late = [back, HOLIDAY_START + timedelta(days=6)]  # 17, 19 Jul
    after = HOLIDAY_END + timedelta(days=1)  # 21 Jul, the week after
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [_planned(user_id, day, "bike_endurance") for day in (before, *early, *late, after)]
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END, today=date(2026, 7, 10))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        result = await service.resume(user, today=back)
        assert result.restored_count == 2
        assert result.cancelled is False
        assert result.window.end_date == back - timedelta(days=1)
        assert result.window.resumed_at_utc is not None

        rows = await _active_rows(session, user_id)
        for day in late:
            assert rows[day].status == "planned"
            assert rows[day].source == HOLIDAY_RESUME_SOURCE
            assert rows[day].version == 3
        for day in early:
            assert rows[day].status == "skipped"
            assert rows[day].source == HOLIDAY_PAUSE_SOURCE
        for day in (before, after):
            assert rows[day].version == 1
            assert rows[day].source == "test"

    stored = await _stored_windows(db_conn, user_id)
    assert stored[0]["endDate"] == (back - timedelta(days=1)).isoformat()
    assert stored[0]["resumedAtUtc"] is not None


@pytest.mark.asyncio
async def test_resume_before_the_holiday_starts_cancels_it(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    inside = [HOLIDAY_START, HOLIDAY_END]
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([_planned(user_id, day, "bike_vo2") for day in inside])
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        await service.pause(user, HOLIDAY_START, HOLIDAY_END, today=date(2026, 7, 10))

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = HolidayPauseService(session)
        result = await service.resume(user, today=date(2026, 7, 11))
        assert result.cancelled is True
        assert result.restored_count == 2
        rows = await _active_rows(session, user_id)
        assert all(rows[day].status == "planned" for day in inside)

    assert await _stored_windows(db_conn, user_id) == []


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
