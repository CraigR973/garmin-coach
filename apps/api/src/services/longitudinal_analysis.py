"""Monthly whole-history analyst with durable structured findings (Batch 220).

The deterministic layer assembles compact per-night evidence and descriptive
temperature bands.  Claude's job is to reason over those measurements and name
confounds; it does not get a pre-computed coefficient or causal conclusion.
The provider response is JSON-schema constrained, policy checked, then routed
as an audited observation on the existing temperature/early-waking experiment.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DAILY_METRIC_PHASE_SETTLED,
    Activity,
    Analysis,
    DailyMetric,
    Experiment,
    ManualEntry,
    PlanBlock,
    Sleep,
    WeatherDaily,
)
from src.models.notification import PushSubscription
from src.models.profile import Profile
from src.services.anthropic_batch import (
    AnthropicBatchError,
    AnthropicMessageBatchClient,
    MessageBatchClient,
)
from src.services.anthropic_text import AnthropicApiError, classify_anthropic_error
from src.services.bulk_history_reads import without_sleep_raw_payload
from src.services.experiment_tracker import ExperimentTrackerService
from src.services.generation_requests import (
    claim_generation_request,
    longitudinal_generation_identity,
    stamp_generation_identity,
)
from src.services.insights import BedroomDriverValues, bedroom_driver_values_by_date
from src.services.workload_budget import workload_slot

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

ANALYSIS_TYPE = "longitudinal_findings"
PROMPT_VERSION = "longitudinal-analysis-v1-2026-08-24"
TARGET_EXPERIMENT_SLUG = "early_waking_0400"

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

MIN_BEDROOM_NIGHTS = 21
MIN_STRUCTURED_SETUP_NIGHTS = 21
MIN_TEMPERATURE_BANDS = 3
MIN_NIGHTS_PER_TEMPERATURE_BAND = 5
TEMPERATURE_BAND_WIDTH_C = 1.0
MAX_INPUT_TOKENS = 900_000

SYSTEM_PROMPT = """You are the longitudinal analyst for one private fitness coach.
Reason from the supplied per-night evidence; do not diagnose disease and do not
invent measurements, setup changes, causal mechanisms, or target temperatures.

The `nights` data is columnar: each row has the same positional order as
`columns`. `temperatureBands` contains deterministic descriptive summaries, not
causal conclusions. Copy those bands exactly into the temperature finding; do
not recalculate or smooth them. Historical free-text notes are evidence of what
the user said, but only `setupRecorded=true` is structured setup coverage.

You MUST return at least one `temperature_sleep` finding. Distinguish association
from causation, name competing explanations, and use `inconclusive` whenever
coverage cannot distinguish them. If warm-weather constraints make a putative
target unreachable, say so in `reachability` and propose an experiment that
measures achievable room temperature rather than prescribing an impossible
target. Keep observations concise and factual enough to live in an experiment
record. The response is schema-constrained JSON; emit no prose outside it."""


class LongitudinalAnalysisError(RuntimeError):
    pass


class BillingAlertNotReady(LongitudinalAnalysisError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TerminalBatchRequestError(AnthropicApiError):
    """A provider-side individual request that has permanently ended in error."""


class FindingBand(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    lower_c: float = Field(alias="lowerC")
    upper_c: float = Field(alias="upperC")
    nights: int = Field(ge=1)
    rem_mean_min: float | None = Field(alias="remMeanMin")
    awake_mean_min: float | None = Field(alias="awakeMeanMin")
    sleep_score_mean: float | None = Field(alias="sleepScoreMean")


class ReachabilityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["reachable", "partly_reachable", "unreachable", "unknown"]
    explanation: str = Field(min_length=5, max_length=600)


class ProposedExperimentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = Field(min_length=5, max_length=160)
    hypothesis: str = Field(min_length=10, max_length=600)
    minimum_nights: int = Field(alias="minimumNights", ge=1, le=180)
    setup_to_hold_constant: list[str] = Field(
        alias="setupToHoldConstant", min_length=1, max_length=8
    )
    measurements: list[str] = Field(min_length=1, max_length=10)
    reachability_plan: str = Field(alias="reachabilityPlan", min_length=5, max_length=600)


class DataQualityFlagFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "insufficient_setup_coverage",
        "insufficient_temperature_coverage",
        "measurement_uncertainty",
        "confounded_history",
        "other",
    ]
    detail: str = Field(min_length=5, max_length=600)


class LongitudinalFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    finding_key: str = Field(alias="findingKey", min_length=3, max_length=64)
    topic: Literal["temperature_sleep", "data_quality", "training_recovery", "other"]
    observation: str = Field(min_length=10, max_length=1000)
    confidence: Literal["low", "moderate", "high"]
    evidence_status: Literal["supported", "refuted", "inconclusive"] = Field(alias="evidenceStatus")
    evidence_summary: list[str] = Field(alias="evidenceSummary", min_length=1, max_length=8)
    temperature_bands: list[FindingBand] = Field(alias="temperatureBands", max_length=30)
    confounds: list[str] = Field(max_length=12)
    reachability: ReachabilityFinding
    proposed_experiment: ProposedExperimentFinding | None = Field(alias="proposedExperiment")
    data_quality_flag: DataQualityFlagFinding | None = Field(alias="dataQualityFlag")


class LongitudinalFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[LongitudinalFinding] = Field(min_length=1, max_length=5)


@dataclass(frozen=True, slots=True)
class NightEvidence:
    calendar_date: date
    sleep_score: int | None = None
    age_adjusted_sleep_score: int | None = None
    sleep_duration_min: float | None = None
    deep_sleep_min: float | None = None
    light_sleep_min: float | None = None
    rem_sleep_min: float | None = None
    awake_sleep_min: float | None = None
    overnight_hrv_ms: int | None = None
    resting_heart_rate_bpm: int | None = None
    sleep_stress_avg: float | None = None
    restless_moments: int | None = None
    body_battery_change: int | None = None
    wake_readiness_score: int | None = None
    wake_hrv_ms: int | None = None
    wake_body_battery_charged: int | None = None
    prior_day_stress_avg: float | None = None
    prior_day_body_battery_drained: int | None = None
    prior_day_training_load: float | None = None
    prior_day_activity_duration_min: float | None = None
    prior_day_activity_types: tuple[str, ...] = ()
    prior_plan_block_type: str | None = None
    bedroom_mean_temp_c: float | None = None
    bedroom_min_temp_c: float | None = None
    bedroom_max_temp_c: float | None = None
    bedroom_warning_min: float | None = None
    bedroom_critical_min: float | None = None
    bedroom_fan_min: float | None = None
    bedroom_peak_fan_speed: float | None = None
    outdoor_overnight_low_c: float | None = None
    overnight_wind_max_mph: float | None = None
    overnight_wind_gust_mph: float | None = None
    overnight_wind_direction_deg: float | None = None
    overnight_humidity_mean_pct: float | None = None
    setup_recorded: bool = False
    bedding_weight: str | None = None
    window_count: int | None = None
    window_aperture_cm: float | None = None
    blind_position: str | None = None
    pre_cool_start_local: str | None = None
    notes: tuple[str, ...] = ()


COLUMNS: tuple[str, ...] = (
    "date",
    "sleepScore",
    "ageAdjustedSleepScore",
    "sleepDurationMin",
    "deepSleepMin",
    "lightSleepMin",
    "remSleepMin",
    "awakeSleepMin",
    "overnightHrvMs",
    "restingHeartRateBpm",
    "sleepStressAvg",
    "restlessMoments",
    "bodyBatteryChange",
    "wakeReadinessScore",
    "wakeHrvMs",
    "wakeBodyBatteryCharged",
    "priorDayStressAvg",
    "priorDayBodyBatteryDrained",
    "priorDayTrainingLoad",
    "priorDayActivityDurationMin",
    "priorDayActivityTypes",
    "priorPlanBlockType",
    "bedroomMeanTempC",
    "bedroomMinTempC",
    "bedroomMaxTempC",
    "bedroomWarningMin",
    "bedroomCriticalMin",
    "bedroomFanMin",
    "bedroomPeakFanSpeed",
    "outdoorOvernightLowC",
    "overnightWindMaxMph",
    "overnightWindGustMph",
    "overnightWindDirectionDeg",
    "overnightHumidityMeanPct",
    "setupRecorded",
    "beddingWeight",
    "windowCount",
    "windowApertureCm",
    "blindPosition",
    "preCoolStartLocal",
    "notes",
)


@dataclass(frozen=True, slots=True)
class AlertReadiness:
    ready: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SubmitResult:
    analysis: Analysis
    submitted: bool
    input_tokens: int | None
    packet_bytes: int | None


@dataclass(frozen=True, slots=True)
class CollectionResult:
    pending: int = 0
    completed: int = 0
    failed: int = 0
    findings_routed: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _minutes(seconds: int | float | None) -> float | None:
    return round(float(seconds) / 60.0, 1) if seconds is not None else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _manual_context(entries: list[ManualEntry]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return the wake-date setup plus all useful notes in entry order."""

    setup: dict[str, Any] = {}
    notes: list[str] = []
    for entry in entries:
        # Only the unlinked morning check-in owns the night's setup. Activity-
        # linked entries carry a default empty object and must not erase it. An
        # explicit empty morning object, however, is the supported clear action.
        if entry.planned_workout_id is None and entry.activity_id is None:
            setup = dict(entry.sleep_setup_json or {})
        if entry.notes and entry.notes.strip():
            notes.append(entry.notes.strip())
    return setup, tuple(notes)


def _night_row(night: NightEvidence) -> list[Any]:
    return [
        night.calendar_date.isoformat(),
        night.sleep_score,
        night.age_adjusted_sleep_score,
        night.sleep_duration_min,
        night.deep_sleep_min,
        night.light_sleep_min,
        night.rem_sleep_min,
        night.awake_sleep_min,
        night.overnight_hrv_ms,
        night.resting_heart_rate_bpm,
        night.sleep_stress_avg,
        night.restless_moments,
        night.body_battery_change,
        night.wake_readiness_score,
        night.wake_hrv_ms,
        night.wake_body_battery_charged,
        night.prior_day_stress_avg,
        night.prior_day_body_battery_drained,
        night.prior_day_training_load,
        night.prior_day_activity_duration_min,
        list(night.prior_day_activity_types),
        night.prior_plan_block_type,
        night.bedroom_mean_temp_c,
        night.bedroom_min_temp_c,
        night.bedroom_max_temp_c,
        night.bedroom_warning_min,
        night.bedroom_critical_min,
        night.bedroom_fan_min,
        night.bedroom_peak_fan_speed,
        night.outdoor_overnight_low_c,
        night.overnight_wind_max_mph,
        night.overnight_wind_gust_mph,
        night.overnight_wind_direction_deg,
        night.overnight_humidity_mean_pct,
        night.setup_recorded,
        night.bedding_weight,
        night.window_count,
        night.window_aperture_cm,
        night.blind_position,
        night.pre_cool_start_local,
        list(night.notes),
    ]


def temperature_bands(
    nights: list[NightEvidence], *, width_c: float = TEMPERATURE_BAND_WIDTH_C
) -> list[dict[str, Any]]:
    """Fixed-width descriptive bands; deliberately no regression or optimum."""

    grouped: dict[float, list[NightEvidence]] = defaultdict(list)
    for night in nights:
        if night.bedroom_mean_temp_c is None:
            continue
        lower = math.floor(night.bedroom_mean_temp_c / width_c) * width_c
        grouped[round(lower, 4)].append(night)

    bands: list[dict[str, Any]] = []
    for lower, rows in sorted(grouped.items()):
        rem = [row.rem_sleep_min for row in rows if row.rem_sleep_min is not None]
        awake = [row.awake_sleep_min for row in rows if row.awake_sleep_min is not None]
        scores = [float(row.sleep_score) for row in rows if row.sleep_score is not None]
        bands.append(
            {
                "lowerC": round(lower, 1),
                "upperC": round(lower + width_c, 1),
                "nights": len(rows),
                "remMeanMin": _mean(rem),
                "awakeMeanMin": _mean(awake),
                "sleepScoreMean": _mean(scores),
            }
        )
    return bands


_REACHABILITY_PHRASES = (
    "nothing else i can do",
    "impossible to get",
    "max possible",
    "maximum possible",
    "as cool as possible",
    "cooled as much as possible",
)


def _reachability_constraints(nights: list[NightEvidence]) -> list[dict[str, str]]:
    constraints: list[dict[str, str]] = []
    for night in nights:
        for note in night.notes:
            folded = note.casefold()
            if any(phrase in folded for phrase in _REACHABILITY_PHRASES):
                constraints.append({"date": night.calendar_date.isoformat(), "note": note})
    return constraints


def build_longitudinal_packet(nights: list[NightEvidence], *, as_of_date: date) -> dict[str, Any]:
    """Pure, clock-free, deterministic packet builder."""

    ordered = sorted(
        (night for night in nights if night.calendar_date <= as_of_date),
        key=lambda night: night.calendar_date,
    )
    bands = temperature_bands(ordered)
    bedroom_nights = sum(night.bedroom_mean_temp_c is not None for night in ordered)
    setup_nights = sum(night.setup_recorded for night in ordered)
    note_nights = sum(bool(night.notes) for night in ordered)
    weather_nights = sum(night.outdoor_overnight_low_c is not None for night in ordered)
    qualified_bands = sum(int(band["nights"]) >= MIN_NIGHTS_PER_TEMPERATURE_BAND for band in bands)
    return {
        "packetType": "longitudinal_evidence",
        "packetVersion": 1,
        "asOfDate": as_of_date.isoformat(),
        "coverage": {
            "sleepNights": len(ordered),
            "bedroomTemperatureNights": bedroom_nights,
            "weatherNights": weather_nights,
            "manualNoteNights": note_nights,
            "structuredSetupNights": setup_nights,
            "minimumBedroomNights": MIN_BEDROOM_NIGHTS,
            "minimumStructuredSetupNights": MIN_STRUCTURED_SETUP_NIGHTS,
            "minimumTemperatureBands": MIN_TEMPERATURE_BANDS,
            "minimumNightsPerTemperatureBand": MIN_NIGHTS_PER_TEMPERATURE_BAND,
            "qualifiedTemperatureBands": qualified_bands,
            "causalTemperatureClaimEligible": (
                bedroom_nights >= MIN_BEDROOM_NIGHTS
                and setup_nights >= MIN_STRUCTURED_SETUP_NIGHTS
                and qualified_bands >= MIN_TEMPERATURE_BANDS
            ),
        },
        "columns": list(COLUMNS),
        "nights": [_night_row(night) for night in ordered],
        "temperatureBands": bands,
        "reachabilityConstraints": _reachability_constraints(ordered),
        "evidenceRules": {
            "temperatureBandsAreDescriptive": True,
            "historicalNotesAreNotStructuredSetup": True,
            "missingValuesAreNull": True,
            "sleepDateIsWakeDate": True,
            "priorDayFieldsDescribeTheDayBeforeSleep": True,
        },
    }


def build_message_params(
    packet: dict[str, Any], *, model_name: str, max_tokens: int
) -> tuple[dict[str, Any], str]:
    prompt = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    params = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": anthropic_output_schema(),
            }
        },
    }
    return params, prompt


_ANTHROPIC_UNSUPPORTED_SCHEMA_CONSTRAINTS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "pattern",
    }
)


def anthropic_output_schema() -> dict[str, Any]:
    """Transform Pydantic JSON Schema for Anthropic's supported subset.

    Anthropic's SDK helpers remove these constraints before sending and then
    validate the response against the original model.  This repo deliberately
    keeps its thin HTTP boundary, so perform the same split explicitly: the
    provider gets only grammar-supported structure; ``model_validate_json``
    below retains every length/range constraint locally.
    """

    def transform(value: Any) -> Any:
        if isinstance(value, list):
            return [transform(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: transform(item)
            for key, item in value.items()
            if key not in _ANTHROPIC_UNSUPPORTED_SCHEMA_CONSTRAINTS
        }

    schema = transform(LongitudinalFindings.model_json_schema(by_alias=True))
    if not isinstance(schema, dict):  # pragma: no cover - Pydantic always returns an object
        raise LongitudinalAnalysisError("Longitudinal output schema was not an object.")
    return schema


def _deterministic_experiment() -> ProposedExperimentFinding:
    return ProposedExperimentFinding(
        title="Bedroom temperature and sleep architecture",
        hypothesis=(
            "Holding the recorded sleep setup stable will show whether both colder "
            "and warmer bedroom bands coincide with lower REM or more awake time."
        ),
        minimumNights=MIN_STRUCTURED_SETUP_NIGHTS,
        setupToHoldConstant=[
            "bedding weight",
            "window count and aperture",
            "blind position",
            "pre-cool start time",
        ],
        measurements=[
            "bedroom mean/min/max temperature",
            "REM minutes",
            "awake minutes",
            "training load",
            "alcohol/late-food/stress notes",
        ],
        reachabilityPlan=(
            "Record the coolest achievable room temperature on warm nights and compare "
            "achievable bands; do not prescribe a target that the room cannot reach."
        ),
    )


def enforce_findings_policy(
    packet: dict[str, Any], findings: LongitudinalFindings
) -> LongitudinalFindings:
    """Pin model output to measured bands and the structured-coverage floor."""

    temperature = [finding for finding in findings.findings if finding.topic == "temperature_sleep"]
    if not temperature:
        raise LongitudinalAnalysisError("Batch result omitted the required temperature finding.")

    coverage = packet.get("coverage")
    if not isinstance(coverage, dict):
        raise LongitudinalAnalysisError("Longitudinal packet coverage is missing.")
    eligible = coverage.get("causalTemperatureClaimEligible") is True
    setup_nights = int(coverage.get("structuredSetupNights") or 0)
    bedroom_nights = int(coverage.get("bedroomTemperatureNights") or 0)
    qualified_bands = int(coverage.get("qualifiedTemperatureBands") or 0)
    deterministic_bands = [
        FindingBand.model_validate(item) for item in packet.get("temperatureBands", [])
    ]
    constraints = packet.get("reachabilityConstraints")
    has_constraint = isinstance(constraints, list) and bool(constraints)

    guarded: list[LongitudinalFinding] = []
    for original in findings.findings:
        finding = original.model_copy(deep=True)
        if finding.topic != "temperature_sleep":
            guarded.append(finding)
            continue
        finding.temperature_bands = deterministic_bands
        if not eligible:
            finding.evidence_status = "inconclusive"
            finding.confidence = "low"
            coverage_confound = (
                f"Only {setup_nights} nights have structured sleep setup and "
                f"{bedroom_nights} have bedroom temperature; the policy floor is "
                f"{MIN_STRUCTURED_SETUP_NIGHTS} structured and {MIN_BEDROOM_NIGHTS} "
                f"temperature nights, with {MIN_TEMPERATURE_BANDS} bands holding at "
                f"least {MIN_NIGHTS_PER_TEMPERATURE_BAND} nights each (currently "
                f"{qualified_bands})."
            )
            if coverage_confound not in finding.confounds:
                finding.confounds.append(coverage_confound)
            finding.data_quality_flag = DataQualityFlagFinding(
                kind=(
                    "insufficient_setup_coverage"
                    if setup_nights < MIN_STRUCTURED_SETUP_NIGHTS
                    else "insufficient_temperature_coverage"
                ),
                detail=coverage_confound,
            )
            if finding.proposed_experiment is None:
                finding.proposed_experiment = _deterministic_experiment()
        if has_constraint and finding.reachability.status == "reachable":
            finding.reachability = ReachabilityFinding(
                status="partly_reachable",
                explanation=(
                    "The user's notes explicitly say maximum cooling was already used on "
                    "hot nights, so a lower band is not always reachable."
                ),
            )
        guarded.append(finding)
    return LongitudinalFindings(findings=guarded)


def parse_batch_result(
    rows: list[dict[str, Any]], *, custom_id: str
) -> tuple[LongitudinalFindings, dict[str, Any]]:
    row = next((item for item in rows if item.get("custom_id") == custom_id), None)
    if row is None:
        raise LongitudinalAnalysisError("Batch results omitted the submitted custom_id.")
    result = row.get("result")
    if not isinstance(result, dict):
        raise LongitudinalAnalysisError("Batch result was not an object.")
    result_type = result.get("type")
    if result_type == "errored":
        error_response = result.get("error")
        error_object = error_response.get("error") if isinstance(error_response, dict) else None
        error_type = error_object.get("type") if isinstance(error_object, dict) else None
        message = error_object.get("message") if isinstance(error_object, dict) else None
        classified = classify_anthropic_error(
            400,
            error_type=error_type if isinstance(error_type, str) else None,
            error_message=message if isinstance(message, str) else None,
        )
        raise TerminalBatchRequestError(
            message if isinstance(message, str) else "Anthropic batch request failed.",
            reason=classified,
            status_code=400,
            anthropic_type=error_type if isinstance(error_type, str) else None,
        )
    if result_type != "succeeded":
        raise LongitudinalAnalysisError(f"Batch request ended as {result_type!r}.")
    message = result.get("message")
    if not isinstance(message, dict):
        raise LongitudinalAnalysisError("Successful batch result omitted its message.")
    if message.get("stop_reason") == "max_tokens":
        raise LongitudinalAnalysisError("Longitudinal finding hit max_tokens.")
    text_parts: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
    output = "".join(text_parts).strip()
    if not output:
        raise LongitudinalAnalysisError("Batch message did not contain structured output.")
    try:
        parsed = LongitudinalFindings.model_validate_json(output)
    except ValidationError as exc:
        raise LongitudinalAnalysisError("Batch findings failed local schema validation.") from exc
    return parsed, row


async def billing_alert_readiness(
    session: AsyncSession, *, subject_profile_id: uuid.UUID | None = None
) -> AlertReadiness:
    raw_id = settings.admin_alert_user_id.strip()
    if not raw_id:
        return AlertReadiness(False, "admin_alert_user_id_unset")
    try:
        profile_id = uuid.UUID(raw_id)
    except ValueError:
        return AlertReadiness(False, "admin_alert_user_id_invalid")
    if subject_profile_id is not None and profile_id == subject_profile_id:
        return AlertReadiness(False, "admin_alert_points_to_subject")
    profile = await session.get(Profile, profile_id)
    if profile is None or not profile.is_active or profile.deleted_at is not None:
        return AlertReadiness(False, "admin_alert_profile_inactive")
    subscription = await session.scalar(
        select(PushSubscription.id).where(
            PushSubscription.user_id == profile_id,
            PushSubscription.is_active.is_(True),
        )
    )
    if subscription is None:
        return AlertReadiness(False, "admin_alert_subscription_missing")
    return AlertReadiness(True)


class LongitudinalAnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assemble_nights(self, player: Profile, *, as_of_date: date) -> list[NightEvidence]:
        sleeps = list(
            (
                await self.session.execute(
                    select(Sleep)
                    .options(without_sleep_raw_payload())
                    .where(
                        Sleep.user_id == player.id,
                        Sleep.calendar_date <= as_of_date,
                    )
                    .order_by(Sleep.calendar_date)
                )
            )
            .scalars()
            .all()
        )
        if not sleeps:
            return []
        start = sleeps[0].calendar_date
        player_zone = ZoneInfo(player.timezone or "UTC")
        activity_start_utc = (
            datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=player_zone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        activity_end_utc = (
            datetime.combine(
                as_of_date + timedelta(days=1),
                datetime.min.time(),
                tzinfo=player_zone,
            )
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        metrics = list(
            (
                await self.session.execute(
                    select(DailyMetric).where(
                        DailyMetric.user_id == player.id,
                        DailyMetric.calendar_date >= start - timedelta(days=1),
                        DailyMetric.calendar_date <= as_of_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        weather = list(
            (
                await self.session.execute(
                    select(WeatherDaily).where(
                        WeatherDaily.user_id == player.id,
                        WeatherDaily.calendar_date >= start,
                        WeatherDaily.calendar_date <= as_of_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        manual = list(
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == player.id,
                        ManualEntry.entry_date >= start,
                        ManualEntry.entry_date <= as_of_date,
                    )
                    .order_by(ManualEntry.entry_date, ManualEntry.entry_at_utc)
                )
            )
            .scalars()
            .all()
        )
        activities = list(
            (
                await self.session.execute(
                    select(Activity).where(
                        Activity.user_id == player.id,
                        Activity.start_utc >= activity_start_utc,
                        Activity.start_utc < activity_end_utc,
                    )
                )
            )
            .scalars()
            .all()
        )
        plan_blocks = list(
            (
                await self.session.execute(
                    select(PlanBlock)
                    .where(
                        PlanBlock.user_id == player.id,
                        PlanBlock.end_date >= start - timedelta(days=1),
                        PlanBlock.start_date <= as_of_date,
                    )
                    .order_by(PlanBlock.version, PlanBlock.sequence_index)
                )
            )
            .scalars()
            .all()
        )
        bedroom = await bedroom_driver_values_by_date(
            self.session, player, start=start, end=as_of_date
        )

        metric_by_key = {(row.calendar_date, row.phase): row for row in metrics}
        weather_by_date = {row.calendar_date: row for row in weather}
        manual_by_date: dict[date, list[ManualEntry]] = defaultdict(list)
        for manual_row in manual:
            manual_by_date[manual_row.entry_date].append(manual_row)
        activity_by_date: dict[date, list[Activity]] = defaultdict(list)
        for activity_row in activities:
            local_date = activity_row.start_utc.replace(tzinfo=UTC).astimezone(player_zone).date()
            activity_by_date[local_date].append(activity_row)
        block_type_by_date: dict[date, str] = {}
        for block in plan_blocks:
            cursor = max(block.start_date, start - timedelta(days=1))
            through = min(block.end_date, as_of_date)
            while cursor <= through:
                if block.block_type:
                    block_type_by_date[cursor] = block.block_type
                cursor += timedelta(days=1)

        evidence: list[NightEvidence] = []
        for sleep in sleeps:
            wake = metric_by_key.get((sleep.calendar_date, DAILY_METRIC_PHASE_MORNING))
            prior_date = sleep.calendar_date - timedelta(days=1)
            prior = metric_by_key.get((prior_date, DAILY_METRIC_PHASE_SETTLED))
            weather_row = weather_by_date.get(sleep.calendar_date)
            bedroom_row = bedroom.get(sleep.calendar_date)
            entries = manual_by_date.get(sleep.calendar_date, [])
            setup, notes = _manual_context(entries)
            prior_activities = activity_by_date.get(prior_date, [])
            evidence.append(
                NightEvidence(
                    calendar_date=sleep.calendar_date,
                    sleep_score=sleep.score,
                    age_adjusted_sleep_score=sleep.age_adjusted_score,
                    sleep_duration_min=_minutes(sleep.duration_sec),
                    deep_sleep_min=_minutes(sleep.deep_sleep_sec),
                    light_sleep_min=_minutes(sleep.light_sleep_sec),
                    rem_sleep_min=_minutes(sleep.rem_sleep_sec),
                    awake_sleep_min=_minutes(sleep.awake_sleep_sec),
                    overnight_hrv_ms=sleep.avg_overnight_hrv_ms,
                    resting_heart_rate_bpm=sleep.resting_heart_rate_bpm,
                    sleep_stress_avg=sleep.avg_sleep_stress,
                    restless_moments=sleep.restless_moments_count,
                    body_battery_change=sleep.body_battery_change,
                    wake_readiness_score=wake.readiness_score if wake else None,
                    wake_hrv_ms=wake.hrv_last_night_avg_ms if wake else None,
                    wake_body_battery_charged=wake.body_battery_charged if wake else None,
                    prior_day_stress_avg=prior.stress_avg if prior else None,
                    prior_day_body_battery_drained=(prior.body_battery_drained if prior else None),
                    prior_day_training_load=(
                        round(sum(float(row.training_load or 0) for row in prior_activities), 1)
                        if any(row.training_load is not None for row in prior_activities)
                        else None
                    ),
                    prior_day_activity_duration_min=(
                        round(
                            sum(float(row.duration_sec or 0) for row in prior_activities) / 60.0,
                            1,
                        )
                        if any(row.duration_sec is not None for row in prior_activities)
                        else None
                    ),
                    prior_day_activity_types=tuple(
                        sorted({row.activity_type for row in prior_activities})
                    ),
                    prior_plan_block_type=block_type_by_date.get(prior_date),
                    **_bedroom_fields(bedroom_row),
                    outdoor_overnight_low_c=(weather_row.overnight_low_c if weather_row else None),
                    overnight_wind_max_mph=(
                        weather_row.overnight_wind_max_mph if weather_row else None
                    ),
                    overnight_wind_gust_mph=(
                        weather_row.overnight_wind_gust_mph if weather_row else None
                    ),
                    overnight_wind_direction_deg=(
                        weather_row.overnight_wind_direction_deg if weather_row else None
                    ),
                    overnight_humidity_mean_pct=(
                        weather_row.overnight_relative_humidity_mean_pct if weather_row else None
                    ),
                    setup_recorded=bool(setup),
                    bedding_weight=_str_value(setup.get("beddingWeight")),
                    window_count=_int_value(setup.get("windowCount")),
                    window_aperture_cm=_float_value(setup.get("windowApertureCm")),
                    blind_position=_str_value(setup.get("blindPosition")),
                    pre_cool_start_local=_str_value(setup.get("preCoolStartLocal")),
                    notes=notes,
                )
            )
        return evidence

    async def assemble_packet(self, player: Profile, *, as_of_date: date) -> dict[str, Any]:
        return build_longitudinal_packet(
            await self.assemble_nights(player, as_of_date=as_of_date),
            as_of_date=as_of_date,
        )

    async def submit_monthly(
        self,
        player: Profile,
        *,
        as_of_date: date,
        client: MessageBatchClient | None = None,
        commit: bool = True,
    ) -> SubmitResult:
        readiness = await billing_alert_readiness(self.session, subject_profile_id=player.id)
        if not readiness.ready:
            raise BillingAlertNotReady(readiness.reason or "admin_alert_not_ready")
        if not settings.anthropic_api_key and client is None:
            raise LongitudinalAnalysisError("ANTHROPIC_API_KEY is not configured.")

        period_key = as_of_date.strftime("%Y-%m")
        request_identity = longitudinal_generation_identity(
            user_id=player.id,
            period_key=period_key,
            prompt_version=PROMPT_VERSION,
        )
        async with claim_generation_request(
            self.session,
            user_id=player.id,
            request_identity=request_identity,
            generation_kind=ANALYSIS_TYPE,
            lease_scope=f"longitudinal:{player.id}:{period_key}",
        ) as claim:
            if claim.existing_analysis is not None:
                raw = claim.existing_analysis.raw_response
                metrics = raw.get("requestMetrics") if isinstance(raw, dict) else None
                return SubmitResult(
                    claim.existing_analysis,
                    False,
                    _dict_int(metrics, "inputTokens"),
                    _dict_int(metrics, "packetBytes"),
                )

            packet = await self.assemble_packet(player, as_of_date=as_of_date)
            stamp_generation_identity(
                packet,
                request_identity=request_identity,
                input_version=period_key,
            )
            params, prompt = build_message_params(
                packet,
                model_name=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
            )
            packet_bytes = len(prompt.encode("utf-8"))
            custom_id = f"longitudinal-{player.id.hex[:24]}-{as_of_date:%Y%m}"
            provider = client or AnthropicMessageBatchClient(api_key=settings.anthropic_api_key)
            async with workload_slot(workload="anthropic", user_id=player.id):
                input_tokens = await provider.count_tokens(params)
                if input_tokens > MAX_INPUT_TOKENS:
                    raise LongitudinalAnalysisError(
                        f"Longitudinal input is {input_tokens} tokens; limit is {MAX_INPUT_TOKENS}."
                    )
                batch = await provider.submit(custom_id=custom_id, params=params)
            batch_id = batch.get("id")
            if not isinstance(batch_id, str) or not batch_id:
                raise LongitudinalAnalysisError("Anthropic batch create omitted its id.")
            analysis = Analysis(
                user_id=player.id,
                activity_id=None,
                planned_workout_id=None,
                analysis_type=ANALYSIS_TYPE,
                subject_date=as_of_date,
                generated_at_utc=_utcnow(),
                prompt_version=PROMPT_VERSION,
                model_name=settings.anthropic_model,
                verdict=STATUS_PENDING,
                context_packet=packet,
                output_markdown="",
                raw_response={
                    "providerBatch": batch,
                    "customId": custom_id,
                    "requestMetrics": {
                        "packetBytes": packet_bytes,
                        "inputTokens": input_tokens,
                    },
                },
            )
            self.session.add(analysis)
            await self.session.flush()
            claim.mark_completed(analysis)
            if commit:
                await self.session.commit()
                await self.session.refresh(analysis)
            log.info(
                "longitudinal_batch_submitted",
                analysis_id=str(analysis.id),
                batch_id=batch_id,
                packet_bytes=packet_bytes,
                input_tokens=input_tokens,
            )
            return SubmitResult(analysis, True, input_tokens, packet_bytes)

    async def pending(self, player: Profile) -> list[Analysis]:
        return list(
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == player.id,
                        Analysis.analysis_type == ANALYSIS_TYPE,
                        Analysis.verdict == STATUS_PENDING,
                    )
                    .order_by(Analysis.generated_at_utc)
                )
            )
            .scalars()
            .all()
        )

    async def collect_pending(
        self,
        player: Profile,
        *,
        client: MessageBatchClient | None = None,
        commit: bool = True,
    ) -> CollectionResult:
        rows = await self.pending(player)
        if not rows:
            return CollectionResult()
        if not settings.anthropic_api_key and client is None:
            raise LongitudinalAnalysisError("ANTHROPIC_API_KEY is not configured.")
        provider = client or AnthropicMessageBatchClient(api_key=settings.anthropic_api_key)
        result = CollectionResult()
        for analysis in rows:
            try:
                # Routing an ended result can touch experiments and audit rows.
                # Keep those writes in a savepoint so a later validation/routing
                # failure cannot be committed alongside the failed marker.
                async with self.session.begin_nested():
                    outcome = await self._collect_one(player, analysis, provider)
            except Exception as exc:
                await self.session.refresh(analysis)
                raw = dict(analysis.raw_response or {})
                raw["collectionError"] = {
                    "reason": str(getattr(exc, "reason", "collection_failed")),
                    "atUtc": _utcnow().isoformat() + "Z",
                }
                analysis.raw_response = raw
                if isinstance(
                    exc,
                    (
                        LongitudinalAnalysisError,
                        TerminalBatchRequestError,
                        AnthropicBatchError,
                    ),
                ):
                    analysis.verdict = STATUS_FAILED
                    result = replace(result, failed=result.failed + 1)
                else:
                    result = replace(result, pending=result.pending + 1)
                if commit:
                    await self.session.commit()
                raise
            if outcome is None:
                result = replace(result, pending=result.pending + 1)
            else:
                result = replace(
                    result,
                    completed=result.completed + 1,
                    findings_routed=result.findings_routed + outcome,
                )
            if commit:
                await self.session.commit()
        return result

    async def _collect_one(
        self,
        player: Profile,
        analysis: Analysis,
        provider: MessageBatchClient,
    ) -> int | None:
        raw = dict(analysis.raw_response or {})
        batch = raw.get("providerBatch")
        batch_id = batch.get("id") if isinstance(batch, dict) else None
        custom_id = raw.get("customId")
        if not isinstance(batch_id, str) or not isinstance(custom_id, str):
            raise LongitudinalAnalysisError("Pending analysis has no provider batch identity.")
        current = await provider.retrieve(batch_id)
        raw["providerBatch"] = current
        raw["lastPolledAtUtc"] = _utcnow().isoformat() + "Z"
        if current.get("processing_status") != "ended":
            analysis.raw_response = raw
            return None
        provider_rows = await provider.results(batch_id)
        parsed, provider_result = parse_batch_result(provider_rows, custom_id=custom_id)
        guarded = enforce_findings_policy(analysis.context_packet, parsed)
        routed = await self._route_findings(player, analysis, guarded)
        message = provider_result.get("result")
        message = message.get("message") if isinstance(message, dict) else None
        model = message.get("model") if isinstance(message, dict) else None
        if isinstance(model, str):
            analysis.model_name = model
        raw["providerResult"] = provider_result
        raw["structuredFindings"] = guarded.model_dump(by_alias=True, mode="json")
        raw["routing"] = routed
        analysis.raw_response = raw
        analysis.verdict = STATUS_COMPLETED
        log.info(
            "longitudinal_batch_completed",
            analysis_id=str(analysis.id),
            batch_id=batch_id,
            findings=len(guarded.findings),
            routed=len(routed),
        )
        return len(routed)

    async def _route_findings(
        self,
        player: Profile,
        analysis: Analysis,
        findings: LongitudinalFindings,
    ) -> list[dict[str, str]]:
        tracker = ExperimentTrackerService(self.session)
        await tracker.seed_defaults(player, commit=False)
        experiments = await tracker.list_experiments(player, seed=False)
        experiment = next(
            (
                row
                for row in experiments
                if row.success_criteria_json.get("slug") == TARGET_EXPERIMENT_SLUG
            ),
            None,
        )
        if experiment is None:
            raise LongitudinalAnalysisError("Temperature experiment could not be seeded.")
        routed: list[dict[str, str]] = []
        for finding in findings.findings:
            if finding.topic != "temperature_sleep":
                continue
            if _already_routed(experiment, analysis.id, finding.finding_key):
                routed.append(
                    {
                        "experimentId": str(experiment.id),
                        "findingKey": finding.finding_key,
                    }
                )
                continue
            await tracker.add_observation(
                player,
                experiment.id,
                note=finding.observation,
                on_date=analysis.subject_date,
                metrics={
                    "source": ANALYSIS_TYPE,
                    "longitudinalAnalysisId": str(analysis.id),
                    **finding.model_dump(by_alias=True, mode="json"),
                },
                commit=False,
            )
            routed.append(
                {
                    "experimentId": str(experiment.id),
                    "findingKey": finding.finding_key,
                }
            )
        if not routed:
            raise LongitudinalAnalysisError("No temperature findings were routed.")
        return routed


def _bedroom_fields(row: BedroomDriverValues | None) -> dict[str, float | None]:
    return {
        "bedroom_mean_temp_c": row.mean_temp_c if row else None,
        "bedroom_min_temp_c": row.min_temp_c if row else None,
        "bedroom_max_temp_c": row.max_temp_c if row else None,
        "bedroom_warning_min": row.warning_minutes if row else None,
        "bedroom_critical_min": row.critical_minutes if row else None,
        "bedroom_fan_min": row.fan_ran_minutes if row else None,
        "bedroom_peak_fan_speed": row.peak_fan_speed if row else None,
    }


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _dict_int(value: Any, key: str) -> int | None:
    if not isinstance(value, dict):
        return None
    item = value.get(key)
    return item if isinstance(item, int) else None


def _already_routed(experiment: Experiment, analysis_id: uuid.UUID, finding_key: str) -> bool:
    observations = experiment.observations_json or {}
    entries = observations.get("entries") if isinstance(observations, dict) else None
    if not isinstance(entries, list):
        return False
    for entry in entries:
        metrics = entry.get("metrics") if isinstance(entry, dict) else None
        if not isinstance(metrics, dict):
            continue
        if (
            metrics.get("longitudinalAnalysisId") == str(analysis_id)
            and metrics.get("findingKey") == finding_key
        ):
            return True
    return False
