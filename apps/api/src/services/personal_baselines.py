"""Helpers for threading Mark's personal metric bands into coach packets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from statistics import median
from typing import Any

from src.models.coaching import MetricBaseline

BASELINE_TREND_WINDOW_DAYS = 84
READINESS_TREND_MIN_SAMPLES_PER_HALF = 21
READINESS_TREND_DECLINE_POINTS = 5.0
SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR = 60.0


def baseline_lookup(
    baselines: Iterable[MetricBaseline],
) -> dict[str, MetricBaseline]:
    return {row.metric_key: row for row in baselines}


def baseline_center(row: MetricBaseline | None) -> float | None:
    if row is None:
        return None
    for value in (row.median_value, row.mean_value):
        if value is not None:
            return float(value)
    return None


def effective_readiness_floor(personal_center: float | None) -> float:
    """Keep the soft-sleep readiness gate above a fixed safety anchor."""
    if personal_center is None:
        return SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR
    return max(float(personal_center), SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR)


def readiness_baseline_trend(
    observations: Sequence[tuple[date, int | float | None]],
    *,
    as_of: date,
) -> dict[str, Any]:
    """Alarm when the two halves of the trailing 84-day readiness window decline.

    The split is calendar-based rather than sample-based so missing Garmin days
    cannot move old observations into the recent half. Half-window medians keep
    the signal resistant to one-off bad mornings; at least half of each 42-day
    half must be observed before the trend is classified.
    """
    window_start = as_of - timedelta(days=BASELINE_TREND_WINDOW_DAYS - 1)
    split_date = window_start + timedelta(days=BASELINE_TREND_WINDOW_DAYS // 2)
    first_half = [
        float(value)
        for day, value in observations
        if window_start <= day < split_date and value is not None
    ]
    second_half = [
        float(value)
        for day, value in observations
        if split_date <= day <= as_of and value is not None
    ]
    enough_data = (
        len(first_half) >= READINESS_TREND_MIN_SAMPLES_PER_HALF
        and len(second_half) >= READINESS_TREND_MIN_SAMPLES_PER_HALF
    )
    first_median = float(median(first_half)) if enough_data else None
    second_median = float(median(second_half)) if enough_data else None
    delta = (
        round(second_median - first_median, 1)
        if first_median is not None and second_median is not None
        else None
    )
    triggered = delta is not None and delta <= -READINESS_TREND_DECLINE_POINTS
    status = "declining" if triggered else ("stable" if enough_data else "insufficient_data")
    reason = None
    if triggered and delta is not None:
        reason = (
            "Readiness baseline trend warning: the recent 42-day median "
            f"({second_median:.1f}) is {abs(delta):.1f} points below the prior "
            f"42-day median ({first_median:.1f})."
        )

    return {
        "metricKey": "readiness_score",
        "status": status,
        "triggered": triggered,
        "verdictImpact": "warning_only",
        "windowDays": BASELINE_TREND_WINDOW_DAYS,
        "windowStartDate": window_start.isoformat(),
        "windowEndDate": as_of.isoformat(),
        "splitDate": split_date.isoformat(),
        "firstHalfMedian": first_median,
        "secondHalfMedian": second_median,
        "delta": delta,
        "firstHalfSampleCount": len(first_half),
        "secondHalfSampleCount": len(second_half),
        "minimumSamplesPerHalf": READINESS_TREND_MIN_SAMPLES_PER_HALF,
        "declineThresholdPoints": READINESS_TREND_DECLINE_POINTS,
        "reason": reason,
    }


def baseline_band_packet(
    baselines: Iterable[MetricBaseline],
    *,
    keys: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    rows = baseline_lookup(baselines)
    selected = rows if keys is None else {key: rows[key] for key in keys if key in rows}
    return {
        key: {
            "label": row.metric_label,
            "source": row.source,
            "sampleCount": row.sample_count,
            "lowerQuartile": row.lower_quartile_value,
            "median": row.median_value,
            "mean": row.mean_value,
            "upperQuartile": row.upper_quartile_value,
            "windowStartDate": row.window_start_date.isoformat(),
            "windowEndDate": row.window_end_date.isoformat(),
        }
        for key, row in selected.items()
    }


def metric_within_baseline_band(
    value: float | int | None,
    row: MetricBaseline | None,
    *,
    lower_is_better: bool = False,
) -> bool:
    if value is None or row is None:
        return False
    current = float(value)
    if lower_is_better:
        ceiling = row.upper_quartile_value
        return ceiling is not None and current <= float(ceiling)
    floor = row.lower_quartile_value
    return floor is not None and current >= float(floor)


def serialize_training_schedule(knowledge_base: Mapping[str, Any]) -> dict[str, Any]:
    schedule = knowledge_base.get("training_schedule")
    if isinstance(schedule, dict):
        return dict(schedule)
    training_plan = knowledge_base.get("training_plan")
    if isinstance(training_plan, dict):
        nested = training_plan.get("trainingSchedule")
        if isinstance(nested, dict):
            return dict(nested)
    return {}
