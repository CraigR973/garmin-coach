"""Batch 341 (DS328-07): a weekly review is skipped only for a week mostly away.

On Sun 27 Sep the holiday had begun, so the review of 21-27 Sep was skipped though the
week held 17 activities; the 4 Oct skip (a week wholly away) is the intended case.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.services.holiday_pause import HolidayWindow, week_mostly_away

SUNDAY = date(2026, 9, 27)
PAUSED = datetime(2026, 9, 1, 8, 0)


def _away(start: date, end: date) -> HolidayWindow:
    return HolidayWindow(start_date=start, end_date=end, paused_at_utc=PAUSED)


@pytest.mark.parametrize(
    ("windows", "skipped"),
    [
        # 27 Sep as it happened: the holiday began on the review's own Sunday.
        ([_away(date(2026, 9, 27), date(2026, 10, 10))], False),
        # The intended skip: the whole week away.
        ([_away(date(2026, 9, 19), date(2026, 10, 2))], True),
        # Most of the week away (Thu-Sun, four of seven days).
        ([_away(date(2026, 9, 24), date(2026, 9, 30))], True),
        # Less than most (Fri-Sun, three of seven).
        ([_away(date(2026, 9, 25), date(2026, 9, 30))], False),
        # Two short trips that add up to most of the week.
        (
            [
                _away(date(2026, 9, 21), date(2026, 9, 22)),
                _away(date(2026, 9, 25), date(2026, 9, 26)),
            ],
            True,
        ),
        # Back early: a resume moves the end to the day before it (Mon-Tue away).
        ([_away(date(2026, 9, 21), date(2026, 9, 22))], False),
        ([], False),
    ],
)
def test_only_a_week_mostly_away_skips_its_review(
    windows: list[HolidayWindow], skipped: bool
) -> None:
    assert week_mostly_away(windows, SUNDAY) is skipped
