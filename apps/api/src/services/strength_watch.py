"""Put this week's dumbbell sessions on his watch, when he asks (Batch 340, FC331-01).

One tap on Week sends the next seven days' Dumbbells A and B to Garmin Connect as
strength workouts, each scheduled on its own day, so they sync to his watch beside the
routines he already runs there. It writes to Garmin only when he asks, never on a
schedule, and keeps no record of its own: a workout whose name is already in his Garmin
library is left alone, so a second tap does nothing. Each session's name carries its
date, so a moved or edited session is a new name and goes up again.

The Garmin write goes through the same client and session as the outdoor-ride delivery
(``GarminConnectClient.upload_and_schedule_workout``); tests use a fake.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import PlannedWorkout
from src.models.profile import Profile
from src.services.garmin_strength_export import build_garmin_strength_workout, moves_for
from src.services.garmin_sync import GarminScheduledWorkout

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

WINDOW_DAYS = 7


class StrengthWatchClient(Protocol):
    def workout_names(self) -> set[str]: ...

    def upload_and_schedule_workout(
        self, workout_json: dict[str, object], calendar_date: date
    ) -> GarminScheduledWorkout: ...


@dataclass(slots=True)
class StrengthWatchResult:
    placed: list[str] = field(default_factory=list)
    already_there: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def watch_name(workout: PlannedWorkout) -> str:
    """The name on his watch: the session and its day, so each week's dose is its own."""

    title = (workout.title or "Dumbbells").split(" (")[0]
    return f"{title} · {workout.workout_date.strftime('%a %d %b')}"


class StrengthWatchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sessions_ahead(self, player: Profile, today: date) -> list[PlannedWorkout]:
        """The next seven days' Dumbbells A and B, still to do."""

        rows = (
            await self.session.execute(
                select(PlannedWorkout)
                .where(
                    PlannedWorkout.user_id == player.id,
                    PlannedWorkout.is_active.is_(True),
                    PlannedWorkout.status == "planned",
                    PlannedWorkout.workout_date >= today,
                    PlannedWorkout.workout_date < today + timedelta(days=WINDOW_DAYS),
                )
                .order_by(PlannedWorkout.workout_date)
            )
        ).scalars()
        return [row for row in rows if moves_for(row.title) is not None]

    async def put_on_watch(
        self, player: Profile, *, today: date, client: StrengthWatchClient
    ) -> StrengthWatchResult:
        result = StrengthWatchResult()
        sessions = await self.sessions_ahead(player, today)
        if not sessions:
            return result
        existing = await asyncio.to_thread(client.workout_names)
        for workout in sessions:
            name = watch_name(workout)
            if name in existing:
                result.already_there.append(name)
                continue
            moves = moves_for(workout.title)
            assert moves is not None
            # Plan No. 3's rows predate the hops (Batch 340.3): the watch holds what his
            # plan row holds, so a row that names no hops sends none.
            summary = str((workout.structured_workout or {}).get("summary") or "")
            if "hops" not in summary.lower():
                moves = tuple(move for move in moves if move.category != "PLYO")
            try:
                payload = build_garmin_strength_workout(
                    name=name, moves=moves, intensity_target=workout.intensity_target
                )
                await asyncio.to_thread(
                    client.upload_and_schedule_workout, payload, workout.workout_date
                )
            except Exception as exc:  # noqa: BLE001 - external IO: report it, never hide it
                log.warning("strength_watch_failed", name=name, error=str(exc)[:300])
                result.failed.append(name)
                continue
            result.placed.append(name)
        return result
