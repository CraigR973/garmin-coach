"""What Zwift holds for a planned ride, set against what the day asks for (Batch 335).

A ride reaches Zwift as an intervals.icu event, and the event can stop matching its plan
row. On 8 Oct 2026 Mark approved a Red easing of Thursday's Sweet Spot and then swapped
Thursday with Saturday; the eased 29-minute event went to Saturday, then on to Sunday,
while Home, Week and the brief named the planned 58-minute Sweet Spot "in Zwift". This
module answers one question for those screens and for the daily check: is the ride on
Zwift the plan row's own, a change made for this day, or neither?

Rides are compared as Zwift holds them (the intervals.icu payload: the event's name and
its steps in %FTP), never as stored IR, which also records the FTP it was built with.
Mark's FTP changed on 20 Oct 2026 and every pushed event still records 280 W, though each
rides exactly as planned.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, PlannedWorkout, WorkoutDeliveryProposal
from src.services.structured_workout_builder import is_indoor_bike_workout
from src.services.verdict_grading import (
    ENGINE_GRADED,
    ride_transform,
    stored_actions,
    stored_engine,
)
from src.services.verdict_scaling import (
    MORNING_TRANSFORM_ORIGINS,
    TRANSFORM_TIRED_TEMPO,
    TRANSFORM_TIRED_ZONE2,
    _normalize_verdict,
    adjust_ir_for_verdict,
    companion_session_present,
)
from src.services.workout_delivery import (
    WorkoutDeliveryService,
    build_intervals_payload,
    build_structured_workout_ir,
)

#: The ride on Zwift is the plan row's own.
LIVE_RIDE_AS_PLANNED: Final = "as_planned"
#: A change made for this day: this morning's easing or pick, or one of Mark's own edits.
LIVE_RIDE_CHANGED: Final = "changed"
#: Neither: another day's easing carried here, or a plan row that changed under its event.
LIVE_RIDE_NOT_THIS_DAY: Final = "not_this_day"

_ANALYSIS_TYPE_MORNING: Final = "morning"


def ride_on_zwift(ir: Mapping[str, Any]) -> tuple[str, str] | None:
    """The ride as Zwift holds it (event name and steps), or ``None`` when unreadable."""
    try:
        payload = build_intervals_payload(dict(ir))
    except (KeyError, TypeError, ValueError):
        return None
    return str(payload["name"]), str(payload["description"])


def plan_ride_ir(base_ir: Mapping[str, Any], *, verdict: str | None) -> dict[str, Any]:
    """The plan row's own ride, annotated exactly as reconcile delivers a baseline."""
    ride = dict(base_ir)
    ride["origin"] = "as_planned"
    ride["adjustment"] = {"verdict": verdict, "changed": False}
    return ride


def morning_rides(
    base_ir: Mapping[str, Any],
    *,
    status: str | None,
    graded: bool,
    action: str | None,
    companion_session: bool,
) -> list[dict[str, Any]]:
    """The rides a day's morning may have put on Zwift for one session.

    The version the morning offers (its session action's transform, or under the ladder
    its colour) and, on a tired-morning pick, the tempo version Mark may take instead.
    """
    transform = ride_transform(status, graded=graded, action=action)
    if transform is None:
        return []
    rides = [
        adjust_ir_for_verdict(
            dict(base_ir), transform, companion_session=companion_session, graded=graded
        )
    ]
    if transform == TRANSFORM_TIRED_ZONE2:
        rides.append(adjust_ir_for_verdict(dict(base_ir), TRANSFORM_TIRED_TEMPO, graded=True))
    return rides


def classify_live_ride(
    live_ir: Mapping[str, Any],
    *,
    plan_ir: Mapping[str, Any],
    this_day: Sequence[Mapping[str, Any]],
) -> str:
    """Whether the live ride is the plan row's, a change for this day, or neither.

    ``this_day`` holds the morning changes that belong to this session on this date: what
    its morning offers, and what Mark approved for it. A morning's easing that matches
    none of them was made for another day (or another version of the row) and carried
    here. Any other origin is Mark's own doing, an edit or a deload he approved, and
    stays his wherever the session goes.
    """
    ride = ride_on_zwift(live_ir)
    if ride is not None and ride == ride_on_zwift(plan_ir):
        return LIVE_RIDE_AS_PLANNED
    origin = str(live_ir.get("origin") or "")
    if origin in MORNING_TRANSFORM_ORIGINS:
        if ride is not None and any(ride == ride_on_zwift(change) for change in this_day):
            return LIVE_RIDE_CHANGED
        return LIVE_RIDE_NOT_THIS_DAY
    if origin == "as_planned":
        # Delivered as the plan row, and the row has changed since.
        return LIVE_RIDE_NOT_THIS_DAY
    return LIVE_RIDE_CHANGED


def _top_power_pct(ir: Mapping[str, Any]) -> int | None:
    steps = ir.get("steps")
    if not isinstance(steps, list):
        return None
    powers = [
        max(int(step.get("powerStartPct") or 0), int(step.get("powerEndPct") or 0))
        for step in steps
        if isinstance(step, dict)
    ]
    return max(powers) if powers else None


def _duration_min(ir: Mapping[str, Any]) -> int | None:
    total = ir.get("totalDurationSec")
    if isinstance(total, int | float) and total > 0:
        return round(total / 60)
    return None


@dataclass(frozen=True, slots=True)
class LiveRide:
    """The ride on Zwift for one planned session, as a screen names it."""

    state: str
    title: str
    duration_min: int | None
    top_power_pct: int | None
    origin: str | None

    @classmethod
    def from_ir(cls, ir: Mapping[str, Any], *, state: str) -> LiveRide:
        origin = ir.get("origin")
        return cls(
            state=state,
            title=str(ir.get("name") or "Workout"),
            duration_min=_duration_min(ir),
            top_power_pct=_top_power_pct(ir),
            origin=str(origin) if isinstance(origin, str) else None,
        )


class LiveRideReader:
    """Reads the live event of an indoor ride and says how it stands against its day."""

    def __init__(
        self, session: AsyncSession, *, rail: WorkoutDeliveryService | None = None
    ) -> None:
        self.session = session
        self.rail = rail or WorkoutDeliveryService(session)

    async def live_event(
        self, user_id: uuid.UUID, workout: PlannedWorkout
    ) -> WorkoutDeliveryProposal | None:
        """The event on Zwift for this session (by id, then by its date), as the rail finds it.

        The date fallback serves events keyed to the slot before mixed days. An event that
        belongs to another session still on the plan is that session's, never this one's,
        so the daily check can never write one ride's plan over another's event.
        """
        live = await self.rail.latest_delivered_for_workout(user_id, workout.id)
        if live is not None:
            return live
        live = await self.rail.latest_delivered_for_date(user_id, workout.workout_date)
        if live is None or live.planned_workout_id in (None, workout.id):
            return live
        owner = await self.session.get(PlannedWorkout, live.planned_workout_id)
        if owner is not None and owner.is_active:
            return None
        return live

    async def read(
        self,
        user_id: uuid.UUID,
        workout: PlannedWorkout,
        *,
        live: WorkoutDeliveryProposal | None = None,
    ) -> LiveRide | None:
        """The live ride for an indoor bike session, or ``None`` when Zwift holds none."""
        if not is_indoor_bike_workout(workout.structured_workout):
            return None
        if live is None:
            live = await self.live_event(user_id, workout)
        if live is None or not isinstance(live.structured_workout_ir, dict):
            return None
        try:
            ftp_watts = await self.rail._ftp_watts(user_id)
            base_ir = build_structured_workout_ir(workout, ftp_watts=ftp_watts)
        except HTTPException:
            return None
        live_ir = live.structured_workout_ir
        this_day: list[dict[str, Any]] = []
        if str(live_ir.get("origin") or "") in MORNING_TRANSFORM_ORIGINS:
            this_day = await self._this_day_changes(user_id, workout, base_ir)
        state = classify_live_ride(live_ir, plan_ir=base_ir, this_day=this_day)
        return LiveRide.from_ir(live_ir, state=state)

    async def _this_day_changes(
        self, user_id: uuid.UUID, workout: PlannedWorkout, base_ir: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """What this session's own morning offers, plus the changes Mark approved for it.

        The approved changes matter because a morning read again later in the day (Mark
        files several check-ins) can offer a different ride from the one he took.
        """
        changes: list[dict[str, Any]] = []
        approved = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal).where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.planned_workout_id == workout.id,
                        WorkoutDeliveryProposal.approved_by_profile_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        changes.extend(
            proposal.structured_workout_ir
            for proposal in approved
            if isinstance(proposal.structured_workout_ir, dict)
        )
        morning = await self.session.scalar(
            select(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == _ANALYSIS_TYPE_MORNING,
                Analysis.subject_date == workout.workout_date,
            )
            .order_by(Analysis.generated_at_utc.desc(), Analysis.created_at.desc())
            .limit(1)
        )
        if morning is None:
            return changes
        others = (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == workout.workout_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.id != workout.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        changes.extend(
            morning_rides(
                base_ir,
                status=_normalize_verdict(morning.verdict),
                graded=stored_engine(morning.context_packet) == ENGINE_GRADED,
                action=stored_actions(morning.context_packet).get(str(workout.id)),
                companion_session=companion_session_present(other.status for other in others),
            )
        )
        return changes
