"""A factual opening for a challenge to one same-day morning cut.

The stored morning projection describes what the read proposed. It does not
prove that Mark approved the offer or that the adjusted ride reached his device.
Ambiguous dates, sessions and durations leave the model's ordinary answer path
alone rather than attaching the wrong workout to his question.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, status

_CUT_TOPIC = re.compile(
    r"\b(?:cut|cuts|trim|trimmed|shorten(?:ed|ing)?|reduc(?:e|ed|tion)|"
    r"eas(?:e|ed|ier|ing)|lighter|less time|duration|(?:severe|training) actions?)\b",
    re.IGNORECASE,
)
_CHALLENGE = re.compile(
    r"\b(?:why|too|overly|excessive|severe|disproportionate|unfair|"
    r"overcautious|cautious|concern(?:ed)?|question|justif(?:y|ied)|"
    r"emphasis|weight|solely)\b",
    re.IGNORECASE,
)
_PAST_SESSION = re.compile(
    r"\b(?:yesterday(?:'s)?|last week|previous (?:ride|session|week)|"
    r"last (?:ride|session)|on \d{1,2} (?:jan|feb|mar|apr|may|jun|jul|aug|"
    r"sep|oct|nov|dec))\b",
    re.IGNORECASE,
)
_DURATION_QUOTE = re.compile(r"\b(\d+)[-\s]*(?:min(?:ute)?s?|hours?|hrs?)\b", re.IGNORECASE)
_MINIMISED_CUT = re.compile(
    r"\b(?:cut|trim|reduction|easing|shortening)\b[^.!?]{0,65}"
    r"\b(?:modest|minor|small|slight|tiny|negligible)\b|"
    r"\b(?:modest|minor|small|slight|tiny|negligible)\b[^.!?]{0,65}"
    r"\b(?:cut|trim|reduction|easing|shortening)\b",
    re.IGNORECASE,
)

CUT_REPLY_INSTRUCTION = (
    "For this question the app will prepend this source-checked first sentence "
    "to your final answer: {opening} Write only the remaining explanation, "
    "in at most 85 words and two or three short sentences. Mark wants a "
    "real-world training reason, not a description of software rules. Explain "
    "what the observed pattern supports and say plainly when it does not "
    "justify the exact size of both the duration and intensity cuts. Avoid "
    "engine, gate, guardrail, weighting and other internal-process language. "
    "Do not repeat or contradict the duration figures, minimise the size of "
    "the cut, or imply that the proposed change was approved or uploaded. "
    "Keep the computed call and pass-on rules."
)


def source_backed_cut_opening(question: str, app_state: Mapping[str, Any]) -> str | None:
    """Use exactly one same-day adjusted session, or leave the reply untouched."""
    if not (_CUT_TOPIC.search(question) and _CHALLENGE.search(question)):
        return None
    if _PAST_SESSION.search(question):
        return None
    today = app_state.get("todayLocalDate")
    origin = app_state.get("conversationOpenedFrom")
    if not isinstance(today, str) or not isinstance(origin, Mapping):
        return None
    if origin.get("subjectDate") != today:
        return None
    recent = app_state.get("recentMornings")
    days = recent.get("days") if isinstance(recent, Mapping) else None
    if not isinstance(days, list):
        return None
    matches = [day for day in days if isinstance(day, Mapping) and day.get("date") == today]
    if len(matches) != 1 or matches[0].get("morningRead") is not True:
        return None
    sessions = matches[0].get("sessions")
    if not isinstance(sessions, list):
        return None
    adjusted = [
        item
        for item in sessions
        if isinstance(item, Mapping) and item.get("morningCall") == "adjusted"
    ]
    if len(adjusted) != 1:
        return None
    session = adjusted[0]
    planned = session.get("planned")
    changed = session.get("adjusted")
    if not isinstance(planned, Mapping) or not isinstance(changed, Mapping):
        return None
    before, after = planned.get("durationMin"), changed.get("durationMin")
    if not (type(before) is int and type(after) is int and 0 < after < before):
        return None
    removed = before - after
    quoted_durations = _DURATION_QUOTE.findall(question)
    # A quoted duration could name the session rather than the size of its
    # reduction, so the difference alone is not enough to identify the ride.
    if any(int(value) not in {before, after} for value in quoted_durations):
        return None
    percent = (removed * 100 + before // 2) // before
    return (
        "You're right to question the size: the morning proposed shortening "
        f"your session from {before} to {after} minutes, a {removed}-minute "
        f"cut ({percent}% of the planned time)."
    )


def compose_source_backed_cut_answer(answer: str, opening: str | None) -> str:
    """Put the checked facts first; reject a contradictory size judgement."""
    if opening is None:
        return answer
    remaining = answer.strip()
    if not remaining or _MINIMISED_CUT.search(remaining):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The coach couldn't answer just now. Please try again in a moment.",
        )
    if remaining.startswith(opening):
        return remaining
    return f"{opening} {remaining}"
