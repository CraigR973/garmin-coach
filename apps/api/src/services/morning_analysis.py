"""Morning analysis context assembly, verdict rules, and Claude boundary."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.coaching_state import CoachingStateService

PROMPT_VERSION = "morning-analysis-v1-2026-06-20"
ANALYSIS_TYPE = "morning"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are Garmin Coach, a private daily endurance and sleep coach.
Use only the supplied context packet. Follow every data-quality guardrail.
Return concise markdown with a sleep summary line, a metrics-vs-baselines read,
a thermal/environment review, and a Green/Amber/Red workout verdict for today.
Bold each bullet headline. Never mention left/right power balance. Never keep
VO2 work on a Red verdict. When Garmin readiness is Low, call it load-driven only
if the packet explicitly says recovery signals justify that interpretation."""


class MorningAnalysisError(RuntimeError):
    """Raised when morning analysis cannot be generated."""


@dataclass(frozen=True)
class ClaudeGenerationResult:
    output_markdown: str
    raw_response: dict[str, Any]
    model_name: str | None


class MorningAnalysisClient(Protocol):
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        """Generate the model output for an assembled morning packet."""


class AnthropicMorningAnalysisClient:
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
            raise MorningAnalysisError("ANTHROPIC_API_KEY is not configured.")

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
            raise MorningAnalysisError("Claude response was not a JSON object.")

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
            raise MorningAnalysisError("Claude response did not contain text output.")

        model = raw.get("model")
        return ClaudeGenerationResult(
            output_markdown=output,
            raw_response=raw,
            model_name=model if isinstance(model, str) else self.model_name,
        )


@dataclass(frozen=True)
class MorningAnalysisResult:
    analysis: Analysis
    generated: bool


class MorningAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assemble_context_packet(self, player: Profile, subject_date: date) -> dict[str, Any]:
        await CoachingStateService(self.session).ensure_seeded(player, commit=False)

        kb_rows = await self._active_knowledge_base(player.id)
        knowledge_base = {row.section: row.content for row in kb_rows}
        daily_metric = await self._daily_metric(player.id, subject_date)
        sleep = await self._sleep(player.id, subject_date)
        manual_entries = await self._manual_entries(player.id, subject_date)
        planned_workouts = await self._planned_workouts(player.id, subject_date)
        baselines = await self._metric_baselines(player.id)
        weather = await self._weather(player.id, subject_date)
        temperature_rows = await self._overnight_temperature_rows(
            player.id,
            subject_date,
            player.timezone,
        )

        age_adjusted_sleep_score = _age_adjusted_sleep_score(sleep, knowledge_base)
        metrics_table = _metrics_vs_baselines(
            daily_metric,
            sleep,
            baselines,
            age_adjusted_sleep_score,
        )
        thermal_review = _thermal_review(temperature_rows, weather, knowledge_base)
        verdict = _morning_verdict(
            daily_metric=daily_metric,
            sleep=sleep,
            age_adjusted_sleep_score=age_adjusted_sleep_score,
            manual_entries=manual_entries,
            planned_workouts=planned_workouts,
        )

        return {
            "packetType": "morning_analysis",
            "packetVersion": 1,
            "subjectDate": subject_date.isoformat(),
            "generatedAtUtc": _utcnow().isoformat() + "Z",
            "profile": _profile_packet(player, knowledge_base),
            "knowledgeBase": {
                "sections": [_knowledge_base_packet(row) for row in kb_rows],
                "dataQualityGuardrails": _data_quality_guardrails(knowledge_base),
                "sleepProtocol": knowledge_base.get("sleep_protocol", {}),
                "activeHypotheses": knowledge_base.get("active_hypotheses", {}),
            },
            "dailyMetrics": _daily_metric_packet(daily_metric),
            "sleep": _sleep_packet(sleep, age_adjusted_sleep_score),
            "manualEntries": [_manual_entry_packet(entry) for entry in manual_entries],
            "plannedWorkouts": [_planned_workout_packet(workout) for workout in planned_workouts],
            "metricsVsBaselines": metrics_table,
            "environment": {
                "thermalReview": thermal_review,
                "weather": _weather_packet(weather),
            },
            "verdict": verdict,
            "prompt": {
                "version": PROMPT_VERSION,
                "system": SYSTEM_PROMPT,
                "outputRules": [
                    "bold_each_bullet_headline",
                    "include_sleep_summary_line",
                    "include_metrics_vs_baselines_table",
                    "include_thermal_environment_review",
                    "include_plan_aware_workout_verdict",
                    "never_reference_left_right_power_balance",
                    "never_recommend_vo2_on_red",
                ],
            },
        }

    async def generate_and_store(
        self,
        player: Profile,
        subject_date: date,
        *,
        client: MorningAnalysisClient | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> MorningAnalysisResult:
        if not force:
            existing = await self.latest_analysis(player.id, subject_date)
            if existing is not None:
                return MorningAnalysisResult(analysis=existing, generated=False)

        context_packet = await self.assemble_context_packet(player, subject_date)
        user_prompt = build_morning_user_prompt(context_packet)
        analysis_client = client or AnthropicMorningAnalysisClient()
        generation = await analysis_client.generate(
            context_packet=context_packet,
            user_prompt=user_prompt,
        )
        verdict = context_packet.get("verdict", {}).get("status")
        analysis = Analysis(
            user_id=player.id,
            activity_id=None,
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
        return MorningAnalysisResult(analysis=analysis, generated=True)

    async def latest_analysis(self, user_id: uuid.UUID, subject_date: date) -> Analysis | None:
        return cast(
            Analysis | None,
            await self.session.scalar(
                select(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == ANALYSIS_TYPE,
                    Analysis.subject_date == subject_date,
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

    async def _sleep(self, user_id: uuid.UUID, subject_date: date) -> Sleep | None:
        return cast(
            Sleep | None,
            await self.session.scalar(
                select(Sleep).where(Sleep.user_id == user_id, Sleep.calendar_date == subject_date)
            ),
        )

    async def _manual_entries(self, user_id: uuid.UUID, subject_date: date) -> list[ManualEntry]:
        rows = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == subject_date,
                    )
                    .order_by(desc(ManualEntry.entry_at_utc))
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

    async def _metric_baselines(self, user_id: uuid.UUID) -> list[MetricBaseline]:
        rows = (
            (
                await self.session.execute(
                    select(MetricBaseline)
                    .where(MetricBaseline.user_id == user_id)
                    .order_by(MetricBaseline.metric_key.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _weather(self, user_id: uuid.UUID, subject_date: date) -> WeatherDaily | None:
        return cast(
            WeatherDaily | None,
            await self.session.scalar(
                select(WeatherDaily)
                .where(
                    WeatherDaily.user_id == user_id,
                    WeatherDaily.calendar_date == subject_date,
                )
                .order_by(desc(WeatherDaily.updated_at))
                .limit(1)
            )
        )

    async def _overnight_temperature_rows(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        timezone_name: str,
    ) -> list[TemperatureReading]:
        start_utc, end_utc = _overnight_window_utc(subject_date, timezone_name)
        rows = (
            (
                await self.session.execute(
                    select(TemperatureReading)
                    .where(
                        TemperatureReading.user_id == user_id,
                        TemperatureReading.captured_at_utc >= start_utc,
                        TemperatureReading.captured_at_utc <= end_utc,
                    )
                    .order_by(TemperatureReading.captured_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


def build_morning_user_prompt(context_packet: Mapping[str, Any]) -> str:
    return (
        "Generate today's morning Garmin Coach analysis from this context packet.\n\n"
        "Context packet JSON:\n"
        f"{json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)}"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _profile_packet(player: Profile, knowledge_base: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "userId": str(player.id),
        "displayName": player.display_name,
        "timezone": player.timezone,
        "latitude": player.latitude,
        "longitude": player.longitude,
        "athleteProfile": knowledge_base.get("profile", {}),
    }


def _knowledge_base_packet(row: KnowledgeBase) -> dict[str, Any]:
    return {
        "section": row.section,
        "version": row.version,
        "source": row.source,
        "content": row.content,
    }


def _data_quality_guardrails(knowledge_base: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = knowledge_base.get("data_quality_rules", {})
    rules = section.get("rules") if isinstance(section, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _daily_metric_packet(row: DailyMetric | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "recordedAtUtc": _dt(row.recorded_at_utc),
        "readinessScore": row.readiness_score,
        "readinessLevel": row.readiness_level,
        "readinessSleepScore": row.readiness_sleep_score,
        "recoveryTimeMin": row.recovery_time_min,
        "acuteLoad": row.acute_load,
        "trainingStatus": row.training_status,
        "hrvLastNightAvgMs": row.hrv_last_night_avg_ms,
        "hrvWeeklyAvgMs": row.hrv_weekly_avg_ms,
        "hrvStatus": row.hrv_status,
        "hrvBaselineLowMs": row.hrv_baseline_low_ms,
        "hrvBaselineHighMs": row.hrv_baseline_high_ms,
        "restingHeartRateBpm": row.resting_heart_rate_bpm,
        "stressAvg": row.stress_avg,
        "bodyBatteryCharged": row.body_battery_charged,
        "bodyBatteryDrained": row.body_battery_drained,
        "bodyBatteryEnd": row.body_battery_end,
        "weightKg": row.weight_kg,
        "vo2max": row.vo2max,
    }


def _sleep_packet(row: Sleep | None, age_adjusted_sleep_score: int | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "sleepStartUtc": _dt(row.sleep_start_utc),
        "sleepEndUtc": _dt(row.sleep_end_utc),
        "score": row.score,
        "ageAdjustedScore": age_adjusted_sleep_score,
        "qualifier": row.qualifier,
        "durationMin": _minutes(row.duration_sec),
        "deepSleepMin": _minutes(row.deep_sleep_sec),
        "lightSleepMin": _minutes(row.light_sleep_sec),
        "remSleepMin": _minutes(row.rem_sleep_sec),
        "awakeSleepMin": _minutes(row.awake_sleep_sec),
        "averageSpo2Pct": row.average_spo2_pct,
        "lowestSpo2Pct": row.lowest_spo2_pct,
        "averageRespiration": row.average_respiration,
        "restingHeartRateBpm": row.resting_heart_rate_bpm,
        "avgOvernightHrvMs": row.avg_overnight_hrv_ms,
        "hrvStatus": row.hrv_status,
        "avgSleepStress": row.avg_sleep_stress,
        "restlessMomentsCount": row.restless_moments_count,
        "bodyBatteryChange": row.body_battery_change,
    }


def _manual_entry_packet(row: ManualEntry) -> dict[str, Any]:
    return {
        "entryDate": row.entry_date.isoformat(),
        "entryAtUtc": _dt(row.entry_at_utc),
        "bpSystolic": row.bp_systolic,
        "bpDiastolic": row.bp_diastolic,
        "subjectiveScore": row.subjective_score,
        "rpe": row.rpe,
        "feel": row.feel,
        "supplements": row.supplements_json,
        "food": row.food_json,
        "notes": row.notes,
    }


def _planned_workout_packet(row: PlannedWorkout) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "planBlockId": str(row.plan_block_id) if row.plan_block_id else None,
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


def _weather_packet(row: WeatherDaily | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "calendarDate": row.calendar_date.isoformat(),
        "source": row.source,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "tempHighC": row.temp_high_c,
        "tempLowC": row.temp_low_c,
        "overnightLowC": row.overnight_low_c,
        "overnightWindMaxMph": row.overnight_wind_max_mph,
        "overnightWindGustMph": row.overnight_wind_gust_mph,
        "precipitationMm": row.precipitation_mm,
        "sunriseUtc": _dt(row.sunrise_utc),
        "sunsetUtc": _dt(row.sunset_utc),
    }


def _age_adjusted_sleep_score(
    sleep: Sleep | None,
    knowledge_base: Mapping[str, Any],
) -> int | None:
    if sleep is None:
        return None
    if sleep.age_adjusted_score is not None:
        return sleep.age_adjusted_score
    if sleep.score is None:
        return None
    age_adjustment = knowledge_base.get("age_adjustment", {})
    delta = 4
    if isinstance(age_adjustment, dict):
        raw_delta = age_adjustment.get("sleepScoreDelta")
        if isinstance(raw_delta, int | float):
            delta = int(raw_delta)
    return min(100, sleep.score + delta)


def _metrics_vs_baselines(
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    baselines: Sequence[MetricBaseline],
    age_adjusted_sleep_score: int | None,
) -> list[dict[str, Any]]:
    current_values = {
        "sleep_score": sleep.score if sleep else None,
        "age_adjusted_sleep_score": age_adjusted_sleep_score,
        "resting_heart_rate_bpm": _first_not_none(
            daily_metric.resting_heart_rate_bpm if daily_metric else None,
            sleep.resting_heart_rate_bpm if sleep else None,
        ),
        "body_battery_charge": daily_metric.body_battery_charged if daily_metric else None,
        "average_spo2_pct": sleep.average_spo2_pct if sleep else None,
        "average_respiration": sleep.average_respiration if sleep else None,
        "hrv_7_day_avg_ms": daily_metric.hrv_weekly_avg_ms if daily_metric else None,
    }
    rows: list[dict[str, Any]] = []
    for baseline in baselines:
        current = current_values.get(baseline.metric_key)
        center = _first_not_none(baseline.median_value, baseline.mean_value)
        delta = (
            None
            if current is None or center is None
            else round(float(current) - float(center), 2)
        )
        rows.append(
            {
                "metricKey": baseline.metric_key,
                "label": baseline.metric_label,
                "currentValue": current,
                "baselineMedian": baseline.median_value,
                "baselineMean": baseline.mean_value,
                "deltaVsBaseline": delta,
                "lowerQuartile": baseline.lower_quartile_value,
                "upperQuartile": baseline.upper_quartile_value,
                "sampleCount": baseline.sample_count,
                "excludedSampleCount": baseline.excluded_sample_count,
                "reliabilityStartDate": (
                    baseline.reliability_start_date.isoformat()
                    if baseline.reliability_start_date
                    else None
                ),
            }
        )
    return rows


def _thermal_review(
    temperature_rows: Sequence[TemperatureReading],
    weather: WeatherDaily | None,
    knowledge_base: Mapping[str, Any],
) -> dict[str, Any]:
    sleep_protocol = knowledge_base.get("sleep_protocol", {})
    threshold_low = 19.5
    threshold_high = 20.0
    target_precool = 17.0
    if isinstance(sleep_protocol, dict):
        threshold = sleep_protocol.get("thermalDisruptionThresholdC")
        if isinstance(threshold, dict):
            low = threshold.get("low")
            high = threshold.get("high")
            if isinstance(low, int | float):
                threshold_low = float(low)
            if isinstance(high, int | float):
                threshold_high = float(high)
        precool = sleep_protocol.get("preCoolTemperatureC")
        if isinstance(precool, int | float):
            target_precool = float(precool)

    values = [row.temperature_c for row in temperature_rows]
    peak = max(values) if values else None
    low = min(values) if values else None
    last = values[-1] if values else None
    flags: list[str] = []
    if peak is not None and peak >= threshold_high:
        flags.append("thermal_disruption_likely")
    elif peak is not None and peak >= threshold_low:
        flags.append("thermal_disruption_watch")
    if low is not None and low > target_precool + 1.0:
        flags.append("precool_target_missed")
    if weather and weather.overnight_wind_gust_mph and weather.overnight_wind_gust_mph >= 30:
        flags.append("wind_disruption_watch")

    return {
        "sampleCount": len(values),
        "indoorPeakC": peak,
        "indoorLowC": low,
        "indoorLastC": last,
        "targetPreCoolC": target_precool,
        "disruptionThresholdC": {"low": threshold_low, "high": threshold_high},
        "overnightWeatherLowC": weather.overnight_low_c if weather else None,
        "overnightWindMaxMph": weather.overnight_wind_max_mph if weather else None,
        "overnightWindGustMph": weather.overnight_wind_gust_mph if weather else None,
        "flags": flags,
    }


def _morning_verdict(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    age_adjusted_sleep_score: int | None,
    manual_entries: Sequence[ManualEntry],
    planned_workouts: Sequence[PlannedWorkout],
) -> dict[str, Any]:
    subjective_score = _latest_subjective_score(manual_entries)
    hrv_status = _lower(daily_metric.hrv_status if daily_metric else None) or _lower(
        sleep.hrv_status if sleep else None
    )
    hrv_low = _hrv_below_baseline(daily_metric)
    readiness_level = _lower(daily_metric.readiness_level if daily_metric else None)
    has_vo2 = any("vo2" in workout.workout_type.lower() for workout in planned_workouts)
    recovery_signals_good = (
        (age_adjusted_sleep_score is not None and age_adjusted_sleep_score >= 74)
        and not hrv_low
        and (hrv_status in {None, "balanced", "stable", "optimal", "normal"})
        and (subjective_score is None or subjective_score >= 5)
    )

    reasons: list[str] = []
    readiness_interpretation = None
    if readiness_level == "low":
        if recovery_signals_good and _load_signal_present(daily_metric):
            readiness_interpretation = "load_driven"
            reasons.append(
                "Garmin readiness is Low but recovery signals justify a load-driven read."
            )
        else:
            reasons.append(
                "Garmin readiness is Low without enough recovery evidence to downplay it."
            )

    if age_adjusted_sleep_score is not None and age_adjusted_sleep_score < 60:
        status = "Red"
        reasons.append("Age-adjusted sleep is below 60.")
    elif hrv_low and hrv_status in {"unbalanced", "low"}:
        status = "Red"
        reasons.append("HRV is below baseline and marked low/unbalanced.")
    elif readiness_level == "low" and readiness_interpretation != "load_driven":
        status = "Amber"
    elif age_adjusted_sleep_score is not None and age_adjusted_sleep_score < 74:
        status = "Amber"
        reasons.append("Age-adjusted sleep is below the 74+ green target.")
    elif hrv_status in {"unbalanced", "low", "poor"} or hrv_low:
        status = "Amber"
        reasons.append("HRV is not cleanly in range.")
    elif subjective_score is not None and subjective_score < 5:
        status = "Amber"
        reasons.append("Subjective score is below 5.")
    else:
        status = "Green"
        reasons.append("Sleep, HRV, and subjective signals clear the green rule.")

    plan_adjustments = _plan_adjustments(status, planned_workouts)
    if status == "Red" and has_vo2:
        plan_adjustments.append("Replace VO2 with rest, mobility, or a very easy spin.")

    return {
        "status": status,
        "reasons": reasons,
        "readinessLevel": daily_metric.readiness_level if daily_metric else None,
        "readinessInterpretation": readiness_interpretation,
        "ageAdjustedSleepScore": age_adjusted_sleep_score,
        "subjectiveScore": subjective_score,
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": hrv_low,
        "hasVo2WorkoutToday": has_vo2,
        "planAdjustments": plan_adjustments,
        "safetyRulesApplied": ["red_never_vo2"] if status == "Red" else [],
    }


def _plan_adjustments(status: str, planned_workouts: Sequence[PlannedWorkout]) -> list[str]:
    if not planned_workouts:
        return ["No active planned workout found for today; keep advice conservative."]
    if status == "Green":
        return ["Proceed with the planned workout if warm-up confirms readiness."]
    if status == "Amber":
        return ["Cut duration 20-30%, drop intensity by a zone, and remove HIT/VO2 work."]
    return ["Substitute recovery, mobility, or rest."]


def _latest_subjective_score(manual_entries: Sequence[ManualEntry]) -> int | None:
    for entry in manual_entries:
        if entry.subjective_score is not None:
            return entry.subjective_score
    return None


def _hrv_below_baseline(daily_metric: DailyMetric | None) -> bool:
    if daily_metric is None:
        return False
    value = daily_metric.hrv_weekly_avg_ms or daily_metric.hrv_last_night_avg_ms
    low = daily_metric.hrv_baseline_low_ms
    return value is not None and low is not None and value < low


def _load_signal_present(daily_metric: DailyMetric | None) -> bool:
    if daily_metric is None:
        return False
    if daily_metric.acute_load is not None and daily_metric.acute_load > 0:
        return True
    return daily_metric.recovery_time_min is not None and daily_metric.recovery_time_min > 0


def _overnight_window_utc(subject_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    local_start = datetime.combine(subject_date - timedelta(days=1), time(18, 0), tzinfo=timezone)
    local_end = datetime.combine(subject_date, time(8, 0), tzinfo=timezone)
    return (
        local_start.astimezone(UTC).replace(tzinfo=None),
        local_end.astimezone(UTC).replace(tzinfo=None),
    )


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _minutes(seconds: int | None) -> int | None:
    return round(seconds / 60) if seconds is not None else None


def _first_not_none[T](*values: T | None) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


def _lower(value: str | None) -> str | None:
    return value.lower() if value else None
