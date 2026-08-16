"""Batch 205 / CI191-02 consequence 3 — a stored verdict is not mutable.

``analyses`` keeps every historical morning row, and the rule for reading one
back used to be *the newest wins*. 2026-07-05 reads ``Amber@07:23 ->
Green@22:03``, and the later row was the one the Red-morning cluster, the
reviews and the block-progression trend all counted — a colour Mark was never
shown replacing the one he was.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Analysis
from src.models.profile import Profile, UserRole
from src.services.chronic_patterns import ChronicPatternSuggestionService
from src.services.delivered_verdict import MORNING_READ_CUTOFF, delivered_verdicts

SUBJECT = date(2026, 7, 5)
LONDON = "Europe/London"


def _analysis(
    subject_date: date,
    generated_local_hour: int,
    generated_local_minute: int,
    verdict: str,
    *,
    user_id: uuid.UUID | None = None,
) -> Analysis:
    """A morning analysis generated at a given *British Summer Time* wall clock."""
    local = datetime(
        subject_date.year,
        subject_date.month,
        subject_date.day,
        generated_local_hour,
        generated_local_minute,
    )
    # July: BST is UTC+1, so the stored naive-UTC value is one hour behind.
    generated_at_utc = local - timedelta(hours=1)
    return Analysis(
        user_id=user_id or uuid.uuid4(),
        analysis_type="morning",
        subject_date=subject_date,
        generated_at_utc=generated_at_utc,
        created_at=generated_at_utc,
        prompt_version="test",
        verdict=verdict,
        context_packet={},
        output_markdown="",
        raw_response={},
    )


# --- the rule --------------------------------------------------------------


def test_an_evening_regeneration_does_not_replace_the_colour_mark_was_shown() -> None:
    """The 2026-07-05 case, exactly."""
    rows = [
        _analysis(SUBJECT, 7, 23, "Amber"),
        _analysis(SUBJECT, 22, 3, "Green"),
    ]

    assert delivered_verdicts(rows, timezone_name=LONDON) == {SUBJECT: "Amber"}


def test_a_post_check_in_regeneration_still_counts() -> None:
    """The check-in is real evidence the first read lacked, and it lands in the window."""
    rows = [
        _analysis(SUBJECT, 7, 23, "Green"),
        _analysis(SUBJECT, 9, 40, "Amber"),
    ]

    assert delivered_verdicts(rows, timezone_name=LONDON) == {SUBJECT: "Amber"}


def test_the_cutoff_is_the_close_of_the_wake_window() -> None:
    """A wake-triggered read cannot be produced after wake detection stops polling."""
    inside = _analysis(SUBJECT, MORNING_READ_CUTOFF.hour, MORNING_READ_CUTOFF.minute, "Red")
    outside = _analysis(SUBJECT, MORNING_READ_CUTOFF.hour, MORNING_READ_CUTOFF.minute + 1, "Green")

    assert delivered_verdicts([inside, outside], timezone_name=LONDON) == {SUBJECT: "Red"}


def test_a_day_generated_entirely_late_keeps_its_earliest_read() -> None:
    """A missed morning still reports a colour rather than dropping out of the window."""
    rows = [
        _analysis(SUBJECT, 19, 0, "Amber"),
        _analysis(SUBJECT, 23, 30, "Green"),
    ]

    assert delivered_verdicts(rows, timezone_name=LONDON) == {SUBJECT: "Amber"}


def test_input_order_does_not_decide_the_answer() -> None:
    rows = [_analysis(SUBJECT, 22, 3, "Green"), _analysis(SUBJECT, 7, 23, "Amber")]

    assert delivered_verdicts(rows, timezone_name=LONDON) == {SUBJECT: "Amber"}


def test_each_date_is_resolved_independently() -> None:
    other = SUBJECT + timedelta(days=1)
    rows = [
        _analysis(SUBJECT, 7, 23, "Red"),
        _analysis(SUBJECT, 22, 3, "Green"),
        _analysis(other, 7, 30, "Green"),
    ]

    assert delivered_verdicts(rows, timezone_name=LONDON) == {SUBJECT: "Red", other: "Green"}


def test_an_unknown_timezone_falls_back_to_utc_rather_than_raising() -> None:
    rows = [_analysis(SUBJECT, 7, 23, "Amber")]

    assert delivered_verdicts(rows, timezone_name="Not/AZone") == {SUBJECT: "Amber"}


def test_local_time_is_what_is_compared_not_utc() -> None:
    """A 00:30 BST read is 23:30 UTC the previous day — still inside the morning."""
    row = _analysis(SUBJECT, 0, 30, "Red")

    assert row.generated_at_utc.hour == 23
    assert delivered_verdicts([row], timezone_name=LONDON) == {SUBJECT: "Red"}


# --- wired into the Red-morning cluster ------------------------------------


@pytest.mark.asyncio
async def test_recent_verdicts_counts_the_morning_read(db_conn: AsyncConnection) -> None:
    """The chronic Red cluster reads the colours Mark was given.

    Two dates each carry a morning Red and an evening Green regeneration.
    Pre-Batch-205 both dates would have counted as Green and the cluster would
    have been empty.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    first = SUBJECT
    second = SUBJECT + timedelta(days=1)

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Delivered verdicts",
                role=UserRole.admin,
                timezone=LONDON,
                is_active=True,
            )
        )
        await session.flush()
        for day in (first, second):
            session.add(_analysis(day, 7, 23, "Red", user_id=user_id))
            session.add(_analysis(day, 22, 3, "Green", user_id=user_id))
        await session.flush()

        verdicts = await ChronicPatternSuggestionService(session)._recent_verdicts(
            user_id, as_of=second, timezone_name=LONDON
        )

    by_date = {row.calendar_date: row.verdict for row in verdicts}
    assert by_date == {first: "Red", second: "Red"}


@pytest.mark.asyncio
async def test_recent_verdicts_keeps_a_same_morning_regeneration(
    db_conn: AsyncConnection,
) -> None:
    """The pin selects within the morning; it does not freeze the first read."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Check-in regeneration",
                role=UserRole.admin,
                timezone=LONDON,
                is_active=True,
            )
        )
        await session.flush()
        session.add(_analysis(SUBJECT, 7, 23, "Green", user_id=user_id))
        session.add(_analysis(SUBJECT, 9, 40, "Red", user_id=user_id))
        await session.flush()

        verdicts = await ChronicPatternSuggestionService(session)._recent_verdicts(
            user_id, as_of=SUBJECT, timezone_name=LONDON
        )

    assert [(row.calendar_date, row.verdict) for row in verdicts] == [(SUBJECT, "Red")]
