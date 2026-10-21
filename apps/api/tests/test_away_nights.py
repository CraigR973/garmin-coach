"""Decision #429: the nights Mark is on record as having slept away from home.

The note texts below are synthetic. The repo is public, and his own words never go in it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import CheckInReading, KnowledgeBase, ManualEntry
from src.models.profile import Profile, UserRole
from src.services.away_nights import (
    HOLIDAY_WINDOWS_SECTION,
    holiday_wake_dates,
    reading_reports_away,
    recorded_away_wake_dates,
    reported_now_or_last_night,
    stored_holiday_windows,
)
from src.services.notes_reader import notes_hash


def test_a_holiday_is_its_nights_away_keyed_on_the_mornings_after() -> None:
    """27 Sep–6 Oct is nine nights away: he wakes away from 28 Sep to 6 Oct."""
    nights = holiday_wake_dates(date(2026, 9, 27), date(2026, 10, 6))

    assert len(nights) == 9
    assert nights[0] == date(2026, 9, 28)
    assert nights[-1] == date(2026, 10, 6)
    # The night before he leaves and the night he comes home are spent at home.
    assert date(2026, 9, 27) not in nights
    assert date(2026, 10, 7) not in nights


def test_a_window_that_starts_and_ends_on_one_day_has_no_night_away() -> None:
    assert holiday_wake_dates(date(2026, 7, 12), date(2026, 7, 12)) == []


def test_only_now_or_last_night_speaks_for_the_night_just_gone() -> None:
    assert reported_now_or_last_night({"state": "present", "when": "now"})
    assert reported_now_or_last_night({"state": "present", "when": "last_night"})
    assert not reported_now_or_last_night({"state": "present", "when": "earlier"})
    assert not reported_now_or_last_night({"state": "absent", "when": "last_night"})

    assert reading_reports_away({"travel": {"state": "present", "when": "last_night"}})
    assert not reading_reports_away({"travel": {"state": "present", "when": "earlier"}})
    assert not reading_reports_away({"travel": "present"})
    assert not reading_reports_away({"alcohol": {"state": "present", "when": "last_night"}})
    assert not reading_reports_away({})


def test_malformed_holiday_windows_are_skipped_and_resumed_ones_kept() -> None:
    content = {
        "windows": [
            {
                "startDate": "2026-07-12",
                "endDate": "2026-07-16",
                "resumedAtUtc": "2026-07-16T12:00:00",
            },
            {"startDate": "2026-09-27", "endDate": "2026-10-06", "resumedAtUtc": None},
            {"startDate": "not a date", "endDate": "2026-10-06"},
            {"endDate": "2026-10-06"},
            "not a window",
        ]
    }

    assert stored_holiday_windows(content) == [
        (date(2026, 7, 12), date(2026, 7, 16)),
        (date(2026, 9, 27), date(2026, 10, 6)),
    ]
    assert stored_holiday_windows(None) == []
    assert stored_holiday_windows({"windows": "not a list"}) == []


def _reading(entry: ManualEntry, *, when: str, digest: str | None = None) -> CheckInReading:
    reading: dict[str, Any] = {
        "status": "read",
        "travel": {"state": "present", "when": when, "words": "synthetic"},
    }
    return CheckInReading(
        id=uuid.uuid4(),
        user_id=entry.user_id,
        manual_entry_id=entry.id,
        notes_sha256=digest or notes_hash(entry.notes) or "",
        status="read",
        reading=reading,
        model_name="claude-test",
        prompt_version="notes-reader-test",
    )


@pytest.mark.asyncio
async def test_on_postgres_the_loader_reads_holidays_and_current_travel_readings(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()

    def entry(day: date, notes: str) -> ManualEntry:
        return ManualEntry(
            id=uuid.uuid4(),
            user_id=user_id,
            entry_date=day,
            entry_at_utc=datetime(day.year, day.month, day.day, 8, 0),
            notes=notes,
        )

    away_last_night = entry(date(2026, 10, 19), "Synthetic note: slept away last night.")
    travel_earlier = entry(date(2026, 10, 12), "Synthetic note: travelled last week.")
    edited_since = entry(date(2026, 10, 15), "Synthetic note: the version it carries now.")
    outside = entry(date(2026, 9, 1), "Synthetic note: away, but outside the range.")
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Away Nights Test",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section=HOLIDAY_WINDOWS_SECTION,
                version=1,
                is_active=True,
                content={
                    "windows": [
                        {
                            "startDate": "2026-09-27",
                            "endDate": "2026-10-06",
                            "pausedAtUtc": "2026-09-27T10:06:04",
                            "resumedAtUtc": None,
                        }
                    ]
                },
            )
        )
        session.add_all([away_last_night, travel_earlier, edited_since, outside])
        await session.flush()
        session.add_all(
            [
                _reading(away_last_night, when="last_night"),
                # "Earlier" travel describes the past, not the night just gone.
                _reading(travel_earlier, when="earlier"),
                # A reading of an older version of the note no longer counts.
                _reading(
                    edited_since,
                    when="now",
                    digest=notes_hash("Synthetic note: an older version."),
                ),
                _reading(outside, when="last_night"),
            ]
        )
        await session.commit()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        nights = await recorded_away_wake_dates(
            session, user_id, start=date(2026, 9, 24), end=date(2026, 10, 21)
        )

    assert nights == frozenset(
        {*holiday_wake_dates(date(2026, 9, 27), date(2026, 10, 6)), date(2026, 10, 19)}
    )
