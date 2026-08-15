"""Deterministic chronic sleep-pattern suggestions and structural action signal.

Batch 59 turns the age-norm and personal-baseline reads into small, grounded
actions when a pattern repeats across weeks. Batch 171 keeps those advisory cards
unchanged and derives a deterministic deload-proposal signal from a protected
recovery-marker pattern. Batch 182 qualifies clustered Red mornings by cause and
limits that acute path to a week-preserving rearrangement. This module still does
not mutate the plan or set the daily verdict; the executable-coaching and
restructure services own action behind the existing approval rails.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    MetricBaseline,
    PlanBlock,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile
from src.services.age_norms import build_age_comparison
from src.services.insights import DriverCorrelation
from src.services.rem_interventions import RemRotation, select_rem_interventions
from src.services.sleep_scoring import age_adjusted_sleep_score_for_row

WINDOW_DAYS = 28
MIN_OBSERVED_NIGHTS = 21
MIN_METRIC_SAMPLES = 10
MIN_DRIVER_SAMPLES = 8
CHRONIC_ACTION_MISS_RATIO = 0.7
CHRONIC_ACTION_RED_WINDOW_DAYS = 7
CHRONIC_ACTION_RED_THRESHOLD = 2
CHRONIC_DELOAD_WINDOW_DAYS = 7
RECOVERY_DEBT_EXPLAINED_MIN = 24 * 60
ACUTE_RED_EXCLUSION_LIMIT = 1
ACUTE_RED_EXCLUSION_MAX_AGE_DAYS = 2

_PLANNED_RECOVERY_BLOCK_TYPES = frozenset({"recovery", "taper", "consolidation"})
_HEALTHY_HRV_STATES = frozenset({"balanced", "stable", "optimal", "normal"})

_ACUTE_EXOGENOUS_CHECK_IN_CAUSES = frozenset({"alcohol", "illness", "travel"})
_ENDOGENOUS_TRAINING_CHECK_IN_CAUSES = frozenset({"deliberate_rest", "training_load"})

_CHECK_IN_CAUSE_PATTERNS: dict[str, tuple[str, ...]] = {
    "alcohol": (
        r"\bhangover\b",
        r"\balcohol\b",
        r"\bdrank\b",
        r"\bdrinking\b",
        r"\b\d+(?:\.\d+)?\s*(?:uk\s+)?units?\b",
    ),
    "illness": (
        r"\bunwell\b",
        r"\bill(?:ness)?\b",
        r"\bsick\b",
        r"\bflu\b",
        r"\binfection\b",
        r"\b(?:head|chest\s+)?cold\b",
    ),
    "travel": (
        r"\bholiday\b",
        r"\btravell?(?:ing|ed)?\b",
        r"\baway (?:from home|overnight|on holiday)\b",
        r"\bjet\s*lag\b",
        r"\bdifferent bed\b",
    ),
    "deliberate_rest": (
        r"\btraining break\b",
        r"\brest day\b",
        r"\brecovery week\b",
        r"\bdeload\b",
        r"\bdeliberate(?:ly)? rest\b",
    ),
    "training_load": (
        r"\btraining load\b",
        r"\bcumulative\b.{0,24}\btraining\b",
        r"\bhard(?:er)? day(?:'s)? training\b",
        r"\bhard(?:er)? training\b",
        r"\bback[- ]to[- ]back\b",
        r"\b(?:three|3)[- ]day\b.{0,24}\b(?:block|load|training)\b",
    ),
}

_RECOVERY_ACTION_METRICS = frozenset(
    {"readiness_score", "hrv_7_day_avg_ms", "resting_heart_rate_bpm"}
)

SuggestionTone = Literal["watch", "protect"]
SuggestionStatus = Literal["insufficient_history", "clear", "active"]


@dataclass(frozen=True)
class SleepNight:
    calendar_date: date
    score: int | None = None
    age_adjusted_score: int | None = None
    duration_sec: int | None = None
    deep_sleep_sec: int | None = None
    light_sleep_sec: int | None = None
    rem_sleep_sec: int | None = None
    awake_sleep_sec: int | None = None
    restless_moments_count: int | None = None
    resting_heart_rate_bpm: int | None = None


@dataclass(frozen=True)
class RecoveryDay:
    calendar_date: date
    readiness_score: int | None = None
    hrv_7_day_avg_ms: int | None = None
    resting_heart_rate_bpm: int | None = None
    recovery_time_min: int | None = None
    acute_load: float | None = None
    hrv_last_night_avg_ms: int | None = None
    hrv_status: str | None = None
    hrv_baseline_low_ms: int | None = None
    hrv_baseline_high_ms: int | None = None


@dataclass(frozen=True)
class BaselineBand:
    metric_key: str
    label: str
    lower_quartile: float | None
    upper_quartile: float | None
    median: float | None
    mean: float | None
    sample_count: int


@dataclass(frozen=True)
class PatternFlag:
    metric_key: str
    label: str
    source: Literal["age_norm", "personal_baseline"]
    samples: int
    misses: int
    miss_ratio: float
    comparator: str
    latest_value: float | None
    better: Literal["higher", "lower"]


@dataclass(frozen=True)
class VerdictDay:
    calendar_date: date
    verdict: str | None


@dataclass(frozen=True)
class RedDayEvidence:
    calendar_date: date
    recovery_time_min: int | None = None
    acute_load: float | None = None
    hrv_ms: int | None = None
    hrv_status: str | None = None
    hrv_floor_ms: float | None = None
    resting_heart_rate_bpm: int | None = None
    resting_hr_ceiling_bpm: float | None = None
    check_in_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RedMorningQualification:
    calendar_date: date
    counts_toward_cluster: bool
    classification: str
    explanation_sources: tuple[str, ...]
    evidence: RedDayEvidence | None = None

    def to_packet(self) -> dict[str, Any]:
        evidence = self.evidence
        check_in_reasons = evidence.check_in_reasons if evidence else ()
        return {
            "date": self.calendar_date.isoformat(),
            "countsTowardCluster": self.counts_toward_cluster,
            "classification": self.classification,
            "explanationSources": list(self.explanation_sources),
            "physiology": {
                "recoveryTimeMin": evidence.recovery_time_min if evidence else None,
                "acuteLoad": evidence.acute_load if evidence else None,
                "hrvMs": evidence.hrv_ms if evidence else None,
                "hrvStatus": evidence.hrv_status if evidence else None,
                "hrvFloorMs": evidence.hrv_floor_ms if evidence else None,
                "restingHeartRateBpm": (evidence.resting_heart_rate_bpm if evidence else None),
                "restingHrCeilingBpm": (evidence.resting_hr_ceiling_bpm if evidence else None),
            },
            "checkInReasons": list(check_in_reasons),
            "acuteExogenousReasons": [
                reason for reason in check_in_reasons if reason in _ACUTE_EXOGENOUS_CHECK_IN_CAUSES
            ],
            "endogenousTrainingReasons": [
                reason
                for reason in check_in_reasons
                if reason in _ENDOGENOUS_TRAINING_CHECK_IN_CAUSES
            ],
        }


@dataclass(frozen=True)
class ScheduledRecoveryBlock:
    name: str
    block_type: str
    start_date: date
    end_date: date

    def to_packet(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "blockType": self.block_type,
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
        }


@dataclass(frozen=True)
class RecordedTrainingContext:
    start_date: date
    end_date: date
    reason: str
    source: Literal["holiday_plan", "morning_check_in"]

    def to_packet(self) -> dict[str, Any]:
        return {
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class ChronicActionSignal:
    triggered: bool
    trigger_sources: tuple[str, ...] = ()
    recovery_markers: tuple[str, ...] = ()
    red_morning_count: int = 0
    red_morning_observed_count: int = 0
    red_morning_qualifications: tuple[RedMorningQualification, ...] = ()
    reasons: tuple[str, ...] = ()
    kind: Literal["deload_proposal", "rearrange_proposal"] = "deload_proposal"
    proposal_window_days: int = CHRONIC_DELOAD_WINDOW_DAYS
    suppressed_by_plan: bool = False
    scheduled_recovery_blocks: tuple[ScheduledRecoveryBlock, ...] = ()
    recorded_training_context: tuple[RecordedTrainingContext, ...] = ()

    def to_packet(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "kind": self.kind,
            "proposalWindowDays": self.proposal_window_days,
            "triggerSources": list(self.trigger_sources),
            "recoveryMarkers": list(self.recovery_markers),
            "redMorningCount": self.red_morning_count,
            "redMorningObservedCount": self.red_morning_observed_count,
            "redMorningThreshold": CHRONIC_ACTION_RED_THRESHOLD,
            "redMorningWindowDays": CHRONIC_ACTION_RED_WINDOW_DAYS,
            "acuteRedExclusionLimit": ACUTE_RED_EXCLUSION_LIMIT,
            "acuteRedExclusionMaxAgeDays": ACUTE_RED_EXCLUSION_MAX_AGE_DAYS,
            "redMorningQualifications": [
                item.to_packet() for item in self.red_morning_qualifications
            ],
            "reasons": list(self.reasons),
            "suppressedByPlan": self.suppressed_by_plan,
            "scheduledRecoveryBlocks": [
                block.to_packet() for block in self.scheduled_recovery_blocks
            ],
            "recordedTrainingContext": [
                item.to_packet() for item in self.recorded_training_context
            ],
            "deliveryContract": (
                "restructure_preview_apply"
                if self.kind == "rearrange_proposal"
                else "propose_approve_push"
            ),
            "humanApprovalRequired": True,
            "verdictImpact": "none",
        }


@dataclass(frozen=True)
class EvidenceWindow:
    start_date: date
    end_date: date
    weeks: int
    nights_observed: int
    nights_required: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "startDate": self.start_date.isoformat(),
            "endDate": self.end_date.isoformat(),
            "weeks": self.weeks,
            "nightsObserved": self.nights_observed,
            "nightsRequired": self.nights_required,
        }


@dataclass(frozen=True)
class SuggestionDriver:
    driver: str
    label: str
    coefficient: float
    sample_count: int
    summary: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "label": self.label,
            "coefficient": self.coefficient,
            "sampleCount": self.sample_count,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ChronicSuggestion:
    id: str
    metric_key: str
    label: str
    title: str
    summary: str
    tone: SuggestionTone
    priority: int
    evidence: list[str]
    actions: list[str]
    driver: SuggestionDriver | None = None
    rotation: RemRotation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "metricKey": self.metric_key,
            "label": self.label,
            "title": self.title,
            "summary": self.summary,
            "tone": self.tone,
            "priority": self.priority,
            "evidence": self.evidence,
            "actions": self.actions,
            "driver": self.driver.to_dict() if self.driver else None,
            "rotation": self.rotation.to_dict() if self.rotation else None,
        }


@dataclass(frozen=True)
class ChronicSuggestionResult:
    status: SuggestionStatus
    headline: str
    summary: str
    evidence_window: EvidenceWindow
    items: list[ChronicSuggestion] = field(default_factory=list)
    action_signal: ChronicActionSignal = field(
        default_factory=lambda: ChronicActionSignal(triggered=False)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "headline": self.headline,
            "summary": self.summary,
            "evidenceWindow": self.evidence_window.to_dict(),
            "items": [item.to_dict() for item in self.items],
        }


_DRIVER_LABELS = {
    "prev_day_training_load": "training load",
    "overnight_low_c": "warm overnight weather",
    "overnight_wind_max_mph": "overnight wind",
    "bedroom_warning_minutes": "time above 19.5C",
    "bedroom_critical_minutes": "time above 20C",
    "bedroom_fan_ran_minutes": "fan runtime",
    "bedroom_peak_fan_speed": "fan speed",
    "daytime_stress_avg": "daytime stress",
    "resting_heart_rate_bpm": "resting heart rate",
    "sleep_stress_avg": "sleep stress",
}

_BASELINE_SPECS: dict[str, tuple[str, Literal["higher", "lower"]]] = {
    "sleep_score": ("Sleep score", "higher"),
    "age_adjusted_sleep_score": ("Age-adjusted sleep", "higher"),
    "readiness_score": ("Readiness", "higher"),
    "hrv_7_day_avg_ms": ("HRV (7-day)", "higher"),
    "resting_heart_rate_bpm": ("Resting HR", "lower"),
}

_PROTECTED_METRICS = {
    "sleep_duration_hours",
    "rem_sleep_pct",
    "deep_sleep_pct",
    "awake_sleep_pct",
    "restless_moments_count",
    "sleep_score",
    "age_adjusted_sleep_score",
}


def build_chronic_pattern_suggestions(
    *,
    sleeps: Sequence[SleepNight],
    recovery_days: Sequence[RecoveryDay],
    baselines: Mapping[str, BaselineBand],
    sleep_drivers: Sequence[DriverCorrelation],
    age: int | None,
    sex: str | None,
    sleep_protocol: Mapping[str, Any] | None,
    as_of: date,
    window_days: int = WINDOW_DAYS,
    recent_verdicts: Sequence[VerdictDay] = (),
    red_day_evidence: Mapping[date, RedDayEvidence] | None = None,
    scheduled_recovery_blocks: Sequence[ScheduledRecoveryBlock] = (),
    recorded_training_context: Sequence[RecordedTrainingContext] = (),
) -> ChronicSuggestionResult:
    """Detect repeated below-norm/baseline misses and map them to actions."""
    start = as_of - timedelta(days=window_days - 1)
    window = EvidenceWindow(
        start_date=start,
        end_date=as_of,
        weeks=max(1, round(window_days / 7)),
        nights_observed=len([row for row in sleeps if start <= row.calendar_date <= as_of]),
        nights_required=MIN_OBSERVED_NIGHTS,
    )
    if window.nights_observed < MIN_OBSERVED_NIGHTS:
        return ChronicSuggestionResult(
            status="insufficient_history",
            headline="Not enough recent sleep history yet",
            summary=(
                f"{window.nights_observed} nights are available in the last {window.weeks} weeks; "
                f"{MIN_OBSERVED_NIGHTS} are needed before the app calls a chronic pattern."
            ),
            evidence_window=window,
            action_signal=_chronic_action_signal(
                [],
                recent_verdicts,
                as_of=as_of,
                red_day_evidence=red_day_evidence,
                scheduled_recovery_blocks=scheduled_recovery_blocks,
                recorded_training_context=recorded_training_context,
            ),
        )

    flags = _age_norm_flags(sleeps, age=age, sex=sex, start=start, end=as_of)
    flags.extend(_baseline_flags(sleeps, recovery_days, baselines, start=start, end=as_of))
    chronic = [
        flag
        for flag in flags
        if flag.samples >= MIN_METRIC_SAMPLES and flag.misses >= _miss_threshold(flag.samples)
    ]
    chronic.sort(key=lambda flag: (flag.miss_ratio, flag.misses), reverse=True)
    action_signal = _chronic_action_signal(
        chronic,
        recent_verdicts,
        as_of=as_of,
        red_day_evidence=red_day_evidence,
        scheduled_recovery_blocks=scheduled_recovery_blocks,
        recorded_training_context=recorded_training_context,
    )

    drivers = _useful_drivers(sleep_drivers)
    suggestions = [
        _suggestion(
            flag,
            index=index,
            driver=_driver_for_flag(flag, drivers),
            protocol=sleep_protocol,
            as_of=as_of,
        )
        for index, flag in enumerate(chronic[:3])
    ]
    if not suggestions:
        return ChronicSuggestionResult(
            status="clear",
            headline="No chronic sleep pattern flagged",
            summary=(
                f"The last {window.weeks} weeks have enough history, but no sleep metric missed "
                "its age norm or personal band often enough to call it chronic."
            ),
            evidence_window=window,
            action_signal=action_signal,
        )
    return ChronicSuggestionResult(
        status="active",
        headline="Chronic sleep patterns to work on",
        summary=(
            f"{len(suggestions)} repeated pattern{'s' if len(suggestions) != 1 else ''} "
            f"stood out across {window.nights_observed} recent nights."
        ),
        evidence_window=window,
        items=suggestions,
        action_signal=action_signal,
    )


class ChronicPatternSuggestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def suggestions(
        self,
        player: Profile,
        *,
        as_of: date,
        sleep_drivers: Sequence[DriverCorrelation],
        sleep_protocol: Mapping[str, Any] | None = None,
        current_verdict: str | None = None,
    ) -> ChronicSuggestionResult:
        start = as_of - timedelta(days=WINDOW_DAYS - 1)
        sleep_rows = (
            (
                await self.session.execute(
                    select(Sleep)
                    .where(
                        Sleep.user_id == player.id,
                        Sleep.calendar_date >= start,
                        Sleep.calendar_date <= as_of,
                    )
                    .order_by(Sleep.calendar_date.asc())
                )
            )
            .scalars()
            .all()
        )
        metric_rows = (
            (
                await self.session.execute(
                    select(DailyMetric)
                    .where(
                        DailyMetric.user_id == player.id,
                        DailyMetric.calendar_date >= start,
                        DailyMetric.calendar_date <= as_of,
                    )
                    .order_by(DailyMetric.calendar_date.asc())
                )
            )
            .scalars()
            .all()
        )
        profile_section = await self._profile_section(player.id)
        age = _profile_age(profile_section)
        sex = _profile_sex(profile_section)
        baseline_bands = await self._baselines(player.id)
        manual_rows = await self._manual_entries(player.id, start=start, end=as_of)
        recent_verdicts = await self._recent_verdicts(player.id, as_of=as_of)
        if current_verdict is not None:
            recent_verdicts = [row for row in recent_verdicts if row.calendar_date != as_of] + [
                VerdictDay(calendar_date=as_of, verdict=current_verdict)
            ]
        recovery_days = [_recovery_day(row) for row in metric_rows]
        return build_chronic_pattern_suggestions(
            sleeps=[_sleep_night(row, age=age, sex=sex) for row in sleep_rows],
            recovery_days=recovery_days,
            baselines=baseline_bands,
            sleep_drivers=sleep_drivers,
            age=age,
            sex=sex,
            sleep_protocol=sleep_protocol,
            as_of=as_of,
            recent_verdicts=recent_verdicts,
            red_day_evidence=_red_day_evidence(
                recovery_days,
                manual_rows=manual_rows,
                baselines=baseline_bands,
            ),
            scheduled_recovery_blocks=await self._scheduled_recovery_blocks(player.id, as_of=as_of),
            recorded_training_context=await self._recorded_training_context(
                player.id,
                start=start,
                end=as_of,
                manual_rows=manual_rows,
            ),
        )

    async def _manual_entries(
        self, user_id: uuid.UUID, *, start: date, end: date
    ) -> list[ManualEntry]:
        rows = await self.session.execute(
            select(ManualEntry)
            .where(
                ManualEntry.user_id == user_id,
                ManualEntry.entry_date >= start,
                ManualEntry.entry_date <= end,
                ManualEntry.planned_workout_id.is_(None),
                ManualEntry.activity_id.is_(None),
            )
            .order_by(ManualEntry.entry_date.asc(), ManualEntry.entry_at_utc.asc())
        )
        return list(rows.scalars().all())

    async def _scheduled_recovery_blocks(
        self, user_id: uuid.UUID, *, as_of: date
    ) -> list[ScheduledRecoveryBlock]:
        end = as_of + timedelta(days=CHRONIC_DELOAD_WINDOW_DAYS - 1)
        rows = (
            (
                await self.session.execute(
                    select(PlanBlock)
                    .join(PlannedWorkout, PlannedWorkout.plan_block_id == PlanBlock.id)
                    .where(
                        PlanBlock.user_id == user_id,
                        func.lower(PlanBlock.block_type).in_(_PLANNED_RECOVERY_BLOCK_TYPES),
                        PlanBlock.start_date <= end,
                        PlanBlock.end_date >= as_of,
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status == "planned",
                        PlannedWorkout.workout_date >= as_of,
                        PlannedWorkout.workout_date <= end,
                    )
                    .order_by(PlanBlock.start_date.asc(), PlanBlock.name.asc())
                )
            )
            .scalars()
            .unique()
            .all()
        )
        return [
            ScheduledRecoveryBlock(
                name=row.name,
                block_type=str(row.block_type or "").lower(),
                start_date=row.start_date,
                end_date=row.end_date,
            )
            for row in rows
        ]

    async def _recorded_training_context(
        self,
        user_id: uuid.UUID,
        *,
        start: date,
        end: date,
        manual_rows: Sequence[ManualEntry],
    ) -> list[RecordedTrainingContext]:
        recorded = _check_in_training_context(manual_rows)
        row = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == "holiday_windows",
                KnowledgeBase.is_active.is_(True),
            )
        )
        windows = row.content.get("windows", []) if row and isinstance(row.content, dict) else []
        for raw in windows:
            if not isinstance(raw, dict):
                continue
            try:
                window_start = date.fromisoformat(str(raw["startDate"]))
                window_end = date.fromisoformat(str(raw["endDate"]))
            except (KeyError, TypeError, ValueError):
                continue
            if window_start <= end and window_end >= start:
                recorded.append(
                    RecordedTrainingContext(
                        start_date=window_start,
                        end_date=window_end,
                        reason="holiday",
                        source="holiday_plan",
                    )
                )
        return sorted(
            recorded,
            key=lambda item: (item.start_date, item.end_date, item.reason, item.source),
        )

    async def _profile_section(self, user_id: uuid.UUID) -> Mapping[str, Any]:
        row = await self.session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == "profile",
                KnowledgeBase.is_active.is_(True),
            )
        )
        return row.content if row and isinstance(row.content, dict) else {}

    async def _profile_age(self, user_id: uuid.UUID) -> int | None:
        return _profile_age(await self._profile_section(user_id))

    async def _profile_sex(self, user_id: uuid.UUID) -> str | None:
        return _profile_sex(await self._profile_section(user_id))

    async def _baselines(self, user_id: uuid.UUID) -> dict[str, BaselineBand]:
        rows = (
            (
                await self.session.execute(
                    select(MetricBaseline).where(MetricBaseline.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        selected: dict[str, MetricBaseline] = {}
        for row in rows:
            existing = selected.get(row.metric_key)
            if existing is None or row.source == "db_history":
                selected[row.metric_key] = row
        return {
            key: BaselineBand(
                metric_key=row.metric_key,
                label=row.metric_label,
                lower_quartile=row.lower_quartile_value,
                upper_quartile=row.upper_quartile_value,
                median=row.median_value,
                mean=row.mean_value,
                sample_count=row.sample_count,
            )
            for key, row in selected.items()
        }

    async def _recent_verdicts(self, user_id: uuid.UUID, *, as_of: date) -> list[VerdictDay]:
        start = as_of - timedelta(days=CHRONIC_ACTION_RED_WINDOW_DAYS - 1)
        rows = (
            (
                await self.session.execute(
                    select(Analysis)
                    .where(
                        Analysis.user_id == user_id,
                        Analysis.analysis_type == "morning",
                        Analysis.subject_date >= start,
                        Analysis.subject_date <= as_of,
                    )
                    .order_by(
                        Analysis.subject_date.asc(),
                        Analysis.generated_at_utc.asc(),
                        Analysis.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        latest_by_date: dict[date, str | None] = {}
        for row in rows:
            latest_by_date[row.subject_date] = row.verdict
        return [
            VerdictDay(calendar_date=day, verdict=latest_by_date[day])
            for day in sorted(latest_by_date)
        ]


def _profile_age(profile_section: Mapping[str, Any]) -> int | None:
    value = profile_section.get("age")
    return int(value) if isinstance(value, int | float) else None


def _profile_sex(profile_section: Mapping[str, Any]) -> str | None:
    value = profile_section.get("sex")
    return value if isinstance(value, str) else None


def _sleep_night(row: Sleep, *, age: int | None = None, sex: str | None = None) -> SleepNight:
    return SleepNight(
        calendar_date=row.calendar_date,
        score=row.score,
        age_adjusted_score=age_adjusted_sleep_score_for_row(row, age=age, sex=sex),
        duration_sec=row.duration_sec,
        deep_sleep_sec=row.deep_sleep_sec,
        light_sleep_sec=row.light_sleep_sec,
        rem_sleep_sec=row.rem_sleep_sec,
        awake_sleep_sec=row.awake_sleep_sec,
        restless_moments_count=row.restless_moments_count,
        resting_heart_rate_bpm=row.resting_heart_rate_bpm,
    )


def _recovery_day(row: DailyMetric) -> RecoveryDay:
    return RecoveryDay(
        calendar_date=row.calendar_date,
        readiness_score=row.readiness_score,
        hrv_7_day_avg_ms=row.hrv_weekly_avg_ms,
        resting_heart_rate_bpm=row.resting_heart_rate_bpm,
        recovery_time_min=row.recovery_time_min,
        acute_load=row.acute_load,
        hrv_last_night_avg_ms=row.hrv_last_night_avg_ms,
        hrv_status=row.hrv_status,
        hrv_baseline_low_ms=row.hrv_baseline_low_ms,
        hrv_baseline_high_ms=row.hrv_baseline_high_ms,
    )


def classify_check_in_causes(feel: str | None, notes: str | None) -> tuple[str, ...]:
    """Turn Mark's persisted free-text explanation into narrow acute-cause tags.

    This is deliberately a deterministic vocabulary rather than an LLM read: the
    tags can qualify chronic escalation, so the same text must produce the same
    result on every run. Unknown wording stays unknown and therefore cannot make a
    Red disappear. A small negation check avoids treating phrases such as "no
    alcohol" as an explanation.
    """

    text = " ".join(part.strip() for part in (feel, notes) if part and part.strip()).lower()
    if not text:
        return ()
    found: list[str] = []
    for cause, patterns in _CHECK_IN_CAUSE_PATTERNS.items():
        if any(_non_negated_match(text, pattern) for pattern in patterns):
            found.append(cause)
    return tuple(found)


def _non_negated_match(text: str, pattern: str) -> bool:
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start() - 18) : match.start()]
        if not re.search(
            r"(?:\bno|\bnot|\bwithout|\bdidn['’]?t)(?:\s+\w+){0,2}\s+$",
            prefix,
        ):
            return True
    return False


def _check_in_training_context(
    manual_rows: Sequence[ManualEntry],
) -> list[RecordedTrainingContext]:
    recorded: list[RecordedTrainingContext] = []
    seen: set[tuple[date, str]] = set()
    for row in manual_rows:
        for cause in classify_check_in_causes(row.feel, row.notes):
            key = (row.entry_date, cause)
            if key in seen:
                continue
            seen.add(key)
            recorded.append(
                RecordedTrainingContext(
                    start_date=row.entry_date,
                    end_date=row.entry_date,
                    reason=cause,
                    source="morning_check_in",
                )
            )
    return recorded


def _red_day_evidence(
    recovery_days: Sequence[RecoveryDay],
    *,
    manual_rows: Sequence[ManualEntry],
    baselines: Mapping[str, BaselineBand],
) -> dict[date, RedDayEvidence]:
    text_by_date: dict[date, list[str | None]] = {}
    for manual_row in manual_rows:
        text_by_date.setdefault(manual_row.entry_date, []).extend(
            (manual_row.feel, manual_row.notes)
        )

    hrv_baseline = baselines.get("hrv_7_day_avg_ms")
    rhr_baseline = baselines.get("resting_heart_rate_bpm")
    evidence: dict[date, RedDayEvidence] = {}
    for recovery_day in recovery_days:
        texts = text_by_date.get(recovery_day.calendar_date, [])
        feel = " ".join(part for part in texts[::2] if part) or None
        notes = " ".join(part for part in texts[1::2] if part) or None
        evidence[recovery_day.calendar_date] = RedDayEvidence(
            calendar_date=recovery_day.calendar_date,
            recovery_time_min=recovery_day.recovery_time_min,
            acute_load=recovery_day.acute_load,
            hrv_ms=recovery_day.hrv_7_day_avg_ms or recovery_day.hrv_last_night_avg_ms,
            hrv_status=recovery_day.hrv_status,
            hrv_floor_ms=(
                float(recovery_day.hrv_baseline_low_ms)
                if recovery_day.hrv_baseline_low_ms is not None
                else hrv_baseline.lower_quartile
                if hrv_baseline is not None
                else None
            ),
            resting_heart_rate_bpm=recovery_day.resting_heart_rate_bpm,
            resting_hr_ceiling_bpm=(
                rhr_baseline.upper_quartile if rhr_baseline is not None else None
            ),
            check_in_reasons=classify_check_in_causes(feel, notes),
        )
    return evidence


def _age_norm_flags(
    sleeps: Sequence[SleepNight],
    *,
    age: int | None,
    sex: str | None,
    start: date,
    end: date,
) -> list[PatternFlag]:
    grouped: dict[str, list[tuple[bool, float | None, str, str, Literal["higher", "lower"]]]] = {}
    for sleep in sleeps:
        if not start <= sleep.calendar_date <= end:
            continue
        comparison = build_age_comparison(
            age=age,
            sex=sex,
            vo2max=None,
            resting_heart_rate_bpm=None,
            hrv_overnight_ms=None,
            fitness_age=None,
            duration_sec=sleep.duration_sec,
            deep_sleep_sec=sleep.deep_sleep_sec,
            light_sleep_sec=sleep.light_sleep_sec,
            rem_sleep_sec=sleep.rem_sleep_sec,
            awake_sleep_sec=sleep.awake_sleep_sec,
            restless_moments_count=sleep.restless_moments_count,
        )
        for row in comparison.sleep_rows:
            # Light is not suggestion-driving (#132); Restless has no defensible
            # population band (Batch 61) — both stay out of age-norm flagging.
            if row.metric_key in {"light_sleep_pct", "restless_moments_count"}:
                continue
            if row.band_low is not None and row.band_high is not None:
                reference = (
                    f"healthy {row.age_band} range {row.band_low:g}–{row.band_high:g}{row.unit}"
                )
            else:
                reference = f"typical {row.age_band} value {row.age_average:g}{row.unit}"
            grouped.setdefault(row.metric_key, []).append(
                (
                    row.tone == "warn",
                    row.value,
                    row.label,
                    reference,
                    row.better_direction,
                )
            )
    return [_flag_from_group(key, "age_norm", values) for key, values in grouped.items()]


def _baseline_flags(
    sleeps: Sequence[SleepNight],
    recovery_days: Sequence[RecoveryDay],
    baselines: Mapping[str, BaselineBand],
    *,
    start: date,
    end: date,
) -> list[PatternFlag]:
    values_by_key: dict[str, list[float | None]] = {
        "sleep_score": [float(row.score) if row.score is not None else None for row in sleeps],
        "age_adjusted_sleep_score": [
            float(row.age_adjusted_score) if row.age_adjusted_score is not None else None
            for row in sleeps
        ],
        "readiness_score": [
            float(row.readiness_score) if row.readiness_score is not None else None
            for row in recovery_days
        ],
        "hrv_7_day_avg_ms": [
            float(row.hrv_7_day_avg_ms) if row.hrv_7_day_avg_ms is not None else None
            for row in recovery_days
        ],
        "resting_heart_rate_bpm": [
            float(row.resting_heart_rate_bpm) if row.resting_heart_rate_bpm is not None else None
            for row in recovery_days
        ],
    }
    # The date-window filtering happens before callers build the sequences in the
    # DB path. Pure tests may pass wider fixtures, so filter here too.
    sleep_dates = [row.calendar_date for row in sleeps if start <= row.calendar_date <= end]
    recovery_dates = [
        row.calendar_date for row in recovery_days if start <= row.calendar_date <= end
    ]
    valid_lengths = {
        "sleep_score": len(sleep_dates),
        "age_adjusted_sleep_score": len(sleep_dates),
        "readiness_score": len(recovery_dates),
        "hrv_7_day_avg_ms": len(recovery_dates),
        "resting_heart_rate_bpm": len(recovery_dates),
    }

    flags: list[PatternFlag] = []
    for key, (fallback_label, better) in _BASELINE_SPECS.items():
        baseline = baselines.get(key)
        if baseline is None:
            continue
        threshold = baseline.lower_quartile if better == "higher" else baseline.upper_quartile
        if threshold is None:
            continue
        samples: list[tuple[bool, float | None, str, str, Literal["higher", "lower"]]] = []
        for value in values_by_key.get(key, [])[: valid_lengths[key]]:
            if value is None:
                continue
            miss = value < threshold if better == "higher" else value > threshold
            comparator = (
                f"personal floor {threshold:g}"
                if better == "higher"
                else f"personal ceiling {threshold:g}"
            )
            samples.append((miss, value, baseline.label or fallback_label, comparator, better))
        if samples:
            flags.append(_flag_from_group(key, "personal_baseline", samples))
    return flags


def _flag_from_group(
    metric_key: str,
    source: Literal["age_norm", "personal_baseline"],
    values: Sequence[tuple[bool, float | None, str, str, Literal["higher", "lower"]]],
) -> PatternFlag:
    samples = len(values)
    misses = len([item for item in values if item[0]])
    latest_value = next((item[1] for item in reversed(values) if item[1] is not None), None)
    first = values[0]
    return PatternFlag(
        metric_key=metric_key,
        label=first[2],
        source=source,
        samples=samples,
        misses=misses,
        miss_ratio=misses / samples if samples else 0.0,
        comparator=first[3],
        latest_value=latest_value,
        better=first[4],
    )


def _miss_threshold(samples: int) -> int:
    return max(MIN_METRIC_SAMPLES, math.ceil(samples * 0.5))


def _chronic_action_signal(
    chronic_flags: Sequence[PatternFlag],
    recent_verdicts: Sequence[VerdictDay],
    *,
    as_of: date,
    red_day_evidence: Mapping[date, RedDayEvidence] | None = None,
    scheduled_recovery_blocks: Sequence[ScheduledRecoveryBlock] = (),
    recorded_training_context: Sequence[RecordedTrainingContext] = (),
) -> ChronicActionSignal:
    """Escalate chronic evidence to a deload and acute clusters to rearrange.

    A protected recovery marker must still miss its personal band on at least 70%
    of already-qualified samples before the seven-day deload path can fire. A
    clustered pair of Reds is a different, acute signal: each Red is first
    qualified using its same-day physiology and persisted check-in explanation,
    and a qualifying pair may only propose a week-preserving rearrangement.
    """

    recovery_flags = [
        flag
        for flag in chronic_flags
        if flag.source == "personal_baseline"
        and flag.metric_key in _RECOVERY_ACTION_METRICS
        and flag.samples >= MIN_METRIC_SAMPLES
        and flag.miss_ratio >= CHRONIC_ACTION_MISS_RATIO
    ]
    recovery_flags.sort(key=lambda flag: (flag.miss_ratio, flag.misses), reverse=True)

    verdict_start = as_of - timedelta(days=CHRONIC_ACTION_RED_WINDOW_DAYS - 1)
    latest_by_date: dict[date, str | None] = {}
    for row in recent_verdicts:
        if verdict_start <= row.calendar_date <= as_of:
            latest_by_date[row.calendar_date] = row.verdict
    evidence_by_date = red_day_evidence or {}
    red_days = [
        day
        for day, verdict in sorted(latest_by_date.items())
        if (verdict or "").strip().lower() == "red"
    ]
    # Acute check-in explanations are a bounded exception, never a permanent
    # veto. Work newest-first so the one available exclusion belongs to the most
    # recent still-live explanation; return the evidence in chronological order.
    acute_exclusions_remaining = ACUTE_RED_EXCLUSION_LIMIT
    qualifications_by_date: dict[date, RedMorningQualification] = {}
    for day in reversed(red_days):
        qualification = _qualify_red_morning(
            day,
            evidence_by_date.get(day),
            as_of=as_of,
            allow_acute_exclusion=acute_exclusions_remaining > 0,
        )
        qualifications_by_date[day] = qualification
        if qualification.classification == "explained_by_acute_check_in":
            acute_exclusions_remaining -= 1
    qualifications = tuple(qualifications_by_date[day] for day in red_days)
    red_count = sum(1 for item in qualifications if item.counts_toward_cluster)

    trigger_sources: list[str] = []
    reasons: list[str] = []
    kind: Literal["deload_proposal", "rearrange_proposal"] = "deload_proposal"
    suppressed_by_plan = False
    if recovery_flags:
        trigger_sources.append("sustained_recovery_marker")
        markers = ", ".join(flag.label for flag in recovery_flags)
        reasons.append(
            f"{markers} missed the personal recovery band on at least "
            f"{CHRONIC_ACTION_MISS_RATIO * 100:.0f}% of measured days."
        )
    elif red_count >= CHRONIC_ACTION_RED_THRESHOLD:
        kind = "rearrange_proposal"
        trigger_sources.append("red_morning_cluster")
        reasons.append(
            f"{red_count} unexplained or systemically strained Red mornings occurred "
            f"inside the last {CHRONIC_ACTION_RED_WINDOW_DAYS} days; preserve the "
            "weekly mix by rearranging rather than reducing the week."
        )

    recovery_blocks = tuple(scheduled_recovery_blocks)
    if trigger_sources and recovery_blocks:
        suppressed_by_plan = True
        block_labels = ", ".join(f"{block.name} ({block.block_type})" for block in recovery_blocks)
        reasons.append(
            "No extra structural proposal because the plan already schedules "
            f"{block_labels} inside the seven-day action horizon."
        )

    return ChronicActionSignal(
        triggered=bool(trigger_sources) and not suppressed_by_plan,
        trigger_sources=tuple(trigger_sources),
        recovery_markers=tuple(flag.metric_key for flag in recovery_flags),
        red_morning_count=red_count,
        red_morning_observed_count=len(red_days),
        red_morning_qualifications=qualifications,
        reasons=tuple(reasons),
        kind=kind,
        suppressed_by_plan=suppressed_by_plan,
        scheduled_recovery_blocks=recovery_blocks,
        recorded_training_context=tuple(recorded_training_context),
    )


def _qualify_red_morning(
    calendar_date: date,
    evidence: RedDayEvidence | None,
    *,
    as_of: date,
    allow_acute_exclusion: bool,
) -> RedMorningQualification:
    if evidence is None:
        return RedMorningQualification(
            calendar_date=calendar_date,
            counts_toward_cluster=True,
            classification="unexplained_red",
            explanation_sources=(),
            evidence=None,
        )

    acute_reasons = tuple(
        reason for reason in evidence.check_in_reasons if reason in _ACUTE_EXOGENOUS_CHECK_IN_CAUSES
    )
    endogenous_reasons = tuple(
        reason
        for reason in evidence.check_in_reasons
        if reason in _ENDOGENOUS_TRAINING_CHECK_IN_CAUSES
    )

    hrv_status = str(evidence.hrv_status or "").strip().lower()
    hrv_crashed = evidence.hrv_ms is not None and (
        (evidence.hrv_floor_ms is not None and float(evidence.hrv_ms) < evidence.hrv_floor_ms)
        or hrv_status in {"unbalanced", "low", "poor"}
    )
    resting_hr_crashed = (
        evidence.resting_heart_rate_bpm is not None
        and evidence.resting_hr_ceiling_bpm is not None
        and float(evidence.resting_heart_rate_bpm) > evidence.resting_hr_ceiling_bpm
    )

    # Training load and deliberate recovery are the structural rail's signal,
    # not an acute excuse for suppressing it. If both acute and endogenous tags
    # are present, the endogenous signal wins.
    if endogenous_reasons:
        return RedMorningQualification(
            calendar_date=calendar_date,
            counts_toward_cluster=True,
            classification="endogenous_training_signal",
            explanation_sources=("morning_check_in", "endogenous_training_signal"),
            evidence=evidence,
        )

    if acute_reasons:
        if hrv_crashed or resting_hr_crashed:
            return RedMorningQualification(
                calendar_date=calendar_date,
                counts_toward_cluster=True,
                classification="acute_cause_with_systemic_strain",
                explanation_sources=("morning_check_in", "strained_physiology"),
                evidence=evidence,
            )
        if (as_of - calendar_date).days > ACUTE_RED_EXCLUSION_MAX_AGE_DAYS:
            return RedMorningQualification(
                calendar_date=calendar_date,
                counts_toward_cluster=True,
                classification="acute_check_in_expired",
                explanation_sources=("morning_check_in", "exclusion_expired"),
                evidence=evidence,
            )
        if not allow_acute_exclusion:
            return RedMorningQualification(
                calendar_date=calendar_date,
                counts_toward_cluster=True,
                classification="acute_exclusion_cap_reached",
                explanation_sources=("morning_check_in", "exclusion_cap"),
                evidence=evidence,
            )
        return RedMorningQualification(
            calendar_date=calendar_date,
            counts_toward_cluster=False,
            classification="explained_by_acute_check_in",
            explanation_sources=("morning_check_in",),
            evidence=evidence,
        )

    hrv_not_below_floor = evidence.hrv_ms is not None and (
        evidence.hrv_floor_ms is None or float(evidence.hrv_ms) >= evidence.hrv_floor_ms
    )
    hrv_intact = hrv_not_below_floor and hrv_status in _HEALTHY_HRV_STATES
    resting_hr_intact = (
        evidence.resting_heart_rate_bpm is not None
        and evidence.resting_hr_ceiling_bpm is not None
        and float(evidence.resting_heart_rate_bpm) <= evidence.resting_hr_ceiling_bpm
    )
    recovery_debt = (
        evidence.recovery_time_min is not None
        and evidence.recovery_time_min > RECOVERY_DEBT_EXPLAINED_MIN
    )
    if recovery_debt and hrv_intact and resting_hr_intact:
        return RedMorningQualification(
            calendar_date=calendar_date,
            counts_toward_cluster=False,
            classification="expected_training_debt",
            explanation_sources=("recovery_debt", "intact_hrv", "intact_resting_hr"),
            evidence=evidence,
        )

    classification = (
        "systemic_markers_strained" if hrv_crashed or resting_hr_crashed else "unexplained_red"
    )
    return RedMorningQualification(
        calendar_date=calendar_date,
        counts_toward_cluster=True,
        classification=classification,
        explanation_sources=(),
        evidence=evidence,
    )


def _useful_drivers(drivers: Sequence[DriverCorrelation]) -> list[SuggestionDriver]:
    ranked = [
        driver
        for driver in drivers
        if driver.sample_count >= MIN_DRIVER_SAMPLES and driver.coefficient < 0
    ] or [driver for driver in drivers if driver.sample_count >= MIN_DRIVER_SAMPLES]
    return [
        SuggestionDriver(
            driver=driver.driver,
            label=_DRIVER_LABELS.get(driver.driver, driver.driver.replace("_", " ")),
            coefficient=driver.coefficient,
            sample_count=driver.sample_count,
            summary=driver.summary,
        )
        for driver in ranked
    ]


def _driver_for_flag(
    flag: PatternFlag, drivers: Sequence[SuggestionDriver]
) -> SuggestionDriver | None:
    if not drivers:
        return None
    if flag.metric_key in {"awake_sleep_pct", "restless_moments_count", "deep_sleep_pct"}:
        thermal = next((driver for driver in drivers if driver.driver.startswith("bedroom_")), None)
        if thermal:
            return thermal
    if flag.metric_key in {"sleep_duration_hours", "rem_sleep_pct"}:
        load = next(
            (driver for driver in drivers if driver.driver == "prev_day_training_load"),
            None,
        )
        if load:
            return load
    stress = next(
        (
            driver
            for driver in drivers
            if driver.driver in {"daytime_stress_avg", "sleep_stress_avg"}
        ),
        None,
    )
    return stress or drivers[0]


def _suggestion(
    flag: PatternFlag,
    *,
    index: int,
    driver: SuggestionDriver | None,
    protocol: Mapping[str, Any] | None,
    as_of: date,
) -> ChronicSuggestion:
    tone: SuggestionTone = "protect" if flag.miss_ratio >= 0.7 else "watch"
    evidence = [(f"{flag.misses} of {flag.samples} measured nights missed {flag.comparator}.")]
    if flag.latest_value is not None:
        evidence.append(f"Latest value: {_format_value(flag.latest_value)}.")
    if driver and driver.summary:
        evidence.append(driver.summary)
    actions, rotation = _actions_for(flag.metric_key, driver, protocol, as_of)
    title = _title_for(flag)
    return ChronicSuggestion(
        id=f"chronic-{flag.metric_key}",
        metric_key=flag.metric_key,
        label=flag.label,
        title=title,
        summary=_summary_for(flag, driver),
        tone=tone,
        priority=index + 1,
        evidence=evidence[:3],
        actions=actions[:3],
        driver=driver,
        rotation=rotation,
    )


def _title_for(flag: PatternFlag) -> str:
    if flag.metric_key == "rem_sleep_pct":
        return "Protect REM consistency"
    if flag.metric_key == "deep_sleep_pct":
        return "Protect early-night deep sleep"
    if flag.metric_key == "sleep_duration_hours":
        return "Lift total sleep time"
    if flag.metric_key in {"awake_sleep_pct", "restless_moments_count"}:
        return "Reduce overnight disruption"
    if flag.metric_key in {"sleep_score", "age_adjusted_sleep_score"}:
        return "Stabilise the overall sleep score"
    if flag.metric_key in {"hrv_7_day_avg_ms", "readiness_score"}:
        return "Protect recovery markers"
    if flag.metric_key == "resting_heart_rate_bpm":
        return "Keep resting HR inside range"
    return f"Work on {flag.label.lower()}"


def _summary_for(flag: PatternFlag, driver: SuggestionDriver | None) -> str:
    basis = "age norm" if flag.source == "age_norm" else "personal baseline"
    if driver:
        return (
            f"{flag.label} has repeatedly missed its {basis}; {driver.label} is the "
            "strongest measured lever to check first."
        )
    return f"{flag.label} has repeatedly missed its {basis}; keep the action narrow and measurable."


def _actions_for(
    metric_key: str,
    driver: SuggestionDriver | None,
    protocol: Mapping[str, Any] | None,
    as_of: date,
) -> tuple[list[str], RemRotation | None]:
    bedtime = _protocol_value(protocol, "bedtime", "23:15")
    seal = _protocol_value(protocol, "sealTargetTime", "22:00")
    breathing = _protocol_value(protocol, "coherenceBreathingTime", "20:00")
    snack = _protocol_value(protocol, "latestSnackTime", "21:30")

    rotation: RemRotation | None = None
    actions: list[str] = []
    if driver:
        if driver.driver.startswith("bedroom_") or driver.driver == "overnight_low_c":
            actions.append(
                f"Check Bedroom before the {seal} seal point and let Auto hold the pre-cool."
            )
        elif driver.driver == "prev_day_training_load":
            actions.append(
                "Treat high-load or late-training evenings as protect nights: shorten "
                "the admin tail and start wind-down earlier."
            )
        elif driver.driver in {"daytime_stress_avg", "sleep_stress_avg"}:
            actions.append(f"Keep the {breathing} coherence-breathing slot non-negotiable.")
        elif driver.driver == "resting_heart_rate_bpm":
            actions.append(
                "If resting HR is elevated too, keep the morning check-in honest "
                "before approving work."
            )

    if metric_key == "rem_sleep_pct":
        # Batch 72: a persistent REM miss gets a broader, rotating library handed
        # out one or two at a time — not the same static pair every week.
        rem_actions, rotation = select_rem_interventions(
            as_of=as_of,
            protocol=protocol,
            driver_key=driver.driver if driver else None,
        )
        actions.extend(rem_actions)
    elif metric_key == "deep_sleep_pct":
        actions.append(
            f"Keep the final snack before {snack} and the room cool before the first cycle."
        )
        actions.append("Keep alcohol-free, heavy-food-free evenings around key training days.")
    elif metric_key == "sleep_duration_hours":
        actions.append(
            f"Use {bedtime} as a hard stop, not an aspiration, until duration normalises."
        )
        actions.append(
            "If the day ran late, protect the next morning rather than compressing sleep."
        )
    elif metric_key in {"awake_sleep_pct", "restless_moments_count"}:
        actions.append(
            f"Tighten the room setup by {seal}; disruption is the first thing to remove."
        )
        actions.append(f"Keep fluids/snack finished by {snack} so wake-ups have fewer triggers.")
    elif metric_key in {"sleep_score", "age_adjusted_sleep_score"}:
        actions.append(
            f"Run the full sleep protocol: breathing at {breathing}, seal by {seal}, bed {bedtime}."
        )
    elif metric_key in {"hrv_7_day_avg_ms", "readiness_score"}:
        actions.append(
            "Pair the suggestion with the existing Green/Amber/Red read; do not chase load."
        )
    elif metric_key == "resting_heart_rate_bpm":
        actions.append("Bias the evening toward cooling, hydration, and a clean wind-down.")

    # De-duplicate while preserving priority.
    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped, rotation


def _protocol_value(protocol: Mapping[str, Any] | None, key: str, fallback: str) -> str:
    if not protocol:
        return fallback
    value = protocol.get(key)
    return str(value) if isinstance(value, str | int | float) else fallback


def _format_value(value: float) -> str:
    rounded = round(value, 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:g}"
