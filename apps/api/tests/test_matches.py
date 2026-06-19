"""Tests for match read endpoints."""

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
from src.models.match import Match, MatchStatus
from src.models.profile import PlayerRole, Profile
from src.models.team import Team, TournamentStage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player() -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = PlayerRole.player
    p.deleted_at = None
    return p


def _make_team(code: str, group_id: uuid.UUID | None = None) -> Team:
    t = MagicMock(spec=Team)
    t.id = uuid.uuid4()
    t.name = f"Team {code}"
    t.code = code
    t.flag_emoji = "🏳"
    t.group_id = group_id
    return t


def _make_match(
    home: Team | None,
    away: Team | None,
    match_num: int = 1,
    status: MatchStatus = MatchStatus.scheduled,
    kickoff: datetime | None = None,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = match_num
    m.stage = TournamentStage.group
    m.group_id = uuid.uuid4()
    m.home_team_id = home.id if home else None
    m.away_team_id = away.id if away else None
    m.home_team_placeholder = None
    m.away_team_placeholder = None
    m.kickoff_utc = kickoff or _now()
    m.venue = "Stadium"
    m.status = status
    m.actual_home_score = None
    m.actual_away_score = None
    m.extra_time = False
    m.penalties = False
    m.postponed_reason = None
    m.deleted_at = None
    return m


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    return mock_db


@asynccontextmanager
async def _override(mock_db: AsyncMock, player: Profile) -> AsyncGenerator[None, None]:
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_player] = lambda: player
    try:
        yield
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# list_matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_matches_returns_all() -> None:
    home, away = _make_team("MEX"), _make_team("RSA")
    match = _make_match(home, away, match_num=1)
    db = _stub_db([_scalars([match]), _scalars([home, away]), _scalars([])])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/matches", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["match_number"] == 1
    assert data[0]["home_team"]["code"] == "MEX"
    assert data[0]["away_team"]["code"] == "RSA"


@pytest.mark.asyncio
async def test_list_matches_invalid_stage_returns_422() -> None:
    db = _stub_db([])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/matches?stage=invalid", headers={"Authorization": "Bearer x"}
            )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# upcoming_matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upcoming_returns_scheduled_only() -> None:
    home, away = _make_team("BRA"), _make_team("MAR")
    scheduled_match = _make_match(home, away, status=MatchStatus.scheduled)
    db = _stub_db([_scalars([scheduled_match]), _scalars([home, away]), _scalars([])])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/matches/upcoming", headers={"Authorization": "Bearer x"}
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "scheduled"


# ---------------------------------------------------------------------------
# live_matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_matches() -> None:
    home, away = _make_team("USA"), _make_team("CAN")
    live_match = _make_match(home, away, status=MatchStatus.live)
    db = _stub_db([_scalars([live_match]), _scalars([home, away]), _scalars([])])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/matches/live", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "live"
    # U27.B1 — field is part of the contract; null until a minute source exists.
    assert data[0]["elapsed_minutes"] is None


# ---------------------------------------------------------------------------
# get_match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_match_found() -> None:
    home, away = _make_team("ENG"), _make_team("FRA")
    match = _make_match(home, away)
    db = _stub_db([_scalar_one(match), _scalars([home, away]), _scalars([])])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/matches/{match.id}", headers={"Authorization": "Bearer x"}
            )

    assert resp.status_code == 200
    assert resp.json()["id"] == str(match.id)


@pytest.mark.asyncio
async def test_get_match_not_found() -> None:
    db = _stub_db([_scalar_one(None)])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/matches/{uuid.uuid4()}", headers={"Authorization": "Bearer x"}
            )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/matches")
    assert resp.status_code in (401, 403)
