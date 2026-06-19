"""Tests for group standings endpoints and standings computation."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_player, require_admin
from src.database import get_db
from src.main import app
from src.models.group import Group
from src.models.match import Match, MatchStatus
from src.models.profile import PlayerRole, Profile
from src.models.team import Team, TournamentStage
from src.routers.groups import _compute_standings

# ---------------------------------------------------------------------------
# Helpers
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


def _make_admin() -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Admin"
    p.role = PlayerRole.admin
    p.deleted_at = None
    return p


def _make_team(code: str, group_id: uuid.UUID) -> Team:
    t = MagicMock(spec=Team)
    t.id = uuid.uuid4()
    t.name = f"Team {code}"
    t.code = code
    t.flag_emoji = "🏳"
    t.group_id = group_id
    return t


def _make_group(name: str = "A", override: list[str] | None = None) -> Group:
    g = MagicMock(spec=Group)
    g.id = uuid.uuid4()
    g.name = name
    g.standings_override = override
    return g


def _make_completed_match(
    home: Team,
    away: Team,
    home_score: int,
    away_score: int,
    group_id: uuid.UUID | None = None,
) -> Match:
    m = MagicMock(spec=Match)
    m.id = uuid.uuid4()
    m.match_number = 1
    m.stage = TournamentStage.group
    m.group_id = group_id
    m.home_team_id = home.id
    m.away_team_id = away.id
    m.kickoff_utc = _now()
    m.status = MatchStatus.completed
    m.actual_home_score = home_score
    m.actual_away_score = away_score
    m.extra_time = False
    m.penalties = False
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


@asynccontextmanager
async def _override_admin(mock_db: AsyncMock, admin: Profile) -> AsyncGenerator[None, None]:
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_player] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    try:
        yield
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Unit tests: _compute_standings
# ---------------------------------------------------------------------------


def test_standings_empty_group() -> None:
    gid = uuid.uuid4()
    teams = [_make_team("A", gid), _make_team("B", gid), _make_team("C", gid), _make_team("D", gid)]
    standings = _compute_standings(teams, [], None)
    assert len(standings) == 4
    for s in standings:
        assert s.played == 0
        assert s.points == 0


def test_standings_simple_win() -> None:
    gid = uuid.uuid4()
    mex = _make_team("MEX", gid)
    rsa = _make_team("RSA", gid)
    kor = _make_team("KOR", gid)
    cze = _make_team("CZE", gid)
    # MEX beats RSA 2-0
    match = _make_completed_match(mex, rsa, 2, 0, group_id=gid)
    standings = _compute_standings([mex, rsa, kor, cze], [match], None)
    by_code = {s.team_code: s for s in standings}
    assert by_code["MEX"].won == 1
    assert by_code["MEX"].points == 3
    assert by_code["MEX"].gf == 2
    assert by_code["MEX"].gd == 2
    assert by_code["RSA"].lost == 1
    assert by_code["RSA"].points == 0
    assert by_code["RSA"].gd == -2


def test_standings_draw() -> None:
    gid = uuid.uuid4()
    a = _make_team("AAA", gid)
    b = _make_team("BBB", gid)
    match = _make_completed_match(a, b, 1, 1, group_id=gid)
    standings = _compute_standings([a, b], [match], None)
    by_code = {s.team_code: s for s in standings}
    assert by_code["AAA"].drawn == 1
    assert by_code["AAA"].points == 1
    assert by_code["BBB"].drawn == 1
    assert by_code["BBB"].points == 1


def test_standings_sorted_by_points() -> None:
    gid = uuid.uuid4()
    a = _make_team("AAA", gid)
    b = _make_team("BBB", gid)
    c = _make_team("CCC", gid)
    # A beats B, A beats C
    m1 = _make_completed_match(a, b, 1, 0)
    m2 = _make_completed_match(a, c, 2, 0)
    standings = _compute_standings([a, b, c], [m1, m2], None)
    assert standings[0].team_code == "AAA"
    assert standings[0].points == 6


def test_standings_sorted_by_gd_after_points() -> None:
    gid = uuid.uuid4()
    a = _make_team("AAA", gid)
    b = _make_team("BBB", gid)
    c = _make_team("CCC", gid)
    # A beats C 1-0, B beats C 3-0 → A and B both have 3 pts; B has better GD
    m1 = _make_completed_match(a, c, 1, 0)
    m2 = _make_completed_match(b, c, 3, 0)
    standings = _compute_standings([a, b, c], [m1, m2], None)
    assert standings[0].team_code == "BBB"
    assert standings[1].team_code == "AAA"


def test_standings_override_reorders() -> None:
    gid = uuid.uuid4()
    a = _make_team("AAA", gid)
    b = _make_team("BBB", gid)
    # No matches — all tied at 0 pts; natural sort would put AAA first
    standings_no_override = _compute_standings([a, b], [], None)
    assert standings_no_override[0].team_code == "AAA"

    # Override puts BBB first
    standings_overridden = _compute_standings([a, b], [], ["BBB", "AAA"])
    assert standings_overridden[0].team_code == "BBB"
    assert standings_overridden[1].team_code == "AAA"


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_empty_standings() -> None:
    group = _make_group("A")
    db = _stub_db(
        [
            _scalars([group]),
            _scalars([]),  # teams
            _scalars([]),  # matches
        ]
    )
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/groups", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "A"
    assert data[0]["standings"] == []


@pytest.mark.asyncio
async def test_get_group_not_found() -> None:
    db = _stub_db([_scalar_one(None)])
    player = _make_player()

    async with _override(db, player):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/groups/Z", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_override_standings_sets_positions() -> None:
    group = _make_group("A")
    db = _stub_db([_scalar_one(group)])
    admin = _make_admin()

    async with _override_admin(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/groups/A/override-standings",
                json={"positions": ["MEX", "RSA", "KOR", "CZE"]},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 204
    # Verify the override was set on the group object
    assert group.standings_override == ["MEX", "RSA", "KOR", "CZE"]


@pytest.mark.asyncio
async def test_override_standings_group_not_found() -> None:
    db = _stub_db([_scalar_one(None)])
    admin = _make_admin()

    async with _override_admin(db, admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/groups/Z/override-standings",
                json={"positions": ["A", "B"]},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code == 404
