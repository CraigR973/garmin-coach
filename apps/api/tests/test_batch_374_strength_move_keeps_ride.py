"""Batch 374 — moving a dumbbell session never moves the day's ride.

At 16:05 UTC on 2 Nov 2026 Mark moved Dumbbells A from Thu 12 Nov to Mon 9 Nov. The strength
row has no Zwift event of its own, so ``swap_day`` fell back to the day's live event, which
was Thursday's sweet spot: it moved that event to Monday and pointed its proposal at the
strength row. The orchestrator moved it back at 17:11 UTC. The rail now takes a day's event
for a session only when the session is a ride and the event is not another live session's.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile
from src.services.executable_coaching import ExecutableCoachingService
from tests.test_executable_coaching import (
    VO2_STRUCTURED,
    _active_all_on,
    _FakeIntervalsClient,
    _seed_profile,
)

THURSDAY, MONDAY = date(2026, 7, 9), date(2026, 7, 6)


def _ride(user_id: uuid.UUID, ride_id: uuid.UUID, day: date) -> PlannedWorkout:
    return PlannedWorkout(
        id=ride_id,
        user_id=user_id,
        workout_date=day,
        version=1,
        title="Sweet Spot (3 × 20 min @ 90%)",
        workout_type="bike_sweet_spot",
        status="planned",
        is_active=True,
        planned_duration_min=80,
        intensity_target="Sweet spot ~88-93% FTP",
        structured_workout=VO2_STRUCTURED,
        source="test",
    )


def _dumbbells_a(user_id: uuid.UUID, a_id: uuid.UUID, day: date) -> PlannedWorkout:
    return PlannedWorkout(
        id=a_id,
        user_id=user_id,
        workout_date=day,
        version=2,
        title="Dumbbells A (legs and back)",
        workout_type="strength_maintenance",
        status="planned",
        is_active=True,
        planned_duration_min=35,
        intensity_target="Dumbbells 3 × 10",
        structured_workout={"summary": "Goblet squat … low hops (2 × 10, soft landings)."},
        source="test",
    )


async def _proposal(session: AsyncSession, user_id: uuid.UUID) -> WorkoutDeliveryProposal:
    [proposal] = (
        (
            await session.execute(
                select(WorkoutDeliveryProposal).where(
                    WorkoutDeliveryProposal.user_id == user_id,
                    WorkoutDeliveryProposal.intervals_event_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return proposal


@pytest.mark.asyncio
async def test_moving_dumbbells_off_a_ride_day_leaves_the_ride_on_zwift(
    db_conn: AsyncConnection,
) -> None:
    """2 Nov's move, replayed: A leaves Thursday, the sweet spot stays on Thursday."""
    user_id, ride_id, a_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([_ride(user_id, ride_id, THURSDAY), _dumbbells_a(user_id, a_id, THURSDAY)])
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THURSDAY, end_date=THURSDAY)
        before = await _proposal(session, user_id)
        event_id = before.intervals_event_id

        moved = await service.swap_day(user, planned_workout_id=a_id, target_date=MONDAY)

        assert moved.workout_date == MONDAY
        assert fake.updates == [] and fake.deletes == []  # no cloud write at all
        after = await _proposal(session, user_id)
        assert (after.intervals_event_id, after.workout_date) == (event_id, THURSDAY)
        assert after.planned_workout_id == ride_id
        assert [w.workout_type for w in await _active_all_on(session, user_id, THURSDAY)] == [
            "bike_sweet_spot"
        ]


@pytest.mark.asyncio
async def test_moving_dumbbells_onto_a_ride_day_leaves_that_ride_on_zwift(
    db_conn: AsyncConnection,
) -> None:
    """The other direction: A arrives on a ride day, which keeps its event."""
    user_id, ride_id, a_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([_ride(user_id, ride_id, THURSDAY), _dumbbells_a(user_id, a_id, MONDAY)])
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THURSDAY, end_date=THURSDAY)
        event_id = (await _proposal(session, user_id)).intervals_event_id

        await service.swap_day(user, planned_workout_id=a_id, target_date=THURSDAY)

        assert fake.updates == [] and fake.deletes == []
        after = await _proposal(session, user_id)
        assert (after.intervals_event_id, after.workout_date, after.planned_workout_id) == (
            event_id,
            THURSDAY,
            ride_id,
        )


@pytest.mark.asyncio
async def test_skipping_dumbbells_on_a_ride_day_never_deletes_the_ride(
    db_conn: AsyncConnection,
) -> None:
    user_id, ride_id, a_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([_ride(user_id, ride_id, THURSDAY), _dumbbells_a(user_id, a_id, THURSDAY)])
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THURSDAY, end_date=THURSDAY)
        await service.skip_workout(user, planned_workout_id=a_id)
        assert fake.deletes == []
        assert (await _proposal(session, user_id)).planned_workout_id == ride_id


@pytest.mark.asyncio
async def test_moving_the_ride_still_moves_its_event(db_conn: AsyncConnection) -> None:
    user_id, ride_id, a_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all([_ride(user_id, ride_id, THURSDAY), _dumbbells_a(user_id, a_id, THURSDAY)])
        await session.commit()

    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=THURSDAY, end_date=THURSDAY)
        event_id = (await _proposal(session, user_id)).intervals_event_id

        await service.swap_day(user, planned_workout_id=ride_id, target_date=MONDAY)

        assert [eid for eid, _ in fake.updates] == [event_id]
        assert [w.title for w in await _active_all_on(session, user_id, THURSDAY)] == [
            "Dumbbells A (legs and back)"
        ]
