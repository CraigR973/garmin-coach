"""Deterministic morning verdict policy and its supporting transforms.

Batch 245 extracts the app's central safety decision from the packet/model
orchestrator. This module is deliberately model-free and database-free: callers
supply already-loaded rows and receive a deterministic packet.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from statistics import median, pstdev
from typing import Any

from fastapi import HTTPException

from src.models.coaching import DailyMetric, ManualEntry, MetricBaseline, PlannedWorkout, Sleep
from src.services.breathwork_brief import BreathworkBriefResult
from src.services.hrv_recalibration import detect_hrv_recalibration, is_band_artifact
from src.services.personal_baselines import (
    SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,
    baseline_center,
    effective_readiness_floor,
    metric_within_baseline_band,
)
from src.services.provenance import (
    FIGURE_HRV_ACUTE_FLOOR,
    Provenance,
    provenance_packet,
)
from src.services.provenance import (
    threshold as provenance_threshold,
)
from src.services.provenance import (
    window as provenance_window,
)
from src.services.sleep_history import SPO2_HRV_RELIABLE_FROM
from src.services.symptom_check import (
    EASING_CHEST_QUESTION,
    EASY_RIDING_PLAN_LINE,
    SYMPTOM_FLOORS,
    SYMPTOMS_CHEST_HEART,
    latest_symptom_answer,
    more_severe_symptom,
    reports_symptoms,
    symptom_signal,
)
from src.services.verdict_grading import THRESHOLDS, ride_transform
from src.services.verdict_scaling import (
    AMBER_POWER_CAP_PCT,
    companion_session_present,
    ir_has_vo2,
    summarize_verdict_adjustment,
)
from src.services.workout_categories import (
    DAY_CATEGORY_FLEXIBILITY,
    DAY_CATEGORY_WALK,
    DAY_CATEGORY_WEIGHTS,
    category_for_workout_type,
    is_bike_workout_type,
)
from src.services.workout_delivery import build_structured_workout_ir

# Batch 167 (#248): load can only harden the deterministic light.
ACWR_AMBER_CAP_THRESHOLD = 1.5
RECOVERY_TIME_AMBER_CAP_MIN = 24 * 60
# A Low-readiness exception needs affirmative balanced-load evidence.
ACWR_LOAD_DRIVEN_MAX = 1.3

# Batch 246: acute physiology is compared with Mark's own history, but it stays
# conservative about sparse history and wrist Pulse Ox. Garmin explicitly calls
# Pulse Ox an estimate rather than a medical measurement, so a noisy nadir is
# never enough by itself to surface a medical escalation.
ACUTE_BASELINE_WINDOW_DAYS = 84
ACUTE_BASELINE_MIN_SAMPLES = 21
RESTING_HR_ABSOLUTE_DELTA_BPM = 7.0
# Batch 305: the rise that can take a low HRV night off the bike with it. It is the
# graded verdict's own mild line, so the two can never disagree about what "raised"
# means; two mornings above his usual range is no longer enough on its own.
RESTING_HR_CORROBORATION_DELTA_BPM = THRESHOLDS["resting_hr_rise_mild_bpm"].value
HRV_ACUTE_DROP_STDDEVS = 1.5
# Batch 294: the 1.5 SD floor caps the day at Amber; only an illness-grade drop takes
# Mark off the bike on its own. At 1.5 SD the rail fired on 6 of his 75 eligible
# mornings (8%), three of them by under 1 ms; at 2.5 SD or 30% under his median it
# fires once, on 16 Jul 2026 (33 ms against 48). Batch 240's finding, which the rail
# answered, was a 60-70% overnight collapse, not a 17% dip.
HRV_ILLNESS_DROP_STDDEVS = 2.5
HRV_ILLNESS_DROP_FRACTION = 0.30
AVERAGE_SPO2_ALERT_THRESHOLD_PCT = 92.0
SPO2_NADIR_ALERT_THRESHOLD_PCT = 88.0
SPO2_NADIR_WINDOW_DAYS = 3
SPO2_NADIR_MIN_NIGHTS = 2
RESPIRATION_SUSTAINED_NIGHTS = 2

MEDICAL_BOUNDARY_STANDING_LINE = (
    "This read comes from your watch and your room sensors. It can't see how you "
    "actually feel — if those two disagree, trust yourself."
)
INSUFFICIENT_DATA_MESSAGE = "Insufficient data to judge today."

# Batch 269: a graded response to Garmin's HRV signal. The same-day Red needs last
# night's own reading under the floor, and a morning whose only mark is Garmin's
# weekly signal holds the session instead of cutting it. The chat block and the
# recent-mornings surfaces quote the Red reason, so its wording is unchanged.
HRV_RED_REASON = "HRV is below baseline and marked low/unbalanced."
HRV_EASE_REASON = "HRV is not cleanly in range."
HRV_HOLD_PLAN_LINE = "Hold the prescribed targets rather than pushing past the top of each zone."
HRV_CONCERN_OVERNIGHT_BELOW_FLOOR = "overnight_below_floor"
HRV_CONCERN_FLOOR_MOVED = "floor_moved"
HRV_CONCERN_WEEKLY_BELOW_FLOOR = "weekly_average_below_floor"
HRV_CONCERN_GARMIN_STATUS = "garmin_status"


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _todays_bike_workout(planned_workouts: Sequence[PlannedWorkout]) -> PlannedWorkout | None:
    for workout in planned_workouts:
        if workout.status in {"completed", "skipped"}:
            continue
        if is_bike_workout_type(workout.workout_type):
            return workout
    return None


def _verdict_adjustment_packet(
    status: str, planned_workouts: Sequence[PlannedWorkout]
) -> dict[str, Any] | None:
    """The deterministic Amber/Red adjustment for today's ride, for the packet.

    Batch 173.3: built from the *same* ``adjust_ir_for_verdict`` transform the
    delivery rail and the interval editor use, so the narrative and brief-chat can
    quote the app's own duration/%FTP figures. Explanatory only — returns ``None``
    on Green, a rest/no-ride day, or a malformed ride, and never influences the
    verdict or the numbers.

    Batch 215.5: the day's other sessions are resolved here, from the planned
    workouts already in hand, so the figure the brief quotes carries the same
    combined-load gate the delivery rail applies.
    """
    if status not in {"Amber", "Red"}:
        return None
    ride = _todays_bike_workout(planned_workouts)
    if ride is None:
        return None
    try:
        base_ir = build_structured_workout_ir(ride)
    except HTTPException:
        return None
    companion = companion_session_present(
        workout.status for workout in planned_workouts if workout.id != ride.id
    )
    summary = summarize_verdict_adjustment(base_ir, status, companion_session=companion)
    if summary is None:
        return None
    return {**summary, "plannedWorkoutId": str(ride.id)}


def _training_load_cap(
    training_load: Mapping[str, Any] | None,
) -> dict[str, Any]:
    signal = training_load or {}
    acwr = _coerce_float(signal.get("acuteChronicLoadRatio"))
    recovery_time_min = _coerce_int(signal.get("recoveryTimeMin"))
    sources: list[str] = []
    reasons: list[str] = []

    if acwr is not None and acwr >= ACWR_AMBER_CAP_THRESHOLD:
        sources.append("acute_chronic_load_ratio")
        reasons.append(
            "Training load sets an Amber ceiling: acute:chronic load ratio "
            f"{acwr:.2f} is at or above {ACWR_AMBER_CAP_THRESHOLD:.2f}."
        )
    if recovery_time_min is not None and recovery_time_min > RECOVERY_TIME_AMBER_CAP_MIN:
        sources.append("recovery_time")
        recovery_hours = recovery_time_min / 60
        reasons.append(
            "Training load sets an Amber ceiling: Garmin recovery time "
            f"{recovery_hours:.1f} hours is beyond 24 hours."
        )

    return {
        "triggered": bool(sources),
        "applied": False,
        "sources": sources,
        "acuteChronicLoadRatio": acwr,
        "recoveryTimeMin": recovery_time_min,
        "thresholds": {
            "acuteChronicLoadRatio": ACWR_AMBER_CAP_THRESHOLD,
            "recoveryTimeMinExclusive": RECOVERY_TIME_AMBER_CAP_MIN,
        },
        "reasons": reasons,
    }


def _load_driven_eligibility(
    training_load: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Whether load is affirmative evidence for relaxing a Low readiness.

    The exception is intentionally narrower than the one-way Amber cap: ACWR
    must be present and inside the app's balanced range, while a recovery clock
    beyond the cap boundary vetoes the escape. Missing evidence is unknown.
    """
    signal = training_load or {}
    acwr = _coerce_float(signal.get("acuteChronicLoadRatio"))
    recovery_time_min = _coerce_int(signal.get("recoveryTimeMin"))
    acwr_benign = acwr is not None and acwr <= ACWR_LOAD_DRIVEN_MAX
    recovery_time_benign = (
        recovery_time_min is None or recovery_time_min <= RECOVERY_TIME_AMBER_CAP_MIN
    )
    return {
        "eligible": acwr_benign and recovery_time_benign,
        "acuteChronicLoadRatio": acwr,
        "recoveryTimeMin": recovery_time_min,
        "acuteChronicLoadRatioBenign": acwr_benign,
        "recoveryTimeBenign": recovery_time_benign,
        "thresholds": {
            "acuteChronicLoadRatioMaxInclusive": ACWR_LOAD_DRIVEN_MAX,
            "recoveryTimeMinMaxInclusive": RECOVERY_TIME_AMBER_CAP_MIN,
        },
    }


def _has_hrv_measurement(daily_metric: DailyMetric | None, sleep: Sleep | None) -> bool:
    return any(
        value is not None
        for value in (
            daily_metric.hrv_weekly_avg_ms if daily_metric else None,
            daily_metric.hrv_last_night_avg_ms if daily_metric else None,
            sleep.avg_overnight_hrv_ms if sleep else None,
        )
    )


def _positive_hrv_evidence(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    hrv_status: str | None,
    hrv_below_baseline: bool,
) -> bool:
    return (
        _has_hrv_measurement(daily_metric, sleep)
        and not hrv_below_baseline
        and hrv_status in {"balanced", "stable", "optimal", "normal"}
    )


def _readiness_score_ok(
    daily_metric: DailyMetric | None,
    *,
    readiness_floor: float,
) -> bool:
    if daily_metric is None:
        return False
    readiness_level = _lower(daily_metric.readiness_level)
    readiness_score = daily_metric.readiness_score
    return readiness_level not in {"low", "poor"} and (
        readiness_score is not None and readiness_score >= readiness_floor
    )


def _resting_hr_elevated(
    daily_metric: DailyMetric | None,
    baseline: MetricBaseline | None,
) -> bool:
    resting_hr = daily_metric.resting_heart_rate_bpm if daily_metric else None
    ceiling = baseline.upper_quartile_value if baseline else None
    return resting_hr is not None and ceiling is not None and float(resting_hr) > float(ceiling)


def _baseline_ready(row: MetricBaseline | None) -> bool:
    return row is not None and row.sample_count >= ACUTE_BASELINE_MIN_SAMPLES


def _number(value: float | int | None) -> str:
    if value is None:
        return "unavailable"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _baseline_dates(row: MetricBaseline | None) -> tuple[str | None, str | None]:
    if row is None:
        return None, None
    return row.window_start_date.isoformat(), row.window_end_date.isoformat()


def _prior_daily_metric(
    recent_daily_metrics: Sequence[DailyMetric],
    *,
    subject_date: date,
) -> DailyMetric | None:
    prior_date = subject_date - timedelta(days=1)
    return next((row for row in recent_daily_metrics if row.calendar_date == prior_date), None)


# -- the acute notices' words ------------------------------------------------------
#
# The ladder's words are Batch 293's and 294's, signed off by Craig on Mark's behalf on
# 27 and 28 Sep 2026. Batch 298 gives the graded verdict its own closing sentence for a
# signal that is one thing a little off, signed off on 1 Oct 2026
# (docs/drafts/2026-10-01-batch-298-wording.md). The rails always write the ladder's
# words, which the rollback restores byte for byte; ``graded_acute_physiology`` rewrites
# a graded packet's copy.

LADDER_MILD_SIGNAL_CLOSING = (
    "On its own it caps today at Amber: an eased session, not a day off the bike."
)
GRADED_MILD_SIGNAL_CLOSING = (
    "On its own it is one thing a little off, and today's call already counts it: not a "
    "day off the bike."
)
LADDER_EITHER_ALONE_CLAUSE = "Either on its own would only cap the day;"
GRADED_EITHER_ALONE_CLAUSE = "Either on its own would only be a little off;"
LADDER_BELOW_FLOOR = "Below it the day is capped at Amber"
GRADED_BELOW_FLOOR = "Below it last night counts as one thing a little off in the graded verdict"


def _rhr_mild_notice(current: Any, median_value: Any, closing: str) -> str:
    """Two mornings a little above his usual range (Batch 293)."""
    return (
        f"Your resting heart rate is {current} this morning against a usual "
        f"{_number(median_value)} — a little above your usual range, as it was "
        "yesterday. Small rises like this usually come from travel, a short night, "
        f"a busy week or a hard day before. {closing}"
    )


def _hrv_mild_notice(current: Any, median_value: Any, closing: str) -> str:
    """A low night under his acute floor, on its own (Batch 294)."""
    return (
        f"Your overnight HRV is {current} ms this morning against a usual "
        f"{_number(median_value)} ms — lower than most nights for you. Dips like "
        "this usually come from a short night, a drink, a busy week or a hard day "
        f"before. {closing}"
    )


def _hrv_corroborated_notice(
    current: Any, median_value: Any, second_sign: str, either_alone: str
) -> str:
    """A low night with a second sign, which rests the bike (Batch 294)."""
    return (
        f"Your overnight HRV is {current} ms this morning against a usual "
        f"{_number(median_value)} ms, and {second_sign}. {either_alone} together they "
        "are worth respecting. Take today off the bike. If you feel unwell, rest until "
        "it settles, and see your GP if it doesn't."
    )


def _hrv_floor_rule(below_floor: str) -> str:
    """The acute HRV floor's rule, for the model and the working (Batches 273, 294)."""
    return (
        f"his own median over the window, minus "
        f"{HRV_ACUTE_DROP_STDDEVS} standard deviations of it — a personal "
        f"floor, not a population band, and not Garmin's. {below_floor}; it rests the "
        f"bike only at {HRV_ILLNESS_DROP_STDDEVS} standard deviations or "
        f"{HRV_ILLNESS_DROP_FRACTION:.0%} under the median, or below the "
        "floor alongside a raised resting heart rate or a reported symptom"
    )


def _rhr_rail(
    daily_metric: DailyMetric | None,
    baseline: MetricBaseline | None,
    recent_daily_metrics: Sequence[DailyMetric],
) -> dict[str, Any]:
    current = daily_metric.resting_heart_rate_bpm if daily_metric else None
    median_value = baseline.median_value if baseline else None
    upper_quartile = baseline.upper_quartile_value if baseline else None
    enough_history = _baseline_ready(baseline)
    delta = (
        float(current) - float(median_value)
        if current is not None and median_value is not None
        else None
    )
    absolute_delta = bool(
        enough_history and delta is not None and delta >= RESTING_HR_ABSOLUTE_DELTA_BPM
    )
    prior = (
        _prior_daily_metric(recent_daily_metrics, subject_date=daily_metric.calendar_date)
        if daily_metric is not None
        else None
    )
    prior_value = prior.resting_heart_rate_bpm if prior is not None else None
    consecutive_q3 = bool(
        enough_history
        and current is not None
        and prior_value is not None
        and upper_quartile is not None
        and float(current) > float(upper_quartile)
        and float(prior_value) > float(upper_quartile)
    )
    triggered = absolute_delta or consecutive_q3
    trigger = "absolute_delta" if absolute_delta else "consecutive_q3" if consecutive_q3 else None
    reason = None
    escalation = None
    if triggered and current is not None and median_value is not None:
        # Batch 293: the two paths are graded. Decision #318 asked for proportionate
        # copy on the milder one, but only its opening sentence got it; both shared an
        # illness list, "take today off the bike" and "see your GP". On 27 Sep 2026,
        # a 47 after a 46 against a usual 44, Mark accepted the cap and objected to
        # the illness talk. Only a jump of RESTING_HR_ABSOLUTE_DELTA_BPM or more now
        # rests the bike, and its GP line is conditional on feeling unwell.
        # Mark-facing wording, signed off by Craig on Mark's behalf on 27 Sep 2026.
        if absolute_delta:
            reason = (
                f"Resting heart rate sets an Amber ceiling: {current} bpm is "
                f"{_number(delta)} bpm above the personal median of {_number(median_value)}."
            )
            escalation = (
                f"Your resting heart rate is {current} this morning against a usual "
                f"{_number(median_value)} — a rise of {_number(delta)} bpm. A jump that size "
                "can come from a short night, alcohol, dehydration or a hard day, and "
                "sometimes from your body fighting something off. Take today off the bike. "
                "If you also feel unwell, rest until it settles, and see your GP if it doesn't."
            )
        else:
            reason = (
                "Resting heart rate sets an Amber ceiling: it has been above the "
                f"personal upper quartile of {_number(upper_quartile)} bpm for two mornings."
            )
            escalation = _rhr_mild_notice(current, median_value, LADDER_MILD_SIGNAL_CLOSING)
    return {
        "triggered": triggered,
        "verdictImpact": "amber_cap",
        # Batch 293: only the large jump takes Mark off the bike.
        "requiresBikeRest": absolute_delta,
        "trigger": trigger,
        "currentBpm": current,
        "priorBpm": prior_value,
        "baselineMedianBpm": median_value,
        "baselineUpperQuartileBpm": upper_quartile,
        "baselineSampleCount": baseline.sample_count if baseline else 0,
        "baselineWindowStartDate": _baseline_dates(baseline)[0],
        "baselineWindowEndDate": _baseline_dates(baseline)[1],
        "deltaFromMedianBpm": round(delta, 1) if delta is not None else None,
        "thresholds": {
            "absoluteDeltaBpmInclusive": RESTING_HR_ABSOLUTE_DELTA_BPM,
            "consecutiveMorningsAboveUpperQuartile": 2,
            "minimumBaselineSamples": ACUTE_BASELINE_MIN_SAMPLES,
        },
        "reason": reason,
        "escalation": escalation,
    }


def _rhr_corroborates(rhr: Mapping[str, Any]) -> bool:
    """A resting-heart-rate rise big enough to take a low HRV night off the bike.

    Batch 305: two mornings above his upper quartile is a real but small signal (on
    27 Sep, 47 after 46 against a usual 44), so it no longer corroborates on its own; a
    rise of :data:`RESTING_HR_CORROBORATION_DELTA_BPM` over his median does, once his
    baseline is known, even on a single morning. Replayed on 3 Oct 2026, no morning lost
    its floor and one gained it: 1 Aug, already Red, is off the bike rather than a
    recovery spin.
    """
    delta = rhr.get("deltaFromMedianBpm")
    enough_history = int(rhr.get("baselineSampleCount") or 0) >= ACUTE_BASELINE_MIN_SAMPLES
    return (
        enough_history
        and isinstance(delta, int | float)
        and float(delta) >= RESTING_HR_CORROBORATION_DELTA_BPM
    )


def _hrv_corroboration_clause(corroborated_by: Sequence[str], symptom_answer: str | None) -> str:
    """How the off-the-bike HRV notice names the second sign (Batch 294).

    A reported symptom is named before a resting-heart-rate rise when both came with
    the dip, because it is the one Mark gave the app himself.
    """
    floor = SYMPTOM_FLOORS.get(symptom_answer) if symptom_answer is not None else None
    if "symptom_answer" in corroborated_by and floor is not None:
        return floor.corroboration
    return "your resting heart rate is up as well"


def _hrv_rail(
    daily_metric: DailyMetric | None,
    recent_daily_metrics: Sequence[DailyMetric],
    *,
    corroborated_by: Sequence[str] = (),
    symptom_answer: str | None = None,
) -> dict[str, Any]:
    """Last night's HRV against Mark's own 84-day history (Batch 246, graded in 294).

    Below his median minus 1.5 SD the day is capped at Amber. It rests the bike only
    at an illness-grade drop (at least 2.5 SD or 30% under the median), or when the
    capped drop comes with a second sign: the resting-heart-rate rail, or a symptom
    he reported. ``corroborated_by`` names those signs; the caller decides them.
    """
    current = daily_metric.hrv_last_night_avg_ms if daily_metric else None
    subject_date = daily_metric.calendar_date if daily_metric else None
    window_start = (
        subject_date - timedelta(days=ACUTE_BASELINE_WINDOW_DAYS)
        if subject_date is not None
        else None
    )
    observations = sorted(
        [
            (row.calendar_date, float(row.hrv_last_night_avg_ms))
            for row in recent_daily_metrics
            if row.hrv_last_night_avg_ms is not None
            and row.calendar_date >= SPO2_HRV_RELIABLE_FROM
            and (window_start is None or row.calendar_date >= window_start)
            and (subject_date is None or row.calendar_date < subject_date)
        ],
        key=lambda observation: observation[0],
    )
    values = [value for _, value in observations]
    enough_history = len(values) >= ACUTE_BASELINE_MIN_SAMPLES
    median_value = float(median(values)) if enough_history else None
    stddev_value = float(pstdev(values)) if enough_history else None
    threshold = (
        median_value - HRV_ACUTE_DROP_STDDEVS * stddev_value
        if median_value is not None and stddev_value is not None
        else None
    )
    illness_line = (
        max(
            median_value - HRV_ILLNESS_DROP_STDDEVS * stddev_value,
            median_value * (1 - HRV_ILLNESS_DROP_FRACTION),
        )
        if median_value is not None and stddev_value is not None
        else None
    )
    illness_grade = bool(
        current is not None and illness_line is not None and float(current) <= illness_line
    )
    # An illness-grade drop always caps too, even when a wide spread puts the 30% line
    # above the 1.5 SD floor.
    triggered = illness_grade or bool(
        current is not None and threshold is not None and float(current) < threshold
    )
    corroboration = list(corroborated_by) if triggered else []
    requires_bike_rest = illness_grade or bool(triggered and corroboration)
    reason = None
    escalation = None
    if triggered and current is not None and median_value is not None:
        history_window = (
            f" from {observations[0][0].isoformat()} to {observations[-1][0].isoformat()}"
            if observations
            else ""
        )
        reason = (
            f"Overnight HRV sets an Amber ceiling: {current} ms is below the acute "
            f"personal floor of {_number(threshold)} ms."
        )
        # Mark-facing wording, signed off by Craig on Mark's behalf on 28 Sep 2026
        # (docs/drafts/2026-09-28-batch-294-wording.md). The illness-grade line is the
        # one this rail has always written.
        if illness_grade:
            escalation = (
                f"Your overnight HRV is {current} ms this morning against a usual "
                f"{_number(median_value)} ms{history_window} — a drop that size in a single "
                "night is unusual "
                "for you. It usually means one of: an infection starting, a heavy drink, a "
                "badly broken night, or real stress carried into sleep. Training hard through "
                "it tends to deepen it. Take today off the bike, and if you feel unwell "
                "alongside it, see your GP rather than just resting."
            )
        elif requires_bike_rest:
            escalation = _hrv_corroborated_notice(
                current,
                median_value,
                _hrv_corroboration_clause(corroboration, symptom_answer),
                LADDER_EITHER_ALONE_CLAUSE,
            )
        else:
            escalation = _hrv_mild_notice(current, median_value, LADDER_MILD_SIGNAL_CLOSING)
    return {
        "triggered": triggered,
        "verdictImpact": "amber_cap",
        "requiresBikeRest": requires_bike_rest,
        "illnessGrade": illness_grade,
        "corroboratedBy": corroboration,
        "currentMs": current,
        "baselineMedianMs": median_value,
        "baselineStddevMs": round(stddev_value, 2) if stddev_value is not None else None,
        "baselineSampleCount": len(values),
        "baselineWindowStartDate": observations[0][0].isoformat() if observations else None,
        "baselineWindowEndDate": observations[-1][0].isoformat() if observations else None,
        "acuteFloorMs": round(threshold, 2) if threshold is not None else None,
        "illnessLineMs": round(illness_line, 2) if illness_line is not None else None,
        "thresholds": {
            "stddevsBelowMedianExclusive": HRV_ACUTE_DROP_STDDEVS,
            "illnessStddevsBelowMedianInclusive": HRV_ILLNESS_DROP_STDDEVS,
            "illnessFractionBelowMedianInclusive": HRV_ILLNESS_DROP_FRACTION,
            "windowDays": ACUTE_BASELINE_WINDOW_DAYS,
            "minimumBaselineSamples": ACUTE_BASELINE_MIN_SAMPLES,
            "reliabilityStartDate": SPO2_HRV_RELIABLE_FROM.isoformat(),
        },
        "reason": reason,
        "escalation": escalation,
        # Batch 273: this rail has published its own working since Batch 122 -
        # median, spread, sample count, window, and the thresholds block. It was
        # provenance without a shape or a surface. Adapt it into the common one
        # rather than recomputing it, so the panel and the rail cannot disagree.
        "provenance": provenance_packet(
            [
                Provenance(
                    figure=FIGURE_HRV_ACUTE_FLOOR,
                    label="acute personal HRV floor",
                    value=round(threshold, 2) if threshold is not None else None,
                    units="ms",
                    rule=_hrv_floor_rule(LADDER_BELOW_FLOOR),
                    window=provenance_window(
                        kind="rolling_days",
                        start=observations[0][0] if observations else None,
                        end=observations[-1][0] if observations else None,
                        label=(
                            f"the {ACUTE_BASELINE_WINDOW_DAYS} days before this morning, "
                            f"excluding it, and nothing before "
                            f"{SPO2_HRV_RELIABLE_FROM.isoformat()} when the readings "
                            "were not reliable"
                        ),
                    ),
                    sources={
                        "table": "daily_metrics.hrv_last_night_avg_ms",
                        # Batch 273.2: the panel states the window and the multiplier
                        # from the packet rather than hardcoding the rail's constants.
                        "windowDays": ACUTE_BASELINE_WINDOW_DAYS,
                        "stddevsBelowMedian": HRV_ACUTE_DROP_STDDEVS,
                        # Batch 294: the off-the-bike line, stated so the panel can
                        # word it without copying the constants.
                        "illnessStddevsBelowMedian": HRV_ILLNESS_DROP_STDDEVS,
                        "illnessFractionBelowMedian": HRV_ILLNESS_DROP_FRACTION,
                        "illnessLineMs": (
                            round(illness_line, 2) if illness_line is not None else None
                        ),
                        "nightsUsed": len(values),
                        "minimumNightsRequired": ACUTE_BASELINE_MIN_SAMPLES,
                        "medianMs": median_value,
                        "stddevMs": round(stddev_value, 2) if stddev_value is not None else None,
                        "enoughHistory": enough_history,
                    },
                    threshold=provenance_threshold(
                        name="this morning's reading against the floor",
                        compared_against=current,
                        units="ms",
                        source="daily_metrics.hrv_last_night_avg_ms for this morning",
                    ),
                )
            ]
        ),
    }


def _oxygen_respiration_rail(
    sleep: Sleep | None,
    baselines: Mapping[str, MetricBaseline],
    recent_sleeps: Sequence[Sleep],
) -> dict[str, Any]:
    average_spo2 = sleep.average_spo2_pct if sleep else None
    nadir_spo2 = sleep.lowest_spo2_pct if sleep else None
    respiration = sleep.average_respiration if sleep else None
    spo2_baseline = baselines.get("average_spo2_pct")
    respiration_baseline = baselines.get("average_respiration")
    respiration_q3 = respiration_baseline.upper_quartile_value if respiration_baseline else None
    average_low = bool(
        average_spo2 is not None and float(average_spo2) < AVERAGE_SPO2_ALERT_THRESHOLD_PCT
    )

    subject_date = sleep.calendar_date if sleep else None
    window_start = (
        subject_date - timedelta(days=SPO2_NADIR_WINDOW_DAYS - 1)
        if subject_date is not None
        else None
    )
    window_rows = [
        row
        for row in [*recent_sleeps, *([sleep] if sleep is not None else [])]
        if row.calendar_date >= SPO2_HRV_RELIABLE_FROM
        and (window_start is None or row.calendar_date >= window_start)
        and (subject_date is None or row.calendar_date <= subject_date)
    ]
    # One row per calendar date is guaranteed by the table, but sorting makes the
    # rolling evidence and rendered window deterministic for direct unit callers.
    window_rows.sort(key=lambda row: row.calendar_date)
    nadir_nights = [
        row
        for row in window_rows
        if row.lowest_spo2_pct is not None
        and float(row.lowest_spo2_pct) < SPO2_NADIR_ALERT_THRESHOLD_PCT
    ]
    nadir_cluster = len(nadir_nights) >= SPO2_NADIR_MIN_NIGHTS
    prior_sleep = (
        next(
            (
                row
                for row in recent_sleeps
                if subject_date is not None
                and row.calendar_date == subject_date - timedelta(days=1)
            ),
            None,
        )
        if sleep is not None
        else None
    )
    prior_respiration = prior_sleep.average_respiration if prior_sleep else None
    respiration_sustained = bool(
        _baseline_ready(respiration_baseline)
        and respiration_q3 is not None
        and respiration is not None
        and prior_respiration is not None
        and float(respiration) > float(respiration_q3)
        and float(prior_respiration) > float(respiration_q3)
    )
    corroborated_cluster = nadir_cluster and respiration_sustained
    triggered = average_low or corroborated_cluster
    trigger = (
        "low_average_spo2"
        if average_low
        else "nadir_cluster_with_respiration"
        if triggered
        else None
    )
    escalation = None
    reason = None
    if triggered:
        spo2_median = spo2_baseline.median_value if spo2_baseline else None
        respiration_median = respiration_baseline.median_value if respiration_baseline else None
        spo2_window_start, spo2_window_end = _baseline_dates(spo2_baseline)
        respiration_window_start, respiration_window_end = _baseline_dates(respiration_baseline)
        spo2_window = (
            f" from {spo2_window_start} to {spo2_window_end}"
            if spo2_window_start is not None and spo2_window_end is not None
            else ""
        )
        respiration_window = (
            f" from {respiration_window_start} to {respiration_window_end}"
            if respiration_window_start is not None and respiration_window_end is not None
            else ""
        )
        if average_low:
            opening = (
                "Your watch estimated overnight oxygen saturation at an average of "
                f"{_number(average_spo2)}% last night against a usual "
                f"{_number(spo2_median)}%{spo2_window}, and your breathing rate was "
                f"{_number(respiration)} against a usual {_number(respiration_median)}"
                f"{respiration_window}."
            )
            reason = (
                "Overnight oxygen surveillance triggered: average wrist SpO₂ "
                f"{_number(average_spo2)}% is below {AVERAGE_SPO2_ALERT_THRESHOLD_PCT:.0f}%."
            )
        else:
            opening = (
                f"Your watch recorded an oxygen nadir of {_number(nadir_spo2)}% last night, "
                f"below {SPO2_NADIR_ALERT_THRESHOLD_PCT:.0f}% on {len(nadir_nights)} of the "
                f"last {SPO2_NADIR_WINDOW_DAYS} nights. Its usual overnight average is "
                f"{_number(spo2_median)}%{spo2_window}, and your breathing rate has stayed "
                f"above its usual upper quartile of {_number(respiration_q3)}"
                f"{respiration_window} for two nights."
            )
            reason = (
                "Overnight oxygen/respiration surveillance triggered: repeated low wrist "
                "SpO₂ nadirs are corroborated by sustained elevated respiration."
            )
        escalation = (
            f"{opening} Sustained low overnight oxygen has causes worth checking properly — "
            "a chest infection, or disrupted breathing during sleep. This one isn't "
            "something training or rest changes. Mention this to your GP if it happens again."
        )
    return {
        "triggered": triggered,
        "verdictImpact": "surveillance_only",
        "trigger": trigger,
        "averageSpo2Pct": average_spo2,
        "lowestSpo2Pct": nadir_spo2,
        "averageRespiration": respiration,
        "priorAverageRespiration": prior_respiration,
        "spo2BaselineMedianPct": spo2_baseline.median_value if spo2_baseline else None,
        "spo2BaselineSampleCount": spo2_baseline.sample_count if spo2_baseline else 0,
        "spo2BaselineWindowStartDate": _baseline_dates(spo2_baseline)[0],
        "spo2BaselineWindowEndDate": _baseline_dates(spo2_baseline)[1],
        "respirationBaselineMedian": (
            respiration_baseline.median_value if respiration_baseline else None
        ),
        "respirationBaselineUpperQuartile": respiration_q3,
        "respirationBaselineSampleCount": (
            respiration_baseline.sample_count if respiration_baseline else 0
        ),
        "respirationBaselineWindowStartDate": _baseline_dates(respiration_baseline)[0],
        "respirationBaselineWindowEndDate": _baseline_dates(respiration_baseline)[1],
        "nadirNightsInWindow": len(nadir_nights),
        "respirationSustained": respiration_sustained,
        "thresholds": {
            "averageSpo2PctExclusive": AVERAGE_SPO2_ALERT_THRESHOLD_PCT,
            "nadirSpo2PctExclusive": SPO2_NADIR_ALERT_THRESHOLD_PCT,
            "nadirWindowDays": SPO2_NADIR_WINDOW_DAYS,
            "nadirMinimumNights": SPO2_NADIR_MIN_NIGHTS,
            "respirationConsecutiveNightsAboveUpperQuartile": RESPIRATION_SUSTAINED_NIGHTS,
            "minimumBaselineSamples": ACUTE_BASELINE_MIN_SAMPLES,
            "reliabilityStartDate": SPO2_HRV_RELIABLE_FROM.isoformat(),
        },
        "reason": reason,
        "escalation": escalation,
    }


def _escalation_level(signal: Mapping[str, Any]) -> str:
    """How serious a notice is, which sets the heading the app shows (Batch 293).

    ``rest`` takes Mark off the bike; ``watch`` is surveillance that changes no
    training; ``ease`` explains an Amber cap in plain words.
    """
    if signal.get("requiresBikeRest") is True:
        return "rest"
    if signal.get("verdictImpact") == "surveillance_only":
        return "watch"
    return "ease"


def _acute_physiology_rail(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    baselines: Mapping[str, MetricBaseline],
    recent_daily_metrics: Sequence[DailyMetric],
    recent_sleeps: Sequence[Sleep],
    symptom_answer: str | None = None,
    symptom_source: str | None = None,
    symptom_words: str | None = None,
    symptom_easing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # Batch 294: the symptom answer is a medical floor, and a second sign for the HRV
    # dip. It leads the notices because it is the one Mark gave the app himself.
    # Batch 303: ``symptom_easing`` is what follows a symptom on a morning with no
    # floor of its own; a floor set today drops it.
    symptoms = symptom_signal(symptom_answer, easing=symptom_easing)
    # Batch 297: where the answer came from — his tap, or his note read by the reader —
    # and, for a note, his words.
    symptoms["source"] = symptom_source if symptom_answer is not None else None
    symptoms["words"] = symptom_words if symptom_source == "notes" else None
    rhr = _rhr_rail(
        daily_metric,
        baselines.get("resting_heart_rate_bpm"),
        recent_daily_metrics,
    )
    hrv = _hrv_rail(
        daily_metric,
        recent_daily_metrics,
        corroborated_by=[
            name
            for name, present in (
                ("resting_heart_rate", _rhr_corroborates(rhr)),
                ("symptom_answer", reports_symptoms(symptom_answer)),
            )
            if present
        ],
        symptom_answer=symptom_answer,
    )
    oxygen_respiration = _oxygen_respiration_rail(sleep, baselines, recent_sleeps)
    missing_rows = [
        name for name, row in (("daily_metric", daily_metric), ("sleep", sleep)) if row is None
    ]
    data_sufficiency = {
        "status": "insufficient_data" if missing_rows else "sufficient",
        "message": INSUFFICIENT_DATA_MESSAGE if missing_rows else None,
        "missingRows": missing_rows,
    }
    signals = (
        ("symptoms", symptoms),
        ("resting_heart_rate", rhr),
        ("overnight_hrv", hrv),
        ("oxygen_respiration", oxygen_respiration),
    )
    triggered_signals = [name for name, signal in signals if signal["triggered"]]
    escalations = [
        {"kind": name, "level": _escalation_level(signal), "message": signal["escalation"]}
        for name, signal in signals
        if signal["triggered"] and isinstance(signal["escalation"], str)
    ]
    # Batch 303: an easy day back after a fever carries its own notice, first, in the
    # place the fever's notice stood. Nothing sets a floor today, so the rail above
    # wrote none. A chest question has no notice: its card on Home says it.
    easing = symptoms.get("easing")
    if isinstance(easing, Mapping) and isinstance(easing.get("notice"), str):
        escalations.insert(0, {"kind": "symptoms", "level": "ease", "message": easing["notice"]})
    return {
        "status": (
            "triggered" if triggered_signals else "insufficient_data" if missing_rows else "clear"
        ),
        "standingLine": MEDICAL_BOUNDARY_STANDING_LINE,
        "dataSufficiency": data_sufficiency,
        "triggeredSignals": triggered_signals,
        "requiresBikeRest": bool(
            symptoms["requiresBikeRest"] or rhr["requiresBikeRest"] or hrv["requiresBikeRest"]
        ),
        # Batch 294: no training of any kind — every session type, not only the bike.
        "requiresTrainingRest": bool(symptoms["requiresTrainingRest"]),
        "symptoms": symptoms,
        "restingHeartRate": rhr,
        "overnightHrv": hrv,
        "oxygenRespiration": oxygen_respiration,
        "escalations": escalations,
    }


def _sleep_credit_ceiling(
    *,
    sleep: Sleep | None,
    age_adjusted_sleep_score: int | None,
    positive_hrv_evidence: bool,
    resting_hr_in_band: bool,
    readiness_ok: bool,
    positive_subjective_evidence: bool,
) -> dict[str, Any]:
    raw_sleep_score = sleep.score if sleep is not None else None
    crossed_red = (
        raw_sleep_score is not None
        and raw_sleep_score < 60
        and age_adjusted_sleep_score is not None
        and age_adjusted_sleep_score >= 60
    )
    crossed_green = (
        raw_sleep_score is not None
        and raw_sleep_score < 74
        and age_adjusted_sleep_score is not None
        and age_adjusted_sleep_score >= 74
    )
    objective_recovery_corroborated = positive_hrv_evidence and resting_hr_in_band and readiness_ok
    exception_evidence_complete = objective_recovery_corroborated and positive_subjective_evidence
    # Age scoring may move a raw-Red night into Amber, but never all the way to
    # Green. A crossing of only the Green line keeps Batch 170's complete-
    # corroboration exception.
    allowed_green = not crossed_red and ((not crossed_green) or exception_evidence_complete)
    reason = None
    if crossed_red:
        reason = (
            "The raw Garmin sleep score is below 60; age adjustment may lift the "
            "night to Amber but cannot carry it to Green."
        )
    elif crossed_green and not allowed_green:
        reason = (
            "Age-adjusted sleep reaches the Green line, but the raw Garmin sleep score "
            "is below 74 without complete measured recovery and check-in evidence."
        )
    return {
        "rawSleepScore": raw_sleep_score,
        "ageAdjustedSleepScore": age_adjusted_sleep_score,
        "crossedRedThreshold": crossed_red,
        "crossedGreenThreshold": crossed_green,
        "maximumStatus": "Amber" if crossed_red else None,
        "corroboratedByObjectiveRecovery": objective_recovery_corroborated,
        "positiveSubjectiveEvidence": positive_subjective_evidence,
        "exceptionEvidenceComplete": exception_evidence_complete,
        "allowedGreen": allowed_green,
        "applied": False,
        "reason": reason,
    }


def morning_verdict(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    age_adjusted_sleep_score: int | None,
    manual_entries: Sequence[ManualEntry],
    planned_workouts: Sequence[PlannedWorkout],
    baselines: Mapping[str, MetricBaseline] | None = None,
    yesterday_load: Mapping[str, Any] | None = None,
    training_load: Mapping[str, Any] | None = None,
    readiness_baseline_trend: Mapping[str, Any] | None = None,
    breathwork_brief: BreathworkBriefResult | None = None,
    rest_day: Mapping[str, Any] | None = None,
    recent_daily_metrics: Sequence[DailyMetric] = (),
    recent_sleeps: Sequence[Sleep] = (),
    enforce_data_sufficiency: bool = False,
    notes_symptom_answer: str | None = None,
    notes_symptom_words: str | None = None,
    symptom_easing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    subjective_score = _latest_subjective_score(manual_entries)
    tapped_answer = latest_symptom_answer(manual_entries)
    # Batch 297: a symptom his note names sets the same floor as answering with it.
    # The more severe of the two stands, so the note can only add caution.
    symptom_answer = more_severe_symptom(tapped_answer, notes_symptom_answer)
    symptom_source = (
        "notes"
        if notes_symptom_answer is not None
        and symptom_answer == notes_symptom_answer
        and symptom_answer != tapped_answer
        else "answer"
    )
    hrv_status = _lower(daily_metric.hrv_status if daily_metric else None) or _lower(
        sleep.hrv_status if sleep else None
    )
    hrv_low = _hrv_below_baseline(daily_metric)
    readiness_level = _lower(daily_metric.readiness_level if daily_metric else None)
    baselines = baselines or {}
    acute_physiology = _acute_physiology_rail(
        daily_metric=daily_metric,
        sleep=sleep,
        baselines=baselines,
        recent_daily_metrics=recent_daily_metrics,
        recent_sleeps=recent_sleeps,
        symptom_answer=symptom_answer,
        symptom_source=symptom_source,
        symptom_words=notes_symptom_words,
        symptom_easing=symptom_easing,
    )
    # Batch 271's signal. Batch 269 gates the HRV Red on it below and Batch 270
    # classifies a Red cluster with it; both read this one signal so they cannot
    # disagree about what an artifact is.
    hrv_recalibration = detect_hrv_recalibration(daily_metric, recent_daily_metrics)
    band_artifact = is_band_artifact(hrv_recalibration)
    overnight_below_floor = _overnight_below_floor(daily_metric)
    hrv_graded_response: dict[str, Any] = {
        "tier": None,
        "concern": None,
        "garminStatus": hrv_status,
        "overnightMs": daily_metric.hrv_last_night_avg_ms if daily_metric else None,
        "weeklyAvgMs": daily_metric.hrv_weekly_avg_ms if daily_metric else None,
        "floorMs": daily_metric.hrv_baseline_low_ms if daily_metric else None,
        "overnightBelowFloor": (
            overnight_below_floor
            if daily_metric is not None and daily_metric.hrv_last_night_avg_ms is not None
            else None
        ),
        "floorMoved": band_artifact,
        "corroboratingSignals": [],
        "heldBackBy": None,
    }
    resting_hr_baseline = baselines.get("resting_heart_rate_bpm")
    resting_hr_in_band = metric_within_baseline_band(
        daily_metric.resting_heart_rate_bpm if daily_metric else None,
        resting_hr_baseline,
        lower_is_better=True,
    )
    # Preserve the existing Poor-readiness corroboration rule independently of
    # the stricter, history-qualified acute rail introduced in Batch 246.
    resting_hr_elevated = _resting_hr_elevated(daily_metric, resting_hr_baseline)
    readiness_center = baseline_center(baselines.get("readiness_score"))
    readiness_floor = effective_readiness_floor(readiness_center)
    readiness_trend = dict(
        readiness_baseline_trend
        or {
            "metricKey": "readiness_score",
            "status": "not_evaluated",
            "triggered": False,
            "verdictImpact": "warning_only",
            "reason": None,
        }
    )
    rest_day = rest_day or {}
    is_rest_day = bool(rest_day.get("isRestDay"))
    has_vo2 = not is_rest_day and any(
        _workout_has_vo2_intensity(workout)
        for workout in planned_workouts
        if workout.status not in {"completed", "skipped"}
    )
    positive_hrv_evidence = _positive_hrv_evidence(
        daily_metric=daily_metric,
        sleep=sleep,
        hrv_status=hrv_status,
        hrv_below_baseline=hrv_low,
    )
    readiness_ok_for_override = _readiness_score_ok(
        daily_metric,
        readiness_floor=readiness_floor,
    )
    positive_subjective_evidence = subjective_score is not None and subjective_score >= 5
    recovery_signals_good = (
        (age_adjusted_sleep_score is not None and age_adjusted_sleep_score >= 74)
        and positive_hrv_evidence
        and positive_subjective_evidence
    )
    soft_sleep_override = _soft_sleep_recovery_override(
        age_adjusted_sleep_score=age_adjusted_sleep_score,
        subjective_score=subjective_score,
        hrv_status=hrv_status,
        hrv_below_baseline=hrv_low,
        positive_hrv_evidence=positive_hrv_evidence,
        resting_hr_in_band=resting_hr_in_band,
        readiness_ok=readiness_ok_for_override,
    )
    yesterday_hard = (yesterday_load or {}).get("status") == "hard"
    training_load_cap = _training_load_cap(training_load)
    load_driven_eligibility = _load_driven_eligibility(training_load)
    sleep_credit_ceiling = _sleep_credit_ceiling(
        sleep=sleep,
        age_adjusted_sleep_score=age_adjusted_sleep_score,
        positive_hrv_evidence=positive_hrv_evidence,
        resting_hr_in_band=resting_hr_in_band,
        readiness_ok=readiness_ok_for_override,
        positive_subjective_evidence=positive_subjective_evidence,
    )

    reasons: list[str] = []
    readiness_interpretation = None
    if readiness_level == "poor":
        reasons.append("Garmin readiness is Poor; keep the day cautious.")
    elif readiness_level == "low":
        if recovery_signals_good and load_driven_eligibility["eligible"]:
            readiness_interpretation = "load_driven"
            reasons.append(
                "Garmin readiness is Low, measured recovery is clean, and ACWR is "
                "inside the benign load-driven range."
            )
        else:
            reasons.append(
                "Garmin readiness is Low without complete recovery evidence and a "
                "proved-benign load signal to downplay it."
            )

    if age_adjusted_sleep_score is not None and age_adjusted_sleep_score < 60:
        status = "Red"
        reasons.append("Age-adjusted sleep is below 60.")
    elif (
        hrv_low
        and overnight_below_floor
        and hrv_status in {"unbalanced", "low"}
        and not band_artifact
    ):
        # Batch 269: Garmin's flag is its 7-day average against its band, so the
        # same-day Red also needs last night's own reading under the floor, and
        # never fires when Garmin moved the floor under a reading that held.
        status = "Red"
        reasons.append(HRV_RED_REASON)
        hrv_graded_response["tier"] = "red"
        hrv_graded_response["concern"] = HRV_CONCERN_OVERNIGHT_BELOW_FLOOR
    elif readiness_level == "poor":
        status = "Amber"
    elif readiness_level == "low" and readiness_interpretation != "load_driven":
        status = "Amber"
    elif soft_sleep_override:
        status = "Green"
        reasons.append(
            "Age-adjusted sleep is soft, but measured HRV, resting HR, readiness, "
            "and the current check-in hold the day Green."
        )
    elif age_adjusted_sleep_score is not None and age_adjusted_sleep_score < 74:
        status = "Amber"
        reasons.append("Age-adjusted sleep is below the 74+ green target.")
    elif hrv_status in {"unbalanced", "low", "poor"} or hrv_low:
        hold_concern = _hrv_hold_concern(
            hrv_low=hrv_low,
            overnight_below_floor=overnight_below_floor,
            band_artifact=band_artifact,
        )
        corroborating = _hrv_corroborating_signals(
            daily_metric=daily_metric,
            readiness_level=readiness_level,
            readiness_baseline=baselines.get("readiness_score"),
            resting_hr_elevated=resting_hr_elevated,
            subjective_score=subjective_score,
        )
        hrv_graded_response["concern"] = hold_concern or (
            HRV_CONCERN_OVERNIGHT_BELOW_FLOOR
            if overnight_below_floor
            else HRV_CONCERN_GARMIN_STATUS
        )
        hrv_graded_response["corroboratingSignals"] = corroborating
        # Batch 269: the hold is for Garmin's mildest flag only. Its Low is a week
        # well under the band, which still eases the day.
        if (
            daily_metric is not None
            and hold_concern is not None
            and hrv_status == "unbalanced"
            and not corroborating
        ):
            status = "Green"
            reasons.append(_hrv_hold_reason(hold_concern, daily_metric, hrv_recalibration))
            hrv_graded_response["tier"] = "hold"
        else:
            status = "Amber"
            reasons.append(HRV_EASE_REASON)
            hrv_graded_response["tier"] = "ease"
    elif subjective_score is not None and subjective_score < 5:
        status = "Amber"
        reasons.append("Subjective score is below 5.")
    else:
        status = "Green"
        if positive_hrv_evidence and positive_subjective_evidence:
            reasons.append(
                "Sleep, measured HRV, and the current subjective signal clear the green rule."
            )
        elif positive_hrv_evidence:
            reasons.append(
                "Sleep and measured HRV clear the green rule; no current subjective "
                "check-in was used as positive evidence."
            )
        elif positive_subjective_evidence:
            reasons.append(
                "Sleep clears the green rule and the current check-in is positive; "
                "missing HRV is neutral, not positive evidence."
            )
        else:
            reasons.append(
                "Sleep clears the green rule; missing HRV/check-in data is neutral "
                "and did not provide positive evidence."
            )

    cumulative_escalation: dict[str, Any] = {
        "triggered": False,
        "applied": False,
        "readinessLevel": readiness_level,
        "negativeSignals": [],
        "reason": None,
    }
    if readiness_level == "poor":
        negative_signals: list[str] = []
        if age_adjusted_sleep_score is not None and 60 <= age_adjusted_sleep_score < 74:
            negative_signals.append("soft_sleep")
        if subjective_score is not None and subjective_score < 5:
            negative_signals.append("low_subjective")
        if yesterday_hard:
            negative_signals.append("hard_yesterday")
        if resting_hr_elevated:
            negative_signals.append("elevated_resting_heart_rate")
        cumulative_escalation["negativeSignals"] = negative_signals
        cumulative_escalation["triggered"] = bool(negative_signals)
        if status == "Amber" and negative_signals:
            status = "Red"
            cumulative_escalation["applied"] = True
            cumulative_escalation["reason"] = (
                "Garmin readiness is Poor and a second recovery signal is negative."
            )
            reasons.append(str(cumulative_escalation["reason"]))

    if status == "Green" and not sleep_credit_ceiling["allowedGreen"]:
        status = "Amber"
        sleep_credit_ceiling["applied"] = True
        reason = sleep_credit_ceiling.get("reason")
        if isinstance(reason, str):
            reasons.append(reason)

    acute_status_before_cap = status
    for signal_key in ("restingHeartRate", "overnightHrv", "oxygenRespiration"):
        signal_reason = acute_physiology[signal_key].get("reason")
        if isinstance(signal_reason, str):
            reasons.append(signal_reason)
    acute_verdict_cap_triggered = bool(
        acute_physiology["restingHeartRate"]["triggered"]
        or acute_physiology["overnightHrv"]["triggered"]
    )
    if status == "Green" and acute_verdict_cap_triggered:
        status = "Amber"
    status_after_acute_cap = status
    data_sufficiency = acute_physiology["dataSufficiency"]
    if enforce_data_sufficiency and data_sufficiency["status"] == "insufficient_data":
        if status == "Green":
            status = "Amber"
        reasons.append(INSUFFICIENT_DATA_MESSAGE)
    acute_physiology["statusBeforeCap"] = acute_status_before_cap
    acute_physiology["statusAfterCap"] = status
    acute_physiology["verdictCapApplied"] = (
        acute_status_before_cap == "Green"
        and status_after_acute_cap == "Amber"
        and acute_verdict_cap_triggered
    )
    acute_physiology["missingDataFloorApplied"] = (
        enforce_data_sufficiency
        and status_after_acute_cap == "Green"
        and status == "Amber"
        and data_sufficiency["status"] == "insufficient_data"
    )

    status_before_load_cap = status
    if training_load_cap["triggered"]:
        if status == "Green":
            status = "Amber"
            training_load_cap["applied"] = True
        reasons.extend(training_load_cap["reasons"])
    training_load_cap["statusBeforeCap"] = status_before_load_cap
    # Batch 294: a symptom floor outranks every rung of the ladder. No other signal can
    # override it, so it is applied last and its reason reads first.
    symptom_floor = acute_physiology["symptoms"]
    symptom_floor["statusBeforeFloor"] = status
    symptom_floor["applied"] = bool(symptom_floor["triggered"])
    if symptom_floor["applied"]:
        status = "Red"
        reasons.insert(0, str(symptom_floor["reason"]))
    # Batch 269: a hold only stands if nothing after the ladder capped the day. When
    # a ceiling did, the HRV flag still cut nothing on its own, and the packet names
    # the ceiling that did.
    if hrv_graded_response["tier"] == "hold" and status != "Green":
        hrv_graded_response["tier"] = "ease"
        hrv_graded_response["heldBackBy"] = next(
            (
                name
                for name, applied in (
                    ("symptom_floor", symptom_floor["applied"]),
                    ("sleep_credit_ceiling", sleep_credit_ceiling["applied"]),
                    ("acute_physiology_cap", acute_physiology["verdictCapApplied"]),
                    ("missing_data_floor", acute_physiology["missingDataFloorApplied"]),
                    ("training_load_cap", training_load_cap["applied"]),
                )
                if applied
            ),
            None,
        )
    baseline_trend_reason = readiness_trend.get("reason")
    if readiness_trend.get("triggered") and isinstance(baseline_trend_reason, str):
        reasons.append(baseline_trend_reason)

    requires_training_rest = bool(acute_physiology["requiresTrainingRest"])
    requires_bike_rest = bool(acute_physiology["requiresBikeRest"])
    if requires_training_rest and not is_rest_day:
        plan_adjustments = [str(symptom_floor["planLine"])]
    elif requires_bike_rest and not is_rest_day:
        plan_adjustments = [
            "Take today off the bike; do not substitute an eased ride for the acute signal."
        ]
    else:
        plan_adjustments = _plan_adjustments(
            status,
            planned_workouts,
            is_rest_day=is_rest_day,
            hold_targets=hrv_graded_response["tier"] == "hold",
        )
    if status != "Green" and yesterday_hard and not is_rest_day and not requires_training_rest:
        plan_adjustments.append(
            "Treat yesterday's hard session as extra context for easing today's work."
        )
    # Batch 294: on a morning that has already taken him off the bike, "a very easy
    # spin" contradicts the line above it. Red-never-VO2 is still recorded below.
    if status == "Red" and has_vo2 and not requires_bike_rest:
        plan_adjustments.append("Replace VO2 with rest, mobility, or a very easy spin.")
    breathwork_signal = {
        "status": status,
        "readinessLevel": readiness_level,
        "readinessInterpretation": readiness_interpretation,
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": hrv_low,
        "symptomsAnswer": symptom_answer,
    }
    if should_recommend_breathwork(breathwork_signal):
        plan_adjustments.append(
            _breathwork_recommendation(breathwork_brief, age_adjusted_sleep_score)
        )

    safety_rules = ["red_never_vo2"] if status == "Red" and has_vo2 else []
    if training_load_cap["triggered"]:
        safety_rules.append("training_load_amber_cap")
    if sleep_credit_ceiling["applied"]:
        safety_rules.append(
            "sleep_credit_red_ceiling"
            if sleep_credit_ceiling["crossedRedThreshold"]
            else "sleep_credit_green_ceiling"
        )
    if cumulative_escalation["applied"]:
        safety_rules.append("poor_readiness_cumulative_red")
    if symptom_floor["applied"]:
        safety_rules.append(
            "symptom_no_training_floor" if requires_training_rest else "symptom_easy_riding_floor"
        )
    if acute_physiology["restingHeartRate"]["triggered"]:
        safety_rules.append("acute_resting_heart_rate_amber_cap")
    if acute_physiology["overnightHrv"]["triggered"]:
        safety_rules.append("acute_overnight_hrv_amber_cap")
    if acute_physiology["oxygenRespiration"]["triggered"]:
        safety_rules.append("oxygen_respiration_surveillance")
    if enforce_data_sufficiency and data_sufficiency["status"] == "insufficient_data":
        safety_rules.append("missing_data_amber_floor")

    return {
        "status": status,
        "reasons": reasons,
        "readinessLevel": daily_metric.readiness_level if daily_metric else None,
        "readinessInterpretation": readiness_interpretation,
        "loadDrivenEligibility": load_driven_eligibility,
        "ageAdjustedSleepScore": age_adjusted_sleep_score,
        "subjectiveScore": subjective_score,
        "subjectiveLabel": subjective_score_label(subjective_score),
        "positiveSubjectiveEvidence": positive_subjective_evidence,
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": hrv_low,
        "positiveHrvEvidence": positive_hrv_evidence,
        "restingHeartRateWithinBaseline": resting_hr_in_band,
        "restingHeartRateElevated": resting_hr_elevated,
        "readinessBaselineCenter": readiness_center,
        "readinessAbsoluteFloor": SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,
        "readinessEffectiveFloor": readiness_floor,
        "readinessBaselineTrend": readiness_trend,
        "softSleepRecoveryOverride": soft_sleep_override,
        "sleepCreditCeiling": sleep_credit_ceiling,
        "cumulativeEscalation": cumulative_escalation,
        "acutePhysiology": acute_physiology,
        "hrvRecalibration": hrv_recalibration,
        "hrvGradedResponse": hrv_graded_response,
        "yesterdayLoadStatus": (yesterday_load or {}).get("status"),
        "trainingLoadCap": training_load_cap,
        "dayType": "rest" if is_rest_day else "training",
        "isRestDay": is_rest_day,
        "restDayReason": rest_day.get("reason"),
        "hasVo2WorkoutToday": has_vo2,
        "planAdjustments": plan_adjustments,
        "safetyRulesApplied": safety_rules,
    }


def should_recommend_breathwork(signal: Mapping[str, Any]) -> bool:
    # Batch 294: a chest-or-heart morning is for a doctor, not a breathing drill
    # (Craig, on Mark's behalf, 28 Sep 2026).
    if signal.get("symptomsAnswer") == SYMPTOMS_CHEST_HEART:
        return False
    status = str(signal.get("status") or "").lower()
    readiness_level = str(signal.get("readinessLevel") or "").lower()
    readiness_interpretation = signal.get("readinessInterpretation")
    hrv_status = str(signal.get("hrvStatus") or "").lower()
    hrv_below_baseline = bool(signal.get("hrvBelowBaseline"))
    readiness_is_recovery_low = (
        readiness_level in {"low", "poor"} and readiness_interpretation != "load_driven"
    )
    return (
        status == "red"
        or readiness_is_recovery_low
        or hrv_status in {"unbalanced", "low", "poor"}
        or hrv_below_baseline
    )


def _workout_has_vo2_intensity(workout: PlannedWorkout) -> bool:
    try:
        return ir_has_vo2(build_structured_workout_ir(workout))
    except HTTPException:
        return "vo2" in (workout.workout_type or "").lower()


def _breathwork_recommendation(
    breathwork_brief: BreathworkBriefResult | None,
    age_adjusted_sleep_score: int | None,
) -> str:
    context = ""
    if breathwork_brief is not None:
        week_start = breathwork_brief.as_of_date - timedelta(days=6)
        sessions_this_week = sum(
            1 for session in breathwork_brief.recent_sessions if session.session_date >= week_start
        )
        context = f" You've logged {sessions_this_week} breathwork session(s) in the last 7 days."
    sleep_context = (
        f" Age-adjusted sleep is {age_adjusted_sleep_score}."
        if age_adjusted_sleep_score is not None
        else ""
    )
    return (
        "Add a short breathwork session today to help down-regulate the recovery signal."
        f"{context}{sleep_context}"
    )


def _plan_adjustments(
    status: str,
    planned_workouts: Sequence[PlannedWorkout],
    *,
    is_rest_day: bool = False,
    hold_targets: bool = False,
) -> list[str]:
    live_workouts = [
        workout for workout in planned_workouts if workout.status not in {"completed", "skipped"}
    ]
    reset_week = any(_is_reset_week_workout(workout) for workout in live_workouts)
    if is_rest_day:
        adjustments = ["Today is an intentional rest day; keep paused or skipped sessions paused."]
    elif not planned_workouts:
        adjustments = ["No active planned workout found for today; keep advice conservative."]
    elif not live_workouts:
        adjustments = [
            "No live workout remains today; do not revive completed or skipped sessions."
        ]
    elif status == "Green":
        adjustments = ["Proceed with the planned workout if warm-up confirms readiness."]
        if hold_targets:
            adjustments.append(HRV_HOLD_PLAN_LINE)
    elif status == "Amber":
        ride_adjustment = _verdict_adjustment_packet(status, planned_workouts)
        categories = {category_for_workout_type(workout.workout_type) for workout in live_workouts}
        adjustments = []
        if ride_adjustment is not None:
            duration = ride_adjustment.get("adjustedDurationMin")
            adjustments.append(
                f"Cut the bike to {duration} min; hold Zone 2, ease harder intervals by a "
                f"zone, and convert former HIT/VO2 work to no more than "
                f"{AMBER_POWER_CAP_PCT}% FTP (Sweet Spot)."
            )
            if ride_adjustment.get("companionSession") is True:
                adjustments.append(
                    "Another session shares today, so this cut accounts for the day's total load."
                )
        if DAY_CATEGORY_WEIGHTS in categories:
            adjustments.append(
                "Keep strength submaximal: reduce the sets and stop well short of failure."
            )
        if DAY_CATEGORY_FLEXIBILITY in categories:
            adjustments.append(
                "Keep mobility gentle and symptom-led; shorten it if it stops feeling restorative."
            )
        if DAY_CATEGORY_WALK in categories:
            adjustments.append(
                "Keep the walk easy and conversational; shorten it rather than "
                "turning it into training."
            )
    else:
        # Batch 215: Red no longer means one thing. An already-Zone-2 ride keeps its
        # intensity and takes a light duration cut, so the instruction has to follow
        # the transform rather than assert a substitution that did not happen.
        adjustment = _verdict_adjustment_packet(status, planned_workouts)
        # Batch 252.4: key on the endurance *path*, not on whether the number
        # moved. A 68-75% ride is eased to the 67% anchor and is still Zone 2, so
        # the narrow flag would have sent it down the substitution branch below.
        if isinstance(adjustment, Mapping) and adjustment.get("keptAsEndurance"):
            adjustments = [
                f"Hold Zone 2 (~{adjustment.get('adjustedWorkPowerPct')}% FTP) and cut to "
                f"{adjustment.get('adjustedDurationMin')} min; no intervals and no HIT/VO2. "
                "Sustained easy work builds sleep pressure — keep it, do not delete it."
            ]
        else:
            adjustments = ["Substitute recovery, mobility, or rest."]
    if reset_week:
        adjustments.insert(
            0,
            (
                "This week is an intended light reset; judge the reduced cycling load "
                "as planned deload, not missed load."
            ),
        )
    return adjustments


def _is_reset_week_workout(workout: PlannedWorkout) -> bool:
    structured = workout.structured_workout or {}
    if not isinstance(structured, dict):
        return False
    reset = structured.get("resetWeek")
    return isinstance(reset, dict) and reset.get("active") is True


def _latest_subjective_score(manual_entries: Sequence[ManualEntry]) -> int | None:
    for entry in manual_entries:
        if entry.subjective_score is not None:
            return entry.subjective_score
    return None


def _soft_sleep_recovery_override(
    *,
    age_adjusted_sleep_score: int | None,
    subjective_score: int | None,
    hrv_status: str | None,
    hrv_below_baseline: bool,
    positive_hrv_evidence: bool,
    resting_hr_in_band: bool,
    readiness_ok: bool,
) -> bool:
    if age_adjusted_sleep_score is None or not 60 <= age_adjusted_sleep_score < 74:
        return False
    # ``readiness_ok`` applies Mark's personal median anchored at 60 and requires
    # a measured score outside Garmin's Low/Poor categories. Missing HRV,
    # readiness, or check-in data is neutral and cannot satisfy this exception.
    return (
        not hrv_below_baseline
        and hrv_status in {"balanced", "stable", "optimal", "normal"}
        and positive_hrv_evidence
        and resting_hr_in_band
        and readiness_ok
        and subjective_score is not None
        and subjective_score >= 5
    )


def _hrv_below_baseline(daily_metric: DailyMetric | None) -> bool:
    """Garmin's own comparison: the 7-day average against Garmin's band.

    Batch 269 left this reading the weekly average on purpose. Garmin's band is a
    band for the 7-day average, and one night swings several ms around it: reading
    last night's value here instead, as the batch row first proposed, would have
    cut 10 of Mark's 43 Green days between 1 Jul and 26 Sep 2026, every one on a
    balanced week. Last night's reading decides only the same-day Red
    (``_overnight_below_floor``).
    """
    if daily_metric is None:
        return False
    value = daily_metric.hrv_weekly_avg_ms or daily_metric.hrv_last_night_avg_ms
    low = daily_metric.hrv_baseline_low_ms
    return value is not None and low is not None and value < low


def _overnight_below_floor(daily_metric: DailyMetric | None) -> bool:
    """Is last night's own reading under Garmin's floor? (Batch 269.1)

    The same-day Red reads this morning's measurement, not last week's average. With
    no overnight reading it falls back to the average, so a missing measurement can
    never clear a morning the old rule would have cut.
    """
    if daily_metric is None:
        return False
    value = daily_metric.hrv_last_night_avg_ms
    if value is None:
        value = daily_metric.hrv_weekly_avg_ms
    low = daily_metric.hrv_baseline_low_ms
    return value is not None and low is not None and value < low


def _hrv_hold_concern(
    *,
    hrv_low: bool,
    overnight_below_floor: bool,
    band_artifact: bool,
) -> str | None:
    """Why Garmin flagged a week that last night's reading does not support.

    ``None`` when last night's reading supports the flag, or when the flag is not
    about the floor at all: those mornings ease as they always did.
    """
    if band_artifact:
        return HRV_CONCERN_FLOOR_MOVED
    if hrv_low and not overnight_below_floor:
        return HRV_CONCERN_WEEKLY_BELOW_FLOOR
    return None


def _hrv_corroborating_signals(
    *,
    daily_metric: DailyMetric | None,
    readiness_level: str | None,
    readiness_baseline: MetricBaseline | None,
    resting_hr_elevated: bool,
    subjective_score: int | None,
) -> list[str]:
    """What else disagrees with last night's reading this morning (Batch 269).

    These are the signals that may ease a session on their own (Mark's G3 answer,
    made on his behalf on 27 Sep 2026): resting heart rate above his usual range,
    readiness below it or Garmin's Low or Poor, and a low check-in. Any one of them
    beside an HRV flag makes the morning Amber rather than a hold. Sleep is not
    listed because it already decides the day before this rule (under 74
    age-adjusted) or caps it after (the Batch 170 credit ceiling).
    """
    signals: list[str] = []
    if resting_hr_elevated:
        signals.append("resting_heart_rate_above_usual")
    readiness_score = daily_metric.readiness_score if daily_metric is not None else None
    usual_low = (
        readiness_baseline.lower_quartile_value
        if readiness_baseline is not None and _baseline_ready(readiness_baseline)
        else None
    )
    if readiness_level in {"low", "poor"} or (
        readiness_score is not None
        and usual_low is not None
        and float(readiness_score) < float(usual_low)
    ):
        signals.append("readiness_below_usual")
    if subjective_score is not None and subjective_score < 5:
        signals.append("check_in_low")
    return signals


def _hrv_hold_reason(
    concern: str,
    daily_metric: DailyMetric,
    recalibration: Mapping[str, Any],
) -> str:
    overnight = _number(daily_metric.hrv_last_night_avg_ms)
    floor = _number(daily_metric.hrv_baseline_low_ms)
    if concern == HRV_CONCERN_FLOOR_MOVED:
        band_low = recalibration.get("bandLow")
        usual = band_low.get("referenceMs") if isinstance(band_low, Mapping) else None
        return (
            f"Garmin moved its HRV floor to {floor} ms from a usual {_number(usual)} ms "
            f"while last night's reading held at {overnight} ms, and no other signal "
            "disagrees, so the moved floor alone does not cut the session."
        )
    return (
        f"Garmin's 7-day HRV average ({_number(daily_metric.hrv_weekly_avg_ms)} ms) is "
        f"under its {floor} ms floor, but last night's own reading ({overnight} ms) is "
        "not, and no other signal disagrees, so the HRV flag alone does not cut the "
        "session."
    )


def subjective_score_label(score: int | None) -> str | None:
    """Map the numeric check-in score to the nearest word anchor.

    Source of truth for the anchors is the frontend feel scale
    (apps/web/src/lib/subjectiveFeel.ts): 2=Rough, 4=Meh, 6=OK, 8=Good,
    10=Great. The read always speaks his word, never the raw 0-10 number.
    Batch 91 (#164), extended to the full 0-10 input in Batch 146."""
    if score is None:
        return None
    if score <= 3:
        return "Rough"
    if score <= 5:
        return "Meh"
    if score <= 7:
        return "OK"
    if score <= 9:
        return "Good"
    return "Great"


def _lower(value: str | None) -> str | None:
    return value.lower() if value else None


# -- the graded verdict's packet (Batch 296) ---------------------------------------------
#
# The colour comes from ``services.verdict_grading`` when ``settings.verdict_engine`` is
# ``graded``. The ladder above still runs first: its acute rail supplies the floors, and
# its own colour is logged beside the graded one, never put in the packet (which is
# serialised into the prompt). Mark-facing lines signed off by Craig on Mark's behalf on
# 29 Sep 2026 (docs/drafts/2026-09-29-batch-296-wording.md).

GRADED_MOVE_LINE = (
    "Move {title} to a better day this week if there is one; otherwise ride it and hold "
    "the targets."
)
GRADED_EASE_HARD_LINE = "Ease the hard intervals a zone; the rest of the session stays as planned."
GRADED_ZONE_TWO_LINE = "Keep your Zone 2 ride at full length."
#: Batch 298: the week is named as his plan names it (signed off 1 Oct 2026); W12 is a
#: consolidation week and W13 a taper, and both were "a planned recovery week".
GRADED_LIGHT_WEEK_LINE = (
    "This is your planned {week} week, so today's session stays as planned: hold the targets."
)
GRADED_RECOVERY_WEEK_LINE = GRADED_LIGHT_WEEK_LINE.format(week="recovery")
BIKE_REST_PLAN_LINE = (
    "Take today off the bike; do not substitute an eased ride for the acute signal."
)

#: The ladder's own working, which a graded packet does not carry. Each explains a rung
#: the graded verdict does not have; left in, the brief would narrate a rule that did
#: not decide the day.
LADDER_ONLY_FIELDS = (
    "readinessInterpretation",
    "loadDrivenEligibility",
    "positiveSubjectiveEvidence",
    "positiveHrvEvidence",
    "restingHeartRateWithinBaseline",
    "restingHeartRateElevated",
    "readinessBaselineCenter",
    "readinessAbsoluteFloor",
    "readinessEffectiveFloor",
    "softSleepRecoveryOverride",
    "sleepCreditCeiling",
    "cumulativeEscalation",
    "hrvRecalibration",
    "hrvGradedResponse",
    "trainingLoadCap",
)


def graded_plan_adjustments(
    graded: Any,
    planned_workouts: Sequence[PlannedWorkout],
    *,
    is_rest_day: bool,
    acute: Mapping[str, Any],
    has_vo2: bool,
) -> list[str]:
    """The day's plan lines under the graded verdict, one per session action."""

    live = [
        workout for workout in planned_workouts if workout.status not in {"completed", "skipped"}
    ]
    raw_symptoms = acute.get("symptoms")
    symptoms: Mapping[str, Any] = raw_symptoms if isinstance(raw_symptoms, Mapping) else {}
    if acute.get("requiresTrainingRest") is True and not is_rest_day:
        return [str(symptoms.get("planLine") or BIKE_REST_PLAN_LINE)]
    if acute.get("requiresBikeRest") is True and not is_rest_day:
        return [BIKE_REST_PLAN_LINE]
    if is_rest_day or not planned_workouts or not live:
        return _plan_adjustments(graded.status, planned_workouts, is_rest_day=is_rest_day)
    if graded.status == "Red":
        red_lines = _plan_adjustments("Red", planned_workouts)
        if has_vo2:
            red_lines.append("Replace VO2 with rest, mobility, or a very easy spin.")
        return red_lines

    actions = {action.session_id: action.action for action in graded.actions}
    light_week = graded.references.get("lightWeek") if graded.references else None
    hold_line = GRADED_LIGHT_WEEK_LINE.format(
        week=light_week if isinstance(light_week, str) else "recovery"
    )
    lines: list[str] = []
    other_categories: set[str] = set()
    for workout in live:
        action = actions.get(str(workout.id))
        if action == "hold_targets":
            line = hold_line
        elif action == "move_or_hold":
            line = GRADED_MOVE_LINE.format(title=workout.title or "the hard session")
        elif action == "ease_hard":
            line = GRADED_EASE_HARD_LINE
        elif action == "recovery":
            # Batch 303: below Red only what follows a symptom swaps a hard session
            # for an easy spin (an easy day back after a fever, an open chest question).
            line = EASY_RIDING_PLAN_LINE
        elif graded.status == "Amber" and is_bike_workout_type(workout.workout_type):
            line = GRADED_ZONE_TWO_LINE
        else:
            if graded.status == "Amber":
                other_categories.add(category_for_workout_type(workout.workout_type))
            continue
        if line not in lines:
            lines.append(line)
    # Amber's session-specific lines for the sessions that are not rides (Batch 243).
    if DAY_CATEGORY_WEIGHTS in other_categories:
        lines.append("Keep strength submaximal: reduce the sets and stop well short of failure.")
    if DAY_CATEGORY_FLEXIBILITY in other_categories:
        lines.append(
            "Keep mobility gentle and symptom-led; shorten it if it stops feeling restorative."
        )
    if DAY_CATEGORY_WALK in other_categories:
        lines.append(
            "Keep the walk easy and conversational; shorten it rather than turning it into "
            "training."
        )
    if not lines:
        lines.append("Proceed with the planned workout if warm-up confirms readiness.")
    if graded.held and hold_line not in lines:
        lines.append(HRV_HOLD_PLAN_LINE)
    if any(_is_reset_week_workout(workout) for workout in live):
        lines.insert(
            0,
            "This week is an intended light reset; judge the reduced cycling load as planned "
            "deload, not missed load.",
        )
    return lines


def graded_verdict_packet(
    ladder: Mapping[str, Any],
    graded: Any,
    planned_workouts: Sequence[PlannedWorkout],
    *,
    breathwork_line: str | None,
) -> dict[str, Any]:
    """The ladder's packet, with the colour, reasons and plan the graded verdict set.

    Kept: the acute rail and its floors, the readiness trend warning, the check-in, the
    rest-day context and the VO2 flag. Removed: the ladder's own working
    (:data:`LADDER_ONLY_FIELDS`). Added: ``engine``, ``held`` and ``graded``.
    """

    acute = ladder["acutePhysiology"]
    is_rest_day = bool(ladder.get("isRestDay"))
    has_vo2 = bool(ladder.get("hasVo2WorkoutToday"))
    status = graded.status
    reasons: list[str] = []
    raw_symptoms = acute.get("symptoms")
    symptoms: Mapping[str, Any] = raw_symptoms if isinstance(raw_symptoms, Mapping) else {}
    if symptoms.get("triggered") is True and isinstance(symptoms.get("reason"), str):
        reasons.append(str(symptoms["reason"]))
    # Batch 303: what follows a symptom reads first, as a floor's reason does.
    if graded.easing is not None and graded.easing_reason:
        reasons.append(graded.easing_reason)
    reasons.append(graded.summary)
    if graded.missing_data_floor_applied:
        reasons.append(INSUFFICIENT_DATA_MESSAGE)
    trend = ladder.get("readinessBaselineTrend")
    if (
        isinstance(trend, Mapping)
        and trend.get("triggered")
        and isinstance(trend.get("reason"), str)
    ):
        reasons.append(str(trend["reason"]))

    plan = graded_plan_adjustments(
        graded, planned_workouts, is_rest_day=is_rest_day, acute=acute, has_vo2=has_vo2
    )
    if breathwork_line is not None:
        plan.append(breathwork_line)

    safety = ["graded_verdict"]
    if symptoms.get("triggered") is True:
        safety.append(
            "symptom_no_training_floor"
            if acute.get("requiresTrainingRest") is True
            else "symptom_easy_riding_floor"
        )
    if acute.get("requiresBikeRest") is True:
        safety.append("bike_rest_floor")
    if graded.easing is not None:
        safety.append(
            "chest_question_easy_riding"
            if graded.easing == EASING_CHEST_QUESTION
            else "fever_return_easy_riding"
        )
    oxygen = acute.get("oxygenRespiration")
    if isinstance(oxygen, Mapping) and oxygen.get("triggered") is True:
        safety.append("oxygen_respiration_surveillance")
    if graded.missing_data_floor_applied:
        safety.append("missing_data_amber_floor")
    if status == "Red" and has_vo2:
        safety.append("red_never_vo2")

    packet = {key: value for key, value in ladder.items() if key not in LADDER_ONLY_FIELDS}
    packet["acutePhysiology"] = graded_acute_physiology(acute)
    packet.update(
        {
            "engine": "graded",
            "status": status,
            "held": graded.held,
            "reasons": reasons,
            "planAdjustments": plan,
            "safetyRulesApplied": safety,
            "graded": graded.to_packet(),
        }
    )
    return packet


#: The ladder's own working inside the acute rail. Each records what the ladder's cap
#: did to the ladder's colour, so a graded packet carrying them would put the ladder's
#: colour in front of the model (Decision #367 says it never enters the packet).
LADDER_ONLY_ACUTE_FIELDS = (
    "statusBeforeCap",
    "statusAfterCap",
    "verdictCapApplied",
    "missingDataFloorApplied",
)

#: What an acute signal does under the graded verdict: one domain signal, rated there.
GRADED_SIGNAL_IMPACT = "graded_domain_signal"


def graded_acute_physiology(acute: Mapping[str, Any]) -> dict[str, Any]:
    """The acute rail as a graded packet carries it (Batch 298).

    The rail writes the ladder's words: a low HRV night or two mornings of raised
    resting heart rate "caps today at Amber". The graded verdict rates either as one
    thing a little off and may show Green with the targets held, so on 1 Oct the notice
    and the brief told Mark the day was capped while the reason said two things were a
    little off. This copy says what the graded verdict did. The floors, levels, numbers
    and the off-the-bike and GP lines are unchanged apart from the one clause that
    called a single sign a cap. The ladder's packet is not touched.
    """

    out = copy.deepcopy(dict(acute))
    for key in LADDER_ONLY_ACUTE_FIELDS:
        out.pop(key, None)
    symptoms = out.get("symptoms")
    if isinstance(symptoms, dict):
        symptoms.pop("statusBeforeFloor", None)
    messages: dict[str, str] = {}

    rhr = out.get("restingHeartRate")
    if isinstance(rhr, dict):
        rhr["verdictImpact"] = GRADED_SIGNAL_IMPACT
        if rhr.get("triggered") is True:
            current, median_value = rhr.get("currentBpm"), rhr.get("baselineMedianBpm")
            if rhr.get("trigger") == "absolute_delta":
                rhr["reason"] = (
                    f"Resting heart rate {current} bpm is "
                    f"{_number(rhr.get('deltaFromMedianBpm'))} bpm above the personal median "
                    f"of {_number(median_value)}."
                )
            else:
                rhr["reason"] = (
                    "Resting heart rate has been above the personal upper quartile of "
                    f"{_number(rhr.get('baselineUpperQuartileBpm'))} bpm for two mornings: "
                    "one thing a little off."
                )
                rhr["escalation"] = _rhr_mild_notice(
                    current, median_value, GRADED_MILD_SIGNAL_CLOSING
                )
            if isinstance(rhr.get("escalation"), str):
                messages["resting_heart_rate"] = rhr["escalation"]

    hrv = out.get("overnightHrv")
    if isinstance(hrv, dict):
        hrv["verdictImpact"] = GRADED_SIGNAL_IMPACT
        if hrv.get("triggered") is True:
            current, median_value = hrv.get("currentMs"), hrv.get("baselineMedianMs")
            if hrv.get("illnessGrade") is True:
                hrv["reason"] = (
                    f"Overnight HRV {current} ms is an illness-grade drop, at or under "
                    f"{_number(hrv.get('illnessLineMs'))} ms."
                )
            else:
                hrv["reason"] = (
                    f"Overnight HRV {current} ms is below the acute personal floor of "
                    f"{_number(hrv.get('acuteFloorMs'))} ms."
                )
                raw_symptoms = out.get("symptoms")
                answer = raw_symptoms.get("answer") if isinstance(raw_symptoms, dict) else None
                corroborated = [str(sign) for sign in hrv.get("corroboratedBy") or []]
                hrv["escalation"] = (
                    _hrv_corroborated_notice(
                        current,
                        median_value,
                        _hrv_corroboration_clause(
                            corroborated, answer if isinstance(answer, str) else None
                        ),
                        GRADED_EITHER_ALONE_CLAUSE,
                    )
                    if hrv.get("requiresBikeRest") is True
                    else _hrv_mild_notice(current, median_value, GRADED_MILD_SIGNAL_CLOSING)
                )
            if isinstance(hrv.get("escalation"), str):
                messages["overnight_hrv"] = hrv["escalation"]
        for entry in hrv.get("provenance") or []:
            if isinstance(entry, dict) and entry.get("figure") == FIGURE_HRV_ACUTE_FLOOR:
                entry["rule"] = _hrv_floor_rule(GRADED_BELOW_FLOOR)

    out["escalations"] = [
        {
            **escalation,
            "message": messages.get(str(escalation.get("kind")), escalation.get("message")),
        }
        if isinstance(escalation, dict)
        else escalation
        for escalation in out.get("escalations") or []
    ]
    # The app heads a single mild sign "Counted in today's call" only on these words.
    out["gradedWording"] = True
    return out


def graded_verdict_adjustment_packet(
    graded: Any, planned_workouts: Sequence[PlannedWorkout]
) -> dict[str, Any] | None:
    """Today's ride change under the graded verdict, for the packet (Batch 296).

    The same transform the delivery rail applies (``morning_ir``), so the brief quotes
    the ride Mark would be sent. ``None`` when the session action leaves the ride as
    planned: a held or moved session, or a Zone 2 ride on an Amber morning.
    """

    ride = _todays_bike_workout(planned_workouts)
    if ride is None:
        return None
    action = next((item.action for item in graded.actions if item.session_id == str(ride.id)), None)
    transform = ride_transform(graded.status, graded=True, action=action)
    if transform is None:
        return None
    try:
        base_ir = build_structured_workout_ir(ride)
    except HTTPException:
        return None
    companion = companion_session_present(
        workout.status for workout in planned_workouts if workout.id != ride.id
    )
    summary = summarize_verdict_adjustment(
        base_ir, transform, companion_session=companion, graded=True
    )
    if summary is None:
        return None
    return {**summary, "plannedWorkoutId": str(ride.id)}
