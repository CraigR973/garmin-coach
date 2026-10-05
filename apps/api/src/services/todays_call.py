"""Today's call: what to do today, in a coach's words (Batch 313).

The morning reached Mark as a colour. Home and the brief page led with a grade ("Rest or
substitute" on any Red, a "Red verdict" chip and, on Red, a stop sign above "Today's a
rest day"), the written brief opened "**Red.**" and the sleep calendar marked G, A and
R, though the engine already decides what happens to each session (``verdict_grading``'s
session actions). Craig signed off, on Mark's behalf (4 Oct 2026,
``docs/drafts/2026-10-04-morning-call-wording.md``, and two more lines on 5 Oct), the
morning states that separate the two things the colour fused:

* the **headline** says what to do today, from the engine's own session actions;
* the **reading**, a chip, says how recovered he is: Recovered, Some fatigue or Still
  recovering, the engine's Green, Amber and Red in words;
* rest days lead with "Rest day" whatever the reading, and a low reading makes the rest
  "well timed", not a warning;
* red is kept for the two health warnings; recovery and rest days are a calm blue.

One function, :func:`todays_call`, picks the state from the stored morning packet. It
runs when the morning is graded, before the paid brief, and its result is stored with
the morning (``todaysCall``), so Home, the brief page, the written brief and the coach
chat read one copy. A morning stored before this batch is read with the same rule from
its stored fields. Nothing here changes the colour, the engine, the ride changes or the
rule that a Red day never sends VO2 to Zwift.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from src.services.workout_categories import is_bike_workout_type

#: How every prompt that speaks to Mark names the morning: the written brief and the
#: coach chat (the weekly review states its own count, in the same words).
TODAYS_CALL_RULE: Final = """Speak to Mark about the morning in today's call's words,
never in colours. todaysCall is the morning's call: its headline says what to do today,
its line says why, and readingWords says how recovered he is (Recovered, Some fatigue or
Still recovering: the engine's Green, Amber and Red in words). Use the headline and the
reading word for word, call a rest day a rest day, and never write Green, Amber, Red or
verdict to him. If he uses a colour himself, answer in kind and give the call's words
beside it. The stored colour stays the engine's record, and nothing you say changes it."""

# -- the readings: the engine's Green, Amber and Red, in words (the chip) ------------------

READING_RECOVERED: Final = "recovered"
READING_SOME_FATIGUE: Final = "some_fatigue"
READING_STILL_RECOVERING: Final = "still_recovering"
READING_WAITING: Final = "waiting"
READING_WORDS: Final[dict[str, str]] = {
    READING_RECOVERED: "Recovered",
    READING_SOME_FATIGUE: "Some fatigue",
    READING_STILL_RECOVERING: "Still recovering",
    READING_WAITING: "Waiting for data",
}
_READING_BY_STATUS: Final[dict[str, str]] = {
    "Green": READING_RECOVERED,
    "Amber": READING_SOME_FATIGUE,
    "Red": READING_STILL_RECOVERING,
}

# -- the looks (313.4) ------------------------------------------------------------------

#: Green and a tick: the go calls (states 1-4).
LOOK_GO: Final = "go"
#: Amber and a gauge: the adjust calls (5-7).
LOOK_ADJUST: Final = "adjust"
#: Blue and a charging battery: recovery and rest (8-10, 12-15). In Zwift's zone
#: colours, which he rides by, blue is easy and red is all-out.
LOOK_RECOVER: Final = "recover"
#: Grey: no session planned, and the call not ready (16, 17).
LOOK_NEUTRAL: Final = "neutral"
#: Red and the stop icon: the two health warnings only (11).
LOOK_WARNING: Final = "warning"

# -- the words, signed off by Craig on Mark's behalf (4 Oct 2026; 5 Oct where marked) -----

GREEN_LIGHT: Final = "Green light"
GREEN_LIGHT_LINE: Final = "You're recovered. Today's session is on as written."
GREEN_LIGHT_HARD_ADD: Final = "Make it count."
GREEN_LIGHT_EASY_ADD: Final = "Keep the easy riding easy."

HOLD_TARGETS: Final = "Green light — hold the targets"
HOLD_TARGETS_EASY_LINE: Final = (
    "One reading's a touch off. Today's session is on as written; leave a little in the tank."
)
HOLD_TARGETS_HARD_LINE: Final = (
    "One reading's a touch off. If there's a better day this week, move the hard session "
    "there; if not, ride it and hold the targets."
)

LIGHT_WEEK: Final = "As planned — hold the targets"
LIGHT_WEEK_LINE: Final = (
    "It's your {week} week, so the session's already light. Ride it as written and hold the "
    "targets."
)

AS_PLANNED: Final = "As planned"
AS_PLANNED_LINE: Final = (
    "There's some fatigue about, and today's plan already suits it. Keep it comfortable."
)
#: Craig, 5 Oct 2026: a still-recovering morning with no ride planned, only strength or
#: mobility, which the engine keeps as planned.
AS_PLANNED_STILL_RECOVERING_LINE: Final = (
    "Your body's still recovering, and today's plan already suits it. Keep it comfortable."
)

TAKE_THE_EDGE_OFF: Final = "Take the edge off"
TAKE_THE_EDGE_OFF_LINE: Final = (
    "There's some fatigue about. Ride the full session with the hard efforts eased a zone; "
    "easy riding stays as planned."
)

EASY_OR_TEMPO: Final = "Easy or tempo — your call"
_SLEEP_CAUSE: Final = "Sleep let you down last night"
_FEEL_CAUSE: Final = "You're feeling flat this morning"
EASY_OR_TEMPO_LINE: Final = (
    "{cause}, so the hard efforts are off today. Move the session to a fresher day, or pick "
    "easy Zone 2 or tempo below."
)

LONG_RIDE_SHORTER: Final = "Long ride — shorter if you like"
#: The feel version is Craig's of 5 Oct 2026; the sleep version is the draft's.
LONG_RIDE_SHORTER_LINE: Final = (
    "{cause}. Ride it as planned, or take the shorter version in one tap."
)

RECOVERY_DAY: Final = "Recovery day"
RECOVERY_DAY_LINE: Final = (
    "Your body's still recovering. The hard session will do more for you on a fresher day "
    "— today, rest or an easy spin."
)

SHORT_AND_EASY: Final = "Short and easy"
SHORT_AND_EASY_LINE: Final = (
    "Your body's still recovering. Keep today's Zone 2 ride, just shorter — easy miles, "
    "nothing more."
)

EASY_DAY: Final = "Easy day"
EASY_DAY_LINE: Final = "Today's hard session becomes an easy spin — the note below explains why."

#: The health warnings keep the words signed off on 28 Sep 2026 (Batches 277 and 294).
NO_TRAINING: Final = "No training today"
NO_TRAINING_LINE: Final = "The symptoms you've reported rule out training today."
OFF_THE_BIKE: Final = "Take today off the bike"
OFF_THE_BIKE_LINE: Final = "An acute recovery signal rules out riding today."

REST_DAY: Final = "Rest day"
REST_DAY_LINES: Final[dict[str, str]] = {
    READING_RECOVERED: (
        "You're recovered — enjoy the day off. Rest is where this week's training turns into "
        "fitness."
    ),
    READING_SOME_FATIGUE: "Good timing — there's some fatigue about, and today lets it clear.",
    READING_STILL_RECOVERING: (
        "Well timed — your body's still recovering, and rest is exactly what it needs."
    ),
}

HOLIDAY: Final = "Holiday"
HOLIDAY_LINE: Final = "Enjoy the break. The plan picks up when you're home."

NO_SESSION_PLANNED: Final = "No session planned"
NO_SESSION_PLANNED_LINE: Final = "There's nothing in your plan for today yet."

NOT_READY: Final = "Not ready yet"
NOT_READY_LINE: Final = "Today's call lands once your overnight data has synced."

# -- the states ---------------------------------------------------------------------------

STATE_GREEN_LIGHT: Final = 1
STATE_HOLD_TARGETS: Final = 2
STATE_LIGHT_WEEK: Final = 3
STATE_AS_PLANNED: Final = 4
STATE_TAKE_THE_EDGE_OFF: Final = 5
STATE_EASY_OR_TEMPO: Final = 6
STATE_LONG_RIDE_SHORTER: Final = 7
STATE_RECOVERY_DAY: Final = 8
STATE_SHORT_AND_EASY: Final = 9
STATE_EASY_DAY: Final = 10
STATE_HEALTH_WARNING: Final = 11
STATE_REST_RECOVERED: Final = 12
STATE_REST_SOME_FATIGUE: Final = 13
STATE_REST_STILL_RECOVERING: Final = 14
STATE_HOLIDAY: Final = 15
STATE_NO_SESSION_PLANNED: Final = 16
STATE_NOT_READY: Final = 17

_REST_STATES: Final[dict[str, int]] = {
    READING_RECOVERED: STATE_REST_RECOVERED,
    READING_SOME_FATIGUE: STATE_REST_SOME_FATIGUE,
    READING_STILL_RECOVERING: STATE_REST_STILL_RECOVERING,
}

#: The rest-day reasons the morning stores (``restDay.reason``). A planned rest day is
#: Batch 313's: nothing planned inside a week a plan block covers.
REST_HOLIDAY: Final = "holiday"
REST_ALL_SKIPPED: Final = "all_skipped"
REST_PLANNED: Final = "planned_rest"

#: Session statuses that are not a live session today.
_NOT_LIVE: Final = frozenset({"completed", "skipped"})
#: Workout types the ladder-era history reads as hard (the replay's own list).
_LADDER_HARD_TYPES: Final = frozenset({"bike_vo2", "bike_sweet_spot", "bike_threshold"})


@dataclass(frozen=True, slots=True)
class TodaysCall:
    """One morning's call: its state, headline, line, reading and look."""

    state: int
    key: str
    headline: str
    line: str
    reading: str
    look: str

    @property
    def reading_words(self) -> str:
        return READING_WORDS[self.reading]

    def to_packet(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "key": self.key,
            "headline": self.headline,
            "line": self.line,
            "reading": self.reading,
            "readingWords": self.reading_words,
            "look": self.look,
        }


@dataclass(frozen=True, slots=True)
class _Session:
    action: str
    is_bike: bool
    is_hard: bool


NOT_READY_CALL: Final = TodaysCall(
    state=STATE_NOT_READY,
    key="not_ready",
    headline=NOT_READY,
    line=NOT_READY_LINE,
    reading=READING_WAITING,
    look=LOOK_NEUTRAL,
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _status(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return {"green": "Green", "amber": "Amber", "red": "Red"}.get(value.strip().lower())


def reading_for_status(status: str | None) -> str | None:
    """The chip for a stored colour: Recovered, Some fatigue or Still recovering."""

    normalized = _status(status)
    return _READING_BY_STATUS[normalized] if normalized is not None else None


def rest_reason(packet: Mapping[str, Any], *, in_plan_week: bool | None = None) -> str | None:
    """Why a stored morning is a rest day, or ``None`` (Batch 313's one rule).

    A holiday, a day whose sessions are all skipped, or a day with nothing planned
    inside a week the plan covers. A morning stored with Batch 313's rule records
    ``restDay.insidePlanWeek``; one stored before it is read with the same rule, from
    its own sessions and ``in_plan_week`` (the plan blocks, which the caller reads).
    """

    rest_day = _mapping(packet.get("restDay"))
    if rest_day.get("isRestDay") is True:
        reason = rest_day.get("reason")
        return str(reason) if isinstance(reason, str) else REST_ALL_SKIPPED
    if "insidePlanWeek" in rest_day:
        return None
    planned = packet.get("plannedWorkouts")
    if isinstance(planned, list) and not planned and in_plan_week is True:
        return REST_PLANNED
    return None


def _sessions(packet: Mapping[str, Any], verdict: Mapping[str, Any], status: str) -> list[_Session]:
    """Today's live sessions and what the morning decided for each."""

    graded = _mapping(verdict.get("graded"))
    actions = graded.get("actions")
    if verdict.get("engine") == "graded" and isinstance(actions, list):
        return [
            _Session(
                action=str(item.get("action") or ""),
                is_bike=is_bike_workout_type(item.get("workoutType")),
                is_hard=item.get("isHard") is True,
            )
            for item in actions
            if isinstance(item, Mapping)
        ]
    # A morning the ladder decided (before 30 Sep 2026, or after a rollback) stored no
    # session actions: read the ladder's own rule for each live session.
    held = _mapping(verdict.get("hrvGradedResponse")).get("tier") == "hold"
    sessions: list[_Session] = []
    planned = packet.get("plannedWorkouts")
    for item in planned if isinstance(planned, list) else []:
        if not isinstance(item, Mapping) or item.get("status") in _NOT_LIVE:
            continue
        workout_type = item.get("workoutType")
        is_bike = is_bike_workout_type(workout_type)
        is_hard = is_bike and str(workout_type or "").lower() in _LADDER_HARD_TYPES
        if not is_bike:
            action = "as_planned"
        elif status == "Red":
            action = "recovery" if is_hard else "shortened_zone2"
        elif status == "Amber":
            action = "ease_hard" if is_hard else "as_planned"
        elif held and is_hard:
            action = "move_or_hold"
        else:
            action = "as_planned"
        sessions.append(_Session(action=action, is_bike=is_bike, is_hard=is_hard))
    return sessions


def _tired_cause(verdict: Mapping[str, Any]) -> str:
    """Sleep or how he feels: what made a tired morning tired (Batch 306's flag).

    Stored since Batch 313 (``references.tiredBy``). Before that the domains decide; when
    both are marked the sleep wording leads (313, open at its start: settled as
    recommended).
    """

    graded = _mapping(verdict.get("graded"))
    stored = _mapping(graded.get("references")).get("tiredBy")
    if stored in ("sleep", "feel"):
        return str(stored)
    ratings = {
        str(item.get("domain")): item.get("rating")
        for item in graded.get("domains") or []
        if isinstance(item, Mapping)
    }
    if ratings.get("subjective") == "marked" and ratings.get("sleep") != "marked":
        return "feel"
    return "sleep"


def _call(state: int, key: str, headline: str, line: str, reading: str, look: str) -> TodaysCall:
    return TodaysCall(
        state=state, key=key, headline=headline, line=line, reading=reading, look=look
    )


def todays_call(packet: Any, *, in_plan_week: bool | None = None) -> TodaysCall:
    """The call for one stored morning (313.3). Pure and deterministic.

    The order is the draft's: a health warning first, on any day; then a holiday or a
    rest day; then a day with nothing planned; then the session actions, the most
    consequential first (recovery spin, shorter Zone 2, pick Zone 2 or tempo, ease the
    hard work, offer shorter, move or hold, hold the targets, as planned).
    """

    packet = _mapping(packet)
    verdict = _mapping(packet.get("verdict"))
    status = _status(verdict.get("status"))
    if status is None:
        return NOT_READY_CALL
    reading = _READING_BY_STATUS[status]

    acute = _mapping(verdict.get("acutePhysiology"))
    if acute.get("requiresTrainingRest") is True:
        return _call(
            STATE_HEALTH_WARNING,
            "no_training",
            NO_TRAINING,
            NO_TRAINING_LINE,
            reading,
            LOOK_WARNING,
        )
    if acute.get("requiresBikeRest") is True:
        return _call(
            STATE_HEALTH_WARNING,
            "off_the_bike",
            OFF_THE_BIKE,
            OFF_THE_BIKE_LINE,
            reading,
            LOOK_WARNING,
        )

    rest = rest_reason(packet, in_plan_week=in_plan_week)
    if rest == REST_HOLIDAY:
        return _call(STATE_HOLIDAY, "holiday", HOLIDAY, HOLIDAY_LINE, reading, LOOK_RECOVER)
    if rest is not None:
        return _call(
            _REST_STATES[reading],
            "rest_day",
            REST_DAY,
            REST_DAY_LINES[reading],
            reading,
            LOOK_RECOVER,
        )

    planned = packet.get("plannedWorkouts")
    if not (isinstance(planned, list) and planned):
        # Nothing planned and not a rest day: outside every plan week (state 16).
        return _call(
            STATE_NO_SESSION_PLANNED,
            "no_session_planned",
            NO_SESSION_PLANNED,
            NO_SESSION_PLANNED_LINE,
            reading,
            LOOK_NEUTRAL,
        )
    # A session already ridden or skipped has no action; the colour's own call stands.
    sessions = _sessions(packet, verdict, status)
    actions = {session.action for session in sessions}
    graded = _mapping(verdict.get("graded"))

    if status == "Red":
        if any(session.action == "recovery" and session.is_hard for session in sessions):
            return _call(
                STATE_RECOVERY_DAY,
                "recovery_day",
                RECOVERY_DAY,
                RECOVERY_DAY_LINE,
                reading,
                LOOK_RECOVER,
            )
        if "shortened_zone2" in actions:
            return _call(
                STATE_SHORT_AND_EASY,
                "short_and_easy",
                SHORT_AND_EASY,
                SHORT_AND_EASY_LINE,
                reading,
                LOOK_RECOVER,
            )
        return _call(
            STATE_AS_PLANNED,
            "as_planned_still_recovering",
            AS_PLANNED,
            AS_PLANNED_STILL_RECOVERING_LINE,
            reading,
            LOOK_GO,
        )
    if "recovery" in actions:
        # Below Red only what follows a symptom (Batch 303) makes a hard session an
        # easy spin: an easy day back after a fever, or an unanswered chest question.
        return _call(STATE_EASY_DAY, "easy_day", EASY_DAY, EASY_DAY_LINE, reading, LOOK_RECOVER)
    if "pick_zone2_or_tempo" in actions:
        cause = _FEEL_CAUSE if _tired_cause(verdict) == "feel" else _SLEEP_CAUSE
        return _call(
            STATE_EASY_OR_TEMPO,
            "easy_or_tempo",
            EASY_OR_TEMPO,
            EASY_OR_TEMPO_LINE.format(cause=cause),
            reading,
            LOOK_ADJUST,
        )
    if "ease_hard" in actions:
        return _call(
            STATE_TAKE_THE_EDGE_OFF,
            "take_the_edge_off",
            TAKE_THE_EDGE_OFF,
            TAKE_THE_EDGE_OFF_LINE,
            reading,
            LOOK_ADJUST,
        )
    if "offer_shorter" in actions:
        cause = _FEEL_CAUSE if _tired_cause(verdict) == "feel" else _SLEEP_CAUSE
        return _call(
            STATE_LONG_RIDE_SHORTER,
            "long_ride_shorter",
            LONG_RIDE_SHORTER,
            LONG_RIDE_SHORTER_LINE.format(cause=cause),
            reading,
            LOOK_ADJUST,
        )
    if "move_or_hold" in actions:
        return _call(
            STATE_HOLD_TARGETS,
            "hold_targets",
            HOLD_TARGETS,
            HOLD_TARGETS_HARD_LINE,
            reading,
            LOOK_GO,
        )
    if "hold_targets" in actions:
        week = _mapping(graded.get("references")).get("lightWeek")
        return _call(
            STATE_LIGHT_WEEK,
            "light_week",
            LIGHT_WEEK,
            LIGHT_WEEK_LINE.format(week=week if isinstance(week, str) and week else "recovery"),
            reading,
            LOOK_GO,
        )
    if verdict.get("held") is True or (
        status == "Green" and _mapping(verdict.get("hrvGradedResponse")).get("tier") == "hold"
    ):
        return _call(
            STATE_HOLD_TARGETS,
            "hold_targets",
            HOLD_TARGETS,
            HOLD_TARGETS_EASY_LINE,
            reading,
            LOOK_GO,
        )
    if status == "Amber":
        return _call(STATE_AS_PLANNED, "as_planned", AS_PLANNED, AS_PLANNED_LINE, reading, LOOK_GO)
    line = GREEN_LIGHT_LINE
    if any(session.is_bike and session.is_hard for session in sessions):
        line = f"{line} {GREEN_LIGHT_HARD_ADD}"
    elif any(session.is_bike for session in sessions):
        line = f"{line} {GREEN_LIGHT_EASY_ADD}"
    return _call(STATE_GREEN_LIGHT, "green_light", GREEN_LIGHT, line, reading, LOOK_GO)


def stored_call(packet: Any, *, in_plan_week: bool | None = None) -> TodaysCall:
    """The call a morning stored, or the same rule read from its stored fields."""

    stored = _mapping(_mapping(packet).get("todaysCall"))
    if isinstance(stored.get("state"), int) and isinstance(stored.get("headline"), str):
        reading = str(stored.get("reading") or "")
        if reading in READING_WORDS:
            return TodaysCall(
                state=int(stored["state"]),
                key=str(stored.get("key") or ""),
                headline=str(stored["headline"]),
                line=str(stored.get("line") or ""),
                reading=reading,
                look=str(stored.get("look") or LOOK_NEUTRAL),
            )
    return todays_call(packet, in_plan_week=in_plan_week)


def needs_plan_week(packet: Any) -> bool:
    """Whether reading a stored morning's call needs the plan blocks (Batch 313).

    Only a morning stored before the batch, with nothing planned, no stored call and
    no rest flag, needs to know whether a plan week covered it.
    """

    packet = _mapping(packet)
    if isinstance(_mapping(packet.get("todaysCall")).get("state"), int):
        return False
    rest_day = _mapping(packet.get("restDay"))
    if rest_day.get("isRestDay") is True or "insidePlanWeek" in rest_day:
        return False
    planned = packet.get("plannedWorkouts")
    return isinstance(planned, list) and not planned


def calendar_day(
    verdict: str | None,
    rest_day: Any,
    planned_count: int | None,
    *,
    in_plan_week: bool | None = None,
) -> dict[str, Any] | None:
    """One stored morning as the sleep calendar shows it: its reading, and rest or not.

    The calendar reads the colour column and two small parts of the packet, never the
    whole packet (``batch-verify``'s JSONB rule); the rest-day rule is the call's own.
    """

    reading = reading_for_status(verdict)
    if reading is None:
        return None
    planned: list[Any] | None = [{}] * planned_count if planned_count is not None else None
    packet = {"restDay": dict(_mapping(rest_day)), "plannedWorkouts": planned}
    return {
        "reading": reading,
        "restDay": rest_reason(packet, in_plan_week=in_plan_week) is not None,
    }
