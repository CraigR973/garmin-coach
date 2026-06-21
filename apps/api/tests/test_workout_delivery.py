from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import PlannedWorkout
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
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self.payloads.append(payload)
        return IntervalsCreateResult(event_id="evt_123", raw_response={"id": "evt_123"})


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
