"""Helpers for threading Mark's personal metric bands into coach packets."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
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
    away_days: Collection[date] = (),
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
    # Batch 369.1 (UX362-04, ST363-08b): Mark asked twice whether the holiday explained
    # the slide; the fall held without it (-7 instead of -11) and the app never said so.
    # The same halves with his days away left out, and the sentence pre-written in plain
    # figures, so the brief never quotes a median.
    without_away = _halves_without(observations, away_days, window_start, split_date, as_of)
    reason = None
    sentence = None
    if triggered and delta is not None and first_median is not None and second_median is not None:
        sentence = readiness_trend_sentence(first_median, second_median, without_away)
        # The reason is shown with the morning's other reasons: the same plain sentence.
        reason = sentence

    return {
        "metricKey": "readiness_score",
        "status": status,
        "triggered": triggered,
        "verdictImpact": "warning_only",
        "windowDays": BASELINE_TREND_WINDOW_DAYS,
        "windowStartDate": window_start.isoformat(),
        "windowEndDate": as_of.isoformat(),
        "splitDate": split_date.isoformat(),
        "usualBefore": None if first_median is None else round(first_median),
        "usualRecent": None if second_median is None else round(second_median),
        "delta": delta,
        "withoutAway": without_away,
        "sentence": sentence,
        "firstHalfSampleCount": len(first_half),
        "secondHalfSampleCount": len(second_half),
        "minimumSamplesPerHalf": READINESS_TREND_MIN_SAMPLES_PER_HALF,
        "declineThresholdPoints": READINESS_TREND_DECLINE_POINTS,
        "reason": reason,
    }


def _halves_without(
    observations: Sequence[tuple[date, int | float | None]],
    away_days: Collection[date],
    window_start: date,
    split_date: date,
    as_of: date,
) -> dict[str, Any] | None:
    """Both halves' usual with his days away left out (Batch 369.1); ``None`` if none were."""

    away = set(away_days)
    if not any(window_start <= day <= as_of for day in away):
        return None
    before_home = [
        float(v)
        for d, v in observations
        if window_start <= d < split_date and v is not None and d not in away
    ]
    recent_home = [
        float(v)
        for d, v in observations
        if split_date <= d <= as_of and v is not None and d not in away
    ]
    if not before_home or not recent_home:
        return None
    usual_before = round(float(median(before_home)))
    usual_recent = round(float(median(recent_home)))
    return {
        "usualBefore": usual_before,
        "usualRecent": usual_recent,
        "stillLower": usual_recent - usual_before <= -READINESS_TREND_DECLINE_POINTS,
        "daysAwayLeftOut": sum(1 for d in away if window_start <= d <= as_of),
    }


#: Batch 369.1 (Craig, 3 Nov): the line is said again only when his recent usual has
#: moved this many points since it was last said, or on a Monday.
READINESS_SAY_MOVE_POINTS = 3


def readiness_trend_say(
    trend: dict[str, Any], previous: Mapping[str, Any] | None, subject_date: date
) -> bool:
    """Whether the brief says the readiness line today, recording what was last said.

    The same paragraph went out on five mornings running after Mark had questioned it
    twice (UX362-04), and the first replay of the fix said it on 3 of 5 days as the
    figure drifted a point a day. It is said when the warning starts, when his recent
    usual has moved :data:`READINESS_SAY_MOVE_POINTS` since it was last said, and on
    Mondays. ``trend["saidUsualRecent"]`` carries the last figure said forward.
    """

    if not trend.get("triggered"):
        trend["saidUsualRecent"] = None
        return False
    recent = trend.get("usualRecent")
    said = (previous or {}).get("saidUsualRecent") if (previous or {}).get("triggered") else None
    say = (
        said is None
        or recent is None
        or abs(float(recent) - float(said)) >= READINESS_SAY_MOVE_POINTS
        or subject_date.weekday() == 0
    )
    trend["saidUsualRecent"] = recent if say else said
    return say


def readiness_trend_sentence(
    usual_before: float, usual_recent: float, without_away: Mapping[str, Any] | None
) -> str:
    """The brief's readiness line in plain figures (Batch 369.1; draft for Craig's sign-off)."""

    line = (
        f"Your readiness has run lower for six weeks: usually {usual_recent:.0f} lately, "
        f"against {usual_before:.0f} the six weeks before."
    )
    if without_away is None:
        return line
    if without_away["stillLower"]:
        return (
            f"{line} It still shows with your days away left out "
            f"({without_away['usualRecent']} against {without_away['usualBefore']})."
        )
    return (
        f"{line} Most of that is your days away: with them left out it is "
        f"{without_away['usualRecent']} against {without_away['usualBefore']}."
    )


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
