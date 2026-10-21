"""The nights Mark is on record as having slept away from home (Decision #429).

Two records say a night was spent away, and nothing else may: a holiday window he
set in the plan, and a check-in whose note the notes reader (Batch 297) read as
travel *now* or *last night*. A note that places travel earlier describes the past,
not the night just gone, and counts for nothing here — the bound
``chronic_patterns.reading_causes`` already applies to an acute cause.

Two readers need the same answer and cannot import each other: the chronic-pattern
cards, which count how many of a flag's misses fell on nights away, and the driver
correlation in ``insights``, which must not pair the empty home bedroom with sleep
measured somewhere else. On 18 Oct 2026 the "Protect recovery markers" card counted
18 low 7-day HRV mornings of 28, 11 of them inside the 27 Sep–6 Oct holiday or the
week its nights stayed in the average, and named bedroom temperature as the closest
tracking factor over 116 nights, 13 of which were holiday nights in a room nobody
slept in (the Hive poll does not stop for a holiday; the fan does). Both now take
their away nights from here, so they cannot disagree about which nights they are.

Every function but the loader is pure. A night is keyed by its wake date, the date
Garmin stores the sleep under.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import CheckInReading, KnowledgeBase, ManualEntry
from src.services.notes_reader import notes_hash

#: The recorded contexts that place him somewhere other than his own bedroom.
AWAY_REASONS: Final = frozenset({"holiday", "travel"})

#: A cause in a note speaks for the night just gone only when it says now or last night.
ACUTE_WHEN: Final = frozenset({"now", "last_night"})

HOLIDAY_WINDOWS_SECTION: Final = "holiday_windows"


def reported_now_or_last_night(item: Mapping[str, Any]) -> bool:
    """True when one cause in a notes reading is present for now or last night."""

    return item.get("state") == "present" and item.get("when") in ACUTE_WHEN


def holiday_wake_dates(start_date: date, end_date: date) -> list[date]:
    """The wake dates of the nights a holiday covers.

    Overnight away is end-exclusive (Decision #213): he sleeps away on the evenings
    from ``start_date`` to the day before ``end_date``, and each of those nights ends
    the next morning. A holiday of 27 Sep–6 Oct is nine nights, waking 28 Sep to
    6 Oct; the night before he leaves and the night he comes home are at home.
    """

    nights = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(1, nights + 1)]


def stored_holiday_windows(content: Mapping[str, Any] | None) -> list[tuple[date, date]]:
    """``(start, end)`` for each well-formed window of the ``holiday_windows`` section.

    A resumed window still counts: it records where he was on its dates, and Resume
    shortens a window to end the day before he came home (Decision #351).
    """

    raw_windows = content.get("windows", []) if isinstance(content, Mapping) else []
    windows: list[tuple[date, date]] = []
    for raw in raw_windows if isinstance(raw_windows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        try:
            windows.append(
                (
                    date.fromisoformat(str(raw["startDate"])),
                    date.fromisoformat(str(raw["endDate"])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return windows


def current_readings(
    manual_rows: Sequence[ManualEntry], readings: Sequence[CheckInReading]
) -> dict[uuid.UUID, Mapping[str, Any]]:
    """Each check-in's reading of the note it carries now, when one was read."""

    by_key = {
        (row.manual_entry_id, row.notes_sha256): row for row in readings if row.status == "read"
    }
    current: dict[uuid.UUID, Mapping[str, Any]] = {}
    for entry in manual_rows:
        digest = notes_hash(entry.notes)
        stored = by_key.get((entry.id, digest)) if digest is not None else None
        if stored is not None:
            current[entry.id] = stored.reading or {}
    return current


def reading_reports_away(reading: Mapping[str, Any]) -> bool:
    """True when a notes reading puts him away from home now or last night."""

    travel = reading.get("travel")
    return isinstance(travel, Mapping) and reported_now_or_last_night(travel)


async def recorded_away_wake_dates(
    session: AsyncSession, user_id: uuid.UUID, *, start: date, end: date
) -> frozenset[date]:
    """Every wake date from ``start`` to ``end`` whose night he is on record as away.

    The check-ins are read through their stored readings only, joined so that a
    window of four months moves the few notes that have a reading rather than every
    note in it. A reading counts only for the version of the note it was made from.
    """

    away: set[date] = set()
    holiday_content = await session.scalar(
        select(KnowledgeBase.content).where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.section == HOLIDAY_WINDOWS_SECTION,
            KnowledgeBase.is_active.is_(True),
        )
    )
    for window_start, window_end in stored_holiday_windows(holiday_content):
        away.update(
            day for day in holiday_wake_dates(window_start, window_end) if start <= day <= end
        )

    rows = await session.execute(
        select(
            ManualEntry.entry_date,
            ManualEntry.notes,
            CheckInReading.notes_sha256,
            CheckInReading.reading,
        )
        .join(CheckInReading, CheckInReading.manual_entry_id == ManualEntry.id)
        .where(
            ManualEntry.user_id == user_id,
            ManualEntry.entry_date >= start,
            ManualEntry.entry_date <= end,
            ManualEntry.planned_workout_id.is_(None),
            ManualEntry.activity_id.is_(None),
            CheckInReading.status == "read",
        )
    )
    for entry_date, notes, digest, reading in rows.all():
        if notes_hash(notes) != digest or not isinstance(reading, Mapping):
            continue
        if reading_reports_away(reading):
            away.add(entry_date)
    return frozenset(away)
