from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import ManualEntry, PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile, UserRole
from src.services.plan_actions import PlanActionService, quick_add_options
from src.services.workout_categories import day_state_for_workout_types
from src.services.workout_delivery import STATUS_PUSHED, IntervalsCreateResult


class _FakeIntervalsClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self._counter = 0

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self.payloads.append(payload)
        self._counter += 1
        event_id = f"evt_{self._counter}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(self, event_id: str, payload: dict) -> IntervalsCreateResult:
        self.updates.append((event_id, payload))
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        self.deletes.append(event_id)


async def _seed_user(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    user = Profile(
        id=user_id,
        display_name="Plan Action Test",
        pin_hash="x" * 60,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_workout(
    session: AsyncSession,
    user_id: uuid.UUID,
    workout_date: date,
    *,
    workout_id: uuid.UUID | None = None,
    version: int = 1,
    workout_type: str = "strength_maintenance",
    structured: dict | None = None,
) -> PlannedWorkout:
    workout = PlannedWorkout(
        id=workout_id or uuid.uuid4(),
        user_id=user_id,
        workout_date=workout_date,
        version=version,
        title="Strength maintenance" if workout_type.startswith("strength") else "Endurance ride",
        workout_type=workout_type,
        status="planned",
        is_active=True,
        planned_duration_min=20 if workout_type.startswith("strength") else 45,
        intensity_target="maintenance" if workout_type.startswith("strength") else "Zone 2",
        structured_workout=structured
        or (
            {"format": "strength", "focus": "maintenance"}
            if workout_type.startswith("strength")
            else {
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 5, "target": "easy"},
                    {"label": "Endurance", "minutes": 35, "target": "zone 2"},
                    {"label": "Cool-down", "minutes": 5, "target": "easy"},
                ],
            }
        ),
        source="test",
    )
    session.add(workout)
    await session.flush()
    return workout


def test_day_state_labels_mixed_and_rest() -> None:
    rest = day_state_for_workout_types([])
    assert rest.label == "Rest"
    assert rest.is_rest is True

    mixed = day_state_for_workout_types(["bike_endurance", "strength_maintenance", "mobility"])
    assert mixed.categories == ["cycle", "weights", "flexibility"]
    assert mixed.label == "Cycle + Weights + Flexibility"


@pytest.mark.asyncio
async def test_schedule_groups_live_days_with_explicit_rest(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    monday = date(2026, 8, 10)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(session, user_id, monday, workout_type="bike_endurance")
        await _seed_workout(session, user_id, monday, version=2, workout_type="mobility")
        await session.commit()

        schedule = await PlanActionService(session).schedule(user, start_date=monday, days=3)

    assert [day.date for day in schedule.days] == [monday, date(2026, 8, 11), date(2026, 8, 12)]
    assert schedule.days[0].day_state.label == "Cycle + Flexibility"
    assert len(schedule.days[0].workouts) == 2
    assert schedule.days[1].day_state.label == "Rest"
    assert schedule.days[1].workouts == []


@pytest.mark.asyncio
async def test_add_workout_appends_to_occupied_day_and_bike_reconciles(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 13)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(session, user_id, day, workout_type="strength_maintenance")
        await session.commit()

        added = await PlanActionService(session, intervals_client=fake).add_workout(
            user, workout_date=day, category="cycle"
        )

        workouts = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == day,
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        proposals = (
            (
                await session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.planned_workout_id == added.id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(workouts) == 2
    assert added.version == 2
    assert fake.payloads[0]["name"] == "Endurance ride"
    assert proposals[0].status == STATUS_PUSHED


def test_quick_add_options_lists_selectable_subtypes_per_category() -> None:
    cycle_subtypes = {option.subtype for option in quick_add_options("cycle")}
    weights_subtypes = {option.subtype for option in quick_add_options("weights")}
    flexibility_subtypes = {option.subtype for option in quick_add_options("flexibility")}

    assert cycle_subtypes == {"endurance", "sweet_spot", "recovery"}
    assert weights_subtypes == {"maintenance", "recovery"}
    assert flexibility_subtypes == {"mobility"}

    with pytest.raises(HTTPException):
        quick_add_options("rest")


@pytest.mark.asyncio
async def test_add_workout_honours_chosen_subtype_and_duration(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 24)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()

        added = await PlanActionService(session, intervals_client=fake).add_workout(
            user, workout_date=day, category="cycle", subtype="sweet_spot", duration_min=50
        )

    assert added.workout_type == "bike_sweet_spot"
    assert added.title == "Sweet Spot ride"
    assert added.planned_duration_min == 50
    steps = added.structured_workout["steps"]
    assert sum(step["minutes"] for step in steps) == 50


@pytest.mark.asyncio
async def test_add_workout_rejects_duration_outside_subtype_bounds(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 25)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()

        with pytest.raises(HTTPException):
            await PlanActionService(session).add_workout(
                user, workout_date=day, category="cycle", subtype="recovery", duration_min=120
            )


@pytest.mark.asyncio
async def test_move_ride_onto_flexibility_day_is_category_scoped(db_conn: AsyncConnection) -> None:
    """Batch 65: moving a ride onto a day that only holds a flexibility session is a
    move, not a cross-category swap — the ride joins that day and the flexibility
    stays put, so nothing is dragged back onto the vacated day."""
    user_id = uuid.uuid4()
    monday, wednesday = date(2026, 8, 17), date(2026, 8, 19)
    workout_id = uuid.uuid4()
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(
            session, user_id, monday, workout_id=workout_id, workout_type="bike_endurance"
        )
        await session.commit()
        service = PlanActionService(session, intervals_client=fake)
        await service.executable.reconcile_deliveries(user, start_date=monday, end_date=monday)
        await service.add_workout(user, workout_date=wednesday, category="flexibility")

        moved = await service.swap_workout_into_date(
            user, planned_workout_id=workout_id, target_date=wednesday
        )

        async def _active_on(day: date) -> list[PlannedWorkout]:
            return list(
                (
                    await session.execute(
                        select(PlannedWorkout)
                        .where(
                            PlannedWorkout.user_id == user_id,
                            PlannedWorkout.workout_date == day,
                            PlannedWorkout.is_active.is_(True),
                        )
                        .order_by(PlannedWorkout.version)
                    )
                )
                .scalars()
                .all()
            )

        monday_active = await _active_on(monday)
        wednesday_active = await _active_on(wednesday)

    assert moved.workout_date == wednesday
    # The flexibility is NOT dragged back — Monday is now empty.
    assert monday_active == []
    # Wednesday carries both its flexibility and the moved ride.
    assert sorted(w.workout_type for w in wednesday_active) == ["bike_endurance", "mobility"]
    assert fake.updates  # the ride's Zwift event moved


@pytest.mark.asyncio
async def test_skip_day_skips_every_active_workout(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 20)
    fake = _FakeIntervalsClient()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await _seed_workout(session, user_id, day, workout_type="bike_endurance")
        await _seed_workout(session, user_id, day, version=2, workout_type="mobility")
        await session.commit()

        skipped = await PlanActionService(session, intervals_client=fake).skip_day(
            user, workout_date=day
        )

        rows = (
            (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == day,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(skipped) == 2
    assert {row.status for row in rows} == {"skipped"}


@pytest.mark.asyncio
async def test_record_actual_captures_unplanned_reality(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    day = date(2026, 8, 22)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await _seed_user(session, user_id)
        await session.commit()

        entry = await PlanActionService(session).record_actual(
            user,
            workout_date=day,
            label="Walked instead",
            notes="Easy 40 minutes.",
        )

        stored = await session.get(ManualEntry, entry.id)

    assert stored is not None
    assert stored.planned_workout_id is None
    assert stored.adherence_status == "modified"
    assert stored.actual_workout_json == {"label": "Walked instead", "source": "did_something_else"}
