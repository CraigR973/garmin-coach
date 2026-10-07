"""Batch 324.2: change anything in the proposed plan, on the draft itself.

Every change in the closed list is held here against a real Plan No. 3 draft: what it does,
the words it logs, what it refuses and in which words, and that every ride it leaves behind
is still one the delivery rail can send to Zwift.
"""

from __future__ import annotations

import copy
import math
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import KnowledgeBase, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.routers.block_generator import _draft_envelope
from src.services.block_generator import (
    BLOCK_LOCK_SOURCE,
    GENERATED_BLOCK_SECTION,
    PLAN_ACCEPTED_WORDS,
    PLAN_MOVED_ON_WORDS,
    BlockGeneratorService,
)
from src.services.next_plan import WEEKDAYS, next_plan_draft
from src.services.plan_changes import (
    BY_COACH,
    BY_MARK,
    DAYS_WORDS,
    INTERVAL_BOUNDS_WORDS,
    LENGTH_FROM_INTERVALS_WORDS,
    LONG_RIDE_ADD_WORDS,
    MALFORMED_WORDS,
    NOT_A_RIDE_WORDS,
    NOT_FOUND_WORDS,
    REFUSED_DAYS,
    REFUSED_MALFORMED,
    REFUSED_NOT_EDITABLE,
    REFUSED_NOT_FOUND,
    REFUSED_OUT_OF_RANGE,
    REFUSED_OUTSIDE_PLAN,
    REFUSED_START,
    REFUSED_UNCHANGED,
    RESET_UNCHANGED_WORDS,
    RIDE_MINUTES_WORDS,
    TEST_FIXED_WORDS,
    TITLE_WORDS,
    UNCHANGED_WORDS,
    PlanChangeRefused,
    apply_change,
    find_session,
    normalise_draft,
    parse_change,
    session_changes_since_rebuild,
    session_edits,
    start_options,
    weeks_over_longest,
)
from src.services.workout_delivery import (
    IntervalsCreateResult,
    expand_structured_steps,
    validate_deliverable_bike_workout,
)

START = date(2026, 10, 19)
TODAY = date(2026, 10, 10)  # a Saturday: the next Monday is 12 Oct
AT = datetime(2026, 10, 10, 9, 0)
PLAN_DAYS = {
    "strengthA": 0,
    "vo2": 1,
    "zone2": 2,
    "sweetSpot": 3,
    "rest": 4,
    "sprints": 5,
    "strengthB": 5,
    "longRide": 6,
}


def _plan() -> dict[str, Any]:
    return next_plan_draft(
        start_date=START,
        ftp_watts=280,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 10, 7, 7, 0),
        plan_number=3,
        previous_name="Plan No. 2",
    )


def _apply(draft: dict[str, Any], change: dict[str, Any], *, by: str = BY_MARK) -> Any:
    return apply_change(draft, change, today=TODAY, by=by, at_utc=AT)


def _refused(draft: dict[str, Any], change: Any) -> PlanChangeRefused:
    with pytest.raises(PlanChangeRefused) as caught:
        _apply(draft, change)
    return caught.value


def _session(draft: dict[str, Any], session_id: str) -> dict[str, Any]:
    return find_session(draft, session_id)[1]


def _every_ride_deliverable(draft: dict[str, Any]) -> None:
    for week in draft["weeks"]:
        for workout in week["workouts"]:
            structured = workout["structuredWorkout"]
            if structured.get("format") != "bike":
                continue
            steps = validate_deliverable_bike_workout(
                structured, workout["intensityTarget"], context=workout["id"]
            )
            seconds = sum(int(step["durationSec"]) for step in steps)
            assert workout["plannedDurationMin"] == math.ceil(seconds / 60), workout["id"]
        assert week["totalMin"] == sum(w["plannedDurationMin"] for w in week["workouts"])


# -- the draft carries what a change needs --------------------------------------------------


def test_the_draft_names_every_session_and_starts_at_revision_0() -> None:
    draft = _plan()
    ids = [w["id"] for week in draft["weeks"] for w in week["workouts"]]
    assert ids == [f"s{n:03d}" for n in range(1, 92)]
    assert draft["revision"] == 0
    assert draft["changes"] == []
    assert draft["days"] == PLAN_DAYS
    assert draft["proposal"] == {"startDate": "2026-10-19", "days": PLAN_DAYS}


def test_a_draft_made_before_324_is_given_ids_days_and_a_proposal() -> None:
    old = _plan()
    for key in ("revision", "changes", "days", "proposal"):
        del old[key]
    for week in old["weeks"]:
        for workout in week["workouts"]:
            del workout["id"]

    working = normalise_draft(old)

    assert [w["id"] for w in working["weeks"][0]["workouts"]][:2] == ["s001", "s002"]
    assert working["days"] == PLAN_DAYS  # read back from the basis's weekday names
    assert working["proposal"] == {"startDate": "2026-10-19", "days": PLAN_DAYS}
    assert working["revision"] == 0 and working["changes"] == []
    assert "id" not in old["weeks"][0]["workouts"][0]  # a copy: the stored draft is untouched


def test_a_change_never_mutates_the_draft_it_was_given() -> None:
    draft = _plan()
    before = copy.deepcopy(draft)
    _apply(draft, {"kind": "remove", "session": "s009"})
    _apply(draft, {"kind": "days", "days": {**PLAN_DAYS, "vo2": 2, "zone2": 1}})
    assert draft == before


# -- his days --------------------------------------------------------------------------------


def test_his_days_rebuild_every_week_from_the_table() -> None:
    applied = _apply(_plan(), {"kind": "days", "days": {**PLAN_DAYS, "vo2": 2, "zone2": 1}})
    draft = applied.draft

    for week in draft["weeks"]:
        by_kind = {
            w["kind"]: date.fromisoformat(w["workoutDate"]).weekday() for w in week["workouts"]
        }
        assert by_kind.get("vo2", by_kind.get("test")) == 2
        assert by_kind["zone2"] == 1
    assert applied.summary == "Rebuilt with your days: VO₂ on Wednesday and Zone 2 on Tuesday."
    assert draft["days"] == {**PLAN_DAYS, "vo2": 2, "zone2": 1}
    assert draft["proposal"]["days"] == PLAN_DAYS
    assert draft["whyThisPlan"][0].startswith("Your week, as you set it: dumbbells on Monday, ")
    assert "Week 1 opens with an FTP ramp test on Wednesday 21 October." in draft["whyThisPlan"][1]
    assert draft["revision"] == 1
    assert draft["changes"][0]["summary"] == applied.summary
    _every_ride_deliverable(draft)


def test_a_rebuild_for_his_days_says_how_many_single_changes_went() -> None:
    draft = _apply(_plan(), {"kind": "title", "session": "s003", "title": "Z2 with Dave"}).draft
    draft = _apply(draft, {"kind": "remove", "session": "s012"}).draft
    assert session_changes_since_rebuild(draft) == 2

    applied = _apply(draft, {"kind": "days", "days": {**PLAN_DAYS, "longRide": 0, "strengthA": 6}})

    assert applied.summary == (
        "Rebuilt with your days: Dumbbells A on Sunday and the long ride on Monday. "
        "Your 2 earlier changes to single sessions went with it."
    )
    assert _session(applied.draft, "s003")["title"] == "Z2"
    assert session_changes_since_rebuild(applied.draft) == 0


def test_weekday_names_are_read_as_days() -> None:
    names = {key: WEEKDAYS[day] for key, day in {**PLAN_DAYS, "vo2": 2, "zone2": 1}.items()}
    assert parse_change({"kind": "days", "days": names})["days"] == {
        **PLAN_DAYS,
        "vo2": 2,
        "zone2": 1,
    }


@pytest.mark.parametrize(
    "days",
    [
        {**PLAN_DAYS, "vo2": 2},  # two rides on Wednesday
        {**PLAN_DAYS, "rest": 6},  # the rest day under the long ride
        {**PLAN_DAYS, "rest": 0},  # the rest day under dumbbells
        {**PLAN_DAYS, "strengthB": 0},  # both dumbbell sessions on Monday
    ],
)
def test_days_that_do_not_make_a_week_are_refused_in_words(days: dict[str, int]) -> None:
    refused = _refused(_plan(), {"kind": "days", "days": days})
    assert (refused.reason, refused.words) == (REFUSED_DAYS, DAYS_WORDS)


def test_the_same_days_are_no_change() -> None:
    refused = _refused(_plan(), {"kind": "days", "days": PLAN_DAYS})
    assert (refused.reason, refused.words) == (REFUSED_UNCHANGED, UNCHANGED_WORDS)


# -- the start date --------------------------------------------------------------------------


def test_the_start_moves_everything_and_keeps_his_changes() -> None:
    draft = _apply(_plan(), {"kind": "minutes", "session": "s007", "minutes": 150}).draft

    applied = _apply(draft, {"kind": "start", "startDate": "2026-10-26"})
    moved = applied.draft

    assert moved["startDate"] == "2026-10-26" and moved["endDate"] == "2027-01-24"
    assert moved["weeks"][0]["startDate"] == "2026-10-26"
    assert _session(moved, "s007")["workoutDate"] == "2026-11-01"
    assert _session(moved, "s007")["plannedDurationMin"] == 150
    assert applied.summary == "Now starts Monday 26 October (it was Monday 19 October)."
    assert "Week 1 opens with an FTP ramp test on Tuesday 27 October." in moved["whyThisPlan"][1]
    assert moved["proposal"]["startDate"] == "2026-10-19"
    _every_ride_deliverable(moved)


def test_the_start_is_any_monday_from_the_next_to_eight_weeks_on() -> None:
    assert start_options(TODAY)[0] == date(2026, 10, 12)
    assert start_options(TODAY)[-1] == date(2026, 12, 7)
    assert start_options(date(2026, 10, 12))[0] == date(2026, 10, 12)  # today, on a Monday

    for refused_start in ("2026-10-27", "2026-12-14", "2026-10-05"):
        refused = _refused(_plan(), {"kind": "start", "startDate": refused_start})
        assert refused.reason == REFUSED_START
        assert refused.words == (
            "The plan can start on any Monday from Monday 12 October to Monday 7 December."
        )
    assert _refused(_plan(), {"kind": "start", "startDate": "2026-10-19"}).reason == (
        REFUSED_UNCHANGED
    )


# -- a session's intervals, minutes and name -------------------------------------------------


def test_intervals_change_by_the_five_numbers_and_the_ride_stays_deliverable() -> None:
    applied = _apply(
        _plan(),
        {
            "kind": "intervals",
            "session": "s009",
            "repeat": 12,
            "workSec": 30,
            "workPct": 130,
            "restSec": 30,
            "restPct": 55,
        },
    )
    ride = _session(applied.draft, "s009")

    assert applied.summary == (
        "Tue 27 Oct, VO₂ (30/30s, 2 × 10 @ 130%): each of its 2 sets, 10 × 30s/30s @ 130%/55% "
        "becomes 12 × 30s/30s @ 130%/55%."
    )
    assert ride["title"] == "VO₂ (2 blocks of 12 × 30s/30s @ 130%/55%)"
    assert ride["plannedDurationMin"] == 55  # 17 + 2 × 12 min + 4 + 10
    assert ride["workoutType"] == "bike_vo2"
    assert applied.draft["weeks"][1]["totalMin"] == 445 + 4
    _every_ride_deliverable(applied.draft)


def test_a_half_minute_ride_rounds_its_minutes_up_as_the_session_editor_does() -> None:
    applied = _apply(
        _plan(),
        {
            "kind": "intervals",
            "session": "s044",
            "repeat": 9,
            "workSec": 30,
            "workPct": 125,
            "restSec": 15,
            "restPct": 55,
        },
    )
    ride = _session(applied.draft, "s044")
    seconds = sum(
        int(step["durationSec"])
        for step in expand_structured_steps(ride["structuredWorkout"], ride["intensityTarget"])
    )
    assert seconds == 43 * 60 + 30
    assert ride["plannedDurationMin"] == 44


@pytest.mark.parametrize(
    ("session", "words"),
    [("s002", TEST_FIXED_WORDS), ("s001", NOT_A_RIDE_WORDS)],
)
def test_the_test_and_dumbbells_have_no_intervals_to_change(session: str, words: str) -> None:
    change = {
        "kind": "intervals",
        "session": session,
        "repeat": 4,
        "workSec": 60,
        "workPct": 110,
        "restSec": 60,
        "restPct": 55,
    }
    refused = _refused(_plan(), change)
    assert (refused.reason, refused.words) == (REFUSED_NOT_EDITABLE, words)


def test_intervals_outside_the_editor_bounds_are_refused_in_words() -> None:
    change = {
        "kind": "intervals",
        "session": "s009",
        "repeat": 0,
        "workSec": 30,
        "workPct": 130,
        "restSec": 30,
        "restPct": 55,
    }
    refused = _refused(_plan(), change)
    assert (refused.reason, refused.words) == (REFUSED_OUT_OF_RANGE, INTERVAL_BOUNDS_WORDS)
    unchanged = {**change, "repeat": 10}
    assert _refused(_plan(), unchanged).reason == REFUSED_UNCHANGED


def test_a_steady_ride_changes_its_steady_block() -> None:
    applied = _apply(_plan(), {"kind": "minutes", "session": "s007", "minutes": 150})
    ride = _session(applied.draft, "s007")

    assert applied.summary == "Sun 25 Oct, Long Z2: 120 min becomes 150 min."
    assert ride["structuredWorkout"]["steps"][1]["minutes"] == 130
    assert ride["structuredWorkout"]["summary"] == (
        "10 min ramp → 130 min @65–72% (midpoint 68%) → 10 min ramp"
    )
    assert applied.draft["weeks"][0]["totalMin"] == 414 + 30
    _every_ride_deliverable(applied.draft)


def test_a_title_carrying_minutes_follows_them() -> None:
    applied = _apply(_plan(), {"kind": "minutes", "session": "s091", "minutes": 50})
    assert _session(applied.draft, "s091")["title"] == "Optional Ride (50 min @ 60–65%) OR Rest"


def test_dumbbell_minutes_change() -> None:
    applied = _apply(_plan(), {"kind": "minutes", "session": "s013", "minutes": 30})
    session = _session(applied.draft, "s013")
    assert session["plannedDurationMin"] == 30
    assert session["structuredWorkout"]["steps"][0]["minutes"] == 30
    assert applied.summary == "Sat 31 Oct, Dumbbells B (upper body): 25 min becomes 30 min."


def test_minutes_are_refused_where_the_length_is_not_his_to_set() -> None:
    vo2 = _refused(_plan(), {"kind": "minutes", "session": "s009", "minutes": 60})
    assert (vo2.reason, vo2.words) == (REFUSED_NOT_EDITABLE, LENGTH_FROM_INTERVALS_WORDS)
    test = _refused(_plan(), {"kind": "minutes", "session": "s002", "minutes": 30})
    assert (test.reason, test.words) == (REFUSED_NOT_EDITABLE, TEST_FIXED_WORDS)


@pytest.mark.parametrize(
    ("session", "minutes", "words"),
    [
        ("s007", 25, "This ride needs at least 30 minutes for its warm-up and cool-down."),
        ("s007", 19, RIDE_MINUTES_WORDS),
        ("s007", 241, RIDE_MINUTES_WORDS),
        ("s013", 61, RIDE_MINUTES_WORDS),
        ("s013", 9, RIDE_MINUTES_WORDS),
    ],
)
def test_minutes_out_of_range_are_refused_in_words(session: str, minutes: int, words: str) -> None:
    refused = _refused(_plan(), {"kind": "minutes", "session": session, "minutes": minutes})
    assert (refused.reason, refused.words) == (REFUSED_OUT_OF_RANGE, words)


def test_a_session_can_be_renamed() -> None:
    applied = _apply(_plan(), {"kind": "title", "session": "s003", "title": "  Z2  with Dave "})
    assert _session(applied.draft, "s003")["title"] == "Z2 with Dave"
    assert applied.summary == "Wed 21 Oct: “Z2” is now called “Z2 with Dave”."
    too_long = _refused(_plan(), {"kind": "title", "session": "s003", "title": "x" * 81})
    assert (too_long.reason, too_long.words) == (REFUSED_OUT_OF_RANGE, TITLE_WORDS)
    assert _refused(_plan(), {"kind": "title", "session": "s003", "title": "Z2"}).reason == (
        REFUSED_UNCHANGED
    )


# -- move, remove, add -----------------------------------------------------------------------


def test_a_session_moves_to_a_day_with_a_ride_rides_before_strength() -> None:
    applied = _apply(_plan(), {"kind": "move", "session": "s009", "toDate": "2026-10-26"})
    monday = [w for w in applied.draft["weeks"][1]["workouts"] if w["workoutDate"] == "2026-10-26"]

    assert [(w["id"], w["slot"], w["dayOffset"]) for w in monday] == [
        ("s009", 0, 0),
        ("s008", 1, 0),
    ]
    assert applied.summary == "VO₂ (30/30s, 2 × 10 @ 130%) moves from Tue 27 Oct to Mon 26 Oct."
    assert applied.draft["weeks"][1]["totalMin"] == 445


def test_a_session_moves_to_another_week() -> None:
    applied = _apply(_plan(), {"kind": "move", "session": "s014", "toDate": "2026-11-06"})
    weeks = applied.draft["weeks"]

    assert "s014" not in [w["id"] for w in weeks[1]["workouts"]]
    moved = _session(applied.draft, "s014")
    assert (moved["workoutDate"], moved["dayOffset"], moved["slot"]) == ("2026-11-06", 4, 0)
    assert weeks[1]["totalMin"] == 445 - 120
    assert weeks[2]["totalMin"] == 324 + 120  # a recovery week, now with a long ride
    assert weeks_over_longest(applied.draft) == []


def test_a_move_outside_the_plan_or_to_the_same_day_is_refused() -> None:
    outside = _refused(_plan(), {"kind": "move", "session": "s014", "toDate": "2027-01-18"})
    assert outside.reason == REFUSED_OUTSIDE_PLAN
    assert outside.words == "That day isn't in the plan: it runs from Mon 19 Oct to Sun 17 Jan."
    same = _refused(_plan(), {"kind": "move", "session": "s014", "toDate": "2026-11-01"})
    assert same.reason == REFUSED_UNCHANGED


def test_a_session_is_removed() -> None:
    applied = _apply(_plan(), {"kind": "remove", "session": "s012"})
    saturday = [
        w for w in applied.draft["weeks"][1]["workouts"] if w["workoutDate"] == "2026-10-31"
    ]
    assert [(w["id"], w["slot"]) for w in saturday] == [("s013", 0)]
    assert applied.summary == "Sat 31 Oct, Z2 + Neuromuscular: removed."
    missing = _refused(applied.draft, {"kind": "remove", "session": "s012"})
    assert (missing.reason, missing.words) == (REFUSED_NOT_FOUND, NOT_FOUND_WORDS)


@pytest.mark.parametrize(
    ("session_type", "minutes", "title", "expected_minutes"),
    [
        ("easy", None, "Easy spin", 45),
        ("zone2", 50, "Z2", 50),
        ("long", None, "Long Z2", 120),
        ("strength_a", None, "Dumbbells A (legs and back)", 20),
        ("strength_b", 15, "Dumbbells B (upper body)", 15),
    ],
)
def test_a_session_is_added_to_any_day(
    session_type: str, minutes: int | None, title: str, expected_minutes: int
) -> None:
    applied = _apply(
        _plan(),
        {"kind": "add", "date": "2026-10-23", "sessionType": session_type, "minutes": minutes},
    )
    added = _session(applied.draft, "s092")

    assert (added["title"], added["plannedDurationMin"], added["workoutDate"]) == (
        title,
        expected_minutes,
        "2026-10-23",
    )
    assert applied.summary == f"Fri 23 Oct: {title} added, {expected_minutes} min."
    assert applied.draft["weeks"][0]["totalMin"] == 414 + expected_minutes
    _every_ride_deliverable(applied.draft)


def test_an_added_strength_session_takes_that_weeks_dose() -> None:
    applied = _apply(_plan(), {"kind": "add", "date": "2026-12-02", "sessionType": "strength_a"})
    added = _session(applied.draft, "s092")
    assert added["intensityTarget"] == "Dumbbells 3 × 8"
    assert added["plannedDurationMin"] == 25


def test_an_added_session_out_of_range_is_refused() -> None:
    short_long = {"kind": "add", "date": "2026-10-23", "sessionType": "long", "minutes": 50}
    refused = _refused(_plan(), short_long)
    assert (refused.reason, refused.words) == (REFUSED_OUT_OF_RANGE, LONG_RIDE_ADD_WORDS)
    long_easy = {"kind": "add", "date": "2026-10-23", "sessionType": "easy", "minutes": 241}
    assert _refused(_plan(), long_easy).words == RIDE_MINUTES_WORDS


# -- back to the plan as proposed ------------------------------------------------------------


def test_back_to_the_plan_as_proposed_undoes_everything() -> None:
    proposed = _plan()
    draft = proposed
    for change in (
        {"kind": "start", "startDate": "2026-10-26"},
        {"kind": "days", "days": {**PLAN_DAYS, "vo2": 2, "zone2": 1}},
        {"kind": "remove", "session": "s010"},
        {"kind": "add", "date": "2026-10-30", "sessionType": "easy"},
    ):
        draft = _apply(draft, change).draft

    applied = _apply(draft, {"kind": "reset"})

    assert applied.summary == "Back to the plan as proposed."
    for key in ("startDate", "endDate", "days", "weeks", "whyThisPlan"):
        assert applied.draft[key] == proposed[key], key
    assert applied.draft["revision"] == 5
    assert [entry["revision"] for entry in applied.draft["changes"]] == [1, 2, 3, 4, 5]
    refused = _refused(applied.draft, {"kind": "reset"})
    assert (refused.reason, refused.words) == (REFUSED_UNCHANGED, RESET_UNCHANGED_WORDS)


# -- the log, the reader, and what the builder offers ----------------------------------------


def test_the_log_records_who_made_each_change() -> None:
    draft = _apply(_plan(), {"kind": "remove", "session": "s012"}, by=BY_COACH).draft
    entry = draft["changes"][0]
    assert entry == {
        "revision": 1,
        "atUtc": "2026-10-10T09:00:00",
        "by": "coach",
        "summary": "Sat 31 Oct, Z2 + Neuromuscular: removed.",
        "change": {"kind": "remove", "session": "s012"},
    }


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"kind": "rename_everything"},
        {"kind": "minutes", "session": "s007"},
        {"kind": "minutes", "session": "s007", "minutes": True},
        {"kind": "minutes", "session": "s007", "minutes": "150"},
        {"kind": "move", "session": "s007", "toDate": "next week"},
        {"kind": "days", "days": {"vo2": 2}},
        {"kind": "add", "date": "2026-10-23", "sessionType": "vo2"},
        {"kind": "intervals", "session": "s009", "repeat": 12},
    ],
)
def test_a_change_that_cannot_be_read_is_refused_in_words(change: Any) -> None:
    refused = _refused(_plan(), change)
    assert (refused.reason, refused.words) == (REFUSED_MALFORMED, MALFORMED_WORDS)


def test_the_builder_is_told_what_each_session_can_change() -> None:
    draft = _plan()
    assert session_edits(_session(draft, "s002")) == {
        "minutes": None,
        "intervals": None,
        "fixed": TEST_FIXED_WORDS,
    }
    assert session_edits(_session(draft, "s007"))["minutes"] == {"min": 30, "max": 240}
    assert session_edits(_session(draft, "s045"))["minutes"] == {"min": 20, "max": 240}
    assert session_edits(_session(draft, "s013"))["minutes"] == {"min": 10, "max": 60}
    vo2 = session_edits(_session(draft, "s009"))
    assert vo2["minutes"] is None
    assert vo2["intervals"] == {
        "repeat": 10,
        "workSec": 30,
        "workPct": 130,
        "restSec": 30,
        "restPct": 55,
        "label": "10 × 30s/30s @ 130%/55%",
        "matchingSets": 2,
    }


def test_a_week_longer_than_his_longest_is_flagged_not_refused() -> None:
    applied = _apply(_plan(), {"kind": "add", "date": "2026-10-30", "sessionType": "long"})
    assert applied.draft["weeks"][1]["totalMin"] == 565
    assert weeks_over_longest(applied.draft) == [2]


def test_every_change_in_a_long_session_of_changes_leaves_every_ride_deliverable() -> None:
    draft = _plan()
    for change in (
        {
            "kind": "intervals",
            "session": "s004",
            "repeat": 3,
            "workSec": 900,
            "workPct": 92,
            "restSec": 240,
            "restPct": 55,
        },
        {
            "kind": "intervals",
            "session": "s005",
            "repeat": 8,
            "workSec": 10,
            "workPct": 180,
            "restSec": 170,
            "restPct": 55,
        },
        {
            "kind": "intervals",
            "session": "s088",
            "repeat": 2,
            "workSec": 480,
            "workPct": 90,
            "restSec": 120,
            "restPct": 60,
        },
        {"kind": "minutes", "session": "s003", "minutes": 90},
        {"kind": "minutes", "session": "s089", "minutes": 30},
        {"kind": "move", "session": "s002", "toDate": "2026-10-21"},
        {"kind": "add", "date": "2027-01-15", "sessionType": "zone2", "minutes": 35},
        {"kind": "start", "startDate": "2026-11-02"},
    ):
        draft = _apply(draft, change).draft
        _every_ride_deliverable(draft)
    assert draft["revision"] == 8
    assert date.fromisoformat(draft["startDate"]) == START + timedelta(weeks=2)


# -- on Postgres: the service versions the draft, and accepting writes what he changed --------

#: Well in the past, so the default plan a fresh profile is seeded with never overlaps it.
DB_START = date(2026, 6, 1)


async def _db_profile(session: AsyncSession) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Plan Changes",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.flush()
    session.add(
        KnowledgeBase(
            user_id=player.id,
            section="profile",
            version=1,
            is_active=True,
            source="test",
            content={"athleteName": "Mark", "ftpWatts": 280},
            updated_by_profile_id=player.id,
        )
    )
    await session.commit()
    return player


async def _draft_rows(session: AsyncSession, player: Profile) -> list[KnowledgeBase]:
    return list(
        (
            await session.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.user_id == player.id,
                    KnowledgeBase.section == GENERATED_BLOCK_SECTION,
                )
                .order_by(KnowledgeBase.version)
            )
        )
        .scalars()
        .all()
    )


class _FakeZwift:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def create_workout_event(self, payload: dict[str, Any]) -> IntervalsCreateResult:
        self.payloads.append(payload)
        event_id = f"evt_{len(self.payloads)}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(
        self, event_id: str, payload: dict[str, Any]
    ) -> IntervalsCreateResult:
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_on_postgres_a_change_versions_the_draft(db_conn: AsyncConnection) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _db_profile(session)
        service = BlockGeneratorService(session)
        await service.generate(player, start_date=DB_START)

        changed = await service.change(
            player, {"kind": "remove", "session": "s012"}, expected_revision=0
        )

        assert changed["revision"] == 1
        rows = await _draft_rows(session, player)
        assert [(row.version, row.is_active) for row in rows] == [(1, False), (2, True)]
        assert rows[0].content["revision"] == 0
        assert "s012" not in [
            w["id"] for week in rows[1].content["weeks"] for w in week["workouts"]
        ]
        assert rows[1].content["changes"][0]["by"] == BY_MARK


@pytest.mark.asyncio
async def test_on_postgres_a_change_against_an_older_revision_is_not_applied(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _db_profile(session)
        service = BlockGeneratorService(session)
        await service.generate(player, start_date=DB_START)
        await service.change(player, {"kind": "remove", "session": "s012"})

        with pytest.raises(HTTPException) as stale:
            await service.change(player, {"kind": "remove", "session": "s013"}, expected_revision=0)
        assert (stale.value.status_code, stale.value.detail) == (409, PLAN_MOVED_ON_WORDS)
        with pytest.raises(HTTPException) as refused:
            await service.change(player, {"kind": "minutes", "session": "s009", "minutes": 60})
        assert (refused.value.status_code, refused.value.detail) == (
            422,
            LENGTH_FROM_INTERVALS_WORDS,
        )
        assert len(await _draft_rows(session, player)) == 2


@pytest.mark.asyncio
async def test_on_postgres_accepting_a_changed_plan_writes_what_he_changed(
    db_conn: AsyncConnection,
) -> None:
    zwift = _FakeZwift()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = await _db_profile(session)
        service = BlockGeneratorService(session, intervals_client=zwift)
        await service.generate(player, start_date=DB_START)
        for change in (
            {"kind": "remove", "session": "s005"},  # week 1's Saturday ride
            {"kind": "add", "date": "2026-06-05", "sessionType": "easy"},  # his Friday
            {"kind": "move", "session": "s014", "toDate": "2026-06-13"},  # Sunday's to Saturday
            {
                "kind": "intervals",
                "session": "s009",
                "repeat": 12,
                "workSec": 30,
                "workPct": 130,
                "restSec": 30,
                "restPct": 55,
            },
        ):
            await service.change(player, change)

        result = await service.lock(player)

        assert result.workouts_written == 91
        rows = {
            (row.workout_date, row.title): row
            for row in (
                await session.execute(
                    select(PlannedWorkout).where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.source == BLOCK_LOCK_SOURCE,
                    )
                )
            )
            .scalars()
            .all()
        }
        titles_on = {
            day: sorted(title for (row_day, title) in rows if row_day == day)
            for day in (date(2026, 6, 5), date(2026, 6, 6), date(2026, 6, 13), date(2026, 6, 14))
        }
        assert titles_on == {
            date(2026, 6, 5): ["Easy spin"],
            date(2026, 6, 6): ["Dumbbells B (upper body)"],
            date(2026, 6, 13): ["Dumbbells B (upper body)", "Long Z2", "Z2 + Neuromuscular"],
            date(2026, 6, 14): [],
        }
        vo2 = rows[(date(2026, 6, 9), "VO₂ (2 blocks of 12 × 30s/30s @ 130%/55%)")]
        assert vo2.planned_duration_min == 55
        # Every ride went to Zwift as changed: 65 rides, less one removed, plus one added.
        assert len(zwift.payloads) == 65

        with pytest.raises(HTTPException) as accepted:
            await service.change(player, {"kind": "remove", "session": "s001"})
        assert (accepted.value.status_code, accepted.value.detail) == (409, PLAN_ACCEPTED_WORDS)


def test_the_builder_envelope_carries_what_each_session_can_change() -> None:
    data = _draft_envelope(_plan(), TODAY).data

    assert data.canGenerate is False
    assert len(data.sessionEdits) == 91
    assert data.sessionEdits["s002"]["fixed"] == TEST_FIXED_WORDS
    assert data.startOptions[0] == "2026-10-12" and len(data.startOptions) == 9
    assert data.sessionChangesSinceRebuild == 0
    assert data.weeksOverLongest == []

    locked = {**_plan(), "status": "locked"}
    hints = _draft_envelope(locked, TODAY).data
    assert hints.canGenerate is True
    assert (hints.sessionEdits, hints.startOptions) == ({}, [])
