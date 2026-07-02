from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile
from src.services.strength_brief import StrengthBriefResult, StrengthBriefService
from src.services.workout_delivery import STATUS_PROPOSED, STATUS_PUSHED

ANALYSIS_TYPE_MORNING = "morning"
ANALYSIS_TYPE_POST_WORKOUT = "post_workout"
ANALYSIS_TYPE_POST_FLEXIBILITY = "post_flexibility"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _local_today(timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


def _activity_local_date(activity: Activity, timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return activity.start_utc.replace(tzinfo=UTC).astimezone(timezone).date()


@dataclass
class DeliveryState:
    """The Zwift-delivery state of a planned workout, for the Today card (Batch 29).

    ``changed`` is the two-state split: True when an un-acted coach adjustment is
    waiting (Approve & upload), False when the live session is the as-planned one
    (Edit / Swap / Skip). The live-event fields describe what currently sits on
    Zwift for the slot (push-on-plan-set means the baseline is already there).
    """

    live_status: str | None
    live_origin: str | None
    intervals_event_id: str | None
    changed: bool
    adjustment: dict[str, object] | None


@dataclass
class DailyLoopSnapshot:
    subject_date: date
    morning_analysis: Analysis | None
    daily_metric: DailyMetric | None
    sleep: Sleep | None
    manual_entry: ManualEntry | None
    post_workout_analyses: list[Analysis]
    post_flexibility_analyses: list[Analysis]
    post_ride_checkins: dict[uuid.UUID, ManualEntry]
    planned_workouts: list[PlannedWorkout]
    adherence_entries: dict[uuid.UUID, ManualEntry]
    deliveries: dict[uuid.UUID, DeliveryState]
    latest_temperature: TemperatureReading | None
    weather: WeatherDaily | None
    data_quality_warnings: list[dict[str, str]]
    strength_brief: StrengthBriefResult


class DailyLoopService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_snapshot(
        self,
        player: Profile,
        *,
        subject_date: date | None = None,
    ) -> DailyLoopSnapshot:
        target_date = subject_date or _local_today(player.timezone)

        morning_analysis = await self._latest_morning_analysis(player.id, target_date)
        daily_metric = await self._daily_metric(player.id, target_date)
        sleep = await self._sleep(player.id, target_date)
        manual_entry = await self._manual_entry(player.id, target_date)
        post_workout_analyses = await self._post_workout_analyses(player.id, target_date)
        post_flexibility_analyses = await self._post_flexibility_analyses(player.id, target_date)
        post_ride_checkins = await self._post_ride_checkins(player.id, target_date)
        planned_workouts = await self._planned_workouts(player.id, target_date)
        adherence_entries = await self._adherence_entries(player.id, target_date)
        deliveries = await self._deliveries(player.id, planned_workouts)
        latest_temperature = await self._latest_temperature(player.id)
        weather = await self._weather(player.id, target_date)
        warnings = await self._data_quality_warnings(player.id, target_date, planned_workouts)
        strength_brief = await StrengthBriefService(self.session).brief(player, as_of=target_date)

        return DailyLoopSnapshot(
            subject_date=target_date,
            morning_analysis=morning_analysis,
            daily_metric=daily_metric,
            sleep=sleep,
            manual_entry=manual_entry,
            post_workout_analyses=post_workout_analyses,
            post_flexibility_analyses=post_flexibility_analyses,
            post_ride_checkins=post_ride_checkins,
            planned_workouts=planned_workouts,
            adherence_entries=adherence_entries,
            deliveries=deliveries,
            latest_temperature=latest_temperature,
            weather=weather,
            data_quality_warnings=warnings,
            strength_brief=strength_brief,
        )

    async def upsert_manual_entry(
        self,
        player: Profile,
        *,
        subject_date: date,
        bp_systolic: int | None,
        bp_diastolic: int | None,
        subjective_score: int | None,
        rpe: float | None,
        feel: str | None,
        supplements_json: dict[str, object],
        food_json: dict[str, object],
        notes: str | None,
    ) -> ManualEntry:
        entry = await self._manual_entry(player.id, subject_date)
        if entry is None:
            entry = ManualEntry(
                user_id=player.id,
                entry_date=subject_date,
                entry_at_utc=_utcnow(),
            )
            self.session.add(entry)

        entry.entry_at_utc = _utcnow()
        entry.bp_systolic = bp_systolic
        entry.bp_diastolic = bp_diastolic
        entry.subjective_score = subjective_score
        entry.rpe = rpe
        entry.feel = feel
        entry.supplements_json = supplements_json
        entry.food_json = food_json
        entry.notes = notes
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def upsert_post_ride_checkin(
        self,
        player: Profile,
        *,
        subject_date: date,
        activity_id: uuid.UUID,
        subjective_score: int | None,
        rpe: float | None,
        feel: str | None,
        notes: str | None,
    ) -> ManualEntry:
        activity = await self._activity(player.id, activity_id, subject_date, player.timezone)
        if activity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity not found for this date",
            )

        entry = await self._post_ride_checkin(player.id, subject_date, activity_id)
        if entry is None:
            entry = ManualEntry(
                user_id=player.id,
                activity_id=activity_id,
                entry_date=subject_date,
                entry_at_utc=_utcnow(),
            )
            self.session.add(entry)

        entry.entry_at_utc = _utcnow()
        entry.subjective_score = subjective_score
        entry.rpe = rpe
        entry.feel = feel
        entry.notes = notes
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def upsert_adherence(
        self,
        player: Profile,
        *,
        subject_date: date,
        planned_workout_id: uuid.UUID,
        adherence_status: str,
        rpe: float | None,
        feel: str | None,
        notes: str | None,
        actual_workout_json: dict[str, object],
    ) -> ManualEntry:
        workout = await self._planned_workout(player.id, planned_workout_id, subject_date)
        if workout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Planned workout not found for this date",
            )

        entry = await self._adherence_entry(player.id, subject_date, planned_workout_id)
        if entry is None:
            entry = ManualEntry(
                user_id=player.id,
                planned_workout_id=planned_workout_id,
                entry_date=subject_date,
                entry_at_utc=_utcnow(),
            )
            self.session.add(entry)

        entry.entry_at_utc = _utcnow()
        entry.planned_workout_version = workout.version
        entry.adherence_status = adherence_status
        entry.rpe = rpe
        entry.feel = feel
        entry.notes = notes
        entry.actual_workout_json = actual_workout_json
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def _latest_morning_analysis(
        self, user_id: uuid.UUID, subject_date: date
    ) -> Analysis | None:
        return (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_MORNING,
                        Analysis.subject_date == subject_date,
                    )
                    .order_by(Analysis.generated_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _daily_metric(self, user_id: uuid.UUID, subject_date: date) -> DailyMetric | None:
        return (
            (
                await self.session.execute(
                    select(DailyMetric).where(
                        DailyMetric.user_id == user_id,
                        DailyMetric.calendar_date == subject_date,
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _post_workout_analyses(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> list[Analysis]:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .join(Activity, Analysis.activity_id == Activity.id)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_POST_WORKOUT,
                        Analysis.subject_date == subject_date,
                    )
                    .order_by(Activity.start_utc.desc(), Analysis.generated_at_utc.desc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _post_flexibility_analyses(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> list[Analysis]:
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .join(Activity, Analysis.activity_id == Activity.id)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == ANALYSIS_TYPE_POST_FLEXIBILITY,
                        Analysis.subject_date == subject_date,
                    )
                    .order_by(Activity.start_utc.desc(), Analysis.generated_at_utc.desc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _sleep(self, user_id: uuid.UUID, subject_date: date) -> Sleep | None:
        return (
            (
                await self.session.execute(
                    select(Sleep).where(
                        Sleep.user_id == user_id,
                        Sleep.calendar_date == subject_date,
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _manual_entry(self, user_id: uuid.UUID, subject_date: date) -> ManualEntry | None:
        return (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                        ManualEntry.planned_workout_id.is_(None),
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _planned_workouts(
        self, user_id: uuid.UUID, subject_date: date
    ) -> list[PlannedWorkout]:
        return list(
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == subject_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _deliveries(
        self, user_id: uuid.UUID, planned_workouts: list[PlannedWorkout]
    ) -> dict[uuid.UUID, DeliveryState]:
        """The Zwift-delivery state per planned workout, for the Today card.

        ``live`` is resolved by *date* (the event sitting on the slot, robust to a
        restructure re-versioning the row); ``pending`` is the latest un-acted
        coach adjustment, which flips the card into its Approve & upload state.
        """
        states: dict[uuid.UUID, DeliveryState] = {}
        for workout in planned_workouts:
            live: WorkoutDeliveryProposal | None = await self.session.scalar(
                select(WorkoutDeliveryProposal)
                .where(
                    WorkoutDeliveryProposal.user_id == user_id,
                    WorkoutDeliveryProposal.planned_workout_id == workout.id,
                    WorkoutDeliveryProposal.status == STATUS_PUSHED,
                    WorkoutDeliveryProposal.intervals_event_id.is_not(None),
                )
                .order_by(WorkoutDeliveryProposal.created_at.desc())
                .limit(1)
            )
            if live is None:
                live = await self.session.scalar(
                    select(WorkoutDeliveryProposal)
                    .where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.workout_date == workout.workout_date,
                        WorkoutDeliveryProposal.status == STATUS_PUSHED,
                        WorkoutDeliveryProposal.intervals_event_id.is_not(None),
                    )
                    .order_by(WorkoutDeliveryProposal.created_at.desc())
                    .limit(1)
                )
            pending = await self._pending_adjustment(user_id, workout.id)
            live_ir = (
                live.structured_workout_ir
                if live is not None and isinstance(live.structured_workout_ir, dict)
                else {}
            )
            pending_adjustment = None
            if pending is not None and isinstance(pending.structured_workout_ir, dict):
                raw = pending.structured_workout_ir.get("adjustment")
                pending_adjustment = raw if isinstance(raw, dict) else None
            states[workout.id] = DeliveryState(
                live_status=live.status if live is not None else None,
                live_origin=live_ir.get("origin") if live is not None else None,
                intervals_event_id=live.intervals_event_id if live is not None else None,
                changed=pending is not None,
                adjustment=pending_adjustment,
            )
        return states

    async def _pending_adjustment(
        self, user_id: uuid.UUID, planned_workout_id: uuid.UUID
    ) -> WorkoutDeliveryProposal | None:
        proposals = (
            (
                await self.session.execute(
                    select(WorkoutDeliveryProposal)
                    .where(
                        WorkoutDeliveryProposal.user_id == user_id,
                        WorkoutDeliveryProposal.planned_workout_id == planned_workout_id,
                        WorkoutDeliveryProposal.status == STATUS_PROPOSED,
                    )
                    .order_by(WorkoutDeliveryProposal.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        for proposal in proposals:
            ir = (
                proposal.structured_workout_ir
                if isinstance(proposal.structured_workout_ir, dict)
                else {}
            )
            adjustment = ir.get("adjustment")
            if isinstance(adjustment, dict) and adjustment.get("changed"):
                return proposal
        return None

    async def _planned_workout(
        self,
        user_id: uuid.UUID,
        planned_workout_id: uuid.UUID,
        subject_date: date,
    ) -> PlannedWorkout | None:
        return (
            (
                await self.session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.id == planned_workout_id,
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == subject_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _adherence_entries(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> dict[uuid.UUID, ManualEntry]:
        entries = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                        ManualEntry.planned_workout_id.is_not(None),
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc())
                )
            )
            .scalars()
            .all()
        )

        latest_by_workout: dict[uuid.UUID, ManualEntry] = {}
        for entry in entries:
            if entry.planned_workout_id is None or entry.planned_workout_id in latest_by_workout:
                continue
            latest_by_workout[entry.planned_workout_id] = entry
        return latest_by_workout

    async def _adherence_entry(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        planned_workout_id: uuid.UUID,
    ) -> ManualEntry | None:
        return (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                        ManualEntry.planned_workout_id == planned_workout_id,
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _post_ride_checkins(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> dict[uuid.UUID, ManualEntry]:
        entries = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                        ManualEntry.activity_id.is_not(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc())
                )
            )
            .scalars()
            .all()
        )

        latest_by_activity: dict[uuid.UUID, ManualEntry] = {}
        for entry in entries:
            if entry.activity_id is None or entry.activity_id in latest_by_activity:
                continue
            latest_by_activity[entry.activity_id] = entry
        return latest_by_activity

    async def _post_ride_checkin(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        activity_id: uuid.UUID,
    ) -> ManualEntry | None:
        return (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                        ManualEntry.activity_id == activity_id,
                    )
                    .order_by(ManualEntry.entry_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _activity(
        self,
        user_id: uuid.UUID,
        activity_id: uuid.UUID,
        subject_date: date,
        timezone_name: str,
    ) -> Activity | None:
        activity = (
            (
                await self.session.execute(
                    select(Activity).where(
                        Activity.id == activity_id,
                        Activity.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if activity is None:
            return None
        if _activity_local_date(activity, timezone_name) != subject_date:
            return None
        return activity

    async def _latest_temperature(self, user_id: uuid.UUID) -> TemperatureReading | None:
        return (
            (
                await self.session.execute(
                    select(TemperatureReading)
                    .where(TemperatureReading.user_id == user_id)
                    .order_by(TemperatureReading.captured_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _weather(self, user_id: uuid.UUID, subject_date: date) -> WeatherDaily | None:
        return (
            (
                await self.session.execute(
                    select(WeatherDaily).where(
                        WeatherDaily.user_id == user_id,
                        WeatherDaily.calendar_date == subject_date,
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _data_quality_warnings(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        planned_workouts: list[PlannedWorkout],
    ) -> list[dict[str, str]]:
        kb = (
            (
                await self.session.execute(
                    select(KnowledgeBase)
                    .where(
                        KnowledgeBase.user_id == user_id,
                        KnowledgeBase.section == "data_quality_rules",
                        KnowledgeBase.is_active.is_(True),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

        warnings: list[dict[str, str]] = []
        rules = kb.content.get("rules", []) if kb is not None else []
        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                warning = {
                    "id": str(rule.get("id", "rule")),
                    "summary": str(rule.get("summary", "Data-quality rule")),
                    "reason": str(rule.get("reason", "")),
                    "status": "info",
                    "detail": "",
                }
                if warning["id"] == "spo2_hrv_reliable_since" and subject_date < date(2026, 6, 11):
                    warning["status"] = "active"
                    warning["detail"] = "This date is before the overnight reliability cutoff."
                if warning["id"] == "exclude_wrist_hr_strength" and any(
                    "strength" in workout.workout_type.lower() for workout in planned_workouts
                ):
                    warning["status"] = "active"
                    warning["detail"] = (
                        "Today's plan includes strength work, so wrist HR is "
                        "excluded from recovery calls."
                    )
                warnings.append(warning)

        return warnings
