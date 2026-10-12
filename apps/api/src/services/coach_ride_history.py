"""Previous completed ride by Garmin workout identity, never by a plan row."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity
from src.services.bulk_history_reads import activity_ride_comparison_columns
from src.services.coach_sections import activity_state, minutes

BIKE_TYPES = frozenset({"indoor_cycling", "road_biking", "cycling"})
GENERIC_TITLES = frozenset({"indoor cycling", "road cycling", "cycling"})
GENERIC_DURATION_TOLERANCE_MIN = 5
_PLAN_PREFIX = re.compile(r"^.*?\bWk\s*\d+\s*WO\s*\d+\s*[-: ]*", re.IGNORECASE)
_ADJUSTMENT_PREFIX = re.compile(r"^(?:Amber-adjusted|Red-substituted):\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RideSample:
    id: uuid.UUID
    activity_name: str
    activity_type: str
    start_utc: datetime
    duration_sec: float | None
    avg_heart_rate_bpm: int | None
    max_heart_rate_bpm: int | None
    avg_power_watts: int | None
    normalized_power_watts: int | None

    @classmethod
    def from_activity(cls, row: Activity) -> RideSample:
        return cls(
            row.id,
            row.activity_name,
            row.activity_type,
            row.start_utc,
            row.duration_sec,
            row.avg_heart_rate_bpm,
            row.max_heart_rate_bpm,
            row.avg_power_watts,
            row.normalized_power_watts,
        )


def workout_name(title: str) -> str:
    """Remove the plan slot and adjustment prefix, leaving what Garmin says he rode."""
    name = _PLAN_PREFIX.sub("", title.strip(), count=1)
    name = _ADJUSTMENT_PREFIX.sub("", name, count=1)
    return " ".join(name.split()).casefold()


def previous_ride(current: RideSample, rides: Sequence[RideSample]) -> RideSample | None:
    if current.activity_type not in BIKE_TYPES:
        return None
    name = workout_name(current.activity_name)
    generic = name in GENERIC_TITLES
    matches = (
        ride
        for ride in rides
        if ride.id != current.id
        and ride.activity_type == current.activity_type
        and ride.start_utc < current.start_utc
        and (
            (
                generic
                and workout_name(ride.activity_name) in GENERIC_TITLES
                and current.duration_sec is not None
                and ride.duration_sec is not None
                and abs(round(current.duration_sec / 60) - round(ride.duration_sec / 60))
                <= GENERIC_DURATION_TOLERANCE_MIN
            )
            or (not generic and bool(name) and workout_name(ride.activity_name) == name)
        )
    )
    return max(matches, key=lambda ride: ride.start_utc, default=None)


async def activity_states_with_previous(
    session: AsyncSession,
    user_id: uuid.UUID,
    rows: Sequence[Activity],
    local_date_of: Callable[[datetime], date],
) -> list[dict[str, Any]]:
    """Attach one previous ride to each visible bike session with one typed history read."""
    bikes = [row for row in rows if row.activity_type in BIKE_TYPES]
    history = [RideSample.from_activity(row) for row in bikes]
    if bikes:
        older = await session.execute(
            activity_ride_comparison_columns()
            .where(
                Activity.user_id == user_id,
                Activity.activity_type.in_(BIKE_TYPES),
                Activity.start_utc < min(row.start_utc for row in bikes),
            )
            .order_by(Activity.start_utc.desc())
        )
        history.extend(RideSample(*record) for record in older.all())
    result = []
    for row in rows:
        state = activity_state(row, local_date_of)
        if row.activity_type in BIKE_TYPES:
            prior = previous_ride(RideSample.from_activity(row), history)
            state["previousSameWorkout"] = (
                {
                    "activityId": str(prior.id),
                    "localDate": local_date_of(prior.start_utc).isoformat(),
                    "title": prior.activity_name,
                    "durationMin": minutes(prior.duration_sec),
                    "avgHeartRateBpm": prior.avg_heart_rate_bpm,
                    "maxHeartRateBpm": prior.max_heart_rate_bpm,
                    "avgPowerWatts": prior.avg_power_watts,
                    "normalizedPowerWatts": prior.normalized_power_watts,
                    "matchBasis": (
                        "type_and_duration"
                        if workout_name(row.activity_name) in GENERIC_TITLES
                        else "workout_name"
                    ),
                }
                if prior is not None
                else None
            )
        result.append(state)
    return result
