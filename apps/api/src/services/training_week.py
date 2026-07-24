"""Factual calendar-week training history for coaching narratives.

Batch 148 closes the gap between three existing sources of truth:

* active ``PlannedWorkout`` rows describe the final schedule;
* workout-action ``Analysis`` rows describe explicit changes;
* Garmin ``Activity`` rows describe what actually happened.

The resulting packet is deliberately asymmetric: a planned or changed workout
can never imply completion. Only an entry in ``days[].executed`` is execution
evidence.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, Analysis, PlannedWorkout
from src.models.profile import Profile

ACTION_AUDIT_TYPES = frozenset(
    {
        "workout_moved",
        "workout_skipped",
        "workout_removed",
        "workout_replaced",
    }
)


class TrainingWeekService:
    """Read-only assembler for the profile's calendar week through ``as_of``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, player: Profile, *, as_of: date) -> dict[str, Any]:
        week_start = as_of - timedelta(days=as_of.weekday())
        planned = await self._active_planned_workouts(player.id, week_start, as_of)
        audits = await self._action_audits(player.id)
        activities = await self._activities(
            player.id,
            week_start,
            as_of,
            player.timezone,
        )

        audit_workout_ids = {
            linked_id
            for audit in audits
            if (linked_id := _audit_planned_workout_id(audit)) is not None
        }
        matched_ids = await self._matched_planned_workout_ids(activities)
        lookup_ids = audit_workout_ids | set(matched_ids.values())
        workouts_by_id = await self._workouts_by_id(lookup_ids)

        return build_training_week_packet(
            start_date=week_start,
            end_date=as_of,
            timezone_name=player.timezone,
            planned_workouts=planned,
            action_audits=audits,
            activities=activities,
            workouts_by_id=workouts_by_id,
            matched_planned_workout_ids=matched_ids,
        )

    async def _active_planned_workouts(
        self,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[PlannedWorkout]:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
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

    async def _action_audits(self, user_id: uuid.UUID) -> list[Analysis]:
        # A move can originate outside the week and land inside it (or vice
        # versa), so filtering only on subject_date would hide one side. These
        # private-user audit rows are compact; the pure reducer below retains
        # only events whose origin or target intersects the requested window.
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type.in_(tuple(ACTION_AUDIT_TYPES)),
                    )
                    .order_by(Analysis.generated_at_utc.asc(), Analysis.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _activities(
        self,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        timezone_name: str,
    ) -> list[Activity]:
        timezone = _timezone(timezone_name)
        start_utc = (
            datetime.combine(start_date, time.min, tzinfo=timezone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        end_utc = (
            datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == user_id,
                        Activity.start_utc >= start_utc,
                        Activity.start_utc < end_utc,
                    )
                    .order_by(Activity.start_utc.asc(), Activity.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _matched_planned_workout_ids(
        self,
        activities: Sequence[Activity],
    ) -> dict[uuid.UUID, uuid.UUID]:
        activity_ids = [activity.id for activity in activities]
        if not activity_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.activity_id.in_(activity_ids),
                        Analysis.planned_workout_id.is_not(None),
                    )
                    .order_by(Analysis.generated_at_utc.asc(), Analysis.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        matches: dict[uuid.UUID, uuid.UUID] = {}
        for row in rows:
            if row.activity_id is not None and row.planned_workout_id is not None:
                # Later analyses overwrite earlier ones, matching the app's
                # freshest-analysis convention elsewhere.
                matches[row.activity_id] = row.planned_workout_id
        return matches

    async def _workouts_by_id(
        self,
        workout_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, PlannedWorkout]:
        if not workout_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(PlannedWorkout.id.in_(tuple(workout_ids)))
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}


def build_training_week_packet(
    *,
    start_date: date,
    end_date: date,
    timezone_name: str,
    planned_workouts: Sequence[PlannedWorkout],
    action_audits: Sequence[Analysis],
    activities: Sequence[Activity],
    workouts_by_id: Mapping[uuid.UUID, PlannedWorkout] | None = None,
    matched_planned_workout_ids: Mapping[uuid.UUID, uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Reduce already-loaded rows into a deterministic per-day packet."""
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    lookup = dict(workouts_by_id or {})
    matches = dict(matched_planned_workout_ids or {})
    days: dict[date, dict[str, Any]] = {
        day: {
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "dayStatus": "rest_day",
            "planned": [],
            "changes": [],
            "executed": [],
        }
        for day in _dates_inclusive(start_date, end_date)
    }

    for workout in planned_workouts:
        if start_date <= workout.workout_date <= end_date:
            days[workout.workout_date]["planned"].append(_planned_workout_packet(workout))

    for audit in action_audits:
        _add_change_event(
            days,
            audit,
            start_date=start_date,
            end_date=end_date,
            workouts_by_id=lookup,
        )

    for activity in activities:
        activity_date = _activity_local_date(activity, timezone_name)
        if not start_date <= activity_date <= end_date:
            continue
        matched_id = matches.get(activity.id)
        matched_workout = lookup.get(matched_id) if matched_id is not None else None
        days[activity_date]["executed"].append(
            _activity_packet(activity, matched_workout=matched_workout)
        )

    for day, packet in days.items():
        packet["planned"].sort(key=lambda item: (item["title"], item["id"]))
        packet["changes"].sort(
            key=lambda item: (
                item["generatedAtUtc"],
                item.get("direction") or "",
                item["summary"],
            )
        )
        packet["executed"].sort(key=lambda item: (item["startUtc"], item["activityId"]))
        packet["dayStatus"] = _day_status(packet, is_subject_date=day == end_date)

    return {
        "window": {
            "kind": "calendar_week_to_date",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
        "days": list(days.values()),
        "grounding": {
            "plannedMeaning": "final active schedule, not proof of completion",
            "changedMeaning": "explicit workout-action audit, not proof of completion",
            "executedMeaning": "Garmin activity record; the only completion truth here",
            "recommendationAttribution": (
                "not inferred: no durable audit link proves a change followed an app suggestion"
            ),
        },
    }


def _add_change_event(
    days: Mapping[date, dict[str, Any]],
    audit: Analysis,
    *,
    start_date: date,
    end_date: date,
    workouts_by_id: Mapping[uuid.UUID, PlannedWorkout],
) -> None:
    action = audit.analysis_type.removeprefix("workout_")
    linked_id = _audit_planned_workout_id(audit)
    workout = workouts_by_id.get(linked_id) if linked_id is not None else None
    target_date = _moved_target_date(audit, workout) if action == "moved" else None
    base = {
        "action": action,
        "summary": audit.output_markdown,
        "generatedAtUtc": _datetime_packet(audit.generated_at_utc),
        "workout": _planned_workout_packet(workout) if workout is not None else None,
        "source": "workout_action_audit",
        "attribution": "not_inferred",
    }

    if action == "moved":
        source_date = audit.subject_date
        if start_date <= source_date <= end_date:
            days[source_date]["changes"].append(
                {
                    **base,
                    "direction": "out",
                    "fromDate": source_date.isoformat(),
                    "toDate": target_date.isoformat() if target_date is not None else None,
                }
            )
        if (
            target_date is not None
            and target_date != source_date
            and start_date <= target_date <= end_date
        ):
            days[target_date]["changes"].append(
                {
                    **base,
                    "direction": "in",
                    "fromDate": source_date.isoformat(),
                    "toDate": target_date.isoformat(),
                }
            )
        return

    if start_date <= audit.subject_date <= end_date:
        days[audit.subject_date]["changes"].append(
            {
                **base,
                "direction": None,
                "fromDate": audit.subject_date.isoformat(),
                "toDate": None,
            }
        )


def _day_status(packet: Mapping[str, Any], *, is_subject_date: bool) -> str:
    executed = cast(list[dict[str, Any]], packet["executed"])
    planned = cast(list[dict[str, Any]], packet["planned"])
    changes = cast(list[dict[str, Any]], packet["changes"])
    if executed:
        return "executed"
    if any(change["action"] == "skipped" for change in changes) or (
        planned and all(workout["status"] == "skipped" for workout in planned)
    ):
        return "skipped"
    if any(change["action"] == "removed" for change in changes) and not planned:
        return "removed"
    if planned:
        return "planned" if is_subject_date else "no_activity_recorded"
    if changes:
        return "changed_no_activity"
    return "rest_day"


def _planned_workout_packet(row: PlannedWorkout) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workoutDate": row.workout_date.isoformat(),
        "version": row.version,
        "title": row.title,
        "workoutType": row.workout_type,
        "status": row.status,
        "plannedDurationMin": row.planned_duration_min,
        "intensityTarget": row.intensity_target,
        "source": row.source,
    }


def _activity_packet(
    row: Activity,
    *,
    matched_workout: PlannedWorkout | None,
) -> dict[str, Any]:
    return {
        "activityId": str(row.id),
        "garminActivityId": row.garmin_activity_id,
        "title": row.activity_name,
        "activityType": row.activity_type,
        "startUtc": _datetime_packet(row.start_utc),
        "durationMin": (
            round(float(row.duration_sec) / 60, 1) if row.duration_sec is not None else None
        ),
        "trainingLoad": row.training_load,
        "avgPowerWatts": row.avg_power_watts,
        "normalizedPowerWatts": row.normalized_power_watts,
        "aerobicTrainingEffect": row.aerobic_training_effect,
        "anaerobicTrainingEffect": row.anaerobic_training_effect,
        "matchedPlannedWorkout": (
            _planned_workout_packet(matched_workout) if matched_workout is not None else None
        ),
    }


def _audit_planned_workout_id(audit: Analysis) -> uuid.UUID | None:
    if audit.planned_workout_id is not None:
        return audit.planned_workout_id
    packet = audit.context_packet if isinstance(audit.context_packet, dict) else {}
    raw_id = packet.get("plannedWorkoutId")
    if not isinstance(raw_id, str):
        return None
    try:
        return uuid.UUID(raw_id)
    except ValueError:
        return None


def _moved_target_date(
    audit: Analysis,
    linked_workout: PlannedWorkout | None,
) -> date | None:
    if linked_workout is not None:
        return linked_workout.workout_date
    packet = audit.context_packet if isinstance(audit.context_packet, dict) else {}
    tag = packet.get("tag")
    if not isinstance(tag, str):
        return None
    raw_date = tag.rsplit(":", maxsplit=1)[-1]
    try:
        return date.fromisoformat(raw_date)
    except ValueError:
        return None


def _activity_local_date(activity: Activity, timezone_name: str) -> date:
    return activity.start_utc.replace(tzinfo=UTC).astimezone(_timezone(timezone_name)).date()


def _timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _dates_inclusive(start_date: date, end_date: date) -> list[date]:
    return [
        start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)
    ]


def _datetime_packet(value: datetime) -> str:
    suffix = "" if value.tzinfo is not None else "Z"
    return value.isoformat() + suffix
