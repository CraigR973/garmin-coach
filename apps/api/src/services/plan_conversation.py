"""Talk the proposed plan through with the coach (Batch 324).

Craig, 7 Oct 2026: Mark should be able to "have a conversation with the coach about the
upcoming proposed plan", and the coach may offer a change he applies with one tap. Batch
324.1 keeps the raw draft (about 74,000 characters) out of every prompt; this module is the
only way the coach sees it:

* :func:`compact_view` — what the chat carries while a draft waits: its name, dates, his
  days, the "why this plan" note, one line a week naming each session by id, and his
  changes so far. A few thousand characters, bounded by 13 week lines and the last 20
  changes, and never dropped for length.
* :func:`week_detail` — one week in full, for the coach's ``get_proposed_plan_week`` tool.
* :func:`extract_plan_change` and :func:`plan_change_offer` — the change an answer offers,
  marked ``[[PROPOSE_PLAN_CHANGE {...}]]``, validated by applying it to a copy of the draft
  as it stands (``plan_changes.apply_change``), so the coach's offer is bounded by exactly
  the rules his own taps are. The offer records the revision it was made against; a draft
  that has moved on refuses it, in words.
* :func:`plan_capability_instruction` — the closed list, stated to the model.

Nothing here writes a row. An offer changes the proposed plan only when he taps it, and the
plan reaches Zwift only when he accepts it.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import KnowledgeBase
from src.services.coach_policy import GENERATED_BLOCK_SECTION
from src.services.interval_workout_editor import (
    MAX_POWER_PCT,
    MAX_REPEATS,
    MAX_REST_DURATION_SEC,
    MAX_WORK_DURATION_SEC,
    MIN_POWER_PCT,
    MIN_REPEATS,
    MIN_REST_DURATION_SEC,
    MIN_WORK_DURATION_SEC,
)
from src.services.next_plan import WEEKDAYS
from src.services.plan_changes import (
    BY_COACH,
    LONG_RIDE_ADD_MIN_MINUTES,
    MALFORMED_WORDS,
    REFUSED_MALFORMED,
    RIDE_MAX_MINUTES,
    RIDE_MIN_MINUTES,
    STRENGTH_MAX_MINUTES,
    STRENGTH_MIN_MINUTES,
    PlanChangeRefused,
    apply_change,
    normalise_draft,
    short_day,
    start_options,
    weeks_over_longest,
)

STATUS_DRAFT: Final = "draft"

#: The last changes the compact view lists; older ones are counted, not shown.
COMPACT_CHANGES: Final = 20

PLAN_CHANGE_MARKER_OPEN: Final = "[[PROPOSE_PLAN_CHANGE "
PLAN_CHANGE_MARKER_CLOSE: Final = "]]"
_PLAN_CHANGE_MARKER: Final = re.compile(
    r"\[\[PROPOSE_PLAN_CHANGE\s*(?P<payload>\{.*?\})?\s*\]\]", re.DOTALL
)

#: The states an offer can be in. ``proposed`` waits for his tap; ``applied`` is done;
#: ``stale`` was tapped after the plan had moved on; ``unavailable`` could not be offered.
OFFER_PROPOSED: Final = "proposed"
OFFER_APPLIED: Final = "applied"
OFFER_STALE: Final = "stale"
OFFER_UNAVAILABLE: Final = "unavailable"

UNAVAILABLE_NO_PLAN: Final = "no_plan"
NO_PLAN_WORDS: Final = "There's no plan waiting to change."
STALE_WORDS: Final = (
    "The plan has changed since the coach suggested this, so it hasn't been applied. "
    "Ask the coach again."
)
PLAN_GONE_WORDS: Final = "That plan isn't waiting any more: it has been accepted or declined."
APPLIED_ALREADY_WORDS: Final = "This change is already in your proposed plan."
NOTHING_TO_APPLY_WORDS: Final = "There's no change to apply here."


async def load_waiting_draft(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any] | None:
    """His proposed plan while it waits for him (a draft), read with ids; else ``None``."""

    row = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.section == GENERATED_BLOCK_SECTION,
            KnowledgeBase.is_active.is_(True),
        )
    )
    if row is None or not isinstance(row.content, dict):
        return None
    if row.content.get("status") != STATUS_DRAFT:
        return None
    try:
        return normalise_draft(row.content)
    except PlanChangeRefused:
        return None


def _day_label(iso: str) -> str:
    return short_day(date.fromisoformat(iso)).split(" ", 1)[0]


def _week_line(week: dict[str, Any]) -> str:
    start = date.fromisoformat(week["startDate"])
    end = date.fromisoformat(week["endDate"])
    span = (
        f"{start.day}–{short_day(end).split(' ', 1)[1]}"
        if start.month == end.month
        else f"{short_day(start).split(' ', 1)[1]}–{short_day(end).split(' ', 1)[1]}"
    )
    sessions = " · ".join(
        f"{_day_label(w['workoutDate'])} {w['id']} {w['title']} {w['plannedDurationMin']} min"
        for w in week["workouts"]
    )
    return (
        f"Week {week['weekNumber']} ({span}, {week['label']}, {week['totalMin']} min): "
        f"{sessions or 'nothing planned'}"
    )


COMPACT_VIEW_MEANING: Final = (
    "Mark's proposed next plan, waiting in the plan builder. It is not his plan yet: nothing "
    "in it is on his calendar or in Zwift until he accepts it, and he can change any of it "
    "first, by hand or with a change you offer. Each week is one line: weekday, the "
    "session's id, its title and minutes. get_proposed_plan_week returns any week in full "
    "(targets and steps). whyThisPlan explains the plan as proposed; changes lists what has "
    "been changed since, newest last, and who made each change. weeksOverLongest are weeks "
    "longer than his longest week of his last plan, which the builder warns him about."
)


def _who(entry: dict[str, Any]) -> str:
    return "Mark" if entry.get("by") == "you" else "your suggestion, which Mark applied"


def compact_view(draft: dict[str, Any]) -> dict[str, Any]:
    """The proposed plan as the chat carries it: a few thousand characters, never the draft."""

    raw_basis = draft.get("basis")
    basis: dict[str, Any] = raw_basis if isinstance(raw_basis, dict) else {}
    changes = list(draft.get("changes") or [])
    shown = changes[-COMPACT_CHANGES:]
    view: dict[str, Any] = {
        "planName": draft.get("planName"),
        "status": "waiting for Mark: he can accept it, change it, or decline it",
        "startDate": draft["startDate"],
        "endDate": draft["endDate"],
        "revision": draft.get("revision", 0),
        "days": {key: WEEKDAYS[int(day)] for key, day in dict(draft["days"]).items()},
        "previousPlan": basis.get("previousPlan"),
        "longestWeekMinutes": basis.get("longestWeekMin"),
        "whyThisPlan": list(draft.get("whyThisPlan") or []),
        "weeks": [_week_line(week) for week in draft["weeks"]],
        "weeksOverLongest": weeks_over_longest(draft),
        "changes": [
            f"Revision {entry.get('revision')} ({_who(entry)}): {entry.get('summary')}"
            for entry in shown
            if isinstance(entry, dict)
        ],
        "meaning": COMPACT_VIEW_MEANING,
    }
    if len(changes) > len(shown):
        view["olderChangesNotShown"] = len(changes) - len(shown)
    return view


def week_detail(draft: dict[str, Any], week_number: int) -> dict[str, Any] | None:
    """One week of the proposed plan in full, or ``None`` for a week it does not have."""

    week = next((w for w in draft["weeks"] if int(w["weekNumber"]) == week_number), None)
    if week is None:
        return None
    return {
        "weekNumber": week["weekNumber"],
        "label": week["label"],
        "startDate": week["startDate"],
        "endDate": week["endDate"],
        "totalMin": week["totalMin"],
        "sessions": [
            {
                "id": w["id"],
                "date": w["workoutDate"],
                "day": WEEKDAYS[date.fromisoformat(w["workoutDate"]).weekday()],
                "title": w["title"],
                "minutes": w["plannedDurationMin"],
                "target": w.get("intensityTarget"),
                "summary": (w.get("structuredWorkout") or {}).get("summary"),
                "steps": (w.get("structuredWorkout") or {}).get("steps"),
            }
            for w in week["workouts"]
        ],
    }


# -- the offer -------------------------------------------------------------------------------


def extract_plan_change(answer: str) -> tuple[str, str | None, bool]:
    """Mark's copy without the marker, the raw payload if any, and whether a marker was there."""

    match = _PLAN_CHANGE_MARKER.search(answer)
    if match is None:
        return answer, None, False
    cleaned = _PLAN_CHANGE_MARKER.sub("", answer).strip()
    return cleaned, match.group("payload"), True


def plan_change_offer(
    payload: str | None,
    draft: dict[str, Any] | None,
    *,
    today: date,
    now: datetime,
) -> dict[str, Any]:
    """The change to put in front of him, checked against the draft as it stands.

    Every check is the one his own tap would meet: the change is applied to a copy of the
    draft and the copy thrown away. A change the draft cannot take is stored as unavailable,
    with the words he is shown, so a claim the coach made is never left with nothing under it.
    """

    if draft is None:
        return {"status": OFFER_UNAVAILABLE, "reason": UNAVAILABLE_NO_PLAN, "words": NO_PLAN_WORDS}
    try:
        if payload is None:
            raise ValueError("no payload")
        change = json.loads(payload)
        applied = apply_change(draft, change, today=today, by=BY_COACH, at_utc=now)
    except PlanChangeRefused as refused:
        return {"status": OFFER_UNAVAILABLE, "reason": refused.reason, "words": refused.words}
    except ValueError:
        return {"status": OFFER_UNAVAILABLE, "reason": REFUSED_MALFORMED, "words": MALFORMED_WORDS}
    return {
        "status": OFFER_PROPOSED,
        "change": applied.change,
        "summary": applied.summary,
        "planName": draft.get("planName"),
        "generatedAtUtc": draft.get("generatedAtUtc"),
        "revision": int(draft.get("revision") or 0),
    }


def offer_is_current(offer: dict[str, Any], draft: dict[str, Any] | None) -> bool:
    """Whether the draft is still the one, at the revision, the offer was made against."""

    return (
        draft is not None
        and draft.get("generatedAtUtc") == offer.get("generatedAtUtc")
        and int(draft.get("revision") or 0) == offer.get("revision")
    )


def plan_capability_instruction(draft: dict[str, Any] | None, *, today: date) -> str | None:
    """What the coach may offer on the proposed plan, in the app's exact terms; ``None`` if none.

    Stated as a closed list because the model reads a capability list as closed (Batch 238).
    The revision is left out on purpose: it is in the plan's view, and keeping it out of this
    cached prefix means a change he makes does not rebuild the cache.
    """

    if draft is None:
        return None
    options = start_options(today)
    name = draft.get("planName") or "his next plan"
    return (
        f"Capability for his proposed plan: {name} is waiting in the plan builder "
        "(proposedPlan, below). Separately from today's session, you can offer him ONE change "
        "to it per answer, from this closed list, and the app checks it against the plan as "
        "it stands before it shows it to him. Use the session ids shown in the plan.\n"
        '- days: which weekday each kind of session is on, every week: {"kind": "days", '
        '"days": {"strengthA": "Monday", "vo2": "Tuesday", "zone2": "Wednesday", '
        '"sweetSpot": "Thursday", "rest": "Friday", "sprints": "Saturday", "strengthB": '
        '"Saturday", "longRide": "Sunday"}}. All eight, every time. Each ride on a day of its '
        "own, nothing on the rest day, the two dumbbell sessions on different days. It "
        "rebuilds the plan from its table, so any changes he made to single sessions go: say "
        "so when you offer it.\n"
        '- start: {"kind": "start", "startDate": "YYYY-MM-DD"}, a Monday from '
        f"{options[0].isoformat()} to {options[-1].isoformat()}. His changes move with it.\n"
        '- intervals: {"kind": "intervals", "session": "s009", "repeat": 12, "workSec": 30, '
        '"workPct": 130, "restSec": 30, "restPct": 55}: the ride\'s interval set as it would '
        "be AFTER the change; for a ride with matching sets, the numbers for ONE set. Any ride "
        f"with an interval set except the ramp test; repeats {MIN_REPEATS}-{MAX_REPEATS}, "
        f"effort {MIN_WORK_DURATION_SEC}-{MAX_WORK_DURATION_SEC} seconds, recovery "
        f"{MIN_REST_DURATION_SEC}-{MAX_REST_DURATION_SEC} seconds, both percentages "
        f"{MIN_POWER_PCT}-{MAX_POWER_PCT}. Read the week with get_proposed_plan_week first.\n"
        '- minutes: {"kind": "minutes", "session": "s007", "minutes": 150}: a steady ride '
        f"({RIDE_MIN_MINUTES}-{RIDE_MAX_MINUTES}) or a dumbbell session "
        f"({STRENGTH_MIN_MINUTES}-{STRENGTH_MAX_MINUTES}); an interval ride's length comes "
        "from its intervals.\n"
        '- title: {"kind": "title", "session": "s003", "title": "..."}.\n'
        '- move: {"kind": "move", "session": "s014", "toDate": "YYYY-MM-DD"}, any day of the '
        "plan.\n"
        '- remove: {"kind": "remove", "session": "s012"}.\n'
        '- add: {"kind": "add", "date": "YYYY-MM-DD", "sessionType": "zone2", "minutes": 60}, '
        "sessionType one of zone2, easy, long, strength_a, strength_b (a long ride at least "
        f"{LONG_RIDE_ADD_MIN_MINUTES} minutes; a dumbbell session takes that week's dose).\n"
        '- reset: {"kind": "reset"}, back to the plan as proposed.\n'
        "When your answer offers one of these, end it with the marker on its own line:\n"
        f'{PLAN_CHANGE_MARKER_OPEN}{{"kind": "remove", "session": "s012"}}'
        f"{PLAN_CHANGE_MARKER_CLOSE}\n"
        "The app removes the marker before Mark sees it and shows him the change with a button "
        "to apply it. It changes the proposed plan only when he taps it, and nothing reaches "
        "his calendar or Zwift until he accepts the whole plan. So describe what you are "
        "putting in front of him, and never say you have changed, applied, moved or "
        "scheduled anything. If he wants several changes, offer the one that matters most "
        "and say you can do the next after it. If what he wants is not on this list, say "
        "plainly that it is not a change you can make here."
    )
