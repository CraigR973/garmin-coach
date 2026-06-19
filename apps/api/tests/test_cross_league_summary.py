"""Tests for GET /api/v1/me/cross-league-summary (M5).

Mock-based tests pin the averaging rules (exclude leagues below the minimum
member count, tie-break math, empty case) and run without a database. The
DB-backed test seeds three real leagues to prove the SQL and the average-rank
acceptance criterion end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.profile import Profile

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _player() -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Caller"
    return p


def _result(rows: list[object]) -> MagicMock:
    r = MagicMock()
    r.all.return_value = rows
    return r


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


def _mock_db_for(
    memberships: list[SimpleNamespace],
    counts: list[SimpleNamespace],
    snapshots: list[SimpleNamespace],
) -> AsyncMock:
    """A mock DB that answers the endpoint's three queries in order.

    When there are no memberships the endpoint returns early after one query,
    so only the first result is consumed.
    """
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[_result(memberships), _result(counts), _result(snapshots)]
    )
    return mock_db


async def _get_summary(mock_db: AsyncMock) -> dict[str, object]:
    app.dependency_overrides[get_current_player] = _player
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/me/cross-league-summary")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Averaging rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_averages_rank_across_leagues() -> None:
    """Three leagues, all with >= 3 members, ranks 2/1/3 → average 2.0."""
    l1, l2, l3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    memberships = [
        SimpleNamespace(id=l1, slug="alpha", name="Alpha"),
        SimpleNamespace(id=l2, slug="bravo", name="Bravo"),
        SimpleNamespace(id=l3, slug="charlie", name="Charlie"),
    ]
    counts = [
        SimpleNamespace(league_id=l1, member_count=5),
        SimpleNamespace(league_id=l2, member_count=4),
        SimpleNamespace(league_id=l3, member_count=3),
    ]
    snapshots = [
        SimpleNamespace(league_id=l1, rank=2, total_points=100, triggered_by_match_id=None),
        SimpleNamespace(league_id=l2, rank=1, total_points=100, triggered_by_match_id=None),
        SimpleNamespace(league_id=l3, rank=3, total_points=100, triggered_by_match_id=None),
    ]

    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))

    assert data["avg_rank"] == 2.0
    assert data["total_points"] == 100
    assert data["leagues_count"] == 3
    assert len(data["per_league"]) == 3
    assert {pl["slug"] for pl in data["per_league"]} == {"alpha", "bravo", "charlie"}


@pytest.mark.asyncio
async def test_summary_excludes_small_leagues_from_average() -> None:
    """A league below the 3-member floor still appears, but not in the mean."""
    big, tiny = uuid.uuid4(), uuid.uuid4()
    memberships = [
        SimpleNamespace(id=big, slug="big", name="Big"),
        SimpleNamespace(id=tiny, slug="tiny", name="Tiny"),
    ]
    counts = [
        SimpleNamespace(league_id=big, member_count=5),
        SimpleNamespace(league_id=tiny, member_count=1),
    ]
    snapshots = [
        SimpleNamespace(league_id=big, rank=4, total_points=42, triggered_by_match_id=None),
        SimpleNamespace(league_id=tiny, rank=1, total_points=42, triggered_by_match_id=None),
    ]

    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))

    # Only the 5-member league counts toward the average → 4.0, not (4+1)/2.
    assert data["avg_rank"] == 4.0
    assert data["leagues_count"] == 2
    tiny_entry = next(pl for pl in data["per_league"] if pl["slug"] == "tiny")
    assert tiny_entry["rank"] == 1  # shown in the breakdown
    assert tiny_entry["member_count"] == 1


@pytest.mark.asyncio
async def test_summary_avg_null_when_no_qualifying_league() -> None:
    """If every league is below the floor, avg_rank is null (not a divide-by-zero)."""
    only = uuid.uuid4()
    memberships = [SimpleNamespace(id=only, slug="duo", name="Duo")]
    counts = [SimpleNamespace(league_id=only, member_count=2)]
    snapshots = [
        SimpleNamespace(league_id=only, rank=1, total_points=7, triggered_by_match_id=None)
    ]

    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))

    assert data["avg_rank"] is None
    assert data["total_points"] == 7
    assert data["leagues_count"] == 1


@pytest.mark.asyncio
async def test_summary_empty_when_no_leagues() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_result([]))

    data = await _get_summary(mock_db)

    assert data == {
        "avg_rank": None,
        "total_points": 0,
        "leagues_count": 0,
        "per_league": [],
    }


@pytest.mark.asyncio
async def test_summary_rank_null_when_no_snapshot_yet() -> None:
    """A league the player joined but has no scored result in yet → rank null,
    and it does not poison the average."""
    scored, fresh = uuid.uuid4(), uuid.uuid4()
    memberships = [
        SimpleNamespace(id=scored, slug="scored", name="Scored"),
        SimpleNamespace(id=fresh, slug="fresh", name="Fresh"),
    ]
    counts = [
        SimpleNamespace(league_id=scored, member_count=4),
        SimpleNamespace(league_id=fresh, member_count=4),
    ]
    snapshots = [
        SimpleNamespace(league_id=scored, rank=2, total_points=30, triggered_by_match_id=None)
    ]

    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))

    assert data["avg_rank"] == 2.0  # only the scored league contributes
    fresh_entry = next(pl for pl in data["per_league"] if pl["slug"] == "fresh")
    assert fresh_entry["rank"] is None


@pytest.mark.asyncio
async def test_summary_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/me/cross-league-summary")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# DB-backed: real fixture with three leagues
# ---------------------------------------------------------------------------


async def _profile(conn: AsyncConnection, name: str) -> uuid.UUID:
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
                    CAST('player' AS player_role),
                    :email,
                    'Test',
                    'User',
                    CAST('user' AS site_role)
                )
                RETURNING id
                """
            ),
            {"name": name, "email": f"{name}@test.invalid"},
        )
    ).scalar_one()


async def _league(conn: AsyncConnection, slug: str, creator: uuid.UUID) -> uuid.UUID:
    league_id = (
        await conn.execute(
            text(
                """
                INSERT INTO leagues (id, slug, name, created_by)
                VALUES (gen_random_uuid(), :slug, :slug, :p)
                RETURNING id
                """
            ),
            {"slug": slug, "p": str(creator)},
        )
    ).scalar_one()
    await _member(conn, league_id, creator)
    return league_id


async def _member(conn: AsyncConnection, league_id: uuid.UUID, player_id: uuid.UUID) -> None:
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


async def _snapshot(
    conn: AsyncConnection,
    player_id: uuid.UUID,
    league_id: uuid.UUID,
    points: int,
    rank: int,
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
        {
            "p": str(player_id),
            "l": str(league_id),
            "pts": points,
            "rank": rank,
            "t": datetime(2026, 6, 20, 18, 0, 0),
        },
    )


@pytest.mark.asyncio
async def test_cross_league_summary_db_three_leagues(db_conn: AsyncConnection) -> None:
    """Acceptance #1: average rank across three real leagues with varying ranks."""
    caller = await _profile(db_conn, "summary_caller")
    # Two filler members per league so each clears the 3-member floor.
    fillers = [await _profile(db_conn, f"filler_{i}") for i in range(2)]

    ranks = {"sum-a": 2, "sum-b": 1, "sum-c": 3}
    league_ids: dict[str, uuid.UUID] = {}
    for slug, rank in ranks.items():
        lid = await _league(db_conn, slug, caller)
        for f in fillers:
            await _member(db_conn, lid, f)
        await _snapshot(db_conn, caller, lid, points=100, rank=rank)
        league_ids[slug] = lid

    session = AsyncSession(bind=db_conn, expire_on_commit=False)

    def _caller() -> MagicMock:
        p = MagicMock(spec=Profile)
        p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
        p.id = caller
        return p

    app.dependency_overrides[get_db] = _db_with(session)
    app.dependency_overrides[get_current_player] = _caller
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/me/cross-league-summary")
    finally:
        app.dependency_overrides.clear()
        await session.close()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["leagues_count"] == 3
    assert data["total_points"] == 100
    assert data["avg_rank"] == 2.0  # (2 + 1 + 3) / 3
    per = {pl["slug"]: pl for pl in data["per_league"]}
    assert per["sum-a"]["rank"] == 2
    assert per["sum-b"]["rank"] == 1
    assert per["sum-c"]["rank"] == 3
    assert all(pl["member_count"] == 3 for pl in data["per_league"])


@pytest.mark.asyncio
async def test_cross_league_summary_db_excludes_solo_league(db_conn: AsyncConnection) -> None:
    """A solo league the caller is in is listed but excluded from the average."""
    caller = await _profile(db_conn, "solo_caller")
    fillers = [await _profile(db_conn, f"solo_filler_{i}") for i in range(2)]

    big = await _league(db_conn, "solo-big", caller)
    for f in fillers:
        await _member(db_conn, big, f)
    await _snapshot(db_conn, caller, big, points=60, rank=3)

    solo = await _league(db_conn, "solo-only", caller)  # caller is the only member
    await _snapshot(db_conn, caller, solo, points=60, rank=1)

    session = AsyncSession(bind=db_conn, expire_on_commit=False)

    def _caller() -> MagicMock:
        p = MagicMock(spec=Profile)
        p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
        p.id = caller
        return p

    app.dependency_overrides[get_db] = _db_with(session)
    app.dependency_overrides[get_current_player] = _caller
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/me/cross-league-summary")
    finally:
        app.dependency_overrides.clear()
        await session.close()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["leagues_count"] == 2
    assert data["avg_rank"] == 3.0  # only the 3-member league counts
    per = {pl["slug"]: pl for pl in data["per_league"]}
    assert per["solo-only"]["member_count"] == 1
    assert per["solo-only"]["rank"] == 1


# ---------------------------------------------------------------------------
# rank_delta: U16.3 acceptance criteria
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rank_delta_moved_up() -> None:
    """Two snapshots: prior rank 5, latest rank 3 → delta = +2 (positive = moved up)."""
    lg = uuid.uuid4()
    memberships = [SimpleNamespace(id=lg, slug="up", name="Up")]
    counts = [SimpleNamespace(league_id=lg, member_count=5)]
    snapshots = [
        # rn=1 (latest): rank 3
        SimpleNamespace(league_id=lg, rank=3, total_points=50, triggered_by_match_id=None),
        # rn=2 (prior): rank 5
        SimpleNamespace(league_id=lg, rank=5, total_points=40, triggered_by_match_id=None),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    entry = data["per_league"][0]
    assert entry["rank"] == 3
    assert entry["rank_delta"] == 2  # prior(5) - latest(3) = +2


@pytest.mark.asyncio
async def test_rank_delta_moved_down() -> None:
    """Two snapshots: prior rank 2, latest rank 4 → delta = -2 (negative = slipped)."""
    lg = uuid.uuid4()
    memberships = [SimpleNamespace(id=lg, slug="down", name="Down")]
    counts = [SimpleNamespace(league_id=lg, member_count=5)]
    snapshots = [
        SimpleNamespace(league_id=lg, rank=4, total_points=50, triggered_by_match_id=None),
        SimpleNamespace(league_id=lg, rank=2, total_points=40, triggered_by_match_id=None),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    assert data["per_league"][0]["rank_delta"] == -2


@pytest.mark.asyncio
async def test_rank_delta_null_on_single_snapshot() -> None:
    """One snapshot → rank_delta is null (not enough history)."""
    lg = uuid.uuid4()
    memberships = [SimpleNamespace(id=lg, slug="new", name="New")]
    counts = [SimpleNamespace(league_id=lg, member_count=5)]
    snapshots = [
        SimpleNamespace(league_id=lg, rank=2, total_points=30, triggered_by_match_id=None),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    assert data["per_league"][0]["rank_delta"] is None


@pytest.mark.asyncio
async def test_rank_delta_zero_same_rank() -> None:
    """Same rank in both snapshots → delta = 0."""
    lg = uuid.uuid4()
    memberships = [SimpleNamespace(id=lg, slug="same", name="Same")]
    counts = [SimpleNamespace(league_id=lg, member_count=5)]
    snapshots = [
        SimpleNamespace(league_id=lg, rank=3, total_points=50, triggered_by_match_id=None),
        SimpleNamespace(league_id=lg, rank=3, total_points=40, triggered_by_match_id=None),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    assert data["per_league"][0]["rank_delta"] == 0


@pytest.mark.asyncio
async def test_rank_delta_triggered_by_match_id_carried() -> None:
    """triggered_by_match_id from the latest snapshot is surfaced in per_league."""
    lg = uuid.uuid4()
    match_id = uuid.uuid4()
    memberships = [SimpleNamespace(id=lg, slug="m", name="M")]
    counts = [SimpleNamespace(league_id=lg, member_count=5)]
    snapshots = [
        SimpleNamespace(league_id=lg, rank=2, total_points=50, triggered_by_match_id=match_id),
        SimpleNamespace(league_id=lg, rank=4, total_points=40, triggered_by_match_id=uuid.uuid4()),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    entry = data["per_league"][0]
    assert entry["triggered_by_match_id"] == str(match_id)
    assert entry["rank_delta"] == 2


@pytest.mark.asyncio
async def test_rank_delta_avg_rank_still_present() -> None:
    """avg_rank is still present in the response (back-compat)."""
    lg = uuid.uuid4()
    memberships = [SimpleNamespace(id=lg, slug="compat", name="Compat")]
    counts = [SimpleNamespace(league_id=lg, member_count=5)]
    snapshots = [
        SimpleNamespace(league_id=lg, rank=2, total_points=80, triggered_by_match_id=None),
        SimpleNamespace(league_id=lg, rank=3, total_points=60, triggered_by_match_id=None),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    assert "avg_rank" in data
    assert data["avg_rank"] == 2.0


@pytest.mark.asyncio
async def test_rank_delta_deterministic_two_leagues() -> None:
    """Delta is computed independently per league with correct rn ordering."""
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    memberships = [
        SimpleNamespace(id=l1, slug="alpha", name="Alpha"),
        SimpleNamespace(id=l2, slug="beta", name="Beta"),
    ]
    counts = [
        SimpleNamespace(league_id=l1, member_count=5),
        SimpleNamespace(league_id=l2, member_count=4),
    ]
    # l1: moved up 2 (5→3); l2: single snapshot → null
    snapshots = [
        SimpleNamespace(league_id=l1, rank=3, total_points=60, triggered_by_match_id=None),
        SimpleNamespace(league_id=l1, rank=5, total_points=50, triggered_by_match_id=None),
        SimpleNamespace(league_id=l2, rank=1, total_points=60, triggered_by_match_id=None),
    ]
    data = await _get_summary(_mock_db_for(memberships, counts, snapshots))
    per = {pl["slug"]: pl for pl in data["per_league"]}
    assert per["alpha"]["rank_delta"] == 2
    assert per["beta"]["rank_delta"] is None
