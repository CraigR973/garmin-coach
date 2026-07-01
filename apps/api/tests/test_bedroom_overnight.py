"""Pure tests for the overnight bedroom chart helpers (Batch 31)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.services.bedroom_overnight import (
    OvernightSummary,
    default_night,
    extract_hypnogram,
    iso_z,
    night_for_local,
    night_window,
    recent_nights,
    sleep_calendar_date,
    summarize_overnight,
)

LONDON = ZoneInfo("Europe/London")


# --- night_window -----------------------------------------------------------


def test_night_window_bst_converts_to_utc() -> None:
    # 2026-06-29 is BST (UTC+1): 21:30 local -> 20:30 UTC; next-day 09:00 -> 08:00 UTC.
    start, end = night_window(date(2026, 6, 29), LONDON)
    assert start == datetime(2026, 6, 29, 20, 30)
    assert end == datetime(2026, 6, 30, 8, 0)


def test_night_window_gmt_is_utc() -> None:
    # 2026-01-15 is GMT (UTC+0): local == UTC.
    start, end = night_window(date(2026, 1, 15), LONDON)
    assert start == datetime(2026, 1, 15, 21, 30)
    assert end == datetime(2026, 1, 16, 9, 0)


# --- default_night ----------------------------------------------------------


def test_default_night_after_winddown_is_last_night() -> None:
    now = datetime(2026, 6, 30, 10, 0, tzinfo=LONDON)  # past 09:00 wind-down
    assert default_night(now) == date(2026, 6, 29)


def test_default_night_before_winddown_is_night_before_last() -> None:
    now = datetime(2026, 6, 30, 7, 0, tzinfo=LONDON)  # still inside last night's window
    assert default_night(now) == date(2026, 6, 28)


# --- night_for_local --------------------------------------------------------


def test_night_for_local_buckets_evening_and_morning() -> None:
    assert night_for_local(datetime(2026, 6, 29, 22, 0)) == date(2026, 6, 29)
    assert night_for_local(datetime(2026, 6, 29, 21, 30)) == date(2026, 6, 29)  # boundary
    assert night_for_local(datetime(2026, 6, 30, 3, 0)) == date(2026, 6, 29)
    assert night_for_local(datetime(2026, 6, 30, 8, 0)) == date(2026, 6, 29)


def test_night_for_local_daytime_is_none() -> None:
    assert night_for_local(datetime(2026, 6, 30, 9, 0)) is None  # wind-down boundary
    assert night_for_local(datetime(2026, 6, 30, 14, 0)) is None


# --- recent_nights ----------------------------------------------------------


def test_recent_nights_dedups_sorts_and_skips_daytime() -> None:
    stamps = [
        datetime(2026, 6, 29, 22, 0),  # night 06-29
        datetime(2026, 6, 30, 2, 0),  # night 06-29
        datetime(2026, 6, 30, 14, 0),  # daytime -> ignored
        datetime(2026, 6, 28, 23, 0),  # night 06-28
    ]
    assert recent_nights(stamps) == [date(2026, 6, 29), date(2026, 6, 28)]


def test_recent_nights_respects_limit() -> None:
    stamps = [datetime(2026, 6, d, 23, 0) for d in range(1, 11)]
    assert recent_nights(stamps, limit=3) == [date(2026, 6, 10), date(2026, 6, 9), date(2026, 6, 8)]


# --- sleep_calendar_date ----------------------------------------------------


def test_sleep_calendar_date_is_wake_morning() -> None:
    assert sleep_calendar_date(date(2026, 6, 29)) == date(2026, 6, 30)


# --- extract_hypnogram ------------------------------------------------------


def test_extract_hypnogram_maps_levels_and_skips_bad_entries() -> None:
    payload = {
        "sleepLevels": [
            {
                "startGMT": "2026-06-29T23:00:00.0",
                "endGMT": "2026-06-29T23:30:00.0",
                "activityLevel": 1.0,
            },
            {
                "startGMT": "2026-06-29T23:30:00.0",
                "endGMT": "2026-06-30T00:30:00.0",
                "activityLevel": 0.0,
            },
            {"missing": "times"},
            {"startGMT": "not-a-date", "endGMT": "also-bad", "activityLevel": 2.0},
            {
                "startGMT": "2026-06-30T05:00:00.0",
                "endGMT": "2026-06-30T05:15:00.0",
                "activityLevel": 3.0,
            },
        ]
    }
    spans = extract_hypnogram(payload)
    assert [s["stage"] for s in spans] == ["light", "deep", "awake"]
    assert spans[0] == {
        "start": "2026-06-29T23:00:00Z",
        "end": "2026-06-29T23:30:00Z",
        "stage": "light",
    }


def test_extract_hypnogram_handles_missing_payload() -> None:
    assert extract_hypnogram(None) == []
    assert extract_hypnogram({}) == []
    assert extract_hypnogram({"sleepLevels": "nope"}) == []


# --- summarize_overnight ----------------------------------------------------


def test_summarize_overnight_rolls_up_range_runtime_and_peak() -> None:
    summary = summarize_overnight(
        [19.0, 21.5, 20.0, None],
        [(True, 3), (True, 5), (False, None), (None, None)],
    )
    assert summary == OvernightSummary(
        min_temp_c=19.0, max_temp_c=21.5, fan_ran_minutes=30, peak_speed=5
    )


def test_summarize_overnight_empty_is_zeroed() -> None:
    assert summarize_overnight([], []) == OvernightSummary(
        min_temp_c=None, max_temp_c=None, fan_ran_minutes=0, peak_speed=None
    )


def test_iso_z_appends_zulu_and_drops_microseconds() -> None:
    assert iso_z(datetime(2026, 6, 29, 20, 30, 0, 500)) == "2026-06-29T20:30:00Z"
