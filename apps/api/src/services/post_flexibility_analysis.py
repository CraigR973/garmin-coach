"""Post-flexibility/mobility analysis for Garmin ``other`` mobility sessions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    PlannedWorkout,
)
from src.models.profile import Profile
from src.services.anthropic_text import generate_anthropic_text
from src.services.coaching_state import CoachingStateService
from src.services.holiday_pause import HolidayPauseService, HolidayWindow
from src.services.personal_baselines import serialize_training_schedule
from src.services.post_workout_analysis import (
    ClaudeGenerationResult,
    PostWorkoutAnalysisError,
    _activity_local_date,
    _activity_packet,
    _analysis_rules,
    _data_quality_guardrails,
    _dt,
    _manual_entry_packet,
    _minutes,
    _planned_workout_packet,
    _utcnow,
)

PROMPT_VERSION = "post-flexibility-analysis-v3-2026-07-12"
ANALYSIS_TYPE = "post_flexibility"
WINDOW_4W_DAYS = 28
FORWARD_PLAN_DAYS = 14

SYSTEM_PROMPT = """You are CheckMark, a private mobility and recovery coach.
Use only the supplied context packet. Follow every data-quality guardrail.
Use `subjectWeekday` as the authoritative weekday; never derive the weekday from
`subjectDate` yourself. Treat `mobilityBaseline` as Mark's established daily habit:
the cycling `weeklyRhythm` is not a mobility budget, so never call a mobility
session a bonus, overshoot, extra load, or evidence that the week is too full.
Respect `holidayContext`: a planned workout with `isLive=false` is not live and
must not be cited as upcoming work. Keep the one light next step within mobility.
Return concise markdown that acknowledges the mobility session, reads consistency
against the current routine, notes whether heart rate was unusually high for a
mobility session, and gives one light next step. This is advisory only: do not
make cycling recovery decisions, do not discuss power, FTP, cadence, stamina,
Performance Condition, Training Effect, or zones.
If the activity check-in notes contain a question, answer it directly using only
the supplied packet; say when the available data cannot support an answer."""


@dataclass(frozen=True)
class FlexibilitySession:
    activity_id: uuid.UUID
    session_date: date
    duration_min: int | None


@dataclass(frozen=True)
class FlexibilityConsistency:
    current_streak: int
    sessions_this_week: int
    sessions_4w: int
    sessions_per_week_4w: float


@dataclass(frozen=True)
class FlexibilityAnalysisResult:
    analysis: Analysis
    generated: bool


class FlexibilityAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled mobility packet."""


class AnthropicFlexibilityAnalysisClient:
    """Small HTTP boundary for Anthropic Messages, using the mobility prompt."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.max_tokens = max_tokens or settings.anthropic_max_tokens

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        if not self.api_key:
            raise PostWorkoutAnalysisError("ANTHROPIC_API_KEY is not configured.")
        result = await generate_anthropic_text(
            api_key=self.api_key,
            model_name=self.model_name,
            max_tokens=self.max_tokens,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            error_cls=PostWorkoutAnalysisError,
        )
        return ClaudeGenerationResult(
            output_markdown=result.output_markdown,
            raw_response=result.raw_response,
            model_name=result.model_name,
        )


def is_flexibility_activity(activity: Activity) -> bool:
    """Select Mark's mobility routine by name, never by Garmin's broad ``other`` type."""

    name = (activity.activity_name or "").lower()
    activity_type = (activity.activity_type or "").lower()
    if activity_type == "yoga":
        return False
    return "mobility" in name


def compute_flexibility_consistency(
    sessions: Sequence[FlexibilitySession],
    *,
    as_of_date: date,
    window_days: int = WINDOW_4W_DAYS,
) -> FlexibilityConsistency:
    window_start = as_of_date - timedelta(days=window_days)
    window_sessions = sorted(
        [session for session in sessions if window_start < session.session_date <= as_of_date],
        key=lambda session: session.session_date,
    )
    session_dates = {session.session_date for session in window_sessions}

    streak = 0
    cursor = as_of_date
    while cursor in session_dates:
        streak += 1
        cursor -= timedelta(days=1)

    week_start = as_of_date - timedelta(days=as_of_date.weekday())
    sessions_this_week = sum(1 for session in window_sessions if session.session_date >= week_start)
    weeks = window_days / 7
    return FlexibilityConsistency(
        current_streak=streak,
        sessions_this_week=sessions_this_week,
        sessions_4w=len(window_sessions),
        sessions_per_week_4w=round(len(window_sessions) / weeks, 2) if weeks > 0 else 0.0,
    )


def _relevant_holiday_windows(
    windows: Sequence[HolidayWindow],
    *,
    subject_date: date,
    horizon_days: int = FORWARD_PLAN_DAYS,
) -> list[HolidayWindow]:
    horizon_end = subject_date + timedelta(days=horizon_days)
    return [
        window
        for window in windows
        if window.end_date >= subject_date and window.start_date <= horizon_end
    ]


def _holiday_context(
    windows: Sequence[HolidayWindow],
    *,
    subject_date: date,
    horizon_days: int = FORWARD_PLAN_DAYS,
) -> dict[str, Any]:
    next_week_start = subject_date + timedelta(days=1)
    next_week_end = subject_date + timedelta(days=7)
    return {
        "forwardHorizonDays": horizon_days,
        "nextWeekIsHoliday": any(
            window.start_date <= next_week_end and window.end_date >= next_week_start
            for window in windows
        ),
        "windows": [
            {
                "startDate": window.start_date.isoformat(),
                "endDate": window.end_date.isoformat(),
                "isActive": window.is_active,
            }
            for window in windows
        ],
    }


def _planned_workout_with_holiday(
    workout: PlannedWorkout,
    windows: Sequence[HolidayWindow],
) -> dict[str, Any]:
    packet = _planned_workout_packet(workout)
    inside_holiday = any(
        window.start_date <= workout.workout_date <= window.end_date for window in windows
    )
    packet["insideHolidayWindow"] = inside_holiday
    packet["isLive"] = workout.status != "skipped" and not inside_holiday
    return packet


class PostFlexibilityAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_flexibility_activities(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> list[Activity]:
        lower_bound = since or (_utcnow() - timedelta(days=7))
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(Activity.user_id == user_id, Activity.start_utc >= lower_bound)
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )

        pending: list[Activity] = []
        for activity in rows:
            if not is_flexibility_activity(activity):
                continue
            latest = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._activity_checkin(activity.user_id, activity.id)
            if latest is None or not _analysis_covers_activity_checkin(latest, checkin):
                pending.append(activity)
        return pending

    async def generate_for_pending_flexibility(
        self,
        player: Profile,
        *,
        since: datetime | None = None,
        client: FlexibilityAnalysisClient | None = None,
        commit: bool = True,
    ) -> list[FlexibilityAnalysisResult]:
        results: list[FlexibilityAnalysisResult] = []
        for activity in await self.pending_flexibility_activities(player.id, since=since):
            results.append(
                await self.generate_and_store(
                    player,
                    activity,
                    client=client,
                    commit=False,
                )
            )
        if commit:
            await self.session.commit()
            for result in results:
                await self.session.refresh(result.analysis)
        else:
            await self.session.flush()
        return results

    async def assemble_flexibility_packet(
        self, player: Profile, activity: Activity
    ) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        subject_date = _activity_local_date(activity, player.timezone)
        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        holiday_windows = _relevant_holiday_windows(
            await HolidayPauseService(self.session).get_windows(player),
            subject_date=subject_date,
        )
        holiday_context = _holiday_context(holiday_windows, subject_date=subject_date)
        daily_metric = await self._daily_metric(player.id, subject_date)
        checkin = await self._activity_checkin(player.id, activity.id)
        sessions = await self._flexibility_sessions(player.id, as_of=subject_date)
        consistency = compute_flexibility_consistency(sessions, as_of_date=subject_date)

        resting_hr = daily_metric.resting_heart_rate_bpm if daily_metric else None
        avg_hr = activity.avg_heart_rate_bpm
        return {
            "packetType": "post_flexibility_analysis",
            "packetVersion": 1,
            "subjectDate": subject_date.isoformat(),
            "subjectWeekday": subject_date.strftime("%A"),
            "generatedAtUtc": _utcnow().isoformat() + "Z",
            "profile": {
                "userId": str(player.id),
                "displayName": player.display_name,
                "timezone": player.timezone,
                "athleteProfile": knowledge_base.get("profile", {}),
            },
            "knowledgeBase": {
                "dataQualityGuardrails": _data_quality_guardrails(knowledge_base),
                "trainingPlan": knowledge_base.get("training_plan", {}),
                "trainingSchedule": serialize_training_schedule(knowledge_base),
                "analysisRules": _analysis_rules(knowledge_base),
            },
            "activity": _flexibility_activity_packet(activity),
            "heartRateReview": {
                "restingHeartRateBpm": resting_hr,
                "avgHeartRateBpm": avg_hr,
                "avgAboveRestingBpm": (avg_hr - resting_hr)
                if avg_hr is not None and resting_hr is not None
                else None,
                "maxHeartRateBpm": activity.max_heart_rate_bpm,
            },
            "consistency": {
                "currentStreak": consistency.current_streak,
                "sessionsThisWeek": consistency.sessions_this_week,
                "sessions4w": consistency.sessions_4w,
                "sessionsPerWeek4w": consistency.sessions_per_week_4w,
                "interpretation": "established_daily_mobility_habit",
            },
            "mobilityBaseline": {
                "cadence": "daily",
                "isBaselineHabit": True,
                "weeklyRhythmScope": "cycling_only",
                "countsAsRecoveryLoad": False,
            },
            "holidayContext": holiday_context,
            "plannedWorkouts": [
                _planned_workout_with_holiday(workout, holiday_windows)
                for workout in planned_workouts
            ],
            "activityCheckIn": _manual_entry_packet(checkin),
            "guardrails": {
                "advisoryOnly": True,
                "neverFeedsRecoveryDecision": True,
                "noPowerZonesCadenceStaminaPcTrainingEffectOrTimeseries": True,
            },
            "prompt": {
                "version": PROMPT_VERSION,
                "system": SYSTEM_PROMPT,
                "outputRules": [
                    "acknowledge_mobility_session",
                    "read_consistency_and_streak",
                    "use_supplied_subject_weekday_never_derive_it",
                    "treat_daily_mobility_as_baseline_not_plan_overshoot",
                    "ignore_non_live_workouts_inside_holiday_windows",
                    "flag_unusually_high_heart_rate_when_present",
                    "give_one_light_mobility_only_next_step",
                    "do_not_discuss_power_or_zones",
                    "do_not_make_recovery_decisions",
                ],
            },
        }

    async def generate_and_store(
        self,
        player: Profile,
        activity: Activity,
        *,
        client: FlexibilityAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> FlexibilityAnalysisResult:
        if not force:
            existing = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._activity_checkin(player.id, activity.id)
            if existing is not None and _analysis_covers_activity_checkin(existing, checkin):
                return FlexibilityAnalysisResult(analysis=existing, generated=False)

        context_packet = await self.assemble_flexibility_packet(player, activity)
        user_prompt = build_flexibility_user_prompt(context_packet)
        analysis_client = client or AnthropicFlexibilityAnalysisClient()
        generation = await analysis_client.generate(
            context_packet=context_packet,
            user_prompt=user_prompt,
        )
        subject_date = _activity_local_date(activity, player.timezone)
        analysis = Analysis(
            user_id=player.id,
            activity_id=activity.id,
            analysis_type=ANALYSIS_TYPE,
            subject_date=subject_date,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
            model_name=generation.model_name,
            verdict="advisory",
            context_packet=context_packet,
            output_markdown=generation.output_markdown,
            raw_response=generation.raw_response,
        )
        self.session.add(analysis)
        if commit:
            await self.session.commit()
            await self.session.refresh(analysis)
        else:
            await self.session.flush()
        return FlexibilityAnalysisResult(analysis=analysis, generated=True)

    async def latest_analysis_for_activity(self, activity_id: uuid.UUID) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.activity_id == activity_id,
                    Analysis.analysis_type == ANALYSIS_TYPE,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    async def _active_knowledge_base(self, user_id: uuid.UUID) -> list[KnowledgeBase]:
        rows = (
            (
                await self.session.execute(
                    select(KnowledgeBase)
                    .where(KnowledgeBase.user_id == user_id, KnowledgeBase.is_active.is_(True))
                    .order_by(KnowledgeBase.section.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _planned_workouts(
        self, user_id: uuid.UUID, subject_date: date
    ) -> list[PlannedWorkout]:
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date >= subject_date,
                        PlannedWorkout.workout_date
                        <= subject_date + timedelta(days=FORWARD_PLAN_DAYS),
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.workout_date.asc(), PlannedWorkout.version.desc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _daily_metric(self, user_id: uuid.UUID, subject_date: date) -> DailyMetric | None:
        return cast(
            DailyMetric | None,
            await self.session.scalar(
                select(DailyMetric).where(
                    DailyMetric.user_id == user_id,
                    DailyMetric.calendar_date == subject_date,
                )
            ),
        )

    async def _activity_checkin(
        self, user_id: uuid.UUID, activity_id: uuid.UUID
    ) -> ManualEntry | None:
        return cast(
            ManualEntry | None,
            await self.session.scalar(
                select(ManualEntry)
                .where(
                    ManualEntry.user_id == user_id,
                    ManualEntry.activity_id == activity_id,
                )
                .order_by(desc(ManualEntry.entry_at_utc), desc(ManualEntry.created_at))
                .limit(1)
            ),
        )

    async def _flexibility_sessions(
        self,
        user_id: uuid.UUID,
        *,
        as_of: date,
    ) -> list[FlexibilitySession]:
        start = as_of - timedelta(days=WINDOW_4W_DAYS)
        lower_bound = datetime(start.year, start.month, start.day)
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(Activity.user_id == user_id, Activity.start_utc >= lower_bound)
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return [
            FlexibilitySession(
                activity_id=row.id,
                session_date=row.start_utc.date(),
                duration_min=_minutes(row.duration_sec),
            )
            for row in rows
            if row.start_utc.date() <= as_of and is_flexibility_activity(row)
        ]


def build_flexibility_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate the post-flexibility CheckMark analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _flexibility_activity_packet(row: Activity) -> dict[str, Any]:
    packet = _activity_packet(row)
    allowed = {
        "id",
        "garminActivityId",
        "garminActivityUuid",
        "activityName",
        "activityType",
        "startUtc",
        "endUtc",
        "durationMin",
        "elapsedDurationMin",
        "movingDurationMin",
        "distanceM",
        "calories",
        "avgHeartRateBpm",
        "maxHeartRateBpm",
        "excludeFromRecovery",
    }
    return {key: value for key, value in packet.items() if key in allowed}


def _analysis_covers_activity_checkin(
    analysis: Analysis,
    checkin: ManualEntry | None,
) -> bool:
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    packet_checkin = packet.get("activityCheckIn")
    if checkin is None:
        return packet_checkin is None
    if not isinstance(packet_checkin, dict):
        return False
    return packet_checkin.get("entryAtUtc") == _dt(checkin.entry_at_utc)
