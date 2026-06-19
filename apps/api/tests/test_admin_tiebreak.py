"""U38.4 — admin tiebreak-override endpoints (HTTP layer, mocked session).

The override→recompute→re-rank behaviour against a real database lives in
``test_tiebreak_cascade.test_admin_override_breaks_all_axis_tie``. These cover
the route wiring: auth, league/member resolution, upsert, and the response
shape, with a mocked ``AsyncSession`` so no live DB is required.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole, Profile


def _make_admin() -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.role = PlayerRole.admin
    return p


def _result(scalar: object = None, rows: list[object] | None = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.all.return_value = rows or []
    return r


@asynccontextmanager
async def _client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    async def _get_db_override() -> AsyncIterator[AsyncMock]:
        yield mock_db

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[require_admin] = _make_admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)


def _base_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.delete = AsyncMock()
    return mock_db


@pytest.mark.asyncio
async def test_set_override_creates_and_recomputes() -> None:
    league = MagicMock()
    league.id = uuid.uuid4()
    player = MagicMock(spec=Profile)
    player.display_name = "Alice"
    pid = uuid.uuid4()

    mock_db = _base_db()
    # execute order: league lookup, member lookup, existing-override lookup,
    # then the recompute INSERT...SELECT.
    mock_db.execute = AsyncMock(
        side_effect=[_result(league), _result(player), _result(None), _result()]
    )

    async with _client(mock_db) as client:
        resp = await client.put(
            f"/api/v1/admin/leagues/steele-spreadsheet/tiebreak/{pid}",
            json={"manual_order": 1, "reason": "coin toss declined"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["manual_order"] == 1
    assert body["player_name"] == "Alice"
    assert body["league_slug"] == "steele-spreadsheet"
    assert mock_db.add.call_count == 2  # new override row + audit log
    mock_db.commit.assert_awaited()  # persisted after recompute


@pytest.mark.asyncio
async def test_set_override_updates_existing() -> None:
    league = MagicMock()
    league.id = uuid.uuid4()
    player = MagicMock(spec=Profile)
    player.display_name = "Bob"
    existing = MagicMock()
    existing.manual_order = 9
    pid = uuid.uuid4()

    mock_db = _base_db()
    mock_db.execute = AsyncMock(
        side_effect=[_result(league), _result(player), _result(existing), _result()]
    )

    async with _client(mock_db) as client:
        resp = await client.put(
            f"/api/v1/admin/leagues/steele-spreadsheet/tiebreak/{pid}",
            json={"manual_order": 2},
        )

    assert resp.status_code == 200
    assert existing.manual_order == 2  # mutated in place, not a second insert
    mock_db.add.assert_called_once()  # only the audit log is added


@pytest.mark.asyncio
async def test_set_override_unknown_league_404() -> None:
    mock_db = _base_db()
    mock_db.execute = AsyncMock(side_effect=[_result(None)])  # league lookup fails

    async with _client(mock_db) as client:
        resp = await client.put(
            f"/api/v1/admin/leagues/nope/tiebreak/{uuid.uuid4()}",
            json={"manual_order": 1},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_override_non_member_404() -> None:
    league = MagicMock()
    league.id = uuid.uuid4()
    mock_db = _base_db()
    # league found, but the player is not an active member.
    mock_db.execute = AsyncMock(side_effect=[_result(league), _result(None)])

    async with _client(mock_db) as client:
        resp = await client.put(
            f"/api/v1/admin/leagues/steele-spreadsheet/tiebreak/{uuid.uuid4()}",
            json={"manual_order": 1},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clear_override_404_when_absent() -> None:
    league = MagicMock()
    league.id = uuid.uuid4()
    mock_db = _base_db()
    mock_db.execute = AsyncMock(side_effect=[_result(league), _result(None)])

    async with _client(mock_db) as client:
        resp = await client.delete(
            f"/api/v1/admin/leagues/steele-spreadsheet/tiebreak/{uuid.uuid4()}",
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_overrides_returns_rows() -> None:
    league = MagicMock()
    league.id = uuid.uuid4()
    ovr = MagicMock()
    ovr.player_id = uuid.uuid4()
    ovr.manual_order = 1
    ovr.reason = "decider lost"
    profile = MagicMock(spec=Profile)
    profile.display_name = "Carol"

    mock_db = _base_db()
    mock_db.execute = AsyncMock(side_effect=[_result(league), _result(rows=[(ovr, profile)])])

    async with _client(mock_db) as client:
        resp = await client.get("/api/v1/admin/leagues/steele-spreadsheet/tiebreak-overrides")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["player_name"] == "Carol"
    assert data[0]["manual_order"] == 1


@pytest.mark.asyncio
async def test_set_override_requires_admin() -> None:
    """Without the admin override the route is gated (401/403)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/admin/leagues/steele-spreadsheet/tiebreak/{uuid.uuid4()}",
            json={"manual_order": 1},
        )
    assert resp.status_code in (401, 403)
