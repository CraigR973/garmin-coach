"""DB-backed tests for the overnight bedroom read API (Batch 31).

``GET /api/v1/bedroom/overnight`` is a pure read that joins temperature + fan +
sleep for one night. The Dreo/Hive clouds are never touched. The auth + db
overrides mirror ``test_fan.py``.
"""

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
from src.models.coaching import FanStateReading, Sleep, TemperatureReading
from src.models.profile import Profile, UserRole
from src.routers import bedroom as bedroom_router

NIGHT = date(2026, 6, 29)  # BST window: 2026-06-29 20:30 UTC → 2026-06-30 08:00 UTC


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


async def _seed_night(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Bedroom Read Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        # Temperature: two readings inside the window, one daytime outside it.
        session.add_all(
            [
                TemperatureReading(
                    user_id=user_id,
                    captured_at_utc=datetime(2026, 6, 29, 22, 0),
                    temperature_c=20.4,
                ),
                TemperatureReading(
                    user_id=user_id,
                    captured_at_utc=datetime(2026, 6, 30, 2, 0),
                    temperature_c=19.2,
                ),
                TemperatureReading(
                    user_id=user_id,
                    captured_at_utc=datetime(2026, 6, 29, 12, 0),  # daytime → excluded
                    temperature_c=24.0,
                ),
            ]
        )
        # Fan: two ticks inside the window.
        session.add_all(
            [
                FanStateReading(
                    user_id=user_id,
                    captured_at_utc=datetime(2026, 6, 29, 22, 5),
                    phase="control",
                    auto_enabled=True,
                    observed_temp_c=20.4,
                    fan_on=True,
                    fan_speed=5,
                    action="apply",
                    reason="20.4C -> speed 5",
                ),
                FanStateReading(
                    user_id=user_id,
                    captured_at_utc=datetime(2026, 6, 30, 2, 5),
                    phase="control",
                    auto_enabled=True,
                    observed_temp_c=19.2,
                    fan_on=False,
                    fan_speed=None,
                    action="apply",
                    reason="19.2C below threshold",
                ),
            ]
        )
        # Sleep keyed by the wake morning (night + 1), with a hypnogram.
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=date(2026, 6, 30),
                sleep_start_utc=datetime(2026, 6, 29, 22, 30),
                sleep_end_utc=datetime(2026, 6, 30, 6, 30),
                score=78,
                age_adjusted_score=82,
                duration_sec=28800,
                awake_sleep_sec=900,
                restless_moments_count=12,
                raw_payload={
                    "sleepLevels": [
                        {
                            "startGMT": "2026-06-29T22:30:00.0",
                            "endGMT": "2026-06-29T23:30:00.0",
                            "activityLevel": 1.0,
                        },
                        {
                            "startGMT": "2026-06-29T23:30:00.0",
                            "endGMT": "2026-06-30T00:30:00.0",
                            "activityLevel": 0.0,
                        },
                    ]
                },
            )
        )
        await session.commit()
    return user_id


@pytest.mark.asyncio
async def test_overnight_joins_temp_fan_and_sleep(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_night(session_factory)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/bedroom/overnight?date=2026-06-29")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["night"] == "2026-06-29"
    assert data["windowStartUtc"] == "2026-06-29T20:30:00Z"
    assert data["windowEndUtc"] == "2026-06-30T08:00:00Z"
    assert data["thresholds"] == {"onC": 19.5, "criticalC": 20.0}

    # Daytime reading excluded; two in-window readings remain, time-ordered.
    assert [p["c"] for p in data["temperature"]] == [20.4, 19.2]
    assert data["fan"][0]["action"] == "apply"
    assert data["fan"][0]["on"] is True
    assert data["fan"][0]["speed"] == 5
    assert data["fan"][1]["on"] is False

    assert data["sleep"]["score"] == 78
    assert [s["stage"] for s in data["sleep"]["stages"]] == ["light", "deep"]

    # Summary roll-up: one on-tick × 15 min, peak speed 5, range over the curve.
    assert data["summary"]["fanRanMinutes"] == 15
    assert data["summary"]["peakSpeed"] == 5
    assert data["summary"]["minTempC"] == 19.2
    assert data["summary"]["maxTempC"] == 20.4

    assert "2026-06-29" in data["nights"]


@pytest.mark.asyncio
async def test_overnight_defaults_to_last_completed_night(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_night(session_factory)
    monkeypatch.setattr(bedroom_router, "default_night", lambda now_local: NIGHT)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/bedroom/overnight")  # no ?date
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["night"] == "2026-06-29"
    assert len(data["temperature"]) == 2


@pytest.mark.asyncio
async def test_overnight_rejects_bad_date(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_night(session_factory)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/bedroom/overnight?date=29-06-2026")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400, resp.text
