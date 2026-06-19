"""Tests for U12 join-by-code endpoints.

Covers:
- GET /api/v1/leagues/by-code/{code}  (public)
- POST /api/v1/leagues/join-by-code   (authenticated, multi-use)
- POST /api/v1/leagues/{slug}/join-code/rotate  (admin)
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.league import League, LeaguePrivacy
from src.models.league_membership import LeagueMemberRole, LeagueMembership
from src.models.profile import PlayerRole, Profile, SiteRole
from src.routers.leagues import require_league_admin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(*, is_admin: bool = False) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = PlayerRole.admin if is_admin else PlayerRole.player
    p.site_role = SiteRole.user
    p.deleted_at = None
    return p


def _make_league(*, join_code: str = "ABCDE2", max_members: int = 15) -> MagicMock:
    lg = MagicMock(spec=League)
    lg.id = uuid.uuid4()
    lg.slug = "test-league"
    lg.name = "Test League"
    lg.description = None
    lg.privacy = LeaguePrivacy.private
    lg.max_members = max_members
    lg.join_code = join_code
    lg.deleted_at = None
    lg.updated_at = _now()
    return lg


def _make_membership(league_id: uuid.UUID, player_id: uuid.UUID) -> MagicMock:
    m = MagicMock(spec=LeagueMembership)
    m.id = uuid.uuid4()
    m.league_id = league_id
    m.player_id = player_id
    m.role = LeagueMemberRole.admin
    m.deleted_at = None
    m.joined_at = _now()
    return m


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


@asynccontextmanager
async def _override_db(mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@asynccontextmanager
async def _override_player(player: MagicMock) -> AsyncGenerator[None, None]:
    app.dependency_overrides[get_current_player] = lambda: player
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_player, None)


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_count(value: int) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar.return_value = value
    return r


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/by-code/{code}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_by_code_found() -> None:
    league = _make_league(join_code="ABCDE2", max_members=10)
    mock_db = _stub_db([_scalar(league), _scalar_count(3)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leagues/by-code/ABCDE2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test League"
    assert data["member_count"] == 3
    assert data["max_members"] == 10


@pytest.mark.asyncio
async def test_by_code_case_insensitive() -> None:
    league = _make_league(join_code="ABCDE2")
    mock_db = _stub_db([_scalar(league), _scalar_count(1)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leagues/by-code/abcde2")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_by_code_not_found() -> None:
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leagues/by-code/ZZZZZZ")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/join-by-code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_by_code_success() -> None:
    player = _make_player()
    league = _make_league(join_code="ABCDE2", max_members=10)
    mock_db = _stub_db(
        [
            _scalar(league),  # league lookup
            _scalar(None),  # existing membership check (not a member)
            _scalar_count(3),  # active_member_count
            _scalar(None),  # upsert_membership - no existing row
            _scalars([]),  # notify_member_joined: _admin_players query
        ]
    )

    async with _override_db(mock_db), _override_player(player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/leagues/join-by-code",
                json={"code": "ABCDE2"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["league_slug"] == "test-league"
    assert data["league_name"] == "Test League"


@pytest.mark.asyncio
async def test_join_by_code_multiuse() -> None:
    """Two different players can join using the same code."""
    league = _make_league(join_code="ABCDE2", max_members=10)

    for _ in range(2):
        player = _make_player()
        mock_db = _stub_db(
            [
                _scalar(league),
                _scalar(None),
                _scalar_count(3),
                _scalar(None),
                _scalars([]),  # notify_member_joined: _admin_players query
            ]
        )
        async with _override_db(mock_db), _override_player(player):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/leagues/join-by-code",
                    json={"code": "ABCDE2"},
                )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_join_by_code_already_member() -> None:
    player = _make_player()
    league = _make_league(join_code="ABCDE2")
    membership = _make_membership(league.id, player.id)
    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(membership),  # already a member
        ]
    )

    async with _override_db(mock_db), _override_player(player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/leagues/join-by-code",
                json={"code": "ABCDE2"},
            )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "ALREADY_MEMBER"


@pytest.mark.asyncio
async def test_join_by_code_league_full() -> None:
    player = _make_player()
    league = _make_league(join_code="ABCDE2", max_members=5)
    mock_db = _stub_db(
        [
            _scalar(league),
            _scalar(None),  # not a member
            _scalar_count(5),  # at capacity
        ]
    )

    async with _override_db(mock_db), _override_player(player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/leagues/join-by-code",
                json={"code": "ABCDE2"},
            )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "LEAGUE_FULL"


@pytest.mark.asyncio
async def test_join_by_code_invalid_code() -> None:
    player = _make_player()
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db), _override_player(player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/leagues/join-by-code",
                json={"code": "ZZZZZZ"},
            )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/leagues/{slug}/join-code/rotate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_join_code_success() -> None:
    player = _make_player(is_admin=True)
    league = _make_league(join_code="ABCDE2")

    mock_db = _stub_db([])

    app.dependency_overrides[require_league_admin] = lambda: (player, league)
    try:
        async with _override_db(mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/leagues/test-league/join-code/rotate")
    finally:
        app.dependency_overrides.pop(require_league_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert "join_code" in data
    assert len(data["join_code"]) == 6
