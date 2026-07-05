"""Helpers for threading Mark's personal metric bands into coach packets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.models.coaching import MetricBaseline


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
