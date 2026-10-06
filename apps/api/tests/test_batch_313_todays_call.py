"""Batch 313 — today's call in a coach's words, and rest days that read as rest.

The morning reached Mark as a colour ("Rest or substitute" on any Red, a "Red verdict"
chip, a stop sign above "Today's a rest day"). The headline now says what to do today,
from the engine's own session actions; a chip says how recovered he is; rest days lead
with "Rest day"; red is kept for the two health warnings. Every line below is the one
Craig signed off on Mark's behalf (``docs/drafts/2026-10-04-morning-call-wording.md``,
4 Oct 2026; the two marked 5 Oct are his answers that day), copied here as literals so a
change to the words fails a test.

* **Each state**, from a stored packet: its headline, line, reading and look.
* **The rest-day rule**: a day with nothing planned inside a plan week is a rest day; the
  fixture's three empty mornings (18, 21, 25 Sep) become rest days and no colour moves.
* **The words live with the rule**: the call is stored with the morning and a morning
  stored before this batch is read with the same rule.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from src.services.todays_call import (
    LOOK_ADJUST,
    LOOK_GO,
    LOOK_NEUTRAL,
    LOOK_RECOVER,
    LOOK_WARNING,
    stored_call,
    todays_call,
)

VO2 = {"plannedWorkoutId": "vo2", "workoutType": "bike_vo2", "isHard": True, "isKey": True}
Z2 = {"plannedWorkoutId": "z2", "workoutType": "bike_z2", "isHard": False, "isKey": False}
LONG = {"plannedWorkoutId": "long", "workoutType": "bike_endurance", "isHard": False, "isKey": True}
STRENGTH = {
    "plannedWorkoutId": "gym",
    "workoutType": "strength_maintenance",
    "isHard": False,
    "isKey": False,
}


def _packet(
    status: str | None,
    *actions: tuple[dict[str, Any], str],
    held: bool = False,
    floor: str | None = None,
    acute: dict[str, Any] | None = None,
    rest: dict[str, Any] | None = None,
    light_week: str | None = None,
    tired_by: str | None = None,
    domains: list[dict[str, Any]] | None = None,
    planned: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A graded morning packet as ``assemble_context_packet`` stores it."""
    return {
        "verdict": {
            "engine": "graded",
            "status": status,
            "held": held,
            "acutePhysiology": acute or {},
            "graded": {
                "floor": floor,
                "domains": domains or [],
                "actions": [{**session, "action": action} for session, action in actions],
                "references": {"lightWeek": light_week, "tiredBy": tired_by},
            },
        },
        "restDay": rest or {"isRestDay": False, "reason": None, "insidePlanWeek": True},
        "plannedWorkouts": (
            planned
            if planned is not None
            else [
                {"id": session["plannedWorkoutId"], "status": "planned", **session}
                for session, _ in actions
            ]
        ),
    }


def _seen(packet: dict[str, Any], **kwargs: Any) -> tuple[int, str, str, str, str]:
    call = todays_call(packet, **kwargs)
    return call.state, call.headline, call.line, call.reading_words, call.look


# -- the states, as signed off -----------------------------------------------------------

STATES: dict[str, tuple[dict[str, Any], tuple[int, str, str, str, str]]] = {
    "1 recovered, a hard session": (
        _packet("Green", (VO2, "as_planned"), (Z2, "as_planned")),
        (
            1,
            "Green light",
            "You're recovered. Today's session is on as written. Make it count.",
            "Recovered",
            LOOK_GO,
        ),
    ),
    "1 recovered, only easy riding": (
        _packet("Green", (Z2, "as_planned")),
        (
            1,
            "Green light",
            "You're recovered. Today's session is on as written. Keep the easy riding easy.",
            "Recovered",
            LOOK_GO,
        ),
    ),
    "2 one reading off, no hard session": (
        _packet("Green", (Z2, "as_planned"), held=True),
        (
            2,
            "Green light — hold the targets",
            "One reading's a touch off. Today's session is on as written; leave a little in "
            "the tank.",
            "Recovered",
            LOOK_GO,
        ),
    ),
    "2 one reading off, a hard session": (
        _packet("Green", (VO2, "move_or_hold"), (Z2, "as_planned"), held=True),
        (
            2,
            "Green light — hold the targets",
            "One reading's a touch off. If there's a better day this week, move the hard "
            "session there; if not, ride it and hold the targets.",
            "Recovered",
            LOOK_GO,
        ),
    ),
    "3 consolidation week, held": (
        _packet("Amber", (VO2, "hold_targets"), light_week="consolidation"),
        (
            3,
            "As planned — hold the targets",
            "It's your consolidation week, so the session's already light. Ride it as "
            "written and hold the targets.",
            "Some fatigue",
            LOOK_GO,
        ),
    ),
    "3 taper week, held Green": (
        _packet("Green", (VO2, "hold_targets"), held=True, light_week="taper"),
        (
            3,
            "As planned — hold the targets",
            "It's your taper week, so the session's already light. Ride it as written and "
            "hold the targets.",
            "Recovered",
            LOOK_GO,
        ),
    ),
    "4 some fatigue, only easy riding": (
        _packet("Amber", (Z2, "as_planned")),
        (
            4,
            "As planned",
            "There's some fatigue about, and today's plan already suits it. Keep it comfortable.",
            "Some fatigue",
            LOOK_GO,
        ),
    ),
    "4 some fatigue, strength": (
        _packet("Amber", (STRENGTH, "as_planned")),
        (
            4,
            "As planned",
            "There's some fatigue about, and today's plan already suits it. Keep it comfortable.",
            "Some fatigue",
            LOOK_GO,
        ),
    ),
    "4 still recovering, no ride (Craig, 5 Oct)": (
        _packet("Red", (STRENGTH, "as_planned")),
        (
            4,
            "As planned",
            "Your body's still recovering, and today's plan already suits it. Keep it comfortable.",
            "Still recovering",
            LOOK_GO,
        ),
    ),
    "5 some fatigue, hard session eased": (
        _packet("Amber", (VO2, "ease_hard"), (Z2, "as_planned")),
        (
            5,
            "Take the edge off",
            "There's some fatigue about. Ride the full session with the hard efforts eased "
            "a zone; easy riding stays as planned.",
            "Some fatigue",
            LOOK_ADJUST,
        ),
    ),
    "6 tired by sleep": (
        _packet("Amber", (VO2, "pick_zone2_or_tempo"), tired_by="sleep"),
        (
            6,
            "Easy or tempo — your call",
            "Sleep let you down last night, so the hard efforts are off today. Move the "
            "session to a fresher day, or pick easy Zone 2 or tempo below.",
            "Some fatigue",
            LOOK_ADJUST,
        ),
    ),
    "6 tired by how he feels": (
        _packet("Amber", (VO2, "pick_zone2_or_tempo"), tired_by="feel"),
        (
            6,
            "Easy or tempo — your call",
            "You're feeling flat this morning, so the hard efforts are off today. Move the "
            "session to a fresher day, or pick easy Zone 2 or tempo below.",
            "Some fatigue",
            LOOK_ADJUST,
        ),
    ),
    "7 tired, a long ride": (
        _packet("Amber", (LONG, "offer_shorter"), tired_by="sleep"),
        (
            7,
            "Long ride — shorter if you like",
            "Sleep let you down last night. Ride it as planned, or take the shorter version "
            "in one tap.",
            "Some fatigue",
            LOOK_ADJUST,
        ),
    ),
    "7 tired by how he feels (Craig, 5 Oct)": (
        _packet("Amber", (LONG, "offer_shorter"), tired_by="feel"),
        (
            7,
            "Long ride — shorter if you like",
            "You're feeling flat this morning. Ride it as planned, or take the shorter "
            "version in one tap.",
            "Some fatigue",
            LOOK_ADJUST,
        ),
    ),
    "8 still recovering, a hard session": (
        _packet("Red", (VO2, "recovery"), (Z2, "shortened_zone2")),
        (
            8,
            "Recovery day",
            "Your body's still recovering. The hard session will do more for you on a "
            "fresher day — today, rest or an easy spin.",
            "Still recovering",
            LOOK_RECOVER,
        ),
    ),
    "9 still recovering, a Zone 2 ride": (
        _packet("Red", (Z2, "shortened_zone2")),
        (
            9,
            "Short and easy",
            "Your body's still recovering. Keep today's Zone 2 ride, just shorter — easy "
            "miles, nothing more.",
            "Still recovering",
            LOOK_RECOVER,
        ),
    ),
    "10 an easy day back after a fever": (
        _packet("Amber", (VO2, "recovery"), floor="hard_work_to_easy"),
        (
            10,
            "Easy day",
            "Today's hard session becomes an easy spin — the note below explains why.",
            "Some fatigue",
            LOOK_RECOVER,
        ),
    ),
    "11 no training": (
        _packet(
            "Red",
            (VO2, "no_training"),
            floor="no_training",
            acute={"requiresTrainingRest": True, "requiresBikeRest": True},
        ),
        (
            11,
            "No training today",
            "The symptoms you've reported rule out training today.",
            "Still recovering",
            LOOK_WARNING,
        ),
    ),
    "11 off the bike": (
        _packet(
            "Amber", (VO2, "off_the_bike"), floor="bike_rest", acute={"requiresBikeRest": True}
        ),
        (
            11,
            "Take today off the bike",
            "An acute recovery signal rules out riding today.",
            "Some fatigue",
            LOOK_WARNING,
        ),
    ),
    "12 rest day, recovered": (
        _packet(
            "Green",
            rest={"isRestDay": True, "reason": "planned_rest", "insidePlanWeek": True},
            planned=[],
        ),
        (
            12,
            "Rest day",
            "You're recovered — enjoy the day off. Rest is where this week's training turns "
            "into fitness.",
            "Recovered",
            LOOK_RECOVER,
        ),
    ),
    "13 rest day, some fatigue": (
        _packet(
            "Amber",
            rest={"isRestDay": True, "reason": "planned_rest", "insidePlanWeek": True},
            planned=[],
        ),
        (
            13,
            "Rest day",
            "Good timing — there's some fatigue about, and today lets it clear.",
            "Some fatigue",
            LOOK_RECOVER,
        ),
    ),
    "14 rest day, still recovering": (
        _packet(
            "Red",
            rest={"isRestDay": True, "reason": "all_skipped", "insidePlanWeek": True},
            planned=[{"id": "vo2", "status": "skipped", "workoutType": "bike_vo2"}],
        ),
        (
            14,
            "Rest day",
            "Well timed — your body's still recovering, and rest is exactly what it needs.",
            "Still recovering",
            LOOK_RECOVER,
        ),
    ),
    "15 holiday": (
        _packet(
            "Red",
            rest={"isRestDay": True, "reason": "holiday", "insidePlanWeek": True},
            planned=[{"id": "vo2", "status": "skipped", "workoutType": "bike_vo2"}],
        ),
        (
            15,
            "Holiday",
            "Enjoy the break. The plan picks up when you're home.",
            "Still recovering",
            LOOK_RECOVER,
        ),
    ),
    "16 no plan loaded": (
        _packet(
            "Amber",
            rest={"isRestDay": False, "reason": None, "insidePlanWeek": False},
            planned=[],
        ),
        (
            16,
            "No session planned",
            "There's nothing in your plan for today yet.",
            "Some fatigue",
            LOOK_NEUTRAL,
        ),
    ),
    "17 not ready": (
        _packet(None),
        (
            17,
            "Not ready yet",
            "Today's call lands once your overnight data has synced.",
            "Waiting for data",
            LOOK_NEUTRAL,
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(STATES))
def test_each_state_reads_as_signed_off(name: str) -> None:
    packet, expected = STATES[name]
    assert _seen(packet) == expected


def test_every_one_of_the_17_states_is_reachable() -> None:
    assert {expected[0] for _, expected in STATES.values()} == set(range(1, 18))


def test_an_amber_day_with_only_a_zone_2_ride_says_as_planned() -> None:
    call = todays_call(_packet("Amber", (Z2, "as_planned")))
    assert call.headline == "As planned"


def test_a_red_day_with_a_hard_session_is_a_recovery_day_never_rest_or_substitute() -> None:
    call = todays_call(_packet("Red", (VO2, "recovery")))
    assert call.headline == "Recovery day"
    assert "substitute" not in (call.headline + call.line).lower()


@pytest.mark.parametrize("floor", ["requiresTrainingRest", "requiresBikeRest"])
def test_a_rest_day_with_a_health_warning_still_leads_with_it(floor: str) -> None:
    packet = _packet(
        "Red",
        acute={floor: True, "requiresBikeRest": True},
        rest={"isRestDay": True, "reason": "planned_rest", "insidePlanWeek": True},
        planned=[],
    )
    call = todays_call(packet)
    assert call.state == 11
    assert call.look == LOOK_WARNING


def test_red_appears_only_for_the_health_warnings() -> None:
    for name, (packet, _) in STATES.items():
        call = todays_call(packet)
        assert (call.look == LOOK_WARNING) == (call.state == 11), name


#: A colour or "verdict" named to Mark. "Green light" is a coach's go, signed off as the
#: headline of states 1 and 2, so it is the one phrase allowed through.
COLOUR_WORDS = re.compile(r"\b(green|amber|red|verdict)\b", re.IGNORECASE)


def names_a_colour(text: str) -> bool:
    return COLOUR_WORDS.search(text.replace("Green light", "")) is not None


def test_no_call_names_a_colour_or_a_verdict() -> None:
    for name, (packet, _) in STATES.items():
        call = todays_call(packet)
        assert not names_a_colour(f"{call.headline} {call.line} {call.reading_words}"), name


def test_an_empty_day_stored_before_the_rule_is_read_with_it() -> None:
    """A morning stored before Batch 313 has no ``insidePlanWeek``: the reader says."""
    old = _packet("Red", planned=[], rest={"isRestDay": False, "reason": None})
    assert todays_call(old, in_plan_week=True).state == 14
    assert todays_call(old, in_plan_week=False).state == 16
    assert todays_call(old).state == 16


def test_a_stored_call_is_read_back_word_for_word() -> None:
    packet = _packet("Amber", (VO2, "ease_hard"))
    packet["todaysCall"] = todays_call(packet).to_packet()
    # Edit the stored words: the reader returns what was stored, not a recomputation.
    packet["todaysCall"]["line"] = "stored line"
    assert stored_call(packet).line == "stored line"
    del packet["todaysCall"]
    assert stored_call(packet).headline == "Take the edge off"


# -- the API serves the call ------------------------------------------------------------


def _analysis(packet: dict[str, Any]) -> Any:
    import uuid
    from datetime import date, datetime

    from src.models.coaching import Analysis

    return Analysis(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        analysis_type="morning",
        subject_date=date(2026, 3, 10),
        generated_at_utc=datetime(2026, 3, 10, 7, 0),
        prompt_version="morning-analysis-v57",
        model_name=None,
        verdict=packet["verdict"]["status"],
        context_packet=packet,
        output_markdown="",
        raw_response={},
    )


def test_the_envelope_serves_the_stored_call_word_for_word() -> None:
    from src.services.daily_loop_envelope import _serialize_analysis

    packet = _packet("Amber", (VO2, "ease_hard"))
    packet["todaysCall"] = todays_call(packet).to_packet()
    out = _serialize_analysis(_analysis(packet))
    assert out is not None
    assert out.todaysCall == packet["todaysCall"]
    assert out.todaysCall["headline"] == "Take the edge off"


def test_the_envelope_reads_a_morning_stored_before_the_batch_with_the_same_rule() -> None:
    from src.services.daily_loop_envelope import _serialize_analysis
    from src.services.todays_call import needs_plan_week

    old = _packet("Red", planned=[], rest={"isRestDay": False, "reason": None})
    assert needs_plan_week(old) is True
    rest = _serialize_analysis(_analysis(old), in_plan_week=True)
    unplanned = _serialize_analysis(_analysis(old), in_plan_week=False)
    assert rest is not None and unplanned is not None
    assert rest.todaysCall is not None and rest.todaysCall["headline"] == "Rest day"
    assert unplanned.todaysCall is not None
    assert unplanned.todaysCall["headline"] == "No session planned"


def test_only_an_old_empty_morning_needs_the_plan_blocks() -> None:
    from src.services.todays_call import needs_plan_week

    assert needs_plan_week(_packet("Amber", (Z2, "as_planned"))) is False
    stored = _packet("Red", planned=[], rest={"isRestDay": False, "reason": None})
    stored["todaysCall"] = todays_call(stored).to_packet()
    assert needs_plan_week(stored) is False
    rest = _packet("Red", planned=[], rest={"isRestDay": True, "reason": "holiday"})
    assert needs_plan_week(rest) is False


def test_the_calendar_day_is_the_reading_and_the_rest_rule() -> None:
    from src.services.todays_call import calendar_day

    assert calendar_day("Red", {}, 0, in_plan_week=True) == {
        "reading": "still_recovering",
        "restDay": True,
    }
    assert calendar_day("Red", {}, 0, in_plan_week=False) == {
        "reading": "still_recovering",
        "restDay": False,
    }
    assert calendar_day("green", {"isRestDay": True, "reason": "holiday"}, 1) == {
        "reading": "recovered",
        "restDay": True,
    }
    assert calendar_day("Amber", None, None, in_plan_week=True) == {
        "reading": "some_fatigue",
        "restDay": False,
    }
    assert calendar_day(None, {}, 0, in_plan_week=True) is None


def test_the_web_calendar_words_are_the_servers() -> None:
    """The calendar's copy of the reading words, pinned to the one rule's."""
    import json
    from pathlib import Path

    from src.services.todays_call import READING_WORDS, REST_DAY

    words = json.loads(
        (
            Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "readingWords.json"
        ).read_text()
    )
    assert words["restDay"] == REST_DAY
    assert words["readings"] == {
        key: value for key, value in READING_WORDS.items() if key != "waiting"
    }


# -- one rest-day rule (313.2) -----------------------------------------------------------


def test_an_empty_day_inside_a_plan_week_is_a_planned_rest_day() -> None:
    from datetime import date

    from src.services.morning_analysis import _rest_day_context

    day = date(2026, 3, 10)
    rest = _rest_day_context([], [], subject_date=day, inside_plan_week=True)
    assert (rest["isRestDay"], rest["reason"], rest["insidePlanWeek"]) == (
        True,
        "planned_rest",
        True,
    )
    # Outside every plan week an empty day stays unknown: "No session planned".
    unknown = _rest_day_context([], [], subject_date=day, inside_plan_week=False)
    assert (unknown["isRestDay"], unknown["reason"], unknown["insidePlanWeek"]) == (
        False,
        None,
        False,
    )


def test_a_planned_rest_day_has_its_own_plan_line() -> None:
    from src.services.morning_verdict import _plan_adjustments

    assert _plan_adjustments("Red", [], is_rest_day=True, rest_reason="planned_rest") == [
        "Today is a planned rest day."
    ]
    assert _plan_adjustments("Red", [], is_rest_day=True, rest_reason="holiday") == [
        "Today is an intentional rest day; keep paused or skipped sessions paused."
    ]
    assert _plan_adjustments("Red", [], is_rest_day=False) == [
        "No active planned workout found for today; keep advice conservative."
    ]


def test_the_rest_rule_flips_the_fixtures_empty_mornings_and_no_colour() -> None:
    """18, 21 and 25 Sep had nothing planned inside a plan week: rest days, same colour."""
    from datetime import date

    from tests.test_batch_295_verdict_grading import _load_fixture, _replayed

    fixture = _load_fixture()
    with_rule = _replayed(fixture)
    without = _replayed(fixture, rules_off={"planned_rest_day"})
    flipped = {day for day in with_rule if with_rule[day].rest_day != without[day].rest_day}
    assert flipped == {date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 25)}
    for day in with_rule:
        assert with_rule[day].graded_label == without[day].graded_label, day
        assert with_rule[day].ladder_label == without[day].ladder_label, day
        assert [a.action for a in with_rule[day].graded.actions] == [
            a.action for a in without[day].graded.actions
        ], day


# -- what made a tired morning tired -----------------------------------------------------


def test_a_tired_morning_records_whether_sleep_or_feel_made_it() -> None:
    from dataclasses import replace

    from src.services.verdict_grading import grade
    from tests.test_batch_295_verdict_grading import _inputs

    by_sleep = grade(_inputs(sleep_score=55))
    assert [a.action for a in by_sleep.actions][0] == "pick_zone2_or_tempo"
    assert by_sleep.references["tiredBy"] == "sleep"
    by_feel = grade(_inputs(feel=4))
    assert [a.action for a in by_feel.actions][0] == "pick_zone2_or_tempo"
    assert by_feel.references["tiredBy"] == "feel"
    # Two marked domains make Red, not a tired Amber; both count only when Garmin's own
    # score is very poor and the age credit lifted it: the sleep wording leads.
    both = grade(_inputs(sleep_score=62, raw_offset=7, feel=4))
    assert both.status == "Amber"
    assert both.references["tiredBy"] == "sleep"
    assert grade(_inputs()).references["tiredBy"] is None
    assert (
        grade(replace(_inputs(sleep_score=55), tired_morning_choices=False)).references["tiredBy"]
        is None
    )


# -- the prompts speak in the call's words (313.6) ----------------------------------------


def test_the_graded_brief_speaks_in_the_calls_words_and_the_ladder_is_untouched() -> None:
    from src.services.morning_analysis import (
        GRADED_PROMPT_VERSION,
        GRADED_SYSTEM_PROMPT,
        LADDER_SYSTEM_PROMPT,
    )
    from src.services.todays_call import TODAYS_CALL_RULE

    assert GRADED_PROMPT_VERSION == "morning-analysis-v58-2026-10-06"
    assert TODAYS_CALL_RULE in GRADED_SYSTEM_PROMPT
    assert "restDay.reason planned_rest" in GRADED_SYSTEM_PROMPT
    assert "frame today's verdict as a rest day" not in GRADED_SYSTEM_PROMPT
    assert TODAYS_CALL_RULE not in LADDER_SYSTEM_PROMPT
    assert "frame today's verdict as a rest day" in LADDER_SYSTEM_PROMPT


def test_the_chat_and_the_review_speak_in_the_calls_words() -> None:
    from src.services.brief_chat import PROMPT_VERSION as CHAT_VERSION
    from src.services.brief_chat import SYSTEM_PROMPT as CHAT_PROMPT
    from src.services.reviews import PROMPT_VERSION as REVIEW_VERSION
    from src.services.reviews import REVIEW_MORNINGS_RULE
    from src.services.reviews import SYSTEM_PROMPT as REVIEW_PROMPT
    from src.services.todays_call import TODAYS_CALL_RULE

    assert CHAT_VERSION == "coach-chat-v19-2026-10-05"
    assert TODAYS_CALL_RULE in CHAT_PROMPT
    assert "answer in kind" in TODAYS_CALL_RULE
    assert REVIEW_VERSION == "reviews-v11-2026-10-05"
    assert REVIEW_MORNINGS_RULE in REVIEW_PROMPT
    assert "3 recovered · 2 some fatigue · 2 still recovering" in REVIEW_MORNINGS_RULE


def test_the_plan_states_the_same_rules_in_the_calls_words() -> None:
    """Coach memory shows these to Mark; a fresh seed says them as production's v4 will."""
    from datetime import date

    from src.services.coaching_state import _training_plan_content

    constraints = _training_plan_content(date(2026, 7, 20))["constraints"]
    joined = " ".join(constraints)
    assert not names_a_colour(joined)
    assert "eased a zone" in joined and "full length" in joined
    assert "easy recovery spin" in joined and "never VO2" in joined
