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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, median
from typing import Any, Final

WINDOW_DAYS: Final = 28
MIN_RIDES_EACH: Final = 3
#: Rides count as the same power within this many watts of the windows' shared median.
POWER_BAND_WATTS: Final = 6.0
#: A fall or rise in heart rate at that power smaller than this is noise.
DRIFT_BPM: Final = 3.0
#: Each of his last hard sessions must land this share of its work intervals on target.
ON_TARGET_SHARE: Final = 0.9
#: How many hard sessions in a row.
HARD_SESSIONS_IN_A_ROW: Final = 3

STATUS_IMPROVING: Final = "improving"
STATUS_STEADY: Final = "steady"
STATUS_SLIPPING: Final = "slipping"
STATUS_NOT_ENOUGH: Final = "not_enough_rides"

#: The note the weekly review quotes (draft for Craig's sign-off).
READY_NOTE: Final = (
    "Your last three hard sessions all landed on target, and you woke up fresh after each. "
    "You look ready for a little more: a ramp test, or one small step up in your next hard "
    "session. Nothing changes unless you choose it."
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
    status = (
        STATUS_IMPROVING
        if change <= -DRIFT_BPM
        else STATUS_SLIPPING
        if change >= DRIFT_BPM
        else STATUS_STEADY
    )
    return {
        **result,
        "status": status,
        "heartRateBefore": round(before, 1),
        "heartRateAfter": round(after, 1),
        "changeBpm": round(change, 1),
    }


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
    )
    return {
        "sessions": [
            {
                "date": s.day.isoformat(),
                "onTargetShare": share,
                "freshNextMorning": s.fresh_next_morning,
            }
            for s, share in zip(recent, shares, strict=True)
        ],
        "landing": landing,
    }


def progress_signal(
    rides: Sequence[FixedPowerRide], sessions: Sequence[HardSession], *, as_of: date
) -> dict[str, Any]:
    """The weekly review's progress signal: the drift, the hard work, and the note if due."""

    drift = fitness_drift(rides, as_of=as_of)
    hard = hard_work_on_target(sessions, as_of=as_of)
    ready = bool(hard["landing"])
    return {
        "fitnessDrift": drift,
        "hardWork": hard,
        "readyToProgress": ready,
        "note": READY_NOTE if ready else None,
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


def hard_sessions_from_packets(
    rows: Sequence[tuple[date, Any]], morning_status: Mapping[date, str | None]
) -> list[HardSession]:
    """Graded hard work from stored post-ride packets' ``intervals``: work intervals whose
    target is sweet spot or harder, how many landed on target, and whether the next
    morning's call (``morning_status``, each day's colour) was not cautious."""

    sessions: list[HardSession] = []
    for day, intervals in rows:
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
                )
            )
    return sessions
