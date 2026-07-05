"""Deterministic chronic sleep-pattern suggestions.

Batch 59 turns the age-norm and personal-baseline reads into small, grounded
actions when a pattern repeats across weeks. It stays read-only: no analyses row,
no migration, no verdict or delivery-rule change.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import DailyMetric, KnowledgeBase, MetricBaseline, Sleep
from src.models.profile import Profile
from src.services.age_norms import build_age_comparison
from src.services.insights import DriverCorrelation

WINDOW_DAYS = 28
MIN_OBSERVED_NIGHTS = 21
MIN_METRIC_SAMPLES = 10
MIN_DRIVER_SAMPLES = 8

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
        }


@dataclass(frozen=True)
class ChronicSuggestionResult:
    status: SuggestionStatus
    headline: str
    summary: str
    evidence_window: EvidenceWindow
    items: list[ChronicSuggestion] = field(default_factory=list)

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
        )

    flags = _age_norm_flags(sleeps, age=age, sex=sex, start=start, end=as_of)
    flags.extend(_baseline_flags(sleeps, recovery_days, baselines, start=start, end=as_of))
    chronic = [
        flag
        for flag in flags
        if flag.samples >= MIN_METRIC_SAMPLES and flag.misses >= _miss_threshold(flag.samples)
    ]
    chronic.sort(key=lambda flag: (flag.miss_ratio, flag.misses), reverse=True)

    drivers = _useful_drivers(sleep_drivers)
    suggestions = [
        _suggestion(
            flag,
            index=index,
            driver=_driver_for_flag(flag, drivers),
            protocol=sleep_protocol,
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
        return build_chronic_pattern_suggestions(
            sleeps=[_sleep_night(row) for row in sleep_rows],
            recovery_days=[_recovery_day(row) for row in metric_rows],
            baselines=await self._baselines(player.id),
            sleep_drivers=sleep_drivers,
            age=await self._profile_age(player.id),
            sex=await self._profile_sex(player.id),
            sleep_protocol=sleep_protocol,
            as_of=as_of,
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
        value = (await self._profile_section(user_id)).get("age")
        return int(value) if isinstance(value, int | float) else None

    async def _profile_sex(self, user_id: uuid.UUID) -> str | None:
        value = (await self._profile_section(user_id)).get("sex")
        return value if isinstance(value, str) else None

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


def _sleep_night(row: Sleep) -> SleepNight:
    return SleepNight(
        calendar_date=row.calendar_date,
        score=row.score,
        age_adjusted_score=row.age_adjusted_score,
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
    )


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
            if row.metric_key == "light_sleep_pct":
                continue
            grouped.setdefault(row.metric_key, []).append(
                (
                    row.tone == "warn",
                    row.value,
                    row.label,
                    f"typical {row.age_band} value {row.age_average:g}{row.unit}",
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
) -> ChronicSuggestion:
    tone: SuggestionTone = "protect" if flag.miss_ratio >= 0.7 else "watch"
    evidence = [(f"{flag.misses} of {flag.samples} measured nights missed {flag.comparator}.")]
    if flag.latest_value is not None:
        evidence.append(f"Latest value: {_format_value(flag.latest_value)}.")
    if driver and driver.summary:
        evidence.append(driver.summary)
    actions = _actions_for(flag.metric_key, driver, protocol)
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
    metric_key: str, driver: SuggestionDriver | None, protocol: Mapping[str, Any] | None
) -> list[str]:
    bedtime = _protocol_value(protocol, "bedtime", "23:15")
    seal = _protocol_value(protocol, "sealTargetTime", "22:00")
    breathing = _protocol_value(protocol, "coherenceBreathingTime", "20:00")
    snack = _protocol_value(protocol, "latestSnackTime", "21:30")

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
        actions.append(f"Make {bedtime} the latest normal lights-out target for the next week.")
        actions.append(
            "Avoid moving the wake time earlier after a short night; REM is late-night heavy."
        )
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
    return deduped


def _protocol_value(protocol: Mapping[str, Any] | None, key: str, fallback: str) -> str:
    if not protocol:
        return fallback
    value = protocol.get(key)
    return str(value) if isinstance(value, str | int | float) else fallback


def _format_value(value: float) -> str:
    rounded = round(value, 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:g}"
