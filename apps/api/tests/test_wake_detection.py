"""Unit tests for the pure wake-detection decision core (services/wake_detection).

The full back-to-sleep / nap / backstop matrix from
docs/designs/wake-triggered-morning.md. No I/O — these run without a database.
Europe/London is BST (UTC+1) on the test date, so a local wake of 08:00 maps to a
UTC-naive sleepEnd of 07:00.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from src.services.wake_detection import (
    BACKSTOP,
    DURATION_FLOOR_MIN,
    SETTLE_MIN,
    WINDOW_END,
    WINDOW_START,
    SleepReading,
    is_morning_ready,
)

LONDON = ZoneInfo("Europe/London")
TODAY = date(2026, 6, 24)


def _now(hour: int, minute: int = 0) -> datetime:
    """Timezone-aware local 'now' on the test date."""
    return datetime(2026, 6, 24, hour, minute, tzinfo=LONDON)


def _sleep_end(hour: int, minute: int = 0) -> datetime:
    """UTC-naive sleepEnd for a given Europe/London local wake time."""
    return datetime(2026, 6, 24, hour, minute, tzinfo=LONDON).astimezone(UTC).replace(tzinfo=None)


def _reading(
    sleep_end: datetime | None,
    *,
    duration_min: int | None = 480,
    day: date | None = TODAY,
) -> SleepReading:
    return SleepReading(calendar_date=day, sleep_end_utc=sleep_end, duration_min=duration_min)


# ---------------------------------------------------------------------------
# Calibration constants are locked to the spec (Mark's 363-night backfill)
# ---------------------------------------------------------------------------


def test_calibration_constants_match_spec() -> None:
    # Batch 138 / Decision #217: backstop moved 09:30 → 11:00, window-end 10:00 → 11:30
    # so a genuine lie-in isn't force-read before he is actually up.
    assert WINDOW_START == time(3, 30)
    assert WINDOW_END == time(11, 30)
    assert BACKSTOP == time(11, 0)
    assert DURATION_FLOOR_MIN == 180
    assert SETTLE_MIN == 20


# ---------------------------------------------------------------------------
# The decision matrix
# ---------------------------------------------------------------------------


def test_fires_on_stable_and_settled_wake() -> None:
    """Same sleepEnd as last poll + wake ≥ settle_min ago → fire, persist it."""
    sleep_end = _sleep_end(8, 0)  # 07:00 UTC
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(sleep_end),
        prev_sleep_end=sleep_end,
        now=_now(8, 25),  # 07:25 UTC → settled 25 min
    )
    assert decision.action == "fire"
    assert decision.reason == "stable_wake"
    assert decision.sleep_end_to_persist == sleep_end


def test_first_sighting_waits_and_persists_current() -> None:
    sleep_end = _sleep_end(8, 0)
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(sleep_end),
        prev_sleep_end=None,
        now=_now(8, 25),
    )
    assert decision.action == "wait"
    assert decision.reason == "awaiting_stability"
    assert decision.sleep_end_to_persist == sleep_end


def test_back_to_sleep_waits_and_persists_later_value() -> None:
    """A later sleepEnd than last poll means he drifted back to sleep — keep waiting."""
    prev = _sleep_end(6, 30)
    later = _sleep_end(7, 0)
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(later),
        prev_sleep_end=prev,
        now=_now(8, 25),
    )
    assert decision.action == "wait"
    assert decision.sleep_end_to_persist == later  # persist the later value


def test_stable_but_not_yet_settled_waits() -> None:
    """Same sleepEnd as last poll but the wake is too recent — wait for settle_min."""
    sleep_end = _sleep_end(8, 0)  # 07:00 UTC
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(sleep_end),
        prev_sleep_end=sleep_end,
        now=_now(8, 10),  # 07:10 UTC → only 10 min < settle_min
    )
    assert decision.action == "wait"
    assert decision.reason == "awaiting_stability"


def test_nap_below_floor_is_ignored() -> None:
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(_sleep_end(8, 0), duration_min=60),
        prev_sleep_end=None,
        now=_now(8, 25),
    )
    assert decision.action == "nap_ignored"
    assert decision.reason == "nap_below_floor"
    assert decision.sleep_end_to_persist is None  # don't pollute real-session tracking


def test_missing_duration_is_not_treated_as_a_nap() -> None:
    sleep_end = _sleep_end(8, 0)
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(sleep_end, duration_min=None),
        prev_sleep_end=None,
        now=_now(8, 25),
    )
    assert decision.action == "wait"
    assert decision.reason == "awaiting_stability"


def test_unfinalized_no_record_waits() -> None:
    decision = is_morning_ready(
        today=TODAY,
        sleep=None,
        prev_sleep_end=None,
        now=_now(5, 0),  # in window, before backstop
    )
    assert decision.action == "wait"
    assert decision.reason == "unfinalized"
    assert decision.sleep_end_to_persist is None


def test_unfinalized_missing_sleep_end_waits() -> None:
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(None),  # session present but no sleepEnd yet
        prev_sleep_end=None,
        now=_now(5, 0),
    )
    assert decision.action == "wait"
    assert decision.reason == "unfinalized"


def test_sleep_for_a_prior_date_is_not_today() -> None:
    """A stale record for yesterday must not be read as today's wake."""
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(_sleep_end(7, 0), day=date(2026, 6, 23)),
        prev_sleep_end=None,
        now=_now(8, 25),
    )
    assert decision.action == "wait"
    assert decision.reason == "unfinalized"


def test_future_sleep_end_is_not_yet_finalized() -> None:
    """A sleepEnd in the future (clock skew) is not finalized — wait."""
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(_sleep_end(9, 0)),  # 08:00 UTC, after now
        prev_sleep_end=None,
        now=_now(7, 30),  # 06:30 UTC
    )
    assert decision.action == "wait"
    assert decision.reason == "unfinalized"


def test_past_backstop_fires_on_unfinalized_data() -> None:
    decision = is_morning_ready(
        today=TODAY,
        sleep=None,
        prev_sleep_end=None,
        now=_now(11, 5),  # past 11:00
    )
    assert decision.action == "fire"
    assert decision.reason == "backstop"
    assert decision.sleep_end_to_persist is None


def test_backstop_boundary_is_inclusive() -> None:
    decision = is_morning_ready(
        today=TODAY,
        sleep=None,
        prev_sleep_end=None,
        now=_now(11, 0),  # exactly the backstop
    )
    assert decision.action == "fire"
    assert decision.reason == "backstop"


def test_lie_in_before_new_backstop_still_waits() -> None:
    """Batch 138 / Decision #217: a first-sighting wake at 10:00 local — past the
    *old* 09:30 backstop but before the new 11:00 one — must WAIT for stability,
    not force-fire. This is the whole point of moving the backstop out: a genuine
    lie-in is no longer read on one unstable sighting before he is actually up.
    (Under the old 09:30 backstop this same input would have fired "backstop".)"""
    sleep_end = _sleep_end(9, 50)  # 08:50 UTC
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(sleep_end),
        prev_sleep_end=None,  # first sighting
        now=_now(10, 0),  # past old 09:30 backstop, before new 11:00
    )
    assert decision.action == "wait"
    assert decision.reason == "awaiting_stability"


def test_past_backstop_fires_and_persists_finalized_end() -> None:
    sleep_end = _sleep_end(9, 0)  # 08:00 UTC, before now
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(sleep_end),
        prev_sleep_end=None,
        now=_now(11, 5),
    )
    assert decision.action == "fire"
    assert decision.reason == "backstop"
    assert decision.sleep_end_to_persist == sleep_end


def test_past_backstop_overrides_a_nap() -> None:
    """A nap never fires on its own, but the backstop still guarantees a verdict."""
    decision = is_morning_ready(
        today=TODAY,
        sleep=_reading(_sleep_end(9, 0), duration_min=45),
        prev_sleep_end=None,
        now=_now(11, 5),
    )
    assert decision.action == "fire"
    assert decision.reason == "backstop"
    assert decision.sleep_end_to_persist is None  # the nap end is not persisted


# ---------------------------------------------------------------------------
# SleepReading.from_sleep_fields adapter
# ---------------------------------------------------------------------------


def test_from_sleep_fields_none_or_empty() -> None:
    assert SleepReading.from_sleep_fields(None) is None
    assert SleepReading.from_sleep_fields({}) is None


def test_from_sleep_fields_builds_reading() -> None:
    end = datetime(2026, 6, 24, 7, 0)
    reading = SleepReading.from_sleep_fields(
        {"calendar_date": TODAY, "sleep_end_utc": end, "duration_sec": 28800}
    )
    assert reading is not None
    assert reading.calendar_date == TODAY
    assert reading.sleep_end_utc == end
    assert reading.duration_min == 480


def test_from_sleep_fields_missing_duration() -> None:
    reading = SleepReading.from_sleep_fields(
        {"calendar_date": TODAY, "sleep_end_utc": None, "duration_sec": None}
    )
    assert reading is not None
    assert reading.duration_min is None
