"""A dated HRV-floor challenge reads source observations before replying."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import DailyMetric
from src.models.profile import Profile, UserRole
from src.services.chat_context import (
    ChatContextService,
    _asks_about_hrv_floor,
    _hrv_floor_history_packet,
)


def test_hrv_floor_history_is_requested_only_for_the_relevant_question() -> None:
    assert _asks_about_hrv_floor("Garmin lowered my HRV floor from 46 to 45")
    assert _asks_about_hrv_floor("Did the HRV baseline threshold change?")
    assert not _asks_about_hrv_floor("Can you monitor the 18° pre-cool target?")
    assert not _asks_about_hrv_floor("My HRV was low last night")


def test_dated_wake_rows_show_the_floor_rose_not_fell() -> None:
    packet = _hrv_floor_history_packet(
        [
            (date(2026, 9, 19), "settled", 99),
            (date(2026, 9, 18), "morning", 46),
            (date(2026, 9, 17), "morning", 45),
            (date(2026, 9, 19), "morning", 46),
            (date(2026, 9, 18), "settled", 45),
        ],
        start=date(2026, 9, 12),
        end=date(2026, 9, 19),
    )

    assert packet["observations"] == [
        {"date": "2026-09-17", "observationPhase": "morning", "floorMs": 45},
        {"date": "2026-09-18", "observationPhase": "morning", "floorMs": 46},
        {"date": "2026-09-19", "observationPhase": "morning", "floorMs": 46},
    ]
    assert packet["latestRecordedChange"] == {
        "fromDate": "2026-09-17",
        "fromMs": 45,
        "toDate": "2026-09-18",
        "toMs": 46,
        "direction": "rose",
        "consecutiveDates": True,
    }


@pytest.mark.asyncio
async def test_floor_history_is_profile_scoped_and_as_of_the_question(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    asked_at = datetime(2026, 9, 19, 9, 0)
    async with session_factory() as session:
        user = Profile(
            id=uuid.uuid4(),
            display_name="HRV floor test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        other = Profile(
            id=uuid.uuid4(),
            display_name="Other HRV floor test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add_all([user, other])
        await session.flush()

        def reading(
            profile: Profile,
            day: int,
            phase: str,
            floor: int,
            recorded_at: datetime,
            *,
            inserted_at: datetime | None = None,
        ) -> DailyMetric:
            return DailyMetric(
                id=uuid.uuid4(),
                user_id=profile.id,
                calendar_date=date(2026, 9, day),
                phase=phase,
                hrv_baseline_low_ms=floor,
                recorded_at_utc=recorded_at,
                created_at=inserted_at or recorded_at,
                updated_at=inserted_at or recorded_at,
                raw_payload={},
            )

        session.add_all(
            [
                reading(user, 17, "morning", 45, datetime(2026, 9, 17, 8, 0)),
                reading(user, 18, "morning", 46, datetime(2026, 9, 18, 8, 0)),
                reading(user, 19, "morning", 46, datetime(2026, 9, 19, 8, 0)),
                reading(user, 19, "settled", 33, datetime(2026, 9, 19, 20, 0)),
                reading(
                    user,
                    16,
                    "morning",
                    44,
                    datetime(2026, 9, 16, 8, 0),
                    inserted_at=datetime(2026, 9, 20, 8, 0),
                ),
                reading(other, 19, "morning", 30, datetime(2026, 9, 19, 8, 0)),
            ]
        )
        await session.flush()

        packet = await ChatContextService(session)._hrv_floor_history(
            user.id, date(2026, 9, 19), asked_at_utc=asked_at
        )

    assert [row["date"] for row in packet["observations"]] == [
        "2026-09-17",
        "2026-09-18",
        "2026-09-19",
    ]
    assert packet["latestRecordedChange"]["direction"] == "rose"
    assert all(row["floorMs"] in (45, 46) for row in packet["observations"])
