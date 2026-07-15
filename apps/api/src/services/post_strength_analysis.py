"""Post-strength analysis for Garmin strength sessions (Batch 43).

The per-session counterpart to Batch 40 (post-flexibility). Same Batch 8
machinery — hourly poll → ``generate_for_pending_strength`` → lean packet → thin
Anthropic boundary → ``analyses`` (``analysis_type='post_strength'``) → daily
loop — keyed on the Garmin strength activity.

Higher-reuse than Batch 40: the selector already exists
(``is_strength_activity`` via ``exclude_from_recovery``, #49/#80) and the
consistency read reuses Batch 19's pure ``compute_strength_rollup``, so the only
new pieces here are a lean HR/consistency packet (no power/FTP/time-series) and a
strength-coach prompt.

Recovery isolation (#49/#80) preserved: this analysis is advisory only. It never
feeds verdict or recovery decisions, and the packet omits power/FTP/cadence/
stamina/Performance Condition/Training Effect/zones/time-series.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
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
from src.services.post_workout_analysis import (
    ClaudeGenerationResult,
    PostWorkoutAnalysisError,
    _activity_local_date,
    _activity_packet,
    _analysis_rules,
    _data_quality_guardrails,
    _dt,
    _manual_entry_packet,
    _planned_workout_packet,
    _utcnow,
)
from src.services.strength_brief import (
    WINDOW_12W_DAYS,
    StrengthBriefResult,
    StrengthSession,
    compute_strength_rollup,
    is_strength_activity,
)

PROMPT_VERSION = "post-strength-analysis-v3-2026-07-12"
ANALYSIS_TYPE = "post_strength"

SYSTEM_PROMPT = """You are CheckMark, a private strength and conditioning coach.
Use `subjectWeekday` as the authoritative weekday; never derive the weekday from
`subjectDate` yourself.
Use only the supplied context packet. Follow every data-quality guardrail.
Return concise markdown that acknowledges the strength session, reads frequency
and consistency against the recent trend, notes whether heart rate was unusually
high for a strength session, and gives one light next step. This is advisory
only: the session was recorded on a wrist heart-rate monitor, so do not make
cycling recovery decisions from it, and do not discuss power, FTP, cadence,
stamina, Performance Condition, Training Effect, or zones.
If the activity check-in notes contain a question, answer it directly using only
the supplied packet; say when the available data cannot support an answer."""


@dataclass(frozen=True)
class StrengthAnalysisResult:
    analysis: Analysis
    generated: bool


class StrengthAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled strength packet."""


class AnthropicStrengthAnalysisClient:
    """Small HTTP boundary for Anthropic Messages, using the strength prompt."""

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


def _consistency_packet(rollup: StrengthBriefResult) -> dict[str, Any]:
    """Serialize the reused Batch 19 rollup into the lean packet's consistency block."""

    return {
        "sessions4w": rollup.window_4w.session_count,
        "sessionsPerWeek4w": rollup.window_4w.sessions_per_week,
        "totalDurationMin4w": rollup.window_4w.total_duration_min,
        "sessions12w": rollup.window_12w.session_count,
        "sessionsPerWeek12w": rollup.window_12w.sessions_per_week,
        "trend": rollup.trend,
        "trendReason": rollup.trend_reason,
    }


class PostStrengthAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_strength_activities(
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
            if not is_strength_activity(activity):
                continue
            latest = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._activity_checkin(activity.user_id, activity.id)
            if latest is None or not _analysis_covers_activity_checkin(latest, checkin):
                pending.append(activity)
        return pending

    async def generate_for_pending_strength(
        self,
        player: Profile,
        *,
        since: datetime | None = None,
        client: StrengthAnalysisClient | None = None,
        commit: bool = True,
    ) -> list[StrengthAnalysisResult]:
        results: list[StrengthAnalysisResult] = []
        for activity in await self.pending_strength_activities(player.id, since=since):
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

    async def assemble_strength_packet(self, player: Profile, activity: Activity) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        subject_date = _activity_local_date(activity, player.timezone)
        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        daily_metric = await self._daily_metric(player.id, subject_date)
        checkin = await self._activity_checkin(player.id, activity.id)
        sessions = await self._strength_sessions(player.id, as_of=subject_date)
        rollup = compute_strength_rollup(sessions, as_of_date=subject_date)

        resting_hr = daily_metric.resting_heart_rate_bpm if daily_metric else None
        avg_hr = activity.avg_heart_rate_bpm
        return {
            "packetType": "post_strength_analysis",
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
                "analysisRules": _analysis_rules(knowledge_base),
            },
            "activity": _strength_activity_packet(activity),
            "heartRateReview": {
                "restingHeartRateBpm": resting_hr,
                "avgHeartRateBpm": avg_hr,
                "avgAboveRestingBpm": (avg_hr - resting_hr)
                if avg_hr is not None and resting_hr is not None
                else None,
                "maxHeartRateBpm": activity.max_heart_rate_bpm,
                "wristHeartRateNote": (
                    "Strength heart rate is wrist-based and excluded from recovery decisions (#49)."
                ),
            },
            "consistency": _consistency_packet(rollup),
            "plannedWorkouts": [_planned_workout_packet(workout) for workout in planned_workouts],
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
                    "acknowledge_strength_session",
                    "read_frequency_and_trend",
                    "flag_unusually_high_heart_rate_when_present",
                    "give_one_light_next_step",
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
        client: StrengthAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> StrengthAnalysisResult:
        if not force:
            existing = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._activity_checkin(player.id, activity.id)
            if existing is not None and _analysis_covers_activity_checkin(existing, checkin):
                return StrengthAnalysisResult(analysis=existing, generated=False)

        context_packet = await self.assemble_strength_packet(player, activity)
        user_prompt = build_strength_user_prompt(context_packet)
        analysis_client = client or AnthropicStrengthAnalysisClient()
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
        return StrengthAnalysisResult(analysis=analysis, generated=True)

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
                        PlannedWorkout.workout_date == subject_date,
                        PlannedWorkout.is_active.is_(True),
                    )
                    .order_by(PlannedWorkout.version.desc())
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

    async def _strength_sessions(
        self,
        user_id: uuid.UUID,
        *,
        as_of: date,
    ) -> list[StrengthSession]:
        start = as_of - timedelta(days=WINDOW_12W_DAYS)
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
            StrengthSession(
                activity_id=row.id,
                activity_name=row.activity_name,
                activity_type=row.activity_type,
                session_date=row.start_utc.date(),
                duration_min=(
                    round(row.duration_sec / 60) if row.duration_sec is not None else None
                ),
                training_load=(float(row.training_load) if row.training_load is not None else None),
            )
            for row in rows
            if row.start_utc.date() <= as_of and is_strength_activity(row)
        ]


def build_strength_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate the post-strength CheckMark analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _strength_activity_packet(row: Activity) -> dict[str, Any]:
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
