"""Tests for passwordless activation, device verification, and revocation."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from src.auth import generate_opaque_token, hash_token, require_admin
from src.database import get_db
from src.main import app
from src.models.profile import Profile, UserRole
from src.models.refresh_token import RefreshToken


def _make_user(role: UserRole = UserRole.player) -> Profile:
    user = MagicMock(spec=Profile)
    user.id = uuid.uuid4()
    user.display_name = "Test User"
    user.role = role
    user.timezone = "UTC"
    user.deleted_at = None
    user.is_active = True
    return user


def _stub_db(execute_results: list[object]) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def _scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@asynccontextmanager
async def _override_db(mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def test_opaque_tokens_are_random_and_only_their_hash_is_persistable() -> None:
    first = generate_opaque_token()
    second = generate_opaque_token()

    assert first != second
    assert len(first) >= 40
    assert len(hash_token(first)) == 64
    assert first not in hash_token(first)


async def test_activate_success_mints_device_token_without_logging_credentials(
    client: AsyncClient,
) -> None:
    user = _make_user(role=UserRole.admin)
    code = "activate-me-once"
    mock_db = _stub_db([_scalar(user.id), _scalar(user)])

    with capture_logs() as logs:
        async with _override_db(mock_db):
            response = await client.post(
                "/api/v1/auth/activate",
                json={"code": code},
                headers={"User-Agent": "TestAgent/1.0"},
            )

    assert response.status_code == 200, response.text
    data = response.json()
    raw_device_token = data["device_token"]
    assert data["player"]["display_name"] == "Test User"
    consume_statement = mock_db.execute.await_args_list[0].args[0]
    consume_params = consume_statement.compile().params
    assert "activation" in consume_params.values()
    assert hash_token(code) in consume_params.values()

    added = mock_db.add.call_args[0][0]
    assert isinstance(added, RefreshToken)
    assert added.user_id == user.id
    assert added.purpose == "device"
    assert added.device_hint == "TestAgent/1.0"
    assert added.token_hash == hash_token(raw_device_token)
    assert code not in repr(logs)
    assert raw_device_token not in repr(logs)


async def test_activate_rejects_expired_code(client: AsyncClient) -> None:
    code = "expired-code"
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        response = await client.post("/api/v1/auth/activate", json={"code": code})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired activation code"


async def test_activate_rejects_unknown_code(client: AsyncClient) -> None:
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        response = await client.post("/api/v1/auth/activate", json={"code": "unknown-code"})

    assert response.status_code == 401


async def test_concurrent_activation_consumes_code_once_and_mints_one_device(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    code = generate_opaque_token()
    async with session_factory() as session:
        await session.execute(text("SET search_path TO coach, public"))
        session.add(
            Profile(
                id=user_id,
                display_name="Atomic Activation",
                role=UserRole.player,
                timezone="UTC",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            RefreshToken(
                user_id=user_id,
                token_hash=hash_token(code),
                purpose="activation",
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
            )
        )
        await session.commit()

    async def _db_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            await session.execute(text("SET search_path TO coach, public"))
            try:
                yield session
            finally:
                await session.rollback()

    app.dependency_overrides[get_db] = _db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            first, second = await asyncio.gather(
                http.post("/api/v1/auth/activate", json={"code": code}),
                http.post("/api/v1/auth/activate", json={"code": code}),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert sorted((first.status_code, second.status_code)) == [200, 401]
    async with session_factory() as session:
        await session.execute(text("SET search_path TO coach, public"))
        device_count = await session.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.purpose == "device",
            )
        )
        assert device_count == 1
        await session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await session.execute(delete(Profile).where(Profile.id == user_id))
        await session.commit()


async def test_me_profile_accepts_device_token(client: AsyncClient) -> None:
    user = _make_user(role=UserRole.admin)
    mock_db = _stub_db([_scalar(user)])

    async with _override_db(mock_db):
        response = await client.get(
            "/api/v1/me/profile",
            headers={"Authorization": "Bearer raw-device-token"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Test User"


async def test_me_profile_rejects_non_device_bearer(client: AsyncClient) -> None:
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        response = await client.get(
            "/api/v1/me/profile",
            headers={"Authorization": "Bearer legacy.jwt.value"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


async def test_revoke_current_device_without_logging_bearer(client: AsyncClient) -> None:
    user = _make_user(role=UserRole.admin)
    raw_device_token = "current-device-secret"
    mock_db = _stub_db([_scalar(user), MagicMock()])

    with capture_logs() as logs:
        async with _override_db(mock_db):
            response = await client.post(
                "/api/v1/auth/revoke",
                headers={"Authorization": f"Bearer {raw_device_token}"},
            )

    assert response.status_code == 204
    mock_db.commit.assert_awaited_once()
    update_statement = mock_db.execute.await_args_list[1].args[0]
    compiled_params = update_statement.compile().params.values()
    assert hash_token(raw_device_token) in compiled_params
    assert raw_device_token not in repr(logs)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/refresh"),
        ("POST", "/api/v1/auth/logout"),
        ("PUT", "/api/v1/auth/me/pin"),
        ("POST", "/api/v1/auth/pin/reset-request"),
        ("POST", "/api/v1/auth/pin/reset"),
    ],
)
async def test_pin_and_jwt_routes_are_absent(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    response = await client.request(method, path, json={})
    assert response.status_code == 404


async def test_require_admin_rejects_player_role() -> None:
    user = _make_user(role=UserRole.player)

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user)

    assert exc_info.value.status_code == 403


async def test_require_admin_passes_admin_role() -> None:
    user = _make_user(role=UserRole.admin)
    assert await require_admin(user) is user
