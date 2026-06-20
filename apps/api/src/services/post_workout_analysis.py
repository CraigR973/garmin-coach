"""Post-workout analysis context assembly, trigger selection, and Claude boundary."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Activity,
    ActivityTimeSeries,
    Analysis,
    KnowledgeBase,
    PlannedWorkout,
)
from src.models.profile import Profile
from src.services.coaching_state import CoachingStateService

PROMPT_VERSION = "post-workout-analysis-v1-2026-06-20"
ANALYSIS_TYPE = "post_workout"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are Garmin Coach, a private endurance post-workout analyst.
Use only the supplied context packet. Follow every data-quality guardrail.
Return concise markdown with a workout rating, performance read, specific timed
recovery protocol, and tomorrow impact. Include power, HR, zones, cadence,
Performance Condition, Stamina, and Training Effect when present. Never mention
left/right power balance. Do not use wrist-HR strength sessions for recovery
decisions."""


class PostWorkoutAnalysisError(RuntimeError):
    """Raised when post-workout analysis cannot be generated."""


@dataclass(frozen=True)
class ClaudeGenerationResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str | None


@dataclass(frozen=True)
class PostWorkoutAnalysisResult:
    analysis: Analysis
    generated: bool


class PostWorkoutAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled post-workout packet."""


class AnthropicPostWorkoutAnalysisClient:
    """Small HTTP boundary for Anthropic Messages without adding an SDK dependency."""

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

        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=payload)
            response.raise_for_status()
            raw = response.json()

        if not isinstance(raw, dict):
            raise PostWorkoutAnalysisError("Claude response was not a JSON object.")

        text_parts: list[str] = []
        content = raw.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
        output = "\n\n".join(text_parts).strip()
        if not output:
            raise PostWorkoutAnalysisError("Claude response did not contain text output.")

        model = raw.get("model")
        return ClaudeGenerationResult(
            output_markdown=output,
            raw_response=raw,
            model_name=model if isinstance(model, str) else self.model_name,
        )


class PostWorkoutAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_ride_activities(
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
                    .where(
                        Activity.user_id == user_id,
                        Activity.start_utc >= lower_bound,
                        Activity.exclude_from_recovery.is_(False),
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )

        pending: list[Activity] = []
        for activity in rows:
            if not _is_ride(activity):
                continue
            if await self.latest_analysis_for_activity(activity.id) is None:
                pending.append(activity)
        return pending

    async def generate_for_pending_rides(
        self,
        player: Profile,
        *,
        since: datetime | None = None,
        client: PostWorkoutAnalysisClient | None = None,
        commit: bool = True,
    ) -> list[PostWorkoutAnalysisResult]:
        results: list[PostWorkoutAnalysisResult] = []
        for activity in await self.pending_ride_activities(player.id, since=since):
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

    async def assemble_context_packet(self, player: Profile, activity: Activity) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        subject_date = _activity_local_date(activity, player.timezone)
        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        morning_analysis = await self._latest_morning_analysis(player.id, subject_date)
        timeseries = await self._timeseries(activity.id)
        ftp_watts = _ftp_watts(knowledge_base)
        time_series_summary = _time_series_summary(timeseries, ftp_watts)
        recovery_decision = _recovery_decision_packet(activity)

        return {
            "packetType": "post_workout_analysis",
            "packetVersion": 1,
            "subjectDate": subject_date.isoformat(),
            "generatedAtUtc": _utcnow().isoformat() + "Z",
            "profile": {
                "userId": str(player.id),
                "displayName": player.display_name,
                "timezone": player.timezone,
                "athleteProfile": knowledge_base.get("profile", {}),
                "ftpWatts": ftp_watts,
            },
            "knowledgeBase": {
                "dataQualityGuardrails": _data_quality_guardrails(knowledge_base),
                "trainingPlan": knowledge_base.get("training_plan", {}),
                "analysisRules": knowledge_base.get("analysis_rules", {}),
            },
            "activity": _activity_packet(activity),
            "timeSeriesSummary": time_series_summary,
            "plannedWorkouts": [_planned_workout_packet(workout) for workout in planned_workouts],
            "morningVerdict": _morning_analysis_packet(morning_analysis),
            "recoveryDecision": recovery_decision,
            "prompt": {
                "version": PROMPT_VERSION,
                "system": SYSTEM_PROMPT,
                "outputRules": [
                    "include_workout_rating",
                    "include_power_hr_zones_cadence_performance_condition_stamina_training_effect",
                    "include_specific_timed_recovery_protocol",
                    "include_tomorrow_impact",
                    "never_reference_left_right_power_balance",
                    "exclude_wrist_hr_strength_from_recovery_decisions",
                ],
            },
        }

    async def generate_and_store(
        self,
        player: Profile,
        activity: Activity,
        *,
        client: PostWorkoutAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> PostWorkoutAnalysisResult:
        if not force:
            existing = await self.latest_analysis_for_activity(activity.id)
            if existing is not None:
                return PostWorkoutAnalysisResult(analysis=existing, generated=False)

        context_packet = await self.assemble_context_packet(player, activity)
        user_prompt = build_post_workout_user_prompt(context_packet)
        analysis_client = client or AnthropicPostWorkoutAnalysisClient()
        generation = await analysis_client.generate(
            context_packet=context_packet,
            user_prompt=user_prompt,
        )
        subject_date = _activity_local_date(activity, player.timezone)
        verdict = context_packet.get("recoveryDecision", {}).get("status")
        analysis = Analysis(
            user_id=player.id,
            activity_id=activity.id,
            analysis_type=ANALYSIS_TYPE,
            subject_date=subject_date,
            generated_at_utc=_utcnow(),
            prompt_version=PROMPT_VERSION,
            model_name=generation.model_name,
            verdict=verdict if isinstance(verdict, str) else None,
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
        return PostWorkoutAnalysisResult(analysis=analysis, generated=True)

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
        self,
        user_id: uuid.UUID,
        subject_date: date,
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

    async def _latest_morning_analysis(
        self,
        user_id: uuid.UUID,
        subject_date: date,
    ) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == "morning",
                    Analysis.subject_date == subject_date,
                )
                .order_by(desc(Analysis.generated_at_utc), desc(Analysis.created_at))
                .limit(1)
            ),
        )

    async def _timeseries(self, activity_id: uuid.UUID) -> list[ActivityTimeSeries]:
        rows = (
            (
                await self.session.execute(
                    select(ActivityTimeSeries)
                    .where(ActivityTimeSeries.activity_id == activity_id)
                    .order_by(ActivityTimeSeries.sample_index.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


def build_post_workout_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate the post-workout Garmin Coach analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_ride(activity: Activity) -> bool:
    activity_type = activity.activity_type.lower()
    activity_name = activity.activity_name.lower()
    return any(token in activity_type or token in activity_name for token in ("cycling", "bike"))


def _activity_local_date(activity: Activity, timezone_name: str) -> date:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("UTC")
        return activity.start_utc.replace(tzinfo=UTC).astimezone(timezone).date()
    except Exception:
        return activity.start_utc.date()


def _data_quality_guardrails(knowledge_base: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = knowledge_base.get("data_quality_rules", {})
    rules = section.get("rules") if isinstance(section, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _ftp_watts(knowledge_base: Mapping[str, Any]) -> int | None:
    profile = knowledge_base.get("profile", {})
    if not isinstance(profile, dict):
        return None
    ftp = profile.get("ftpWatts")
    if isinstance(ftp, int | float):
        return int(ftp)
    return None


def _activity_packet(row: Activity) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "garminActivityId": row.garmin_activity_id,
        "garminActivityUuid": row.garmin_activity_uuid,
        "activityName": row.activity_name,
        "activityType": row.activity_type,
        "startUtc": _dt(row.start_utc),
        "endUtc": _dt(row.end_utc),
        "durationMin": _minutes(row.duration_sec),
        "elapsedDurationMin": _minutes(row.elapsed_duration_sec),
        "movingDurationMin": _minutes(row.moving_duration_sec),
        "distanceM": row.distance_m,
        "calories": row.calories,
        "avgHeartRateBpm": row.avg_heart_rate_bpm,
        "maxHeartRateBpm": row.max_heart_rate_bpm,
        "avgPowerWatts": row.avg_power_watts,
        "maxPowerWatts": row.max_power_watts,
        "normalizedPowerWatts": row.normalized_power_watts,
        "intensityFactor": row.intensity_factor,
        "trainingLoad": row.training_load,
        "aerobicTrainingEffect": row.aerobic_training_effect,
        "anaerobicTrainingEffect": row.anaerobic_training_effect,
        "avgCadenceRpm": row.avg_cadence_rpm,
        "maxCadenceRpm": row.max_cadence_rpm,
        "avgRespiration": row.avg_respiration,
        "maxRespiration": row.max_respiration,
        "excludeFromRecovery": row.exclude_from_recovery,
    }


def _time_series_summary(
    rows: Sequence[ActivityTimeSeries],
    ftp_watts: int | None,
) -> dict[str, Any]:
    power_values = [row.power_watts for row in rows if row.power_watts is not None]
    hr_values = [row.heart_rate_bpm for row in rows if row.heart_rate_bpm is not None]
    cadence_values = [row.cadence_rpm for row in rows if row.cadence_rpm is not None]
    respiration_values = [row.respiration for row in rows if row.respiration is not None]
    pc_values = [row.performance_condition for row in rows if row.performance_condition is not None]
    available_stamina_values = [
        row.available_stamina for row in rows if row.available_stamina is not None
    ]
    potential_stamina_values = [
        row.potential_stamina for row in rows if row.potential_stamina is not None
    ]

    return {
        "sampleCount": len(rows),
        "power": _series_stats(power_values),
        "heartRate": _series_stats(hr_values),
        "cadence": _series_stats(cadence_values),
        "respiration": _series_stats(respiration_values),
        "performanceCondition": {
            **_series_stats(pc_values),
            "start": pc_values[0] if pc_values else None,
            "end": pc_values[-1] if pc_values else None,
        },
        "stamina": {
            "availableStart": available_stamina_values[0] if available_stamina_values else None,
            "availableEnd": available_stamina_values[-1] if available_stamina_values else None,
            "availableMin": min(available_stamina_values) if available_stamina_values else None,
            "potentialStart": potential_stamina_values[0] if potential_stamina_values else None,
            "potentialEnd": potential_stamina_values[-1] if potential_stamina_values else None,
        },
        "powerZones": _power_zone_distribution(rows, ftp_watts),
    }


def _series_stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {
        "avg": round(sum(values) / len(values), 2),
        "min": min(values),
        "max": max(values),
    }


def _power_zone_distribution(
    rows: Sequence[ActivityTimeSeries],
    ftp_watts: int | None,
) -> list[dict[str, Any]]:
    if ftp_watts is None:
        return []
    counts: Counter[str] = Counter()
    for row in rows:
        if row.power_watts is None:
            continue
        counts[_power_zone(row.power_watts, ftp_watts)] += 1
    total = sum(counts.values())
    if total == 0:
        return []
    return [
        {
            "zone": zone,
            "sampleCount": counts[zone],
            "samplePct": round((counts[zone] / total) * 100, 1),
        }
        for zone in ("Z1", "Z2", "Z3", "Z4", "Z5", "Z6")
        if counts[zone] > 0
    ]


def _power_zone(power_watts: float, ftp_watts: int) -> str:
    pct = power_watts / ftp_watts
    if pct < 0.56:
        return "Z1"
    if pct < 0.76:
        return "Z2"
    if pct < 0.91:
        return "Z3"
    if pct < 1.06:
        return "Z4"
    if pct < 1.21:
        return "Z5"
    return "Z6"


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
        "structuredWorkout": row.structured_workout,
        "source": row.source,
    }


def _morning_analysis_packet(row: Analysis | None) -> dict[str, Any] | None:
    if row is None:
        return None
    verdict = row.context_packet.get("verdict", {}) if isinstance(row.context_packet, dict) else {}
    return {
        "id": str(row.id),
        "generatedAtUtc": _dt(row.generated_at_utc),
        "verdict": row.verdict,
        "reasons": verdict.get("reasons", []) if isinstance(verdict, dict) else [],
        "planAdjustments": verdict.get("planAdjustments", []) if isinstance(verdict, dict) else [],
        "readinessInterpretation": (
            verdict.get("readinessInterpretation") if isinstance(verdict, dict) else None
        ),
    }


def _recovery_decision_packet(activity: Activity) -> dict[str, Any]:
    if activity.exclude_from_recovery:
        return {
            "status": "excluded",
            "excluded": True,
            "reason": "Strength/wrist-HR activity is excluded from recovery decisions.",
        }
    return {
        "status": "ready_for_review",
        "excluded": False,
        "reason": "Cycling activity can inform post-workout recovery guidance.",
    }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _minutes(seconds: float | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None
