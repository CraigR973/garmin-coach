"""The graded verdict: rate independent domains, then combine (Batch 295).

The ladder in ``morning_verdict`` lets the first matching rule decide the day, so
one marginal signal can turn a morning Red: 21 of Mark's 98 mornings from 21 Jun to
27 Sep 2026 were Red, 12 of them on one HRV rule. The 28 Sep review
(``docs/reviews/verdict-grading-review-2026-09-28.md``) replaced that with graded
evidence, and this module is the engine:

1. **Floors first** (Batch 294): a reported symptom, an illness-grade HRV drop, or a
   resting-heart-rate jump of 7 bpm. They come from the ladder's own acute rail, so
   the two can never disagree about a floor.
2. **Rate each domain** ``none``, ``mild`` or ``marked`` against Mark's own normal,
   taking the worst signal inside it:

   * **autonomic** — last night's HRV, his 7-day HRV against his own baseline, and
     his resting heart rate;
   * **sleep** — the sleep score and total sleep;
   * **load** — the acute:chronic ratio, Garmin's recovery time and yesterday's load;
   * **subjective** — his check-in feel against his own mean and spread.

   Garmin readiness mostly restates his sleep and recovery time (r 0.69 and −0.72
   over 99 mornings), so it never votes on its own: it can only confirm a mild
   sleep or load domain into a marked one. Garmin's HRV status and band are context
   for the brief and are not read here at all.
3. **Combine across domains**: Red when two or more are marked or he says he feels
   Rough; Amber when one is marked or two or more are mild; Green with the targets
   held when one is mild; Green otherwise.

Everything here is pure, like ``morning_verdict`` since Batch 245: callers supply
plain values and receive a deterministic result. Nothing live reads it yet — Batch
295 builds it beside the ladder and replays it over every stored morning
(``services/verdict_replay.py``); Batch 296 switches the colour.

Every line the engine uses is in :data:`THRESHOLDS`, with its value, unit, source and
reason, so the replay report, the provenance and the tests read the same numbers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Final, Literal

from fastapi import HTTPException

from src.services.verdict_scaling import ir_has_vo2, ir_is_endurance
from src.services.workout_categories import is_bike_workout_type
from src.services.workout_delivery import build_structured_workout_ir

Rating = Literal["none", "mild", "marked"]
RATING_ORDER: Final[dict[str, int]] = {"none": 0, "mild": 1, "marked": 2}

DOMAIN_AUTONOMIC: Final = "autonomic"
DOMAIN_SLEEP: Final = "sleep"
DOMAIN_LOAD: Final = "load"
DOMAIN_SUBJECTIVE: Final = "subjective"
DOMAINS: Final = (DOMAIN_AUTONOMIC, DOMAIN_SLEEP, DOMAIN_LOAD, DOMAIN_SUBJECTIVE)

FLOOR_NO_TRAINING: Final = "no_training"
FLOOR_EASY_RIDING: Final = "easy_riding"
FLOOR_BIKE_REST: Final = "bike_rest"

ACTION_AS_PLANNED: Final = "as_planned"
ACTION_HOLD_TARGETS: Final = "hold_targets"
ACTION_MOVE_OR_HOLD: Final = "move_or_hold"
ACTION_EASE_HARD: Final = "ease_hard"
ACTION_RECOVERY: Final = "recovery"
ACTION_SHORTENED_Z2: Final = "shortened_zone2"
ACTION_OFF_THE_BIKE: Final = "off_the_bike"
ACTION_NO_TRAINING: Final = "no_training"


@dataclass(frozen=True, slots=True)
class Threshold:
    """One line the engine uses, stated once (295.4)."""

    key: str
    value: float
    units: str
    source: str
    reason: str


def _threshold(key: str, value: float, units: str, source: str, reason: str) -> Threshold:
    return Threshold(key=key, value=value, units=units, source=source, reason=reason)


#: Every line the graded verdict uses. The replay report prints this table, the
#: provenance cites it, and the tests read it rather than repeating the numbers.
THRESHOLDS: Final[dict[str, Threshold]] = {
    item.key: item
    for item in (
        _threshold(
            "hrv_baseline_window_days",
            84,
            "days",
            "the acute HRV rail's window (Batch 246)",
            "His HRV normal is the nights before this morning over the same window the "
            "acute rail uses, so there is one definition of his normal. Replayed, 28, 56 "
            "and 84 days put 16, 15 and 13 of 75 mornings below the smallest worthwhile "
            "change: the choice barely matters, and 84 is the most stable.",
        ),
        _threshold(
            "hrv_baseline_min_nights",
            21,
            "nights",
            "the acute HRV rail (Batch 246)",
            "Fewer nights than this and his normal is not yet known, so HRV rates nothing.",
        ),
        _threshold(
            "hrv_week_nights",
            7,
            "nights",
            "Plews 2013; Javaloyes 2019",
            "The HRV-guided trials judge a 7-day rolling mean, not a single night, "
            "because one night swings several ms around his normal.",
        ),
        _threshold(
            "hrv_week_min_nights",
            4,
            "nights",
            "engineering choice",
            "A week with fewer readings than this is too thin to call a trend.",
        ),
        _threshold(
            "hrv_swc_sd",
            0.5,
            "SD of nightly HRV",
            "the smallest worthwhile change in the HRV-guided trials (Plews 2013; Javaloyes 2019)",
            "A 7-day mean more than half a standard deviation under his normal is a real "
            "shift, not noise: mild. For him that is about 2.5 ms.",
        ),
        _threshold(
            "hrv_week_marked_sd",
            1.0,
            "SD of nightly HRV",
            "twice the smallest worthwhile change; set from the replay",
            "A week this far down is marked. His lowest 7-day mean in three months was "
            "0.83 SD under his normal (22 Sep), so this has not fired yet; it is for a "
            "genuinely suppressed week.",
        ),
        _threshold(
            "hrv_recovery_min_nights",
            7,
            "nights",
            "Batch 275 (his recovery-week HRV averages 45.3 ms against 48.1 ms)",
            "In a recovery or taper week his HRV is judged against earlier recovery and "
            "taper nights, so the expected dip is not read as strain. With fewer earlier "
            "recovery nights than this, his ordinary normal applies.",
        ),
        _threshold(
            "resting_hr_rise_mild_bpm",
            4,
            "bpm over his median",
            "his own spread: about 1.7 bpm, so 4 is about 2.4 SD",
            "One morning this far up is mild; so are two mornings above his usual range "
            "(the review, MD-3), which on its own is no longer a cap.",
        ),
        _threshold(
            "resting_hr_rise_marked_bpm",
            5,
            "bpm over his median",
            "about 3 SD for him",
            "Marked. 7 bpm or more stays the off-the-bike floor (Batch 293).",
        ),
        _threshold(
            "sleep_score_mild_below",
            74,
            "age-adjusted sleep score",
            "the app's Green line for sleep (Batch 61)",
            "A fair night is mild.",
        ),
        _threshold(
            "sleep_score_marked_below",
            60,
            "age-adjusted sleep score",
            "the app's Red line for sleep (Batch 61)",
            "A very poor night is marked, and on its own that is Amber, not Red: easy "
            "riding is fine after a poor night and helps rebuild sleep pressure "
            "(Batch 215; the review, CO-3).",
        ),
        _threshold(
            "sleep_duration_window_days",
            84,
            "days",
            "the app's personal-baseline window",
            "His usual total sleep is the nights before this morning over 84 days.",
        ),
        _threshold(
            "sleep_duration_min_nights",
            21,
            "nights",
            "the app's personal-baseline minimum",
            "Fewer nights than this and total sleep rates nothing.",
        ),
        _threshold(
            "sleep_duration_mild_sd",
            1.5,
            "SD of his total sleep",
            "set from the replay",
            "About 6.4 hours for him (usual 7.5 ± 0.75 h): mild. Replayed, 11 of 99 nights.",
        ),
        _threshold(
            "sleep_duration_marked_sd",
            2.5,
            "SD of his total sleep",
            "set from the replay",
            "About 5.6 hours for him: marked. Replayed, 5 of 99 nights, four of them "
            "already very poor by the score.",
        ),
        _threshold(
            "acwr_mild",
            1.3,
            "acute:chronic load ratio",
            "the top of the balanced range the app already uses (Batch 201)",
            "A ramp above the balanced range is mild.",
        ),
        _threshold(
            "acwr_marked",
            1.5,
            "acute:chronic load ratio",
            "the app's load cap (Batch 167)",
            "A fast ramp is marked, as it caps the day at Amber today.",
        ),
        _threshold(
            "recovery_time_mild_hours",
            24,
            "hours",
            "the app's load cap (Batch 167)",
            "More than a day of Garmin recovery time left is mild: fine for an easy "
            "session, a reason to move a hard one.",
        ),
        _threshold(
            "recovery_time_marked_hours",
            48,
            "hours",
            "set from the replay",
            "More than two days left is marked. His highest at wake in three months was 47 "
            "hours, so this is for an unusual debt.",
        ),
        _threshold(
            "feel_window_days",
            84,
            "days",
            "the app's personal-baseline window",
            "His usual feel is his morning check-ins over the 84 days before this one.",
        ),
        _threshold(
            "feel_min_check_ins",
            14,
            "check-ins",
            "engineering choice",
            "With fewer scored check-ins than this his spread is not yet known, and the "
            "fallback lines below apply.",
        ),
        _threshold(
            "feel_mild_sd",
            1.0,
            "SD of his feel",
            "the review (his feel tracks his physiology, r 0.4-0.6; Saw 2016)",
            "Feeling a standard deviation below his usual is mild. For him (6.6 ± 1.0) "
            "that is 5 or lower.",
        ),
        _threshold(
            "feel_marked_sd",
            2.0,
            "SD of his feel",
            "the review",
            "Two standard deviations below is marked: 4 or lower for him.",
        ),
        _threshold(
            "feel_rough_max",
            3,
            "feel score (0-10)",
            "the check-in's own word for 0-3 (Batch 146)",
            "Rough on its own makes the day Red: only his own taps may relax the day, and "
            "this one never relaxes it.",
        ),
        _threshold(
            "feel_fallback_mild_max",
            5,
            "feel score (0-10)",
            "his own lines on 28 Sep 2026",
            "Mild when his spread is not yet known.",
        ),
        _threshold(
            "feel_fallback_marked_max",
            4,
            "feel score (0-10)",
            "his own lines on 28 Sep 2026",
            "Marked when his spread is not yet known.",
        ),
        _threshold(
            "long_ride_minutes",
            120,
            "minutes",
            "his plan's long endurance rides (up to 150 minutes)",
            "A ride this long is a key session even at Zone 2.",
        ),
    )
}


def _t(key: str) -> float:
    return THRESHOLDS[key].value


@dataclass(frozen=True, slots=True)
class PlannedSession:
    """One live session today, classified for the session-aware actions."""

    id: str | None
    title: str | None
    workout_type: str | None
    planned_minutes: int | None
    is_bike: bool
    #: Anything above Zone 2 (the scaling rule's own endurance test).
    is_hard: bool
    has_vo2: bool
    #: VO2, threshold-type work or a long ride: the sessions under-training costs.
    is_key: bool


@dataclass(frozen=True, slots=True)
class GradingInputs:
    """Everything the engine reads, as plain values."""

    subject_date: date
    #: The ladder's ``acutePhysiology`` packet: the floors, the HRV and resting-heart-rate
    #: rails and data sufficiency, computed once by ``morning_verdict``.
    acute: Mapping[str, Any]
    #: Nightly overnight HRV since readings became reliable, up to and including last
    #: night, as ``(date, ms)``.
    hrv_nights: tuple[tuple[date, float], ...] = ()
    #: Nights inside a recovery or taper block (Batch 275's grouping).
    recovery_week_nights: frozenset[date] = frozenset()
    #: Is this morning inside a recovery or taper block? (his recovery-week HRV normal)
    in_recovery_week: bool = False
    #: Is this morning inside a recovery, taper or consolidation block? (actions hold)
    recovery_class_block: bool = False
    sleep_score_raw: int | None = None
    sleep_score_age_adjusted: int | None = None
    sleep_minutes: float | None = None
    #: Total sleep in minutes on the nights before this morning, inside the window.
    sleep_minutes_history: tuple[float, ...] = ()
    acwr: float | None = None
    recovery_time_min: float | None = None
    yesterday_load: str | None = None
    feel: int | None = None
    #: His morning feel scores before this morning, inside the window.
    feel_history: tuple[int, ...] = ()
    readiness_level: str | None = None
    readiness_score: float | None = None
    readiness_lower_quartile: float | None = None
    sessions: tuple[PlannedSession, ...] = ()
    rest_day: bool = False


@dataclass(frozen=True, slots=True)
class SignalReading:
    domain: str
    signal: str
    rating: Rating
    value: float | None
    reference: str | None
    reason: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "signal": self.signal,
            "rating": self.rating,
            "value": self.value,
            "reference": self.reference,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DomainRating:
    domain: str
    rating: Rating
    signals: tuple[SignalReading, ...] = ()
    confirmed_by_readiness: bool = False

    def to_packet(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "rating": self.rating,
            "confirmedByReadiness": self.confirmed_by_readiness,
            "signals": [signal.to_packet() for signal in self.signals if signal.rating != "none"],
        }


@dataclass(frozen=True, slots=True)
class SessionAction:
    session_id: str | None
    title: str | None
    workout_type: str | None
    is_key: bool
    is_hard: bool
    action: str
    detail: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "plannedWorkoutId": self.session_id,
            "title": self.title,
            "workoutType": self.workout_type,
            "isKey": self.is_key,
            "isHard": self.is_hard,
            "action": self.action,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GradedVerdict:
    status: str
    #: Green with the targets held: exactly one domain is mild.
    held: bool
    domains: tuple[DomainRating, ...]
    floor: str | None
    reasons: tuple[str, ...]
    rough_check_in: bool = False
    age_credit_guard_applied: bool = False
    missing_data_floor_applied: bool = False
    actions: tuple[SessionAction, ...] = field(default_factory=tuple)

    def domain(self, name: str) -> DomainRating:
        return next(item for item in self.domains if item.domain == name)

    @property
    def label(self) -> str:
        return "Green (held)" if self.held else self.status

    def to_packet(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "held": self.held,
            "floor": self.floor,
            "roughCheckIn": self.rough_check_in,
            "ageCreditGuardApplied": self.age_credit_guard_applied,
            "missingDataFloorApplied": self.missing_data_floor_applied,
            "domains": [item.to_packet() for item in self.domains],
            "reasons": list(self.reasons),
            "actions": [item.to_packet() for item in self.actions],
        }


# -- signals -----------------------------------------------------------------------------


def _worst(ratings: Iterable[Rating]) -> Rating:
    return max(ratings, key=lambda rating: RATING_ORDER[rating], default="none")


def _reading(
    domain: str,
    signal: str,
    rating: Rating,
    value: float | None,
    reason: str,
    reference: str | None = None,
) -> SignalReading:
    return SignalReading(
        domain=domain,
        signal=signal,
        rating=rating,
        value=round(value, 2) if value is not None else None,
        reference=reference,
        reason=reason,
    )


def _mean_sd(values: Sequence[float]) -> tuple[float, float]:
    """Mean and population SD in plain floats (``statistics`` is exact, and slow)."""

    count = len(values)
    centre = sum(values) / count
    return centre, (sum((value - centre) ** 2 for value in values) / count) ** 0.5


def _n(value: Any) -> str:
    """A reading as Mark's devices show it: whole numbers without a trailing .0."""

    number = _as_float(value)
    if number is None:
        return "unknown"
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hrv_week(inputs: GradingInputs) -> SignalReading:
    """His 7-day mean HRV against his own normal (295.3)."""

    day = inputs.subject_date
    week_start = day - timedelta(days=int(_t("hrv_week_nights")) - 1)
    week = [value for night, value in inputs.hrv_nights if week_start <= night <= day]
    window_start = day - timedelta(days=int(_t("hrv_baseline_window_days")))
    baseline = [value for night, value in inputs.hrv_nights if window_start <= night < day]
    if len(week) < _t("hrv_week_min_nights") or len(baseline) < _t("hrv_baseline_min_nights"):
        return _reading(
            DOMAIN_AUTONOMIC,
            "hrv_7_day",
            "none",
            sum(week) / len(week) if week else None,
            "Not enough nights yet to judge his week against his normal.",
        )
    centre, spread = _mean_sd(baseline)
    basis = "his usual"
    if inputs.in_recovery_week:
        recovery = [
            value
            for night, value in inputs.hrv_nights
            if night < week_start and night in inputs.recovery_week_nights
        ]
        if len(recovery) >= _t("hrv_recovery_min_nights"):
            centre = sum(recovery) / len(recovery)
            basis = "his recovery-week usual"
    week_mean = sum(week) / len(week)
    swc = _t("hrv_swc_sd") * spread
    marked_line = centre - _t("hrv_week_marked_sd") * spread
    reference = f"{basis} {centre:.1f} ms, SD {spread:.1f} ms"
    if week_mean < marked_line:
        rating: Rating = "marked"
        reason = (
            f"7-day HRV {week_mean:.1f} ms is more than {_t('hrv_week_marked_sd'):g} SD under "
            f"{basis} {centre:.1f} ms."
        )
    elif week_mean < centre - swc:
        rating = "mild"
        reason = (
            f"7-day HRV {week_mean:.1f} ms is under {basis} {centre:.1f} ms by more than the "
            f"smallest worthwhile change ({swc:.1f} ms)."
        )
    else:
        rating = "none"
        reason = f"7-day HRV {week_mean:.1f} ms is within {basis} range."
    return _reading(DOMAIN_AUTONOMIC, "hrv_7_day", rating, week_mean, reason, reference)


def _hrv_overnight(acute: Mapping[str, Any]) -> SignalReading:
    """Last night's reading, through the acute rail's own arithmetic (Batch 294)."""

    rail = _mapping(acute.get("overnightHrv"))
    current = _as_float(rail.get("currentMs"))
    floor = _as_float(rail.get("acuteFloorMs"))
    if rail.get("illnessGrade") is True:
        return _reading(
            DOMAIN_AUTONOMIC,
            "hrv_overnight",
            "marked",
            current,
            f"Last night's HRV {_n(current)} ms is an illness-grade drop "
            f"(at or under {_n(rail.get('illnessLineMs'))} ms).",
            f"his median {_n(rail.get('baselineMedianMs'))} ms",
        )
    if rail.get("triggered") is True:
        # One low night is noise more often than not: at 1.5 SD it fired on 6 of 75
        # mornings, three by under 1 ms. It counts, but only as mild; the week decides.
        return _reading(
            DOMAIN_AUTONOMIC,
            "hrv_overnight",
            "mild",
            current,
            f"Last night's HRV {_n(current)} ms is under his acute floor of {_n(floor)} ms.",
            f"his median {_n(rail.get('baselineMedianMs'))} ms",
        )
    return _reading(
        DOMAIN_AUTONOMIC, "hrv_overnight", "none", current, "Last night's HRV is not low."
    )


def _resting_hr(acute: Mapping[str, Any]) -> SignalReading:
    rail = _mapping(acute.get("restingHeartRate"))
    current = _as_float(rail.get("currentBpm"))
    delta = _as_float(rail.get("deltaFromMedianBpm"))
    median_bpm = rail.get("baselineMedianBpm")
    reference = f"his median {_n(median_bpm)} bpm" if median_bpm is not None else None
    if rail.get("trigger") == "absolute_delta" or (
        delta is not None and delta >= _t("resting_hr_rise_marked_bpm")
    ):
        return _reading(
            DOMAIN_AUTONOMIC,
            "resting_hr",
            "marked",
            current,
            f"Resting heart rate {_n(current)} bpm is {_n(delta)} bpm over his median.",
            reference,
        )
    if rail.get("trigger") == "consecutive_q3":
        return _reading(
            DOMAIN_AUTONOMIC,
            "resting_hr",
            "mild",
            current,
            f"Resting heart rate {_n(current)} bpm has been above his usual range two mornings.",
            reference,
        )
    if delta is not None and delta >= _t("resting_hr_rise_mild_bpm"):
        return _reading(
            DOMAIN_AUTONOMIC,
            "resting_hr",
            "mild",
            current,
            f"Resting heart rate {_n(current)} bpm is {_n(delta)} bpm over his median.",
            reference,
        )
    return _reading(DOMAIN_AUTONOMIC, "resting_hr", "none", current, "Resting heart rate is usual.")


def _sleep_score(score: int | None, *, signal: str) -> SignalReading:
    if score is None:
        return _reading(DOMAIN_SLEEP, signal, "none", None, "No sleep score.")
    if score < _t("sleep_score_marked_below"):
        return _reading(DOMAIN_SLEEP, signal, "marked", score, f"Sleep score {score} is very poor.")
    if score < _t("sleep_score_mild_below"):
        return _reading(DOMAIN_SLEEP, signal, "mild", score, f"Sleep score {score} is fair.")
    return _reading(DOMAIN_SLEEP, signal, "none", score, f"Sleep score {score} is good.")


def _sleep_duration(inputs: GradingInputs) -> SignalReading:
    minutes = inputs.sleep_minutes
    history = inputs.sleep_minutes_history
    if minutes is None or len(history) < _t("sleep_duration_min_nights"):
        return _reading(DOMAIN_SLEEP, "total_sleep", "none", minutes, "Total sleep not judged.")
    centre, spread = _mean_sd(history)
    reference = f"his usual {centre / 60:.1f} h, SD {spread / 60:.2f} h"
    if spread and minutes < centre - _t("sleep_duration_marked_sd") * spread:
        rating: Rating = "marked"
    elif spread and minutes < centre - _t("sleep_duration_mild_sd") * spread:
        rating = "mild"
    else:
        rating = "none"
    return _reading(
        DOMAIN_SLEEP,
        "total_sleep",
        rating,
        minutes,
        f"Total sleep {minutes / 60:.1f} h against his usual {centre / 60:.1f} h.",
        reference,
    )


def _load(inputs: GradingInputs) -> tuple[SignalReading, ...]:
    readings: list[SignalReading] = []
    acwr = inputs.acwr
    if acwr is not None and acwr >= _t("acwr_marked"):
        readings.append(_reading(DOMAIN_LOAD, "acwr", "marked", acwr, f"Load ratio {acwr:.2f}."))
    elif acwr is not None and acwr >= _t("acwr_mild"):
        readings.append(_reading(DOMAIN_LOAD, "acwr", "mild", acwr, f"Load ratio {acwr:.2f}."))
    else:
        readings.append(_reading(DOMAIN_LOAD, "acwr", "none", acwr, "Load ratio is balanced."))
    hours = inputs.recovery_time_min / 60 if inputs.recovery_time_min is not None else None
    if hours is not None and hours > _t("recovery_time_marked_hours"):
        readings.append(
            _reading(DOMAIN_LOAD, "recovery_time", "marked", hours, f"{hours:.0f} h recovery left.")
        )
    elif hours is not None and hours > _t("recovery_time_mild_hours"):
        readings.append(
            _reading(DOMAIN_LOAD, "recovery_time", "mild", hours, f"{hours:.0f} h recovery left.")
        )
    else:
        readings.append(_reading(DOMAIN_LOAD, "recovery_time", "none", hours, "Recovered."))
    hard_yesterday = (inputs.yesterday_load or "").lower() == "hard"
    readings.append(
        _reading(
            DOMAIN_LOAD,
            "yesterday_load",
            "mild" if hard_yesterday else "none",
            None,
            "Yesterday was a hard day." if hard_yesterday else "Yesterday was not hard.",
        )
    )
    return tuple(readings)


def _feel(inputs: GradingInputs) -> SignalReading:
    feel = inputs.feel
    if feel is None:
        return _reading(DOMAIN_SUBJECTIVE, "feel", "none", None, "No check-in feel.")
    history = [float(score) for score in inputs.feel_history]
    centre, spread = _mean_sd(history) if history else (0.0, 0.0)
    if len(history) >= _t("feel_min_check_ins") and spread > 0:
        reference = f"his usual {centre:.1f}, SD {spread:.1f}"
        if feel <= centre - _t("feel_marked_sd") * spread:
            rating: Rating = "marked"
        elif feel <= centre - _t("feel_mild_sd") * spread:
            rating = "mild"
        else:
            rating = "none"
    else:
        reference = "fallback lines"
        if feel <= _t("feel_fallback_marked_max"):
            rating = "marked"
        elif feel <= _t("feel_fallback_mild_max"):
            rating = "mild"
        else:
            rating = "none"
    return _reading(DOMAIN_SUBJECTIVE, "feel", rating, feel, f"He said {feel}.", reference)


def _readiness_low(inputs: GradingInputs) -> bool:
    level = (inputs.readiness_level or "").lower()
    if level in {"low", "poor"}:
        return True
    return (
        inputs.readiness_score is not None
        and inputs.readiness_lower_quartile is not None
        and inputs.readiness_score < inputs.readiness_lower_quartile
    )


def _signals(inputs: GradingInputs) -> dict[str, tuple[SignalReading, ...]]:
    """Every signal except the sleep score, which is rated twice (see ``grade``)."""

    return {
        DOMAIN_AUTONOMIC: (
            _hrv_overnight(inputs.acute),
            _hrv_week(inputs),
            _resting_hr(inputs.acute),
        ),
        DOMAIN_SLEEP: (_sleep_duration(inputs),),
        DOMAIN_LOAD: _load(inputs),
        DOMAIN_SUBJECTIVE: (_feel(inputs),),
    }


def _domains(
    signals: Mapping[str, tuple[SignalReading, ...]],
    *,
    sleep_score: int | None,
    readiness_low: bool,
) -> tuple[DomainRating, ...]:
    by_domain = {
        **signals,
        DOMAIN_SLEEP: (_sleep_score(sleep_score, signal="sleep_score"), *signals[DOMAIN_SLEEP]),
    }
    ratings: dict[str, Rating] = {
        name: _worst(signal.rating for signal in by_domain[name]) for name in DOMAINS
    }
    confirmed: str | None = None
    # Readiness never votes on its own; it confirms at most one domain it restates
    # (sleep first, then load), so it cannot count twice.
    if readiness_low:
        confirmed = next(
            (name for name in (DOMAIN_SLEEP, DOMAIN_LOAD) if ratings[name] == "mild"), None
        )
        if confirmed is not None:
            ratings[confirmed] = "marked"
    return tuple(
        DomainRating(
            domain=name,
            rating=ratings[name],
            signals=by_domain[name],
            confirmed_by_readiness=name == confirmed,
        )
        for name in DOMAINS
    )


def _combine(domains: Sequence[DomainRating], *, rough: bool) -> tuple[str, bool]:
    marked = sum(1 for item in domains if item.rating == "marked")
    mild = sum(1 for item in domains if item.rating == "mild")
    if rough or marked >= 2:
        return "Red", False
    if marked == 1 or mild >= 2:
        return "Amber", False
    return "Green", mild == 1


_STATUS_ORDER: Final[dict[str, int]] = {"Green": 0, "Amber": 1, "Red": 2}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _floors(acute: Mapping[str, Any]) -> tuple[str | None, bool]:
    """``(symptom floor, bike rest)`` from the acute rail (Batch 294)."""

    symptoms = _mapping(acute.get("symptoms"))
    if acute.get("requiresTrainingRest") is True:
        symptom_floor: str | None = FLOOR_NO_TRAINING
    elif symptoms.get("triggered") is True:
        symptom_floor = FLOOR_EASY_RIDING
    else:
        symptom_floor = None
    return symptom_floor, acute.get("requiresBikeRest") is True


def grade(inputs: GradingInputs) -> GradedVerdict:
    """The graded verdict for one morning. Pure and deterministic."""

    acute = inputs.acute
    rough = inputs.feel is not None and inputs.feel <= _t("feel_rough_max")
    signals = _signals(inputs)
    readiness_low = _readiness_low(inputs)
    domains = _domains(
        signals, sleep_score=inputs.sleep_score_age_adjusted, readiness_low=readiness_low
    )
    status, held = _combine(domains, rough=rough)

    # Age credit may lift a raw-Red night to Amber, but it may never be the only thing
    # between Amber and Green (Batches 170 and 201).
    raw_score = (
        inputs.sleep_score_raw
        if inputs.sleep_score_raw is not None
        else inputs.sleep_score_age_adjusted
    )
    raw_status, _ = _combine(
        _domains(signals, sleep_score=raw_score, readiness_low=readiness_low), rough=rough
    )
    guard = status == "Green" and raw_status == "Amber"
    if guard:
        status, held = "Amber", False

    reasons: list[str] = []
    symptom_floor, bike_rest = _floors(acute)
    if symptom_floor is not None:
        # A reported symptom outranks everything else (Batch 294).
        status, held = "Red", False
        reason = _mapping(acute.get("symptoms")).get("reason")
        if isinstance(reason, str):
            reasons.append(reason)
    if bike_rest:
        # The off-the-bike floors keep the day at least Amber, as they cap it today.
        if status == "Green":
            status, held = "Amber", False
        reasons.append("An acute signal rules out riding today.")

    missing = _mapping(acute.get("dataSufficiency")).get("status") == "insufficient_data"
    missing_floor = missing and status == "Green"
    if missing_floor:
        # Missing data never makes the day better, and never makes it Red.
        status, held = "Amber", False
        reasons.append("Insufficient data to judge today.")

    if rough:
        reasons.append("He said he feels Rough.")
    for item in domains:
        if item.rating == "none":
            continue
        worst_signal = max(item.signals, key=lambda signal: RATING_ORDER[signal.rating])
        confirmation = " Readiness confirms it." if item.confirmed_by_readiness else ""
        reasons.append(
            f"{item.domain.capitalize()} {item.rating}: {worst_signal.reason}{confirmation}"
        )
    raw_sleep = _sleep_score(raw_score, signal="sleep_score").rating
    age_sleep = _sleep_score(inputs.sleep_score_age_adjusted, signal="sleep_score").rating
    if raw_sleep != age_sleep:
        reasons.append(
            f"Age credit lifts the sleep score from {_n(inputs.sleep_score_raw)} to "
            f"{_n(inputs.sleep_score_age_adjusted)} ({raw_sleep} to {age_sleep})."
        )
    if guard:
        reasons.append(
            "Age credit alone would have made the day Green; on the raw sleep score it is "
            "Amber, so it stays Amber."
        )
    floor = (
        FLOOR_NO_TRAINING
        if symptom_floor == FLOOR_NO_TRAINING
        else FLOOR_BIKE_REST
        if bike_rest
        else symptom_floor
    )
    verdict = GradedVerdict(
        status=status,
        held=held,
        domains=domains,
        floor=floor,
        reasons=tuple(reasons),
        rough_check_in=rough,
        age_credit_guard_applied=guard,
        missing_data_floor_applied=missing_floor,
    )
    return replace(verdict, actions=session_actions(verdict, inputs))


# -- the session-aware actions (295.5): computed and reported, not applied ---------------


def session_actions(verdict: GradedVerdict, inputs: GradingInputs) -> tuple[SessionAction, ...]:
    """What the graded verdict would do to each live session today."""

    if inputs.rest_day:
        return ()
    actions: list[SessionAction] = []
    for session in inputs.sessions:
        action, detail = _session_action(verdict, session, inputs.recovery_class_block)
        actions.append(
            SessionAction(
                session_id=session.id,
                title=session.title,
                workout_type=session.workout_type,
                is_key=session.is_key,
                is_hard=session.is_hard,
                action=action,
                detail=detail,
            )
        )
    return tuple(actions)


def _session_action(
    verdict: GradedVerdict, session: PlannedSession, recovery_class_block: bool
) -> tuple[str, str]:
    if verdict.floor == FLOOR_NO_TRAINING:
        return ACTION_NO_TRAINING, "No training of any kind today."
    if verdict.floor == FLOOR_BIKE_REST and session.is_bike:
        return ACTION_OFF_THE_BIKE, "An acute signal rules out riding."
    if not session.is_bike:
        return ACTION_AS_PLANNED, "Not a ride; the verdict's ride changes do not apply."
    if verdict.status == "Red":
        if session.is_hard:
            return ACTION_RECOVERY, "Red: an easy recovery spin instead."
        return ACTION_SHORTENED_Z2, "Red: Zone 2 kept, shorter."
    if recovery_class_block and (verdict.status == "Amber" or verdict.held):
        return ACTION_HOLD_TARGETS, "A planned recovery week is already light: hold the session."
    if verdict.status == "Amber":
        if session.is_hard:
            return ACTION_EASE_HARD, "Amber: hard work eased a zone."
        return ACTION_AS_PLANNED, "Amber: Zone 2 kept at full length."
    if verdict.held and session.is_hard:
        return (
            ACTION_MOVE_OR_HOLD,
            "One mild concern: move it to a better day this week if there is one, "
            "otherwise ride it with the targets held.",
        )
    return ACTION_AS_PLANNED, "As planned."


def classify_session(
    *,
    session_id: str | None,
    title: str | None,
    workout_type: str | None,
    planned_minutes: int | None,
    ir: Mapping[str, Any] | None,
) -> PlannedSession:
    """Classify one session from its structured IR (the scaling rule's own tests)."""

    is_bike = is_bike_workout_type(workout_type)
    ir_dict = dict(ir) if isinstance(ir, Mapping) else None
    has_vo2 = bool(is_bike and ir_dict is not None and ir_has_vo2(ir_dict)) or (
        is_bike and ir_dict is None and "vo2" in (workout_type or "").lower()
    )
    endurance = bool(ir_dict is not None and ir_is_endurance(ir_dict))
    is_hard = bool(is_bike and (has_vo2 or (ir_dict is not None and not endurance)))
    long_ride = bool(
        is_bike
        and not is_hard
        and planned_minutes is not None
        and planned_minutes >= _t("long_ride_minutes")
    )
    return PlannedSession(
        id=session_id,
        title=title,
        workout_type=workout_type,
        planned_minutes=planned_minutes,
        is_bike=is_bike,
        is_hard=is_hard,
        has_vo2=has_vo2,
        is_key=bool(has_vo2 or is_hard or long_ride),
    )


def classify_planned_workout(workout: Any) -> PlannedSession:
    """``classify_session`` for a ``PlannedWorkout`` row or a transient copy of one."""

    try:
        ir: Mapping[str, Any] | None = build_structured_workout_ir(workout)
    except HTTPException:
        ir = None
    return classify_session(
        session_id=str(workout.id) if getattr(workout, "id", None) is not None else None,
        title=getattr(workout, "title", None),
        workout_type=getattr(workout, "workout_type", None),
        planned_minutes=getattr(workout, "planned_duration_min", None),
        ir=ir,
    )
