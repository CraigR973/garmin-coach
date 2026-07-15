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
                    pin_hash="x" * 60,
                    role=UserRole.player,
                    timezone="Europe/London",
                    is_active=True,
                ),
                Profile(
                    id=other_user_id,
                    display_name="Other User",
                    pin_hash="y" * 60,
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
