"""Tests for R12 — Backend tenant isolation.

R12.1: legacy global read endpoints scoped to shared-league players.
R12.2: departed members drop off the leaderboard they left.
R12.3: private leagues return 404 to non-members; public leagues unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.league import League, LeaguePrivacy
from src.models.league_membership import LeagueMembership
from src.models.match import Match, MatchStatus
from src.models.profile import PlayerRole, Profile
from src.routers.leagues import require_league_member

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _profile(
    player_id: uuid.UUID | None = None,
    *,
    site_role: object = None,
    is_active: bool = True,
) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = player_id or uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = PlayerRole.player
    p.site_role = site_role
    p.is_active = is_active
    p.timezone = "UTC"
    p.created_at = datetime(2026, 1, 1)
    p.deleted_at = None
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    return p


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _rows(items: list) -> MagicMock:
    r = MagicMock()
    r.all.return_value = items
    return r


def _stub_db(side_effects: list) -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=side_effects)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)
    db.add = MagicMock()
    return db


@asynccontextmanager
async def _override(player: MagicMock, mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_player] = lambda: player
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_player, None)


# ---------------------------------------------------------------------------
# R12.1 — shared-league scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_player_cross_league_returns_403() -> None:
    """GET /players/{id} returns 403 when requester shares no league with target."""
    requester = _profile()
    target_id = uuid.uuid4()
    target = _profile(target_id)

    mock_db = _stub_db([_scalar(target)])

    with patch(
        "src.routers.players.shared_league_player_ids",
        return_value=frozenset({requester.id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/players/{target_id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_player_same_league_returns_200() -> None:
    """GET /players/{id} returns 200 when target is in a shared league."""
    requester = _profile()
    target_id = uuid.uuid4()
    target = _profile(target_id)

    mock_db = _stub_db([_scalar(target)])

    with patch(
        "src.routers.players.shared_league_player_ids",
        return_value=frozenset({requester.id, target_id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/players/{target_id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_recent_predictions_cross_league_returns_403() -> None:
    """GET /players/{id}/predictions/recent returns 403 for cross-league target."""
    requester = _profile()
    target_id = uuid.uuid4()

    mock_db = _stub_db([_scalar(_profile(target_id))])

    with patch(
        "src.routers.players.shared_league_player_ids",
        return_value=frozenset({requester.id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/players/{target_id}/predictions/recent",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_stats_cross_league_returns_403() -> None:
    """GET /stats/{id} returns 403 for a player in a different league."""
    requester = _profile()
    target_id = uuid.uuid4()

    mock_db = _stub_db([_scalar(_profile(target_id))])

    with patch(
        "src.routers.stats.shared_league_player_ids",
        return_value=frozenset({requester.id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/stats/{target_id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_player_predictions_cross_league_returns_403() -> None:
    """GET /predictions/player/{id} returns 403 for cross-league target."""
    requester = _profile()
    target_id = uuid.uuid4()

    mock_db = _stub_db([_scalar(_profile(target_id))])

    with patch(
        "src.routers.predictions.shared_league_player_ids",
        return_value=frozenset({requester.id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/predictions/player/{target_id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_match_predictions_filters_cross_league_players() -> None:
    """GET /predictions/match/{id} omits predictions from players not in any shared league."""
    requester = _profile()
    shared_id = uuid.uuid4()
    other_id = uuid.uuid4()

    match = MagicMock(spec=Match)
    match.id = uuid.uuid4()
    match.status = MatchStatus.completed
    # Completed ⇒ already kicked off; the shared reveal gate keys on kickoff.
    match.kickoff_utc = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)

    shared_pred = MagicMock()
    shared_pred.player_id = shared_id
    shared_pred.predicted_home = 1
    shared_pred.predicted_away = 0
    shared_pred.points_awarded = 7
    shared_pred.points_breakdown = {}

    other_pred = MagicMock()
    other_pred.player_id = other_id
    other_pred.predicted_home = 2
    other_pred.predicted_away = 1
    other_pred.points_awarded = 3
    other_pred.points_breakdown = {}

    shared_profile = MagicMock()
    shared_profile.display_name = "SharedPlayer"
    other_profile = MagicMock()
    other_profile.display_name = "OtherPlayer"

    mock_db = _stub_db(
        [
            _scalar(match),
            _rows([(shared_pred, shared_profile), (other_pred, other_profile)]),
        ]
    )

    with patch(
        "src.routers.predictions.shared_league_player_ids",
        return_value=frozenset({requester.id, shared_id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    data = resp.json()
    player_names = {p["player_name"] for p in data["predictions"]}
    assert "SharedPlayer" in player_names
    assert "OtherPlayer" not in player_names


@pytest.mark.asyncio
async def test_match_knockout_predictions_filters_cross_league_players() -> None:
    """GET /knockout-predictions/match/{id} omits cross-league players."""
    requester = _profile()
    shared_id = uuid.uuid4()
    other_id = uuid.uuid4()

    match = MagicMock(spec=Match)
    match.id = uuid.uuid4()
    match.status = MatchStatus.completed
    match.kickoff_utc = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)

    shared_pred = MagicMock()
    shared_pred.player_id = shared_id
    shared_pred.predicted_winner_id = uuid.uuid4()
    shared_pred.points_awarded = 10

    other_pred = MagicMock()
    other_pred.player_id = other_id
    other_pred.predicted_winner_id = uuid.uuid4()
    other_pred.points_awarded = 0

    shared_profile = MagicMock()
    shared_profile.display_name = "SharedKoPlayer"
    other_profile = MagicMock()
    other_profile.display_name = "OtherKoPlayer"

    mock_db = _stub_db(
        [
            _scalar(match),
            _rows([(shared_pred, shared_profile), (other_pred, other_profile)]),
        ]
    )

    with patch(
        "src.routers.knockout_predictions.shared_league_player_ids",
        return_value=frozenset({requester.id, shared_id}),
    ):
        async with _override(requester, mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/knockout-predictions/match/{match.id}",
                    headers={"Authorization": "Bearer x"},
                )

    assert resp.status_code == 200
    data = resp.json()
    player_names = {p["player_name"] for p in data["predictions"]}
    assert "SharedKoPlayer" in player_names
    assert "OtherKoPlayer" not in player_names


# ---------------------------------------------------------------------------
# R12.2 — departed members drop off the leaderboard (DB-backed)
# ---------------------------------------------------------------------------


async def _new_profile(conn: AsyncConnection, name: str) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                """
                INSERT INTO profiles (
                    id, display_name, pin_hash, role, email,
                    first_name, last_name, site_role
                )
                VALUES (
                    gen_random_uuid(), :name,
                    '$2b$12$0000000000000000000000000000000000000000000000000000',
                    CAST('player' AS player_role), :email,
                    'Test', 'User', CAST('user' AS site_role)
                )
                RETURNING id
                """
            ),
            {"name": name, "email": f"r12_{name}@test.invalid"},
        )
    ).scalar_one()


async def _new_league(conn: AsyncConnection, slug: str, creator_id: uuid.UUID) -> uuid.UUID:
    league_id = (
        await conn.execute(
            text(
                """
                INSERT INTO leagues (id, slug, name, created_by)
                VALUES (gen_random_uuid(), :slug, :name, :p)
                RETURNING id
                """
            ),
            {"slug": slug, "name": slug, "p": str(creator_id)},
        )
    ).scalar_one()
    await conn.execute(
        text(
            """
            INSERT INTO league_memberships (id, league_id, player_id, role)
            VALUES (gen_random_uuid(), :l, :p, CAST('player' AS league_member_role))
            ON CONFLICT (league_id, player_id) DO NOTHING
            """
        ),
        {"l": str(league_id), "p": str(creator_id)},
    )
    return league_id


async def _add_member(conn: AsyncConnection, league_id: uuid.UUID, player_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO league_memberships (id, league_id, player_id, role)
            VALUES (gen_random_uuid(), :l, :p, CAST('player' AS league_member_role))
            ON CONFLICT (league_id, player_id) DO NOTHING
            """
        ),
        {"l": str(league_id), "p": str(player_id)},
    )


async def _soft_delete_membership(
    conn: AsyncConnection, league_id: uuid.UUID, player_id: uuid.UUID
) -> None:
    await conn.execute(
        text(
            "UPDATE league_memberships SET deleted_at = now() "
            "WHERE league_id = :l AND player_id = :p AND deleted_at IS NULL"
        ),
        {"l": str(league_id), "p": str(player_id)},
    )


async def _insert_snapshot(
    conn: AsyncConnection,
    player_id: uuid.UUID,
    league_id: uuid.UUID,
    points: int,
    rank: int,
    snapshot_at: datetime,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO leaderboard_snapshots (
                id, player_id, league_id, total_points, match_points,
                knockout_winner_points, special_points, rank,
                snapshot_at, triggered_by_match_id
            )
            VALUES (gen_random_uuid(), :p, :l, :pts, :pts, 0, 0, :rank, :t, NULL)
            """
        ),
        {"p": str(player_id), "l": str(league_id), "pts": points, "rank": rank, "t": snapshot_at},
    )


@pytest.mark.asyncio
async def test_departed_member_drops_off_leaderboard(db_conn: AsyncConnection) -> None:
    """Soft-deleting a membership removes that player from the leaderboard."""
    alice_id = await _new_profile(db_conn, "r12_alice")
    bob_id = await _new_profile(db_conn, "r12_bob")

    league_id = await _new_league(db_conn, "r12-depart-league", alice_id)
    await _add_member(db_conn, league_id, bob_id)

    t = datetime(2026, 6, 16, 18, 0, 0)
    await _insert_snapshot(db_conn, alice_id, league_id, 20, 1, t)
    await _insert_snapshot(db_conn, bob_id, league_id, 10, 2, t)

    # Verify both are on the board before departure
    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    requester = MagicMock(spec=Profile)
    requester.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    requester.id = alice_id
    requester.site_role = None
    requester.deleted_at = None

    slug = "r12-depart-league"

    async def _db():  # type: ignore[no-untyped-def]
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_league_member] = lambda: (
        requester,
        MagicMock(id=league_id),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{slug}/leaderboard")
        assert resp.status_code == 200
        names_before = {e["player_name"] for e in resp.json()}
        assert "r12_alice" in names_before
        assert "r12_bob" in names_before
    finally:
        app.dependency_overrides.clear()

    await session.close()

    # Bob leaves the league
    await _soft_delete_membership(db_conn, league_id, bob_id)

    session2 = AsyncSession(bind=db_conn, expire_on_commit=False)
    app.dependency_overrides[get_db] = lambda: (x for x in [session2])

    async def _db2():  # type: ignore[no-untyped-def]
        yield session2

    app.dependency_overrides[get_db] = _db2
    app.dependency_overrides[require_league_member] = lambda: (
        requester,
        MagicMock(id=league_id),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/leagues/{slug}/leaderboard")
        assert resp.status_code == 200
        names_after = {e["player_name"] for e in resp.json()}
        assert "r12_alice" in names_after
        assert "r12_bob" not in names_after, f"departed member still on board: {resp.json()}"
    finally:
        app.dependency_overrides.clear()
        await session2.close()


# ---------------------------------------------------------------------------
# R12.3 — private league 404 for non-members
# ---------------------------------------------------------------------------


def _league(privacy: LeaguePrivacy = LeaguePrivacy.private) -> MagicMock:
    lg = MagicMock(spec=League)
    lg.id = uuid.uuid4()
    lg.slug = "secret-league"
    lg.name = "Secret League"
    lg.description = None
    lg.privacy = privacy
    lg.max_members = 15
    lg.created_by = uuid.uuid4()
    lg.created_at = datetime(2026, 1, 1)
    lg.join_code = "ABCDE2"
    lg.updated_at = datetime(2026, 1, 1)
    lg.deleted_at = None
    return lg


@pytest.mark.asyncio
async def test_private_league_non_member_gets_404() -> None:
    """Non-member requesting a private league by slug gets 404."""
    player = _profile()
    league = _league(privacy=LeaguePrivacy.private)

    mock_db = _stub_db(
        [
            # _resolve_league
            _scalar(league),
            # _resolve_active_membership (non-member)
            _scalar(None),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leagues/secret-league")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_private_league_member_gets_200() -> None:
    """Active member of a private league can still see it."""
    player = _profile()
    league = _league(privacy=LeaguePrivacy.private)
    membership = MagicMock(spec=LeagueMembership)
    membership.role = MagicMock()
    membership.role.value = "player"
    membership.display_name_override = None
    membership.joined_at = datetime(2026, 1, 1)
    membership.deleted_at = None

    mock_db = _stub_db(
        [
            # _resolve_league
            _scalar(league),
            # _resolve_active_membership (is member)
            _scalar(membership),
            # _active_member_count
            _scalar_one(1),
            # member list
            _rows([(membership, player)]),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leagues/secret-league")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_public_open_league_non_member_gets_200() -> None:
    """Non-member can see a public_open league (name/description visible)."""
    player = _profile()
    league = _league(privacy=LeaguePrivacy.public_open)

    mock_db = _stub_db(
        [
            # _resolve_league
            _scalar(league),
            # _resolve_active_membership (not a member)
            _scalar(None),
            # _active_member_count
            _scalar_one(3),
        ]
    )

    async with _override(player, mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/leagues/secret-league")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Secret League"
    assert body["members"] is None
