"""Batch 288 — a usual heart rate is not a high one.

The fixtures are Mark's own stored strength sessions (production, read 2026-09-25):
start time, name, average and peak heart rate, exactly as Garmin recorded them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from src.services.coach_policy import PACKET_FIELD_NAMES_RULE
from src.services.post_strength_analysis import SYSTEM_PROMPT
from src.services.strength_heart_rate import (
    ABOVE_USUAL,
    BELOW_USUAL,
    NO_READING,
    NO_USUAL_RANGE,
    USUAL_RANGE_LOOKBACK_DAYS,
    USUAL_RANGE_MIN_SESSIONS,
    USUAL_RANGE_SESSIONS,
    WITHIN_USUAL,
    StrengthHeartRateSample,
    same_workout_history,
    usual_range_review,
    workout_key,
)

DAILY = "Daily Bodyweight Workout"
WEEKLY = "Weekly Bodyweight Workout"
DUMBBELL = "Dumbbell Workout"

# (start UTC, name, average bpm, peak bpm) — every strength session since 17 Aug 2026.
MARK_SESSIONS: list[tuple[str, str, int, int]] = [
    ("2026-08-17T15:40:27", DUMBBELL, 78, 101),
    ("2026-08-22T07:48:59", "Recovery Morning Routine", 90, 106),
    ("2026-08-23T08:17:54", DAILY, 79, 89),
    ("2026-08-24T08:53:15", DAILY, 80, 91),
    ("2026-08-24T11:29:11", DUMBBELL, 78, 98),
    ("2026-08-25T07:40:55", DAILY, 84, 97),
    ("2026-08-26T08:52:32", DAILY, 83, 92),
    ("2026-08-27T07:43:47", DAILY, 80, 87),
    ("2026-08-29T07:52:12", WEEKLY, 94, 108),
    ("2026-08-31T07:47:54", DAILY, 80, 93),
    ("2026-08-31T09:49:14", DUMBBELL, 82, 107),
    ("2026-09-01T08:28:04", DAILY, 80, 93),
    ("2026-09-02T08:24:03", DAILY, 84, 95),
    ("2026-09-03T07:50:28", DAILY, 81, 94),
    ("2026-09-04T07:50:55", DAILY, 83, 91),
    ("2026-09-05T07:35:21", WEEKLY, 90, 109),
    ("2026-09-06T07:42:39", DAILY, 82, 91),
    ("2026-09-08T07:48:42", DAILY, 86, 97),
    ("2026-09-09T07:53:19", DAILY, 82, 93),
    ("2026-09-09T09:49:11", DUMBBELL, 84, 102),
    ("2026-09-10T07:44:49", DAILY, 81, 92),
    ("2026-09-12T07:53:47", WEEKLY, 87, 101),
    ("2026-09-14T08:06:54", DAILY, 90, 100),
    ("2026-09-14T10:25:27", DUMBBELL, 82, 102),
    ("2026-09-15T08:55:58", DAILY, 83, 95),
    ("2026-09-17T08:46:43", DAILY, 84, 94),
    ("2026-09-18T08:47:41", DAILY, 83, 94),
    ("2026-09-19T07:50:24", WEEKLY, 91, 109),
    ("2026-09-20T09:06:28", DAILY, 85, 100),
    ("2026-09-22T08:09:22", DAILY, 86, 96),
    ("2026-09-23T08:01:00", DAILY, 86, 98),
    ("2026-09-24T08:12:10", DAILY, 84, 96),
]


def _sample(
    start: str, name: str | None, avg: int | None, peak: int | None
) -> StrengthHeartRateSample:
    return StrengthHeartRateSample(
        activity_id=uuid.uuid4(),
        activity_name=name,
        start_utc=datetime.fromisoformat(start),
        avg_heart_rate_bpm=avg,
        max_heart_rate_bpm=peak,
    )


SESSIONS = [_sample(*row) for row in MARK_SESSIONS]


def _session_on(prefix: str, name: str = DAILY) -> StrengthHeartRateSample:
    return next(
        s
        for s in SESSIONS
        if s.start_utc.isoformat().startswith(prefix) and s.activity_name == name
    )


def test_the_rule_is_the_one_chosen_from_his_sessions() -> None:
    assert (USUAL_RANGE_SESSIONS, USUAL_RANGE_MIN_SESSIONS, USUAL_RANGE_LOOKBACK_DAYS) == (
        10,
        5,
        84,
    )


def test_24_sep_is_within_his_usual_range_for_the_workout() -> None:
    """The read that called 96 bpm "a notably high relative bump" (288.5)."""

    review = usual_range_review(_session_on("2026-09-24"), SESSIONS)

    assert review["workoutName"] == DAILY
    assert review["sessionsInRange"] == 10
    # 8 Sep … 23 Sep — which includes the 22 and 23 Sep sessions it was called worse than.
    assert review["firstSessionUtc"] == "2026-09-08T07:48:42"
    assert review["lastSessionUtc"] == "2026-09-23T08:01:00"
    assert review["averageHeartRate"] == {
        "todayBpm": 84,
        "usualLowBpm": 81,
        "usualHighBpm": 90,
        "sessionsCompared": 10,
        "classification": WITHIN_USUAL,
        "bpmOutsideUsual": None,
    }
    assert review["peakHeartRate"] == {
        "todayBpm": 96,
        "usualLowBpm": 92,
        "usualHighBpm": 100,
        "sessionsCompared": 10,
        "classification": WITHIN_USUAL,
        "bpmOutsideUsual": None,
    }


@pytest.mark.parametrize("day", ["2026-09-22", "2026-09-23", "2026-09-24"])
def test_replaying_22_to_24_sep_gives_within_usual_for_all_three(day: str) -> None:
    review = usual_range_review(_session_on(day), SESSIONS)

    assert review["averageHeartRate"]["classification"] == WITHIN_USUAL
    assert review["peakHeartRate"]["classification"] == WITHIN_USUAL


def test_a_genuinely_higher_session_is_above_usual_and_says_by_how_much() -> None:
    """14 Sep: his highest average for the workout, and a peak above the prior ten."""

    review = usual_range_review(_session_on("2026-09-14"), SESSIONS)

    assert review["averageHeartRate"]["classification"] == ABOVE_USUAL
    assert (
        review["averageHeartRate"]["usualLowBpm"],
        review["averageHeartRate"]["usualHighBpm"],
    ) == (80, 86)
    assert review["averageHeartRate"]["bpmOutsideUsual"] == 4
    assert review["peakHeartRate"]["classification"] == ABOVE_USUAL
    assert (review["peakHeartRate"]["usualLowBpm"], review["peakHeartRate"]["usualHighBpm"]) == (
        87,
        97,
    )
    assert review["peakHeartRate"]["bpmOutsideUsual"] == 3


def test_a_session_below_the_range_is_below_usual() -> None:
    today = _sample("2026-09-25T08:00:00", DAILY, 78, 88)

    review = usual_range_review(today, SESSIONS)

    assert review["averageHeartRate"]["classification"] == BELOW_USUAL
    assert review["averageHeartRate"]["bpmOutsideUsual"] == 81 - 78
    assert review["peakHeartRate"]["classification"] == BELOW_USUAL
    assert review["peakHeartRate"]["bpmOutsideUsual"] == 92 - 88


def test_a_value_on_the_edge_of_the_range_is_within_it() -> None:
    today = _sample("2026-09-25T08:00:00", DAILY, 90, 92)

    review = usual_range_review(today, SESSIONS)

    assert review["averageHeartRate"]["classification"] == WITHIN_USUAL
    assert review["peakHeartRate"]["classification"] == WITHIN_USUAL


def test_fewer_than_five_earlier_sessions_has_no_usual_range() -> None:
    """The weekly workout has four sessions; the fifth is compared with nothing yet."""

    today = _sample("2026-09-26T07:50:00", WEEKLY, 99, 125)

    review = usual_range_review(today, SESSIONS)

    assert review["sessionsInRange"] == 4
    for metric in ("averageHeartRate", "peakHeartRate"):
        assert review[metric]["classification"] == NO_USUAL_RANGE
        assert review[metric]["usualLowBpm"] is None
        assert review[metric]["usualHighBpm"] is None
        assert review[metric]["bpmOutsideUsual"] is None
        assert review[metric]["sessionsCompared"] == 4


def test_other_workouts_never_enter_the_range() -> None:
    """A weekly session peaking at 109 must not widen the daily workout's range."""

    history = same_workout_history(_session_on("2026-09-24"), SESSIONS)

    assert {s.activity_name for s in history} == {DAILY}
    assert max(s.max_heart_rate_bpm or 0 for s in history) == 100


def test_only_the_last_ten_earlier_sessions_inside_twelve_weeks_count() -> None:
    today = _session_on("2026-09-24")
    later = _sample("2026-09-24T18:00:00", DAILY, 120, 150)
    ancient = _sample("2026-06-01T08:00:00", DAILY, 60, 70)

    history = same_workout_history(today, [*SESSIONS, later, ancient])

    assert len(history) == 10
    assert today not in history
    assert later not in history
    assert ancient not in history
    assert history == sorted(history, key=lambda s: s.start_utc)


def test_a_workout_outside_the_lookback_has_no_usual_range() -> None:
    old = [_sample(f"2026-05-{day:02d}T08:00:00", DUMBBELL, 78, 100) for day in range(1, 11)]
    today = _sample("2026-09-25T08:00:00", DUMBBELL, 80, 104)

    review = usual_range_review(today, old)

    assert review["sessionsInRange"] == 0
    assert review["peakHeartRate"]["classification"] == NO_USUAL_RANGE


def test_whitespace_and_case_do_not_make_a_different_workout() -> None:
    assert workout_key("Dumbbell Workout ") == workout_key("dumbbell  workout")
    assert workout_key("Dumbbell Workout [SEE NOTES] ") != workout_key("Dumbbell Workout")
    assert workout_key("   ") is None
    assert workout_key(None) is None


def test_an_unnamed_session_has_no_usual_range() -> None:
    history = [_sample(f"2026-09-{day:02d}T08:00:00", None, 80, 95) for day in range(1, 11)]
    today = _sample("2026-09-25T08:00:00", None, 80, 95)

    review = usual_range_review(today, history)

    assert review["sessionsInRange"] == 0
    assert review["averageHeartRate"]["classification"] == NO_USUAL_RANGE


def test_a_missing_reading_is_reported_as_missing() -> None:
    today = _sample("2026-09-25T08:00:00", DAILY, None, 96)

    review = usual_range_review(today, SESSIONS)

    assert review["averageHeartRate"]["classification"] == NO_READING
    assert review["averageHeartRate"]["todayBpm"] is None
    assert review["peakHeartRate"]["classification"] == WITHIN_USUAL


def test_history_missing_a_reading_counts_only_the_sessions_that_have_it() -> None:
    history = [_sample(f"2026-09-{day:02d}T08:00:00", DAILY, 82, None) for day in range(10, 20)]
    history[:4] = [_sample(f"2026-09-{day:02d}T08:00:00", DAILY, 82, 95) for day in range(10, 14)]
    today = _sample("2026-09-25T08:00:00", DAILY, 82, 96)

    review = usual_range_review(today, history)

    assert review["averageHeartRate"]["sessionsCompared"] == 10
    assert review["averageHeartRate"]["classification"] == WITHIN_USUAL
    assert review["peakHeartRate"]["sessionsCompared"] == 4
    assert review["peakHeartRate"]["classification"] == NO_USUAL_RANGE


def test_the_prompt_describes_heart_rate_only_through_the_classification() -> None:
    """288.3: never high or low on its own reading; the old invitation is gone."""

    prompt = " ".join(SYSTEM_PROMPT.split())
    assert "heartRateReview.usualRange" in prompt
    for classification in (WITHIN_USUAL, ABOVE_USUAL, BELOW_USUAL, NO_USUAL_RANGE, NO_READING):
        assert f"`{classification}`" in prompt
    assert "bpmOutsideUsual" in prompt
    assert (
        "Never call his heart rate high, low, elevated, notable, modest or unremarkable on "
        "your own reading" in prompt
    )
    assert "never judge it against resting heart rate" in prompt
    assert "unusually high" not in prompt
    # The rule names classification values; none of them is a word for Mark.
    assert PACKET_FIELD_NAMES_RULE in SYSTEM_PROMPT
