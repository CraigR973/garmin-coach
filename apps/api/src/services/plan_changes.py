"""Change anything in the proposed plan, before he accepts it (Batch 324).

Batch 323 proposed Plan No. 3 for Mark to accept or decline, and its builder's only edit was
``refine``: any title, type, length, target or steps, unvalidated. Craig, 7 Oct 2026: "we
should give him maximum flexibility to change and also have a conversation with the coach
about the upcoming proposed plan". This module is the closed list of changes, the same list
for his own taps and for a change the coach offers him:

* ``days``: his week (which weekday each kind of session is on), rebuilt from the table;
* ``start``: the Monday it starts, moving everything with it;
* ``intervals``: a ride's interval set, by the interval editor's five numbers;
* ``minutes``: a steady ride's or a dumbbell session's length;
* ``title``: what a session is called;
* ``move``, ``remove`` and ``add`` (Zone 2, easy spin, long ride, either dumbbell session);
* ``reset``: back to the plan as proposed.

Every change is pure and deterministic: :func:`apply_change` takes the draft and returns the
changed draft, its revision raised and the change logged in plain words, or raises
:class:`PlanChangeRefused` with the words to show him. Nothing here writes a row or reaches
Zwift; the plan reaches Zwift only when he accepts it (``BlockGeneratorService.lock``).

Rides stay deliverable: a changed ride must still pass the delivery rail's own check, and
its minutes are its steps' total rounded up, as the session interval editor's are
(``executable_coaching.approve_interval_edit``). A week longer than his longest is allowed:
the builder warns and never blocks. Mark-facing words signed off under Craig's delegation
of 6 Oct 2026 (``docs/drafts/2026-10-07-batch-324-wording.md``).
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from fastapi import HTTPException

from src.services.interval_workout_editor import (
    MAX_POWER_PCT,
    MAX_REPEATS,
    MAX_REST_DURATION_SEC,
    MAX_WORK_DURATION_SEC,
    MIN_POWER_PCT,
    MIN_REPEATS,
    MIN_REST_DURATION_SEC,
    MIN_WORK_DURATION_SEC,
    PROPOSED_BLOCK_FIELDS,
    apply_interval_block,
    block_from_proposal,
    block_to_source,
    editable_snapshot_for,
    format_interval_block,
    interval_workout_title,
)
from src.services.next_plan import (
    DAY_KEYS,
    PLAN_NO_2_RHYTHM,
    WEEKDAYS,
    WEEKS,
    Session,
    StrengthDose,
    WeeklyRhythm,
    easy_zone2,
    long_zone2,
    next_plan_draft,
    session_id,
    strength,
    zone2,
)
from src.services.structured_workout_builder import classify_bike_workout_steps
from src.services.workout_delivery import validate_deliverable_bike_workout

KIND_DAYS: Final = "days"
KIND_START: Final = "start"
KIND_INTERVALS: Final = "intervals"
KIND_MINUTES: Final = "minutes"
KIND_TITLE: Final = "title"
KIND_MOVE: Final = "move"
KIND_REMOVE: Final = "remove"
KIND_ADD: Final = "add"
KIND_RESET: Final = "reset"

#: The closed list, in the order the coach's prompt states it.
CHANGE_KINDS: Final = (
    KIND_DAYS,
    KIND_START,
    KIND_INTERVALS,
    KIND_MINUTES,
    KIND_TITLE,
    KIND_MOVE,
    KIND_REMOVE,
    KIND_ADD,
    KIND_RESET,
)

#: Changes to one session: a rebuild for his days replaces them.
SESSION_CHANGE_KINDS: Final = frozenset(
    {KIND_INTERVALS, KIND_MINUTES, KIND_TITLE, KIND_MOVE, KIND_REMOVE, KIND_ADD, "refine"}
)
#: Changes that rebuild the plan from the table.
REBUILD_KINDS: Final = frozenset({KIND_DAYS, KIND_RESET})

ADD_ZONE2: Final = "zone2"
ADD_EASY: Final = "easy"
ADD_LONG: Final = "long"
ADD_STRENGTH_A: Final = "strength_a"
ADD_STRENGTH_B: Final = "strength_b"
ADD_TYPES: Final = (ADD_ZONE2, ADD_EASY, ADD_LONG, ADD_STRENGTH_A, ADD_STRENGTH_B)

#: Who made a change, as the change log says it.
BY_MARK: Final = "you"
BY_COACH: Final = "coach"

#: Minutes: any steady ride, any dumbbell session; an added long ride is at least an hour.
RIDE_MIN_MINUTES: Final = 20
RIDE_MAX_MINUTES: Final = 240
LONG_RIDE_ADD_MIN_MINUTES: Final = 60
STRENGTH_MIN_MINUTES: Final = 10
STRENGTH_MAX_MINUTES: Final = 60
#: A steady ride keeps at least this much of its steady block.
STEADY_MAIN_MIN_MINUTES: Final = 10
#: The start can move to any Monday from the next one to eight weeks after it.
START_WEEKS_AHEAD: Final = 8
TITLE_MAX_LENGTH: Final = 80

_ADD_DEFAULT_MINUTES: Final = {ADD_ZONE2: 60, ADD_EASY: 45, ADD_LONG: 120}

# -- why a change is refused, in his words ---------------------------------------------------

REFUSED_MALFORMED: Final = "malformed"
REFUSED_NOT_FOUND: Final = "not_found"
REFUSED_OUTSIDE_PLAN: Final = "outside_plan"
REFUSED_START: Final = "start_out_of_range"
REFUSED_DAYS: Final = "days_invalid"
REFUSED_NOT_EDITABLE: Final = "not_editable"
REFUSED_OUT_OF_RANGE: Final = "out_of_range"
REFUSED_NOT_DELIVERABLE: Final = "not_deliverable"
REFUSED_UNCHANGED: Final = "unchanged"

MALFORMED_WORDS: Final = "That change couldn't be read. Try it again."
NOT_FOUND_WORDS: Final = "That session isn't in the plan any more."
DAYS_WORDS: Final = (
    "Each ride needs a day of its own, your rest day has nothing on it, and the two "
    "dumbbell sessions go on different days."
)
TEST_FIXED_WORDS: Final = "The ramp test stays as it is. You can move it or remove it."
NOT_A_RIDE_WORDS: Final = "Only a ride has intervals to change."
NO_INTERVALS_WORDS: Final = "This ride has no interval set to change."
LENGTH_FROM_INTERVALS_WORDS: Final = (
    "This ride's length comes from its intervals: change those instead."
)
INTERVAL_BOUNDS_WORDS: Final = (
    f"Reps can be {MIN_REPEATS} to {MAX_REPEATS}, efforts {MIN_WORK_DURATION_SEC} to "
    f"{MAX_WORK_DURATION_SEC} seconds, recoveries {MIN_REST_DURATION_SEC} to "
    f"{MAX_REST_DURATION_SEC} seconds, and both percentages {MIN_POWER_PCT} to "
    f"{MAX_POWER_PCT}% of FTP."
)
RIDE_MINUTES_WORDS: Final = (
    f"A ride can be {RIDE_MIN_MINUTES} to {RIDE_MAX_MINUTES} minutes, and dumbbells "
    f"{STRENGTH_MIN_MINUTES} to {STRENGTH_MAX_MINUTES}."
)
LONG_RIDE_ADD_WORDS: Final = (
    f"A long ride can be {LONG_RIDE_ADD_MIN_MINUTES} to {RIDE_MAX_MINUTES} minutes."
)
TITLE_WORDS: Final = f"A name can be up to {TITLE_MAX_LENGTH} characters."
NOT_DELIVERABLE_WORDS: Final = (
    "That would make a ride Zwift can't run: it needs its warm-up and cool-down."
)
UNCHANGED_WORDS: Final = "That's how the plan already is."
RESET_UNCHANGED_WORDS: Final = "This is already the plan as proposed."


class PlanChangeRefused(Exception):
    """A change the draft cannot take, with the words to show him."""

    def __init__(self, reason: str, words: str) -> None:
        super().__init__(words)
        self.reason = reason
        self.words = words


@dataclass(frozen=True, slots=True)
class AppliedChange:
    """The changed draft, and the change as the log records it."""

    draft: dict[str, Any]
    summary: str
    change: dict[str, Any]


# -- dates in his words ----------------------------------------------------------------------

_SHORT_DAYS: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def short_day(day: date) -> str:
    """``Tue 20 Oct``, as the builder shows each session's day."""

    return f"{_SHORT_DAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1][:3]}"


def long_day(day: date) -> str:
    """``Monday 19 October``."""

    return f"{WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


# -- the draft as this module reads it -------------------------------------------------------

_SESSION_ID = re.compile(r"^s(\d{3,})$")


def normalise_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy of the draft with what Batch 324 adds, for a draft made before it.

    Sessions get ids in plan order (keeping any they have), the draft a revision of 0 and an
    empty change log, his days from the plan's basis, and a proposal of the plan as it is.
    """

    working = copy.deepcopy(dict(draft))
    weeks = working.get("weeks")
    if not isinstance(weeks, list):
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
    taken = [
        int(match.group(1))
        for _week, workout in _sessions(working)
        if isinstance(workout.get("id"), str)
        and (match := _SESSION_ID.match(workout["id"])) is not None
    ]
    seen: set[str] = set()
    number = max(taken, default=0)
    for _week, workout in _sessions(working):
        current = workout.get("id")
        if not isinstance(current, str) or _SESSION_ID.match(current) is None or current in seen:
            number += 1
            workout["id"] = session_id(number)
        seen.add(str(workout["id"]))
    working.setdefault("revision", 0)
    working.setdefault("changes", [])
    if not isinstance(working.get("days"), dict):
        working["days"] = _days_from_basis(working)
    if not isinstance(working.get("proposal"), dict):
        working["proposal"] = {"startDate": working["startDate"], "days": dict(working["days"])}
    return working


def _days_from_basis(draft: Mapping[str, Any]) -> dict[str, int]:
    basis = draft.get("basis")
    names = basis.get("rhythm") if isinstance(basis, dict) else None
    if isinstance(names, dict):
        try:
            return WeeklyRhythm.from_days(
                {key: WEEKDAYS.index(str(names[key])) for key in DAY_KEYS}
            ).to_days()
        except (KeyError, ValueError):
            pass
    return PLAN_NO_2_RHYTHM.to_days()


def _sessions(draft: Mapping[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for week in draft.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for workout in week.get("workouts") or []:
            if isinstance(workout, dict):
                yield week, workout


def find_session(draft: Mapping[str, Any], session: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The week and the session with this id, or a refusal saying it has gone."""

    for week, workout in _sessions(draft):
        if workout.get("id") == session:
            return week, workout
    raise PlanChangeRefused(REFUSED_NOT_FOUND, NOT_FOUND_WORDS)


def _plan_span(draft: Mapping[str, Any]) -> tuple[date, date]:
    return date.fromisoformat(str(draft["startDate"])), date.fromisoformat(str(draft["endDate"]))


def _week_containing(draft: Mapping[str, Any], day: date) -> dict[str, Any]:
    for week in draft["weeks"]:
        if isinstance(week, dict) and date.fromisoformat(
            week["startDate"]
        ) <= day <= date.fromisoformat(week["endDate"]):
            return week
    start, end = _plan_span(draft)
    raise PlanChangeRefused(
        REFUSED_OUTSIDE_PLAN,
        f"That day isn't in the plan: it runs from {short_day(start)} to {short_day(end)}.",
    )


def _is_strength(workout: Mapping[str, Any]) -> bool:
    structured = workout.get("structuredWorkout")
    if isinstance(structured, dict) and structured.get("format") == "strength":
        return True
    return str(workout.get("workoutType") or "").startswith("strength")


def _renumber(week: dict[str, Any]) -> None:
    """Each day's sessions in order, rides before strength, then the week in day order."""

    start = date.fromisoformat(week["startDate"])
    by_date: dict[str, list[dict[str, Any]]] = {}
    for workout in week["workouts"]:
        by_date.setdefault(str(workout["workoutDate"]), []).append(workout)
    for day, sessions in by_date.items():
        sessions.sort(key=lambda item: (_is_strength(item), int(item.get("slot") or 0)))
        for slot, workout in enumerate(sessions):
            workout["slot"] = slot
            workout["dayOffset"] = (date.fromisoformat(day) - start).days
    week["workouts"].sort(key=lambda item: (int(item["dayOffset"]), int(item["slot"])))


def _recount(draft: dict[str, Any]) -> None:
    for week in draft["weeks"]:
        week["totalMin"] = sum(int(w.get("plannedDurationMin") or 0) for w in week["workouts"])


def session_changes_since_rebuild(draft: Mapping[str, Any]) -> int:
    """How many changes to single sessions a rebuild for his days would replace."""

    count = 0
    for entry in draft.get("changes") or []:
        kind = entry.get("change", {}).get("kind") if isinstance(entry, dict) else None
        if kind in REBUILD_KINDS:
            count = 0
        elif kind in SESSION_CHANGE_KINDS:
            count += 1
    return count


def start_options(today: date) -> list[date]:
    """The Mondays the plan can start on: the next one (today, on a Monday) and eight more."""

    first = today + timedelta(days=(7 - today.weekday()) % 7)
    return [first + timedelta(weeks=index) for index in range(START_WEEKS_AHEAD + 1)]


# -- what can be changed on a session --------------------------------------------------------


def _steady_shape(structured: Any) -> tuple[int, int] | None:
    """A steady ride's ramps, ``(in, out)`` minutes: a ramp, one steady block, a ramp."""

    if not isinstance(structured, dict) or structured.get("format") != "bike":
        return None
    steps = structured.get("steps")
    if not isinstance(steps, list) or len(steps) != 3:
        return None
    first, main, last = steps
    if not (isinstance(first, dict) and isinstance(main, dict) and isinstance(last, dict)):
        return None
    if "ramp" not in first or "ramp" not in last:
        return None
    if any(key in main for key in ("ramp", "pattern", "block")):
        return None
    ramps = (first.get("minutes"), last.get("minutes"), main.get("minutes"))
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in ramps):
        return None
    return int(first["minutes"]), int(last["minutes"])


def session_edits(workout: Mapping[str, Any]) -> dict[str, Any]:
    """What the builder offers on a session: its minutes, its five numbers, or neither."""

    structured = workout.get("structuredWorkout")
    if workout.get("kind") == "test":
        return {"minutes": None, "intervals": None, "fixed": TEST_FIXED_WORDS}
    if _is_strength(workout):
        return {
            "minutes": {"min": STRENGTH_MIN_MINUTES, "max": STRENGTH_MAX_MINUTES},
            "intervals": None,
            "fixed": None,
        }
    steady = _steady_shape(structured)
    if steady is not None:
        return {
            "minutes": {
                "min": max(RIDE_MIN_MINUTES, sum(steady) + STEADY_MAIN_MIN_MINUTES),
                "max": RIDE_MAX_MINUTES,
            },
            "intervals": None,
            "fixed": None,
        }
    snapshot = editable_snapshot_for(
        structured if isinstance(structured, dict) else None,
        workout.get("intensityTarget"),
    )
    if snapshot is None:
        return {"minutes": None, "intervals": None, "fixed": None}
    source = block_to_source(snapshot.current)
    return {
        "minutes": None,
        "intervals": {
            "repeat": source["repeat"],
            "workSec": source["work"]["durationSec"],
            "workPct": source["work"]["powerPct"],
            "restSec": source["rest"]["durationSec"],
            "restPct": source["rest"]["powerPct"],
            "label": format_interval_block(snapshot.current),
            "matchingSets": len(snapshot.editable_step_indices),
        },
        "fixed": None,
    }


# -- parsing: the closed list ----------------------------------------------------------------


def _int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
    return value


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
    return value.strip()


def _iso_date(payload: Mapping[str, Any], key: str) -> date:
    try:
        return date.fromisoformat(_text(payload, key))
    except ValueError as exc:
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS) from exc


def _weekday(value: Any) -> int:
    if isinstance(value, str) and value.strip().title() in WEEKDAYS:
        return WEEKDAYS.index(value.strip().title())
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
    return value


def parse_change(change: Any) -> dict[str, Any]:
    """The change in its one stored shape, or a refusal that it could not be read.

    Weekdays may be given as numbers (Monday 0) or names; everything else has one form.
    """

    if not isinstance(change, Mapping):
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
    kind = change.get("kind")
    if kind == KIND_DAYS:
        days = change.get("days")
        if not isinstance(days, Mapping) or set(days) != set(DAY_KEYS):
            raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
        return {"kind": kind, "days": {key: _weekday(days[key]) for key in DAY_KEYS}}
    if kind == KIND_START:
        return {"kind": kind, "startDate": _iso_date(change, "startDate").isoformat()}
    if kind == KIND_INTERVALS:
        parsed: dict[str, Any] = {"kind": kind, "session": _text(change, "session")}
        for field in PROPOSED_BLOCK_FIELDS:
            parsed[field] = _int(change, field)
        return parsed
    if kind == KIND_MINUTES:
        return {
            "kind": kind,
            "session": _text(change, "session"),
            "minutes": _int(change, "minutes"),
        }
    if kind == KIND_TITLE:
        title = " ".join(_text(change, "title").split())
        return {"kind": kind, "session": _text(change, "session"), "title": title}
    if kind == KIND_MOVE:
        return {
            "kind": kind,
            "session": _text(change, "session"),
            "toDate": _iso_date(change, "toDate").isoformat(),
        }
    if kind == KIND_REMOVE:
        return {"kind": kind, "session": _text(change, "session")}
    if kind == KIND_ADD:
        session_type = change.get("sessionType")
        if session_type not in ADD_TYPES:
            raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)
        minutes = change.get("minutes")
        if minutes is not None:
            minutes = _int(change, "minutes")
        return {
            "kind": kind,
            "date": _iso_date(change, "date").isoformat(),
            "sessionType": session_type,
            "minutes": minutes,
        }
    if kind == KIND_RESET:
        return {"kind": kind}
    raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS)


# -- the changes -----------------------------------------------------------------------------


def _rebuild(draft: Mapping[str, Any], *, start: date, days: Mapping[str, int]) -> dict[str, Any]:
    """The plan built from the table for this start and these days, as generate built it."""

    raw_basis = draft.get("basis")
    basis: dict[str, Any] = raw_basis if isinstance(raw_basis, dict) else {}
    proposal = draft["proposal"]
    rebuilt = next_plan_draft(
        start_date=start,
        ftp_watts=int(draft["ftpWatts"]),
        athlete_name=str(draft["athleteName"]),
        generated_at_utc=datetime.fromisoformat(str(draft["generatedAtUtc"])),
        rhythm=WeeklyRhythm.from_days(days),
        longest_week_min=int(basis.get("longestWeekMin") or 0) or _longest(draft),
        plan_number=draft.get("planNumber"),
        previous_name=basis.get("previousPlan"),
        proposed_rhythm=WeeklyRhythm.from_days(proposal["days"]),
    )
    # The plan keeps what it was proposed as, so "back to the plan as proposed" still can.
    rebuilt["proposal"] = copy.deepcopy(proposal)
    return rebuilt


def _longest(draft: Mapping[str, Any]) -> int:
    return max((int(week.get("totalMin") or 0) for week in draft["weeks"]), default=0)


_DAY_NAMES: Final = {
    "strengthA": "Dumbbells A",
    "vo2": "VO₂",
    "zone2": "Zone 2",
    "sweetSpot": "sweet spot",
    "rest": "your rest day",
    "sprints": "the sprint ride",
    "strengthB": "Dumbbells B",
    "longRide": "the long ride",
}


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _change_days(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    new_days: dict[str, int] = change["days"]
    try:
        rhythm = WeeklyRhythm.from_days(new_days)
    except ValueError as exc:
        raise PlanChangeRefused(REFUSED_MALFORMED, MALFORMED_WORDS) from exc
    if not rhythm.is_valid():
        raise PlanChangeRefused(REFUSED_DAYS, DAYS_WORDS)
    current: dict[str, int] = draft["days"]
    if rhythm.to_days() == current:
        raise PlanChangeRefused(REFUSED_UNCHANGED, UNCHANGED_WORDS)
    dropped = session_changes_since_rebuild(draft)
    rebuilt = _rebuild(draft, start=date.fromisoformat(draft["startDate"]), days=new_days)
    moved = [
        f"{_DAY_NAMES[key]} on {WEEKDAYS[new_days[key]]}"
        for key in DAY_KEYS
        if new_days[key] != current.get(key)
    ]
    summary = f"Rebuilt with your days: {_join(moved)}."
    if dropped:
        plural = "s" if dropped > 1 else ""
        summary += f" Your {dropped} earlier change{plural} to single sessions went with it."
    return rebuilt, summary


def _change_start(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    new_start = date.fromisoformat(change["startDate"])
    old_start = date.fromisoformat(draft["startDate"])
    options = start_options(today)
    if new_start == old_start:
        raise PlanChangeRefused(REFUSED_UNCHANGED, UNCHANGED_WORDS)
    if new_start not in options:
        raise PlanChangeRefused(
            REFUSED_START,
            f"The plan can start on any Monday from {long_day(options[0])} to "
            f"{long_day(options[-1])}.",
        )
    shift = new_start - old_start
    for week in draft["weeks"]:
        week["startDate"] = (date.fromisoformat(week["startDate"]) + shift).isoformat()
        week["endDate"] = (date.fromisoformat(week["endDate"]) + shift).isoformat()
        for workout in week["workouts"]:
            workout["workoutDate"] = (
                date.fromisoformat(workout["workoutDate"]) + shift
            ).isoformat()
    draft["startDate"] = new_start.isoformat()
    draft["endDate"] = (date.fromisoformat(draft["endDate"]) + shift).isoformat()
    # The note's dates (the test day, Christmas and New Year) follow the start.
    draft["whyThisPlan"] = _rebuild(draft, start=new_start, days=draft["days"])["whyThisPlan"]
    return draft, f"Now starts {long_day(new_start)} (it was {long_day(old_start)})."


def _change_intervals(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    _week, workout = find_session(draft, change["session"])
    if workout.get("kind") == "test":
        raise PlanChangeRefused(REFUSED_NOT_EDITABLE, TEST_FIXED_WORDS)
    structured = workout.get("structuredWorkout")
    if not isinstance(structured, dict) or structured.get("format") != "bike":
        raise PlanChangeRefused(REFUSED_NOT_EDITABLE, NOT_A_RIDE_WORDS)
    target = workout.get("intensityTarget")
    snapshot = editable_snapshot_for(structured, target)
    if snapshot is None:
        raise PlanChangeRefused(REFUSED_NOT_EDITABLE, NO_INTERVALS_WORDS)
    try:
        block = block_from_proposal(
            {field: change[field] for field in PROPOSED_BLOCK_FIELDS}, current=snapshot.current
        )
    except HTTPException as exc:
        raise PlanChangeRefused(REFUSED_OUT_OF_RANGE, INTERVAL_BOUNDS_WORDS) from exc
    if block == snapshot.current:
        raise PlanChangeRefused(REFUSED_UNCHANGED, UNCHANGED_WORDS)
    updated = apply_interval_block(structured, target, block)
    try:
        steps = validate_deliverable_bike_workout(updated, target)
    except ValueError as exc:
        raise PlanChangeRefused(REFUSED_NOT_DELIVERABLE, NOT_DELIVERABLE_WORDS) from exc
    classification = classify_bike_workout_steps(steps)
    old_title = str(workout["title"])
    workout["structuredWorkout"] = updated
    workout["title"] = interval_workout_title(old_title, updated, target)
    workout["workoutType"] = classification.workout_type
    workout["intensityTarget"] = classification.intensity_target
    # As the session interval editor does: the steps' total, rounded up to the minute.
    workout["plannedDurationMin"] = math.ceil(sum(int(s["durationSec"]) for s in steps) / 60)
    day = short_day(date.fromisoformat(workout["workoutDate"]))
    sets = len(snapshot.editable_step_indices)
    each = f" each of its {sets} sets," if sets > 1 else ""
    return draft, (
        f"{day}, {old_title}:{each} {format_interval_block(snapshot.current)} becomes "
        f"{format_interval_block(block)}."
    )


_MAIN_MINUTES = re.compile(r"→ (\d+) min @")
_TITLE_MINUTES = re.compile(r"\((\d+) min @")


def _change_minutes(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    _week, workout = find_session(draft, change["session"])
    minutes: int = change["minutes"]
    old = int(workout.get("plannedDurationMin") or 0)
    title = str(workout["title"])
    day = short_day(date.fromisoformat(workout["workoutDate"]))
    edits = session_edits(workout)
    bounds = edits["minutes"]
    if bounds is None:
        words = edits["fixed"] or (
            LENGTH_FROM_INTERVALS_WORDS if edits["intervals"] is not None else NO_INTERVALS_WORDS
        )
        raise PlanChangeRefused(REFUSED_NOT_EDITABLE, words)
    if not bounds["min"] <= minutes <= bounds["max"]:
        words = RIDE_MINUTES_WORDS
        if not _is_strength(workout) and minutes < bounds["min"] and minutes >= RIDE_MIN_MINUTES:
            words = (
                f"This ride needs at least {bounds['min']} minutes for its warm-up and cool-down."
            )
        raise PlanChangeRefused(REFUSED_OUT_OF_RANGE, words)
    if minutes == old:
        raise PlanChangeRefused(REFUSED_UNCHANGED, UNCHANGED_WORDS)
    structured = copy.deepcopy(workout["structuredWorkout"])
    steps = structured["steps"]
    if _is_strength(workout):
        for step in steps:
            if isinstance(step, dict) and "minutes" in step:
                step["minutes"] = minutes
    else:
        ramp_in, ramp_out = _steady_shape(structured) or (0, 0)
        main = minutes - ramp_in - ramp_out
        old_main = int(steps[1]["minutes"])
        steps[1]["minutes"] = main
        summary = structured.get("summary")
        if isinstance(summary, str):
            structured["summary"] = _MAIN_MINUTES.sub(
                lambda match: f"→ {main} min @" if int(match.group(1)) == old_main else match[0],
                summary,
                count=1,
            )
        workout["title"] = _TITLE_MINUTES.sub(f"({minutes} min @", title, count=1)
    workout["structuredWorkout"] = structured
    workout["plannedDurationMin"] = minutes
    return draft, f"{day}, {title}: {old} min becomes {minutes} min."


def _change_title(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    _week, workout = find_session(draft, change["session"])
    title: str = change["title"]
    if len(title) > TITLE_MAX_LENGTH:
        raise PlanChangeRefused(REFUSED_OUT_OF_RANGE, TITLE_WORDS)
    old = str(workout["title"])
    if title == old:
        raise PlanChangeRefused(REFUSED_UNCHANGED, UNCHANGED_WORDS)
    workout["title"] = title
    day = short_day(date.fromisoformat(workout["workoutDate"]))
    return draft, f"{day}: “{old}” is now called “{title}”."


def _change_move(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    week, workout = find_session(draft, change["session"])
    to_day = date.fromisoformat(change["toDate"])
    from_day = date.fromisoformat(workout["workoutDate"])
    target = _week_containing(draft, to_day)
    if to_day == from_day:
        raise PlanChangeRefused(REFUSED_UNCHANGED, UNCHANGED_WORDS)
    week["workouts"].remove(workout)
    workout["workoutDate"] = to_day.isoformat()
    # After the day's own sessions; ``_renumber`` puts rides before strength.
    workout["slot"] = len(target["workouts"]) + 1
    target["workouts"].append(workout)
    _renumber(week)
    if target is not week:
        _renumber(target)
    return draft, f"{workout['title']} moves from {short_day(from_day)} to {short_day(to_day)}."


def _change_remove(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    week, workout = find_session(draft, change["session"])
    week["workouts"].remove(workout)
    _renumber(week)
    day = short_day(date.fromisoformat(workout["workoutDate"]))
    return draft, f"{day}, {workout['title']}: removed."


def _added_session(session_type: str, minutes: int, week_number: int) -> Session:
    if session_type == ADD_ZONE2:
        return zone2(minutes)
    if session_type == ADD_EASY:
        return easy_zone2(minutes, title="Easy spin", kind="easy")
    if session_type == ADD_LONG:
        return long_zone2(minutes)
    dose = WEEKS[min(max(week_number, 1), len(WEEKS)) - 1].strength
    return strength(
        StrengthDose(dose.sets_reps, dose.effort, minutes),
        session="A" if session_type == ADD_STRENGTH_A else "B",
    )


def _strength_dose_minutes(week_number: int) -> int:
    return WEEKS[min(max(week_number, 1), len(WEEKS)) - 1].strength.minutes


def _change_add(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del today
    day = date.fromisoformat(change["date"])
    week = _week_containing(draft, day)
    session_type: str = change["sessionType"]
    week_number = int(week["weekNumber"])
    is_strength = session_type in (ADD_STRENGTH_A, ADD_STRENGTH_B)
    minutes: int = change["minutes"] or (
        _strength_dose_minutes(week_number) if is_strength else _ADD_DEFAULT_MINUTES[session_type]
    )
    if is_strength:
        if not STRENGTH_MIN_MINUTES <= minutes <= STRENGTH_MAX_MINUTES:
            raise PlanChangeRefused(REFUSED_OUT_OF_RANGE, RIDE_MINUTES_WORDS)
    elif session_type == ADD_LONG:
        if not LONG_RIDE_ADD_MIN_MINUTES <= minutes <= RIDE_MAX_MINUTES:
            raise PlanChangeRefused(REFUSED_OUT_OF_RANGE, LONG_RIDE_ADD_WORDS)
    elif not RIDE_MIN_MINUTES <= minutes <= RIDE_MAX_MINUTES:
        raise PlanChangeRefused(REFUSED_OUT_OF_RANGE, RIDE_MINUTES_WORDS)
    session = _added_session(session_type, minutes, week_number)
    numbers = [
        int(match.group(1))
        for _week, workout in _sessions(draft)
        if (match := _SESSION_ID.match(str(workout.get("id")))) is not None
    ]
    added = {
        "id": session_id(max(numbers, default=0) + 1),
        **session.to_draft(
            day_offset=(day - date.fromisoformat(week["startDate"])).days,
            slot=len(week["workouts"]) + 1,
            workout_date=day,
        ),
    }
    week["workouts"].append(added)
    _renumber(week)
    return draft, f"{short_day(day)}: {session.title} added, {minutes} min."


def _plan_shape(draft: Mapping[str, Any]) -> tuple[Any, ...]:
    return (draft["startDate"], draft["days"], draft["weeks"])


def _change_reset(
    draft: dict[str, Any], change: dict[str, Any], today: date
) -> tuple[dict[str, Any], str]:
    del change, today
    proposal = draft["proposal"]
    rebuilt = _rebuild(
        draft, start=date.fromisoformat(proposal["startDate"]), days=proposal["days"]
    )
    if _plan_shape(rebuilt) == _plan_shape(draft):
        raise PlanChangeRefused(REFUSED_UNCHANGED, RESET_UNCHANGED_WORDS)
    return rebuilt, "Back to the plan as proposed."


_HANDLERS: Final[
    dict[str, Callable[[dict[str, Any], dict[str, Any], date], tuple[dict[str, Any], str]]]
] = {
    KIND_DAYS: _change_days,
    KIND_START: _change_start,
    KIND_INTERVALS: _change_intervals,
    KIND_MINUTES: _change_minutes,
    KIND_TITLE: _change_title,
    KIND_MOVE: _change_move,
    KIND_REMOVE: _change_remove,
    KIND_ADD: _change_add,
    KIND_RESET: _change_reset,
}


def log_change(
    draft: dict[str, Any],
    *,
    summary: str,
    change: dict[str, Any],
    by: str,
    at_utc: datetime,
) -> None:
    """Raise the draft's revision and record the change, in place."""

    revision = int(draft.get("revision") or 0) + 1
    draft["revision"] = revision
    draft["changes"] = [
        *(draft.get("changes") or []),
        {
            "revision": revision,
            "atUtc": at_utc.isoformat(),
            "by": by,
            "summary": summary,
            "change": change,
        },
    ]


def apply_change(
    draft: Mapping[str, Any],
    change: Any,
    *,
    today: date,
    by: str,
    at_utc: datetime,
) -> AppliedChange:
    """The draft with ``change`` applied, its revision raised and the change logged.

    The draft passed in is never mutated. Raises :class:`PlanChangeRefused` with the words
    to show him when the change cannot be made.
    """

    working = normalise_draft(draft)
    parsed = parse_change(change)
    revision = int(working["revision"])
    changes = list(working["changes"])
    updated, summary = _HANDLERS[parsed["kind"]](working, parsed, today)
    _recount(updated)
    updated["revision"] = revision
    updated["changes"] = changes
    log_change(updated, summary=summary, change=parsed, by=by, at_utc=at_utc)
    return AppliedChange(draft=updated, summary=summary, change=parsed)


def weeks_over_longest(draft: Mapping[str, Any]) -> list[int]:
    """The weeks longer than his longest week, which the builder warns about."""

    basis = draft.get("basis")
    longest = int(basis.get("longestWeekMin") or 0) if isinstance(basis, dict) else 0
    if longest <= 0:
        return []
    return [
        int(week["weekNumber"])
        for week in draft.get("weeks") or []
        if int(week.get("totalMin") or 0) > longest
    ]
