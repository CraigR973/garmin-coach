"""The morning's floors, its context and its graded verdict's packet (Batches 245, 308).

Batch 245 extracted the app's central safety decision from the packet/model
orchestrator. Until Batch 296 a rule ladder here set the colour; the graded verdict
(``services.verdict_grading``) has set it since, and Batch 308 deleted the ladder.
What stays is:

* **the acute rail** (:func:`acute_physiology_rail`): the floors, which the graded
  verdict applies first: a reported symptom, an illness-grade or corroborated HRV drop,
  a large resting-heart-rate jump, and overnight oxygen and breathing surveillance;
* **the morning's context** (:func:`verdict_context`): the readings and plan facts the
  packet carries beside the colour;
* **the graded verdict's plan lines and packet**, built from an explicit allow-list
  (:data:`CONTEXT_FIELDS`).

Deliberately model-free and database-free: callers supply already-loaded rows and
receive a deterministic packet.
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
    EASING_CHEST_FOLLOW_UP,
    EASING_CHEST_QUESTION,
    EASY_RIDING_PLAN_LINE,
    SYMPTOM_FLOORS,
    SYMPTOMS_CHEST_HEART,
    ChestFollowUp,
    latest_symptom_answer,
    more_severe_symptom,
    reports_symptoms,
    symptom_signal,
)
from src.services.verdict_grading import (
    ACTION_MOVE_TEST,
    ACTION_OFFER_SHORTER,
    ACTION_PICK_ZONE2_OR_TEMPO,
    THRESHOLDS,
    ride_transform,
)
from src.services.verdict_scaling import (
    ENDURANCE_CEILING_PCT,
    TEMPO_CAP_PCT,
    TRANSFORM_SHORTER,
    TRANSFORM_TIRED_TEMPO,
    TRANSFORM_TIRED_ZONE2,
    adjust_ir_for_verdict,
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


#: Batch 269: a Green with the targets held says so in the plan (``verdict.held``).
HRV_HOLD_PLAN_LINE = "Hold the prescribed targets rather than pushing past the top of each zone."


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


def _red_ride_adjustment(planned_workouts: Sequence[PlannedWorkout]) -> dict[str, Any] | None:
    """Red's change to today's ride, which picks the Red plan line (Batches 173.3, 215).

    Built from the *same* ``adjust_ir_for_verdict`` transform the delivery rail and the
    interval editor use. ``None`` on a rest or no-ride day, or a malformed ride. The
    day's other sessions are resolved here, so the line carries the same combined-load
    gate the delivery rail applies (Batch 215.5).
    """
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
    summary = summarize_verdict_adjustment(base_ir, "Red", companion_session=companion)
    if summary is None:
        return None
    return {**summary, "plannedWorkoutId": str(ride.id)}


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


# Batch 354: a notice gives Mark its window as "from 10 Jun to 1 Sep" (Craig, 27 Oct,
# Decision #442), never ISO dates; the packet keeps its ISO fields. No year: every
# window ends within days of the morning it describes.
def _day_month(value: date) -> str:
    """``2026-06-10`` as ``10 Jun`` — no leading zero, no platform-specific format."""
    return f"{value.day} {value.strftime('%b')}"


def _window_words(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return ""
    return f" from {_day_month(start)} to {_day_month(end)}"


def _baseline_window_words(row: MetricBaseline | None) -> str:
    if row is None:
        return ""
    return _window_words(row.window_start_date, row.window_end_date)


def _prior_daily_metric(
    recent_daily_metrics: Sequence[DailyMetric],
    *,
    subject_date: date,
) -> DailyMetric | None:
    prior_date = subject_date - timedelta(days=1)
    return next((row for row in recent_daily_metrics if row.calendar_date == prior_date), None)


# -- the acute notices' words ------------------------------------------------------
#
# Batches 293 and 294, signed off by Craig on Mark's behalf on 27 and 28 Sep 2026. Batch
# 298 gave a signal that is one thing a little off its own closing sentence, signed off on
# 1 Oct 2026 (docs/drafts/2026-10-01-batch-298-wording.md). Until Batch 308 the rails wrote
# the ladder's words ("caps today at Amber") and the graded packet rewrote them; the rails
# now write the graded verdict's words themselves, byte for byte as the packet carried them.

#: What a resting-heart-rate or HRV signal does: one domain signal, rated by the graded
#: verdict (Batch 298).
GRADED_SIGNAL_IMPACT = "graded_domain_signal"
MILD_SIGNAL_CLOSING = (
    "On its own it is one thing a little off, and today's call already counts it: not a "
    "day off the bike."
)
EITHER_ALONE_CLAUSE = "Either on its own would only be a little off;"
BELOW_FLOOR = "Below it last night counts as one thing a little off in the graded verdict"


def _rhr_mild_notice(current: Any, median_value: Any) -> str:
    """Two mornings a little above his usual range (Batch 293)."""
    return (
        f"Your resting heart rate is {current} this morning against a usual "
        f"{_number(median_value)} — a little above your usual range, as it was "
        "yesterday. Small rises like this usually come from travel, a short night, "
        f"a busy week or a hard day before. {MILD_SIGNAL_CLOSING}"
    )


def _usual_ms(value: float | None) -> str:
    """His usual HRV in a notice: a whole ms, as Home's reason line gives it (Batch 317)."""
    return _number(round(value) if value is not None else None)


def _hrv_mild_notice(current: Any, usual_value: float | None) -> str:
    """A low night under his acute floor, on its own (Batch 294)."""
    return (
        f"Your overnight HRV is {current} ms this morning against a usual "
        f"{_usual_ms(usual_value)} ms — lower than most nights for you. Dips like "
        "this usually come from a short night, a drink, a busy week or a hard day "
        f"before. {MILD_SIGNAL_CLOSING}"
    )


def _hrv_corroborated_notice(current: Any, usual_value: float | None, second_sign: str) -> str:
    """A low night with a second sign, which rests the bike (Batch 294)."""
    return (
        f"Your overnight HRV is {current} ms this morning against a usual "
        f"{_usual_ms(usual_value)} ms, and {second_sign}. {EITHER_ALONE_CLAUSE} together they "
        "are worth respecting. Take today off the bike. If you feel unwell, rest until "
        "it settles, and see your GP if it doesn't."
    )


def _hrv_floor_rule() -> str:
    """The acute HRV floor's rule, for the model and the working (Batches 273, 294)."""
    return (
        f"his own median over the window, minus "
        f"{HRV_ACUTE_DROP_STDDEVS} standard deviations of it — a personal "
        f"floor, not a population band, and not Garmin's. {BELOW_FLOOR}; it rests the "
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
    delta_from_median = round(delta, 1) if delta is not None else None
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
                f"Resting heart rate {current} bpm is {_number(delta_from_median)} bpm "
                f"above the personal median of {_number(median_value)}."
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
                "Resting heart rate has been above the personal upper quartile of "
                f"{_number(upper_quartile)} bpm for two mornings: one thing a little off."
            )
            escalation = _rhr_mild_notice(current, median_value)
    return {
        "triggered": triggered,
        "verdictImpact": GRADED_SIGNAL_IMPACT,
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
        "deltaFromMedianBpm": delta_from_median,
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
    leave_out: frozenset[date] = frozenset(),
) -> dict[str, Any]:
    """Last night's HRV against Mark's own 84-day history (Batch 246, graded in 294).

    Below his median minus 1.5 SD last night is one thing a little off. It rests the bike only
    at an illness-grade drop (at least 2.5 SD or 30% under the median), or when the
    capped drop comes with a second sign: the resting-heart-rate rail, or a symptom
    he reported. ``corroborated_by`` names those signs; the caller decides them.
    ``leave_out`` names nights his normal does not count while enough others remain
    (Batch 311 (e), a replay switch that is off in production).
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
    # Batch 311 (e), off in production: leave the named nights out of his normal, but
    # only while enough remain for the rail to judge; otherwise his normal keeps them.
    kept = [observation for observation in observations if observation[0] not in leave_out]
    if len(kept) >= ACUTE_BASELINE_MIN_SAMPLES:
        observations = kept
    values = [value for _, value in observations]
    enough_history = len(values) >= ACUTE_BASELINE_MIN_SAMPLES
    median_value = float(median(values)) if enough_history else None
    stddev_value = float(pstdev(values)) if enough_history else None
    # Batch 317 (Decision #450): his usual HRV, the one every Mark-facing line quotes, is
    # the mean of these same nights, the number his 7-day reading is judged against. The
    # floor below stays the median's, so no morning changes colour.
    usual_value = sum(values) / len(values) if enough_history else None
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
            _window_words(observations[0][0], observations[-1][0]) if observations else ""
        )
        reason = (
            f"Overnight HRV {current} ms is below the acute personal floor of "
            f"{_number(round(threshold, 2) if threshold is not None else None)} ms."
        )
        # Mark-facing wording, signed off by Craig on Mark's behalf on 28 Sep 2026
        # (docs/drafts/2026-09-28-batch-294-wording.md). The illness-grade line is the
        # one this rail has always written.
        if illness_grade:
            reason = (
                f"Overnight HRV {current} ms is an illness-grade drop, at or under "
                f"{_number(round(illness_line, 2) if illness_line is not None else None)} ms."
            )
            escalation = (
                f"Your overnight HRV is {current} ms this morning against a usual "
                f"{_usual_ms(usual_value)} ms{history_window} — a drop that size in a single "
                "night is unusual "
                "for you. It usually means one of: an infection starting, a heavy drink, a "
                "badly broken night, or real stress carried into sleep. Training hard through "
                "it tends to deepen it. Take today off the bike, and if you feel unwell "
                "alongside it, see your GP rather than just resting."
            )
        elif requires_bike_rest:
            escalation = _hrv_corroborated_notice(
                current,
                usual_value,
                _hrv_corroboration_clause(corroboration, symptom_answer),
            )
        else:
            escalation = _hrv_mild_notice(current, usual_value)
    return {
        "triggered": triggered,
        "verdictImpact": GRADED_SIGNAL_IMPACT,
        "requiresBikeRest": requires_bike_rest,
        "illnessGrade": illness_grade,
        "corroboratedBy": corroboration,
        "currentMs": current,
        "baselineMedianMs": median_value,
        "usualMs": round(usual_value, 2) if usual_value is not None else None,
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
                    rule=_hrv_floor_rule(),
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
        spo2_window = _baseline_window_words(spo2_baseline)
        respiration_window = _baseline_window_words(respiration_baseline)
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
            # Batch 353: the brief's plain words (Decision #440) for the notice: his lowest
            # reading, not a nadir, and the top of his usual range, not an upper quartile.
            opening = (
                f"Your watch recorded a lowest oxygen reading of {_number(nadir_spo2)}% last "
                f"night, below {SPO2_NADIR_ALERT_THRESHOLD_PCT:.0f}% on {len(nadir_nights)} of "
                f"the last {SPO2_NADIR_WINDOW_DAYS} nights. Its usual overnight average is "
                f"{_number(spo2_median)}%{spo2_window}, and your breathing rate has stayed "
                f"above its usual range (up to {_number(respiration_q3)}{respiration_window}) "
                "for two nights."
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


def acute_physiology_rail(
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
    chest_follow_up: ChestFollowUp | None = None,
    hrv_normal_leaves_out: frozenset[date] = frozenset(),
) -> dict[str, Any]:
    """The floors and surveillance for one morning, against his own history."""
    # Batch 294: the symptom answer is a medical floor, and a second sign for the HRV
    # dip. It leads the notices because it is the one Mark gave the app himself.
    # Batch 303: ``symptom_easing`` is what follows a symptom on a morning with no
    # floor of its own; a floor set today drops it. Batch 315: ``chest_follow_up`` is
    # recorded whatever today's floor is, so the next morning can carry it on.
    symptoms = symptom_signal(symptom_answer, easing=symptom_easing, follow_up=chest_follow_up)
    # Batch 297: where the answer came from — his tap, or his note read by the reader —
    # and, for a note, his words.
    symptoms["source"] = symptom_source if symptom_answer is not None else None
    symptoms["words"] = symptom_words if symptom_source == "notes" else None
    # A floor applies whenever it is set; the graded verdict puts it first (Batch 294).
    symptoms["applied"] = bool(symptoms["triggered"])
    rhr = _rhr_rail(
        daily_metric,
        baselines.get("resting_heart_rate_bpm"),
        recent_daily_metrics,
    )
    hrv = _hrv_rail(
        daily_metric,
        recent_daily_metrics,
        leave_out=hrv_normal_leaves_out,
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
        # The app heads a single mild sign "Counted in today's call" only on these words
        # (Batch 298). A morning stored before 298 carries none.
        "gradedWording": True,
    }


def verdict_context(
    *,
    daily_metric: DailyMetric | None,
    sleep: Sleep | None,
    age_adjusted_sleep_score: int | None,
    manual_entries: Sequence[ManualEntry],
    planned_workouts: Sequence[PlannedWorkout],
    baselines: Mapping[str, MetricBaseline] | None = None,
    yesterday_load: Mapping[str, Any] | None = None,
    readiness_baseline_trend: Mapping[str, Any] | None = None,
    rest_day: Mapping[str, Any] | None = None,
    recent_daily_metrics: Sequence[DailyMetric] = (),
    recent_sleeps: Sequence[Sleep] = (),
    notes_symptom_answer: str | None = None,
    notes_symptom_words: str | None = None,
    symptom_easing: Mapping[str, Any] | None = None,
    follow_up_symptom_answer: str | None = None,
    chest_follow_up: ChestFollowUp | None = None,
    hrv_normal_leaves_out: frozenset[date] = frozenset(),
) -> dict[str, Any]:
    """What the graded verdict reads this morning, and what the packet carries beside it.

    The acute rail (``acutePhysiology``: the floors) and the context fields of
    :data:`CONTEXT_FIELDS`. No colour: the graded verdict sets it (Batch 308).
    """
    subjective_score = _latest_subjective_score(manual_entries)
    # Batch 315: "Still there" on Home's chest or heart follow-up is his own answer that
    # the symptoms are back, so it counts as a tapped "Chest or heart".
    tapped_answer = more_severe_symptom(
        latest_symptom_answer(manual_entries), follow_up_symptom_answer
    )
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
    acute_physiology = acute_physiology_rail(
        daily_metric=daily_metric,
        sleep=sleep,
        baselines=baselines or {},
        recent_daily_metrics=recent_daily_metrics,
        recent_sleeps=recent_sleeps,
        symptom_answer=symptom_answer,
        symptom_source=symptom_source,
        symptom_words=notes_symptom_words,
        symptom_easing=symptom_easing,
        chest_follow_up=chest_follow_up,
        hrv_normal_leaves_out=hrv_normal_leaves_out,
    )
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
    return {
        "readinessLevel": daily_metric.readiness_level if daily_metric else None,
        "ageAdjustedSleepScore": age_adjusted_sleep_score,
        "subjectiveScore": subjective_score,
        "subjectiveLabel": subjective_score_label(subjective_score),
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": _hrv_below_baseline(daily_metric),
        "readinessBaselineTrend": readiness_trend,
        "acutePhysiology": acute_physiology,
        "yesterdayLoadStatus": (yesterday_load or {}).get("status"),
        "dayType": "rest" if is_rest_day else "training",
        "isRestDay": is_rest_day,
        "restDayReason": rest_day.get("reason"),
        "hasVo2WorkoutToday": has_vo2,
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


#: Batch 313: the plan line of an ordinary rest day, a day with nothing planned inside a
#: week the plan covers. A holiday and a day of skipped sessions keep the paused line.
PLANNED_REST_PLAN_LINE = "Today is a planned rest day."
PLANNED_REST_REASON = "planned_rest"


#: The line that marks a planned light reset week (Batch 243), first on any day of one.
RESET_WEEK_LINE = (
    "This week is an intended light reset; judge the reduced cycling load as planned "
    "deload, not missed load."
)


def _live_workouts(planned_workouts: Sequence[PlannedWorkout]) -> list[PlannedWorkout]:
    return [
        workout for workout in planned_workouts if workout.status not in {"completed", "skipped"}
    ]


def _with_reset_week(lines: list[str], live: Sequence[PlannedWorkout]) -> list[str]:
    if any(_is_reset_week_workout(workout) for workout in live):
        lines.insert(0, RESET_WEEK_LINE)
    return lines


def _no_session_lines(
    planned_workouts: Sequence[PlannedWorkout],
    *,
    is_rest_day: bool = False,
    rest_reason: str | None = None,
) -> list[str]:
    """The plan line of a day with no live session to change, whatever the colour.

    A rest day (a holiday, every session skipped, or since Batch 313 nothing planned
    inside a plan week), no plan at all, or every session already done or skipped.
    """
    live = _live_workouts(planned_workouts)
    if is_rest_day and rest_reason == PLANNED_REST_REASON:
        lines = [PLANNED_REST_PLAN_LINE]
    elif is_rest_day:
        lines = ["Today is an intentional rest day; keep paused or skipped sessions paused."]
    elif not planned_workouts:
        lines = ["No active planned workout found for today; keep advice conservative."]
    else:
        lines = ["No live workout remains today; do not revive completed or skipped sessions."]
    return _with_reset_week(lines, live)


def _red_plan_lines(planned_workouts: Sequence[PlannedWorkout]) -> list[str]:
    """A Red day's plan line for its ride (Batch 215).

    Red does not mean one thing: an already-Zone-2 ride keeps its intensity and takes a
    light duration cut, so the instruction follows the transform rather than asserting a
    substitution that did not happen. Batch 252.4 keys on the endurance *path*, not on
    whether the number moved: a 68-75% ride is eased to the 67% anchor and is still
    Zone 2.
    """
    adjustment = _red_ride_adjustment(planned_workouts)
    if isinstance(adjustment, Mapping) and adjustment.get("keptAsEndurance"):
        lines = [
            f"Hold Zone 2 (~{adjustment.get('adjustedWorkPowerPct')}% FTP) and cut to "
            f"{adjustment.get('adjustedDurationMin')} min; no intervals and no HIT/VO2. "
            "Sustained easy work builds sleep pressure — keep it, do not delete it."
        ]
    else:
        lines = ["Substitute recovery, mobility, or rest."]
    return _with_reset_week(lines, _live_workouts(planned_workouts))


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
# The colour comes from ``services.verdict_grading``; the acute rail above supplies its
# floors. Mark-facing lines signed off by Craig on Mark's behalf on 29 Sep 2026
# (docs/drafts/2026-09-29-batch-296-wording.md).


GRADED_MOVE_LINE = (
    "Move {title} to a better day this week if there is one; otherwise ride it and hold "
    "the targets."
)
#: Batch 336 (CI330-03): a test is ridden as planned or moved, never eased. Signed off
#: by Craig on 28 Oct (docs/drafts/2026-10-28-batch-336-wording.md).
GRADED_TEST_MOVE_LINE = (
    "Move {title} to a fresher day this week if there is one; if not, ride it as planned. "
    "A test ridden tired or eased gives a low FTP, and your sessions are set from it."
)
GRADED_EASE_HARD_LINE = "Ease the hard intervals a zone; the rest of the session stays as planned."
GRADED_ZONE_TWO_LINE = "Keep your Zone 2 ride at full length."
#: Batch 298: the week is named as his plan names it (signed off 1 Oct 2026); W12 is a
#: consolidation week and W13 a taper, and both were "a planned recovery week".
GRADED_LIGHT_WEEK_LINE = (
    "This is your planned {week} week, so today's session stays as planned: hold the targets."
)
GRADED_RECOVERY_WEEK_LINE = GRADED_LIGHT_WEEK_LINE.format(week="recovery")
#: Batch 306: a tired morning's choices, signed off by Craig on Mark's behalf on 3 Oct
#: 2026. The caps are the transforms' own, so the words and the ride cannot disagree.
GRADED_PICK_LINE = (
    "Short on sleep or feeling flat, so pick how to ride {title} today: easy Zone 2 "
    f"(nothing above {ENDURANCE_CEILING_PCT}% FTP) or tempo (nothing above {TEMPO_CAP_PCT}%), "
    "full length either way."
)
GRADED_OFFER_SHORTER_LINE = (
    "Keep your Zone 2 ride at full length, or ride a shorter version if you'd rather "
    "({short} min instead of {full})."
)
BIKE_REST_PLAN_LINE = (
    "Take today off the bike; do not substitute an eased ride for the acute signal."
)


#: What the morning packet carries beside the graded verdict (Batch 308): his readings and
#: the plan facts the brief and Home read. An allow-list: a field reaches the packet, the
#: brief and the coach only when it is named here. Until 308 the packet was the ladder's
#: minus the fields the graded verdict did not have, so anything added to the ladder
#: reached the model unless someone remembered to leave it out (CR327-03).
CONTEXT_FIELDS = (
    "readinessLevel",
    "ageAdjustedSleepScore",
    "subjectiveScore",
    "subjectiveLabel",
    "hrvStatus",
    "hrvBelowBaseline",
    "readinessBaselineTrend",
    "yesterdayLoadStatus",
    "dayType",
    "isRestDay",
    "restDayReason",
    "hasVo2WorkoutToday",
)


def graded_plan_adjustments(
    graded: Any,
    planned_workouts: Sequence[PlannedWorkout],
    *,
    is_rest_day: bool,
    acute: Mapping[str, Any],
    has_vo2: bool,
    rest_reason: str | None = None,
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
        return _no_session_lines(planned_workouts, is_rest_day=is_rest_day, rest_reason=rest_reason)
    if graded.status == "Red":
        red_lines = _red_plan_lines(planned_workouts)
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
        elif action == ACTION_MOVE_TEST:
            line = GRADED_TEST_MOVE_LINE.format(title=workout.title or "the test")
        elif action == "ease_hard":
            line = GRADED_EASE_HARD_LINE
        elif action == "recovery":
            # Batch 303: below Red only what follows a symptom swaps a hard session
            # for an easy spin (an easy day back after a fever, an open chest question).
            line = EASY_RIDING_PLAN_LINE
        elif action == ACTION_PICK_ZONE2_OR_TEMPO:
            line = GRADED_PICK_LINE.format(title=workout.title or "the hard session")
        elif action == ACTION_OFFER_SHORTER:
            minutes = offered_shorter_minutes(workout)
            line = (
                GRADED_OFFER_SHORTER_LINE.format(short=minutes[0], full=minutes[1])
                if minutes is not None
                else GRADED_ZONE_TWO_LINE
            )
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
    return _with_reset_week(lines, live)


def graded_verdict_packet(
    context: Mapping[str, Any],
    graded: Any,
    planned_workouts: Sequence[PlannedWorkout],
    *,
    breathwork_line: str | None,
) -> dict[str, Any]:
    """The morning packet's verdict: the context, and what the graded verdict set.

    ``context`` is :func:`verdict_context`'s. The packet carries the acute rail and
    :data:`CONTEXT_FIELDS`, then the colour, reasons, plan lines and safety rules the
    graded verdict set, with ``engine``, ``held`` and ``graded``.
    """

    acute = context["acutePhysiology"]
    is_rest_day = bool(context.get("isRestDay"))
    has_vo2 = bool(context.get("hasVo2WorkoutToday"))
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
    trend = context.get("readinessBaselineTrend")
    if (
        isinstance(trend, Mapping)
        and trend.get("triggered")
        and isinstance(trend.get("reason"), str)
    ):
        reasons.append(str(trend["reason"]))

    plan = graded_plan_adjustments(
        graded,
        planned_workouts,
        is_rest_day=is_rest_day,
        acute=acute,
        has_vo2=has_vo2,
        rest_reason=(
            str(context["restDayReason"]) if isinstance(context.get("restDayReason"), str) else None
        ),
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
            else "chest_follow_up_easy_riding"
            if graded.easing == EASING_CHEST_FOLLOW_UP
            else "fever_return_easy_riding"
        )
    oxygen = acute.get("oxygenRespiration")
    if isinstance(oxygen, Mapping) and oxygen.get("triggered") is True:
        safety.append("oxygen_respiration_surveillance")
    if graded.missing_data_floor_applied:
        safety.append("missing_data_amber_floor")
    if status == "Red" and has_vo2:
        safety.append("red_never_vo2")

    packet: dict[str, Any] = {key: context.get(key) for key in CONTEXT_FIELDS}
    packet["acutePhysiology"] = copy.deepcopy(dict(acute))
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


def offered_shorter_minutes(workout: PlannedWorkout) -> tuple[int, int] | None:
    """``(shorter, full)`` minutes of the long ride a tired morning offers (Batch 306).

    Read off the ride the delivery rail would upload, so the line quotes it exactly.
    """
    try:
        base_ir = build_structured_workout_ir(workout)
    except HTTPException:
        return None
    full = int(base_ir.get("totalDurationSec") or 0)
    shorter = int(
        adjust_ir_for_verdict(base_ir, TRANSFORM_SHORTER, graded=True).get("totalDurationSec") or 0
    )
    if full <= 0 or shorter <= 0 or shorter >= full:
        return None
    return round(shorter / 60), round(full / 60)


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
    packet: dict[str, Any] = {**summary, "plannedWorkoutId": str(ride.id)}
    # Batch 306: on a tired morning the ride is his choice, and until he makes it the
    # planned session stands. The figures above are the version offered first.
    if action == ACTION_PICK_ZONE2_OR_TEMPO:
        packet["choice"] = {
            "kind": "pick",
            "untilPicked": "as_planned",
            "options": [
                {
                    "variant": "zone2",
                    "transform": TRANSFORM_TIRED_ZONE2,
                    "capPct": ENDURANCE_CEILING_PCT,
                },
                {"variant": "tempo", "transform": TRANSFORM_TIRED_TEMPO, "capPct": TEMPO_CAP_PCT},
            ],
        }
    elif action == ACTION_OFFER_SHORTER:
        packet["choice"] = {"kind": "offer", "untilPicked": "as_planned"}
    return packet
