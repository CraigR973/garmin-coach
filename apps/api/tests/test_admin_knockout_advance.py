"""Tests for ``POST /api/v1/admin/knockout/advance`` (Phase 7.1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.match import Match
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import PlayerRole, Profile
from src.models.team import Team, TournamentStage
from src.routers.admin import get_fd_fetcher
from src.routers.groups import TeamStanding
from src.services.football_data import (
    FDMatch,
    FDMatchStatus,
    FDScore,
    FDScoreLine,
    FDTeam,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_admin() -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Admin"
    p.role = PlayerRole.admin
    p.deleted_at = None
    return p


def _team_standing(
    *,
    position: int,
    team_id: uuid.UUID,
    code: str,
    points: int = 9,
    gd: int = 3,
    gf: int = 5,
    played: int = 3,
) -> TeamStanding:
    return TeamStanding(
        position=position,
        team_id=str(team_id),
        team_name=f"Team {code}",
        team_code=code,
        flag_emoji="🏳",
        played=played,
        won=points // 3,
        drawn=points % 3,
        lost=0,
        gf=gf,
        ga=max(gf - gd, 0),
        gd=gd,
        points=points,
    )


def _make_team_orm(team_id: uuid.UUID, code: str) -> Team:
    t = MagicMock(spec=Team)
    t.id = team_id
    t.name = f"Team {code}"
    t.code = code
    t.flag_emoji = "🏳"
    return t


def _build_full_standings() -> tuple[dict[str, list[TeamStanding]], dict[uuid.UUID, Team]]:
    """Build twelve fully-played groups plus the matching ORM Team rows.

    Third-placed teams have descending points so the eight best are
    deterministically A3..H3 (drops I3..L3).
    """
    standings: dict[str, list[TeamStanding]] = {}
    team_rows: dict[uuid.UUID, Team] = {}

    for idx, letter in enumerate("ABCDEFGHIJKL"):
        # 4 teams per group: positions 1..4 with unique team_ids.
        positions: list[TeamStanding] = []
        for pos_idx in range(4):
            pos = pos_idx + 1
            code = f"{letter}{pos}"
            tid = uuid.uuid4()
            team_rows[tid] = _make_team_orm(tid, code)
            if pos == 3:
                # Third-placed: points decay across groups so A-H rank
                # above I-L deterministically.
                standing = _team_standing(
                    position=pos,
                    team_id=tid,
                    code=code,
                    points=6 - (idx // 4),  # A-D:6, E-H:5, I-L:4
                    gd=3 - idx,
                    gf=4,
                )
            elif pos == 1:
                standing = _team_standing(
                    position=pos, team_id=tid, code=code, points=9, gd=5, gf=8
                )
            elif pos == 2:
                standing = _team_standing(
                    position=pos, team_id=tid, code=code, points=6, gd=2, gf=5
                )
            else:
                standing = _team_standing(
                    position=pos, team_id=tid, code=code, points=0, gd=-7, gf=1
                )
            positions.append(standing)
        standings[letter] = positions

    return standings, team_rows


def _fd_r32_fixture(idx: int, kickoff: datetime, fd_id: int = 1000) -> FDMatch:
    return FDMatch(
        id=fd_id + idx,
        utcDate=kickoff,
        status=FDMatchStatus.SCHEDULED,
        stage="LAST_32",
        group=None,
        venue=None,
        lastUpdated=None,
        homeTeam=FDTeam(),
        awayTeam=FDTeam(),
        score=FDScore(
            winner=None,
            duration="REGULAR",
            fullTime=FDScoreLine(),
            halfTime=None,
            extraTime=None,
            penalties=None,
        ),
    )


def _build_fd_r32_fixtures(base: datetime, count: int = 16) -> list[FDMatch]:
    """Return ``count`` fixtures spread two hours apart starting at ``base``.

    A few non-R32 fixtures are mixed in to verify the stage filter.
    """
    out: list[FDMatch] = []
    for i in range(count):
        out.append(_fd_r32_fixture(i, base + timedelta(hours=i * 2)))
    # Pollute the feed with a couple of unrelated stages.
    out.append(
        FDMatch(
            id=9001,
            utcDate=base - timedelta(days=2),
            status=FDMatchStatus.FINISHED,
            stage="GROUP_STAGE",
            group="GROUP_A",
            venue=None,
            lastUpdated=None,
            homeTeam=FDTeam(),
            awayTeam=FDTeam(),
            score=FDScore(
                winner=None,
                duration="REGULAR",
                fullTime=FDScoreLine(),
                halfTime=None,
                extraTime=None,
                penalties=None,
            ),
        )
    )
    return out


def _stub_db(execute_results: list[Any], *, added: list[Any] | None = None) -> AsyncMock:
    """Mock AsyncSession.

    ``execute_results`` is a queue: each call to ``db.execute(...)``
    pops the next item, which is treated as the SQLAlchemy ``Result``
    proxy. For convenience the item may either be a pre-built mock or
    a raw list — lists are wrapped automatically.
    """
    added_sink = added if added is not None else []

    def _wrap(item: Any) -> Any:
        if isinstance(item, list):
            wrapper = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = item
            wrapper.scalars.return_value = scalars
            return wrapper
        return item

    queue = [_wrap(r) for r in execute_results]

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=queue)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    def _add(obj: Any) -> None:
        added_sink.append(obj)
        if isinstance(obj, Match) and obj.id is None:
            obj.id = uuid.uuid4()

    mock_db.add = MagicMock(side_effect=_add)
    return mock_db


@asynccontextmanager
async def _override(
    mock_db: AsyncMock,
    admin: Profile,
    fd_matches: list[FDMatch] | None,
) -> AsyncGenerator[None, None]:
    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def _fake_admin() -> Profile:
        return admin

    def _fake_fetcher_factory() -> Any:
        async def _fetch() -> list[FDMatch]:
            assert fd_matches is not None, "fetcher should not be called"
            return fd_matches

        return _fetch

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = _fake_admin
    app.dependency_overrides[get_fd_fetcher] = _fake_fetcher_factory
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_fd_fetcher, None)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_advance_creates_sixteen_r32_matches_with_teams_and_kickoffs(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _make_admin()
    standings, team_rows = _build_full_standings()

    # Patch the heavy standings loader so the endpoint test doesn't
    # have to mock 12 + 48 + 72 query results. _compute_standings is
    # tested separately by tests/test_groups.py.
    async def _fake_loader(_db: AsyncSession) -> dict[str, list[TeamStanding]]:
        return standings

    monkeypatch.setattr(
        "src.services.knockout_advancement._load_group_standings",
        _fake_loader,
    )

    base = _now() + timedelta(days=2)
    fd_fixtures = _build_fd_r32_fixtures(base)
    added: list[Any] = []
    db = _stub_db(
        execute_results=[
            [],  # _r32_match_count → no existing R32 matches
            list(team_rows.values()),  # resolve advancing teams
        ],
        added=added,
    )

    async with _override(db, admin, fd_fixtures):
        resp = await client.post(
            "/api/v1/admin/knockout/advance",
            json={"from_stage": "group"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["to_stage"] == "r32"
    assert len(body["matches"]) == 16

    created_matches = [obj for obj in added if isinstance(obj, Match)]
    assert len(created_matches) == 16
    match_numbers = sorted(m.match_number for m in created_matches)
    assert match_numbers == list(range(73, 89))

    for m in created_matches:
        assert m.stage == TournamentStage.r32
        assert m.home_team_id is not None
        assert m.away_team_id is not None
        assert m.kickoff_utc is not None
        assert m.football_data_match_id is not None
        assert m.home_team_placeholder in (
            {f"1{c}" for c in "ABCDEFGHIJKL"}
            | {f"2{c}" for c in "ABCDEFGHIJKL"}
            | {f"T{i}" for i in range(1, 9)}
        )

    # Audit log: one entry per created match, all with knockout_advanced.
    audit_rows = [obj for obj in added if isinstance(obj, AuditLog)]
    assert len(audit_rows) == 16
    for row in audit_rows:
        assert row.action_type == ActionType.knockout_advanced
        assert row.actor_type == ActorType.admin
        assert row.actor_id == admin.id
        assert row.changes is not None
        assert row.changes["stage"] == "r32"

    # commit invoked once after building all matches
    assert db.commit.await_count == 1
    assert db.flush.await_count == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_advance_returns_409_when_r32_already_exists(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _make_admin()
    standings, _ = _build_full_standings()

    async def _fake_loader(_db: AsyncSession) -> dict[str, list[TeamStanding]]:
        return standings

    monkeypatch.setattr(
        "src.services.knockout_advancement._load_group_standings",
        _fake_loader,
    )

    db = _stub_db(execute_results=[[MagicMock(spec=Match)]])  # one R32 match exists

    async with _override(db, admin, None):  # fetcher must not be called
        resp = await client.post(
            "/api/v1/admin/knockout/advance",
            json={"from_stage": "group"},
        )

    assert resp.status_code == 409
    assert "already" in resp.json()["detail"].lower()


async def test_advance_returns_422_when_group_stage_incomplete(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _make_admin()
    standings, _ = _build_full_standings()
    # Knock one team's played count back to 2 — group A still has a match left.
    standings["A"][0] = TeamStanding(**{**standings["A"][0].model_dump(), "played": 2})

    async def _fake_loader(_db: AsyncSession) -> dict[str, list[TeamStanding]]:
        return standings

    monkeypatch.setattr(
        "src.services.knockout_advancement._load_group_standings",
        _fake_loader,
    )

    db = _stub_db(execute_results=[[]])  # no existing R32 matches

    async with _override(db, admin, None):
        resp = await client.post(
            "/api/v1/admin/knockout/advance",
            json={"from_stage": "group"},
        )

    assert resp.status_code == 422
    assert "complete" in resp.json()["detail"].lower()


async def test_advance_returns_502_when_football_data_short_on_r32_fixtures(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _make_admin()
    standings, _ = _build_full_standings()

    async def _fake_loader(_db: AsyncSession) -> dict[str, list[TeamStanding]]:
        return standings

    monkeypatch.setattr(
        "src.services.knockout_advancement._load_group_standings",
        _fake_loader,
    )

    base = _now() + timedelta(days=2)
    fd_fixtures = _build_fd_r32_fixtures(base, count=3)  # only 3 R32 fixtures
    db = _stub_db(execute_results=[[]])

    async with _override(db, admin, fd_fixtures):
        resp = await client.post(
            "/api/v1/admin/knockout/advance",
            json={"from_stage": "group"},
        )

    assert resp.status_code == 502
    assert "fixtures" in resp.json()["detail"].lower()


async def test_advance_rejects_unsupported_from_stage(client: AsyncClient) -> None:
    admin = _make_admin()
    db = _stub_db(execute_results=[])  # never reached

    async with _override(db, admin, None):
        resp = await client.post(
            "/api/v1/admin/knockout/advance",
            json={"from_stage": "r32"},  # Phase 7.1: only "group" allowed
        )

    # Pydantic Literal validation rejects with 422 before our handler runs.
    assert resp.status_code == 422


async def test_advance_requires_admin(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/admin/knockout/advance",
        json={"from_stage": "group"},
    )
    assert resp.status_code in (401, 403)
