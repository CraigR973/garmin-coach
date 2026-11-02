"""Put this week's dumbbell sessions on his watch, when he asks (Batch 340, FC331-01).

One tap on Week sends the next seven days' Dumbbells A and B to Garmin Connect as
strength workouts, each scheduled on its own day, so they sync to his watch beside the
routines he already runs there. It writes to Garmin only when he asks, never on a
schedule, and keeps no record of its own: a workout whose name is already in his Garmin
library is left alone, so a second tap does nothing. Each session's name carries its
date, so a moved or edited session is a new name and goes up again.

The Garmin write goes through the same client and session as the outdoor-ride delivery
(``GarminConnectClient.upload_and_schedule_workout``); tests use a fake.

Batch 368.5 (FC360-07): it keeps a record now. Each placed or failed upload writes one
``strength_watch`` audit row (the session, its day, Garmin's workout and schedule ids or
the error), so Craig and the app can say what is on his watch. And before placing, a
session it put up earlier whose plan row has since moved off that day is taken off the
watch (unscheduled and deleted), so a move leaves one copy, not two.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, PlannedWorkout
from src.models.profile import Profile
from src.services.garmin_strength_export import build_garmin_strength_workout, moves_for
from src.services.garmin_sync import GarminScheduledWorkout

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

WINDOW_DAYS = 7
#: Batch 368.5: one audit row per placed, failed or removed watch workout.
AUDIT_TYPE = "strength_watch"
AUDIT_PROMPT_VERSION = "strength-watch:v1"
STATUS_PLACED = "placed"
STATUS_FAILED = "failed"
STATUS_REMOVED = "removed"


class StrengthWatchClient(Protocol):
    def workout_names(self) -> set[str]: ...

    def upload_and_schedule_workout(
        self, workout_json: dict[str, object], calendar_date: date
    ) -> GarminScheduledWorkout: ...

    def delete_scheduled_workout(self, workout_id: str | None, schedule_id: str | None) -> None: ...


@dataclass(slots=True)
class StrengthWatchResult:
    placed: list[str] = field(default_factory=list)
    already_there: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    #: Batch 368.5: earlier copies taken off his watch because the session moved.
    removed: list[str] = field(default_factory=list)


def watch_name_for(title: str | None, day: date) -> str:
    """The name on his watch: the session and its day, so each week's dose is its own."""

    return f"{(title or 'Dumbbells').split(' (')[0]} · {day.strftime('%a %d %b')}"


def watch_name(workout: PlannedWorkout) -> str:
    return watch_name_for(workout.title, workout.workout_date)


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

    def _audit(
        self,
        player: Profile,
        *,
        day: date,
        status: str,
        name: str,
        planned_workout_id: Any = None,
        **fields: Any,
    ) -> None:
        self.session.add(
            Analysis(
                user_id=player.id,
                activity_id=None,
                analysis_type=AUDIT_TYPE,
                subject_date=day,
                generated_at_utc=datetime.now(UTC).replace(tzinfo=None),
                prompt_version=AUDIT_PROMPT_VERSION,
                verdict=None,
                context_packet={
                    "status": status,
                    "name": name,
                    "plannedWorkoutId": str(planned_workout_id) if planned_workout_id else None,
                    **fields,
                },
                output_markdown="",
                raw_response={},
            )
        )

    async def _remove_superseded(
        self,
        player: Profile,
        *,
        today: date,
        client: StrengthWatchClient,
        result: StrengthWatchResult,
    ) -> None:
        """Take off his watch a session placed earlier whose row has moved off its day."""

        rows = (
            await self.session.execute(
                select(Analysis.subject_date, Analysis.context_packet).where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == AUDIT_TYPE,
                    Analysis.subject_date >= today,
                )
            )
        ).all()
        placed: dict[str, tuple[date, dict[str, Any]]] = {}
        removed: set[str] = set()
        for day, packet in rows:
            if not isinstance(packet, dict) or not isinstance(packet.get("name"), str):
                continue
            if packet.get("status") == STATUS_PLACED:
                placed[packet["name"]] = (day, packet)
            elif packet.get("status") == STATUS_REMOVED:
                removed.add(packet["name"])
        for name, (day, packet) in sorted(placed.items()):
            if name in removed:
                continue
            still_planned = (
                await self.session.execute(
                    select(PlannedWorkout.title).where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date == day,
                    )
                )
            ).scalars()
            if any(
                moves_for(title) is not None and watch_name_for(title, day) == name
                for title in still_planned
            ):
                continue
            try:
                await asyncio.to_thread(
                    client.delete_scheduled_workout,
                    packet.get("workoutId"),
                    packet.get("scheduleId"),
                )
            except Exception as exc:  # noqa: BLE001 - external IO: report it, never hide it
                log.warning("strength_watch_remove_failed", name=name, error=str(exc)[:300])
                continue
            self._audit(player, day=day, status=STATUS_REMOVED, name=name)
            result.removed.append(name)

    async def put_on_watch(
        self, player: Profile, *, today: date, client: StrengthWatchClient
    ) -> StrengthWatchResult:
        result = StrengthWatchResult()
        await self._remove_superseded(player, today=today, client=client, result=result)
        sessions = await self.sessions_ahead(player, today)
        if not sessions:
            await self.session.commit()
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
                scheduled = await asyncio.to_thread(
                    client.upload_and_schedule_workout, payload, workout.workout_date
                )
            except Exception as exc:  # noqa: BLE001 - external IO: report it, never hide it
                log.warning("strength_watch_failed", name=name, error=str(exc)[:300])
                self._audit(
                    player,
                    day=workout.workout_date,
                    status=STATUS_FAILED,
                    name=name,
                    planned_workout_id=workout.id,
                    error=str(exc)[:300],
                )
                result.failed.append(name)
                continue
            self._audit(
                player,
                day=workout.workout_date,
                status=STATUS_PLACED,
                name=name,
                planned_workout_id=workout.id,
                workoutId=scheduled.workout_id,
                scheduleId=scheduled.schedule_id,
            )
            result.placed.append(name)
        await self.session.commit()
        return result
