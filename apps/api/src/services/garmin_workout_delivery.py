"""Deliver an outdoor structured workout to Garmin Connect (Batch 78).

The sibling of the intervals.icu/Zwift rail in ``workout_delivery.py``, kept
deliberately separate so the Garmin write path never touches the queries the live
Zwift rail depends on (Decision #151). Push-on-plan-set parity with the indoor
path: every active *outdoor* bike workout in the window is uploaded + scheduled on
Garmin, idempotently (a slot already carrying its current version is a no-op),
honestly on failure (the row records ``failed`` + ``last_error`` and is retried
next reconcile — never silently dropped, #97), and re-synced in place on edit.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import GarminWorkoutDelivery, PlannedWorkout
from src.models.profile import Profile
from src.services.garmin_sync import GarminConnectClient, GarminScheduledWorkout
from src.services.garmin_workout_export import build_garmin_workout
from src.services.workout_delivery import build_structured_workout_ir

STATUS_PUSHED = "pushed"
STATUS_FAILED = "failed"
STATUS_DELETED = "deleted"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GarminWorkoutClient(Protocol):
    def upload_and_schedule_workout(
        self, workout_json: dict[str, Any], calendar_date: date
    ) -> GarminScheduledWorkout: ...

    def delete_scheduled_workout(self, workout_id: str | None, schedule_id: str | None) -> None: ...


class GarminWorkoutDeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        garmin_client: GarminWorkoutClient | None = None,
    ) -> None:
        self.session = session
        # Lazy: the real authenticated client is only built when an outdoor workout
        # actually needs delivering, so the indoor-only path never logs into Garmin.
        self._garmin_client = garmin_client

    def _client(self) -> GarminWorkoutClient:
        if self._garmin_client is None:
            self._garmin_client = GarminConnectClient()
        return self._garmin_client

    async def delivery_for_date(
        self, user_id: uuid.UUID, workout_date: date
    ) -> GarminWorkoutDelivery | None:
        """The single Garmin delivery record for a slot (unique on user+date).

        Keyed by date so it survives Batch 77 re-versioning — an edit that inserts a
        fresh ``planned_workouts`` row still finds the workout already on Garmin and
        replaces it in place rather than uploading a duplicate.
        """
        return await self.session.scalar(
            select(GarminWorkoutDelivery).where(
                GarminWorkoutDelivery.user_id == user_id,
                GarminWorkoutDelivery.workout_date == workout_date,
            )
        )

    async def deliveries_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[GarminWorkoutDelivery]:
        """All Garmin delivery rows in a date window — for read-only status surfacing."""
        return list(
            (
                await self.session.execute(
                    select(GarminWorkoutDelivery).where(
                        GarminWorkoutDelivery.user_id == user_id,
                        GarminWorkoutDelivery.workout_date >= start_date,
                        GarminWorkoutDelivery.workout_date <= end_date,
                    )
                )
            )
            .scalars()
            .all()
        )

    async def reconcile_workout(
        self,
        player: Profile,
        workout: PlannedWorkout,
        *,
        ftp_watts: int,
        commit: bool = True,
    ) -> GarminWorkoutDelivery | None:
        """Ensure ``workout`` is the live Garmin workout for its slot.

        Returns the delivery row (pushed or failed), or ``None`` when the workout is
        non-deliverable or already current on Garmin.
        """
        try:
            ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
            payload = build_garmin_workout(ir, ftp_watts=ftp_watts)
        except (HTTPException, ValueError):
            return None  # malformed/non-deliverable — skip safely, never a wrong upload

        existing = await self.delivery_for_date(player.id, workout.workout_date)
        if (
            existing is not None
            and existing.status == STATUS_PUSHED
            and existing.planned_workout_id == workout.id
            and existing.planned_workout_version == workout.version
        ):
            return None  # this exact version is already on Garmin — idempotent no-op

        record = existing
        if record is None:
            record = GarminWorkoutDelivery(user_id=player.id, workout_date=workout.workout_date)
            self.session.add(record)

        # Delete-first replace: a partial failure leaves the slot empty (retried next
        # reconcile) rather than two rides on the same calendar day.
        old_workout_id = record.garmin_workout_id
        old_schedule_id = record.garmin_schedule_id
        try:
            if old_workout_id or old_schedule_id:
                await asyncio.to_thread(
                    self._client().delete_scheduled_workout, old_workout_id, old_schedule_id
                )
            scheduled = await asyncio.to_thread(
                self._client().upload_and_schedule_workout, payload, workout.workout_date
            )
        except Exception as exc:  # noqa: BLE001 - external IO; honest failure, never silent (#97)
            self._apply(record, workout, ir, payload, status=STATUS_FAILED, error=str(exc))
            record.garmin_workout_id = None
            record.garmin_schedule_id = None
            await self._finish(commit)
            return record

        self._apply(record, workout, ir, payload, status=STATUS_PUSHED, error=None)
        record.garmin_workout_id = scheduled.workout_id or None
        record.garmin_schedule_id = scheduled.schedule_id or None
        record.pushed_at_utc = _utcnow()
        await self._finish(commit)
        return record

    @staticmethod
    def _apply(
        record: GarminWorkoutDelivery,
        workout: PlannedWorkout,
        ir: dict[str, Any],
        payload: dict[str, Any],
        *,
        status: str,
        error: str | None,
    ) -> None:
        record.planned_workout_id = workout.id
        record.planned_workout_version = workout.version
        record.structured_workout_ir = ir
        record.garmin_payload = payload
        record.status = status
        record.last_error = error

    async def _finish(self, commit: bool) -> None:
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
