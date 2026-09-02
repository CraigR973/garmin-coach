"""Deterministic morning verdict policy and its supporting transforms.

Batch 245 extracts the app's central safety decision from the packet/model
orchestrator. This module is deliberately model-free and database-free: callers
supply already-loaded rows and receive a deterministic packet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from fastapi import HTTPException

from src.models.coaching import DailyMetric, ManualEntry, MetricBaseline, PlannedWorkout, Sleep
from src.services.breathwork_brief import BreathworkBriefResult
from src.services.personal_baselines import (
    SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,
    baseline_center,
    effective_readiness_floor,
    metric_within_baseline_band,
)
from src.services.verdict_scaling import (
    AMBER_POWER_CAP_PCT,
    companion_session_present,
    ir_has_vo2,
    summarize_verdict_adjustment,
)
from src.services.workout_categories import is_bike_workout_type
from src.services.workout_delivery import build_structured_workout_ir

# Batch 167 (#248): load can only harden the deterministic light.
ACWR_AMBER_CAP_THRESHOLD = 1.5
RECOVERY_TIME_AMBER_CAP_MIN = 24 * 60
# A Low-readiness exception needs affirmative balanced-load evidence.
ACWR_LOAD_DRIVEN_MAX = 1.3


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
) -> dict[str, Any]:
    subjective_score = _latest_subjective_score(manual_entries)
    hrv_status = _lower(daily_metric.hrv_status if daily_metric else None) or _lower(
        sleep.hrv_status if sleep else None
    )
    hrv_low = _hrv_below_baseline(daily_metric)
    readiness_level = _lower(daily_metric.readiness_level if daily_metric else None)
    baselines = baselines or {}
    resting_hr_baseline = baselines.get("resting_heart_rate_bpm")
    resting_hr_in_band = metric_within_baseline_band(
        daily_metric.resting_heart_rate_bpm if daily_metric else None,
        resting_hr_baseline,
        lower_is_better=True,
    )
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
    elif hrv_low and hrv_status in {"unbalanced", "low"}:
        status = "Red"
        reasons.append("HRV is below baseline and marked low/unbalanced.")
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
        status = "Amber"
        reasons.append("HRV is not cleanly in range.")
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

    status_before_load_cap = status
    if training_load_cap["triggered"]:
        if status == "Green":
            status = "Amber"
            training_load_cap["applied"] = True
        reasons.extend(training_load_cap["reasons"])
    training_load_cap["statusBeforeCap"] = status_before_load_cap
    baseline_trend_reason = readiness_trend.get("reason")
    if readiness_trend.get("triggered") and isinstance(baseline_trend_reason, str):
        reasons.append(baseline_trend_reason)

    plan_adjustments = _plan_adjustments(
        status,
        planned_workouts,
        is_rest_day=is_rest_day,
    )
    if status != "Green" and yesterday_hard and not is_rest_day:
        plan_adjustments.append(
            "Treat yesterday's hard session as extra context for easing today's work."
        )
    if status == "Red" and has_vo2:
        plan_adjustments.append("Replace VO2 with rest, mobility, or a very easy spin.")
    breathwork_signal = {
        "status": status,
        "readinessLevel": readiness_level,
        "readinessInterpretation": readiness_interpretation,
        "hrvStatus": hrv_status,
        "hrvBelowBaseline": hrv_low,
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
    elif status == "Amber":
        adjustments = [
            "Cut duration 25%; hold Zone 2, ease harder intervals by a zone, and "
            f"convert former HIT/VO2 work to no more than {AMBER_POWER_CAP_PCT}% FTP "
            "(Sweet Spot)."
        ]
    else:
        # Batch 215: Red no longer means one thing. An already-Zone-2 ride keeps its
        # intensity and takes a light duration cut, so the instruction has to follow
        # the transform rather than assert a substitution that did not happen.
        adjustment = _verdict_adjustment_packet(status, planned_workouts)
        if isinstance(adjustment, Mapping) and adjustment.get("intensityHeldAtEndurance"):
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
