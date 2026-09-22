"""Batch 271 — a moved goalpost, noticed by us instead of by Mark.

Every row in ``PRODUCTION_SERIES`` was read from ``coach.daily_metrics`` on
2026-09-22, morning phase, and is the exact sequence behind the two Reds Mark
spent three mornings arguing about. Read it downward and the shape is plain:

    date   overnight  weekly  floor  ceiling  status
    16 Sep     44       47      45      56    BALANCED
    17 Sep     43       45      45      56    BALANCED
    18 Sep     48       45      46      56    UNBALANCED  <- Red
    19 Sep     45       45      46      56    UNBALANCED  <- Red
    20 Sep     46       45      45      55    BALANCED
    21 Sep     37       44      45      55    UNBALANCED  <- genuine
    22 Sep     39       43      45      55    UNBALANCED  <- genuine

The floor rose for exactly two days and came back. On 18 September his overnight
HRV was 48 ms — his highest in six days and *above* the raised floor — and the
morning was Red anyway.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from statistics import median

from src.models.coaching import DailyMetric
from src.services.hrv_recalibration import (
    BAND_REFERENCE_WINDOW_DAYS,
    MIN_REFERENCE_SAMPLES,
    READING_REFERENCE_WINDOW_DAYS,
    detect_hrv_recalibration,
    is_band_artifact,
)

USER_ID = uuid.uuid4()

# (day, overnight, weekly, floor, ceiling), exactly as production holds them.
#
# **This series runs from 28 August deliberately, and the reason is a bug this
# file shipped once.** The first version started on 10 September — shorter than
# the 14-day band reference window — so every unit test silently exercised a
# truncated history while production exercised a full one. The two disagreed:
# unit tests said 19 September was a recalibration, production said his reading
# had moved. The production smoke caught it, the unit suite could not have.
# **A fixture must be at least as long as the longest window the code reads.**
PRODUCTION_SERIES: tuple[tuple[date, int, int, int, int], ...] = (
    (date(2026, 8, 28), 43, 49, 44, 56),
    (date(2026, 8, 29), 48, 48, 44, 56),
    (date(2026, 8, 30), 44, 47, 44, 56),
    (date(2026, 8, 31), 47, 47, 44, 56),
    (date(2026, 9, 1), 44, 46, 44, 56),
    (date(2026, 9, 2), 50, 46, 44, 56),
    (date(2026, 9, 3), 51, 47, 44, 56),
    (date(2026, 9, 4), 54, 48, 44, 56),
    (date(2026, 9, 5), 51, 49, 44, 56),
    (date(2026, 9, 6), 49, 49, 44, 56),
    (date(2026, 9, 7), 48, 49, 44, 56),
    (date(2026, 9, 8), 43, 49, 44, 56),
    (date(2026, 9, 9), 49, 49, 44, 56),
    (date(2026, 9, 10), 51, 49, 44, 56),
    (date(2026, 9, 11), 52, 49, 45, 56),
    (date(2026, 9, 12), 48, 48, 45, 56),
    (date(2026, 9, 13), 42, 47, 45, 56),
    (date(2026, 9, 14), 47, 47, 45, 56),
    (date(2026, 9, 15), 42, 47, 45, 56),
    (date(2026, 9, 16), 44, 47, 45, 56),
    (date(2026, 9, 17), 43, 45, 45, 56),
    (date(2026, 9, 18), 48, 45, 46, 56),
    (date(2026, 9, 19), 45, 45, 46, 56),
    (date(2026, 9, 20), 46, 45, 45, 55),
    (date(2026, 9, 21), 37, 44, 45, 55),
    (date(2026, 9, 22), 39, 43, 45, 55),
)


def _row(day: date, overnight: int, weekly: int, floor: int, ceiling: int) -> DailyMetric:
    return DailyMetric(
        user_id=USER_ID,
        calendar_date=day,
        phase="morning",
        hrv_last_night_avg_ms=overnight,
        hrv_weekly_avg_ms=weekly,
        hrv_baseline_low_ms=floor,
        hrv_baseline_high_ms=ceiling,
    )


def _rows() -> list[DailyMetric]:
    return [_row(*entry) for entry in PRODUCTION_SERIES]


def _event_on(day: date) -> dict:
    rows = _rows()
    subject = next(row for row in rows if row.calendar_date == day)
    history = [row for row in rows if row.calendar_date < day]
    return detect_hrv_recalibration(subject, history)


def test_the_two_disputed_mornings_are_the_only_recalibrations() -> None:
    """16-22 Sep: an artifact on 18 and 19, and on no other day.

    This is 271's acceptance criterion, and it is asserted over the full
    production history rather than a truncated one - see PRODUCTION_SERIES.
    """
    flagged = [
        day
        for day, *_ in PRODUCTION_SERIES
        if day >= date(2026, 9, 16) and is_band_artifact(_event_on(day))
    ]
    assert flagged == [date(2026, 9, 18), date(2026, 9, 19)]


def test_the_eighteenth_names_the_movement_and_the_held_reading() -> None:
    event = _event_on(date(2026, 9, 18))
    assert event["status"] == "recalibrated"
    assert event["source"] == "garmin_supplied_band"
    # Values pinned to what production returns on Mark's real rows.
    assert event["bandLow"]["currentMs"] == 46.0
    assert event["bandLow"]["referenceMs"] == 44.5
    assert event["bandLow"]["deltaMs"] == 1.5
    assert event["bandLow"]["sampleCount"] == BAND_REFERENCE_WINDOW_DAYS
    # His reading did not merely hold, it rose — 48 ms against a trailing 44.
    assert event["overnightReading"]["currentMs"] == 48.0
    assert event["overnightReading"]["referenceMs"] == 44.0
    assert event["overnightReading"]["deltaMs"] == 4.0
    assert event["overnightReading"]["sampleCount"] == READING_REFERENCE_WINDOW_DAYS
    assert "did not" in event["reason"]


def test_the_nineteenth_is_caught_although_the_floor_did_not_move_that_day() -> None:
    """The floor went 45 -> 46 on the 18th and *stayed* 46 on the 19th.

    A day-over-day detector sees one movement and calls the 19th normal. The
    19th is the second Red. This is why the comparison is against a trailing
    reference rather than against yesterday.
    """
    by_date = {row.calendar_date: row for row in _rows()}
    assert (
        by_date[date(2026, 9, 18)].hrv_baseline_low_ms
        == by_date[date(2026, 9, 19)].hrv_baseline_low_ms
        == 46
    )
    event = _event_on(date(2026, 9, 19))
    assert event["status"] == "recalibrated"
    assert event["bandLow"]["referenceMs"] == 45.0
    assert event["bandLow"]["deltaMs"] == 1.0


def test_a_moved_ceiling_alone_is_not_an_artifact() -> None:
    """20 Sep: ceiling 56 -> 55, floor holds at 45, reading holds at 46.

    The Red rule compares against the floor, so a falling ceiling cannot have
    caused a Red and must not suppress one.
    """
    event = _event_on(date(2026, 9, 20))
    assert event["status"] == "no_movement"
    assert not is_band_artifact(event)
    assert event["bandHigh"]["deltaMs"] == -1.0
    assert "ceiling" in event["reason"]


def test_a_genuine_crash_against_a_steady_floor_is_not_an_artifact() -> None:
    """21 Sep: overnight 37 ms, floor unmoved at 45. This Red is real."""
    event = _event_on(date(2026, 9, 21))
    assert event["status"] == "no_movement"
    assert not is_band_artifact(event)
    assert event["overnightReading"]["currentMs"] == 37.0


def test_the_twenty_second_is_also_left_alone() -> None:
    event = _event_on(date(2026, 9, 22))
    assert not is_band_artifact(event)


def test_a_missing_history_is_unknown_never_no_movement() -> None:
    """An absent history is not evidence of a stable band."""
    rows = _rows()
    subject = next(row for row in rows if row.calendar_date == date(2026, 9, 18))
    thin = [row for row in rows if row.calendar_date < date(2026, 9, 18)][
        : MIN_REFERENCE_SAMPLES - 1
    ]
    event = detect_hrv_recalibration(subject, thin)
    assert event["status"] == "unknown"
    assert not is_band_artifact(event)

    assert detect_hrv_recalibration(None, rows)["status"] == "unknown"


def test_a_band_that_moves_with_the_man_is_not_an_artifact() -> None:
    """The distinguishing test, stated as its own case.

    Same floor movement as 18 September, but his overnight reading falls with it.
    Suppressing that would be suppressing a real signal.
    """
    history = [_row(date(2026, 9, 10 + i), 48, 48, 45, 56) for i in range(8)]
    subject = _row(date(2026, 9, 18), 38, 45, 46, 56)
    event = detect_hrv_recalibration(subject, history)
    assert event["status"] == "band_and_reading_moved"
    assert not is_band_artifact(event)


def test_a_reading_just_inside_tolerance_still_counts_as_held() -> None:
    """The tolerance is exercised directly, not via a day that happens to sit in it.

    On the real series both artifact days sit *above* their reading reference, so
    nothing in the production data probes this boundary. A synthetic case does.
    """
    history = [_row(date(2026, 9, 4 + i), 46, 47, 45, 56) for i in range(14)]
    inside = _row(date(2026, 9, 18), 44, 45, 46, 56)  # 2 ms under a median of 46
    assert detect_hrv_recalibration(inside, history)["status"] == "recalibrated"

    outside = _row(date(2026, 9, 18), 43, 45, 46, 56)  # 3 ms under
    assert detect_hrv_recalibration(outside, history)["status"] == "band_and_reading_moved"


def test_the_reading_reference_is_shorter_than_the_bands_and_that_is_load_bearing() -> None:
    """A long reading window cannot fire during a drift, which is when it must.

    Mark's overnight HRV declined for a fortnight while Garmin's floor stepped
    up. Measured over 14 days his 19 September reading sits ~3 ms under its
    median purely because of that drift, so the detector calls a genuine band
    artifact a real deterioration and stays silent for the entire period a
    vendor recalibration is most likely. Over 7 days the same reading is *above*
    its median, which is the true answer to the acute question.
    """
    assert READING_REFERENCE_WINDOW_DAYS < BAND_REFERENCE_WINDOW_DAYS

    event = _event_on(date(2026, 9, 19))
    assert event["status"] == "recalibrated"
    assert event["readingReferenceWindowDays"] == READING_REFERENCE_WINDOW_DAYS
    assert event["overnightReading"]["deltaMs"] is not None
    assert event["overnightReading"]["deltaMs"] >= 0

    # The same day, judged against the band's longer window, inverts.
    rows = _rows()
    subject = next(r for r in rows if r.calendar_date == date(2026, 9, 19))
    long_history = [
        r
        for r in rows
        if date(2026, 9, 19) - timedelta(days=BAND_REFERENCE_WINDOW_DAYS)
        <= r.calendar_date
        < date(2026, 9, 19)
    ]
    long_median = median(
        float(r.hrv_last_night_avg_ms) for r in long_history if r.hrv_last_night_avg_ms is not None
    )
    assert float(subject.hrv_last_night_avg_ms or 0) < long_median - 2.0
