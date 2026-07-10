"""Batch 78: outdoor structured workouts deliver to Garmin Connect.

DB-backed; skips locally without ``DATABASE_URL`` (see ``conftest``), runs in CI.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import GarminWorkoutDelivery, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.garmin_sync import GarminScheduledWorkout, GarminSyncError
from src.services.garmin_workout_delivery import (
    STATUS_FAILED,
    STATUS_PUSHED,
    GarminWorkoutDeliveryService,
)

OUTDOOR_STRUCTURED: dict[str, Any] = {
    "format": "bike",
    "delivery": "outdoor",
    "steps": [
        {"label": "Warm-up ramp", "minutes": 10, "ramp": [45, 75]},
        {"label": "Main block", "minutes": 40, "target": "75%"},
        {"label": "Cool-down ramp", "minutes": 5, "ramp": [75, 45]},
    ],
}


class _FakeGarminClient:
    """Records write calls without touching Garmin; sync, like the real client."""

    def __init__(self, *, fail: bool = False) -> None:
        self.uploads: list[tuple[dict[str, Any], date]] = []
        self.deletes: list[tuple[str | None, str | None]] = []
        self.fail = fail
        self._counter = 1000

    def upload_and_schedule_workout(
        self, workout_json: dict[str, Any], calendar_date: date
    ) -> GarminScheduledWorkout:
        if self.fail:
            raise GarminSyncError("garmin upload failed")
        self.uploads.append((workout_json, calendar_date))
        self._counter += 1
        return GarminScheduledWorkout(
            workout_id=f"w{self._counter}", schedule_id=f"s{self._counter}", raw={}
        )

    def delete_scheduled_workout(self, workout_id: str | None, schedule_id: str | None) -> None:
        self.deletes.append((workout_id, schedule_id))


async def _seed_outdoor(
    db_conn: AsyncConnection,
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
    *,
    workout_date: date,
    version: int = 1,
    structured: dict[str, Any] | None = None,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        if await session.get(Profile, user_id) is None:
            session.add(
                Profile(
                    id=user_id,
                    display_name=f"Garmin {user_id.hex[:6]}",
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
                version=version,
                title="Outdoor endurance",
                workout_type="bike_endurance",
                status="planned",
                is_active=True,
                planned_duration_min=55,
                intensity_target="75% FTP",
                structured_workout=structured or OUTDOOR_STRUCTURED,
                source="test",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_outdoor_workout_uploads_and_records_pushed(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 12)
    await _seed_outdoor(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeGarminClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        workout = await session.get(PlannedWorkout, workout_id)
        assert user is not None and workout is not None
        service = GarminWorkoutDeliveryService(session, garmin_client=fake)

        record = await service.reconcile_workout(user, workout, ftp_watts=280)

        assert record is not None
        assert record.status == STATUS_PUSHED
        assert record.garmin_workout_id == "w1001"
        assert record.garmin_schedule_id == "s1001"
        assert record.last_error is None
        assert len(fake.uploads) == 1
        payload, scheduled_date = fake.uploads[0]
        assert scheduled_date == day
        assert payload["sportType"]["sportTypeKey"] == "cycling"


@pytest.mark.asyncio
async def test_same_version_is_idempotent_noop(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 13)
    await _seed_outdoor(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeGarminClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        workout = await session.get(PlannedWorkout, workout_id)
        assert user is not None and workout is not None
        service = GarminWorkoutDeliveryService(session, garmin_client=fake)

        await service.reconcile_workout(user, workout, ftp_watts=280)
        again = await service.reconcile_workout(user, workout, ftp_watts=280)

    assert again is None
    assert len(fake.uploads) == 1  # not re-uploaded


@pytest.mark.asyncio
async def test_edit_new_version_replaces_in_place(db_conn: AsyncConnection) -> None:
    user_id, v1_id, v2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 14)
    await _seed_outdoor(db_conn, user_id, v1_id, workout_date=day, version=1)
    fake = _FakeGarminClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        v1 = await session.get(PlannedWorkout, v1_id)
        assert user is not None and v1 is not None
        service = GarminWorkoutDeliveryService(session, garmin_client=fake)
        await service.reconcile_workout(user, v1, ftp_watts=280)

    # Batch 77 edit: deactivate v1, insert v2 on the same date.
    await _seed_outdoor(db_conn, user_id, v2_id, workout_date=day, version=2)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        v2 = await session.get(PlannedWorkout, v2_id)
        assert user is not None and v2 is not None
        service = GarminWorkoutDeliveryService(session, garmin_client=fake)
        record = await service.reconcile_workout(user, v2, ftp_watts=280)

        assert record is not None
        assert record.planned_workout_id == v2_id
        assert record.planned_workout_version == 2
        assert record.garmin_workout_id == "w1002"  # fresh upload
        # One delivery row per slot (unique user+date) — replaced, not duplicated.
        rows = (
            (
                await session.execute(
                    select(GarminWorkoutDelivery).where(
                        GarminWorkoutDelivery.user_id == user_id,
                        GarminWorkoutDelivery.workout_date == day,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    assert fake.deletes == [("w1001", "s1001")]  # old Garmin workout removed first
    assert len(fake.uploads) == 2


@pytest.mark.asyncio
async def test_upload_failure_is_honest_not_silent(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 15)
    await _seed_outdoor(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeGarminClient(fail=True)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        workout = await session.get(PlannedWorkout, workout_id)
        assert user is not None and workout is not None
        service = GarminWorkoutDeliveryService(session, garmin_client=fake)

        record = await service.reconcile_workout(user, workout, ftp_watts=280)

        assert record is not None
        assert record.status == STATUS_FAILED
        assert record.last_error is not None
        assert "garmin upload failed" in record.last_error
        assert record.garmin_workout_id is None  # nothing live on Garmin


@pytest.mark.asyncio
async def test_non_deliverable_workout_is_skipped(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 7, 16)
    # An empty structured workout is not deliverable — must never upload a guess.
    await _seed_outdoor(
        db_conn, user_id, workout_id, workout_date=day, structured={"format": "bike"}
    )
    fake = _FakeGarminClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        workout = await session.get(PlannedWorkout, workout_id)
        assert user is not None and workout is not None
        service = GarminWorkoutDeliveryService(session, garmin_client=fake)

        record = await service.reconcile_workout(user, workout, ftp_watts=280)

    assert record is None
    assert fake.uploads == []
