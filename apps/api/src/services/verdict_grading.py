"""The graded verdict: rate independent domains, then combine (Batch 295).

The ladder in ``morning_verdict`` lets the first matching rule decide the day, so
one marginal signal can turn a morning Red: 21 of Mark's 98 mornings from 21 Jun to
27 Sep 2026 were Red, 12 of them on one HRV rule. The 28 Sep review
(``docs/reviews/verdict-grading-review-2026-09-28.md``) replaced that with graded
evidence, and this module is the engine:

1. **Floors first** (Batch 294): a reported symptom, an illness-grade HRV drop, or a
   resting-heart-rate jump of 7 bpm. They come from the ladder's own acute rail, so
   the two can never disagree about a floor. Batch 303 adds the weakest floor: on an
   easy day back after a fever, or while a possible chest or heart mention in his note
   is unanswered, a hard session becomes an easy ride and the day is not Red.
2. **Rate each domain** ``none``, ``mild`` or ``marked`` against Mark's own normal,
   taking the worst signal inside it:

   * **autonomic** — last night's HRV, his 7-day HRV against his own baseline, and
     his resting heart rate. Since Batch 304 a 7-day dip is marked once it has lasted
     three mornings, or comes with last night under his acute floor. Since Batch 310,
     in the week after a holiday, a dip still catching up once his last two nights
     are back is a little off;
   * **sleep** — the sleep score and total sleep;
   * **load** — the acute:chronic ratio, Garmin's recovery time and yesterday's load;
   * **subjective** — his check-in feel against his own mean and spread.

   Garmin readiness mostly restates his sleep and recovery time (r 0.69 and −0.72
   over 99 mornings), so it never votes on its own: it can only confirm a mild
   sleep or load domain into a marked one. Because it restates them, that counts the
   same night twice, and since Batch 305 the engine says so: it is deliberate extra
   weight (Craig, 3 Oct 2026), limited to one domain. Garmin's HRV status and band are
   context for the brief and are not read here at all.
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
from typing import Any, Final, Literal, Protocol

from fastapi import HTTPException

from src.services.holiday_pause import HolidayWindow, holiday_windows_away_overnight
from src.services.sleep_history import SPO2_HRV_RELIABLE_FROM
from src.services.symptom_check import EASING_CHEST_QUESTION, EASING_FEVER_RETURN, EASING_KINDS
from src.services.verdict_scaling import (
    TRANSFORM_SHORTER,
    TRANSFORM_TIRED_ZONE2,
    ir_has_vo2,
    ir_is_endurance,
)
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
#: Batch 303: what follows a symptom. A hard session becomes an easy ride; Zone 2,
#: strength and mobility stay as planned; the day is at least Amber and never Red for it.
FLOOR_HARD_WORK_TO_EASY: Final = "hard_work_to_easy"

ACTION_AS_PLANNED: Final = "as_planned"
ACTION_HOLD_TARGETS: Final = "hold_targets"
ACTION_MOVE_OR_HOLD: Final = "move_or_hold"
ACTION_EASE_HARD: Final = "ease_hard"
ACTION_RECOVERY: Final = "recovery"
ACTION_SHORTENED_Z2: Final = "shortened_zone2"
ACTION_OFF_THE_BIKE: Final = "off_the_bike"
ACTION_NO_TRAINING: Final = "no_training"
#: Batch 306 (Craig, 3 Oct 2026): on a tired Amber (sleep or how he feels clearly off)
#: Mark picks how to ride a hard session, easy Zone 2 or tempo, at full length, and a
#: long ride is offered shorter in one tap. Neither changes anything until he picks:
#: the planned session stays on Zwift.
ACTION_PICK_ZONE2_OR_TEMPO: Final = "pick_zone2_or_tempo"
ACTION_OFFER_SHORTER: Final = "offer_shorter"


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
            "shift, not noise: mild. For him that is about 2.5 ms. Once it lasts, it is "
            "marked (the persistence line below).",
        ),
        _threshold(
            "hrv_week_marked_sd",
            1.0,
            "SD of nightly HRV",
            "set just past his worst observed value; no trial source",
            "A week this far down is marked. It was set past his lowest 7-day mean of his "
            "first three months (0.83 SD under his normal, 22 Sep), and first fired on 4 Oct "
            "2026, on his holiday's low week (41.3 ms against a line of 41.5). A week-long "
            "dip is usually marked by the persistence line first.",
        ),
        _threshold(
            "hrv_persistence_mornings",
            3,
            "mornings in a row",
            "Javaloyes 2019 and Vesterinen 2016 (a 7-day mean under the smallest "
            "worthwhile change made that day low-intensity); Kiviniemi 2007 (a 2-day fall "
            "did too); softened by the 1 Oct review",
            "A 7-day mean under his smallest worthwhile change on this many mornings in a "
            "row is marked: the dip has lasted. So is one under it with last night under "
            "his acute floor, where the week and the night agree. The trials eased the "
            "first such morning; he moves or holds for two, then eases (Batch 304).",
        ),
        _threshold(
            "hrv_catch_up_nights",
            2,
            "nights back in his range",
            "an engineering choice: one night swings about 5 ms; it departs from the trials, "
            "which judge the same lagging 7-day mean, only in the 7 days after a holiday",
            "After a holiday the 7-day mean lags his nights. Once his last this-many nights "
            "are each at or above the line the reading uses (his normal, or recovery-week "
            "normal, minus the smallest worthwhile change), last night was at home and the "
            "week holds a night he slept away, a marked week counts as a little off, so a "
            "hard session is held at its targets rather than eased (Batch 310, Craig, 4 Oct "
            "2026). It never takes a little off to nothing, and one night under the line "
            "ends it.",
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
            "the top of the balanced range the app already uses (Batch 201); the ratio "
            "comes from a team-sport injury model (Gabbett 2016) and is contested "
            "(Impellizzeri 2020), and Garmin calls up to 1.4 optimal",
            "A ramp above the balanced range is mild. Moving it to 1.5, Garmin's 'high', "
            "waits until after 20 Oct 2026, so it does not change his first fortnight back "
            "from a holiday unseen (Craig, 3 Oct).",
        ),
        _threshold(
            "acwr_marked",
            1.5,
            "acute:chronic load ratio",
            "the app's load cap (Batch 167), where Garmin's 'high' starts; contested "
            "evidence, as above",
            "A fast ramp is marked, and on its own makes the day Amber.",
        ),
        _threshold(
            "recovery_time_mild_hours",
            24,
            "hours",
            "Garmin's own estimate, no trial source; the line is the app's load cap (Batch 167)",
            "More than a day of Garmin recovery time left is mild: fine for an easy "
            "session, a reason to move a hard one.",
        ),
        _threshold(
            "recovery_time_marked_hours",
            48,
            "hours",
            "set just past his worst observed value; Garmin's own estimate, no trial source",
            "More than two days left is marked. His highest at wake in three months was 47 "
            "hours, so this line has never fired; it is for an unusual debt.",
        ),
        _threshold(
            "yesterday_hard_mild",
            1,
            "hard day before a hard session",
            "engineering choice, no trial source; it overlaps Garmin's recovery time",
            "A hard day yesterday is mild only when today's session is hard too (Batch "
            "305). Before an easy day it is the recovery his plan set, not something off. "
            "Replayed on 3 Oct 2026 it was mild on 17 of 103 mornings; on 5 the day's "
            "session was easy, and those now count for nothing.",
        ),
        _threshold(
            "readiness_confirms_domains",
            1,
            "domain",
            "deliberate extra weight (Craig, 3 Oct 2026); readiness restates his sleep "
            "(r 0.69) and recovery time (r -0.72), so it is not independent evidence",
            "Low readiness (Garmin's Low or Poor, or under his own lower quartile) turns "
            "this many mild sleep or load domains marked, sleep first, and never votes on "
            "its own. It counts that night twice on purpose; replayed on 3 Oct 2026 it "
            "decided 3 of 103 colours (21 and 28 Aug, 4 Sep).",
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
    #: Batch 298: that block's kind as his plan names it ("consolidation", "taper",
    #: "recovery" or "rest"), so the words name the week he is in. ``None`` outside one.
    light_week: str | None = None
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
    #: Batch 297: his check-in note says he feels unwell or unusually tired, so the
    #: subjective domain is one notch worse than his feel alone. Never negative.
    notes_feel_notch: int = 0
    notes_feel_words: str | None = None
    #: Batch 304: a 7-day HRV dip that has lasted rates autonomic marked. A graded
    #: morning stored before the rule is replayed without it, so the replay gives back
    #: exactly what Mark saw (``references.hrvPersistence``).
    hrv_persistence: bool = True
    #: Batch 305: a hard day yesterday counts only when today's session is hard. A
    #: graded morning stored before the rule is replayed without it
    #: (``references.yesterdayCountsOnHardDays``).
    yesterday_counts_on_hard_days: bool = True
    #: Batch 306: a tired Amber offers Mark his choices. A graded morning stored before
    #: it is replayed without them (``references.tiredMorningChoices``).
    tired_morning_choices: bool = True
    #: Batch 310: after a holiday, a 7-day dip still catching up once his nights are back
    #: is a little off. A graded morning stored before the rule is replayed without it
    #: (``references.hrvHolidayCatchUp``).
    hrv_holiday_catch_up: bool = True
    #: Batch 310: the nights inside this morning's 7-night week that he slept away, each
    #: dated by the morning after it (:func:`week_nights_away`). Stored with the morning
    #: (``references.hrvWeekNightsAway``), so the replay sees what the morning saw.
    hrv_nights_away: frozenset[date] = frozenset()


@dataclass(frozen=True, slots=True)
class SignalReading:
    domain: str
    signal: str
    rating: Rating
    value: float | None
    reference: str | None
    reason: str
    #: His usual for this signal (his HRV normal, his resting-HR median), for the
    #: Mark-facing phrase. ``None`` where the phrase needs no comparison.
    usual: float | None = None
    #: Batch 304: mornings in a row his 7-day HRV has been under his smallest worthwhile
    #: change, on the persistent readings only.
    streak: int | None = None

    def to_packet(self) -> dict[str, Any]:
        packet: dict[str, Any] = {
            "domain": self.domain,
            "signal": self.signal,
            "rating": self.rating,
            "value": self.value,
            "reference": self.reference,
            "reason": self.reason,
        }
        if self.streak is not None:
            packet["streak"] = self.streak
        return packet


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
    #: The Mark-facing line saying why today is this colour (Batch 296).
    summary: str = ""
    #: Batch 303: why the hard-work-to-easy floor applies (``fever_return`` or
    #: ``chest_question``), and its Mark-facing reason. ``None`` when it does not.
    easing: str | None = None
    easing_reason: str | None = None
    #: What the stored rows cannot give back later: the replay reads these from a
    #: graded packet so it reproduces production exactly (Batch 296).
    references: Mapping[str, Any] = field(default_factory=dict)

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
            "easing": self.easing,
            "roughCheckIn": self.rough_check_in,
            "ageCreditGuardApplied": self.age_credit_guard_applied,
            "missingDataFloorApplied": self.missing_data_floor_applied,
            "domains": [item.to_packet() for item in self.domains],
            "reasons": list(self.reasons),
            "summary": self.summary,
            "actions": [item.to_packet() for item in self.actions],
            "references": dict(self.references),
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
    usual: float | None = None,
    streak: int | None = None,
) -> SignalReading:
    return SignalReading(
        domain=domain,
        signal=signal,
        rating=rating,
        value=round(value, 2) if value is not None else None,
        reference=reference,
        reason=reason,
        usual=round(usual, 2) if usual is not None else None,
        streak=streak,
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


@dataclass(frozen=True, slots=True)
class _HrvWeek:
    """One morning's 7-day HRV against his normal, as that morning would rate it."""

    rating: Rating
    #: The 7-day mean; ``None`` when no night falls in the week.
    week_mean: float | None
    #: His normal; ``None`` when there are too few nights to judge the week.
    centre: float | None = None
    spread: float = 0.0
    basis: str = "his usual"


def _hrv_week_on(inputs: GradingInputs, day: date, *, in_recovery_week: bool) -> _HrvWeek:
    """The 7-day rating for the morning of ``day`` (295.3), from the nights up to it."""

    week_start = day - timedelta(days=int(_t("hrv_week_nights")) - 1)
    week = [value for night, value in inputs.hrv_nights if week_start <= night <= day]
    window_start = day - timedelta(days=int(_t("hrv_baseline_window_days")))
    baseline = [value for night, value in inputs.hrv_nights if window_start <= night < day]
    if len(week) < _t("hrv_week_min_nights") or len(baseline) < _t("hrv_baseline_min_nights"):
        return _HrvWeek("none", sum(week) / len(week) if week else None)
    centre, spread = _mean_sd(baseline)
    basis = "his usual"
    if in_recovery_week:
        recovery = [
            value
            for night, value in inputs.hrv_nights
            if night < week_start and night in inputs.recovery_week_nights
        ]
        if len(recovery) >= _t("hrv_recovery_min_nights"):
            centre = sum(recovery) / len(recovery)
            basis = "his recovery-week usual"
    week_mean = sum(week) / len(week)
    rating: Rating
    if week_mean < centre - _t("hrv_week_marked_sd") * spread:
        rating = "marked"
    elif week_mean < centre - _t("hrv_swc_sd") * spread:
        rating = "mild"
    else:
        rating = "none"
    return _HrvWeek(rating, week_mean, centre, spread, basis)


def _hrv_streak(inputs: GradingInputs) -> int:
    """Mornings in a row, to this one, his 7-day HRV has been under his SWC (Batch 304).

    Each earlier morning is rated as it would have been that morning: its own week, its
    own normal and its own recovery-week basis. The count stops at the first morning
    that was within his range or had too few nights to judge.
    """

    streak = 0
    day = inputs.subject_date
    while True:
        in_recovery = (
            inputs.in_recovery_week
            if day == inputs.subject_date
            else day in inputs.recovery_week_nights
        )
        if _hrv_week_on(inputs, day, in_recovery_week=in_recovery).rating == "none":
            return streak
        streak += 1
        day -= timedelta(days=1)


def _hrv_persistent(
    inputs: GradingInputs, *, week_mean: float, centre: float, basis: str, reference: str
) -> SignalReading | None:
    """A 7-day dip that has lasted, or that last night agrees with, is marked (Batch 304).

    The trials the engine cites made a 7-day mean under the smallest worthwhile change a
    low-intensity day at once (Javaloyes 2019, Vesterinen 2016), and a 2-day fall too
    (Kiviniemi 2007). The 1 Oct review softened that to three mornings in a row, or one
    with last night under his acute floor, which keeps it within his "at worst Amber".
    """

    streak = _hrv_streak(inputs)
    if streak >= _t("hrv_persistence_mornings"):
        return _reading(
            DOMAIN_AUTONOMIC,
            "hrv_7_day_persistent",
            "marked",
            week_mean,
            f"7-day HRV {week_mean:.1f} ms has been under {basis} {centre:.1f} ms by more than "
            f"the smallest worthwhile change for {streak} mornings in a row.",
            reference,
            usual=centre,
            streak=streak,
        )
    rail = _mapping(inputs.acute.get("overnightHrv"))
    if rail.get("triggered") is True:
        current = _as_float(rail.get("currentMs"))
        return _reading(
            DOMAIN_AUTONOMIC,
            "hrv_7_day_low_night",
            "marked",
            current,
            f"7-day HRV {week_mean:.1f} ms is under {basis} {centre:.1f} ms by more than the "
            f"smallest worthwhile change, and last night's {_n(current)} ms is under his acute "
            f"floor of {_n(rail.get('acuteFloorMs'))} ms.",
            f"his median {_n(rail.get('baselineMedianMs'))} ms",
            usual=_as_float(rail.get("baselineMedianMs")),
            streak=streak,
        )
    return None


def _hrv_catching_up(
    inputs: GradingInputs, week: _HrvWeek, reading: SignalReading
) -> SignalReading | None:
    """After a holiday, a 7-day dip still catching up with his nights is mild (Batch 310).

    The 7-day mean lags his nights: back from a holiday with his nights normal again,
    it stays under his line for days. Craig's rule of 4 Oct 2026: when the seven nights
    it averages include a night he slept away, last night was at home, and his last two
    nights are each at or above the line this reading uses (his normal, or recovery-week
    normal, minus the smallest worthwhile change), a marked week counts as a little off.
    It applies whichever line marked the week, and a mild week takes the same words. It
    never takes mild to none, and it leaves the 7-day rating alone, so 304's streak still
    counts these mornings and one night under the line marks the week again.
    """

    if not inputs.hrv_holiday_catch_up or reading.rating == "none":
        return None
    # 304's low-night clause has last night under his acute floor, under this line, so
    # it can never meet the rule; it is excluded here so that holds in every basis.
    if reading.signal == "hrv_7_day_low_night":
        return None
    if week.centre is None or week.week_mean is None:
        return None
    day = inputs.subject_date
    week_start = day - timedelta(days=int(_t("hrv_week_nights")) - 1)
    averaged = [night for night, _ in inputs.hrv_nights if week_start <= night <= day]
    if day in inputs.hrv_nights_away or not any(
        night in inputs.hrv_nights_away for night in averaged
    ):
        return None
    line = week.centre - _t("hrv_swc_sd") * week.spread
    by_night = dict(inputs.hrv_nights)
    recent = [
        by_night.get(day - timedelta(days=offset))
        for offset in range(int(_t("hrv_catch_up_nights")))
    ]
    # Missing data never makes the day better: a night without a reading is not back.
    if any(value is None or value < line for value in recent):
        return None
    nights = " and ".join(_n(value) for value in reversed(recent))
    return _reading(
        DOMAIN_AUTONOMIC,
        "hrv_7_day_catching_up",
        "mild",
        week.week_mean,
        f"7-day HRV {week.week_mean:.1f} ms is still under {week.basis} {week.centre:.1f} ms "
        f"after his holiday, but his last two nights ({nights} ms) are back at or above "
        f"{line:.1f} ms: the average is catching up, so it counts as a little off.",
        f"{week.basis} {week.centre:.1f} ms, SD {week.spread:.1f} ms",
        usual=week.centre,
    )


def _hrv_week(inputs: GradingInputs) -> SignalReading:
    """His 7-day mean HRV against his own normal (295.3), marked once it lasts (304).

    After a holiday, a dip still catching up with his nights is a little off (310).
    """

    week = _hrv_week_on(inputs, inputs.subject_date, in_recovery_week=inputs.in_recovery_week)
    reading = _hrv_week_reading(inputs, week)
    return _hrv_catching_up(inputs, week, reading) or reading


def _hrv_week_reading(inputs: GradingInputs, week: _HrvWeek) -> SignalReading:
    if week.centre is None or week.week_mean is None:
        return _reading(
            DOMAIN_AUTONOMIC,
            "hrv_7_day",
            "none",
            week.week_mean,
            "Not enough nights yet to judge his week against his normal.",
        )
    centre, week_mean, basis = week.centre, week.week_mean, week.basis
    swc = _t("hrv_swc_sd") * week.spread
    reference = f"{basis} {centre:.1f} ms, SD {week.spread:.1f} ms"
    if week.rating == "marked":
        reason = (
            f"7-day HRV {week_mean:.1f} ms is more than {_t('hrv_week_marked_sd'):g} SD under "
            f"{basis} {centre:.1f} ms."
        )
    elif week.rating == "mild":
        if inputs.hrv_persistence:
            persistent = _hrv_persistent(
                inputs, week_mean=week_mean, centre=centre, basis=basis, reference=reference
            )
            if persistent is not None:
                return persistent
        reason = (
            f"7-day HRV {week_mean:.1f} ms is under {basis} {centre:.1f} ms by more than the "
            f"smallest worthwhile change ({swc:.1f} ms)."
        )
    else:
        reason = f"7-day HRV {week_mean:.1f} ms is within {basis} range."
    return _reading(
        DOMAIN_AUTONOMIC, "hrv_7_day", week.rating, week_mean, reason, reference, usual=centre
    )


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
            usual=_as_float(rail.get("baselineMedianMs")),
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
            usual=_as_float(rail.get("baselineMedianMs")),
        )
    return _reading(
        DOMAIN_AUTONOMIC, "hrv_overnight", "none", current, "Last night's HRV is not low."
    )


def _resting_hr(acute: Mapping[str, Any]) -> SignalReading:
    rail = _mapping(acute.get("restingHeartRate"))
    current = _as_float(rail.get("currentBpm"))
    delta = _as_float(rail.get("deltaFromMedianBpm"))
    median_bpm = rail.get("baselineMedianBpm")
    usual = _as_float(median_bpm)
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
            usual=usual,
        )
    if rail.get("trigger") == "consecutive_q3":
        return _reading(
            DOMAIN_AUTONOMIC,
            "resting_hr_two_mornings",
            "mild",
            current,
            f"Resting heart rate {_n(current)} bpm has been above his usual range two mornings.",
            reference,
            usual=usual,
        )
    if delta is not None and delta >= _t("resting_hr_rise_mild_bpm"):
        return _reading(
            DOMAIN_AUTONOMIC,
            "resting_hr",
            "mild",
            current,
            f"Resting heart rate {_n(current)} bpm is {_n(delta)} bpm over his median.",
            reference,
            usual=usual,
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
    readings.append(_yesterday_load(inputs))
    return tuple(readings)


def _yesterday_load(inputs: GradingInputs) -> SignalReading:
    """A hard day yesterday, which counts only before a hard session (Batch 305)."""

    if (inputs.yesterday_load or "").lower() != "hard":
        return _reading(DOMAIN_LOAD, "yesterday_load", "none", None, "Yesterday was not hard.")
    if inputs.yesterday_counts_on_hard_days and not _hard_ride_today(inputs):
        return _reading(
            DOMAIN_LOAD,
            "yesterday_load",
            "none",
            None,
            "Yesterday's training was hard, and today's session is easy: that is the "
            "recovery his plan set, so it does not count against today.",
        )
    return _reading(
        DOMAIN_LOAD,
        "yesterday_load",
        "mild",
        None,
        "Yesterday's training was hard, and he is still recovering from it.",
    )


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


_NOTCH_UP: Final[dict[str, Rating]] = {"none": "mild", "mild": "marked", "marked": "marked"}


def _notes_feel(inputs: GradingInputs, feel_rating: Rating) -> SignalReading:
    """His note, one notch worse than his feel alone, and never better (Batch 297)."""

    if inputs.notes_feel_notch <= 0:
        return _reading(DOMAIN_SUBJECTIVE, "notes_feel", "none", None, "No note of feeling worse.")
    words = inputs.notes_feel_words or "he feels unwell or unusually tired"
    return _reading(
        DOMAIN_SUBJECTIVE,
        "notes_feel",
        _NOTCH_UP[feel_rating],
        None,
        f'His note: "{words}".',
        "one notch worse than his feel alone",
    )


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
        DOMAIN_SUBJECTIVE: (feel := _feel(inputs), _notes_feel(inputs, feel.rating)),
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
    confirmed: tuple[str, ...] = ()
    # Readiness never votes on its own; it confirms a mild domain it restates (sleep
    # first, then load). Because it restates them, a confirmed domain counts the same
    # night twice: deliberate extra weight, limited by the table (Batch 305).
    if readiness_low:
        confirmed = tuple(name for name in (DOMAIN_SLEEP, DOMAIN_LOAD) if ratings[name] == "mild")[
            : int(_t("readiness_confirms_domains"))
        ]
        for name in confirmed:
            ratings[name] = "marked"
    return tuple(
        DomainRating(
            domain=name,
            rating=ratings[name],
            signals=by_domain[name],
            confirmed_by_readiness=name in confirmed,
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


def _easing(acute: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """What follows a symptom on a morning with no symptom floor of its own (Batch 303)."""

    easing = _mapping(_mapping(acute.get("symptoms")).get("easing"))
    return easing if easing.get("kind") in EASING_KINDS else None


def _hard_ride_today(inputs: GradingInputs) -> bool:
    return not inputs.rest_day and any(
        session.is_bike and session.is_hard for session in inputs.sessions
    )


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
    raw_domains = _domains(signals, sleep_score=raw_score, readiness_low=readiness_low)
    raw_status, _ = _combine(raw_domains, rough=rough)
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
    # Batch 303: what follows a symptom. An easy day back after a fever is at least
    # Amber whatever is planned; an unanswered chest question eases a hard session and
    # otherwise only asks, so with none planned it changes nothing. Neither is Red. A
    # stricter floor today outranks it: "easy riding only" is not said beside "no riding".
    easing = _easing(acute) if symptom_floor is None and not bike_rest else None
    easing_kind: str | None = None
    easing_reason: str | None = None
    if easing is not None and (
        easing.get("kind") == EASING_FEVER_RETURN or _hard_ride_today(inputs)
    ):
        easing_kind = str(easing["kind"])
        easing_reason = str(easing["reason"]) if isinstance(easing.get("reason"), str) else None
        if status == "Green":
            status, held = "Amber", False
        if easing_reason is not None:
            reasons.append(easing_reason)

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
        if symptom_floor is not None
        else FLOOR_HARD_WORK_TO_EASY
        if easing_kind is not None
        else None
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
        # When the guard holds the day at Amber, the raw-score pass is the one that
        # explains it: the fair night is one of the things that is off.
        summary=mark_facing_summary(raw_domains if guard else domains, rough=rough),
        easing=easing_kind,
        easing_reason=easing_reason,
        references={
            "readinessLowerQuartile": inputs.readiness_lower_quartile,
            "inRecoveryWeek": inputs.in_recovery_week,
            "recoveryClassBlock": inputs.recovery_class_block,
            # Batch 298: the light week's name, for the plan line and the hero.
            "lightWeek": inputs.light_week,
            "notesFeelNotch": inputs.notes_feel_notch,
            "notesFeelWords": inputs.notes_feel_words,
            # Batch 304: graded with the HRV persistence rule. A morning stored without
            # this key was graded before it, and the replay grades it without the rule.
            "hrvPersistence": inputs.hrv_persistence,
            # Batch 305: graded with the rule that a hard yesterday counts only before a
            # hard session. A morning stored without the key was graded before it.
            "yesterdayCountsOnHardDays": inputs.yesterday_counts_on_hard_days,
            # Batch 306: graded with a tired morning's choices.
            "tiredMorningChoices": inputs.tired_morning_choices,
            # Batch 310: graded with the holiday catch-up, and the nights away it saw.
            "hrvHolidayCatchUp": inputs.hrv_holiday_catch_up,
            "hrvWeekNightsAway": sorted(night.isoformat() for night in inputs.hrv_nights_away),
        },
    )
    # Batch 300: a light week holds the session only when nothing is clearly off. A
    # domain marked on Garmin's own sleep score counts even where the age credit lifts
    # it, so the credit is never the only thing between easing and holding.
    clearly_off = any(item.rating == "marked" for item in (*domains, *raw_domains))
    # Batch 306: a tired morning is an Amber with sleep or how he feels clearly off,
    # on the age-adjusted sleep score or on Garmin's own, as Batch 300 reads it.
    tired = (
        inputs.tired_morning_choices
        and verdict.status == "Amber"
        and any(
            item.rating == "marked" and item.domain in (DOMAIN_SLEEP, DOMAIN_SUBJECTIVE)
            for item in (*domains, *raw_domains)
        )
    )
    return replace(
        verdict, actions=session_actions(verdict, inputs, clearly_off=clearly_off, tired=tired)
    )


# -- the Mark-facing words (Batch 296) ----------------------------------------------------
#
# Signed off by Craig on Mark's behalf on 29 Sep 2026
# (docs/drafts/2026-09-29-batch-296-wording.md). They lead with his own numbers.

_COUNT_WORDS: Final = ("One", "Two", "Three", "Four")


def _trim(value: float | None, places: int = 2) -> str:
    """``1.35`` and ``1.6``, not ``1.60``."""

    if value is None:
        return "unknown"
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def mark_facing_phrase(signal: SignalReading) -> str:
    """One signal, in Mark's words, with his numbers."""

    marked = signal.rating == "marked"
    value, usual = signal.value, signal.usual
    if signal.signal == "hrv_7_day":
        lead = "well below" if marked else "below"
        return (
            f"your HRV has been {lead} your usual this week "
            f"({_n(round(value) if value is not None else None)} ms against "
            f"{_n(round(usual) if usual is not None else None)})"
        )
    if signal.signal == "hrv_7_day_persistent":
        # Batch 304: a dip that has lasted. The count is mornings of his 7-day average,
        # not low nights, so the words name the average (signed off 3 Oct 2026).
        return (
            f"your 7-day HRV average has been below your usual for {_n(signal.streak)} "
            f"mornings running "
            f"({_n(round(value) if value is not None else None)} ms against "
            f"{_n(round(usual) if usual is not None else None)})"
        )
    if signal.signal == "hrv_7_day_catching_up":
        # Batch 310: after a holiday, his nights back but the average still catching up
        # (signed off by Craig on Mark's behalf, 4 Oct 2026).
        return (
            f"your HRV is back to normal, but your 7-day average is still catching up after "
            f"your holiday ({_n(round(value) if value is not None else None)} ms against "
            f"{_n(round(usual) if usual is not None else None)})"
        )
    if signal.signal == "hrv_7_day_low_night":
        return (
            f"your HRV has been below your usual this week and was low again last night "
            f"({_n(value)} ms against a usual {_n(usual)})"
        )
    if signal.signal == "hrv_overnight":
        lead = "dropped sharply" if marked else "was low"
        return f"your HRV {lead} last night ({_n(value)} ms against a usual {_n(usual)})"
    if signal.signal == "resting_hr_two_mornings":
        return "your resting heart rate has been a little up two mornings running"
    if signal.signal == "resting_hr":
        rise = value - usual if value is not None and usual is not None else None
        return f"your resting heart rate is up {_n(rise)} bpm"
    if signal.signal == "sleep_score":
        quality = "a very poor" if marked else "a fair"
        return f"{quality} night's sleep (score {_n(value)})"
    if signal.signal == "total_sleep":
        length = "a very short" if marked else "a short"
        hours = value / 60 if value is not None else None
        return f"{length} night ({_trim(hours, 1)} hours)"
    if signal.signal == "acwr":
        pace = "climbing fast" if marked else "climbing"
        return f"your training load is {pace} (ratio {_trim(value)})"
    if signal.signal == "recovery_time":
        return f"{_n(round(value) if value is not None else None)} hours of recovery still to go"
    if signal.signal == "yesterday_load":
        # Batch 298: "yesterday was a hard day" read as criticism of a session his own
        # plan set. What is off is the recovery, not the day (signed off 1 Oct 2026).
        return "you're still recovering from yesterday's hard session"
    if signal.signal == "feel":
        return "you said you feel well below par" if marked else "you said you feel a bit below par"
    if signal.signal == "notes_feel":
        # Batch 297: his own words from the check-in note.
        words = signal.reason.removeprefix("His note: ").rstrip(".")
        return f"you wrote {words}"
    return signal.reason


def _domain_phrase(item: DomainRating) -> str:
    worst = max(item.signals, key=lambda signal: RATING_ORDER[signal.rating])
    phrase = mark_facing_phrase(worst)
    return f"{phrase} (your readiness agrees)" if item.confirmed_by_readiness else phrase


def _join(phrases: Sequence[str]) -> str:
    if len(phrases) <= 1:
        return "".join(phrases)
    return ", ".join(phrases[:-1]) + ", and " + phrases[-1]


def _count(number: int) -> str:
    return _COUNT_WORDS[number - 1] if 0 < number <= len(_COUNT_WORDS) else str(number)


def mark_facing_summary(domains: Sequence[DomainRating], *, rough: bool) -> str:
    """Why today is this colour, in one line that leads with his own numbers."""

    if rough:
        return "You said you feel rough."
    marked = [_domain_phrase(item) for item in domains if item.rating == "marked"]
    mild = [_domain_phrase(item) for item in domains if item.rating == "mild"]
    if not marked and not mild:
        return "Your numbers are all within your usual range."
    if not marked:
        noun = "thing is" if len(mild) == 1 else "things are"
        return f"{_count(len(mild))} {noun} a little off: {_join(mild)}."
    if not mild:
        noun = "thing is" if len(marked) == 1 else "things are"
        return f"{_count(len(marked))} {noun} clearly off: {_join(marked)}."
    noun = "thing is" if len(marked) == 1 else "things are"
    return (
        f"{_count(len(marked))} {noun} clearly off, and {_count(len(mild)).lower()} a little "
        f"off: {_join(marked + mild)}."
    )


# -- the session-aware actions (295.5): computed and reported, not applied ---------------


def session_actions(
    verdict: GradedVerdict, inputs: GradingInputs, *, clearly_off: bool, tired: bool = False
) -> tuple[SessionAction, ...]:
    """What the graded verdict would do to each live session today.

    ``clearly_off`` is whether any domain is marked, on the age-adjusted sleep score or
    on Garmin's own (Batch 300): a light week holds the session only when it is not.
    ``tired`` is whether this is an Amber with sleep or how he feels marked (Batch 306).
    """

    if inputs.rest_day:
        return ()
    actions: list[SessionAction] = []
    for session in inputs.sessions:
        action, detail = _session_action(
            verdict,
            session,
            inputs.recovery_class_block,
            inputs.light_week,
            clearly_off=clearly_off,
            tired=tired,
        )
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
    verdict: GradedVerdict,
    session: PlannedSession,
    recovery_class_block: bool,
    light_week: str | None = None,
    *,
    clearly_off: bool = False,
    tired: bool = False,
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
    # Batch 303: what follows a symptom outranks the light-week hold and the Amber
    # ease. A hard session held at its targets, or eased a zone, is still hard work.
    if verdict.floor == FLOOR_HARD_WORK_TO_EASY and session.is_hard:
        if verdict.easing == EASING_CHEST_QUESTION:
            return (
                ACTION_RECOVERY,
                "His note may mean a chest or heart symptom and he has not answered: an "
                "easy spin instead until he does.",
            )
        return ACTION_RECOVERY, "An easy day back after a fever: an easy spin instead."
    # Batch 300 (Craig, 1 Oct 2026): a light week holds the session on a mild concern,
    # and on an Amber made of two. A marked domain takes the ordinary action below, as
    # in any other week: W12's sweet spot is not ridden in full after a sub-60 night.
    if recovery_class_block and not clearly_off and (verdict.status == "Amber" or verdict.held):
        return (
            ACTION_HOLD_TARGETS,
            f"A planned {light_week or 'recovery'} week is already light: hold the session.",
        )
    # Batch 306 (Craig, 3 Oct 2026): on a tired Amber he picks. A tired morning has a
    # marked domain, so the light-week hold above has already passed it by.
    if verdict.status == "Amber" and tired:
        if session.is_hard:
            return (
                ACTION_PICK_ZONE2_OR_TEMPO,
                "A tired morning: he picks easy Zone 2 or tempo, full length either way; "
                "picking neither leaves the planned session.",
            )
        if session.is_key:
            return (
                ACTION_OFFER_SHORTER,
                "A tired morning: the long ride is offered shorter in one tap; it stays "
                "at full length unless he takes it.",
            )
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


# -- reading a stored morning (Batch 296) ------------------------------------------------

#: The engine that set a stored morning's colour. Absent on every packet written
#: before Batch 296, which the ladder decided.
ENGINE_LADDER: Final = "ladder"
ENGINE_GRADED: Final = "graded"

#: Actions that change a ride, and the verdict transform each one takes.
RIDE_TRANSFORMS: Final[dict[str, str]] = {
    "ease_hard": "Amber",
    "recovery": "Red",
    "shortened_zone2": "Red",
    # Batch 306: the version offered by default. The pick's tempo version is built
    # when he chooses it; the shorter ride stands only if he approves it.
    ACTION_PICK_ZONE2_OR_TEMPO: TRANSFORM_TIRED_ZONE2,
    ACTION_OFFER_SHORTER: TRANSFORM_SHORTER,
}


def stored_engine(packet: Any) -> str:
    """Which engine decided a stored morning packet's colour."""

    verdict = packet.get("verdict") if isinstance(packet, Mapping) else None
    engine = verdict.get("engine") if isinstance(verdict, Mapping) else None
    return ENGINE_GRADED if engine == ENGINE_GRADED else ENGINE_LADDER


def stored_actions(packet: Any) -> dict[str, str]:
    """``{planned workout id: action}`` from a graded morning packet, else empty."""

    verdict = packet.get("verdict") if isinstance(packet, Mapping) else None
    graded = verdict.get("graded") if isinstance(verdict, Mapping) else None
    actions = graded.get("actions") if isinstance(graded, Mapping) else None
    if not isinstance(actions, list):
        return {}
    return {
        str(item["plannedWorkoutId"]): str(item["action"])
        for item in actions
        if isinstance(item, Mapping)
        and item.get("plannedWorkoutId") is not None
        and isinstance(item.get("action"), str)
    }


def stored_rest_day(packet: Any) -> bool:
    """Was a stored morning a rest day: a holiday, or every session skipped? (Batch 299)"""

    rest_day = packet.get("restDay") if isinstance(packet, Mapping) else None
    if isinstance(rest_day, Mapping) and isinstance(rest_day.get("isRestDay"), bool):
        return bool(rest_day["isRestDay"])
    verdict = packet.get("verdict") if isinstance(packet, Mapping) else None
    return isinstance(verdict, Mapping) and verdict.get("isRestDay") is True


def stored_seen_workouts(packet: Any) -> frozenset[str]:
    """The planned workout ids a stored morning packet saw (Batch 299)."""

    planned = packet.get("plannedWorkouts") if isinstance(packet, Mapping) else None
    if not isinstance(planned, list):
        return frozenset()
    return frozenset(
        str(item["id"]) for item in planned if isinstance(item, Mapping) and item.get("id")
    )


def ride_transform(
    status: str | None,
    *,
    graded: bool,
    action: str | None,
) -> str | None:
    """The verdict transform a ride takes this morning, or ``None`` for as planned.

    The ladder transforms every ride on an Amber or Red morning. The graded verdict
    transforms a ride only when its session action changes it: a held or moved
    session, and a Zone 2 ride on an Amber morning, are ridden as planned. A ride the
    morning packet did not see falls back to the colour.
    """
    if status not in {"Amber", "Red"}:
        return None
    if not graded:
        return status
    if action is None:
        return status
    return RIDE_TRANSFORMS.get(action)


# -- the inputs, built one way for the live morning and the replay (Batch 296) -----------

#: Block types whose nights form his recovery-week HRV normal (Batch 275's grouping).
RECOVERY_WEEK_TYPES: Final = ("recovery", "rest", "taper")
#: Block types in which the plan is already light, so a mild concern holds the session
#: (the app's recovery-class blocks since Batch 182). Since Batch 300 a marked one eases
#: the hard work as in any other week.
RECOVERY_CLASS_TYPES: Final = ("recovery", "rest", "taper", "consolidation")
LIVE_SESSION_EXCLUDED: Final = frozenset({"completed", "skipped"})


class _Block(Protocol):
    start_date: date
    end_date: date
    block_type: str | None


def block_flags(day: date, blocks: Sequence[_Block]) -> tuple[bool, bool]:
    """(in a recovery or taper week, in a recovery-class block)."""

    for block in blocks:
        if block.start_date <= day <= block.end_date:
            block_type = (block.block_type or "").lower()
            return (
                any(kind in block_type for kind in RECOVERY_WEEK_TYPES),
                any(kind in block_type for kind in RECOVERY_CLASS_TYPES),
            )
    return False, False


#: The order a light week's name is read in, most specific first (Batch 298).
LIGHT_WEEK_NAMES: Final = ("consolidation", "taper", "recovery", "rest")


def light_week_name(day: date, blocks: Sequence[_Block]) -> str | None:
    """The kind of light week ``day`` sits in, as his plan names it, or ``None``.

    Batch 298: every light week was "a planned recovery week" in the words, W12's
    consolidation included. The words now name the week the plan does.
    """

    for block in blocks:
        if block.start_date <= day <= block.end_date:
            block_type = (block.block_type or "").lower()
            return next((name for name in LIGHT_WEEK_NAMES if name in block_type), None)
    return None


def recovery_week_nights(blocks: Sequence[_Block]) -> frozenset[date]:
    nights: set[date] = set()
    for block in blocks:
        block_type = (block.block_type or "").lower()
        if not any(kind in block_type for kind in RECOVERY_WEEK_TYPES):
            continue
        day = block.start_date
        while day <= block.end_date:
            nights.add(day)
            day += timedelta(days=1)
    return frozenset(nights)


def week_nights_away(subject_date: date, windows: Sequence[HolidayWindow]) -> frozenset[date]:
    """The nights of this morning's 7-night HRV week he slept away (Batch 310).

    A night is dated by the morning after it, as his HRV reading is, and a holiday
    window is read end-exclusive, as the bedroom reads it
    (:func:`holiday_pause.holiday_windows_away_overnight`): the night dated ``D`` was
    away when ``D - 1`` falls inside a window's ``[start, end)``. He is home on the
    evening of the end date, and the morning he flies out follows a night at home, so
    a holiday of 27 Sep-6 Oct is away on the nights dated 28 Sep-6 Oct. Reading the
    morning itself inside ``[start, end]`` would count 27 Sep, a night at home.
    """

    week_start = subject_date - timedelta(days=int(_t("hrv_week_nights")) - 1)
    nights = (week_start + timedelta(days=offset) for offset in range(int(_t("hrv_week_nights"))))
    return frozenset(
        night
        for night in nights
        if holiday_windows_away_overnight(windows, night - timedelta(days=1))
    )


def build_grading_inputs(
    *,
    subject_date: date,
    acute: Mapping[str, Any],
    last_night_hrv_ms: float | None,
    hrv_history: Mapping[date, float],
    sleep_score_raw: int | None,
    sleep_score_age_adjusted: int | None,
    sleep_minutes: float | None,
    sleep_minutes_history: Mapping[date, float],
    acwr: float | None,
    recovery_time_min: float | None,
    yesterday_load: str | None,
    feel: int | None,
    feel_history: Mapping[date, int],
    readiness_level: str | None,
    readiness_score: float | None,
    readiness_lower_quartile: float | None,
    planned_workouts: Sequence[Any],
    rest_day: bool,
    blocks: Sequence[_Block],
    notes_feel_notch: int = 0,
    notes_feel_words: str | None = None,
    holiday_windows: Sequence[HolidayWindow] = (),
) -> GradingInputs:
    """One morning's inputs, from its own readings and the rows dated before it.

    The live morning and the replay both call this, so the colour production shows
    and the colour the replay computes can only differ if the rows themselves did.
    """

    day = subject_date
    nights = [
        (night, float(value))
        for night, value in hrv_history.items()
        if SPO2_HRV_RELIABLE_FROM <= night < day and value is not None
    ]
    if last_night_hrv_ms is not None:
        nights.append((day, float(last_night_hrv_ms)))
    sleep_window = day - timedelta(days=int(_t("sleep_duration_window_days")))
    feel_window = day - timedelta(days=int(_t("feel_window_days")))
    in_recovery_week, recovery_class = block_flags(day, blocks)
    live = [
        workout
        for workout in planned_workouts
        if getattr(workout, "status", None) not in LIVE_SESSION_EXCLUDED
    ]
    return GradingInputs(
        subject_date=day,
        acute=acute,
        hrv_nights=tuple(sorted(nights)),
        recovery_week_nights=recovery_week_nights(blocks),
        in_recovery_week=in_recovery_week,
        recovery_class_block=recovery_class,
        light_week=light_week_name(day, blocks) if recovery_class else None,
        sleep_score_raw=sleep_score_raw,
        sleep_score_age_adjusted=sleep_score_age_adjusted,
        sleep_minutes=sleep_minutes,
        sleep_minutes_history=tuple(
            minutes
            for night, minutes in sorted(sleep_minutes_history.items())
            if sleep_window <= night < day and minutes
        ),
        acwr=acwr,
        recovery_time_min=recovery_time_min,
        yesterday_load=yesterday_load,
        feel=feel,
        feel_history=tuple(
            score for night, score in sorted(feel_history.items()) if feel_window <= night < day
        ),
        readiness_level=readiness_level,
        readiness_score=readiness_score,
        readiness_lower_quartile=readiness_lower_quartile,
        sessions=tuple(classify_planned_workout(workout) for workout in live),
        rest_day=rest_day,
        notes_feel_notch=max(0, min(1, notes_feel_notch)),
        notes_feel_words=notes_feel_words,
        hrv_nights_away=week_nights_away(day, holiday_windows),
    )


def readiness_lower_quartile(baseline: Any) -> float | None:
    """His usual readiness floor, once the baseline holds enough mornings."""

    if baseline is None or getattr(baseline, "sample_count", 0) < _t("hrv_baseline_min_nights"):
        return None
    value = getattr(baseline, "lower_quartile_value", None)
    return float(value) if value is not None else None
