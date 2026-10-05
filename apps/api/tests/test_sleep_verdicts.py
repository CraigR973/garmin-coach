"""DB-backed tests for the sleep verdict-range read (Batch 120)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import Analysis
from src.models.profile import Profile, UserRole


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


def _user_override(user_id: uuid.UUID):
    async def _override(db: AsyncSession = Depends(get_db)) -> Profile:
        user = await db.get(Profile, user_id)
        assert user is not None
        return user

    return _override


async def _seed_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                Profile(
                    id=user_id,
                    display_name="Sleep Verdict Test",
                    role=UserRole.player,
                    timezone="Europe/London",
                    is_active=True,
                ),
                Profile(
                    id=other_user_id,
                    display_name="Other User",
                    role=UserRole.player,
                    timezone="Europe/London",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=date(2026, 7, 10),
                    generated_at_utc=datetime(2026, 7, 10, 6, 0),
                    prompt_version="morning-v1",
                    model_name="claude-sonnet",
                    verdict="Amber",
                    context_packet={},
                    output_markdown="older",
                    raw_response={},
                ),
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=date(2026, 7, 10),
                    generated_at_utc=datetime(2026, 7, 10, 7, 0),
                    prompt_version="morning-v1",
                    model_name="claude-sonnet",
                    verdict="Green",
                    context_packet={},
                    output_markdown="newer",
                    raw_response={},
                ),
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=date(2026, 7, 12),
                    generated_at_utc=datetime(2026, 7, 12, 6, 30),
                    prompt_version="morning-v1",
                    model_name="claude-sonnet",
                    verdict="Red",
                    context_packet={},
                    output_markdown="red day",
                    raw_response={},
                ),
                Analysis(
                    user_id=user_id,
                    analysis_type="weekly_review",
                    subject_date=date(2026, 7, 11),
                    generated_at_utc=datetime(2026, 7, 11, 9, 0),
                    prompt_version="review-v1",
                    model_name="claude-sonnet",
                    verdict="green",
                    context_packet={},
                    output_markdown="wrong type",
                    raw_response={},
                ),
                Analysis(
                    user_id=other_user_id,
                    analysis_type="morning",
                    subject_date=date(2026, 7, 11),
                    generated_at_utc=datetime(2026, 7, 11, 6, 0),
                    prompt_version="morning-v1",
                    model_name="claude-sonnet",
                    verdict="amber",
                    context_packet={},
                    output_markdown="other user",
                    raw_response={},
                ),
            ]
        )
        await session.commit()
    return user_id


@pytest.mark.asyncio
async def test_sleep_verdict_range_returns_freshest_morning_verdicts(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_user(session_factory)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/sleep/verdicts?from=2026-07-09&to=2026-07-13")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["from"] == "2026-07-09"
    assert data["to"] == "2026-07-13"
    assert data["verdicts"] == {
        "2026-07-10": "green",
        "2026-07-12": "red",
    }


@pytest.mark.asyncio
async def test_sleep_verdict_range_rejects_invalid_order(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_user(session_factory)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/sleep/verdicts?from=2026-07-13&to=2026-07-09")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "from must be on or before to"


@pytest.mark.asyncio
async def test_the_calendar_reads_each_morning_and_rest_day_as_the_call_does(
    db_conn: AsyncConnection,
) -> None:
    """Batch 313: a reading per day, and an empty plan-week day stored before the rule
    is read as a rest day; a day outside every plan week is not."""
    from src.models.coaching import PlanBlock

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Sleep Calendar Call Test",
                role=UserRole.player,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            PlanBlock(
                user_id=user_id,
                name="W09 RECOVERY",
                block_type="recovery",
                start_date=date(2026, 3, 9),
                end_date=date(2026, 3, 15),
            )
        )

        def morning(day: date, verdict: str, packet: dict[str, object]) -> Analysis:
            return Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=day,
                generated_at_utc=datetime.combine(day, datetime.min.time()),
                prompt_version="morning-v1",
                model_name="claude-sonnet",
                verdict=verdict,
                context_packet=packet,
                output_markdown="",
                raw_response={},
            )

        session.add_all(
            [
                # An empty day inside the plan week, stored before the rule: a rest day.
                morning(date(2026, 3, 10), "Red", {"plannedWorkouts": [], "restDay": {}}),
                # A ride that morning: not a rest day.
                morning(
                    date(2026, 3, 11),
                    "Amber",
                    {"plannedWorkouts": [{"id": "x", "status": "planned"}], "restDay": {}},
                ),
                # A holiday stored as rest.
                morning(
                    date(2026, 3, 12),
                    "Green",
                    {
                        "plannedWorkouts": [{"id": "y", "status": "skipped"}],
                        "restDay": {"isRestDay": True, "reason": "holiday"},
                    },
                ),
                # An empty day outside every plan week: no session planned, not rest.
                morning(date(2026, 3, 20), "Amber", {"plannedWorkouts": [], "restDay": {}}),
                # A packet whose sessions are not a list reads as unknown, not empty.
                morning(date(2026, 3, 13), "Green", {"plannedWorkouts": None}),
            ]
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/sleep/verdicts?from=2026-03-09&to=2026-03-22")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["days"] == {
        "2026-03-10": {"reading": "still_recovering", "restDay": True},
        "2026-03-11": {"reading": "some_fatigue", "restDay": False},
        "2026-03-12": {"reading": "recovered", "restDay": True},
        "2026-03-13": {"reading": "recovered", "restDay": False},
        "2026-03-20": {"reading": "some_fatigue", "restDay": False},
    }
