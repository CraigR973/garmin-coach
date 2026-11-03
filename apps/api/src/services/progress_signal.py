"""Progress has a signal: fitness drift from fixed-power rides, and a "ready to progress"
note (Batch 319).

Aerobic fitness shows most cleanly as heart rate at a fixed power: the same watts, held
in ERG, for at least 20 minutes (``services.fixed_power``). His mid-week Zone 2 ride is
such a ride most weeks. This compares his heart rate on those rides over the last four
weeks with the four before, at the same power (within :data:`POWER_BAND_WATTS` of the
power both windows share), and reads nothing from any other ride: a sweet spot or a long
ride drifts for reasons that are not fitness.

The note (319.3) says he may be ready for a little more when his last three hard sessions
each landed at least nine in ten work intervals on target and he woke up fresh the morning
after each (that morning's call was not cautious). It suggests a ramp test or one step up
and is never applied: his FTP and his plan move only when he chooses (the ramp test,
Batch 336, sets his FTP). The weekly review stops proposing an FTP from watts per
heartbeat across every ride (``insights.detect_ftp_drift``), which moved with the mix.

Every threshold here is **provisional** (Decision #459), chosen before his data could
test it. Pure.

Batch 367.1 (CI359-02, Decision #465): the note's first live firing, in the 1 Nov review,
rested on a Zone 2 ride with six 12-second sprints and offered "a ramp test, or one small
step up" into the recovery week the same review said needed no changes. So only key
sessions count (VO₂, threshold, sweet spot: :data:`KEY_SESSION_TYPES`), and the note holds
in a light week (the week reviewed or the week ahead) and within four weeks of a test,
either side (:func:`progress_hold`). Both only add caution.

Batch 367.2 (ST363-02, amends #459): ERG holds every target (55 of 55 work intervals since
Plan No. 3), so "on target" carried no information and the note was a run of three
Greens, which shuffled mornings produce as often. The note now also needs what ERG cannot
fix: each of the three sessions felt no harder than :data:`MANAGEABLE_EFFORT` out of 10 (his
own check-in), and his heart rate at fixed power is not slipping. It says what happened and
that the plan's next step looks right; it no longer offers a test or a step up.

Batch 367.3 (ST363-03): a drift is called only when the change clears both
:data:`DRIFT_BPM` and twice its own standard error, with each window's spread floored at his
ride-to-ride spread (:data:`RIDE_HR_SD_FLOOR`); 3 rides a side made the old 3 bpm line about
one standard error, so noise alone called a change on one judged Sunday in seven.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, median, stdev
from typing import Any, Final

WINDOW_DAYS: Final = 28
MIN_RIDES_EACH: Final = 3
#: Rides count as the same power within this many watts of the windows' shared median.
POWER_BAND_WATTS: Final = 6.0
#: A fall or rise in heart rate at that power smaller than this is noise.
DRIFT_BPM: Final = 3.0
#: Batch 367.3: his heart rate at Z2 power varies 3.56 bpm ride to ride (ST363-03, 39 rides);
#: a window's spread is never taken as smaller than this.
RIDE_HR_SD_FLOOR: Final = 3.5
#: Batch 367.3: a change must clear this many standard errors of the difference.
DRIFT_SE: Final = 2.0
#: Batch 367.2: the effort (0–10, his check-in) above which a session did not feel manageable.
MANAGEABLE_EFFORT: Final = 7
#: Each of his last hard sessions must land this share of its work intervals on target.
ON_TARGET_SHARE: Final = 0.9
#: How many hard sessions in a row.
HARD_SESSIONS_IN_A_ROW: Final = 3
#: Batch 367.1: the sessions that count as hard work. A Zone 2 ride with sprints is not one.
KEY_SESSION_TYPES: Final = frozenset({"bike_vo2", "bike_threshold", "bike_sweet_spot"})
#: Batch 367.1: no note within this many days of a test, before or after it.
TEST_QUIET_DAYS: Final = 28
HOLD_LIGHT_WEEK: Final = "light_week"
HOLD_NEAR_TEST: Final = "near_test"
HOLD_SLIPPING: Final = "slipping"

STATUS_IMPROVING: Final = "improving"
STATUS_STEADY: Final = "steady"
STATUS_SLIPPING: Final = "slipping"
STATUS_NOT_ENOUGH: Final = "not_enough_rides"

#: The note the weekly review quotes. Batch 367.2: a draft for Craig's sign-off
#: (docs/drafts/2026-11-03-batch-367-wording.md); it replaces 319's "You look ready for a
#: little more: a ramp test, or one small step up".
READY_NOTE: Final = (
    "Your last three hard sessions all landed on target, none felt harder than a 7 out of "
    "10, and you woke up fresh after each. The plan's next step looks right for you."
)


@dataclass(frozen=True, slots=True)
class FixedPowerRide:
    day: date
    power_watts: float
    heart_rate_bpm: float


@dataclass(frozen=True, slots=True)
class HardSession:
    day: date
    work_intervals: int
    on_target: int
    #: The morning after was not cautious (Green); ``None`` when no morning is stored.
    fresh_next_morning: bool | None = None
    #: Batch 367.2: his 0–10 effort from the ride's check-in; ``None`` when he gave none.
    effort: float | None = None


def fitness_drift(rides: Sequence[FixedPowerRide], *, as_of: date) -> dict[str, Any]:
    """Heart rate at a shared fixed power, the last four weeks against the four before."""

    recent_start = as_of - timedelta(days=WINDOW_DAYS - 1)
    earlier_start = recent_start - timedelta(days=WINDOW_DAYS)
    in_range = [ride for ride in rides if earlier_start <= ride.day <= as_of]
    if not in_range:
        return {"status": STATUS_NOT_ENOUGH, "recentRides": 0, "earlierRides": 0}
    centre = median(ride.power_watts for ride in in_range)
    same_power = [ride for ride in in_range if abs(ride.power_watts - centre) <= POWER_BAND_WATTS]
    recent = [ride for ride in same_power if ride.day >= recent_start]
    earlier = [ride for ride in same_power if ride.day < recent_start]
    result: dict[str, Any] = {
        "powerWatts": round(centre),
        "recentRides": len(recent),
        "earlierRides": len(earlier),
        "windowDays": WINDOW_DAYS,
    }
    if len(recent) < MIN_RIDES_EACH or len(earlier) < MIN_RIDES_EACH:
        return {**result, "status": STATUS_NOT_ENOUGH}
    before = mean(ride.heart_rate_bpm for ride in earlier)
    after = mean(ride.heart_rate_bpm for ride in recent)
    change = after - before
    line = drift_line(
        [ride.heart_rate_bpm for ride in earlier], [ride.heart_rate_bpm for ride in recent]
    )
    status = (
        STATUS_IMPROVING
        if change <= -line
        else STATUS_SLIPPING
        if change >= line
        else STATUS_STEADY
    )
    return {
        **result,
        "status": status,
        "heartRateBefore": round(before, 1),
        "heartRateAfter": round(after, 1),
        "changeBpm": round(change, 1),
        "lineBpm": round(line, 1),
    }


def drift_line(earlier: Sequence[float], recent: Sequence[float]) -> float:
    """How far heart rate must move to be called a change (Batch 367.3)."""

    def spread(values: Sequence[float]) -> float:
        return max(stdev(values), RIDE_HR_SD_FLOOR) if len(values) > 1 else RIDE_HR_SD_FLOOR

    error = float((spread(earlier) ** 2 / len(earlier) + spread(recent) ** 2 / len(recent)) ** 0.5)
    return max(DRIFT_BPM, DRIFT_SE * error)


def hard_work_on_target(sessions: Sequence[HardSession], *, as_of: date) -> dict[str, Any]:
    """His last hard sessions: each one's share on target, and the mornings after."""

    recent = sorted(
        (s for s in sessions if s.day <= as_of and s.work_intervals > 0),
        key=lambda s: s.day,
    )[-HARD_SESSIONS_IN_A_ROW:]
    shares = [round(s.on_target / s.work_intervals, 2) for s in recent]
    landing = bool(
        len(recent) == HARD_SESSIONS_IN_A_ROW
        and all(share >= ON_TARGET_SHARE for share in shares)
        and all(s.fresh_next_morning is True for s in recent)
        # Batch 367.2: what ERG cannot hold for him: how hard it felt.
        and all(s.effort is not None and s.effort <= MANAGEABLE_EFFORT for s in recent)
    )
    return {
        "sessions": [
            {
                "date": s.day.isoformat(),
                "onTargetShare": share,
                "freshNextMorning": s.fresh_next_morning,
                "effort": s.effort,
            }
            for s, share in zip(recent, shares, strict=True)
        ],
        "landing": landing,
    }


def progress_hold(
    *,
    as_of: date,
    light_week: bool,
    last_test: date | None = None,
    next_test: date | None = None,
) -> str | None:
    """Why the note holds this week, or ``None`` (Batch 367.1).

    A light week, the one reviewed or the one ahead, is no week to add load; a test within
    four weeks either side means one was just ridden or one is coming.
    """

    if light_week:
        return HOLD_LIGHT_WEEK
    if last_test is not None and timedelta(0) <= as_of - last_test <= timedelta(TEST_QUIET_DAYS):
        return HOLD_NEAR_TEST
    if next_test is not None and timedelta(0) < next_test - as_of <= timedelta(TEST_QUIET_DAYS):
        return HOLD_NEAR_TEST
    return None


def progress_signal(
    rides: Sequence[FixedPowerRide],
    sessions: Sequence[HardSession],
    *,
    as_of: date,
    hold: str | None = None,
) -> dict[str, Any]:
    """The weekly review's progress signal: the drift, the hard work, and the note if due.

    Batch 367.1: ``hold`` (from :func:`progress_hold`) keeps the note back whatever the
    hard work says; ``heldBecause`` records why, for the record, not for Mark.
    """

    drift = fitness_drift(rides, as_of=as_of)
    hard = hard_work_on_target(sessions, as_of=as_of)
    # Batch 367.2: never while his heart rate at fixed power is slipping.
    if hold is None and drift["status"] == STATUS_SLIPPING:
        hold = HOLD_SLIPPING
    ready = bool(hard["landing"]) and hold is None
    return {
        "fitnessDrift": drift,
        "hardWork": hard,
        "readyToProgress": ready,
        "note": READY_NOTE if ready else None,
        "heldBecause": hold if hard["landing"] else None,
        "changesNothing": True,
        "provisional": True,
    }


def rides_from_packets(rows: Sequence[tuple[date, Any]]) -> list[FixedPowerRide]:
    """Fixed-power rides from stored post-ride packets' intervals (Batch 322's check)."""

    from src.services.fixed_power import fixed_power_check

    rides: list[FixedPowerRide] = []
    for day, intervals in rows:
        check = fixed_power_check(intervals if isinstance(intervals, list) else None)
        if check is None or not isinstance(check.get("avgHeartRateBpm"), int | float):
            continue
        rides.append(
            FixedPowerRide(
                day=day,
                power_watts=float(check["powerWatts"]),
                heart_rate_bpm=float(check["avgHeartRateBpm"]),
            )
        )
    return rides


#: A work interval this hard counts as hard work (sweet spot and above).
HARD_TARGET_PCT: Final = 84


def _is_ramp_test(intervals: Any) -> bool:
    """A ramp test's steps are labelled "Ramp step N" (next_plan.ramp_test)."""

    return any(
        isinstance(item, Mapping) and str(item.get("label") or "").startswith("Ramp step")
        for item in (intervals if isinstance(intervals, list) else [])
    )


def last_ramp_test(rows: Sequence[tuple[date, Any, str | None]]) -> date | None:
    """The day of his latest ramp test among stored post-ride reads (Batch 367.1)."""

    days = [day for day, intervals, _type in rows if _is_ramp_test(intervals)]
    return max(days) if days else None


def hard_sessions_from_packets(
    rows: Sequence[tuple[date, Any, str | None]],
    morning_status: Mapping[date, str | None],
    efforts: Mapping[date, float] | None = None,
) -> list[HardSession]:
    """Graded hard work from stored post-ride packets' ``intervals``: work intervals whose
    target is sweet spot or harder, how many landed on target, and whether the next
    morning's call (``morning_status``, each day's colour) was not cautious.

    Batch 367.1: each row carries the session's planned workout type, and only a key
    session counts (:data:`KEY_SESSION_TYPES`): a Zone 2 ride's sprints, or a ride whose
    type the read did not record, are not hard work here."""

    sessions: list[HardSession] = []
    for day, intervals, workout_type in rows:
        if workout_type not in KEY_SESSION_TYPES:
            continue
        if _is_ramp_test(intervals):
            # Craig, 29 Oct: the ramp test runs to failure by design, so it scores 0 on
            # target and would reset the run. It is not a hard session here.
            continue
        hard = [
            item
            for item in (intervals if isinstance(intervals, list) else [])
            if isinstance(item, Mapping)
            and item.get("adherence") in ("on", "under", "over")
            and isinstance(item.get("targetPctFtpLow"), int | float)
            and float(item["targetPctFtpLow"]) >= HARD_TARGET_PCT
        ]
        if hard:
            sessions.append(
                HardSession(
                    day=day,
                    work_intervals=len(hard),
                    on_target=sum(1 for item in hard if item.get("adherence") == "on"),
                    fresh_next_morning=(
                        None
                        if morning_status.get(day + timedelta(days=1)) is None
                        else morning_status.get(day + timedelta(days=1)) == "Green"
                    ),
                    effort=(efforts or {}).get(day),
                )
            )
    return sessions


def effort_from_check_in(check_in: Any) -> float | None:
    """His 0–10 effort from a post-ride check-in: ``effort`` (Batch 322), else ``rpe``."""

    if not isinstance(check_in, Mapping):
        return None
    for key in ("effort", "rpe"):
        value = check_in.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None
