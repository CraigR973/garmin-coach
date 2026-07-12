"""Tests for the bedroom-fan control router (Batch 27.3).

`PUT /api/v1/fan/auto` persists the overnight autopilot preference; `POST
/api/v1/fan/command` drives the Dreo cloud and, on success only, takes manual
control (auto off). The Dreo client is faked so no network or real fan is needed.

The ``get_current_user`` override resolves the profile through the *same* request
``get_db`` session the router commits on, so the persistence assertions exercise
the real attach→mutate→commit path rather than a detached object.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.profile import Profile, UserRole
from src.routers import fan as fan_router
from src.services.dreo_fan import DreoConnectionError, DreoFanInfo, DreoFanSnapshot, DreoFanState


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


class _FakeFan:
    """Minimal stand-in matching the methods routers.fan._drive_fan calls."""

    def __init__(
        self,
        *,
        is_on: bool = True,
        fan_speed: int = 3,
        connect_error: Exception | None = None,
    ) -> None:
        self._state = DreoFanState(is_on=is_on, fan_speed=fan_speed)
        self._connect_error = connect_error
        self.calls: list[tuple] = []
        self.closed = False
        self.selected_fan_id = "fan-bedroom"

    def connect(self, *, fan_id: str | None = None) -> None:
        self.selected_fan_id = fan_id or self.selected_fan_id
        self.calls.append(("connect", self.selected_fan_id))
        if self._connect_error is not None:
            raise self._connect_error

    def power(self, on: bool) -> None:
        self.calls.append(("power", on))

    def set_speed(self, speed: int) -> None:
        self.calls.append(("set_speed", speed))

    def read_state(self) -> DreoFanState:
        return self._state

    def list_fans(self) -> list[DreoFanInfo]:
        return [DreoFanInfo(fan_id=self.selected_fan_id, label="Bedroom fan", auto_target=True)]

    def read_all_states(self) -> list[DreoFanSnapshot]:
        return [
            DreoFanSnapshot(
                info=DreoFanInfo(
                    fan_id=self.selected_fan_id,
                    label="Bedroom fan",
                    auto_target=True,
                ),
                state=self._state,
            )
        ]

    def close(self) -> None:
        self.closed = True


async def _seed_player(
    session_factory: async_sessionmaker[AsyncSession], *, fan_auto_enabled: bool
) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Fan Router Test",
                pin_hash="x" * 60,
                role=UserRole.player,
                timezone="Europe/London",
                is_active=True,
                fan_auto_enabled=fan_auto_enabled,
            )
        )
        await session.commit()
    return user_id


async def _read_auto(session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> bool:
    async with session_factory() as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        return player.fan_auto_enabled


@pytest.mark.asyncio
async def test_put_fan_auto_persists(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, fan_auto_enabled=True)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            off = await client.put("/api/v1/fan/auto", json={"enabled": False})
            on = await client.put("/api/v1/fan/auto", json={"enabled": True})
    finally:
        app.dependency_overrides.clear()

    assert off.status_code == 200, off.text
    assert off.json()["data"]["autoEnabled"] is False
    assert on.json()["data"]["autoEnabled"] is True
    assert await _read_auto(session_factory, user_id) is True


@pytest.mark.asyncio
async def test_post_fan_command_drives_and_takes_manual_control(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, fan_auto_enabled=True)

    fake = _FakeFan(is_on=True, fan_speed=3)
    monkeypatch.setattr(fan_router, "DreoFanClient", lambda: fake)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/fan/command", json={"power": True, "speed": 3})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["autoEnabled"] is False
    assert data["fan"]["id"] == "fan-bedroom"
    assert data["fan"]["isOn"] is True
    assert data["fan"]["speed"] == 3
    assert ("power", True) in fake.calls
    assert ("set_speed", 3) in fake.calls
    assert fake.closed
    # A manual command takes control: the autopilot is now off in the DB.
    assert await _read_auto(session_factory, user_id) is False


@pytest.mark.asyncio
async def test_post_fan_command_targets_the_requested_fan(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, fan_auto_enabled=True)

    fake = _FakeFan(is_on=True, fan_speed=5)
    monkeypatch.setattr(fan_router, "DreoFanClient", lambda: fake)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/fan/command",
                json={"fanId": "fan-office", "power": True, "speed": 5},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert ("connect", "fan-office") in fake.calls
    assert response.json()["data"]["fan"]["id"] == "fan-office"


@pytest.mark.asyncio
async def test_post_fan_command_requires_power_or_speed(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, fan_auto_enabled=True)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/fan/command", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400, response.text
    # The autopilot is untouched by a rejected command.
    assert await _read_auto(session_factory, user_id) is True


@pytest.mark.asyncio
async def test_post_fan_command_502_keeps_autopilot_enabled(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = await _seed_player(session_factory, fan_auto_enabled=True)

    fake = _FakeFan(connect_error=DreoConnectionError("transport not ready"))
    monkeypatch.setattr(fan_router, "DreoFanClient", lambda: fake)

    app.dependency_overrides[get_current_user] = _user_override(user_id)
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/fan/command", json={"power": True})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502, response.text
    # A transient cloud failure must not silently disable the autopilot.
    assert await _read_auto(session_factory, user_id) is True
