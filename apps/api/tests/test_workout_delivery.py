from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import PlannedWorkout, WorkoutDeliveryProposal
from src.models.profile import Profile, UserRole
from src.services.workout_delivery import (
    IntervalsCreateResult,
    WorkoutDeliveryService,
    build_intervals_payload,
    build_structured_workout_ir,
    build_zwo_xml,
)


def _planned_workout(structured_workout: dict) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        user_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        workout_date=date(2026, 6, 23),
        version=3,
        title="VO2 Max Ronnestad 30/15",
        workout_type="bike_vo2",
        status="planned",
        is_active=True,
        planned_duration_min=60,
        intensity_target="105-110% FTP, ERG off",
        structured_workout=structured_workout,
        source="test",
    )


def test_build_structured_workout_ir_expands_cadence_critical_repeats() -> None:
    workout = _planned_workout(
        {
            "format": "bike",
            "steps": [
                {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
                {
                    "label": "Main set",
                    "repeats": 1,
                    "pattern": "13x 30s on / 15s easy",
                    "target": "110% FTP 95rpm",
                },
                {"label": "Cool-down", "minutes": 5, "target": "easy spin"},
            ],
        }
    )

    ir = build_structured_workout_ir(workout, ftp_watts=280)

    assert ir["plannedWorkoutId"] == str(workout.id)
    assert ir["plannedWorkoutVersion"] == 3
    assert ir["cadenceCriticalExpanded"] is True
    assert len(ir["steps"]) == 28
    assert ir["totalDurationSec"] == 600 + (13 * 45) + 300
    assert ir["steps"][1] == {
        "label": "Main set work 1/13",
        "phase": "interval",
        "kind": "steady",
        "durationSec": 30,
        "powerStartPct": 110,
        "powerEndPct": 110,
        "cadenceRpm": 95,
    }
    assert ir["steps"][2]["label"] == "Main set recovery 1/13"
    assert "cadenceRpm" not in ir["steps"][2]


def test_intervals_payload_uses_output_only_calendar_event_shape() -> None:
    workout = _planned_workout(
        {
            "format": "bike",
            "steps": [
                {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
                {"label": "Main set", "repeats": 2, "pattern": "8 min on / 4 min easy"},
            ],
        }
    )

    payload = build_intervals_payload(build_structured_workout_ir(workout))

    assert payload["category"] == "WORKOUT"
    assert payload["start_date_local"] == "2026-06-23T00:00:00"
    assert payload["type"] == "Ride"
    assert payload["name"] == "VO2 Max Ronnestad 30/15"
    assert "- 8m 108%" in payload["description"]
    assert "- 4m 50%" in payload["description"]


def test_zwo_export_is_deterministic_and_uses_flat_steady_steps() -> None:
    workout = _planned_workout(
        {
            "format": "bike",
            "steps": [
                {
                    "label": "Main set",
                    "repeats": 1,
                    "pattern": "2x 30s on / 30s off",
                    "target": "110% FTP 95rpm",
                },
            ],
        }
    )
    ir = build_structured_workout_ir(workout)

    first = build_zwo_xml(ir)
    second = build_zwo_xml(ir)

    assert first == second
    assert "<name>VO2 Max Ronnestad 30/15</name>" in first
    assert first.count("<SteadyState") == 4
    assert 'Duration="30" Power="1.1" Cadence="95"' in first
    assert "<IntervalsT" not in first


def test_non_bike_workouts_are_rejected() -> None:
    workout = _planned_workout({"format": "strength", "steps": [{"label": "Lift", "minutes": 30}]})

    with pytest.raises(HTTPException) as exc_info:
        build_structured_workout_ir(workout)

    assert exc_info.value.status_code == 422
    assert "Only bike workouts" in str(exc_info.value.detail)


class _FakeIntervalsClient:
    def __init__(self, *, fail_update: bool = False, fail_delete: bool = False) -> None:
        self.payloads: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self.fail_update = fail_update
        self.fail_delete = fail_delete
        self._counter = 122

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self.payloads.append(payload)
        self._counter += 1
        event_id = f"evt_{self._counter}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(self, event_id: str, payload: dict) -> IntervalsCreateResult:
        if self.fail_update:
            raise HTTPException(status_code=502, detail="intervals.icu event update failed")
        self.updates.append((event_id, payload))
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        if self.fail_delete:
            raise HTTPException(status_code=502, detail="intervals.icu event delete failed")
        self.deletes.append(event_id)


@pytest.mark.asyncio
async def test_delivery_service_requires_approval_before_push(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    workout_id = uuid.uuid4()
    fake_client = _FakeIntervalsClient()

    async with session_factory() as session:
        user = Profile(
            id=user_id,
            display_name="Delivery Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        workout = PlannedWorkout(
            id=workout_id,
            user_id=user_id,
            workout_date=date(2026, 6, 23),
            version=1,
            title="VO2 Delivery",
            workout_type="bike_vo2",
            status="planned",
            is_active=True,
            planned_duration_min=45,
            intensity_target="110% FTP",
            structured_workout={
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
                    {
                        "label": "Main set",
                        "repeats": 1,
                        "pattern": "2x 30s on / 30s off",
                        "target": "110% FTP 95rpm",
                    },
                ],
            },
            source="test",
        )
        session.add(user)
        await session.flush()
        session.add(workout)
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        service = WorkoutDeliveryService(session, intervals_client=fake_client)
        user = await session.get(Profile, user_id)
        assert user is not None
        proposal = await service.propose(player=user, planned_workout_id=workout_id)

        with pytest.raises(HTTPException) as exc_info:
            await service.push(player=user, proposal_id=proposal.id)

        assert exc_info.value.status_code == 409
        assert fake_client.payloads == []

        approved = await service.approve(player=user, proposal_id=proposal.id)
        assert approved.status == "approved"

        pushed = await service.push(player=user, proposal_id=proposal.id)
        assert pushed.status == "pushed"
        assert pushed.intervals_event_id == "evt_123"
        assert len(fake_client.payloads) == 1


@pytest.mark.asyncio
async def test_list_week_ahead_returns_bike_workouts_with_latest_proposal(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    bike_id = uuid.uuid4()
    strength_id = uuid.uuid4()
    bike2_id = uuid.uuid4()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Week Ahead",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            PlannedWorkout(
                id=bike_id,
                user_id=user_id,
                workout_date=date(2026, 6, 24),
                version=1,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout={
                    "format": "bike",
                    "steps": [
                        {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
                        {"label": "Main set", "repeats": 1, "pattern": "3x 30s on / 30s off"},
                    ],
                },
                source="test",
            )
        )
        session.add(
            PlannedWorkout(
                id=strength_id,
                user_id=user_id,
                workout_date=date(2026, 6, 25),
                version=1,
                title="Strength Maintenance",
                workout_type="strength_maintenance",
                status="planned",
                is_active=True,
                planned_duration_min=40,
                intensity_target="Moderate full-body strength",
                structured_workout={
                    "format": "strength",
                    "steps": [{"label": "Lift", "minutes": 30}],
                },
                source="test",
            )
        )
        session.add(
            PlannedWorkout(
                id=bike2_id,
                user_id=user_id,
                workout_date=date(2026, 6, 26),
                version=1,
                title="Sweet Spot Builder",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                planned_duration_min=75,
                intensity_target="88-94% FTP",
                structured_workout={
                    "format": "bike",
                    "steps": [
                        {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
                        {
                            "label": "Main set",
                            "repeats": 1,
                            "pattern": "8 min on / 4 min easy",
                            "target": "88-94% FTP",
                        },
                    ],
                },
                source="test",
            )
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = WorkoutDeliveryService(session)
        await service.propose(player=user, planned_workout_id=bike_id)

        entries = await service.list_week_ahead(user, start_date=date(2026, 6, 23), days=7)

        by_id = {str(entry.workout.id): entry for entry in entries}
        # Strength days are not deliverable, so they are excluded.
        assert set(by_id) == {str(bike_id), str(bike2_id)}
        assert by_id[str(bike_id)].proposal is not None
        assert by_id[str(bike_id)].proposal.status == "proposed"
        assert by_id[str(bike2_id)].proposal is None


# ---------------------------------------------------------------------------
# Batch 29 — replace / move / delete re-sync primitives
# ---------------------------------------------------------------------------

_BIKE_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
        {"label": "Main set", "repeats": 1, "pattern": "2x 30s on / 30s off", "target": "110% FTP"},
    ],
}


async def _seed_bike_workout(
    db_conn: AsyncConnection,
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
    *,
    workout_date: date = date(2026, 6, 24),
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        if await session.get(Profile, user_id) is None:
            session.add(
                Profile(
                    id=user_id,
                    display_name=f"Rail {user_id.hex[:6]}",
                    pin_hash="x" * 60,
                    role=UserRole.admin,
                    timezone="Europe/London",
                    is_active=True,
                )
            )
            await session.flush()
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=workout_date,
                version=1,
                title="VO2 Builder",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=45,
                intensity_target="110% FTP",
                structured_workout=_BIKE_STRUCTURED,
                source="test",
            )
        )
        await session.commit()


async def _deliver_baseline(
    session: AsyncSession,
    fake_client: _FakeIntervalsClient,
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
):
    """Push-on-plan-set a baseline event and return the live proposal."""
    service = WorkoutDeliveryService(session, intervals_client=fake_client)
    user = await session.get(Profile, user_id)
    assert user is not None
    proposal = await service.propose(player=user, planned_workout_id=workout_id)
    workout = await service._planned_workout(user_id, workout_id)
    ir = build_structured_workout_ir(workout)
    return service, await service.create_event(proposal=proposal, ir=ir)


@pytest.mark.asyncio
async def test_create_event_delivers_baseline_without_approval(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike_workout(db_conn, user_id, workout_id)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        _, proposal = await _deliver_baseline(session, fake, user_id, workout_id)

        # Delivered straight to "pushed" with no approval step (Decision #99 baseline).
        assert proposal.status == "pushed"
        assert proposal.intervals_event_id == "evt_123"
        assert proposal.approved_at_utc is None
        assert len(fake.payloads) == 1
        assert fake.updates == [] and fake.deletes == []


@pytest.mark.asyncio
async def test_replace_event_updates_in_place_without_duplicating(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike_workout(db_conn, user_id, workout_id)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        service, proposal = await _deliver_baseline(session, fake, user_id, workout_id)
        event_id = proposal.intervals_event_id

        new_ir = dict(proposal.structured_workout_ir)
        new_ir["name"] = "Amber-adjusted: VO2 Builder"
        replaced = await service.replace_event(proposal=proposal, ir=new_ir)

        assert replaced.id == proposal.id  # same proposal, no duplicate
        assert replaced.intervals_event_id == event_id  # event keeps its identity
        assert replaced.structured_workout_ir["name"] == "Amber-adjusted: VO2 Builder"
        assert replaced.intervals_payload["name"] == "Amber-adjusted: VO2 Builder"
        # One create (baseline) + one in-place update, never a second create.
        assert len(fake.payloads) == 1
        assert [eid for eid, _ in fake.updates] == [event_id]


@pytest.mark.asyncio
async def test_replace_event_failure_keeps_local_state_honest(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike_workout(db_conn, user_id, workout_id)
    fake = _FakeIntervalsClient(fail_update=True)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        service, proposal = await _deliver_baseline(session, fake, user_id, workout_id)
        original_name = proposal.structured_workout_ir["name"]

        new_ir = dict(proposal.structured_workout_ir)
        new_ir["name"] = "Edited never-landed"
        with pytest.raises(HTTPException) as exc_info:
            await service.replace_event(proposal=proposal, ir=new_ir)
        assert exc_info.value.status_code == 502

    # Re-read from a fresh session: the failed cloud write must not have been
    # persisted as if it landed (Decision #97), but the error is recorded.
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        reread = await session.get(WorkoutDeliveryProposal, proposal.id)
        assert reread is not None
        assert reread.structured_workout_ir["name"] == original_name
        assert reread.status == "pushed"
        assert reread.last_error is not None


@pytest.mark.asyncio
async def test_move_event_updates_date_in_place(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike_workout(db_conn, user_id, workout_id, workout_date=date(2026, 6, 24))
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        service, proposal = await _deliver_baseline(session, fake, user_id, workout_id)
        event_id = proposal.intervals_event_id

        moved = await service.move_event(proposal=proposal, new_date=date(2026, 6, 27))

        assert moved.workout_date == date(2026, 6, 27)
        assert moved.intervals_event_id == event_id
        assert moved.intervals_payload["start_date_local"] == "2026-06-27T00:00:00"
        assert [eid for eid, _ in fake.updates] == [event_id]
        assert len(fake.payloads) == 1  # moved, not recreated


@pytest.mark.asyncio
async def test_delete_event_removes_and_clears_live_pointer(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike_workout(db_conn, user_id, workout_id, workout_date=date(2026, 6, 24))
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        service, proposal = await _deliver_baseline(session, fake, user_id, workout_id)
        event_id = proposal.intervals_event_id

        # Before delete the slot resolves to the live event.
        assert await service.latest_delivered_for_date(user_id, date(2026, 6, 24)) is not None

        deleted = await service.delete_event(proposal=proposal)
        assert deleted.status == "deleted"
        assert fake.deletes == [event_id]

        # The slot no longer resolves to a live event, so a re-create is possible.
        assert await service.latest_delivered_for_date(user_id, date(2026, 6, 24)) is None


@pytest.mark.asyncio
async def test_delete_event_failure_keeps_local_state_honest(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    await _seed_bike_workout(db_conn, user_id, workout_id)
    fake = _FakeIntervalsClient(fail_delete=True)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        service, proposal = await _deliver_baseline(session, fake, user_id, workout_id)

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_event(proposal=proposal)
        assert exc_info.value.status_code == 502

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        reread = await session.get(WorkoutDeliveryProposal, proposal.id)
        assert reread is not None
        # The cloud delete failed, so the event is still considered live locally.
        assert reread.status == "pushed"
        assert reread.last_error is not None
