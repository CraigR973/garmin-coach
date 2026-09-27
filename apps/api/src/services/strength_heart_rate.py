"""A strength session's heart rate, read against Mark's own range for that workout (Batch 288).

On three consecutive Daily Bodyweight Workouts the post-strength read called a peak
of 96 bpm "modest and unremarkable" (22 Sep 2026), 98 bpm "a normal, unremarkable
range" (23 Sep), then 96 bpm "a notably high relative bump" (24 Sep). The packet held
that session's figures and nothing else, so each read invented its own yardstick —
on 24 Sep, the gap to resting heart rate, which had been larger on the day called
modest. Mark checked Garmin (his usual peak for the workout is 94–100) and the coach
conceded twice.

This module hands the model the comparison instead: the same workout's recent range
and a deterministic classification of today against it. The prompt may describe
heart rate only through that classification.

**The rule, chosen from Mark's 136 stored strength sessions at ``/batch-start``:**
the usual range for a metric is the lowest to the highest of his last
:data:`USUAL_RANGE_SESSIONS` sessions of the same workout inside the last
:data:`USUAL_RANGE_LOOKBACK_DAYS` days, and it exists only when at least
:data:`USUAL_RANGE_MIN_SESSIONS` of them carry that reading.

* **Lowest-to-highest, not a trimmed or statistical band**, because Mark reconciles
  figures against Garmin. "96 sat within 92–100 over your last 10 sessions" is
  something he can check session by session; a percentile band is not, and trimming
  the extremes classified more ordinary sessions as outside (32 of 113 peaks against
  14 of 113, replayed over every stored session).
* **No tolerance around the range**, for the same reason: a value classified
  ``within_usual`` is always literally inside the range the read quotes. How far
  outside a value sits travels as ``bpmOutsideUsual`` instead, so a 1 bpm excursion
  is reported as 1 bpm rather than as a bare "above".
* **Ten sessions within twelve weeks.** Ten is two weeks of the daily workout and
  ten weeks of a weekly one; the twelve-week window is the consistency read's own
  (``WINDOW_12W_DAYS``), so the rows are already loaded and a range never rests on
  a workout he stopped doing months ago. Replayed, it puts 22, 23 and 24 Sep all
  within usual, and 14 Sep (average 90 against 80–86, peak 100 against 87–97) above.
* **At least five**, so a workout he has done twice has no "usual" yet. Below that
  the classification is ``no_usual_range`` and the read gives the figures without
  calling them anything.

A peak far above the range is more often a wrist-sensor spike than effort — the
stored history has peaks of 141, 146 and 163 bpm on sessions averaging 77–98. The
classification reports it; it does not decide it is real. Advisory only, like the
rest of the strength read (#49): nothing here feeds a verdict or a recovery decision.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.services.strength_brief import WINDOW_12W_DAYS

USUAL_RANGE_SESSIONS = 10
USUAL_RANGE_MIN_SESSIONS = 5
USUAL_RANGE_LOOKBACK_DAYS = WINDOW_12W_DAYS

WITHIN_USUAL = "within_usual"
ABOVE_USUAL = "above_usual"
BELOW_USUAL = "below_usual"
NO_USUAL_RANGE = "no_usual_range"
NO_READING = "no_reading"

USUAL_RANGE_RULE = (
    f"Usual range = the lowest to the highest of his last {USUAL_RANGE_SESSIONS} sessions "
    f"of this same workout in the last {USUAL_RANGE_LOOKBACK_DAYS} days, needing at least "
    f"{USUAL_RANGE_MIN_SESSIONS}. within_usual = inside that range; above_usual or "
    "below_usual = outside it, by bpmOutsideUsual; no_usual_range = too few earlier "
    "sessions to compare with; no_reading = this session recorded no value."
)


@dataclass(frozen=True, slots=True)
class StrengthHeartRateSample:
    """The typed columns one strength session contributes to the comparison."""

    activity_id: uuid.UUID | None
    activity_name: str | None
    start_utc: datetime
    avg_heart_rate_bpm: int | None
    max_heart_rate_bpm: int | None


def workout_key(activity_name: str | None) -> str | None:
    """The name two sessions must share to be the same workout.

    Whitespace and case are Garmin noise, not a different workout — one stored name
    ends in a trailing space. Anything else, including a bracketed note appended to
    the name, is a different workout and gets its own range.
    """

    if activity_name is None:
        return None
    key = " ".join(activity_name.split()).casefold()
    return key or None


def same_workout_history(
    today: StrengthHeartRateSample,
    sessions: Sequence[StrengthHeartRateSample],
) -> list[StrengthHeartRateSample]:
    """The earlier sessions of today's workout that the range is drawn from, oldest first."""

    key = workout_key(today.activity_name)
    if key is None:
        return []
    earliest = today.start_utc - timedelta(days=USUAL_RANGE_LOOKBACK_DAYS)
    earlier = sorted(
        (
            session
            for session in sessions
            if workout_key(session.activity_name) == key
            and session.activity_id != today.activity_id
            and earliest <= session.start_utc < today.start_utc
        ),
        key=lambda session: session.start_utc,
    )
    return earlier[-USUAL_RANGE_SESSIONS:]


def _metric_against_usual(
    today_bpm: int | None,
    history: Sequence[StrengthHeartRateSample],
    reading: Callable[[StrengthHeartRateSample], int | None],
) -> dict[str, Any]:
    values = [value for value in (reading(session) for session in history) if value is not None]
    low = min(values) if len(values) >= USUAL_RANGE_MIN_SESSIONS else None
    high = max(values) if len(values) >= USUAL_RANGE_MIN_SESSIONS else None
    outside: int | None = None
    if today_bpm is None:
        classification = NO_READING
    elif low is None or high is None:
        classification = NO_USUAL_RANGE
    elif today_bpm > high:
        classification, outside = ABOVE_USUAL, today_bpm - high
    elif today_bpm < low:
        classification, outside = BELOW_USUAL, low - today_bpm
    else:
        classification = WITHIN_USUAL
    return {
        "todayBpm": today_bpm,
        "usualLowBpm": low,
        "usualHighBpm": high,
        "sessionsCompared": len(values),
        "classification": classification,
        "bpmOutsideUsual": outside,
    }


def usual_range_review(
    today: StrengthHeartRateSample,
    sessions: Sequence[StrengthHeartRateSample],
) -> dict[str, Any]:
    """Today's average and peak heart rate against his own range for this workout."""

    history = same_workout_history(today, sessions)
    return {
        "workoutName": today.activity_name,
        "sessionsInRange": len(history),
        "firstSessionUtc": history[0].start_utc.isoformat() if history else None,
        "lastSessionUtc": history[-1].start_utc.isoformat() if history else None,
        "averageHeartRate": _metric_against_usual(
            today.avg_heart_rate_bpm, history, lambda session: session.avg_heart_rate_bpm
        ),
        "peakHeartRate": _metric_against_usual(
            today.max_heart_rate_bpm, history, lambda session: session.max_heart_rate_bpm
        ),
        "rule": USUAL_RANGE_RULE,
    }
