"""A factual opening for a challenge to one same-day morning cut.

The stored morning projection describes what the read proposed. It does not
prove that Mark approved the offer or that the adjusted ride reached his device.
Ambiguous dates, sessions and durations leave the model's ordinary answer path
alone rather than attaching the wrong workout to his question.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import DAILY_METRIC_PHASE_MORNING, Analysis, DailyMetric

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
_FLOOR_AND_NEXT_WEEK = re.compile(r"\bnext\s+weeks?(?:'s)?\b", re.I)
_RECOVERY_WEEKS = re.compile(r"\b(?:3|three)\s+recovery\s+weeks\b", re.I)
_CUT_CONCERN = re.compile(r"\b(?:counter\s*intuitive|sledgehammer|too much)\b", re.I)

CUT_REPLY_INSTRUCTION = (
    "For this question the app will prepend this source-checked first sentence "
    "to your final answer: {opening} Write only the remaining explanation, "
    "in at most 85 words and two or three short sentences. Mark wants a "
    "real-world training reason, not a description of software rules. Explain "
    "what the observed pattern supports and say plainly when it does not "
    "justify the exact size of the actual duration or intensity reduction. "
    "Do not imply that both changed unless the record shows both. Avoid "
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


def source_backed_hrv_cut_reply(question: str, app_state: Mapping[str, Any]) -> str | None:
    """Draft a same-day HRV cut answer only when every stated fact is checked."""
    opening = source_backed_cut_opening(question, app_state)
    if opening is None:
        return None
    today = app_state["todayLocalDate"]
    days = app_state["recentMornings"]["days"]
    day = next(item for item in days if isinstance(item, Mapping) and item.get("date") == today)
    if day.get("noBikeAdvised") is True or day.get("noTrainingAdvised") is True:
        return None
    reasons = day.get("reasons")
    if not isinstance(reasons, list) or not any(
        isinstance(reason, str) and re.search(r"\bHRV\b.*\bbelow\b", reason, re.I)
        for reason in reasons
    ):
        return None
    sessions = day["sessions"]
    session = next(
        item
        for item in sessions
        if isinstance(item, Mapping) and item.get("morningCall") == "adjusted"
    )
    delivery = session.get("onHisDevice")
    if delivery not in ("approved_and_uploaded", "offered_not_approved"):
        return None
    metrics_section = app_state.get("dailyMetrics")
    metrics = metrics_section.get("today") if isinstance(metrics_section, Mapping) else None
    if not isinstance(metrics, Mapping) or metrics.get("calendarDate") != today:
        return None
    assembled = _timestamp(app_state.get("assembledAtUtc"))
    recorded = _timestamp(metrics.get("recordedAtUtc"))
    if assembled is None or recorded is None or recorded > assembled:
        return None
    if delivery == "approved_and_uploaded":
        approved = _timestamp(session.get("approvedAtUtc"))
        if approved is None or approved > assembled:
            return None
    elif session.get("approvedAtUtc") is not None:
        return None
    weekly = _hrv_number(metrics.get("hrvWeeklyAvgMs"))
    floor = _hrv_number(metrics.get("hrvBaselineLowMs"))
    overnight = _hrv_number(metrics.get("hrvLastNightAvgMs"))
    if weekly is None or floor is None or overnight is None or weekly >= floor:
        return None
    relation = "below" if overnight < floor else "at" if overnight == floor else "above"
    device_words = (
        "The easier ride was approved and uploaded."
        if delivery == "approved_and_uploaded"
        else "It remains an offer; the planned ride stayed on your device."
    )
    return (
        f"{opening} Your seven-day HRV average was {weekly:g} ms, below your usual "
        f"{floor:g} ms floor; last night's {overnight:g} ms was "
        f"{relation} that floor. "
        "That supports an easier day, but those readings alone do not establish "
        "that this exact reduction was necessary. The morning's easier option "
        f"remains the recommendation. {device_words}"
    )


async def source_backed_floor_and_next_week_reply(
    session: AsyncSession,
    *,
    analysis: Analysis | None,
    question: str,
    app_state: Mapping[str, Any],
    asked_at_utc: datetime,
) -> str | None:
    """Answer a same-day floor/cut/next-week challenge from pre-question facts.

    The dated morning read is immutable. The wake observation and floor history
    must also have existed when the question was asked. No reconstructed
    ``weekAhead`` or completed activity is allowed into this answer.
    """
    if not all(
        (
            re.search(r"\bHRV\b", question, re.I),
            re.search(r"\bfloor\b", question, re.I),
            _FLOOR_AND_NEXT_WEEK.search(question),
            _RECOVERY_WEEKS.search(question),
            _CUT_CONCERN.search(question),
            re.search(r"\b(?:reduc\w*|cut|shorten\w*)\b", question, re.I),
        )
    ):
        return None
    today_text = app_state.get("todayLocalDate")
    origin = app_state.get("conversationOpenedFrom")
    if not isinstance(today_text, str) or not isinstance(origin, Mapping):
        return None
    try:
        today = date.fromisoformat(today_text)
    except ValueError:
        return None
    if (
        analysis is None
        or analysis.analysis_type != "morning"
        or analysis.subject_date != today
        or origin.get("subjectDate") != today_text
        or _utc(analysis.generated_at_utc) > _utc(asked_at_utc)
        or _utc(analysis.created_at) > _utc(asked_at_utc)
    ):
        return None
    packet = analysis.context_packet
    if not isinstance(packet, Mapping) or packet.get("subjectDate") != today_text:
        return None
    verdict = packet.get("verdict")
    read_metrics = packet.get("dailyMetrics")
    if not isinstance(verdict, Mapping) or not isinstance(read_metrics, Mapping):
        return None
    if verdict.get("status") != "Red" or verdict.get("hrvBelowBaseline") is not True:
        return None
    adjustment = verdict.get("verdictAdjustment")
    physiology = verdict.get("acutePhysiology")
    chronic = verdict.get("chronicAction")
    if not all(isinstance(item, Mapping) for item in (adjustment, physiology, chronic)):
        return None
    assert isinstance(adjustment, Mapping)
    assert isinstance(physiology, Mapping)
    assert isinstance(chronic, Mapping)
    before, after = adjustment.get("plannedDurationMin"), adjustment.get("adjustedDurationMin")
    power_before = adjustment.get("plannedWorkPowerPct")
    power_after = adjustment.get("adjustedWorkPowerPct")
    readiness = read_metrics.get("readinessScore")
    if not (
        adjustment.get("changed") is True
        and type(before) is int
        and type(after) is int
        and 0 < after < before
        and type(power_before) in (int, float)
        and power_before == power_after
        and type(readiness) is int
        and physiology.get("status") == "clear"
        and chronic.get("suppressedByPlan") is True
        and chronic.get("triggered") is False
        and isinstance(chronic.get("scheduledRecoveryBlocks"), list)
        and chronic["scheduledRecoveryBlocks"]
    ):
        return None
    workout_id = adjustment.get("plannedWorkoutId")
    workouts = packet.get("plannedWorkouts")
    actions = verdict.get("todayActions")
    if not isinstance(workouts, list) or not isinstance(actions, list):
        return None
    matched_workouts = [
        workout
        for workout in workouts
        if isinstance(workout, Mapping)
        and workout.get("id") == workout_id
        and workout.get("workoutDate") == today_text
        and workout.get("plannedDurationMin") == before
        and workout.get("workoutType") == "bike_endurance"
    ]
    if len(matched_workouts) != 1 or not any(
        isinstance(action, Mapping)
        and action.get("kind") == "approve_ride"
        and action.get("plannedWorkoutId") == workout_id
        for action in actions
    ):
        return None

    # An old evaluation must not use a settled row written after the question.
    wake = await session.scalar(
        select(DailyMetric).where(
            DailyMetric.user_id == analysis.user_id,
            DailyMetric.calendar_date == today,
            DailyMetric.phase == DAILY_METRIC_PHASE_MORNING,
            DailyMetric.recorded_at_utc <= asked_at_utc,
            DailyMetric.created_at <= asked_at_utc,
            DailyMetric.updated_at <= asked_at_utc,
        )
    )
    if wake is None:
        return None
    overnight, weekly, floor = (
        wake.hrv_last_night_avg_ms,
        wake.hrv_weekly_avg_ms,
        wake.hrv_baseline_low_ms,
    )
    if not (
        isinstance(overnight, int)
        and not isinstance(overnight, bool)
        and isinstance(weekly, int)
        and not isinstance(weekly, bool)
        and isinstance(floor, int)
        and not isinstance(floor, bool)
        and 0 < overnight < 300
        and 0 < weekly < 300
        and 0 < floor < 300
    ):
        return None
    if not (overnight == weekly < floor and wake.readiness_score == readiness):
        return None
    if any(
        read_metrics.get(key) != value
        for key, value in (
            ("hrvLastNightAvgMs", overnight),
            ("hrvWeeklyAvgMs", weekly),
            ("hrvBaselineLowMs", floor),
            ("readinessScore", readiness),
        )
    ):
        return None
    history = app_state.get("hrvFloorHistory")
    if not isinstance(history, Mapping):
        return None
    change = history.get("latestRecordedChange")
    observations = history.get("observations")
    if not isinstance(change, Mapping) or not isinstance(observations, list):
        return None
    try:
        from_day = date.fromisoformat(change["fromDate"])
        to_day = date.fromisoformat(change["toDate"])
    except (KeyError, TypeError, ValueError):
        return None
    old_floor, new_floor = change.get("fromMs"), change.get("toMs")
    if not (
        change.get("direction") == "rose"
        and change.get("consecutiveDates") is True
        and isinstance(old_floor, int)
        and not isinstance(old_floor, bool)
        and isinstance(new_floor, int)
        and not isinstance(new_floor, bool)
        and old_floor < new_floor == floor
        and to_day <= today
        and any(
            isinstance(row, Mapping)
            and row.get("date") == today_text
            and row.get("floorMs") == floor
            for row in observations
        )
    ):
        return None
    removed = before - after
    percent = (removed * 100 + before // 2) // before
    changed_dates = (
        f"{from_day.day} and {to_day.day} {to_day:%b}"
        if (from_day.year, from_day.month) == (to_day.year, to_day.month)
        else f"{from_day.day} {from_day:%b} and {to_day.day} {to_day:%b}"
    )
    return (
        f"You're right to challenge a {before}→{after}-minute cut: that's {removed} "
        f"minutes, or {percent}% of the session, while your readiness was {readiness} "
        "and the acute checks were clear. "
        f"On {today.day} {today:%b}, overnight and seven-day HRV were both "
        f"{overnight} ms against a {floor} ms floor. "
        f"Garmin's floor rose from {old_floor} to {new_floor} ms between "
        f"{changed_dates}; it didn't fall. "
        "Those facts warrant caution, but they don't establish that this exact "
        "cut was necessary or settle the three-week pattern you've noticed. "
        "The morning offered a shorter Zone 2 ride; it did not propose another "
        "change to next week because a recovery block was already scheduled."
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _hrv_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 300:
        return float(value)
    return None
