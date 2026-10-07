"""The next 13 weeks, built from his last plan (Batch 323).

Plan No. 2 ended on Sun 18 Oct 2026 with nothing loaded after it, and the app's own
plan builder (Batch 16) had never run: its build weeks were fixed (the same 75-minute
sweet spot, one 35-minute strength session), it had no FTP test and no strength
progression, its VO2 sessions said "ERG off" though he rides every session in ERG, and it
took its FTP from a drift signal the 6 Oct review found noisy. This module builds the next
plan instead, deterministically and without a model call:

* **his week**, read from his last plan's authored sessions (:func:`rhythm_from`): the
  weekday he did strength, VO2, Zone 2, sweet spot, sprints and the long ride, and the day
  he rested; Plan No. 2's week when there is nothing to read;
* **the progressions**, a reviewed table (:data:`WEEKS`, written into the ledger before
  the code): an FTP ramp test in week 1, build weeks that each ask a little more than the
  last, recovery weeks, consolidation and a taper, and two loaded, progressing dumbbell
  sessions a week;
* **his limits**: no week longer than his last plan's longest (:func:`fit_week` trims the
  Wednesday ride, then the long ride, if a cap is ever lower than the table), every target a
  percentage of FTP, every session a whole number of minutes the delivery rail can trace.

The VO2 protocol each build week uses is the existing toolkit's choice
(``vo2_progression.select_vo2_protocol``: 30/30 before week 7, Rønnestad 30/15 from it),
written for ERG. Every session uses Plan No. 2's step format, so the delivery rail, the
interval editor and the verdict read them as they read his plan. Mark-facing words were
signed off under Craig's delegation of 6 Oct 2026
(``docs/drafts/2026-10-07-batch-323-wording.md``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from src.services.plan_periodisation import BLOCK_SEQUENCE
from src.services.vo2_progression import (
    VO2_PROTOCOL_30_30,
    VO2_PROTOCOL_RONNESTAD_30_15,
    select_vo2_protocol,
)

WEEKDAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: Plan No. 2's longest week (week 5, 7 h 33), the cap when no last plan can be read.
DEFAULT_LONGEST_WEEK_MIN: Final = 453

#: A long ride is any Zone 2 ride this long or longer; shorter ones are his mid-week ride.
LONG_RIDE_MIN_MINUTES: Final = 90

#: The shortest the trim in :func:`fit_week` takes the Wednesday ride and the long ride.
ZONE2_FLOOR_MIN: Final = 30
LONG_RIDE_FLOOR_MIN: Final = 90

PLAN_FRAMEWORK: Final = "13-week 2121"


# -- his week -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeeklyRhythm:
    """The weekday (Monday 0) for each kind of session in his week."""

    strength_a: int = 0
    vo2: int = 1
    zone2: int = 2
    sweet_spot: int = 3
    rest: int = 4
    sprints: int = 5
    strength_b: int = 5
    long_ride: int = 6

    def is_valid(self) -> bool:
        """Every ride on its own day, the rest day empty, and the two strength days apart."""

        rides = (self.vo2, self.zone2, self.sweet_spot, self.sprints, self.long_ride)
        days = (*rides, self.rest, self.strength_a, self.strength_b)
        return (
            all(0 <= day <= 6 for day in days)
            and len(set(rides)) == len(rides)
            and self.rest not in rides
            and self.rest not in (self.strength_a, self.strength_b)
            and self.strength_a != self.strength_b
        )

    def to_packet(self) -> dict[str, str]:
        return {key: WEEKDAYS[day] for key, day in self.to_days().items()}

    def to_days(self) -> dict[str, int]:
        """The week as the draft and the builder carry it: each kind's weekday, Monday 0."""

        return {key: int(getattr(self, attribute)) for key, attribute in DAY_KEYS.items()}

    @classmethod
    def from_days(cls, days: Mapping[str, Any]) -> WeeklyRhythm:
        """The week from the draft's ``days``; raises ``ValueError`` on a missing or bad day."""

        values: dict[str, int] = {}
        for key, attribute in DAY_KEYS.items():
            raw = days.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 6:
                raise ValueError(f"{key} must be a weekday from 0 (Monday) to 6 (Sunday)")
            values[attribute] = raw
        return cls(**values)


#: The draft's names for each kind of session in his week, and the field each one is.
DAY_KEYS: Final = {
    "strengthA": "strength_a",
    "vo2": "vo2",
    "zone2": "zone2",
    "sweetSpot": "sweet_spot",
    "rest": "rest",
    "sprints": "sprints",
    "strengthB": "strength_b",
    "longRide": "long_ride",
}


#: Plan No. 2's week (observed in its authored sessions, 6 Oct 2026).
PLAN_NO_2_RHYTHM: Final = WeeklyRhythm()


@dataclass(frozen=True, slots=True)
class PastSession:
    """One authored session of his last plan, as :func:`rhythm_from` reads it."""

    workout_date: date
    workout_type: str
    title: str
    minutes: int
    block_type: str
    week_number: int


def _mode(days: Sequence[int]) -> int | None:
    """The commonest weekday, the earliest on a tie; ``None`` for none."""

    if not days:
        return None
    counts = Counter(days)
    best = max(counts.values())
    return min(day for day, count in counts.items() if count == best)


def _is_sprints(session: PastSession) -> bool:
    title = session.title.lower()
    return "neuromuscular" in title or "sprint" in title


def rhythm_from(sessions: Sequence[PastSession]) -> WeeklyRhythm:
    """His week, from the build weeks of his last plan; Plan No. 2's week if unreadable."""

    build = [session for session in sessions if session.block_type == "build"]
    if not build:
        return PLAN_NO_2_RHYTHM
    rides = [session for session in build if session.workout_type.startswith("bike_")]
    endurance = [session for session in rides if session.workout_type == "bike_endurance"]
    sprints = _mode([s.workout_date.weekday() for s in endurance if _is_sprints(s)])
    long_ride = _mode(
        [
            s.workout_date.weekday()
            for s in endurance
            if s.minutes >= LONG_RIDE_MIN_MINUTES and not _is_sprints(s)
        ]
    )
    zone2 = _mode(
        [
            s.workout_date.weekday()
            for s in endurance
            if s.minutes < LONG_RIDE_MIN_MINUTES and not _is_sprints(s)
        ]
    )
    vo2 = _mode([s.workout_date.weekday() for s in rides if s.workout_type == "bike_vo2"])
    sweet_spot = _mode(
        [s.workout_date.weekday() for s in rides if s.workout_type == "bike_sweet_spot"]
    )
    strength_counts = Counter(
        s.workout_date.weekday() for s in build if s.workout_type.startswith("strength")
    )
    commonest = sorted(strength_counts.items(), key=lambda item: (-item[1], item[0]))
    strength_days = sorted(day for day, _count in commonest[:2])
    weeks = {s.week_number for s in build}
    empty_by_week = [
        day
        for week in sorted(weeks)
        for day in range(7)
        if not any(s.week_number == week and s.workout_date.weekday() == day for s in build)
    ]
    rest = _mode(empty_by_week)
    found = (sprints, long_ride, zone2, vo2, sweet_spot, rest)
    if any(day is None for day in found) or len(strength_days) < 2:
        return PLAN_NO_2_RHYTHM
    assert sprints is not None and long_ride is not None and zone2 is not None
    assert vo2 is not None and sweet_spot is not None and rest is not None
    rhythm = WeeklyRhythm(
        strength_a=strength_days[0],
        vo2=vo2,
        zone2=zone2,
        sweet_spot=sweet_spot,
        rest=rest,
        sprints=sprints,
        strength_b=strength_days[1],
        long_ride=long_ride,
    )
    return rhythm if rhythm.is_valid() else PLAN_NO_2_RHYTHM


def longest_week_minutes(sessions: Sequence[PastSession]) -> int | None:
    """His last plan's longest week, in planned minutes, or ``None`` for no sessions."""

    totals: Counter[int] = Counter()
    for session in sessions:
        totals[session.week_number] += session.minutes
    return max(totals.values()) if totals else None


# -- the sessions, in Plan No. 2's step format -----------------------------------------------


@dataclass(frozen=True, slots=True)
class Session:
    """One planned session: what the draft, the builder and the lock carry."""

    kind: str
    title: str
    workout_type: str
    minutes: int
    intensity_target: str
    structured_workout: dict[str, Any]

    def to_draft(self, *, day_offset: int, slot: int, workout_date: date) -> dict[str, Any]:
        return {
            "dayOffset": day_offset,
            "slot": slot,
            "workoutDate": workout_date.isoformat(),
            "kind": self.kind,
            "title": self.title,
            "workoutType": self.workout_type,
            "plannedDurationMin": self.minutes,
            "intensityTarget": self.intensity_target,
            "structuredWorkout": self.structured_workout,
        }


def _minutes(seconds: int) -> int:
    if seconds % 60:
        raise ValueError(f"a session must be whole minutes, not {seconds} s")
    return seconds // 60


#: Plan No. 2's "WarmUp v1.3" before a hard session: 17 minutes.
def _vo2_warm_up() -> list[dict[str, Any]]:
    return [
        {"label": "Warm-up ramp 55→80%", "minutes": 10, "ramp": [55, 80]},
        {
            "label": "Primer 2×30s @100% / 55%",
            "target": "100%",
            "pattern": "2 x 30s / 30s @55%",
            "cadenceRpm": 95,
        },
        {"label": "Warm-up @72%", "minutes": 3, "target": "72%"},
        {"label": "Warm-up @55%", "minutes": 2, "target": "55%"},
    ]


#: The sweet spot warm-up of Plan No. 2: 15 minutes.
def _sweet_spot_warm_up() -> list[dict[str, Any]]:
    return [
        {"label": "Warm-up ramp 55→80%", "minutes": 8, "ramp": [55, 80]},
        {
            "label": "Primer 2×30s @100% / 55%",
            "target": "100%",
            "pattern": "2 x 30s / 30s @55%",
            "cadenceRpm": 95,
        },
        {"label": "Warm-up @72%", "minutes": 3, "target": "72%"},
        {"label": "Warm-up @55%", "minutes": 2, "target": "55%"},
    ]


def _cool_down(minutes: int = 10) -> dict[str, Any]:
    return {"label": "Cool-down ramp", "minutes": minutes, "ramp": [70, 45]}


def ramp_test() -> Session:
    """Week 1's FTP test: one-minute steps from 50% of FTP, +6% a minute, in ERG."""

    steps: list[dict[str, Any]] = [
        {"label": "Warm-up ramp 45→65%", "minutes": 10, "ramp": [45, 65]},
        {"label": "Settle @50%", "minutes": 3, "target": "50%"},
    ]
    for index in range(17):
        pct = 50 + 6 * index
        steps.append({"label": f"Ramp step {index + 1} @{pct}%", "minutes": 1, "target": f"{pct}%"})
    steps.append({"label": "Cool-down ramp", "minutes": 10, "ramp": [60, 40]})
    return Session(
        kind="test",
        title="FTP Ramp Test",
        workout_type="bike_threshold",
        minutes=40,
        intensity_target=(
            "Ramp test: one-minute steps from 50% of FTP, up 6% a minute, in ERG until you "
            "can't hold the step"
        ),
        structured_workout={
            "format": "bike",
            "test": "ramp",
            "summary": (
                "10 min ramp → 3 min @50% → one-minute steps from 50% rising 6% a minute, "
                "ridden in ERG until you can't hold the step → 10 min cool-down. Your new FTP "
                "is three-quarters of the best minute you held: set it in Zwift."
            ),
            "steps": steps,
        },
    )


def micro_vo2(week_number: int, *, sets: int, reps: int, pct: int) -> Session:
    """A build week's VO2: the toolkit's protocol for the week, written for ERG."""

    protocol = select_vo2_protocol(week_number, block_type="build")
    work, rest = (30, 30) if protocol.key == VO2_PROTOCOL_30_30 else (30, 15)
    between = 4 if protocol.key == VO2_PROTOCOL_30_30 else 3
    name = "30/30s" if protocol.key == VO2_PROTOCOL_30_30 else "30/15s"
    steps = _vo2_warm_up()
    for index in range(sets):
        steps.append(
            {
                "label": f"{name} @{pct}% set {index + 1}",
                "target": f"{pct}%",
                "pattern": f"{reps} x {work}s / {rest}s @55%",
                "cadenceRpm": 95,
            }
        )
        if index < sets - 1:
            steps.append({"label": "Recover between sets", "minutes": between, "target": "60%"})
    steps.append(_cool_down())
    seconds = (17 + 10 + between * (sets - 1)) * 60 + sets * reps * (work + rest)
    return Session(
        kind="vo2",
        title=f"VO₂ ({name}, {sets} × {reps} @ {pct}%)",
        workout_type="bike_vo2",
        minutes=_minutes(seconds),
        intensity_target=f"{pct}% FTP in ERG, {work}s on / {rest}s easy",
        structured_workout={
            "format": "bike",
            "vo2Protocol": protocol.key,
            "summary": (
                f"WarmUp v1.3 · Main {sets} × {reps} of {work}s @{pct}% / {rest}s @55% "
                f"({between} min @60% between sets) · CoolDown 10 min ramp"
            ),
            "steps": steps,
        },
    )


def vo2_light(reps: int) -> Session:
    """Plan No. 2's recovery-week VO2: two-minute efforts at 115%."""

    steps: list[dict[str, Any]] = [
        {"label": "Warm-up ramp 55→80%", "minutes": 10, "ramp": [55, 80]},
        {"label": "Primer 2×30s @100%", "minutes": 1, "target": "100%", "cadenceRpm": 95},
        {"label": "Warm-up @72%", "minutes": 3, "target": "72%"},
        {"label": "Warm-up @55%", "minutes": 2, "target": "55%"},
        {
            "label": f"VO₂ {reps}×2min @115%",
            "target": "115%",
            "pattern": f"{reps} x 2min / 3min @60%",
        },
        _cool_down(),
    ]
    return Session(
        kind="vo2",
        title=f"VO₂ Light ({reps} × 2 min @ 115%)",
        workout_type="bike_vo2",
        minutes=16 + 5 * reps + 10,
        intensity_target="115% FTP intervals",
        structured_workout={
            "format": "bike",
            "summary": (
                f"WarmUp v1.3 · Main {reps} × 2min @115% (3min @60% recover) · CoolDown 10 min ramp"
            ),
            "steps": steps,
        },
    )


def vo2_primer() -> Session:
    """Plan No. 2's taper VO2: three one-minute efforts at 120%."""

    return Session(
        kind="vo2",
        title="VO₂ Primer (3 × 1 min @ 120%)",
        workout_type="bike_vo2",
        minutes=30,
        intensity_target="VO₂ (see prescription)",
        structured_workout={
            "format": "bike",
            "summary": (
                "WarmUp v1.3 · Main 3 × 1min @120% (2min @60% recover) · CoolDown 8 min ramp"
            ),
            "steps": [
                {"label": "Warm-up ramp 55→80%", "minutes": 8, "ramp": [55, 80]},
                {"label": "Primer 2×30s @100%", "minutes": 1, "target": "100%", "cadenceRpm": 95},
                {"label": "Warm-up @72%", "minutes": 2, "target": "72%"},
                {"label": "Warm-up @55%", "minutes": 2, "target": "55%"},
                {"label": "VO₂ 3×1min @120%", "target": "120%", "pattern": "3 x 1min / 2min @60%"},
                _cool_down(8),
            ],
        },
    )


def sweet_spot(reps: int, minutes: int, pct: int) -> Session:
    """A sweet spot session: ``reps`` × ``minutes`` at ``pct``, 3 minutes easy after each."""

    steps = _sweet_spot_warm_up()
    steps.append(
        {
            "label": f"Sweet Spot {reps}×{minutes} min @{pct}%",
            "target": f"{pct}%",
            "pattern": f"{reps} x {minutes}min / 3min @60%",
            "cadenceRpm": 90,
        }
    )
    steps.append(_cool_down())
    return Session(
        kind="sweet_spot",
        title=f"Sweet Spot ({reps} × {minutes} min @ {pct}%)",
        workout_type="bike_sweet_spot",
        minutes=15 + reps * (minutes + 3) + 10,
        intensity_target=f"Sweet Spot ~{pct}% FTP",
        structured_workout={
            "format": "bike",
            "summary": (
                f"WarmUp v1.3 · Main {reps} × {minutes} min @{pct}% (3 min @60% recover) · "
                "CoolDown 10 min ramp"
            ),
            "steps": steps,
        },
    )


def sweet_spot_single(minutes: int, pct: int, *, title: str, recover: bool) -> Session:
    """One sweet spot block: Plan No. 2's light, consolidation and primer sessions."""

    steps = _sweet_spot_warm_up()
    steps.append(
        {
            "label": f"Sweet Spot 1×{minutes} min @{pct}%",
            "minutes": minutes,
            "target": f"{pct}%",
            "cadenceRpm": 90,
        }
    )
    if recover:
        steps.append({"label": "Recover @60%", "minutes": 3, "target": "60%"})
    cool = 10 if recover else 8
    steps.append(_cool_down(cool))
    return Session(
        kind="sweet_spot",
        title=title,
        workout_type="bike_sweet_spot",
        minutes=15 + minutes + (3 if recover else 0) + cool,
        intensity_target=f"Sweet Spot ~{pct}% FTP",
        structured_workout={
            "format": "bike",
            "summary": (
                f"WarmUp v1.3 · Main 1 × {minutes} min @{pct}%"
                + (" (3 min @60% recover)" if recover else "")
                + f" · CoolDown {cool} min ramp"
            ),
            "steps": steps,
        },
    )


def zone2(minutes: int) -> Session:
    """His mid-week Zone 2 ride, Plan No. 2's shape, at ``minutes``."""

    ramp_in, ramp_out = (10, 10) if minutes >= 55 else (5, 5)
    main = minutes - ramp_in - ramp_out
    pct = 67 if minutes >= 55 else 65
    return Session(
        kind="zone2",
        title="Z2",
        workout_type="bike_endurance",
        minutes=minutes,
        intensity_target="Zone 2 ~65–72% FTP",
        structured_workout={
            "format": "bike",
            "summary": f"{ramp_in} min ramp → {main} min @{pct}% → {ramp_out} min ramp",
            "steps": [
                {"label": "Warm-up ramp 55→80%", "minutes": ramp_in, "ramp": [55, 80]},
                {"label": f"Z2 @{pct}%", "minutes": main, "target": f"{pct}%"},
                {"label": "Cool-down ramp", "minutes": ramp_out, "ramp": [60, 40]},
            ],
        },
    )


def zone2_sprints() -> Session:
    """Plan No. 2's Saturday: Zone 2 with cadence surges and six 12-second sprints."""

    return Session(
        kind="sprints",
        title="Z2 + Neuromuscular",
        workout_type="bike_endurance",
        minutes=58,
        intensity_target="Zone 2 ~65–72% FTP",
        structured_workout={
            "format": "bike",
            "summary": (
                "5 min ramp → 30 min @65% with cadence surges (5 × 1 min @100–105 rpm) → "
                "neuromuscular block 6 × (12 s @185% + 2:48 @55%) → 5 min @50%"
            ),
            "steps": [
                {"label": "Warm-up ramp 50→75%", "minutes": 5, "ramp": [50, 75]},
                {
                    "label": "Z2 @65% + cadence surges (100–105 rpm)",
                    "target": "65%",
                    "pattern": "5 x 1min / 5min @65%",
                    "cadenceRpm": 102,
                },
                {
                    "label": "Neuromuscular sprints @185%",
                    "target": "185%",
                    "pattern": "6 x 12s / 168s @55%",
                },
                {"label": "Cool-down @50%", "minutes": 5, "target": "50%"},
            ],
        },
    )


def easy_zone2(minutes: int, *, title: str = "Easy Z2", kind: str = "sprints") -> Session:
    """An easy Zone 2 ride at 60–65% (Plan No. 2's recovery and taper rides)."""

    ramp = 10 if minutes >= 60 else 5
    main = minutes - 2 * ramp
    return Session(
        kind=kind,
        title=title,
        workout_type="bike_endurance",
        minutes=minutes,
        intensity_target="Zone 2 ~60–65% FTP",
        structured_workout={
            "format": "bike",
            "summary": f"{ramp} min ramp → {main} min @60–65% (midpoint 62%) → {ramp} min ramp",
            "steps": [
                {"label": "Warm-up ramp 45→60%", "minutes": ramp, "ramp": [45, 60]},
                {"label": "Easy Z2 60–65%", "minutes": main, "target": "60–65%"},
                {"label": "Cool-down ramp", "minutes": ramp, "ramp": [60, 45]},
            ],
        },
    )


def long_zone2(minutes: int) -> Session:
    """The long ride: Plan No. 2's shape, 65–72% between a 10-minute ramp each end."""

    main = minutes - 20
    return Session(
        kind="long",
        title="Long Z2",
        workout_type="bike_endurance",
        minutes=minutes,
        intensity_target="Zone 2 ~65–72% FTP",
        structured_workout={
            "format": "bike",
            "summary": f"10 min ramp → {main} min @65–72% (midpoint 68%) → 10 min ramp",
            "steps": [
                {"label": "Warm-up ramp 45→60%", "minutes": 10, "ramp": [45, 60]},
                {"label": "Long Z2 65–72%", "minutes": main, "target": "65–72%"},
                {"label": "Cool-down ramp", "minutes": 10, "ramp": [70, 45]},
            ],
        },
    )


@dataclass(frozen=True, slots=True)
class StrengthDose:
    """One week's prescription for both dumbbell sessions."""

    sets_reps: str
    effort: str
    minutes: int


_STRENGTH_A_MOVES: Final = (
    "goblet squat, Romanian deadlift, reverse lunge (each leg), one-arm row (each arm), "
    "calf raise, side plank (30 s each side)"
)
_STRENGTH_B_MOVES: Final = (
    "shoulder press, reverse-grip row, floor press, pullover, curl, triceps extension, "
    "step-up (each leg), dead bug"
)


def strength(dose: StrengthDose, *, session: str) -> Session:
    """A loaded dumbbell session, A (legs and back) or B (upper body)."""

    moves = _STRENGTH_A_MOVES if session == "A" else _STRENGTH_B_MOVES
    title = "Dumbbells A (legs and back)" if session == "A" else "Dumbbells B (upper body)"
    return Session(
        kind=f"strength_{session.lower()}",
        title=title,
        workout_type="strength_maintenance",
        minutes=dose.minutes,
        intensity_target=f"Dumbbells {dose.sets_reps}",
        structured_workout={
            "format": "strength",
            "summary": (
                f"{moves[0].upper()}{moves[1:]}. {dose.sets_reps}, {dose.effort}. Rest about a "
                "minute between sets."
            ),
            "steps": [
                {
                    "label": f"Dumbbell sets: {moves}",
                    "target": f"{dose.sets_reps}, {dose.effort}",
                    "minutes": dose.minutes,
                }
            ],
        },
    )


# -- the progressions: the ledger's table ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeekPlan:
    """One week of the table: what each kind of session is that week."""

    label: str
    strength: StrengthDose
    vo2: Session
    zone2_min: int
    sweet_spot: Session
    sprints: Session
    long_ride: Session


_LIGHT_STRENGTH_10: Final = StrengthDose("2 × 10", "light: an easier weight than last week", 20)
_LIGHT_STRENGTH_8: Final = StrengthDose("2 × 8", "light: an easier weight than last week", 20)


def _recovery_week() -> WeekPlan:
    return WeekPlan(
        label="RECOVERY",
        strength=_LIGHT_STRENGTH_10,
        vo2=vo2_light(3),
        zone2_min=60,
        sweet_spot=sweet_spot_single(
            20, 89, title="Sweet Spot Light (1 × 20 min @ 89%)", recover=True
        ),
        sprints=easy_zone2(45, title="Easy Z2 (No Sprints)"),
        long_ride=easy_zone2(90, kind="long"),
    )


def _build_weeks() -> tuple[WeekPlan, ...]:
    recovery = _recovery_week()
    later_recovery = WeekPlan(
        label=recovery.label,
        strength=_LIGHT_STRENGTH_8,
        vo2=recovery.vo2,
        zone2_min=recovery.zone2_min,
        sweet_spot=recovery.sweet_spot,
        sprints=recovery.sprints,
        long_ride=recovery.long_ride,
    )
    reserve = "finish each set with 2–3 reps in reserve"
    return (
        WeekPlan(
            "TEST + BUILD",
            StrengthDose("2 × 12", "light: finish each set with 3–4 reps in reserve", 20),
            ramp_test(),
            75,
            sweet_spot(2, 25, 89),
            zone2_sprints(),
            long_zone2(120),
        ),
        WeekPlan(
            "BUILD",
            StrengthDose("3 × 12", reserve, 25),
            micro_vo2(2, sets=2, reps=10, pct=130),
            75,
            sweet_spot(2, 30, 89),
            zone2_sprints(),
            long_zone2(120),
        ),
        recovery,
        WeekPlan(
            "BUILD",
            StrengthDose("3 × 10", "one weight up from week 2; 2 reps in reserve", 25),
            micro_vo2(4, sets=2, reps=12, pct=130),
            75,
            sweet_spot(3, 20, 90),
            zone2_sprints(),
            long_zone2(120),
        ),
        WeekPlan(
            "BUILD",
            StrengthDose("3 × 10", "the same weight, or one up if week 4 felt easy", 25),
            micro_vo2(5, sets=3, reps=10, pct=130),
            55,
            sweet_spot(2, 35, 90),
            zone2_sprints(),
            long_zone2(120),
        ),
        later_recovery,
        WeekPlan(
            "BUILD (30/15s)",
            StrengthDose("3 × 8", "one weight up; 2 reps in reserve", 25),
            micro_vo2(7, sets=2, reps=16, pct=125),
            45,
            sweet_spot(3, 25, 90),
            zone2_sprints(),
            long_zone2(135),
        ),
        WeekPlan(
            "BUILD (30/15s)",
            StrengthDose(
                "4 × 8 on the first three moves, 3 × 8 on the rest", "2 reps in reserve", 25
            ),
            micro_vo2(8, sets=3, reps=12, pct=125),
            35,
            sweet_spot(2, 40, 90),
            zone2_sprints(),
            long_zone2(135),
        ),
        later_recovery,
        WeekPlan(
            "BUILD (30/15s)",
            StrengthDose("3 × 6–8", "one weight up; 1–2 reps in reserve", 25),
            micro_vo2(10, sets=4, reps=10, pct=125),
            30,
            sweet_spot(2, 40, 91),
            zone2_sprints(),
            long_zone2(135),
        ),
        WeekPlan(
            "BUILD (30/15s)",
            StrengthDose(
                "4 × 6–8 on the first three moves, 3 × 6–8 on the rest",
                "1–2 reps in reserve",
                25,
            ),
            micro_vo2(11, sets=4, reps=10, pct=128),
            30,
            sweet_spot(2, 40, 92),
            zone2_sprints(),
            long_zone2(135),
        ),
        WeekPlan(
            "CONSOLIDATION",
            StrengthDose("3 × 8", "the same weights; 2 reps in reserve", 25),
            vo2_light(4),
            60,
            sweet_spot_single(30, 90, title="Sweet Spot (1 × 30 min @ 90%)", recover=True),
            easy_zone2(45),
            easy_zone2(90, kind="long"),
        ),
        WeekPlan(
            "TAPER",
            StrengthDose("2 × 8", "lighter: finish each set with 3–4 reps in reserve", 20),
            vo2_primer(),
            45,
            sweet_spot_single(12, 89, title="Sweet Spot Primer (1 × 12 min @ 89%)", recover=False),
            easy_zone2(40),
            easy_zone2(45, title="Optional Ride (45 min @ 60–65%) OR Rest", kind="long"),
        ),
    )


#: The ledger's Plan No. 3 table, week 1 to 13 (``docs/phase-batches.md``, Batch 323).
WEEKS: Final[tuple[WeekPlan, ...]] = _build_weeks()

assert len(WEEKS) == len(BLOCK_SEQUENCE)


# -- one week, within his longest ------------------------------------------------------------


def week_sessions(week: WeekPlan, rhythm: WeeklyRhythm) -> list[tuple[int, int, Session]]:
    """The week's sessions as ``(weekday, slot, session)``, rides before strength."""

    by_day: dict[int, list[Session]] = {}
    ordered = (
        (rhythm.vo2, week.vo2),
        (rhythm.zone2, zone2(week.zone2_min)),
        (rhythm.sweet_spot, week.sweet_spot),
        (rhythm.sprints, week.sprints),
        (rhythm.long_ride, week.long_ride),
        (rhythm.strength_a, strength(week.strength, session="A")),
        (rhythm.strength_b, strength(week.strength, session="B")),
    )
    for day, session in ordered:
        by_day.setdefault(day, []).append(session)
    return [
        (day, slot, session) for day in sorted(by_day) for slot, session in enumerate(by_day[day])
    ]


def fit_week(week: WeekPlan, cap_min: int) -> WeekPlan:
    """The week trimmed to ``cap_min``: the Wednesday ride first, then the long ride.

    Plan No. 3's table already sits inside Plan No. 2's longest week (453 minutes); the trim
    is for a cap read from a lighter last plan. Neither ride goes below its floor.
    """

    total = _week_minutes(week)
    if total <= cap_min:
        return week
    excess = total - cap_min
    zone2_cut = min(excess, max(0, week.zone2_min - ZONE2_FLOOR_MIN))
    week = _replace_zone2(week, week.zone2_min - zone2_cut)
    excess -= zone2_cut
    if excess > 0 and week.long_ride.kind == "long" and week.long_ride.title == "Long Z2":
        long_cut = min(excess, max(0, week.long_ride.minutes - LONG_RIDE_FLOOR_MIN))
        week = _replace_long(week, long_ride=long_zone2(week.long_ride.minutes - long_cut))
    return week


def _week_minutes(week: WeekPlan) -> int:
    return (
        week.vo2.minutes
        + week.zone2_min
        + week.sweet_spot.minutes
        + week.sprints.minutes
        + week.long_ride.minutes
        + 2 * week.strength.minutes
    )


def _replace_zone2(week: WeekPlan, minutes: int) -> WeekPlan:
    return WeekPlan(
        week.label,
        week.strength,
        week.vo2,
        minutes,
        week.sweet_spot,
        week.sprints,
        week.long_ride,
    )


def _replace_long(week: WeekPlan, *, long_ride: Session) -> WeekPlan:
    return WeekPlan(
        week.label,
        week.strength,
        week.vo2,
        week.zone2_min,
        week.sweet_spot,
        week.sprints,
        long_ride,
    )


# -- the draft ------------------------------------------------------------------------------


_FOCUS: Final = {
    "build": "Progress aerobic capacity and quality bike work.",
    "recovery": "Absorb load and protect sleep quality.",
    "taper": "Sharpen without carrying fatigue.",
    "consolidation": "Stabilize gains and set up the next cycle.",
}


def default_start(today: date, previous_end: date | None) -> date:
    """The day after his last plan ends when that is a Monday still to come; else next Monday."""

    next_monday = today + timedelta(days=7 - today.weekday())
    if previous_end is not None:
        candidate = previous_end + timedelta(days=1)
        if candidate.weekday() == 0 and candidate >= today:
            return candidate
    return next_monday


def _hours(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


def _long_ride_words(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} hours"
    if rest == 30:
        return f"{hours}½ hours"
    return f"{hours} hours {rest}"


def why_this_plan(
    *,
    rhythm: WeeklyRhythm,
    previous_name: str | None,
    weeks: Sequence[dict[str, Any]],
    longest_week_min: int,
    start_date: date,
    days_kept: bool = True,
) -> list[str]:
    """The draft's "why this plan" note, in plain words (signed off under delegation).

    It explains the plan as proposed for his days and start date; changes he makes to single
    sessions are listed beside it, not folded in (Batch 324). ``days_kept`` is false once he
    has set his own days, so the note stops saying they are his last plan's.
    """

    days = WEEKDAYS
    previous = previous_name or "your last plan"
    sprints_and_strength = (
        f"Zone 2 with sprints and dumbbells on {days[rhythm.sprints]}"
        if rhythm.strength_b == rhythm.sprints
        else (
            f"Zone 2 with sprints on {days[rhythm.sprints]}, dumbbells on {days[rhythm.strength_b]}"
        )
    )
    opening = f"It keeps your week from {previous}" if days_kept else "Your week, as you set it"
    lines = [
        (
            f"{opening}: dumbbells on {days[rhythm.strength_a]}, VO₂ "
            f"on {days[rhythm.vo2]}, Zone 2 on {days[rhythm.zone2]}, sweet spot on "
            f"{days[rhythm.sweet_spot]}, {days[rhythm.rest]} off, {sprints_and_strength}, and "
            f"the long ride on {days[rhythm.long_ride]}."
        )
    ]
    test_day = start_date + timedelta(days=rhythm.vo2)
    lines.append(
        f"Week 1 opens with an FTP ramp test on {days[rhythm.vo2]} "
        f"{test_day.day} {test_day.strftime('%B')}. Ride it in ERG until you can't hold the "
        "step. Your new FTP is three-quarters of the best minute you held: set it in Zwift, "
        "and every session follows, because each target is a percentage of FTP."
    )
    long_rides = [
        int(workout["plannedDurationMin"])
        for week in weeks
        if week["blockType"] == "build"
        for workout in week["workouts"]
        if workout["kind"] == "long"
    ]
    lines.append(
        "Each build week asks a little more than the one before: sweet spot from 2 × 25 "
        "minutes to 2 × 40, VO₂ from 30/30s to 30/15s, and the long ride from "
        f"{_long_ride_words(min(long_rides))} to {_long_ride_words(max(long_rides))}."
    )
    lines.append(
        f"Two dumbbell sessions a week, on {days[rhythm.strength_a]} and "
        f"{days[rhythm.strength_b]}, legs as well as arms now, getting heavier through the "
        "plan. Recovery weeks go lighter."
    )
    lines.append(
        f"No week is longer than the longest week of {previous} ({_hours(longest_week_min)})."
    )
    end_date = start_date + timedelta(days=len(weeks) * 7 - 1)
    holidays = [
        (name, day)
        for name, day in (
            ("Christmas Day", date(start_date.year, 12, 25)),
            ("New Year's Day", date(start_date.year + 1, 1, 1)),
        )
        if start_date <= day <= end_date
    ]
    on_rest = [name for name, day in holidays if day.weekday() == rhythm.rest]
    if holidays and len(on_rest) == len(holidays):
        names = " and ".join(on_rest)
        plural = "days" if len(on_rest) > 1 else "day"
        lines.append(f"{names} fall on your {days[rhythm.rest]} rest {plural}.")
    else:
        for name, day in holidays:
            if day.weekday() != rhythm.rest:
                lines.append(f"{name} is a {days[day.weekday()]}: change that day if you need to.")
    lines.append("Nothing changes until you accept it, and you can change any day first.")
    return lines


def next_plan_draft(
    *,
    start_date: date,
    ftp_watts: int,
    athlete_name: str,
    generated_at_utc: datetime,
    rhythm: WeeklyRhythm = PLAN_NO_2_RHYTHM,
    longest_week_min: int = DEFAULT_LONGEST_WEEK_MIN,
    plan_number: int | None = None,
    previous_name: str | None = None,
    proposed_rhythm: WeeklyRhythm | None = None,
) -> dict[str, Any]:
    """The next plan's draft content: the shape the builder, refine, change and lock read.

    Batch 324: every session carries an id that survives a move, the draft a revision that
    each change raises, his days as weekday numbers, the change log, and the proposal it was
    first built from (``proposed_rhythm``, his last plan's week, defaults to ``rhythm``), so
    "back to the plan as proposed" can rebuild it exactly.
    """

    if start_date.weekday() != 0:
        raise ValueError("a plan starts on a Monday")
    proposed = proposed_rhythm or rhythm
    weeks: list[dict[str, Any]] = []
    session_number = 0
    for index, (block_type, planned) in enumerate(zip(BLOCK_SEQUENCE, WEEKS, strict=True), 1):
        week = fit_week(planned, longest_week_min)
        week_start = start_date + timedelta(days=(index - 1) * 7)
        workouts = []
        for day, slot, session in week_sessions(week, rhythm):
            session_number += 1
            workouts.append(
                {
                    "id": session_id(session_number),
                    **session.to_draft(
                        day_offset=day,
                        slot=slot,
                        workout_date=week_start + timedelta(days=day),
                    ),
                }
            )
        weeks.append(
            {
                "weekNumber": index,
                "blockType": block_type,
                "label": week.label,
                "focus": _FOCUS.get(block_type, ""),
                "startDate": week_start.isoformat(),
                "endDate": (week_start + timedelta(days=6)).isoformat(),
                "totalMin": sum(int(w["plannedDurationMin"]) for w in workouts),
                "workouts": workouts,
            }
        )
    name = f"Plan No. {plan_number}" if plan_number is not None else "Your next plan"
    return {
        "status": "draft",
        "framework": PLAN_FRAMEWORK,
        "planName": name,
        "planNumber": plan_number,
        "startDate": start_date.isoformat(),
        "endDate": (start_date + timedelta(days=len(weeks) * 7 - 1)).isoformat(),
        "ftpWatts": ftp_watts,
        "athleteName": athlete_name,
        "generatedAtUtc": generated_at_utc.isoformat(),
        "lockedAtUtc": None,
        "progressionProposal": None,
        "basis": {
            "previousPlan": previous_name,
            "rhythm": rhythm.to_packet(),
            "longestWeekMin": longest_week_min,
            "ftpSource": "profile",
            "vo2Protocols": [VO2_PROTOCOL_30_30, VO2_PROTOCOL_RONNESTAD_30_15],
        },
        "whyThisPlan": why_this_plan(
            rhythm=rhythm,
            previous_name=previous_name,
            weeks=weeks,
            longest_week_min=longest_week_min,
            start_date=start_date,
            days_kept=rhythm == proposed,
        ),
        "days": rhythm.to_days(),
        "revision": 0,
        "changes": [],
        "proposal": {"startDate": start_date.isoformat(), "days": proposed.to_days()},
        "weeks": weeks,
    }


def session_id(number: int) -> str:
    """A draft session's id: ``s001`` for the first session of the plan."""

    return f"s{number:03d}"
