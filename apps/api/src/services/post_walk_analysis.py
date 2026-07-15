"""Post-walk analysis for deliberate Garmin walking activities (Batch 41)."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Activity,
    ActivityTimeSeries,
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
    _minutes,
    _planned_workout_packet,
    _series_stats,
    _utcnow,
)

PROMPT_VERSION = "post-walk-analysis-v3-2026-07-12"
ANALYSIS_TYPE = "post_walk"
WALK_ANALYSIS_MIN_DURATION_SEC = 30 * 60
WALK_ANALYSIS_MIN_DISTANCE_M = 3_000
ACTIVE_RECOVERY_WINDOW_DAYS = 7

SYSTEM_PROMPT = """You are CheckMark, a private Zone-2 walking and active-recovery coach.
Use only the supplied context packet. Follow every data-quality guardrail.
Use `subjectWeekday` as the authoritative weekday; never derive the weekday from
`subjectDate` yourself.
Return concise markdown that reads whether this was genuine easy aerobic work,
notes pace/heart-rate drift when the data supports it, places the walk in recent
active-recovery volume, and gives one practical next step. This is advisory only:
do not make cycling recovery decisions and do not discuss power, FTP, cadence,
stamina, Performance Condition, or Training Effect.
If the activity check-in notes contain a question, answer it directly using only
the supplied packet; say when the available data cannot support an answer."""


@dataclass(frozen=True)
class WalkAnalysisResult:
    analysis: Analysis
    generated: bool


class WalkAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled walk packet."""


class AnthropicWalkAnalysisClient:
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


def is_deliberate_walk(activity: Activity) -> bool:
    return (activity.activity_type or "").lower() == "walking" and (
        (activity.duration_sec or 0) >= WALK_ANALYSIS_MIN_DURATION_SEC
        or (activity.distance_m or 0) >= WALK_ANALYSIS_MIN_DISTANCE_M
    )


def active_recovery_walk_context(
    activities: Sequence[Activity],
    *,
    as_of_date: date,
    window_days: int = ACTIVE_RECOVERY_WINDOW_DAYS,
) -> dict[str, Any]:
    window_start = as_of_date - timedelta(days=window_days)
    walks = [
        activity
        for activity in activities
        if is_deliberate_walk(activity) and window_start < activity.start_utc.date() <= as_of_date
    ]
    total_distance_m = sum(activity.distance_m or 0.0 for activity in walks)
    total_duration_min = sum(_minutes(activity.duration_sec) or 0 for activity in walks)
    return {
        "windowDays": window_days,
        "deliberateWalkCount": len(walks),
        "totalDistanceM": round(total_distance_m, 1),
        "totalDurationMin": total_duration_min,
        "advisoryOnly": True,
    }


class PostWalkAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_walk_activities(
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
                        Activity.activity_type == "walking",
                        Activity.start_utc >= lower_bound,
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        pending: list[Activity] = []
        for activity in rows:
            if not is_deliberate_walk(activity):
                continue
            latest = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._activity_checkin(activity.user_id, activity.id)
            if latest is None or not _analysis_covers_activity_checkin(latest, checkin):
                pending.append(activity)
        return pending

    async def generate_for_pending_walks(
        self,
        player: Profile,
        *,
        since: datetime | None = None,
        client: WalkAnalysisClient | None = None,
        commit: bool = True,
    ) -> list[WalkAnalysisResult]:
        results: list[WalkAnalysisResult] = []
        for activity in await self.pending_walk_activities(player.id, since=since):
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

    async def assemble_walk_packet(self, player: Profile, activity: Activity) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        subject_date = _activity_local_date(activity, player.timezone)
        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        daily_metric = await self._daily_metric(player.id, subject_date)
        checkin = await self._activity_checkin(player.id, activity.id)
        timeseries = await self._timeseries(activity.id)
        recent_walks = await self._recent_walks(player.id, as_of=subject_date)
        hr_zones = _hr_zone_model(knowledge_base)
        walk_summary = _walk_time_series_summary(timeseries, hr_zones["bounds"])

        return {
            "packetType": "post_walk_analysis",
            "packetVersion": 1,
            "subjectDate": subject_date.isoformat(),
            "subjectWeekday": subject_date.strftime("%A"),
            "generatedAtUtc": _utcnow().isoformat() + "Z",
            "profile": {
                "userId": str(player.id),
                "displayName": player.display_name,
                "timezone": player.timezone,
                "athleteProfile": knowledge_base.get("profile", {}),
                "heartRateZones": hr_zones,
            },
            "knowledgeBase": {
                "dataQualityGuardrails": _data_quality_guardrails(knowledge_base),
                "trainingPlan": knowledge_base.get("training_plan", {}),
                "analysisRules": _analysis_rules(knowledge_base),
            },
            "activity": _walk_activity_packet(activity),
            "heartRateReview": {
                "restingHeartRateBpm": daily_metric.resting_heart_rate_bpm
                if daily_metric
                else None,
                "avgHeartRateBpm": activity.avg_heart_rate_bpm,
                "maxHeartRateBpm": activity.max_heart_rate_bpm,
                "hrZoneDistribution": walk_summary["heartRateZones"],
            },
            "paceReview": {
                "avgPaceMinPerKm": _pace_min_per_km(activity.distance_m, activity.duration_sec),
                "movingPaceMinPerKm": _pace_min_per_km(
                    activity.distance_m,
                    activity.moving_duration_sec,
                ),
                "speed": walk_summary["speed"],
                "paceDrift": walk_summary["paceDrift"],
            },
            "timeSeriesSummary": walk_summary,
            "activeRecoveryContext": active_recovery_walk_context(
                recent_walks,
                as_of_date=subject_date,
            ),
            "plannedWorkouts": [_planned_workout_packet(workout) for workout in planned_workouts],
            "activityCheckIn": _manual_entry_packet(checkin),
            "guardrails": {
                "advisoryOnly": True,
                "neverFeedsRecoveryDecision": True,
                "noPowerFtpCadenceStaminaPcTrainingEffect": True,
            },
            "prompt": {
                "version": PROMPT_VERSION,
                "system": SYSTEM_PROMPT,
                "outputRules": [
                    "read_easy_aerobic_or_active_recovery_value",
                    "use_hr_and_pace_not_power",
                    "note_hr_or_pace_drift_only_when_supported",
                    "give_one_practical_next_step",
                    "do_not_make_recovery_decisions",
                ],
            },
        }

    async def generate_and_store(
        self,
        player: Profile,
        activity: Activity,
        *,
        client: WalkAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> WalkAnalysisResult:
        if not force:
            existing = await self.latest_analysis_for_activity(activity.id)
            checkin = await self._activity_checkin(player.id, activity.id)
            if existing is not None and _analysis_covers_activity_checkin(existing, checkin):
                return WalkAnalysisResult(analysis=existing, generated=False)

        context_packet = await self.assemble_walk_packet(player, activity)
        user_prompt = build_walk_user_prompt(context_packet)
        analysis_client = client or AnthropicWalkAnalysisClient()
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
        return WalkAnalysisResult(analysis=analysis, generated=True)

    async def latest_analysis_for_activity(self, activity_id: uuid.UUID) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(Analysis.activity_id == activity_id, Analysis.analysis_type == ANALYSIS_TYPE)
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
                .where(ManualEntry.user_id == user_id, ManualEntry.activity_id == activity_id)
                .order_by(desc(ManualEntry.entry_at_utc), desc(ManualEntry.created_at))
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

    async def _recent_walks(self, user_id: uuid.UUID, *, as_of: date) -> list[Activity]:
        start = as_of - timedelta(days=ACTIVE_RECOVERY_WINDOW_DAYS)
        lower_bound = datetime(start.year, start.month, start.day)
        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .where(
                        Activity.user_id == user_id,
                        Activity.activity_type == "walking",
                        Activity.start_utc >= lower_bound,
                    )
                    .order_by(Activity.start_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return [row for row in rows if row.start_utc.date() <= as_of]


def build_walk_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate the post-walk CheckMark analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _walk_activity_packet(row: Activity) -> dict[str, Any]:
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


def _walk_time_series_summary(
    rows: Sequence[ActivityTimeSeries],
    hr_zone_bounds: Mapping[str, tuple[int, int | None]],
) -> dict[str, Any]:
    hr_values = [row.heart_rate_bpm for row in rows if row.heart_rate_bpm is not None]
    speed_values = [row.speed_mps for row in rows if row.speed_mps is not None]
    distance_values = [row.distance_m for row in rows if row.distance_m is not None]
    return {
        "sampleCount": len(rows),
        "heartRate": _series_stats(hr_values),
        "speed": _series_stats(speed_values),
        "heartRateZones": _heart_rate_zone_distribution(rows, hr_zone_bounds),
        "paceDrift": _pace_drift(rows),
        "distanceTrace": {
            "startM": distance_values[0] if distance_values else None,
            "endM": distance_values[-1] if distance_values else None,
        },
        "elevation": {"gainM": None, "source": "not_stored"},
    }


def _heart_rate_zone_distribution(
    rows: Sequence[ActivityTimeSeries],
    bounds: Mapping[str, tuple[int, int | None]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        if row.heart_rate_bpm is None:
            continue
        counts[_heart_rate_zone(row.heart_rate_bpm, bounds)] += 1
    total = sum(counts.values())
    if total == 0:
        return []
    return [
        {
            "zone": zone,
            "sampleCount": counts[zone],
            "samplePct": round((counts[zone] / total) * 100, 1),
        }
        for zone in ("Z1", "Z2", "Z3", "Z4", "Z5")
        if counts[zone] > 0
    ]


def _heart_rate_zone(
    heart_rate_bpm: float,
    bounds: Mapping[str, tuple[int, int | None]],
) -> str:
    for zone in ("Z1", "Z2", "Z3", "Z4", "Z5"):
        low, high = bounds[zone]
        if heart_rate_bpm >= low and (high is None or heart_rate_bpm <= high):
            return zone
    return "Z5"


def _pace_drift(rows: Sequence[ActivityTimeSeries]) -> dict[str, float | None]:
    usable = [row for row in rows if row.speed_mps is not None and row.heart_rate_bpm is not None]
    if len(usable) < 6:
        return {"firstHalfSpeedMps": None, "secondHalfSpeedMps": None, "heartRateDeltaBpm": None}
    midpoint = len(usable) // 2
    first = usable[:midpoint]
    second = usable[midpoint:]
    first_speed = sum(row.speed_mps or 0.0 for row in first) / len(first)
    second_speed = sum(row.speed_mps or 0.0 for row in second) / len(second)
    first_hr = sum(row.heart_rate_bpm or 0.0 for row in first) / len(first)
    second_hr = sum(row.heart_rate_bpm or 0.0 for row in second) / len(second)
    return {
        "firstHalfSpeedMps": round(first_speed, 2),
        "secondHalfSpeedMps": round(second_speed, 2),
        "heartRateDeltaBpm": round(second_hr - first_hr, 1),
    }


def _pace_min_per_km(distance_m: float | None, duration_sec: float | None) -> float | None:
    if not distance_m or distance_m <= 0 or not duration_sec or duration_sec <= 0:
        return None
    return round((duration_sec / 60) / (distance_m / 1000), 2)


def _hr_zone_model(knowledge_base: Mapping[str, Any]) -> dict[str, Any]:
    profile = knowledge_base.get("profile", {})
    explicit = profile.get("heartRateZones") if isinstance(profile, dict) else None
    if isinstance(explicit, dict):
        parsed = _parse_explicit_hr_zones(explicit)
        if parsed is not None:
            return {"source": "knowledge_base_profile", "bounds": parsed}

    max_hr = None
    if isinstance(profile, dict):
        raw_max = profile.get("maxHeartRateBpm") or profile.get("maxHrBpm")
        if isinstance(raw_max, int | float):
            max_hr = int(raw_max)
    max_hr = max_hr or 170
    bounds = {
        "Z1": (0, round(max_hr * 0.60)),
        "Z2": (round(max_hr * 0.60) + 1, round(max_hr * 0.70)),
        "Z3": (round(max_hr * 0.70) + 1, round(max_hr * 0.80)),
        "Z4": (round(max_hr * 0.80) + 1, round(max_hr * 0.90)),
        "Z5": (round(max_hr * 0.90) + 1, None),
    }
    return {"source": "max_hr_percent_fallback", "maxHeartRateBpm": max_hr, "bounds": bounds}


def _parse_explicit_hr_zones(raw: Mapping[str, Any]) -> dict[str, tuple[int, int | None]] | None:
    parsed: dict[str, tuple[int, int | None]] = {}
    for zone in ("Z1", "Z2", "Z3", "Z4", "Z5"):
        value = raw.get(zone) or raw.get(zone.lower())
        if not isinstance(value, dict):
            return None
        low = value.get("min") or value.get("low")
        high = value.get("max") or value.get("high")
        if not isinstance(low, int | float):
            return None
        if high is not None and not isinstance(high, int | float):
            return None
        parsed[zone] = (int(low), int(high) if high is not None else None)
    return parsed


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
