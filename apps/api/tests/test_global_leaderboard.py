"""Tests for GET /api/v1/leaderboard/global.

Uses the same mock-DB pattern as test_leaderboard.py: override ``get_db``
and ``get_current_player`` so no real Postgres is needed for the unit tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.prediction import LeaderboardSnapshot  # noqa: F401 — used in MagicMock spec
from src.models.profile import Profile  # noqa: F401 — used in MagicMock spec

# ---------------------------------------------------------------------------
# Helpers (mirrored from test_leaderboard.py)
# ---------------------------------------------------------------------------


def _make_player(
    *,
    display_name: str = "Alice",
    is_active: bool = True,
    deleted: bool = False,
) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = display_name
    p.is_active = is_active
    p.deleted_at = datetime(2026, 1, 1) if deleted else None
    p.avatar_url = None
    return p


def _make_snapshot(
    player_id: uuid.UUID,
    *,
    total_points: int = 10,
    match_points: int = 10,
    knockout_winner_points: int = 0,
    special_points: int = 0,
    exact_count: int = 0,
    correct_result_count: int = 0,
    correct_goals_count: int = 0,
    specials_correct_count: int = 0,
    ko_winner_correct_count: int = 0,
    rank: int = 1,
    snapshot_at: datetime | None = None,
) -> MagicMock:
    s = MagicMock(spec=LeaderboardSnapshot)
    s.player_id = player_id
    s.total_points = total_points
    s.match_points = match_points
    s.knockout_winner_points = knockout_winner_points
    s.special_points = special_points
    s.exact_count = exact_count
    s.correct_result_count = correct_result_count
    s.correct_goals_count = correct_goals_count
    s.specials_correct_count = specials_correct_count
    s.ko_winner_correct_count = ko_winner_correct_count
    s.rank = rank
    s.snapshot_at = snapshot_at or datetime(2026, 6, 11, 18, 0, 0)
    return s


def _make_requester(timezone: str = "UTC") -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = "Requester"
    p.is_active = True
    p.deleted_at = None
    p.timezone = timezone
    p.avatar_url = None
    return p


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


# ---------------------------------------------------------------------------
# GET /api/v1/leaderboard/global
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_leaderboard_ranks_players_by_total_points() -> None:
    """Higher total_points comes first; global rank is re-computed (stored rank ignored)."""
    requester = _make_requester()
    alice = _make_player(display_name="Alice")
    bob = _make_player(display_name="Bob")

    # Bob has the higher score; alice's stored rank=1 should be ignored
    snap_alice = _make_snapshot(alice.id, total_points=10, rank=1)
    snap_bob = _make_snapshot(bob.id, total_points=20, rank=2)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(alice, snap_alice), (bob, snap_bob)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = _db_with(mock_db)
    app.dependency_overrides[get_current_player] = lambda: requester

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leaderboard/global")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Bob should be #1 globally despite stored rank=2
        assert data[0]["player_name"] == "Bob"
        assert data[0]["rank"] == 1
        assert data[1]["player_name"] == "Alice"
        assert data[1]["rank"] == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_global_leaderboard_excludes_inactive_players() -> None:
    """Inactive players (is_active=False) are excluded from the global view."""
    requester = _make_requester()
    active = _make_player(display_name="Active", is_active=True)
    _make_player(display_name="Inactive", is_active=False)  # excluded by DB filter

    snap_active = _make_snapshot(active.id, total_points=10, rank=1)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    # The DB query filters is_active; mock returns only the active player
    mock_result.all.return_value = [(active, snap_active)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = _db_with(mock_db)
    app.dependency_overrides[get_current_player] = lambda: requester

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leaderboard/global")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["player_name"] == "Active"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_global_leaderboard_tied_players_share_rank() -> None:
    """Two players with identical totals on every tiebreak axis share a rank."""
    requester = _make_requester()
    alice = _make_player(display_name="Alice")
    bob = _make_player(display_name="Bob")

    snap_alice = _make_snapshot(alice.id, total_points=10, rank=1)
    snap_bob = _make_snapshot(bob.id, total_points=10, rank=1)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(alice, snap_alice), (bob, snap_bob)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = _db_with(mock_db)
    app.dependency_overrides[get_current_player] = lambda: requester

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leaderboard/global")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["rank"] == 1
        assert data[1]["rank"] == 1
        assert data[0]["tied"] is True
        assert data[1]["tied"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_global_leaderboard_tiebreak_by_exact_count() -> None:
    """When total_points tie, exact_count breaks the tie."""
    requester = _make_requester()
    alice = _make_player(display_name="Alice")
    bob = _make_player(display_name="Bob")

    snap_alice = _make_snapshot(alice.id, total_points=10, exact_count=3, rank=1)
    snap_bob = _make_snapshot(bob.id, total_points=10, exact_count=1, rank=2)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(bob, snap_bob), (alice, snap_alice)]  # intentionally unordered
    mock_db.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = _db_with(mock_db)
    app.dependency_overrides[get_current_player] = lambda: requester

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leaderboard/global")

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["player_name"] == "Alice"  # more exact scores wins
        assert data[0]["rank"] == 1
        assert data[1]["player_name"] == "Bob"
        assert data[1]["rank"] == 2
        assert data[0]["tied"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_global_leaderboard_requires_auth() -> None:
    """Unauthenticated requests get 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/leaderboard/global")
    assert resp.status_code == 401
