"""Forward-looking week packet for proactive review guidance (Batch 186)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import PlanBlock, PlannedWorkout
from src.models.profile import Profile
from src.services.training_week import TrainingWeekService
from src.services.weekly_mix import MixSession, summarize_weekly_mix
from src.services.weekly_restructure import (
    CATEGORY_ENDURANCE,
    CATEGORY_RECOVERY,
    CATEGORY_SWEET_SPOT,
    CATEGORY_TEMPO,
    CATEGORY_THRESHOLD,
    CATEGORY_VO2,
    HARD_CATEGORIES,
    categorize,
)
from src.services.workout_completion import WORKOUT_STATUS_COMPLETED

_HARDNESS_RANK = {
    CATEGORY_VO2: 50,
    CATEGORY_THRESHOLD: 45,
    CATEGORY_SWEET_SPOT: 40,
    CATEGORY_TEMPO: 30,
    CATEGORY_ENDURANCE: 20,
    CATEGORY_RECOVERY: 10,
}


class WeekAheadService:
    """Assemble the coming Monday-Sunday plan context without mutating it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        player: Profile,
        *,
        week_start: date,
    ) -> dict[str, Any]:
        week_end = week_start + timedelta(days=6)
        planned = await self._active_planned_workouts(player.id, week_start, week_end)
        blocks = await self._plan_blocks(player.id, week_start, week_end)
        training_week = await TrainingWeekService(self.session).build_window(
            player,
            start_date=week_start,
            end_date=week_end,
            subject_date=week_start,
            window_kind="coming_iso_week",
        )
        mix = summarize_weekly_mix(
            [
                MixSession(
                    workout_date=workout.workout_date,
                    workout_type=workout.workout_type,
                    completed=workout.status == WORKOUT_STATUS_COMPLETED,
                )
                for workout in planned
                if workout.workout_type.startswith("bike_")
            ],
            subject_date=week_start,
        )
        quality_sessions = [
            _workout_packet(workout)
            for workout in planned
            if categorize(workout.workout_type) in HARD_CATEGORIES and workout.status == "planned"
        ]
        hardest = _hardest_session(planned)
        return {
            "packetType": "week_ahead",
            "window": {
                "kind": "coming_iso_week",
                "startDate": week_start.isoformat(),
                "endDate": week_end.isoformat(),
            },
            "trainingWeek": training_week,
            "planBlocks": [
                _block_packet(block, week_start=week_start, week_end=week_end) for block in blocks
            ],
            "blockSummary": _block_summary(blocks, week_start=week_start, week_end=week_end),
            "weeklyMix": mix.to_packet(),
            "qualitySessions": quality_sessions,
            "hardestSession": hardest,
            "protectingNight": _protecting_night(hardest),
            "coachingContract": {
                "classificationImpact": "none",
                "delivery": "folded_into_weekly_review",
                "proposalPolicy": "explanatory_only_no_plan_change",
                "planChangesStayOn": "propose_confirm",
            },
        }

    async def _active_planned_workouts(
        self,
        user_id: uuid.UUID,
        week_start: date,
        week_end: date,
    ) -> list[PlannedWorkout]:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= week_start,
                        PlannedWorkout.workout_date <= week_end,
                    )
                    .order_by(
                        PlannedWorkout.workout_date.asc(),
                        PlannedWorkout.version.desc(),
                        PlannedWorkout.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _plan_blocks(
        self,
        user_id: uuid.UUID,
        week_start: date,
        week_end: date,
    ) -> list[PlanBlock]:
        rows = (
            (
                await self.session.execute(
                    select(PlanBlock)
                    .where(
                        PlanBlock.user_id == user_id,
                        PlanBlock.start_date <= week_end,
                        PlanBlock.end_date >= week_start,
                    )
                    .order_by(
                        PlanBlock.start_date.asc(),
                        PlanBlock.version.desc(),
                        PlanBlock.name.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        latest: dict[tuple[str, date, date], PlanBlock] = {}
        for row in rows:
            key = (row.name, row.start_date, row.end_date)
            if key not in latest:
                latest[key] = row
        return list(latest.values())


def _block_packet(block: PlanBlock, *, week_start: date, week_end: date) -> dict[str, Any]:
    return {
        "id": str(block.id),
        "name": block.name,
        "blockType": block.block_type,
        "startDate": block.start_date.isoformat(),
        "endDate": block.end_date.isoformat(),
        "startsThisWeek": week_start <= block.start_date <= week_end,
        "endsThisWeek": week_start <= block.end_date <= week_end,
    }


def _block_summary(
    blocks: Sequence[PlanBlock],
    *,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    if not blocks:
        return {
            "primaryBlockType": None,
            "hasMidWeekChange": False,
            "recoveryStructured": False,
            "guidance": "No plan block is recorded for this coming week.",
        }
    ordered = sorted(blocks, key=lambda block: (block.start_date, block.end_date, block.name))
    types = [str(block.block_type or "unknown").lower() for block in ordered]
    primary = types[0]
    recovery_structured = any(kind in {"recovery", "taper", "consolidation"} for kind in types)
    has_mid_week_change = any(
        week_start < block.start_date <= week_end or week_start <= block.end_date < week_end
        for block in ordered
    )
    guidance = (
        "This is deliberate lighter structure; target=0 quality buckets are not shortfalls."
        if recovery_structured
        else "Use the week-ahead packet to describe what the plan asks, not to move it."
    )
    return {
        "primaryBlockType": primary,
        "blockTypes": types,
        "hasMidWeekChange": has_mid_week_change,
        "recoveryStructured": recovery_structured,
        "guidance": guidance,
    }


def _workout_packet(workout: PlannedWorkout) -> dict[str, Any]:
    category = categorize(workout.workout_type)
    return {
        "id": str(workout.id),
        "date": workout.workout_date.isoformat(),
        "weekday": workout.workout_date.strftime("%A"),
        "title": workout.title,
        "workoutType": workout.workout_type,
        "category": category,
        "durationMin": workout.planned_duration_min,
        "intensityTarget": workout.intensity_target,
        "status": workout.status,
    }


def _hardest_session(workouts: Sequence[PlannedWorkout]) -> dict[str, Any] | None:
    candidates = [workout for workout in workouts if workout.status == "planned"]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda workout: (
            -_HARDNESS_RANK.get(categorize(workout.workout_type), 0),
            -(workout.planned_duration_min or 0),
            workout.workout_date,
            workout.title,
        ),
    )
    hardest = ranked[0]
    packet = _workout_packet(hardest)
    packet["rankReason"] = "highest_planned_intensity_then_duration"
    return packet


def _protecting_night(hardest: dict[str, Any] | None) -> dict[str, Any] | None:
    if hardest is None:
        return None
    workout_date = date.fromisoformat(str(hardest["date"]))
    night = workout_date - timedelta(days=1)
    return {
        "date": night.isoformat(),
        "weekday": night.strftime("%A"),
        "protectsWorkoutId": hardest["id"],
        "protectsWorkoutTitle": hardest["title"],
    }
